"""
Redis service layer.

All functions return plain dicts/lists/primitives so routers can
serialise them with Pydantic without touching SDK objects.

Connection is configured via environment variables:
  REDIS_HOST      (default: redis)
  REDIS_PORT      (default: 6379)
  REDIS_PASSWORD  (default: none)
  REDIS_DB        (default: 0)    — used only as the fallback default db
"""

import base64
import os
import queue
import threading
from typing import Any, Generator, Optional

import redis
from redis.exceptions import RedisError

# ---------------------------------------------------------------------------
# Connection pools — one per (decoded | binary) × db index
# ---------------------------------------------------------------------------

_pools: dict[int, redis.ConnectionPool] = {}
_bin_pools: dict[int, redis.ConnectionPool] = {}

_REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
_REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
_REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None


def _pool(db: int) -> redis.ConnectionPool:
    if db not in _pools:
        _pools[db] = redis.ConnectionPool(
            host=_REDIS_HOST,
            port=_REDIS_PORT,
            password=_REDIS_PASSWORD,
            db=db,
            decode_responses=True,
            max_connections=20,
        )
    return _pools[db]


def _bin_pool(db: int) -> redis.ConnectionPool:
    """Binary client — for DUMP/RESTORE where decode_responses must be False."""
    if db not in _bin_pools:
        _bin_pools[db] = redis.ConnectionPool(
            host=_REDIS_HOST,
            port=_REDIS_PORT,
            password=_REDIS_PASSWORD,
            db=db,
            decode_responses=False,
            max_connections=5,
        )
    return _bin_pools[db]


def get_client(db: int = 0) -> redis.Redis:
    return redis.Redis(connection_pool=_pool(db))


def get_bin_client(db: int = 0) -> redis.Redis:
    return redis.Redis(connection_pool=_bin_pool(db))


# ---------------------------------------------------------------------------
# Key scanning / browsing
# ---------------------------------------------------------------------------

def scan_keys(
    cursor: int = 0,
    pattern: str = "*",
    count: int = 100,
    key_type: Optional[str] = None,
    db: int = 0,
) -> dict:
    """
    SCAN with optional TYPE filter (Redis 6.0+, falls back gracefully).
    Returns {keys: [{key, type, ttl}], cursor, count, pattern, db}.
    """
    r = get_client(db)
    kwargs: dict = {"cursor": cursor, "match": pattern, "count": count}
    if key_type:
        kwargs["_type"] = key_type

    try:
        next_cursor, keys = r.scan(**kwargs)
    except RedisError:
        kwargs.pop("_type", None)
        next_cursor, keys = r.scan(**kwargs)

    enriched = []
    if keys:
        pipe = r.pipeline(transaction=False)
        for k in keys:
            pipe.type(k)
            pipe.ttl(k)
        responses = pipe.execute(raise_on_error=False)
        for i, k in enumerate(keys):
            enriched.append({
                "key": k,
                "type": responses[i * 2] if not isinstance(responses[i * 2], Exception) else "unknown",
                "ttl": responses[i * 2 + 1] if not isinstance(responses[i * 2 + 1], Exception) else -1,
            })

    return {
        "keys": enriched,
        "cursor": next_cursor,
        "count": len(keys),
        "pattern": pattern,
        "db": db,
    }


def count_keys(db: int = 0) -> int:
    return get_client(db).dbsize()


# ---------------------------------------------------------------------------
# Key detail  (auto-detects type, paginates large collections)
# ---------------------------------------------------------------------------

_MAX_STRING_BYTES = 1024 * 1024   # 1 MB before truncation
_DEFAULT_PAGE = 200               # default items returned for collections


def get_key(
    key: str,
    db: int = 0,
    offset: int = 0,
    count: int = _DEFAULT_PAGE,
) -> dict:
    r = get_client(db)

    pipe = r.pipeline(transaction=False)
    pipe.type(key)
    pipe.ttl(key)
    pipe.object_encoding(key)
    pipe.memory_usage(key)
    responses = pipe.execute(raise_on_error=False)

    key_type = responses[0] if not isinstance(responses[0], Exception) else "none"
    ttl      = responses[1] if not isinstance(responses[1], Exception) else -2
    encoding = responses[2] if not isinstance(responses[2], Exception) else None
    memory   = responses[3] if not isinstance(responses[3], Exception) else None

    if key_type == "none":
        return {
            "key": key, "type": "none", "ttl": -2,
            "encoding": None, "memory_bytes": None,
            "length": None, "value": None, "truncated": False, "db": db,
        }

    value = None
    length = None
    truncated = False

    if key_type == "string":
        raw = r.get(key)
        length = len(raw) if raw else 0
        if length > _MAX_STRING_BYTES:
            value = raw[:_MAX_STRING_BYTES]
            truncated = True
        else:
            value = raw

    elif key_type == "hash":
        length = r.hlen(key)
        if length <= count:
            value = r.hgetall(key)
        else:
            # Cursor-based page via HSCAN
            _, pairs = r.hscan(key, cursor=0, count=count)
            items = list(pairs.items())
            value = dict(items[offset: offset + count])
            truncated = len(items) > offset + count

    elif key_type == "list":
        length = r.llen(key)
        value = r.lrange(key, offset, offset + count - 1)
        truncated = (offset + count) < length

    elif key_type == "set":
        length = r.scard(key)
        if length <= count:
            value = sorted(r.smembers(key))
        else:
            _, members = r.sscan(key, cursor=0, count=count)
            value = sorted(members)
            truncated = True

    elif key_type == "zset":
        length = r.zcard(key)
        pairs = r.zrange(key, offset, offset + count - 1, withscores=True)
        value = [{"member": m, "score": s} for m, s in pairs]
        truncated = (offset + count) < length

    elif key_type == "stream":
        length = r.xlen(key)
        entries = r.xrange(key, count=count)
        value = [{"id": eid, "fields": fields} for eid, fields in entries]
        truncated = len(entries) == count and length > count

    return {
        "key": key,
        "type": key_type,
        "ttl": ttl,
        "encoding": encoding,
        "memory_bytes": memory,
        "length": length,
        "value": value,
        "truncated": truncated,
        "db": db,
    }


def get_key_ttl(key: str, db: int = 0) -> dict:
    r = get_client(db)
    return {"key": key, "ttl": r.ttl(key), "pttl": r.pttl(key)}


def get_key_type(key: str, db: int = 0) -> dict:
    return {"key": key, "type": get_client(db).type(key)}


def get_key_memory(key: str, db: int = 0) -> dict:
    return {"key": key, "memory_bytes": get_client(db).memory_usage(key)}


def get_key_metadata(key: str, db: int = 0) -> dict:
    r = get_client(db)
    pipe = r.pipeline(transaction=False)
    pipe.type(key)
    pipe.ttl(key)
    pipe.pttl(key)
    pipe.object_encoding(key)
    pipe.object_refcount(key)
    pipe.object_idletime(key)
    pipe.memory_usage(key)
    res = pipe.execute(raise_on_error=False)
    return {
        "key": key,
        "type": res[0] if not isinstance(res[0], Exception) else None,
        "ttl": res[1] if not isinstance(res[1], Exception) else -2,
        "pttl": res[2] if not isinstance(res[2], Exception) else -2,
        "encoding": res[3] if not isinstance(res[3], Exception) else None,
        "refcount": res[4] if not isinstance(res[4], Exception) else None,
        "idletime": res[5] if not isinstance(res[5], Exception) else None,
        "memory_bytes": res[6] if not isinstance(res[6], Exception) else None,
    }


def dump_key(key: str, db: int = 0) -> dict:
    raw = get_bin_client(db).dump(key)
    return {
        "key": key,
        "dump_base64": base64.b64encode(raw).decode() if raw else None,
    }


# ---------------------------------------------------------------------------
# Key CRUD
# ---------------------------------------------------------------------------

def set_key(key: str, type_: str, value: Any, ttl: Optional[int], db: int = 0) -> dict:
    r = get_client(db)
    if type_ == "string":
        r.set(key, str(value))
    elif type_ == "hash":
        if not isinstance(value, dict):
            raise ValueError("Hash value must be a JSON object")
        r.delete(key)
        if value:
            r.hset(key, mapping=value)
    elif type_ == "list":
        if not isinstance(value, list):
            raise ValueError("List value must be a JSON array")
        r.delete(key)
        if value:
            r.rpush(key, *[str(v) for v in value])
    elif type_ == "set":
        if not isinstance(value, list):
            raise ValueError("Set value must be a JSON array")
        r.delete(key)
        if value:
            r.sadd(key, *[str(v) for v in value])
    elif type_ == "zset":
        if not isinstance(value, list):
            raise ValueError("ZSet value must be [{member, score}]")
        r.delete(key)
        for item in value:
            r.zadd(key, {item["member"]: float(item["score"])})
    else:
        raise ValueError(f"Unsupported type: {type_}")

    if ttl and ttl > 0:
        r.expire(key, ttl)

    return get_key(key, db=db)


def delete_keys(keys: list[str], db: int = 0) -> dict:
    deleted = get_client(db).delete(*keys)
    return {"deleted": deleted, "keys": keys}


def expire_key(key: str, ttl: int, db: int = 0) -> dict:
    r = get_client(db)
    if ttl <= 0:
        r.persist(key)
        return {"key": key, "action": "persisted", "ttl": -1}
    r.expire(key, ttl)
    return {"key": key, "action": "expire_set", "ttl": ttl}


def persist_key(key: str, db: int = 0) -> dict:
    get_client(db).persist(key)
    return {"key": key, "action": "persisted", "ttl": -1}


def rename_key(key: str, new_key: str, nx: bool = False, db: int = 0) -> dict:
    r = get_client(db)
    if nx:
        result = bool(r.renamenx(key, new_key))
    else:
        r.rename(key, new_key)
        result = True
    return {"old_key": key, "new_key": new_key, "success": result}


def copy_key(
    key: str,
    destination: str,
    destination_db: Optional[int] = None,
    replace: bool = False,
    db: int = 0,
) -> dict:
    r = get_client(db)
    kwargs: dict = {"replace": replace}
    if destination_db is not None:
        kwargs["destination_db"] = destination_db
    result = bool(r.copy(key, destination, **kwargs))
    return {"source": key, "destination": destination, "success": result}


# ---------------------------------------------------------------------------
# Hash field operations
# ---------------------------------------------------------------------------

def hash_get_all(key: str, db: int = 0) -> dict:
    return get_client(db).hgetall(key)


def hash_get_field(key: str, field: str, db: int = 0) -> Optional[str]:
    return get_client(db).hget(key, field)


def hash_set_field(key: str, field: str, value: str, db: int = 0) -> dict:
    get_client(db).hset(key, field, value)
    return {"key": key, "field": field, "value": value}


def hash_del_field(key: str, field: str, db: int = 0) -> dict:
    deleted = bool(get_client(db).hdel(key, field))
    return {"key": key, "field": field, "deleted": deleted}


def hash_get_fields(key: str, db: int = 0) -> list[str]:
    return get_client(db).hkeys(key)


# ---------------------------------------------------------------------------
# List operations
# ---------------------------------------------------------------------------

def list_get(key: str, start: int = 0, stop: int = 99, db: int = 0) -> dict:
    r = get_client(db)
    length = r.llen(key)
    items = r.lrange(key, start, stop)
    return {"key": key, "items": items, "length": length, "start": start, "stop": stop}


def list_push(key: str, values: list[str], direction: str = "right", db: int = 0) -> dict:
    r = get_client(db)
    if direction == "left":
        r.lpush(key, *values)
    else:
        r.rpush(key, *values)
    return {"key": key, "length": r.llen(key)}


def list_pop(key: str, direction: str = "right", db: int = 0) -> dict:
    r = get_client(db)
    value = r.lpop(key) if direction == "left" else r.rpop(key)
    return {"key": key, "value": value}


def list_set_index(key: str, index: int, value: str, db: int = 0) -> dict:
    get_client(db).lset(key, index, value)
    return {"key": key, "index": index, "value": value}


def list_remove(key: str, value: str, count: int = 0, db: int = 0) -> dict:
    removed = get_client(db).lrem(key, count, value)
    return {"key": key, "removed": removed}


# ---------------------------------------------------------------------------
# Set operations
# ---------------------------------------------------------------------------

def set_members(key: str, db: int = 0) -> list[str]:
    return sorted(get_client(db).smembers(key))


def set_add(key: str, members: list[str], db: int = 0) -> dict:
    added = get_client(db).sadd(key, *members)
    return {"key": key, "added": added}


def set_remove(key: str, member: str, db: int = 0) -> dict:
    removed = bool(get_client(db).srem(key, member))
    return {"key": key, "member": member, "removed": removed}


def set_random(key: str, count: int = 1, db: int = 0) -> Any:
    r = get_client(db)
    return r.srandmember(key) if count == 1 else r.srandmember(key, count)


def set_is_member(key: str, member: str, db: int = 0) -> dict:
    return {"key": key, "member": member, "is_member": bool(get_client(db).sismember(key, member))}


# ---------------------------------------------------------------------------
# Sorted Set operations
# ---------------------------------------------------------------------------

def zset_range(
    key: str, start: int = 0, stop: int = 99,
    reverse: bool = False, db: int = 0,
) -> dict:
    r = get_client(db)
    length = r.zcard(key)
    pairs = (
        r.zrevrange(key, start, stop, withscores=True)
        if reverse else
        r.zrange(key, start, stop, withscores=True)
    )
    return {
        "key": key,
        "items": [{"member": m, "score": s} for m, s in pairs],
        "length": length, "start": start, "stop": stop,
    }


def zset_add(key: str, members: list[dict], nx: bool = False, xx: bool = False, db: int = 0) -> dict:
    mapping = {item["member"]: float(item["score"]) for item in members}
    added = get_client(db).zadd(key, mapping, nx=nx, xx=xx)
    return {"key": key, "added": added}


def zset_remove(key: str, member: str, db: int = 0) -> dict:
    removed = bool(get_client(db).zrem(key, member))
    return {"key": key, "member": member, "removed": removed}


def zset_score(key: str, member: str, db: int = 0) -> dict:
    r = get_client(db)
    return {
        "key": key, "member": member,
        "score": r.zscore(key, member),
        "rank": r.zrank(key, member),
        "revrank": r.zrevrank(key, member),
    }


def zset_range_by_score(
    key: str,
    min_score: str = "-inf",
    max_score: str = "+inf",
    offset: int = 0,
    count: int = 100,
    db: int = 0,
) -> dict:
    r = get_client(db)
    pairs = r.zrangebyscore(key, min_score, max_score, withscores=True, start=offset, num=count)
    return {"key": key, "items": [{"member": m, "score": s} for m, s in pairs]}


# ---------------------------------------------------------------------------
# Stream operations
# ---------------------------------------------------------------------------

def stream_range(
    key: str, start: str = "-", end: str = "+",
    count: int = 100, db: int = 0,
) -> dict:
    r = get_client(db)
    length = r.xlen(key)
    entries = r.xrange(key, min=start, max=end, count=count)
    return {
        "key": key,
        "items": [{"id": eid, "fields": fields} for eid, fields in entries],
        "length": length,
    }


def stream_add(key: str, fields: dict, entry_id: str = "*", db: int = 0) -> dict:
    new_id = get_client(db).xadd(key, fields, id=entry_id)
    return {"key": key, "id": new_id}


def stream_delete_entry(key: str, entry_id: str, db: int = 0) -> dict:
    deleted = bool(get_client(db).xdel(key, entry_id))
    return {"key": key, "entry_id": entry_id, "deleted": deleted}


def stream_info(key: str, db: int = 0) -> dict:
    raw = get_client(db).xinfo_stream(key)
    return {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None), list, dict)) else v)
            for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Server information
# ---------------------------------------------------------------------------

def get_info(section: Optional[str] = None, db: int = 0) -> dict:
    r = get_client(db)
    return r.info(section) if section else r.info()


def get_databases(db: int = 0) -> list[dict]:
    info = get_client(db).info("keyspace")
    dbs = []
    for key, val in info.items():
        if key.startswith("db"):
            dbs.append({
                "db": int(key[2:]),
                "keys": val.get("keys", 0),
                "expires": val.get("expires", 0),
                "avg_ttl": val.get("avg_ttl", 0),
            })
    dbs.sort(key=lambda x: x["db"])
    return dbs


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_config(pattern: str = "*", db: int = 0) -> dict:
    return dict(get_client(db).config_get(pattern))


def set_config(parameter: str, value: str, db: int = 0) -> dict:
    get_client(db).config_set(parameter, value)
    return {"parameter": parameter, "value": value}


def config_rewrite(db: int = 0) -> dict:
    get_client(db).config_rewrite()
    return {"action": "rewrite"}


def config_resetstat(db: int = 0) -> dict:
    get_client(db).config_resetstat()
    return {"action": "resetstat"}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def bgsave(db: int = 0) -> dict:
    get_client(db).bgsave()
    return {"action": "bgsave"}


def bgrewriteaof(db: int = 0) -> dict:
    get_client(db).bgrewriteaof()
    return {"action": "bgrewriteaof"}


# ---------------------------------------------------------------------------
# Flush (destructive — callers must enforce confirmation)
# ---------------------------------------------------------------------------

def flushdb(async_: bool = False, db: int = 0) -> dict:
    get_client(db).flushdb(asynchronous=async_)
    return {"action": "flushdb", "db": db}


def flushall(async_: bool = False, db: int = 0) -> dict:
    get_client(db).flushall(asynchronous=async_)
    return {"action": "flushall"}


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def list_clients(db: int = 0) -> list[dict]:
    raw = get_client(db).client_list()
    # redis-py >= 4 already returns list[dict]
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return raw
    # Older versions return a string — parse manually
    result = []
    for line in str(raw).strip().splitlines():
        entry: dict = {}
        for part in line.split():
            if "=" in part:
                k, _, v = part.partition("=")
                entry[k] = v
        if entry:
            result.append(entry)
    return result


def kill_client(addr: Optional[str] = None, client_id: Optional[int] = None, db: int = 0) -> dict:
    r = get_client(db)
    kwargs: dict = {}
    if addr:
        kwargs["addr"] = addr
    if client_id:
        kwargs["client_id"] = client_id
    killed = r.client_kill_filter(**kwargs)
    return {"killed": killed}


# ---------------------------------------------------------------------------
# Slow log
# ---------------------------------------------------------------------------

def get_slowlog(count: int = 50, db: int = 0) -> list[dict]:
    entries = get_client(db).slowlog_get(count)
    result = []
    for e in entries:
        result.append({
            "id": e.get("id"),
            "start_time": e.get("start_time"),
            "duration_microseconds": e.get("duration"),
            "command": e.get("command", []),
            "client_addr": e.get("client_addr", ""),
            "client_name": e.get("client_name", ""),
        })
    return result


def slowlog_len(db: int = 0) -> int:
    return get_client(db).slowlog_len()


def slowlog_reset(db: int = 0) -> dict:
    get_client(db).slowlog_reset()
    return {"action": "slowlog_reset"}


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def get_memory_stats(db: int = 0) -> dict:
    r = get_client(db)
    stats = r.memory_stats()
    doctor = r.memory_doctor()
    return {"stats": stats, "doctor": doctor}


def get_memory_malloc_stats(db: int = 0) -> str:
    return get_client(db).memory_malloc_stats()


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------

def get_latency_latest(db: int = 0) -> list[dict]:
    raw = get_client(db).latency_latest()
    result = []
    for entry in raw or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            result.append({"event": entry[0], "latest_ms": entry[1], "max_ms": entry[2]})
        elif isinstance(entry, dict):
            result.append(entry)
    return result


def get_latency_history(event: str, db: int = 0) -> list[dict]:
    raw = get_client(db).latency_history(event)
    return [{"timestamp": t, "latency_ms": lat} for t, lat in (raw or [])]


def latency_reset(db: int = 0) -> dict:
    get_client(db).latency_reset()
    return {"action": "latency_reset"}


# ---------------------------------------------------------------------------
# Pub/Sub introspection
# ---------------------------------------------------------------------------

def pubsub_channels(pattern: str = "*", db: int = 0) -> list[str]:
    return get_client(db).pubsub_channels(pattern)


def pubsub_numsub(channels: list[str], db: int = 0) -> dict:
    raw = get_client(db).pubsub_numsub(*channels)
    return {ch: cnt for ch, cnt in (raw or [])}


def pubsub_numpat(db: int = 0) -> dict:
    return {"pattern_subscriptions": get_client(db).pubsub_numpat()}


def publish(channel: str, message: str, db: int = 0) -> dict:
    receivers = get_client(db).publish(channel, message)
    return {"channel": channel, "message": message, "receivers": receivers}


def pubsub_subscribe_generator(
    channels: list[str], db: int = 0
) -> Generator[dict, None, None]:
    """Blocking generator that yields pub/sub messages — run in a thread."""
    r = get_client(db)
    p = r.pubsub(ignore_subscribe_messages=True)
    p.subscribe(*channels)
    try:
        for msg in p.listen():
            if msg and msg.get("type") in ("message", "pmessage"):
                yield {
                    "type": msg["type"],
                    "channel": msg.get("channel"),
                    "pattern": msg.get("pattern"),
                    "data": msg.get("data"),
                }
    finally:
        p.unsubscribe()
        p.close()


# ---------------------------------------------------------------------------
# MONITOR — real-time command stream
# ---------------------------------------------------------------------------

def monitor_generator(db: int = 0) -> Generator[dict, None, None]:
    """Blocking generator of MONITOR events — run in a thread."""
    r = get_client(db)
    with r.monitor() as m:
        for command in m.listen():
            yield command


# ---------------------------------------------------------------------------
# LUA scripting
# ---------------------------------------------------------------------------

def eval_script(script: str, keys: list[str], args: list[str], db: int = 0) -> Any:
    return get_client(db).eval(script, len(keys), *keys, *args)


# ---------------------------------------------------------------------------
# Analysis — keyspace, memory, TTL (sample-based, non-blocking)
# ---------------------------------------------------------------------------

def analyze_keyspace(
    pattern: str = "*",
    sample_size: int = 10000,
    db: int = 0,
) -> dict:
    """
    Scan up to `sample_size` keys and return:
      - type distribution
      - top 50 key prefixes (by colon-delimited depth, up to 3 levels)
      - TTL distribution buckets
    """
    r = get_client(db)
    type_counts: dict[str, int] = {}
    prefix_counts: dict[str, int] = {}
    ttl_buckets = {"no_expiry": 0, "lt_1h": 0, "1h_to_24h": 0, "gt_24h": 0}
    total_scanned = 0
    cursor = 0

    while total_scanned < sample_size:
        batch = min(500, sample_size - total_scanned)
        cursor, keys = r.scan(cursor=cursor, match=pattern, count=batch)
        if not keys:
            if cursor == 0:
                break
            continue

        pipe = r.pipeline(transaction=False)
        for k in keys:
            pipe.type(k)
            pipe.ttl(k)
        responses = pipe.execute(raise_on_error=False)

        for i, k in enumerate(keys):
            ktype = responses[i * 2]
            kttl = responses[i * 2 + 1]
            if isinstance(ktype, str):
                type_counts[ktype] = type_counts.get(ktype, 0) + 1
            if isinstance(kttl, int):
                if kttl == -1:
                    ttl_buckets["no_expiry"] += 1
                elif kttl < 3600:
                    ttl_buckets["lt_1h"] += 1
                elif kttl < 86400:
                    ttl_buckets["1h_to_24h"] += 1
                else:
                    ttl_buckets["gt_24h"] += 1
            # Prefix tree — up to 3 levels of ":"
            parts = k.split(":")
            for depth in range(1, min(4, len(parts) + 1)):
                prefix = ":".join(parts[:depth]) + (":*" if depth < len(parts) else "")
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

        total_scanned += len(keys)
        if cursor == 0:
            break

    top_prefixes = sorted(prefix_counts.items(), key=lambda x: x[1], reverse=True)[:50]
    return {
        "total_scanned": total_scanned,
        "type_distribution": type_counts,
        "top_prefixes": [{"prefix": p, "count": c} for p, c in top_prefixes],
        "ttl_distribution": ttl_buckets,
        "db": db,
    }


def analyze_memory_top(
    pattern: str = "*",
    sample_size: int = 1000,
    top_n: int = 50,
    db: int = 0,
) -> list[dict]:
    """Return the top `top_n` keys by memory usage from a sample."""
    r = get_client(db)
    key_memories: list[dict] = []
    scanned = 0
    cursor = 0

    while scanned < sample_size:
        cursor, keys = r.scan(cursor=cursor, match=pattern, count=200)
        if not keys:
            if cursor == 0:
                break
            continue

        pipe = r.pipeline(transaction=False)
        for k in keys:
            pipe.memory_usage(k)
            pipe.type(k)
        responses = pipe.execute(raise_on_error=False)

        for i, k in enumerate(keys):
            mem = responses[i * 2]
            ktype = responses[i * 2 + 1]
            if isinstance(mem, int):
                key_memories.append({"key": k, "memory_bytes": mem, "type": ktype})

        scanned += len(keys)
        if cursor == 0:
            break

    key_memories.sort(key=lambda x: x["memory_bytes"], reverse=True)
    return key_memories[:top_n]


def analyze_expiring_soon(
    within_seconds: int = 3600,
    sample_size: int = 10000,
    pattern: str = "*",
    db: int = 0,
) -> list[dict]:
    """Return keys whose TTL is within `within_seconds`."""
    r = get_client(db)
    expiring: list[dict] = []
    scanned = 0
    cursor = 0

    while scanned < sample_size:
        cursor, keys = r.scan(cursor=cursor, match=pattern, count=500)
        if not keys:
            if cursor == 0:
                break
            continue

        pipe = r.pipeline(transaction=False)
        for k in keys:
            pipe.ttl(k)
            pipe.type(k)
        responses = pipe.execute(raise_on_error=False)

        for i, k in enumerate(keys):
            ttl = responses[i * 2]
            ktype = responses[i * 2 + 1]
            if isinstance(ttl, int) and 0 < ttl <= within_seconds:
                expiring.append({"key": k, "ttl": ttl, "type": ktype})

        scanned += len(keys)
        if cursor == 0:
            break

    expiring.sort(key=lambda x: x["ttl"])
    return expiring


# ---------------------------------------------------------------------------
# WebSocket helpers — thread + queue pattern for blocking generators
# ---------------------------------------------------------------------------

def make_thread_queue(
    generator_fn,
    *args,
    maxsize: int = 200,
    **kwargs,
) -> tuple[queue.Queue, threading.Event]:
    """
    Runs `generator_fn(*args, **kwargs)` in a daemon thread.
    Returns (queue, stop_event).

    The thread puts items onto the queue.
    Caller should set stop_event when done; the thread checks it per item.
    A None sentinel is placed on the queue when the generator is exhausted.
    """
    q: queue.Queue = queue.Queue(maxsize=maxsize)
    stop = threading.Event()

    def _run():
        try:
            for item in generator_fn(*args, **kwargs):
                if stop.is_set():
                    break
                try:
                    q.put(item, timeout=1)
                except queue.Full:
                    pass
        except Exception as exc:
            q.put({"__error__": str(exc)})
        finally:
            q.put(None)  # sentinel

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return q, stop
