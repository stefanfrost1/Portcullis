"""
Shared Docker exception → HTTPException mapper.

Import and use `handle_docker_exc` in all Docker routers to get consistent
HTTP status codes instead of always returning 500 for Docker API errors.
"""

from fastapi import HTTPException, status
from docker.errors import DockerException, NotFound, ImageNotFound, APIError


def handle_docker_exc(exc: DockerException, resource_id: str = "") -> HTTPException:
    """
    Map a docker-py exception to a semantically correct HTTPException.

    - NotFound / ImageNotFound  → 404
    - APIError with conflict     → 409 (container already started/stopped, name conflict)
    - APIError with not running  → 409 (cannot pause a stopped container, etc.)
    - Everything else            → 500
    """
    if isinstance(exc, (NotFound, ImageNotFound)):
        detail = str(exc) or (f"Resource '{resource_id}' not found" if resource_id else "Not found")
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

    if isinstance(exc, APIError):
        msg = str(exc).lower()
        if "conflict" in msg or "already" in msg:
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        if "not running" in msg or "is not paused" in msg or "cannot" in msg:
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
