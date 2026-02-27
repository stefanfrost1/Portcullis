from typing import Any, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Key create / update
# ---------------------------------------------------------------------------

class RedisKeySetRequest(BaseModel):
    type: str = "string"          # string | hash | list | set | zset
    value: Any
    ttl: Optional[int] = None     # seconds; None or <= 0 = no expiry


# ---------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------

class RedisHashFieldRequest(BaseModel):
    value: str


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class RedisListPushRequest(BaseModel):
    values: list[str]
    direction: str = "right"      # left | right


class RedisListSetRequest(BaseModel):
    value: str


class RedisListRemoveRequest(BaseModel):
    value: str
    count: int = 0                # 0 = remove all occurrences


# ---------------------------------------------------------------------------
# Set
# ---------------------------------------------------------------------------

class RedisSetAddRequest(BaseModel):
    members: list[str]


# ---------------------------------------------------------------------------
# Sorted Set
# ---------------------------------------------------------------------------

class RedisZSetAddRequest(BaseModel):
    members: list[dict]           # [{"member": "...", "score": 1.0}]
    nx: bool = False              # only add new members
    xx: bool = False              # only update existing members


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------

class RedisStreamAddRequest(BaseModel):
    fields: dict[str, str]
    entry_id: str = "*"           # "*" = auto-generate


# ---------------------------------------------------------------------------
# TTL / key management
# ---------------------------------------------------------------------------

class RedisExpireRequest(BaseModel):
    ttl: int                      # seconds; <= 0 to call PERSIST instead

class RedisRenameRequest(BaseModel):
    new_key: str
    nx: bool = False              # use RENAMENX

class RedisCopyRequest(BaseModel):
    destination: str
    destination_db: Optional[int] = None
    replace: bool = False


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

class RedisBulkDeleteRequest(BaseModel):
    keys: list[str]


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

class RedisConfigSetRequest(BaseModel):
    parameter: str
    value: str


# ---------------------------------------------------------------------------
# Pub/Sub
# ---------------------------------------------------------------------------

class RedisPublishRequest(BaseModel):
    channel: str
    message: str


# ---------------------------------------------------------------------------
# Scripting
# ---------------------------------------------------------------------------

class RedisEvalRequest(BaseModel):
    script: str
    keys: list[str] = []
    args: list[str] = []
