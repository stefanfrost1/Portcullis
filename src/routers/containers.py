import logging

from fastapi import APIRouter, Query, status
from docker.errors import DockerException

from src.models.schemas import (
    APIResponse,
    ContainerDetail,
    ContainerStats,
    ContainerSummary,
)
from src.routers._docker_errors import handle_docker_exc
from src.services import docker_service as ds

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/containers", tags=["Containers"])


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="List containers",
    description="Return all containers. Pass `running_only=true` to limit to running ones.",
    response_model=APIResponse,
)
def list_containers(
    running_only: bool = Query(False, description="When true, return only running containers"),
):
    try:
        data = ds.list_containers(all_containers=not running_only)
        return APIResponse(data=data)
    except DockerException as exc:
        raise handle_docker_exc(exc)


# ---------------------------------------------------------------------------
# Batch stats  (must be declared before /{container_id} to avoid ambiguity)
# ---------------------------------------------------------------------------

@router.get(
    "/stats/all",
    summary="Resource stats for ALL running containers (parallel fetch)",
    description=(
        "Fetches CPU %, memory, network I/O, and block I/O for every running "
        "container in parallel using a thread pool. "
        "Containers that fail or exceed the per-container timeout appear in "
        "the `errors` list rather than crashing the whole call."
    ),
    response_model=APIResponse,
)
def all_container_stats(
    timeout: float = Query(5.0, ge=1.0, le=30.0, description="Per-container fetch timeout in seconds"),
    max_workers: int = Query(20, ge=1, le=50),
):
    try:
        return APIResponse(data=ds.get_all_container_stats(timeout_seconds=timeout, max_workers=max_workers))
    except DockerException as exc:
        raise handle_docker_exc(exc)


# ---------------------------------------------------------------------------
# Compose project groups
# ---------------------------------------------------------------------------

@router.get(
    "/groups",
    summary="Containers grouped by Compose project",
    description=(
        "Groups all containers (running and stopped) by the "
        "`com.docker.compose.project` label. Returns per-project counts "
        "and a list of services. Containers without a compose label are excluded."
    ),
    response_model=APIResponse,
)
def compose_groups():
    try:
        return APIResponse(data=ds.get_compose_groups())
    except DockerException as exc:
        raise handle_docker_exc(exc)


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

@router.get(
    "/{container_id}",
    summary="Inspect container",
    response_model=APIResponse,
)
def get_container(container_id: str):
    try:
        return APIResponse(data=ds.get_container(container_id))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get(
    "/{container_id}/stats",
    summary="Container resource usage statistics",
    description="CPU %, memory, network I/O, block I/O and PID count (single snapshot).",
    response_model=APIResponse,
)
def container_stats(container_id: str):
    try:
        return APIResponse(data=ds.get_container_stats(container_id))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------

@router.post(
    "/{container_id}/start",
    summary="Start a container",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
)
def start_container(container_id: str):
    logger.info("Starting container %s", container_id)
    try:
        return APIResponse(data=ds.start_container(container_id))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


@router.post(
    "/{container_id}/stop",
    summary="Stop a container",
    response_model=APIResponse,
)
def stop_container(
    container_id: str,
    timeout: int = Query(10, description="Seconds to wait before killing"),
):
    logger.info("Stopping container %s", container_id)
    try:
        return APIResponse(data=ds.stop_container(container_id, timeout=timeout))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


@router.post(
    "/{container_id}/restart",
    summary="Restart a container",
    response_model=APIResponse,
)
def restart_container(
    container_id: str,
    timeout: int = Query(10, description="Seconds to wait before killing"),
):
    try:
        return APIResponse(data=ds.restart_container(container_id, timeout=timeout))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


@router.post(
    "/{container_id}/pause",
    summary="Pause a running container",
    response_model=APIResponse,
)
def pause_container(container_id: str):
    try:
        return APIResponse(data=ds.pause_container(container_id))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


@router.post(
    "/{container_id}/unpause",
    summary="Unpause a paused container",
    response_model=APIResponse,
)
def unpause_container(container_id: str):
    try:
        return APIResponse(data=ds.unpause_container(container_id))
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

@router.delete(
    "/{container_id}",
    summary="Remove a container",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
)
def remove_container(
    container_id: str,
    force: bool = Query(False, description="Force removal of a running container"),
    remove_volumes: bool = Query(False, alias="v", description="Remove associated anonymous volumes"),
):
    logger.info("Removing container %s (force=%s, volumes=%s)", container_id, force, remove_volumes)
    try:
        ds.remove_container(container_id, force=force, remove_volumes=remove_volumes)
        return APIResponse(data={"removed": container_id})
    except DockerException as exc:
        raise handle_docker_exc(exc, container_id)
