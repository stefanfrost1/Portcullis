"""
System-level endpoints:

  GET  /system/info    — Docker daemon info + version
  GET  /system/df      — Disk usage breakdown
  WS   /system/events  — Real-time Docker events stream
  GET  /health         — Health check (can the service reach Docker?)
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from docker.errors import APIError

from src.models.schemas import APIResponse
from src.services import docker_service as ds

router = APIRouter(tags=["System"])


@router.get("/system/info", summary="Docker daemon information", response_model=APIResponse)
def system_info():
    try:
        return APIResponse(data=ds.get_system_info())
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/system/df",
    summary="Docker disk usage",
    description="Images, containers, volumes, and build cache disk usage.",
    response_model=APIResponse,
)
def disk_usage():
    try:
        return APIResponse(data=ds.get_disk_usage())
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.websocket("/system/events")
async def system_events(
    websocket: WebSocket,
    since: Optional[str] = Query(None, description="Start timestamp (Unix or ISO)"),
    filters: Optional[str] = Query(
        None,
        description='JSON-encoded filter dict, e.g. {"type":["container"]}',
    ),
):
    """
    WebSocket stream of Docker daemon events.

    Each message is a JSON-encoded Docker event object, e.g.:
        {"Type": "container", "Action": "start", "Actor": {...}, "time": 1700000000}

    Connect via: ws://<host>/api/v1/system/events
    """
    await websocket.accept()
    try:
        filter_dict = json.loads(filters) if filters else None
        await websocket.send_text(json.dumps({"event": "connected"}))
        loop = asyncio.get_event_loop()

        gen = ds.stream_events(since=since, filters=filter_dict)

        def next_event():
            try:
                return next(gen)
            except StopIteration:
                return None

        while True:
            ev = await loop.run_in_executor(None, next_event)
            if ev is None:
                break
            await websocket.send_text(json.dumps(ev, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(json.dumps({"event": "error", "detail": str(exc)}))
        except Exception:
            pass
        await websocket.close()


@router.get(
    "/health",
    summary="Health check",
    description="Returns 200 if the service can connect to the Docker daemon.",
    response_model=APIResponse,
)
def health():
    try:
        info = ds.get_system_info()
        return APIResponse(
            data={
                "status": "ok",
                "docker_server_version": info["server_version"],
            }
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "detail": str(exc)},
        )
