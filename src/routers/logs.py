"""
Log endpoints:

  GET  /containers/{id}/logs          — fetch N tail lines (plain or with timestamps)
  GET  /containers/{id}/logs/search   — egrep-style regex search, max 2000 lines returned
  WS   /containers/{id}/logs/stream   — WebSocket live log tail
  GET  /containers/{id}/logs/stream   — SSE live log tail (alternative to WebSocket)
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from docker.errors import NotFound, APIError

from src.models.schemas import APIResponse
from src.services import docker_service as ds

router = APIRouter(prefix="/containers", tags=["Logs"])


def _not_found(container_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Container '{container_id}' not found",
    )


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
    tail: int = Query(100, ge=1, le=10000, description="Number of lines from the end"),
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
    except NotFound:
        raise _not_found(container_id)
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
    tail: int = Query(5000, ge=1, le=100000, description="Lines to search through"),
    max_results: int = Query(2000, ge=1, le=2000, description="Maximum matched lines to return"),
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
    except NotFound:
        raise _not_found(container_id)
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
            line = await loop.run_in_executor(None, next_line)
            if line is None:
                await websocket.send_text(json.dumps({"event": "done"}))
                break
            if line.strip():
                await websocket.send_text(json.dumps({"line": line}))
    except WebSocketDisconnect:
        pass
    except NotFound:
        await websocket.send_text(
            json.dumps({"event": "error", "detail": f"Container '{container_id}' not found"})
        )
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
