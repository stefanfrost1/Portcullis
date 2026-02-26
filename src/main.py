"""
MyEngineAPI — Docker management bridge service.

Provides a REST + WebSocket API for the UI to interact with the Docker
daemon without the UI container needing direct socket access.

Base path: /api/v1
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.routers import containers, logs, images, networks, volumes, system

API_PREFIX = "/api/v1"

app = FastAPI(
    title="MyEngineAPI — Docker Bridge",
    description=(
        "Exposes Docker daemon capabilities over HTTP/WebSocket so that the UI "
        "can display container status, stream logs, search logs, and manage "
        "containers without direct Docker socket access."
    ),
    version="1.0.0",
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
app.include_router(logs.router, prefix=API_PREFIX)       # /api/v1/containers/{id}/logs/…
app.include_router(images.router, prefix=API_PREFIX)
app.include_router(networks.router, prefix=API_PREFIX)
app.include_router(volumes.router, prefix=API_PREFIX)
app.include_router(system.router, prefix=API_PREFIX)


# ---------------------------------------------------------------------------
# Root redirect to docs
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{API_PREFIX}/docs")
