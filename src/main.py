"""
Portcullis — Docker + Redis management bridge service.

Provides a REST + WebSocket API for the UI to interact with:
  - The Docker daemon (containers, images, networks, volumes, logs)
  - Redis (key browser, server ops, pub/sub, monitor, analysis)

Neither the Docker socket nor Redis is exposed directly to the UI.

Base path: /api/v1
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.routers import containers, logs, images, networks, volumes, system
from src.routers import redis_keys, redis_server, redis_queues, overview
from src.services import docker_service as ds
from src.services import redis_service as rs

API_PREFIX = "/api/v1"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("portcullis")

# Quieten noisy third-party loggers
logging.getLogger("docker").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Lifespan — startup validation + graceful shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warn if external services unreachable (don't block startup)
    logger.info("Portcullis starting up…")
    try:
        info = ds.get_system_info()
        logger.info("Docker daemon OK (version %s)", info.get("docker_version", "?"))
    except Exception as exc:
        logger.warning("Docker daemon unavailable at startup — Docker endpoints will return 503: %s", exc)

    try:
        rs.get_info("server")
        logger.info("Redis OK")
    except Exception as exc:
        logger.warning("Redis unavailable at startup — Redis endpoints will return 503: %s", exc)

    yield

    # Shutdown
    logger.info("Portcullis shutting down…")
    ds.close_docker_client()
    rs.close_all_pools()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Portcullis — Docker & Redis Bridge",
    description=(
        "Shields the UI from direct Docker socket and Redis access. "
        "Exposes container management, log streaming, image/network/volume ops, "
        "and a full Redis operations API (key browser, server info, pub/sub, "
        "MONITOR stream, keyspace analysis, slow log, memory stats, and more). "
        "Includes a single-call `/overview` endpoint for monitoring dashboards "
        "and queue-depth monitoring for List and Stream keys."
    ),
    version="3.1.0",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
_wildcard = "*" in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _wildcard,   # credentials=True is incompatible with wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ---------------------------------------------------------------------------
# Request ID tracing
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


# ---------------------------------------------------------------------------
# Request logging
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - t0) * 1000)
    req_id = response.headers.get("X-Request-ID", "-")
    logger.info(
        "%s %s → %s  (%dms)  req=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        req_id,
    )
    return response


# ---------------------------------------------------------------------------
# API key authentication (opt-in)
# ---------------------------------------------------------------------------

_AUTH_EXEMPT_PREFIXES = (
    f"{API_PREFIX}/docs",
    f"{API_PREFIX}/redoc",
    f"{API_PREFIX}/openapi.json",
    f"{API_PREFIX}/health",
    "/",
)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if not settings.API_KEY_ENABLED:
        return await call_next(request)

    path = request.url.path
    if any(path == p or path.startswith(p + "/") for p in _AUTH_EXEMPT_PREFIXES):
        return await call_next(request)

    provided = request.headers.get("X-API-Key", "")
    if not provided or provided != settings.API_KEY:
        return JSONResponse(
            status_code=401,
            content={"data": None, "error": {"code": "UNAUTHORIZED",
                                              "message": "Missing or invalid X-API-Key header"}},
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Global error handler — log internally, never expose stack traces to clients
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    req_id = request.headers.get("X-Request-ID", "-")
    logger.error(
        "Unhandled exception on %s %s  req=%s",
        request.method, request.url.path, req_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"data": None, "error": {"code": "INTERNAL_ERROR",
                                          "message": "An internal error occurred"}},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(containers.router, prefix=API_PREFIX)
app.include_router(logs.router, prefix=API_PREFIX)        # /api/v1/containers/{id}/logs/…
app.include_router(logs.global_router, prefix=API_PREFIX) # /api/v1/logs/search
app.include_router(images.router, prefix=API_PREFIX)
app.include_router(networks.router, prefix=API_PREFIX)
app.include_router(volumes.router, prefix=API_PREFIX)
app.include_router(system.router, prefix=API_PREFIX)

# Redis routers — /api/v1/redis/…
app.include_router(redis_keys.router, prefix=API_PREFIX)    # key browser + type operations
app.include_router(redis_server.router, prefix=API_PREFIX)  # server ops, monitoring, analysis
app.include_router(redis_queues.router, prefix=API_PREFIX)  # queue depth monitoring

# Aggregate overview — /api/v1/overview
app.include_router(overview.router, prefix=API_PREFIX)


# ---------------------------------------------------------------------------
# Root redirect to docs
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{API_PREFIX}/docs")
