"""
Response models — the `data` payload of each REST endpoint.

Each model mirrors exactly what the service layer returns (see
src/services/redis_service.py and the routers). Routes use them as
`response_model=APIResponse[Model]`, which is what puts response shapes in
the OpenAPI spec. Fields a model does not declare are passed through, never
dropped (see ResponseModel).
"""

from typing import Any, Literal, Optional, Union

from pydantic import Field

from src.models.schemas import InfoStr, Number, ResponseModel

TTL_DESC = "Seconds to live; -1 = no expiry, -2 = key does not exist"


# ===========================================================================
# Shared fragments
# ===========================================================================

class ActionResult(ResponseModel):
    action: str = Field(description="Name of the action that ran, e.g. `bgsave`")


class KeyCount(ResponseModel):
    count: int
    db: int


class ZSetMember(ResponseModel):
    member: str
    score: Number


class StreamEntry(ResponseModel):
    id: str
    fields: dict[str, str]


class MembersAdded(ResponseModel):
    key: str
    added: int = Field(description="Number of members newly added")


class MemberRemoved(ResponseModel):
    key: str
    member: str
    removed: bool


class ConsumerGroup(ResponseModel):
    name: str
    consumers: int
    pending: int
    last_delivered_id: Optional[str]
    lag: Optional[int] = Field(description="Entries not yet delivered to the group; null on Redis < 7.0")


class QueueSummary(ResponseModel):
    key: str
    type: Literal["list", "stream"]
    depth: int = Field(description="LLEN for lists, XLEN for streams")
    consumer_groups: Optional[list[ConsumerGroup]] = Field(description="Streams only; null for lists")


# ===========================================================================
# Keys — scan, inspect, CRUD
# ===========================================================================

class KeyScanItem(ResponseModel):
    key: str
    type: str = Field(description="string | hash | list | set | zset | stream; `unknown` if TYPE failed")
    ttl: int = Field(description=TTL_DESC)


class KeyScanResult(ResponseModel):
    keys: list[KeyScanItem]
    cursor: int = Field(description="Pass back as `cursor` for the next page; 0 when the scan is complete")
    count: int = Field(description="Number of keys in this page")
    pattern: str
    db: int


class KeysDeleted(ResponseModel):
    deleted: int = Field(description="Number of keys that existed and were removed")
    keys: list[str] = Field(description="Keys that were requested for deletion")


class KeyDetail(ResponseModel):
    key: str
    type: str = Field(description="string | hash | list | set | zset | stream")
    ttl: int = Field(description=TTL_DESC)
    encoding: Optional[str]
    memory_bytes: Optional[int]
    length: Optional[int] = Field(description="String length in bytes, or number of collection items")
    value: Union[str, dict[str, str], list[ZSetMember], list[StreamEntry], list[str], None] = Field(
        description=(
            "Depends on `type`: string → string; hash → object of field → value; "
            "list → array of strings (LRANGE page); set → sorted array of strings; "
            "zset → array of {member, score}; stream → array of {id, fields}."
        ),
    )
    truncated: bool = Field(description="True when `value` is only part of the key's content")
    db: int


class KeyTTL(ResponseModel):
    key: str
    ttl: int = Field(description=TTL_DESC)
    pttl: int = Field(description="Milliseconds to live; -1 = no expiry, -2 = key does not exist")


class KeyExpireResult(ResponseModel):
    key: str
    action: Literal["expire_set", "persisted"]
    ttl: int = Field(description="The TTL now set, or -1 when persisted")


class KeyMetadata(ResponseModel):
    key: str
    type: Optional[str] = Field(description="`none` when the key does not exist")
    ttl: int = Field(description=TTL_DESC)
    pttl: int
    encoding: Optional[str]
    refcount: Optional[int]
    idletime: Optional[int] = Field(description="Seconds since last access")
    memory_bytes: Optional[int]


class KeyDump(ResponseModel):
    key: str
    dump_base64: Optional[str] = Field(description="null when the key does not exist")


class KeyRenameResult(ResponseModel):
    old_key: str
    new_key: str
    success: bool = Field(description="False when `nx` was set and `new_key` already existed")


class KeyCopyResult(ResponseModel):
    source: str
    destination: str
    success: bool


# --- Hash ------------------------------------------------------------------

class HashAll(ResponseModel):
    key: str
    fields: dict[str, str]


class HashFieldNames(ResponseModel):
    key: str
    fields: list[str]


class HashFieldValue(ResponseModel):
    key: str
    field: str
    value: str


class HashFieldDeleted(ResponseModel):
    key: str
    field: str
    deleted: bool


# --- List ------------------------------------------------------------------

class ListRange(ResponseModel):
    key: str
    items: list[str]
    length: int = Field(description="Total list length")
    start: int
    stop: int


class ListLength(ResponseModel):
    key: str
    length: int = Field(description="List length after the push")


class ListPopResult(ResponseModel):
    key: str
    value: Optional[str] = Field(description="null when the list was empty or missing")


class ListRemoveResult(ResponseModel):
    key: str
    removed: int


class ListSetResult(ResponseModel):
    key: str
    index: int
    value: str


# --- Set -------------------------------------------------------------------

class SetMembers(ResponseModel):
    key: str
    members: list[str] = Field(description="Sorted")


class SetRandomMembers(ResponseModel):
    key: str
    members: Union[str, list[str], None] = Field(
        description="A single string when `count` is 1 (null if the set is empty); otherwise an array",
    )


class SetIsMember(ResponseModel):
    key: str
    member: str
    is_member: bool


# --- Sorted set ------------------------------------------------------------

class ZSetRange(ResponseModel):
    key: str
    items: list[ZSetMember]
    length: int = Field(description="Total number of members")
    start: int
    stop: int


class ZSetScoreRange(ResponseModel):
    key: str
    items: list[ZSetMember]


class ZSetMemberScore(ResponseModel):
    key: str
    member: str
    score: Optional[Number] = Field(description="null when the member is not in the set")
    rank: Optional[int] = Field(description="0-based rank by ascending score")
    revrank: Optional[int] = Field(description="0-based rank by descending score")


# --- Stream ----------------------------------------------------------------

class StreamRange(ResponseModel):
    key: str
    items: list[StreamEntry]
    length: int = Field(description="Total number of entries in the stream")


class StreamInfo(ResponseModel):
    """XINFO STREAM. Field names are Redis's own (hyphenated)."""

    _omit_if_unset = frozenset({"max_deleted_entry_id", "entries_added", "recorded_first_entry_id"})

    length: int
    radix_tree_keys: int = Field(alias="radix-tree-keys")
    radix_tree_nodes: int = Field(alias="radix-tree-nodes")
    last_generated_id: str = Field(alias="last-generated-id")
    groups: int
    first_entry: Optional[StreamEntry] = Field(alias="first-entry", description="null when the stream is empty")
    last_entry: Optional[StreamEntry] = Field(alias="last-entry", description="null when the stream is empty")
    max_deleted_entry_id: Optional[str] = Field(None, alias="max-deleted-entry-id", description="Redis 7.0+")
    entries_added: Optional[int] = Field(None, alias="entries-added", description="Redis 7.0+")
    recorded_first_entry_id: Optional[str] = Field(None, alias="recorded-first-entry-id", description="Redis 7.0+")


class StreamAddResult(ResponseModel):
    key: str
    id: str = Field(description="ID of the new entry")


class StreamEntryDeleted(ResponseModel):
    key: str
    entry_id: str
    deleted: bool


# ===========================================================================
# Server
# ===========================================================================

class DatabaseInfo(ResponseModel):
    db: int
    keys: int
    expires: int
    avg_ttl: int = Field(description="Milliseconds")


class SummaryServer(ResponseModel):
    redis_version: Optional[InfoStr]
    uptime_seconds: Optional[int]
    hz: Optional[int]
    config_file: Optional[InfoStr]
    os: Optional[InfoStr]
    mode: InfoStr


class SummaryClients(ResponseModel):
    connected: Optional[int]
    blocked: int
    tracking: int
    max_clients: Optional[int]


class SummaryMemory(ResponseModel):
    used_bytes: int
    used_human: Optional[InfoStr]
    max_bytes: Optional[int] = Field(description="null when no maxmemory limit is set")
    max_human: Optional[InfoStr]
    percent_used: Optional[Number] = Field(description="null when no maxmemory limit is set")
    peak_used_bytes: Optional[int]
    rss_bytes: Optional[int]
    fragmentation_ratio: Optional[Number]
    eviction_policy: Optional[InfoStr]


class SummaryPerformance(ResponseModel):
    ops_per_sec: Optional[int]
    hit_rate: Optional[Number] = Field(description="Percent; null before any keyspace lookups")
    evicted_keys: int
    evicted_keys_per_sec: Number = Field(description="Average over uptime")
    expired_keys: int
    expired_keys_per_sec: Number = Field(description="Average over uptime")
    total_commands_processed: Optional[int]
    total_net_input_bytes: Optional[int]
    total_net_output_bytes: Optional[int]


class SummaryDatabase(ResponseModel):
    db: int
    keys: int
    expires: int
    avg_ttl_ms: int


class SummaryKeyspace(ResponseModel):
    total_keys: int
    databases: list[SummaryDatabase]


class SummaryReplication(ResponseModel):
    role: InfoStr = Field(description="master | slave")
    connected_slaves: int
    master_repl_offset: Optional[int]
    repl_backlog_size: Optional[int]


class SummaryPersistence(ResponseModel):
    rdb_enabled: bool
    aof_enabled: bool
    last_save_timestamp: Optional[int] = Field(description="Unix seconds")
    last_save_ok: bool
    rdb_changes_since_last_save: Optional[int]
    aof_last_rewrite_status: Optional[InfoStr]
    aof_rewrite_in_progress: bool


class RedisSummary(ResponseModel):
    server: SummaryServer
    clients: SummaryClients
    memory: SummaryMemory
    performance: SummaryPerformance
    keyspace: SummaryKeyspace
    replication: SummaryReplication
    persistence: SummaryPersistence


class Replica(ResponseModel):
    id: int
    ip: Optional[str]
    port: Union[int, str, None]
    state: Optional[str]
    offset: int
    lag_seconds: int


class Replication(ResponseModel):
    """`master_host` … `slave_read_only` are present only when `role` is `slave`/`replica`."""

    _omit_if_unset = frozenset({
        "master_host", "master_port", "master_link_status", "master_last_io_seconds_ago",
        "master_sync_in_progress", "slave_repl_offset", "slave_priority", "slave_read_only",
    })

    role: Optional[InfoStr] = Field(description="master | slave")
    connected_slaves: int
    master_replid: Optional[InfoStr]
    master_repl_offset: Optional[int]
    repl_backlog_active: bool
    repl_backlog_size: Optional[int]
    replicas: list[Replica]
    master_host: Optional[InfoStr] = None
    master_port: Optional[int] = None
    master_link_status: Optional[InfoStr] = Field(None, description="up | down")
    master_last_io_seconds_ago: Optional[int] = None
    master_sync_in_progress: Optional[bool] = None
    slave_repl_offset: Optional[int] = None
    slave_priority: Optional[int] = None
    slave_read_only: Optional[bool] = None


class Performance(ResponseModel):
    ops_per_sec: Optional[int]
    hit_rate_percent: Optional[Number] = Field(description="null before any keyspace lookups")
    miss_rate_percent: Optional[Number] = Field(description="null before any keyspace lookups")
    keyspace_hits: int
    keyspace_misses: int
    total_commands_processed: Optional[int]
    total_connections_received: Optional[int]
    evicted_keys: int
    evicted_keys_per_sec: Number = Field(description="Average over uptime")
    expired_keys: int
    expired_keys_per_sec: Number = Field(description="Average over uptime")
    rejected_connections: int
    total_net_input_bytes: Optional[int]
    total_net_output_bytes: Optional[int]
    net_input_bytes_per_sec: Number = Field(description="Average over uptime")
    net_output_bytes_per_sec: Number = Field(description="Average over uptime")
    connected_clients: Optional[int]
    blocked_clients: int
    tracking_clients: int
    uptime_seconds: Optional[int]


class ConfigSetResult(ResponseModel):
    parameter: str
    value: str


class FlushDbResult(ResponseModel):
    action: Literal["flushdb"]
    db: int


class ClientInfo(ResponseModel):
    """One CLIENT LIST entry. All values are strings, as Redis reports them.
    Optional fields appear only on the Redis versions that report them;
    fields from versions newer than these are passed through as well."""

    _omit_if_unset = frozenset({
        "laddr", "ssub", "argv_mem", "multi_mem", "tot_mem", "rbs", "rbp",
        "redir", "resp", "lib_name", "lib_ver",
    })

    id: str
    addr: str
    fd: str
    name: str
    age: str = Field(description="Connection age in seconds")
    idle: str = Field(description="Idle time in seconds")
    flags: str
    db: str
    sub: str
    psub: str
    multi: str
    qbuf: str
    qbuf_free: str = Field(alias="qbuf-free")
    obl: str
    oll: str
    omem: str
    events: str
    cmd: str
    user: str
    laddr: Optional[str] = Field(None, description="Local address (Redis 6.2+)")
    ssub: Optional[str] = Field(None, description="Shard channel subscriptions (Redis 7.0+)")
    argv_mem: Optional[str] = Field(None, alias="argv-mem", description="Redis 6.2+")
    multi_mem: Optional[str] = Field(None, alias="multi-mem", description="Redis 7.0+")
    tot_mem: Optional[str] = Field(None, alias="tot-mem")
    rbs: Optional[str] = Field(None, description="Read buffer size (Redis 7.0+)")
    rbp: Optional[str] = Field(None, description="Read buffer peak (Redis 7.0+)")
    redir: Optional[str] = Field(None, description="Client-side caching redirect client ID")
    resp: Optional[str] = Field(None, description="RESP protocol version (Redis 7.0+)")
    lib_name: Optional[str] = Field(None, alias="lib-name", description="Redis 7.2+")
    lib_ver: Optional[str] = Field(None, alias="lib-ver", description="Redis 7.2+")


class ClientsKilled(ResponseModel):
    killed: int


class SlowlogEntry(ResponseModel):
    id: int
    start_time: int = Field(description="Unix seconds")
    duration_microseconds: int
    command: str
    client_addr: str
    client_name: str


class SlowlogLength(ResponseModel):
    length: int


class MemoryStats(ResponseModel):
    stats: dict[str, Any] = Field(description="MEMORY STATS as returned by Redis (keys vary by version)")
    doctor: Optional[str] = Field(description="MEMORY DOCTOR report; null if unavailable")


class MallocStats(ResponseModel):
    malloc_stats: str


class LatencyEvent(ResponseModel):
    event: str
    timestamp: int = Field(description="Unix seconds of the latest latency spike")
    latest_ms: int = Field(description="Latency of the latest spike")
    max_ms: int = Field(description="Highest latency recorded for this event")


class LatencySample(ResponseModel):
    timestamp: int = Field(description="Unix seconds")
    latency_ms: int


class PubSubChannels(ResponseModel):
    channels: list[str]
    count: int


class PubSubNumPat(ResponseModel):
    pattern_subscriptions: int


class PublishResult(ResponseModel):
    channel: str
    message: str
    receivers: int = Field(description="Number of subscribers that received the message")


class PrefixCount(ResponseModel):
    prefix: str = Field(description="Colon-delimited prefix, e.g. `user:*`; full key names at the leaf level")
    count: int


class TTLDistribution(ResponseModel):
    no_expiry: int
    lt_1h: int
    h1_to_24h: int = Field(alias="1h_to_24h")
    gt_24h: int


class KeyspaceAnalysis(ResponseModel):
    total_scanned: int
    type_distribution: dict[str, int] = Field(description="Key type → count")
    top_prefixes: list[PrefixCount] = Field(description="Top 50, most common first")
    ttl_distribution: TTLDistribution
    db: int


class KeyMemory(ResponseModel):
    key: str
    memory_bytes: int
    type: str


class ExpiringKey(ResponseModel):
    key: str
    ttl: int = Field(description="Seconds")
    type: str


class EvalResult(ResponseModel):
    result: Any = Field(description="Raw script return value (null, integer, string or nested array)")


class RedisHealth(ResponseModel):
    status: Literal["ok"]
    redis_version: Optional[InfoStr]
    uptime_in_seconds: Optional[int]
    connected_clients: Optional[int]


# ===========================================================================
# Queues
# ===========================================================================

class PendingConsumer(ResponseModel):
    name: str
    pending_count: int


class PendingSummary(ResponseModel):
    group: str
    total_pending: int
    min_pending_id: str
    max_pending_id: str
    consumers: list[PendingConsumer]


class QueueDetail(ResponseModel):
    key: str
    type: Literal["list", "stream"]
    depth: int
    sample_oldest: Optional[list[str]] = Field(description="Lists only: entries from the head; null for streams")
    consumer_groups: Optional[list[ConsumerGroup]] = Field(description="Streams only; null for lists")
    pending_summary: Optional[list[PendingSummary]] = Field(
        description="Streams only; null for lists or when nothing is pending",
    )
    oldest_pending_age_seconds: Optional[Number] = Field(
        description="Age of the oldest unacknowledged stream entry; null when none",
    )


class QueueReorderResult(ResponseModel):
    key: str
    position: Literal["top", "bottom"]
    term: str
    matched: int = Field(description="Entries that matched `term` and were moved")
    total: int = Field(description="Entries in the list at the time of the move")
    arrived_during_move: int = Field(description="Entries pushed during the move, appended after the reordered content")
    temp_key: str = Field(description="Temporary key used during the move (already renamed back)")


# ===========================================================================
# Overview
# ===========================================================================

class RedisOverview(ResponseModel):
    status: Literal["ok"]
    version: Optional[InfoStr]
    uptime_seconds: Optional[int]
    connected_clients: Optional[int]
    used_memory_bytes: int
    max_memory_bytes: Optional[int] = Field(description="null when no maxmemory limit is set")
    memory_percent_used: Optional[Number]
    total_keys: int
    ops_per_sec: Optional[int]
    hit_rate: Optional[Number] = Field(description="Percent; null before any keyspace lookups")
    evicted_keys: int
    role: Optional[InfoStr]
    connected_slaves: int
    aof_enabled: bool
    top_queues: list[QueueSummary] = Field(description="Up to 10 deepest queues")


class RedisOverviewError(ResponseModel):
    """Redis could not be read. The message is in `error` or `detail`, depending on where it failed."""

    _omit_if_unset = frozenset({"error", "detail", "top_queues"})

    status: Literal["error"]
    error: Optional[str] = None
    detail: Optional[str] = None
    top_queues: Optional[list[QueueSummary]] = None


class Overview(ResponseModel):
    generated_at: str = Field(description="ISO 8601 UTC timestamp")
    redis: Union[RedisOverview, RedisOverviewError] = Field(discriminator="status")


class HealthStatus(ResponseModel):
    status: Literal["ok"]
