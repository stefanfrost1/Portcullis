"""
Redis key-management endpoints.

URL design:
  GET  /redis/keys               — SCAN (paginated list)
  GET  /redis/keys/count         — DBSIZE
  POST /redis/keys/bulk-delete   — DEL multiple keys

  GET    /redis/key/{key}            — inspect key (type + value + metadata)
  POST   /redis/key/{key}            — create / overwrite key
  DELETE /redis/key/{key}            — DEL

  GET  /redis/key/{key}/ttl          — TTL + PTTL
  POST /redis/key/{key}/expire       — EXPIRE (or PERSIST when ttl <= 0)
  POST /redis/key/{key}/persist      — PERSIST
  GET  /redis/key/{key}/metadata     — type, encoding, refcount, idletime, memory
  GET  /redis/key/{key}/dump         — DUMP (base64)
  POST /redis/key/{key}/rename       — RENAME / RENAMENX
  POST /redis/key/{key}/copy         — COPY

  Hash  — /redis/key/{key}/hash[/{field}]
  List  — /redis/key/{key}/list[/push|pop|remove|{index}]
  Set   — /redis/key/{key}/set[/add|random|ismember|{member}]
  ZSet  — /redis/key/{key}/zset[/add|range-by-score|{member}/score]
  Stream— /redis/key/{key}/stream[/add|info|{entry_id}]

Note: keys containing "/" must be URL-encoded (%2F) by the client.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from redis.exceptions import RedisError, ResponseError

from src.models.redis_schemas import (
    RedisBulkDeleteRequest,
    RedisCopyRequest,
    RedisExpireRequest,
    RedisHashFieldRequest,
    RedisKeySetRequest,
    RedisListPushRequest,
    RedisListRemoveRequest,
    RedisListSetRequest,
    RedisRenameRequest,
    RedisSetAddRequest,
    RedisStreamAddRequest,
    RedisZSetAddRequest,
)
from src.models.schemas import APIResponse
from src.services import redis_service as rs

router = APIRouter(prefix="/redis", tags=["Redis — Keys"])


def _err(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


def _not_found(key: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Key '{key}' does not exist")


# ===========================================================================
# Key listing / scanning
# ===========================================================================

@router.get(
    "/keys",
    summary="Scan keys (cursor-based pagination)",
    description=(
        "SCAN the keyspace. Pass the returned `cursor` back in the next call "
        "until cursor is 0 (scan complete). Use `type` to filter by data type "
        "(requires Redis 6.0+). Each result includes key name, type, and TTL."
    ),
    response_model=APIResponse,
)
def scan_keys(
    cursor: int = Query(0, ge=0),
    pattern: str = Query("*"),
    count: int = Query(100, ge=1, le=5000, description="Hint for keys per batch"),
    key_type: Optional[str] = Query(None, alias="type", description="string|hash|list|set|zset|stream"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.scan_keys(cursor, pattern, count, key_type, db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/keys/count",
    summary="Count keys in database (DBSIZE)",
    response_model=APIResponse,
)
def count_keys(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data={"count": rs.count_keys(db), "db": db})
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/keys/bulk-delete",
    summary="Delete multiple keys (DEL)",
    response_model=APIResponse,
)
def bulk_delete(body: RedisBulkDeleteRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.delete_keys(body.keys, db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Individual key — CRUD + inspect
# ===========================================================================

@router.get(
    "/key/{key}",
    summary="Get key value and metadata",
    description=(
        "Auto-detects type and returns value. Large strings are truncated at 1 MB. "
        "Collections support `offset` + `count` pagination."
    ),
    response_model=APIResponse,
)
def get_key(
    key: str,
    db: int = Query(0, ge=0, le=15),
    offset: int = Query(0, ge=0),
    count: int = Query(200, ge=1, le=5000),
):
    try:
        data = rs.get_key(key, db=db, offset=offset, count=count)
        if data["type"] == "none":
            raise _not_found(key)
        return APIResponse(data=data)
    except HTTPException:
        raise
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/key/{key}",
    summary="Create or overwrite a key",
    description="Replaces the key entirely. Supports string, hash, list, set, zset.",
    response_model=APIResponse,
    status_code=status.HTTP_201_CREATED,
)
def set_key(key: str, body: RedisKeySetRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.set_key(key, body.type, body.value, body.ttl, db))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RedisError as exc:
        raise _err(exc)


@router.delete(
    "/key/{key}",
    summary="Delete a key (DEL)",
    response_model=APIResponse,
)
def delete_key(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        result = rs.delete_keys([key], db)
        if result["deleted"] == 0:
            raise _not_found(key)
        return APIResponse(data=result)
    except HTTPException:
        raise
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# TTL / expiry management
# ===========================================================================

@router.get("/key/{key}/ttl", summary="Get TTL and PTTL", response_model=APIResponse)
def key_ttl(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.get_key_ttl(key, db))
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/key/{key}/expire",
    summary="Set TTL (EXPIRE). Pass ttl <= 0 to call PERSIST.",
    response_model=APIResponse,
)
def key_expire(key: str, body: RedisExpireRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.expire_key(key, body.ttl, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/persist", summary="Remove TTL (PERSIST)", response_model=APIResponse)
def key_persist(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.persist_key(key, db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Key introspection
# ===========================================================================

@router.get(
    "/key/{key}/metadata",
    summary="Key metadata — type, encoding, refcount, idletime, memory",
    response_model=APIResponse,
)
def key_metadata(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.get_key_metadata(key, db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/key/{key}/dump",
    summary="DUMP key (binary serialisation, base64-encoded)",
    response_model=APIResponse,
)
def key_dump(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.dump_key(key, db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Key management — rename, copy
# ===========================================================================

@router.post("/key/{key}/rename", summary="Rename key (RENAME / RENAMENX)", response_model=APIResponse)
def key_rename(key: str, body: RedisRenameRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.rename_key(key, body.new_key, nx=body.nx, db=db))
    except ResponseError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/copy", summary="Copy key (COPY)", response_model=APIResponse)
def key_copy(key: str, body: RedisCopyRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.copy_key(
            key, body.destination,
            destination_db=body.destination_db,
            replace=body.replace,
            db=db,
        ))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Hash
# ===========================================================================

@router.get("/key/{key}/hash", summary="HGETALL", response_model=APIResponse)
def hash_getall(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data={"key": key, "fields": rs.hash_get_all(key, db)})
    except RedisError as exc:
        raise _err(exc)


@router.get("/key/{key}/hash/fields", summary="HKEYS — list field names", response_model=APIResponse)
def hash_fields(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data={"key": key, "fields": rs.hash_get_fields(key, db)})
    except RedisError as exc:
        raise _err(exc)


@router.get("/key/{key}/hash/{field}", summary="HGET field", response_model=APIResponse)
def hash_get(key: str, field: str, db: int = Query(0, ge=0, le=15)):
    try:
        value = rs.hash_get_field(key, field, db)
        if value is None:
            raise HTTPException(status_code=404, detail=f"Field '{field}' not found in '{key}'")
        return APIResponse(data={"key": key, "field": field, "value": value})
    except HTTPException:
        raise
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/hash/{field}", summary="HSET field", response_model=APIResponse)
def hash_set(key: str, field: str, body: RedisHashFieldRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.hash_set_field(key, field, body.value, db))
    except RedisError as exc:
        raise _err(exc)


@router.delete("/key/{key}/hash/{field}", summary="HDEL field", response_model=APIResponse)
def hash_del(key: str, field: str, db: int = Query(0, ge=0, le=15)):
    try:
        result = rs.hash_del_field(key, field, db)
        if not result["deleted"]:
            raise HTTPException(status_code=404, detail=f"Field '{field}' not found")
        return APIResponse(data=result)
    except HTTPException:
        raise
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# List
# ===========================================================================

@router.get(
    "/key/{key}/list",
    summary="LRANGE — paginated list items",
    response_model=APIResponse,
)
def list_get(
    key: str,
    start: int = Query(0, ge=0),
    stop: int = Query(99, ge=0),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.list_get(key, start, stop, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/list/push", summary="LPUSH / RPUSH", response_model=APIResponse)
def list_push(key: str, body: RedisListPushRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.list_push(key, body.values, body.direction, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/list/pop", summary="LPOP / RPOP", response_model=APIResponse)
def list_pop(
    key: str,
    direction: str = Query("right", description="left | right"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.list_pop(key, direction, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/list/remove", summary="LREM — remove by value", response_model=APIResponse)
def list_remove(key: str, body: RedisListRemoveRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.list_remove(key, body.value, body.count, db))
    except RedisError as exc:
        raise _err(exc)


@router.put("/key/{key}/list/{index}", summary="LSET — set item at index", response_model=APIResponse)
def list_set(key: str, index: int, body: RedisListSetRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.list_set_index(key, index, body.value, db))
    except ResponseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Set
# ===========================================================================

@router.get("/key/{key}/set", summary="SMEMBERS", response_model=APIResponse)
def set_members(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data={"key": key, "members": rs.set_members(key, db)})
    except RedisError as exc:
        raise _err(exc)


@router.get("/key/{key}/set/random", summary="SRANDMEMBER", response_model=APIResponse)
def set_random(
    key: str,
    count: int = Query(1, ge=1),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data={"key": key, "members": rs.set_random(key, count, db)})
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/set/add", summary="SADD", response_model=APIResponse)
def set_add(key: str, body: RedisSetAddRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.set_add(key, body.members, db))
    except RedisError as exc:
        raise _err(exc)


@router.get("/key/{key}/set/{member}/ismember", summary="SISMEMBER", response_model=APIResponse)
def set_ismember(key: str, member: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.set_is_member(key, member, db))
    except RedisError as exc:
        raise _err(exc)


@router.delete("/key/{key}/set/{member}", summary="SREM", response_model=APIResponse)
def set_remove(key: str, member: str, db: int = Query(0, ge=0, le=15)):
    try:
        result = rs.set_remove(key, member, db)
        if not result["removed"]:
            raise HTTPException(status_code=404, detail=f"Member '{member}' not in set")
        return APIResponse(data=result)
    except HTTPException:
        raise
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Sorted Set
# ===========================================================================

@router.get(
    "/key/{key}/zset",
    summary="ZRANGE with scores (paginated)",
    response_model=APIResponse,
)
def zset_range(
    key: str,
    start: int = Query(0, ge=0),
    stop: int = Query(99, ge=0),
    reverse: bool = Query(False),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.zset_range(key, start, stop, reverse, db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/key/{key}/zset/range-by-score",
    summary="ZRANGEBYSCORE — filter by score range",
    response_model=APIResponse,
)
def zset_range_by_score(
    key: str,
    min: str = Query("-inf"),
    max: str = Query("+inf"),
    offset: int = Query(0, ge=0),
    count: int = Query(100, ge=1, le=5000),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.zset_range_by_score(key, min, max, offset, count, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/zset/add", summary="ZADD", response_model=APIResponse)
def zset_add(key: str, body: RedisZSetAddRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.zset_add(key, body.members, nx=body.nx, xx=body.xx, db=db))
    except RedisError as exc:
        raise _err(exc)


@router.get("/key/{key}/zset/{member}/score", summary="ZSCORE + ZRANK + ZREVRANK", response_model=APIResponse)
def zset_score(key: str, member: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.zset_score(key, member, db))
    except RedisError as exc:
        raise _err(exc)


@router.delete("/key/{key}/zset/{member}", summary="ZREM", response_model=APIResponse)
def zset_remove(key: str, member: str, db: int = Query(0, ge=0, le=15)):
    try:
        result = rs.zset_remove(key, member, db)
        if not result["removed"]:
            raise HTTPException(status_code=404, detail=f"Member '{member}' not in zset")
        return APIResponse(data=result)
    except HTTPException:
        raise
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Stream
# ===========================================================================

@router.get(
    "/key/{key}/stream",
    summary="XRANGE — paginated stream entries",
    response_model=APIResponse,
)
def stream_range(
    key: str,
    start: str = Query("-", description="Start entry ID or '-' for oldest"),
    end: str = Query("+", description="End entry ID or '+' for newest"),
    count: int = Query(100, ge=1, le=5000),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.stream_range(key, start, end, count, db))
    except RedisError as exc:
        raise _err(exc)


@router.get("/key/{key}/stream/info", summary="XINFO STREAM", response_model=APIResponse)
def stream_info(key: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.stream_info(key, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/key/{key}/stream/add", summary="XADD — append stream entry", response_model=APIResponse)
def stream_add(key: str, body: RedisStreamAddRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.stream_add(key, body.fields, body.entry_id, db))
    except RedisError as exc:
        raise _err(exc)


@router.delete("/key/{key}/stream/{entry_id}", summary="XDEL — remove stream entry", response_model=APIResponse)
def stream_delete(key: str, entry_id: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.stream_delete_entry(key, entry_id, db))
    except RedisError as exc:
        raise _err(exc)
