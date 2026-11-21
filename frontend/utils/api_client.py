"""
EngineClient — thin HTTP wrapper around Portcullis.

All public methods:
- Unwrap the {"data": ..., "error": ...} envelope.
- Return None on any failure (HTTP error, network error, or API error).
- Store a human-readable error string in st.session_state["last_error"].

Instantiate once per session using @st.cache_resource:

    @st.cache_resource
    def get_client() -> EngineClient:
        cfg = get_config()
        return EngineClient(cfg["base_url"], cfg.get("api_key"))

Note: because the client is cached with @st.cache_resource it is shared by
every browser session, so per-user identity must never be stored on it. The
caller's Caddy auth headers are read from st.context on each request instead
(see _identity_headers).
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st


# Endpoints that scan large keyspaces need more than the default budget on a
# busy Redis instance.
DEFAULT_TIMEOUT = 15
SLOW_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_config() -> dict:
    """
    Read connection settings from st.secrets, then env vars, then defaults.
    """
    def _secret(key: str, default: Any = None) -> Any:
        try:
            return st.secrets[key]
        except (KeyError, AttributeError, FileNotFoundError):
            return os.environ.get(key, default)

    return {
        "base_url": (_secret("MYENGINE_URL", "http://localhost:8000")).rstrip("/"),
        "api_key": _secret("MYENGINE_API_KEY") or None,
        "refresh_interval": int(_secret("REFRESH_INTERVAL", 10)),
        # Name shown for the overview page (nav item + header). Set per
        # deployment so a project-scoped instance reads as that project.
        "dashboard_title": (
            _secret("DASHBOARD_TITLE") or _secret("PROJECT_NAME") or "Dashboard"
        ),
    }


# ---------------------------------------------------------------------------
# Caller identity (Caddy → Streamlit → Portcullis)
# ---------------------------------------------------------------------------

_FORWARDED_HEADERS = ("x-user-groups", "x-user", "x-token-user-name")


def _identity_headers() -> dict:
    """Forward the reverse proxy's auth headers from the browser request.

    Portcullis derives its role from `X-User-Groups`; without this the API only
    ever sees an anonymous reader and every admin action returns 403.
    """
    try:
        incoming = st.context.headers or {}
    except Exception:
        return {}

    forwarded = {}
    for name in _FORWARDED_HEADERS:
        value = incoming.get(name)
        if value:
            forwarded[name] = value
    return forwarded


def current_role() -> str:
    """Role the API will apply to this user: admin | developer | reader."""
    groups = _identity_headers().get("x-user-groups", "")
    if "authp/admin" in groups:
        return "admin"
    if "authp/user" in groups:
        return "developer"
    return "reader"


def is_admin() -> bool:
    return current_role() == "admin"


def _key_path(key: str) -> str:
    """Percent-encode a Redis key for use as a single URL path segment."""
    return quote(key, safe="")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class EngineClient:
    """HTTP client for Portcullis."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._base = base_url.rstrip("/") + "/api/v1"
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"
        if api_key:
            self._session.headers["X-API-Key"] = api_key

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _unwrap(self, resp: requests.Response) -> Any:
        """Parse the APIResponse envelope and return data or None."""
        try:
            body = resp.json()
        except Exception:
            self._set_error(f"HTTP {resp.status_code}: non-JSON response")
            return None

        if not resp.ok:
            err = body.get("error") or {}
            detail = body.get("detail")
            msg = err.get("message") or (detail if isinstance(detail, str) else None)
            if not msg:
                msg = f"HTTP {resp.status_code}"
            code = err.get("code", "")
            if resp.status_code == 403:
                msg = f"{msg} (admin role required — sign in as an admin user)"
            self._set_error(f"{code}: {msg}" if code else msg)
            return None

        if body.get("error"):
            err = body["error"]
            self._set_error(f'{err.get("code", "ERROR")}: {err.get("message", "")}')
            return None

        return body.get("data")

    def _set_error(self, message: str) -> None:
        try:
            st.session_state["last_error"] = message
        except Exception:
            pass

    def _clear_error(self) -> None:
        try:
            st.session_state.pop("last_error", None)
        except Exception:
            pass

    def last_error(self) -> str | None:
        """Error from the most recent call, or None if it succeeded."""
        try:
            return st.session_state.get("last_error")
        except Exception:
            return None

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Any:
        self._clear_error()
        try:
            resp = self._session.request(
                method,
                f"{self._base}{path}",
                params=params,
                json=json,
                headers=_identity_headers(),
                timeout=timeout,
            )
            return self._unwrap(resp)
        except requests.Timeout:
            self._set_error(f"Request timed out after {timeout}s: {path}")
            return None
        except requests.RequestException as exc:
            self._set_error(str(exc))
            return None

    def _get(self, path: str, params: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> Any:
        return self._request("GET", path, params=params, timeout=timeout)

    def _post(
        self,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Any:
        return self._request("POST", path, params=params, json=json or {}, timeout=timeout)

    def _delete(self, path: str, params: dict | None = None, json: dict | None = None) -> Any:
        return self._request("DELETE", path, params=params, json=json)

    def _put(self, path: str, json: dict | None = None) -> Any:
        return self._request("PUT", path, json=json or {})

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    def get_overview(self) -> dict | None:
        return self._get("/overview", timeout=SLOW_TIMEOUT)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> dict | None:
        return self._get("/health")

    def get_redis_health(self) -> dict | None:
        return self._get("/redis/health")

    # ------------------------------------------------------------------
    # Redis — Keys
    # ------------------------------------------------------------------

    def get_redis_keys(
        self, pattern: str = "*", cursor: int = 0, count: int = 50, key_type: str | None = None
    ) -> dict | None:
        """Returns {"keys": [{key, type, ttl}], "cursor": N, "count": N}."""
        params: dict = {"pattern": pattern, "cursor": cursor, "count": count}
        if key_type and key_type != "all":
            params["type"] = key_type
        return self._get("/redis/keys", params=params)

    def get_redis_key_count(self) -> int | None:
        data = self._get("/redis/keys/count")
        if data is None:
            return None
        if isinstance(data, int):
            return data
        return data.get("count")

    def get_redis_key(self, key: str, offset: int = 0, count: int = 200) -> dict | None:
        return self._get(
            f"/redis/keys/{_key_path(key)}",
            params={"offset": offset, "count": count},
        )

    def get_redis_key_metadata(self, key: str) -> dict | None:
        return self._get(f"/redis/keys/{_key_path(key)}/metadata")

    def set_redis_key(
        self,
        key: str,
        key_type: str,
        value: Any,
        ttl: int | None = None,
    ) -> dict | None:
        body: dict = {"type": key_type, "value": value}
        if ttl is not None and ttl > 0:
            body["ttl"] = ttl
        return self._put(f"/redis/keys/{_key_path(key)}", json=body)

    def delete_redis_key(self, key: str) -> dict | None:
        return self._delete(f"/redis/keys/{_key_path(key)}")

    def bulk_delete_redis_keys(self, keys: list[str]) -> dict | None:
        return self._delete("/redis/keys", json={"keys": keys})

    def get_redis_key_ttl(self, key: str) -> dict | None:
        return self._get(f"/redis/keys/{_key_path(key)}/ttl")

    def set_redis_key_expire(self, key: str, ttl: int) -> dict | None:
        return self._post(f"/redis/keys/{_key_path(key)}/expire", json={"ttl": ttl})

    def persist_redis_key(self, key: str) -> dict | None:
        return self._post(f"/redis/keys/{_key_path(key)}/persist")

    def rename_redis_key(self, key: str, new_key: str) -> dict | None:
        return self._post(f"/redis/keys/{_key_path(key)}/rename", json={"new_key": new_key})

    def copy_redis_key(self, key: str, destination: str, replace: bool = False) -> dict | None:
        return self._post(
            f"/redis/keys/{_key_path(key)}/copy",
            json={"destination": destination, "replace": replace},
        )

    # -- Hash ----------------------------------------------------------

    def set_redis_hash_field(self, key: str, field: str, value: str) -> dict | None:
        return self._post(
            f"/redis/keys/{_key_path(key)}/hash/{_key_path(field)}",
            json={"value": value},
        )

    def delete_redis_hash_field(self, key: str, field: str) -> dict | None:
        return self._delete(f"/redis/keys/{_key_path(key)}/hash/{_key_path(field)}")

    # -- List ----------------------------------------------------------

    def get_redis_list(self, key: str, start: int = 0, stop: int = 99) -> dict | None:
        return self._get(
            f"/redis/keys/{_key_path(key)}/list",
            params={"start": start, "stop": stop},
        )

    def push_redis_list(self, key: str, values: list[str], direction: str = "right") -> dict | None:
        return self._post(
            f"/redis/keys/{_key_path(key)}/list/push",
            json={"values": values, "direction": direction},
        )

    def pop_redis_list(self, key: str, direction: str = "right") -> dict | None:
        return self._post(
            f"/redis/keys/{_key_path(key)}/list/pop",
            params={"direction": direction},
        )

    def set_redis_list_index(self, key: str, index: int, value: str) -> dict | None:
        return self._put(f"/redis/keys/{_key_path(key)}/list/{index}", json={"value": value})

    def remove_redis_list_value(self, key: str, value: str, count: int = 0) -> dict | None:
        return self._post(
            f"/redis/keys/{_key_path(key)}/list/remove",
            json={"value": value, "count": count},
        )

    # -- Set -----------------------------------------------------------

    def add_redis_set_members(self, key: str, members: list[str]) -> dict | None:
        return self._post(f"/redis/keys/{_key_path(key)}/set/add", json={"members": members})

    def remove_redis_set_member(self, key: str, member: str) -> dict | None:
        return self._delete(f"/redis/keys/{_key_path(key)}/set/{_key_path(member)}")

    # -- Sorted set ----------------------------------------------------

    def add_redis_zset_member(self, key: str, member: str, score: float) -> dict | None:
        return self._post(
            f"/redis/keys/{_key_path(key)}/zset/add",
            json={"members": [{"member": member, "score": score}]},
        )

    def remove_redis_zset_member(self, key: str, member: str) -> dict | None:
        return self._delete(f"/redis/keys/{_key_path(key)}/zset/{_key_path(member)}")

    # -- Stream --------------------------------------------------------

    def get_redis_stream(
        self, key: str, start: str = "-", end: str = "+", count: int = 100
    ) -> dict | None:
        return self._get(
            f"/redis/keys/{_key_path(key)}/stream",
            params={"start": start, "end": end, "count": count},
        )

    def get_redis_stream_info(self, key: str) -> dict | None:
        return self._get(f"/redis/keys/{_key_path(key)}/stream/info")

    def delete_redis_stream_entry(self, key: str, entry_id: str) -> dict | None:
        return self._delete(f"/redis/keys/{_key_path(key)}/stream/{_key_path(entry_id)}")

    # ------------------------------------------------------------------
    # Redis — Server
    # ------------------------------------------------------------------

    def get_redis_summary(self) -> dict | None:
        return self._get("/redis/summary")

    def get_redis_performance(self) -> dict | None:
        return self._get("/redis/performance")

    def get_redis_replication(self) -> dict | None:
        return self._get("/redis/replication")

    def get_redis_clients(self) -> list | None:
        data = self._get("/redis/clients")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("clients", [])
        return None

    def get_redis_slowlog(self, count: int = 25) -> list | None:
        data = self._get("/redis/slowlog", params={"count": count})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("entries", [])
        return None

    def reset_redis_slowlog(self) -> dict | None:
        return self._post("/redis/slowlog/reset")

    def get_redis_config(self, pattern: str = "*") -> dict | None:
        return self._get("/redis/config", params={"pattern": pattern})

    def set_redis_config(self, parameter: str, value: str) -> dict | None:
        return self._post("/redis/config", json={"parameter": parameter, "value": value})

    def get_redis_memory_stats(self) -> dict | None:
        return self._get("/redis/memory/stats")

    def get_redis_latency_latest(self) -> list | None:
        data = self._get("/redis/latency/latest")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("events", [])
        return None

    def reset_redis_latency(self) -> dict | None:
        return self._post("/redis/latency/reset")

    def redis_bgsave(self) -> dict | None:
        return self._post("/redis/bgsave")

    def redis_bgrewriteaof(self) -> dict | None:
        return self._post("/redis/bgrewriteaof")

    def redis_flushdb(self) -> dict | None:
        return self._post("/redis/flushdb", params={"confirm": "true"})

    def get_redis_databases(self) -> dict | None:
        return self._get("/redis/databases")

    # ------------------------------------------------------------------
    # Redis — Pub/Sub
    # ------------------------------------------------------------------

    def get_pubsub_channels(self) -> list | None:
        data = self._get("/redis/pubsub/channels")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("channels", [])
        return None

    def get_pubsub_numsub(self) -> dict | None:
        return self._get("/redis/pubsub/numsub")

    def publish_message(self, channel: str, message: str) -> dict | None:
        return self._post("/redis/pubsub/publish", json={"channel": channel, "message": message})

    # ------------------------------------------------------------------
    # Redis — Analysis
    # ------------------------------------------------------------------

    def get_redis_analysis_keyspace(self, pattern: str = "*") -> dict | None:
        return self._get(
            "/redis/analysis/keyspace",
            params={"pattern": pattern},
            timeout=SLOW_TIMEOUT,
        )

    def get_redis_analysis_memory_top(self, count: int = 20) -> list | None:
        data = self._get(
            "/redis/analysis/memory-top",
            params={"top_n": count},
            timeout=SLOW_TIMEOUT,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("keys", [])
        return None

    def get_redis_analysis_expiring_soon(self, seconds: int = 300) -> list | None:
        data = self._get(
            "/redis/analysis/expiring-soon",
            params={"within_seconds": seconds},
            timeout=SLOW_TIMEOUT,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("keys", [])
        return None

    # ------------------------------------------------------------------
    # Redis — Queues
    # ------------------------------------------------------------------

    def get_redis_queues(self, pattern: str = "*", max_keys: int = 500) -> list | None:
        data = self._get(
            "/redis/queues",
            params={"pattern": pattern, "max_keys": max_keys},
            timeout=SLOW_TIMEOUT,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("queues", [])
        return None

    def get_redis_queue(self, key: str, sample_count: int = 10) -> dict | None:
        return self._get(
            f"/redis/queues/{_key_path(key)}",
            params={"sample_count": sample_count},
        )
