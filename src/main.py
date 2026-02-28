"""
MyEngineAPI — Docker + Redis management bridge service.

Provides a REST + WebSocket API for the UI to interact with:
  - The Docker daemon (containers, images, networks, volumes, logs)
  - Redis (key browser, server ops, pub/sub, monitor, analysis)

Neither the Docker socket nor Redis is exposed directly to the UI.

Base path: /api/v1
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.routers import containers, logs, images, networks, volumes, system
from src.routers import redis_keys, redis_server, redis_queues, overview

API_PREFIX = "/api/v1"

app = FastAPI(
    title="MyEngineAPI — Docker & Redis Bridge",
    description=(
        "Shields the UI from direct Docker socket and Redis access. "
        "Exposes container management, log streaming, image/network/volume ops, "
        "and a full Redis operations API (key browser, server info, pub/sub, "
        "MONITOR stream, keyspace analysis, slow log, memory stats, and more). "
        "Includes a single-call `/overview` endpoint for monitoring dashboards "
        "and queue-depth monitoring for List and Stream keys."
    ),
    version="3.0.0",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json",
)

# ---------------------------------------------------------------------------
# CORS — allow the UI origin; tighten in production
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Override via CORS_ORIGINS env var if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"data": None, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(containers.router, prefix=API_PREFIX)
app.include_router(logs.router, prefix=API_PREFIX)        # /api/v1/containers/{id}/logs/…
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
