"""
EngineClient — thin HTTP wrapper around MyEngineAPI.

All public methods:
- Unwrap the {"data": ..., "error": ...} envelope.
- Return None on any failure (HTTP error, network error, or API error).
- Store a human-readable error string in st.session_state["last_error"].

Instantiate once per session using @st.cache_resource:

    @st.cache_resource
    def get_client() -> EngineClient:
        cfg = get_config()
        return EngineClient(cfg["base_url"], cfg.get("api_key"))
"""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st


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
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class EngineClient:
    """HTTP client for MyEngineAPI."""

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
            msg = err.get("message") or f"HTTP {resp.status_code}"
            code = err.get("code", "")
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

    def _get(self, path: str, params: dict | None = None) -> Any:
        self._clear_error()
        try:
            resp = self._session.get(f"{self._base}{path}", params=params, timeout=15)
            return self._unwrap(resp)
        except requests.RequestException as exc:
            self._set_error(str(exc))
            return None

    def _post(self, path: str, json: dict | None = None, params: dict | None = None) -> Any:
        self._clear_error()
        try:
            resp = self._session.post(
                f"{self._base}{path}", json=json or {}, params=params, timeout=15
            )
            return self._unwrap(resp)
        except requests.RequestException as exc:
            self._set_error(str(exc))
            return None

    def _delete(self, path: str, params: dict | None = None, json: dict | None = None) -> Any:
        self._clear_error()
        try:
            resp = self._session.delete(
                f"{self._base}{path}", params=params, json=json, timeout=15
            )
            return self._unwrap(resp)
        except requests.RequestException as exc:
            self._set_error(str(exc))
            return None

    def _put(self, path: str, json: dict | None = None) -> Any:
        self._clear_error()
        try:
            resp = self._session.put(f"{self._base}{path}", json=json or {}, timeout=15)
            return self._unwrap(resp)
        except requests.RequestException as exc:
            self._set_error(str(exc))
            return None

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    def get_overview(self) -> dict | None:
        return self._get("/overview")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> dict | None:
        return self._get("/health")

    def get_redis_health(self) -> dict | None:
        return self._get("/redis/health")

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    def get_containers(self, all: bool = True) -> list | None:
        data = self._get("/containers", params={"all": str(all).lower()})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("containers", [])
        return None

    def get_container(self, id: str) -> dict | None:
        return self._get(f"/containers/{id}")

    def get_container_stats(self, id: str) -> dict | None:
        return self._get(f"/containers/{id}/stats")

    def get_all_container_stats(self) -> list | None:
        data = self._get("/containers/stats/all")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("stats", [])
        return None

    def get_container_groups(self) -> dict | None:
        return self._get("/containers/groups")

    def container_action(self, id: str, action: str) -> dict | None:
        """action: start | stop | restart | pause | unpause"""
        return self._post(f"/containers/{id}/{action}")

    def remove_container(self, id: str, force: bool = False) -> dict | None:
        params = {"force": "true"} if force else {}
        return self._delete(f"/containers/{id}", params=params)

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def get_images(self) -> list | None:
        data = self._get("/images")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("images", [])
        return None

    def get_image(self, id: str) -> dict | None:
        return self._get(f"/images/{id}")

    def pull_image(self, name: str) -> dict | None:
        return self._post("/images/pull", json={"name": name})

    def remove_image(self, id: str, force: bool = False) -> dict | None:
        params = {"force": "true"} if force else {}
        return self._delete(f"/images/{id}", params=params)

    # ------------------------------------------------------------------
    # Networks
    # ------------------------------------------------------------------

    def get_networks(self) -> list | None:
        data = self._get("/networks")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("networks", [])
        return None

    def get_network(self, id: str) -> dict | None:
        return self._get(f"/networks/{id}")

    def create_network(
        self, name: str, driver: str = "bridge", internal: bool = False
    ) -> dict | None:
        return self._post("/networks", json={"name": name, "driver": driver, "internal": internal})

    def remove_network(self, id: str) -> dict | None:
        return self._delete(f"/networks/{id}")

    # ------------------------------------------------------------------
    # Volumes
    # ------------------------------------------------------------------

    def get_volumes(self) -> list | None:
        data = self._get("/volumes")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("volumes", [])
        return None

    def get_volume(self, name: str) -> dict | None:
        return self._get(f"/volumes/{name}")

    def create_volume(self, name: str, driver: str = "local") -> dict | None:
        return self._post("/volumes", json={"name": name, "driver": driver})

    def remove_volume(self, name: str) -> dict | None:
        return self._delete(f"/volumes/{name}")

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    def get_system_info(self) -> dict | None:
        return self._get("/system/info")

    def get_disk_usage(self) -> dict | None:
        return self._get("/system/df")

    # ------------------------------------------------------------------
    # Redis — Keys
    # ------------------------------------------------------------------

    def get_redis_keys(
        self, pattern: str = "*", cursor: int = 0, count: int = 50, key_type: str | None = None
    ) -> dict | None:
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

    def get_redis_key(self, key: str) -> dict | None:
        return self._get(f"/redis/keys/{key}")

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
        return self._put(f"/redis/keys/{key}", json=body)

    def delete_redis_key(self, key: str) -> dict | None:
        return self._delete(f"/redis/keys/{key}")

    def bulk_delete_redis_keys(self, keys: list[str]) -> dict | None:
        return self._delete("/redis/keys", json={"keys": keys})

    def get_redis_key_ttl(self, key: str) -> dict | None:
        return self._get(f"/redis/keys/{key}/ttl")

    def set_redis_key_expire(self, key: str, ttl: int) -> dict | None:
        return self._post(f"/redis/keys/{key}/expire", json={"ttl": ttl})

    def persist_redis_key(self, key: str) -> dict | None:
        return self._post(f"/redis/keys/{key}/persist")

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

    def get_redis_analysis_keyspace(self) -> dict | None:
        return self._get("/redis/analysis/keyspace")

    def get_redis_analysis_memory_top(self, count: int = 20) -> list | None:
        data = self._get("/redis/analysis/memory-top", params={"count": count})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("keys", [])
        return None

    def get_redis_analysis_expiring_soon(self, seconds: int = 300) -> list | None:
        data = self._get("/redis/analysis/expiring-soon", params={"seconds": seconds})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("keys", [])
        return None

    # ------------------------------------------------------------------
    # Redis — Queues
    # ------------------------------------------------------------------

    def get_redis_queues(self) -> list | None:
        data = self._get("/redis/queues")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("queues", [])
        return None

    def get_redis_queue(self, key: str) -> dict | None:
        return self._get(f"/redis/queues/{key}")
