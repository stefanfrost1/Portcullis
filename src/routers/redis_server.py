"""
Redis server-management, monitoring, and analysis endpoints.

  GET  /redis/info                   — INFO [section]
  GET  /redis/databases              — per-database key counts
  GET  /redis/dbsize                 — DBSIZE alias
  GET  /redis/config                 — CONFIG GET
  POST /redis/config                 — CONFIG SET
  POST /redis/config/rewrite         — CONFIG REWRITE
  POST /redis/config/resetstat       — CONFIG RESETSTAT
  POST /redis/bgsave                 — BGSAVE
  POST /redis/bgrewriteaof           — BGREWRITEAOF
  POST /redis/flushdb                — FLUSHDB  (requires ?confirm=true)
  POST /redis/flushall               — FLUSHALL (requires ?confirm=true)

  GET  /redis/clients                — CLIENT LIST
  POST /redis/clients/kill           — CLIENT KILL (by addr or id)

  GET  /redis/slowlog                — SLOWLOG GET
  GET  /redis/slowlog/len            — SLOWLOG LEN
  POST /redis/slowlog/reset          — SLOWLOG RESET

  GET  /redis/memory/stats           — MEMORY STATS + MEMORY DOCTOR
  GET  /redis/memory/malloc-stats    — MEMORY MALLOC-STATS

  GET  /redis/latency/latest         — LATENCY LATEST
  GET  /redis/latency/history/{event}— LATENCY HISTORY
  POST /redis/latency/reset          — LATENCY RESET

  GET  /redis/pubsub/channels        — PUBSUB CHANNELS
  GET  /redis/pubsub/numsub          — PUBSUB NUMSUB
  GET  /redis/pubsub/numpat          — PUBSUB NUMPAT
  POST /redis/pubsub/publish         — PUBLISH
  WS   /redis/pubsub/subscribe       — live SUBSCRIBE (WebSocket)

  WS   /redis/monitor                — MONITOR command stream (WebSocket)

  GET  /redis/analysis/keyspace      — type + prefix + TTL distribution
  GET  /redis/analysis/memory-top    — top-N keys by memory (sample)
  GET  /redis/analysis/expiring-soon — keys expiring within N seconds

  POST /redis/eval                   — EVAL (LUA script)

  GET  /redis/health                 — connectivity check
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError, ResponseError

from src.models.redis_schemas import (
    RedisConfigSetRequest,
    RedisEvalRequest,
    RedisPublishRequest,
)
from src.models.schemas import APIResponse
from src.services import redis_service as rs

router = APIRouter(prefix="/redis", tags=["Redis — Server"])


def _err(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


# ===========================================================================
# Server information
# ===========================================================================

@router.get(
    "/info",
    summary="Redis INFO command",
    description=(
        "Returns parsed INFO output. Pass `section` to narrow down "
        "(server, clients, memory, persistence, stats, replication, cpu, "
        "commandstats, errorstats, latencystats, cluster, keyspace, all, everything)."
    ),
    response_model=APIResponse,
)
def redis_info(
    section: Optional[str] = Query(None, description="INFO section name"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.get_info(section, db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/databases",
    summary="List databases with key counts",
    description="Parses INFO keyspace and returns per-db key/expire counts.",
    response_model=APIResponse,
)
def databases(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.get_databases(db))
    except RedisError as exc:
        raise _err(exc)


@router.get("/dbsize", summary="DBSIZE — number of keys in the selected database", response_model=APIResponse)
def dbsize(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data={"count": rs.count_keys(db), "db": db})
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Config
# ===========================================================================

@router.get(
    "/config",
    summary="CONFIG GET — get configuration parameters",
    response_model=APIResponse,
)
def config_get(
    pattern: str = Query("*", description="Parameter glob pattern"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.get_config(pattern, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/config", summary="CONFIG SET — update a configuration parameter", response_model=APIResponse)
def config_set(body: RedisConfigSetRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.set_config(body.parameter, body.value, db))
    except ResponseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/config/rewrite",
    summary="CONFIG REWRITE — persist config changes to redis.conf",
    response_model=APIResponse,
)
def config_rewrite(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.config_rewrite(db))
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/config/resetstat",
    summary="CONFIG RESETSTAT — reset stats counters",
    response_model=APIResponse,
)
def config_resetstat(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.config_resetstat(db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Persistence
# ===========================================================================

@router.post("/bgsave", summary="BGSAVE — trigger background RDB snapshot", response_model=APIResponse)
def bgsave(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.bgsave(db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/bgrewriteaof", summary="BGREWRITEAOF — trigger background AOF rewrite", response_model=APIResponse)
def bgrewriteaof(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.bgrewriteaof(db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Flush  — require explicit confirmation to prevent accidents
# ===========================================================================

@router.post(
    "/flushdb",
    summary="FLUSHDB — delete all keys in the selected database",
    description="**Destructive.** Requires `?confirm=true`.",
    response_model=APIResponse,
)
def flushdb(
    confirm: bool = Query(False, description="Must be true to proceed"),
    async_: bool = Query(False, alias="async", description="Run asynchronously"),
    db: int = Query(0, ge=0, le=15),
):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm flushing the database.",
        )
    try:
        return APIResponse(data=rs.flushdb(async_, db))
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/flushall",
    summary="FLUSHALL — delete all keys in ALL databases",
    description="**Destructive.** Requires `?confirm=true`.",
    response_model=APIResponse,
)
def flushall(
    confirm: bool = Query(False, description="Must be true to proceed"),
    async_: bool = Query(False, alias="async"),
    db: int = Query(0, ge=0, le=15),
):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm flushing ALL databases.",
        )
    try:
        return APIResponse(data=rs.flushall(async_, db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Clients
# ===========================================================================

@router.get("/clients", summary="CLIENT LIST — active client connections", response_model=APIResponse)
def list_clients(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.list_clients(db))
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/clients/kill",
    summary="CLIENT KILL — terminate a client connection",
    response_model=APIResponse,
)
def kill_client(
    addr: Optional[str] = Query(None, description="ip:port of the client"),
    client_id: Optional[int] = Query(None, description="Numeric client ID"),
    db: int = Query(0, ge=0, le=15),
):
    if not addr and not client_id:
        raise HTTPException(status_code=400, detail="Provide addr or client_id")
    try:
        return APIResponse(data=rs.kill_client(addr=addr, client_id=client_id, db=db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Slow log
# ===========================================================================

@router.get(
    "/slowlog",
    summary="SLOWLOG GET — recent slow commands",
    response_model=APIResponse,
)
def slowlog_get(
    count: int = Query(50, ge=1, le=1000),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.get_slowlog(count, db))
    except RedisError as exc:
        raise _err(exc)


@router.get("/slowlog/len", summary="SLOWLOG LEN — number of entries", response_model=APIResponse)
def slowlog_len(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data={"length": rs.slowlog_len(db)})
    except RedisError as exc:
        raise _err(exc)


@router.post("/slowlog/reset", summary="SLOWLOG RESET — clear the slow log", response_model=APIResponse)
def slowlog_reset(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.slowlog_reset(db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Memory
# ===========================================================================

@router.get(
    "/memory/stats",
    summary="MEMORY STATS + MEMORY DOCTOR",
    description="Full memory breakdown and any Redis-detected memory issues.",
    response_model=APIResponse,
)
def memory_stats(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.get_memory_stats(db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/memory/malloc-stats",
    summary="MEMORY MALLOC-STATS — allocator internals",
    response_model=APIResponse,
)
def memory_malloc_stats(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data={"malloc_stats": rs.get_memory_malloc_stats(db)})
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Latency
# ===========================================================================

@router.get("/latency/latest", summary="LATENCY LATEST — current latency per event", response_model=APIResponse)
def latency_latest(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.get_latency_latest(db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/latency/history/{event}",
    summary="LATENCY HISTORY — time-series for one event",
    response_model=APIResponse,
)
def latency_history(event: str, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.get_latency_history(event, db))
    except RedisError as exc:
        raise _err(exc)


@router.post("/latency/reset", summary="LATENCY RESET — clear latency samples", response_model=APIResponse)
def latency_reset(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.latency_reset(db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Pub/Sub
# ===========================================================================

@router.get(
    "/pubsub/channels",
    summary="PUBSUB CHANNELS — list active channels",
    response_model=APIResponse,
)
def pubsub_channels(
    pattern: str = Query("*"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        channels = rs.pubsub_channels(pattern, db)
        return APIResponse(data={"channels": channels, "count": len(channels)})
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/pubsub/numsub",
    summary="PUBSUB NUMSUB — subscriber count per channel",
    response_model=APIResponse,
)
def pubsub_numsub(
    channels: list[str] = Query(..., description="Channel names (repeat param)"),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.pubsub_numsub(channels, db))
    except RedisError as exc:
        raise _err(exc)


@router.get("/pubsub/numpat", summary="PUBSUB NUMPAT — number of pattern subscriptions", response_model=APIResponse)
def pubsub_numpat(db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.pubsub_numpat(db))
    except RedisError as exc:
        raise _err(exc)


@router.post(
    "/pubsub/publish",
    summary="PUBLISH — send a message to a channel",
    response_model=APIResponse,
)
def publish(body: RedisPublishRequest, db: int = Query(0, ge=0, le=15)):
    try:
        return APIResponse(data=rs.publish(body.channel, body.message, db))
    except RedisError as exc:
        raise _err(exc)


@router.websocket("/pubsub/subscribe")
async def pubsub_subscribe_ws(
    websocket: WebSocket,
    channels: list[str] = Query(..., description="Channels to subscribe to (repeat param)"),
    db: int = Query(0, ge=0, le=15),
):
    """
    WebSocket: subscribe to one or more pub/sub channels.

    Connect: ws://<host>/api/v1/redis/pubsub/subscribe?channels=ch1&channels=ch2

    Each inbound message:
        {"type": "message", "channel": "ch1", "data": "hello"}
    """
    await websocket.accept()
    try:
        await websocket.send_text(json.dumps({"event": "subscribed", "channels": channels}))
        q, stop = rs.make_thread_queue(rs.pubsub_subscribe_generator, channels, db)
        loop = asyncio.get_event_loop()

        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            if "__error__" in item:
                await websocket.send_text(json.dumps({"event": "error", "detail": item["__error__"]}))
                break
            await websocket.send_text(json.dumps(item, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(json.dumps({"event": "error", "detail": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            stop.set()
        except Exception:
            pass
        await websocket.close()


# ===========================================================================
# MONITOR  — real-time command stream
# ===========================================================================

@router.websocket("/monitor")
async def monitor_ws(
    websocket: WebSocket,
    db: int = Query(0, ge=0, le=15),
):
    """
    WebSocket: stream every command processed by Redis (MONITOR).

    ⚠  This degrades Redis throughput by ~50% — use only for debugging.
    Connect: ws://<host>/api/v1/redis/monitor

    Each message:
        {"time": 1700000000.123, "db": 0, "client_address": "...",
         "command": "SET key value"}
    """
    await websocket.accept()
    try:
        await websocket.send_text(json.dumps({
            "event": "connected",
            "warning": "MONITOR active — Redis throughput is reduced",
        }))
        q, stop = rs.make_thread_queue(rs.monitor_generator, db)
        loop = asyncio.get_event_loop()

        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            if isinstance(item, dict) and "__error__" in item:
                await websocket.send_text(json.dumps({"event": "error", "detail": item["__error__"]}))
                break
            await websocket.send_text(json.dumps(item, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(json.dumps({"event": "error", "detail": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            stop.set()
        except Exception:
            pass
        await websocket.close()


# ===========================================================================
# Analysis
# ===========================================================================

@router.get(
    "/analysis/keyspace",
    summary="Keyspace analysis — type distribution, top prefixes, TTL buckets",
    description=(
        "Samples up to `sample_size` keys and returns: "
        "key type distribution, top-50 colon-delimited prefixes by count, "
        "and TTL distribution (no expiry / <1h / 1-24h / >24h)."
    ),
    response_model=APIResponse,
)
def analysis_keyspace(
    pattern: str = Query("*"),
    sample_size: int = Query(10000, ge=100, le=100000),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.analyze_keyspace(pattern, sample_size, db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/analysis/memory-top",
    summary="Top-N keys by memory usage (sample-based)",
    description=(
        "Scans up to `sample_size` keys and returns the `top_n` heaviest "
        "by MEMORY USAGE. Useful for identifying large-object hotspots."
    ),
    response_model=APIResponse,
)
def analysis_memory_top(
    pattern: str = Query("*"),
    sample_size: int = Query(1000, ge=100, le=50000),
    top_n: int = Query(50, ge=1, le=200),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.analyze_memory_top(pattern, sample_size, top_n, db))
    except RedisError as exc:
        raise _err(exc)


@router.get(
    "/analysis/expiring-soon",
    summary="Keys expiring within N seconds",
    description=(
        "Scans up to `sample_size` keys and returns those whose TTL falls "
        "within `within_seconds`. Results sorted ascending by TTL."
    ),
    response_model=APIResponse,
)
def analysis_expiring_soon(
    within_seconds: int = Query(3600, ge=1, description="TTL threshold in seconds"),
    pattern: str = Query("*"),
    sample_size: int = Query(10000, ge=100, le=100000),
    db: int = Query(0, ge=0, le=15),
):
    try:
        return APIResponse(data=rs.analyze_expiring_soon(within_seconds, sample_size, pattern, db))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# LUA scripting
# ===========================================================================

@router.post(
    "/eval",
    summary="EVAL — execute a LUA script",
    description="Passes `keys` and `args` to the script. Returns raw Redis result.",
    response_model=APIResponse,
)
def eval_script(body: RedisEvalRequest, db: int = Query(0, ge=0, le=15)):
    try:
        result = rs.eval_script(body.script, body.keys, body.args, db)
        return APIResponse(data={"result": result})
    except ResponseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RedisError as exc:
        raise _err(exc)


# ===========================================================================
# Health check
# ===========================================================================

@router.get(
    "/health",
    summary="Redis connectivity check",
    response_model=APIResponse,
)
def redis_health(db: int = Query(0, ge=0, le=15)):
    try:
        info = rs.get_info("server", db)
        return APIResponse(data={
            "status": "ok",
            "redis_version": info.get("redis_version"),
            "uptime_in_seconds": info.get("uptime_in_seconds"),
            "connected_clients": rs.get_info("clients", db).get("connected_clients"),
        })
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "detail": str(exc)},
        )
