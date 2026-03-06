"""
Log endpoints:

  GET  /containers/{id}/logs          — fetch up to 2000 tail lines (plain or with timestamps)
  GET  /containers/{id}/logs/search   — egrep-style regex search within a single container
  WS   /containers/{id}/logs/stream   — WebSocket live log tail
  GET  /containers/{id}/logs/stream   — SSE live log tail (alternative to WebSocket)
  GET  /logs/search                   — egrep-style regex search across ALL containers (global)
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from docker.errors import NotFound, APIError, DockerException

from src.models.schemas import APIResponse
from src.routers._docker_errors import handle_docker_exc
from src.services import docker_service as ds

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/containers", tags=["Logs"])
global_router = APIRouter(prefix="/logs", tags=["Logs"])


# ---------------------------------------------------------------------------
# Fetch logs (HTTP)
# ---------------------------------------------------------------------------

@router.get(
    "/{container_id}/logs",
    summary="Fetch container logs",
    description=(
        "Return the last `tail` lines of stdout/stderr. "
        "Use `since` / `until` to narrow the time window (Unix timestamp or relative like `1h`). "
        "Pass `timestamps=true` to include Docker's log timestamps."
    ),
    response_model=APIResponse,
)
def get_logs(
    container_id: str,
    tail: int = Query(2000, ge=1, le=2000, description="Number of lines from the end (max 2000)"),
    since: Optional[str] = Query(None, description="Show logs since timestamp or relative (e.g. 1h)"),
    until: Optional[str] = Query(None, description="Show logs until timestamp"),
    timestamps: bool = Query(False, description="Include Docker timestamps in each line"),
):
    try:
        lines = ds.get_logs(
            container_id,
            tail=tail,
            since=since,
            until=until,
            timestamps=timestamps,
        )
        return APIResponse(data={"container_id": container_id, "lines": lines, "count": len(lines)})
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


# ---------------------------------------------------------------------------
# Search logs (egrep-style)
# ---------------------------------------------------------------------------

@router.get(
    "/{container_id}/logs/search",
    summary="Search container logs with a regex pattern (egrep-style)",
    description=(
        "Filter log lines matching `pattern` (Python extended regex / egrep compatible). "
        "Searches through the last `tail` lines. Returns at most `max_results` lines (hard cap 2000). "
        "Pass `case_insensitive=true` for case-insensitive matching."
    ),
    response_model=APIResponse,
)
def search_logs(
    container_id: str,
    pattern: str = Query(..., description="Extended regex pattern (egrep-compatible)"),
    tail: int = Query(2000, ge=1, le=2000, description="Lines to search through (max 2000)"),
    max_results: int = Query(200, ge=1, le=2000, description="Maximum matched lines to return"),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    timestamps: bool = Query(False),
    case_insensitive: bool = Query(False),
):
    try:
        result = ds.search_logs(
            container_id,
            pattern=pattern,
            tail=tail,
            max_results=max_results,
            since=since,
            until=until,
            timestamps=timestamps,
            case_insensitive=case_insensitive,
        )
        return APIResponse(data=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


# ---------------------------------------------------------------------------
# WebSocket live stream
# ---------------------------------------------------------------------------

@router.websocket("/{container_id}/logs/stream")
async def stream_logs_ws(
    websocket: WebSocket,
    container_id: str,
    tail: int = Query(50, ge=0, le=1000),
    timestamps: bool = Query(False),
    since: Optional[str] = Query(None),
):
    """
    WebSocket endpoint that streams live log output.

    Connect via: ws://<host>/api/v1/containers/{id}/logs/stream

    Each message is a JSON object:
        {"line": "<log text>"}

    The server sends {"event": "connected"} on open and {"event": "done"} if
    the container stops producing logs.
    """
    await websocket.accept()
    try:
        await websocket.send_text(json.dumps({"event": "connected", "container_id": container_id}))
        loop = asyncio.get_event_loop()

        gen = ds.stream_logs(container_id, tail=tail, since=since, timestamps=timestamps)

        def next_line():
            try:
                return next(gen)
            except StopIteration:
                return None

        while True:
            try:
                line = await asyncio.wait_for(
                    loop.run_in_executor(None, next_line), timeout=30.0
                )
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"event": "heartbeat"}))
                continue
            if line is None:
                await websocket.send_text(json.dumps({"event": "done"}))
                break
            if line.strip():
                await websocket.send_text(json.dumps({"line": line}))
    except WebSocketDisconnect:
        pass
    except DockerException as exc:
        err_http = handle_docker_exc(exc, container_id)
        try:
            await websocket.send_text(json.dumps({"event": "error", "detail": err_http.detail}))
        except Exception:
            pass
        await websocket.close()
    except Exception as exc:
        try:
            await websocket.send_text(json.dumps({"event": "error", "detail": str(exc)}))
        except Exception:
            pass
        await websocket.close()


# ---------------------------------------------------------------------------
# SSE live stream (alternative to WebSocket for simpler clients)
# ---------------------------------------------------------------------------

@router.get(
    "/{container_id}/logs/stream",
    summary="Stream container logs via Server-Sent Events",
    description=(
        "Opens a long-lived HTTP connection that pushes log lines as SSE events. "
        "Each event data field is a JSON string: `{\"line\": \"...\"}`. "
        "Connect via EventSource in the browser."
    ),
    response_class=StreamingResponse,
)
def stream_logs_sse(
    container_id: str,
    tail: int = Query(50, ge=0, le=1000),
    timestamps: bool = Query(False),
    since: Optional[str] = Query(None),
):
    def event_generator():
        try:
            for line in ds.stream_logs(container_id, tail=tail, since=since, timestamps=timestamps):
                if line.strip():
                    payload = json.dumps({"line": line})
                    yield f"data: {payload}\n\n"
        except NotFound:
            yield f"data: {json.dumps({'event': 'error', 'detail': 'Container not found'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'event': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Global log search (all containers, egrep-style)
# ---------------------------------------------------------------------------

@global_router.get(
    "/search",
    summary="Search logs across all containers (global egrep-style)",
    description=(
        "Fetch the last `tail` lines from every container and filter them with `pattern` "
        "(Python extended regex / egrep compatible). "
        "Containers are searched in parallel on the server; only the matching lines are returned. "
        "By default only running containers are searched; pass `running_only=false` to include stopped ones. "
        "Results are grouped by container and sorted by container name."
    ),
    response_model=APIResponse,
)
def global_search_logs(
    pattern: str = Query(..., description="Extended regex pattern (egrep-compatible)"),
    tail: int = Query(2000, ge=1, le=2000, description="Lines to search per container (max 2000)"),
    max_results_per_container: int = Query(200, ge=1, le=2000, description="Max matched lines returned per container"),
    since: Optional[str] = Query(None, description="Show logs since timestamp or relative (e.g. 1h)"),
    until: Optional[str] = Query(None, description="Show logs until timestamp"),
    timestamps: bool = Query(False, description="Include Docker timestamps in matched lines"),
    case_insensitive: bool = Query(False, description="Case-insensitive matching"),
    running_only: bool = Query(True, description="Only search running containers (false includes stopped)"),
):
    try:
        result = ds.global_search_logs(
            pattern=pattern,
            tail=tail,
            max_results_per_container=max_results_per_container,
            since=since,
            until=until,
            timestamps=timestamps,
            case_insensitive=case_insensitive,
            running_only=running_only,
        )
        return APIResponse(data=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except DockerException as exc:
        raise handle_docker_exc(exc, "global")
