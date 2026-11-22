"""
Environment overview — single-call snapshot for monitoring dashboards.

  GET  /overview    — Redis high-level stats + top queue depths in one response
  GET  /health      — Service health check (can the service reach Redis?)

HTTP 200 is always returned from /overview; check the `status` field in the
`redis` section to detect failures.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import APIResponse
from src.services import redis_service as rs

router = APIRouter(tags=["Overview"])


@router.get(
    "/overview",
    summary="Environment snapshot — Redis stats and top queues in one call",
    description=(
        "Returns a high-level snapshot of the Redis instance without requiring "
        "multiple round-trips from the UI.\n\n"
        "**Redis section** includes: connected clients, used memory, keyspace key count, "
        "ops/sec, hit rate, and top queue depths (up to `queue_max_keys` scanned).\n\n"
        "If Redis is unavailable the section contains "
        "`{\"status\": \"error\", \"detail\": \"...\"}`. HTTP status is always **200**."
    ),
    response_model=APIResponse,
)
def overview(
    redis_db: int = Query(0, ge=0, le=15, description="Redis DB index to report on"),
    queue_pattern: str = Query("*", description="Key pattern for queue scan"),
    queue_max_keys: int = Query(200, ge=1, le=2000, description="Max keys to scan for queue depth"),
):
    redis_data: dict

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
        "redis": redis_data,
    })


@router.get(
    "/health",
    summary="Health check",
    description="Returns 200 if the service can connect to Redis, 503 otherwise.",
    response_model=APIResponse,
)
def health():
    try:
        rs.get_client().ping()
        return APIResponse(data={"status": "ok"})
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "detail": str(exc)},
        )
