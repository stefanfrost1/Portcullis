"""
Redis queue-depth monitoring endpoints.

  GET  /redis/queues          — scan for List + Stream keys; return depth sorted desc
  GET  /redis/queues/{key}    — deep-dive: List depth + sample, or Stream groups + pending
  GET  /redis/queues/match/{key}    — count entries whose JSON field equals a value
  POST /redis/queues/reorder/{key}  — 🔒 move those entries to head or tail, atomically
  POST /redis/queues/purge/{key}    — 🔒 delete those entries, atomically

Compatible with Redis 6.0+. Stream consumer-group `lag` field (Redis 7.0+) is returned
as null when absent. PaaS instances that disable OBJECT/MEMORY commands still work.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.exceptions import RedisError, ResponseError

from src.models.redis_schemas import RedisListSelectRequest
from src.models.schemas import APIResponse
from src.routers._auth import require_admin
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


# The three routes below take the key as a trailing path so that keys holding
# `:` and `/` work, and are registered before the catch-all detail route.

@router.get(
    "/match/{key:path}",
    summary="Count list entries whose JSON field equals a value",
    description=(
        "Read-only. Parses every entry of the list as JSON and matches those whose "
        "field at the dot-separated `path` equals any `value`. Returns the list "
        "length, the number matched, the first `sample` positions (0 = head, the "
        "next entry a head-consuming worker pops) and a sample of the matches."
    ),
    response_model=APIResponse,
)
def match_entries(
    key: str,
    path: str = Query(..., description="Dot path, e.g. targetData.sourceFilename"),
    value: list[str] = Query(..., description="Repeatable; match any"),
    sample: int = Query(20, ge=0, le=500),
    db: int = Query(0, ge=0, le=15),
):
    return _select(key, path, value, "count", sample, db)


@router.post(
    "/reorder/{key:path}",
    summary="Move every matching entry to the head or the tail — atomically",
    description=(
        "Moves all entries whose JSON field at `path` equals one of `values` to the "
        "head (`to=head`, processed next by LPOP/BLPOP consumers) or the tail. Order "
        "is kept among the moved entries and among the rest. Runs as one Lua script, "
        "so a consumer popping concurrently can never lose or double an entry."
    ),
    response_model=APIResponse,
)
def reorder_entries(
    key: str,
    body: RedisListSelectRequest,
    to: str = Query(..., pattern="^(head|tail)$"),
    db: int = Query(0, ge=0, le=15),
    _: None = Depends(require_admin),
):
    return _select(key, body.path, body.values, to, 0, db)


@router.post(
    "/purge/{key:path}",
    summary="Delete every matching entry — atomically — and return them",
    description=(
        "Deletes all entries whose JSON field at `path` equals one of `values`, in one "
        "Lua script. The removed entries are returned in `removed` so the caller can "
        "clean up whatever state they stood for."
    ),
    response_model=APIResponse,
)
def purge_entries(
    key: str,
    body: RedisListSelectRequest,
    db: int = Query(0, ge=0, le=15),
    _: None = Depends(require_admin),
):
    return _select(key, body.path, body.values, "purge", 0, db)


def _select(key, path, values, mode, sample, db):
    try:
        return APIResponse(data=rs.list_select(key, path, values, mode=mode, sample=sample, db=db))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ResponseError as exc:
        if "WRONGTYPE" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc))
        raise _err(exc)
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
