"""
Environment overview — single-call snapshot for monitoring dashboards.

  GET  /overview    — Docker + Redis high-level stats in one response

Partial-failure design: if one subsystem is unreachable the other's data is
still returned. HTTP 200 is always returned; check the `error` field in each
sub-section to detect individual failures.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from src.models.schemas import APIResponse
from src.services import docker_service as ds
from src.services import redis_service as rs

router = APIRouter(tags=["Overview"])


@router.get(
    "/overview",
    summary="Full environment snapshot — Docker + Redis in one call",
    description=(
        "Returns a combined high-level snapshot of the Docker environment and Redis "
        "instance without requiring multiple round-trips from the UI.\n\n"
        "**Docker section** includes: running / stopped / paused container counts, "
        "total images, volumes, Compose project count, and disk usage.\n\n"
        "**Redis section** includes: connected clients, used memory, keyspace key count, "
        "ops/sec, hit rate, and top queue depths (up to `queue_max_keys` scanned).\n\n"
        "If a subsystem is unavailable the corresponding section contains "
        "`{\"status\": \"error\", \"detail\": \"...\"}` while the other section is "
        "still populated. HTTP status is always **200**."
    ),
    response_model=APIResponse,
)
def overview(
    redis_db: int = Query(0, ge=0, le=15, description="Redis DB index to report on"),
    queue_pattern: str = Query("*", description="Key pattern for queue scan"),
    queue_max_keys: int = Query(200, ge=1, le=2000, description="Max keys to scan for queue depth"),
):
    docker_data: dict
    redis_data: dict

    try:
        docker_data = ds.get_docker_overview()
    except Exception as exc:
        docker_data = {"status": "error", "detail": str(exc)}

    try:
        redis_overview = rs.get_redis_overview(db=redis_db)
        # Append top queues to the overview
        try:
            queues = rs.get_queues(pattern=queue_pattern, max_keys=queue_max_keys, db=redis_db)
            top_queues = queues[:10]  # top 10 by depth (already sorted desc)
        except Exception:
            top_queues = []
        redis_data = {**redis_overview, "top_queues": top_queues}
    except Exception as exc:
        redis_data = {"status": "error", "detail": str(exc)}

    return APIResponse(data={
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "docker": docker_data,
        "redis": redis_data,
    })
