"""
Redis queue-depth monitoring endpoints.

  GET  /redis/queues          — scan for List + Stream keys; return depth sorted desc
  GET  /redis/queues/{key}    — deep-dive: List depth + sample, or Stream groups + pending

Compatible with Redis 6.0+. Stream consumer-group `lag` field (Redis 7.0+) is returned
as null when absent. PaaS instances that disable OBJECT/MEMORY commands still work.
"""

from fastapi import APIRouter, HTTPException, Query
from redis.exceptions import RedisError

from src.models.schemas import APIResponse
from src.services import redis_service as rs

router = APIRouter(prefix="/redis/queues", tags=["Redis — Queues"])


def _err(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


@router.get(
    "",
    summary="Queue depth overview — all List and Stream keys, sorted by depth",
    description=(
        "Scans up to `max_keys` keys matching `pattern` and filters to those of "
        "type `list` or `stream`. Returns depth (LLEN / XLEN) and, for streams, "
        "consumer-group count and total pending messages. Results sorted descending "
        "by depth so the busiest queues appear first.\n\n"
        "Uses SCAN + pipeline TYPE check (not SCAN TYPE filter) so it is compatible "
        "with Redis 6.0 and PaaS-managed instances."
    ),
    response_model=APIResponse,
)
def list_queues(
    pattern: str = Query("*", description="Key glob pattern to scan"),
    max_keys: int = Query(500, ge=1, le=5000, description="Maximum keys to inspect"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.get_queues(pattern=pattern, max_keys=max_keys, db=db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/{key:path}",
    summary="Queue detail — depth, sample messages, and consumer-group status",
    description=(
        "**List keys**: returns `length` and up to `sample_count` entries from the "
        "head of the list (LRANGE 0 sample_count-1).\n\n"
        "**Stream keys**: returns `length`, `XINFO GROUPS` (name, pending, last-delivered-id, "
        "lag — null on Redis < 7.0), per-group pending count via XPENDING summary form, "
        "and the age (seconds) of the oldest unacknowledged message derived from the "
        "stream entry ID timestamp."
    ),
    response_model=APIResponse,
)
def queue_detail(
    key: str,
    sample_count: int = Query(10, ge=1, le=100, description="Number of messages to sample (List only)"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.get_queue_detail(key=key, sample_count=sample_count, db=db))
    except RedisError as exc:
        raise _err(exc)
