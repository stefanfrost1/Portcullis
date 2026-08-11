"""
Thin wrapper around the Docker SDK.

All methods return plain dicts or primitives so that routers can
serialize them with Pydantic without touching the SDK objects directly.
"""

import logging
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from typing import Generator, Optional

import docker
from docker.errors import DockerException, NotFound, APIError
from docker.models.containers import Container

logger = logging.getLogger(__name__)

from datetime import timedelta

from src.config import settings
from src.models.schemas import (
    ContainerDetail,
    ContainerStats,
    ContainerSummary,
    DiskUsage,
    ImageDetail,
    ImageSummary,
    LogSearchResult,
    GlobalLogSearchResult,
    NetworkSummary,
    SystemInfo,
    VolumeSummary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_client: docker.DockerClient | None = None
_df_client: docker.DockerClient | None = None


def _docker_client() -> docker.DockerClient:
    """Return a cached Docker client (lazy-initialised singleton).

    `max_pool_size` must exceed the worker count of the batch helpers below,
    otherwise threads contend for a small connection pool and calls that fan
    out over every container serialise behind it.
    """
    global _client
    if _client is None:
        _client = docker.from_env(
            timeout=settings.DOCKER_TIMEOUT,
            max_pool_size=settings.DOCKER_MAX_POOL_SIZE,
        )
    return _client


def _disk_usage_client() -> docker.DockerClient:
    """A separate client with a longer timeout, used only by `system df`.

    `docker system df` can take much longer than a normal call on image-heavy
    hosts; giving it its own generous timeout keeps it from tripping
    DOCKER_TIMEOUT (which surfaced as a 500) without making every other call
    wait that long.
    """
    global _df_client
    if _df_client is None:
        _df_client = docker.from_env(
            timeout=settings.DISK_USAGE_TIMEOUT,
            max_pool_size=settings.DOCKER_MAX_POOL_SIZE,
        )
    return _df_client


def close_docker_client() -> None:
    """Close the Docker client connections. Called from the app lifespan shutdown."""
    global _client, _df_client
    for attr in ("_client", "_df_client"):
        client = globals().get(attr)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            globals()[attr] = None


_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"


def _scope_names() -> list[str]:
    """Exact Compose project names in scope (COMPOSE_PROJECTS + COMPOSE_PROJECT)."""
    names = [n.strip() for n in (settings.COMPOSE_PROJECTS or "").split(",") if n.strip()]
    single = (settings.COMPOSE_PROJECT or "").strip()
    if single and single not in names:
        names.append(single)
    return names


def _scope_prefix() -> str:
    """Compose project-name prefix in scope (COMPOSE_PROJECT_PREFIX), or ''."""
    return (settings.COMPOSE_PROJECT_PREFIX or "").strip()


def scope_active() -> bool:
    """True when any project scope (single, list, or prefix) is configured."""
    return bool(_scope_names() or _scope_prefix())


def project_scope() -> Optional[str]:
    """Human-readable description of the active scope, or None when unscoped.

    Surfaced in `/overview` (`project_scope`); filtering itself uses
    `_project_matches()`, not this string.
    """
    if not scope_active():
        return None
    parts: list[str] = []
    prefix = _scope_prefix()
    if prefix:
        parts.append(f"{prefix}*")
    parts.extend(_scope_names())
    return ", ".join(parts) or None


def _project_matches(project: Optional[str]) -> bool:
    """Whether a resource's compose-project label falls in the active scope."""
    if not scope_active():
        return True
    if not project:
        return False
    prefix = _scope_prefix()
    if prefix and project.startswith(prefix):
        return True
    return project in _scope_names()


def _exact_single() -> Optional[str]:
    """The one project to push to the daemon as an exact filter, else None.

    Only a single exact name with no prefix can be filtered entirely daemon-side;
    a list or prefix needs in-process narrowing (Docker labels can't OR/prefix).
    """
    if _scope_prefix():
        return None
    names = _scope_names()
    return names[0] if len(names) == 1 else None


def _needs_client_narrow() -> bool:
    """True when the daemon filter alone is not precise enough (list/prefix)."""
    return scope_active() and _exact_single() is None


def _project_filters(extra: Optional[dict] = None) -> Optional[dict]:
    """Build a Docker API `filters` dict for the active scope.

    - Unscoped: passes `extra` through (or None).
    - Single exact project: an exact `com.docker.compose.project=<name>` label —
      the daemon returns only that project's resources.
    - List / prefix: filters to resources that merely *have* a compose-project
      label (daemon-side), which callers then narrow with `_project_matches()`.
    """
    filters: dict = dict(extra or {})
    if scope_active():
        exact = _exact_single()
        label = f"{_COMPOSE_PROJECT_LABEL}={exact}" if exact else _COMPOSE_PROJECT_LABEL
        existing = filters.get("label")
        if existing is None:
            filters["label"] = label
        elif isinstance(existing, list):
            filters["label"] = [*existing, label]
        else:
            filters["label"] = [existing, label]
    return filters or None


def _container_project(c: Container) -> Optional[str]:
    """Read a container model's compose-project label (sparse or inspected)."""
    labels = c.attrs.get("Labels")
    if labels is None:
        labels = (c.attrs.get("Config") or {}).get("Labels") or {}
    return (labels or {}).get(_COMPOSE_PROJECT_LABEL)


def _volume_project(v) -> Optional[str]:
    """Read a volume model's compose-project label."""
    return (v.attrs.get("Labels") or {}).get(_COMPOSE_PROJECT_LABEL)


def _list_scoped_containers(all_containers: bool, sparse: bool = False) -> list:
    """List containers honouring the active scope (daemon filter + client narrow)."""
    client = _docker_client()
    models = client.containers.list(
        all=all_containers, sparse=sparse, filters=_project_filters()
    )
    if _needs_client_narrow():
        models = [c for c in models if _project_matches(_container_project(c))]
    return models


def _list_scoped_volumes() -> list:
    """List volumes honouring the active scope (daemon filter + client narrow)."""
    client = _docker_client()
    models = client.volumes.list(filters=_project_filters())
    if _needs_client_narrow():
        models = [v for v in models if _project_matches(_volume_project(v))]
    return models


def _container_name(c: Container) -> str:
    """Container name from either an inspected or a sparse (list) model.

    `Container.name` only reads `attrs['Name']`, which `list(sparse=True)` does
    not populate — sparse models carry `Names` instead. The fan-out helpers use
    sparse listing (they only need id + name), so read whichever is present.
    """
    if c.attrs.get("Name"):
        return c.attrs["Name"].lstrip("/")
    names = c.attrs.get("Names") or []
    if names:
        return names[0].lstrip("/")
    return (c.id or "")[:12]


def _batch_deadline(item_count: int, max_workers: int, per_item_timeout: float) -> float:
    """Overall budget for a fan-out call.

    A fixed budget starves hosts with more containers than workers: the last
    wave never gets a chance to finish. Allow one per-item timeout per wave,
    plus slack for the round trips.
    """
    waves = max(1, -(-item_count // max(1, max_workers)))
    return per_item_timeout * waves + 5


def _drain_futures(
    futures: dict,
    per_item_timeout: float,
    overall_timeout: float,
) -> Generator[tuple, None, None]:
    """Yield (item, result, error) for every future without ever raising.

    `as_completed(..., timeout=...)` raises once the *overall* deadline passes,
    which would throw away the results that already completed and fail the whole
    request. This drains whatever is ready and reports the stragglers as errors.
    """
    pending = dict(futures)
    try:
        for future in as_completed(list(futures), timeout=overall_timeout):
            item = pending.pop(future)
            try:
                yield item, future.result(timeout=per_item_timeout), None
            except FutureTimeoutError:
                yield item, None, "timeout"
            except Exception as exc:
                yield item, None, str(exc)
    except FutureTimeoutError:
        pass

    for future, item in pending.items():
        future.cancel()
        yield item, None, "timeout"


def _parse_iso(ts: Optional[str]) -> Optional[str]:
    """Pass through ISO timestamps, return None for zero values."""
    if not ts or ts.startswith("0001"):
        return None
    return ts


def _uptime_seconds(started_at: Optional[str], state: str) -> Optional[int]:
    if state != "running" or not started_at:
        return None
    try:
        # Docker timestamps look like: 2024-01-15T10:23:45.123456789Z
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def _container_summary(c: Container) -> dict:
    attrs = c.attrs
    state = attrs.get("State", {})
    started = _parse_iso(state.get("StartedAt"))
    finished = _parse_iso(state.get("FinishedAt"))
    labels = attrs.get("Config", {}).get("Labels") or {}
    ports = attrs.get("NetworkSettings", {}).get("Ports") or {}

    return {
        "id": c.id,
        "short_id": c.short_id,
        "name": c.name.lstrip("/"),
        "image": attrs.get("Config", {}).get("Image", ""),
        "status": c.status,
        "state": state.get("Status", ""),
        "created": attrs.get("Created", ""),
        "started_at": started,
        "finished_at": finished,
        "uptime_seconds": _uptime_seconds(started, state.get("Status", "")),
        "ports": ports,
        "labels": labels,
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "restart_policy": (attrs.get("HostConfig") or {}).get("RestartPolicy", {}).get("Name"),
        "exit_code": state.get("ExitCode"),
    }


_SENSITIVE_ENV = re.compile(
    r"(password|secret|token|key|cert|auth|credential|api_key|apikey|passwd|private)",
    re.IGNORECASE,
)


def _mask_env(env_list: list[str]) -> list[str]:
    """Replace values of sensitive environment variables with '***'."""
    result = []
    for entry in env_list:
        name, _, _ = entry.partition("=")
        result.append(f"{name}=***" if _SENSITIVE_ENV.search(name) else entry)
    return result


def _container_detail(c: Container) -> dict:
    base = _container_summary(c)
    attrs = c.attrs
    raw_env = attrs.get("Config", {}).get("Env") or []
    base.update(
        {
            "image_id": attrs.get("Image", ""),
            "command": " ".join(attrs.get("Config", {}).get("Cmd") or []),
            "env": _mask_env(raw_env),
            "mounts": attrs.get("Mounts") or [],
            "network_settings": attrs.get("NetworkSettings") or {},
            "host_config": attrs.get("HostConfig") or {},
            "platform": attrs.get("Platform"),
        }
    )
    return base


# Docker log timestamp prefix: "2024-01-15T10:23:45.123456789Z <content>"
_DOCKER_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s*(.*)"
)


def _split_docker_line(line: str) -> tuple[Optional[str], str]:
    """Split a Docker timestamped log line into (timestamp, content).

    Returns (None, line) when no timestamp prefix is found.
    """
    m = _DOCKER_TS_RE.match(line)
    if m:
        return m.group(1), m.group(2)
    return None, line


_PIVOT_TS_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?P<fraction>\.\d+)?"
    r"(?P<tz>Z|[+-]\d{2}:\d{2})?$"
)


def _parse_pivot_datetime(pivot: str) -> datetime:
    """
    Parse an ISO-8601 pivot timestamp safely.

    Docker log timestamps often contain nanoseconds (9 digits), while Python's
    datetime parser supports microseconds (up to 6 digits). We truncate extra
    precision to microseconds for robust parsing.
    """
    raw = (pivot or "").strip()
    m = _PIVOT_TS_RE.fullmatch(raw)
    if not m:
        raise ValueError(
            "Invalid pivot timestamp. Use ISO 8601 format, e.g. 2026-03-07T12:43:36.970734572Z"
        )

    fraction = m.group("fraction") or ""
    if fraction and len(fraction) > 7:  # '.' + up to 6 microsecond digits
        fraction = fraction[:7]

    tz = m.group("tz") or ""
    if tz == "Z":
        tz = "+00:00"

    normalized = f"{m.group('base')}{fraction}{tz}"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Container operations
# ---------------------------------------------------------------------------

def list_containers(all_containers: bool = True) -> list[dict]:
    containers = _list_scoped_containers(all_containers)
    return [_container_summary(c) for c in containers]


def get_container(container_id: str) -> dict:
    client = _docker_client()
    c = client.containers.get(container_id)
    return _container_detail(c)


def get_container_stats(container_id: str) -> dict:
    client = _docker_client()
    c = client.containers.get(container_id)
    raw = c.stats(stream=False)

    # CPU %
    cpu_delta = (
        raw["cpu_stats"]["cpu_usage"]["total_usage"]
        - raw["precpu_stats"]["cpu_usage"]["total_usage"]
    )
    system_delta = (
        raw["cpu_stats"].get("system_cpu_usage", 0)
        - raw["precpu_stats"].get("system_cpu_usage", 0)
    )
    ncpu = raw["cpu_stats"].get("online_cpus") or len(
        raw["cpu_stats"]["cpu_usage"].get("percpu_usage") or [1]
    )
    cpu_percent = (cpu_delta / system_delta * ncpu * 100.0) if system_delta > 0 else 0.0

    # Memory
    mem = raw.get("memory_stats", {})
    mem_usage = mem.get("usage", 0)
    mem_cache = (mem.get("stats") or {}).get("cache", 0)
    mem_rss = mem_usage - mem_cache
    mem_limit = mem.get("limit", 1)
    mem_percent = (mem_rss / mem_limit * 100.0) if mem_limit > 0 else 0.0

    # Network I/O (sum across all interfaces)
    net_rx = net_tx = 0
    for iface in (raw.get("networks") or {}).values():
        net_rx += iface.get("rx_bytes", 0)
        net_tx += iface.get("tx_bytes", 0)

    # Block I/O
    blk_read = blk_write = 0
    for entry in (raw.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []:
        if entry.get("op") == "Read":
            blk_read += entry.get("value", 0)
        elif entry.get("op") == "Write":
            blk_write += entry.get("value", 0)

    return {
        "id": c.id,
        "name": c.name.lstrip("/"),
        "cpu_percent": round(cpu_percent, 2),
        "memory_usage_bytes": mem_rss,
        "memory_limit_bytes": mem_limit,
        "memory_percent": round(mem_percent, 2),
        "network_rx_bytes": net_rx,
        "network_tx_bytes": net_tx,
        "block_read_bytes": blk_read,
        "block_write_bytes": blk_write,
        "pids": (raw.get("pids_stats") or {}).get("current", 0),
    }


def start_container(container_id: str) -> dict:
    client = _docker_client()
    c = client.containers.get(container_id)
    c.start()
    c.reload()
    return _container_summary(c)


def stop_container(container_id: str, timeout: int = 10) -> dict:
    client = _docker_client()
    c = client.containers.get(container_id)
    c.stop(timeout=timeout)
    c.reload()
    return _container_summary(c)


def restart_container(container_id: str, timeout: int = 10) -> dict:
    client = _docker_client()
    c = client.containers.get(container_id)
    c.restart(timeout=timeout)
    c.reload()
    return _container_summary(c)


def pause_container(container_id: str) -> dict:
    client = _docker_client()
    c = client.containers.get(container_id)
    c.pause()
    c.reload()
    return _container_summary(c)


def unpause_container(container_id: str) -> dict:
    client = _docker_client()
    c = client.containers.get(container_id)
    c.unpause()
    c.reload()
    return _container_summary(c)


def remove_container(container_id: str, force: bool = False, remove_volumes: bool = False) -> None:
    client = _docker_client()
    c = client.containers.get(container_id)
    c.remove(force=force, v=remove_volumes)


# ---------------------------------------------------------------------------
# Log operations
# ---------------------------------------------------------------------------

def get_logs(
    container_id: str,
    tail: int = 100,
    since: Optional[str | int] = None,
    until: Optional[str | int] = None,
    timestamps: bool = False,
) -> list[str]:
    client = _docker_client()
    c = client.containers.get(container_id)

    kwargs: dict = {
        "stdout": True,
        "stderr": True,
        "stream": False,
        "timestamps": timestamps,
        "tail": tail,
    }
    if since:
        kwargs["since"] = since
    if until:
        kwargs["until"] = until

    raw: bytes = c.logs(**kwargs)
    lines = raw.decode("utf-8", errors="replace").splitlines()
    return lines


_MAX_PATTERN_LENGTH = 500
_MAX_SEARCH_TAIL = 10_000
_SEARCH_TIMEOUT_SECONDS = 5.0


def search_logs(
    container_id: str,
    pattern: str,
    tail: int = 2000,
    max_results: int = 200,
    since: Optional[str] = None,
    until: Optional[str] = None,
    timestamps: bool = False,
    case_insensitive: bool = False,
) -> dict:
    # Guard: pattern length cap (ReDoS mitigation)
    if len(pattern) > _MAX_PATTERN_LENGTH:
        raise ValueError(f"Regex pattern too long (max {_MAX_PATTERN_LENGTH} characters)")

    # Guard: tail cap
    tail = min(tail, _MAX_SEARCH_TAIL)

    # Always fetch with timestamps internally so we can return them in matches
    raw_lines = get_logs(
        container_id,
        tail=tail,
        since=since,
        until=until,
        timestamps=True,
    )

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}") from exc

    # Execute search in a thread with a timeout to prevent ReDoS hangs
    def _do_search() -> list[str]:
        return [line for line in raw_lines if regex.search(line)]

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_do_search)
        try:
            matched = future.result(timeout=_SEARCH_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            future.cancel()
            raise ValueError(
                f"Pattern search timed out after {_SEARCH_TIMEOUT_SECONDS}s — "
                "simplify the regex or reduce tail size"
            )

    truncated = len(matched) > max_results
    page = matched[:max_results]

    # Build structured matches — timestamp always parsed; content stripped of ts prefix
    structured = []
    display_lines = []
    for raw_line in page:
        ts, content = _split_docker_line(raw_line)
        structured.append({"timestamp": ts, "line": content})
        display_lines.append(raw_line if timestamps else content)

    return {
        "container_id": container_id,
        "pattern": pattern,
        "matched_lines": display_lines,   # backward-compat
        "matches": structured,            # structured with timestamps
        "total_matched": len(matched),
        "truncated": truncated,
    }


_GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT = 10.0
_GLOBAL_SEARCH_MAX_WORKERS = 10


def get_all_container_logs(
    tail: int = 100,
    timestamps: bool = True,
    running_only: bool = True,
) -> dict:
    """Fetch logs from all (running) containers in parallel and return per-container results."""
    containers = _list_scoped_containers(not running_only, sparse=True)

    def _fetch(c) -> dict:
        lines = get_logs(c.id, tail=tail, timestamps=timestamps)
        return {
            "container_id": c.id,
            "container_name": _container_name(c),
            "lines": lines,
            "count": len(lines),
        }

    results: list[dict] = []
    errors: list[dict] = []

    pool = ThreadPoolExecutor(max_workers=_GLOBAL_SEARCH_MAX_WORKERS)
    try:
        futures = {pool.submit(_fetch, c): c for c in containers}
        for c, result, error in _drain_futures(
            futures,
            _GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT,
            _batch_deadline(
                len(containers),
                _GLOBAL_SEARCH_MAX_WORKERS,
                _GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT,
            ),
        ):
            if error:
                errors.append({
                    "container_id": c.id,
                    "container_name": _container_name(c),
                    "error": "fetch timeout" if error == "timeout" else error,
                })
            else:
                results.append(result)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    results.sort(key=lambda r: r["container_name"])
    return {
        "containers_fetched": len(results),
        "containers_searched": len(containers),
        "containers": results,
        "errors": errors,
    }


def global_search_logs(
    pattern: str,
    tail: int = 2000,
    max_results_per_container: int = 200,
    since: Optional[str] = None,
    until: Optional[str] = None,
    timestamps: bool = False,
    case_insensitive: bool = False,
    running_only: bool = True,
) -> dict:
    """
    Search logs across all (running) containers in parallel using a regex pattern.

    Each container is searched independently using a thread pool. Returns matches
    grouped by container; only containers with at least one match are included in
    `results`. Containers that fail or time out are recorded in `errors`.
    """
    if len(pattern) > _MAX_PATTERN_LENGTH:
        raise ValueError(f"Regex pattern too long (max {_MAX_PATTERN_LENGTH} characters)")

    tail = min(tail, _MAX_SEARCH_TAIL)

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}") from exc

    containers = _list_scoped_containers(not running_only, sparse=True)

    def _search_one(c) -> dict:
        # Always fetch with timestamps internally so matches carry pivot timestamps
        raw_lines = get_logs(
            c.id,
            tail=tail,
            since=since,
            until=until,
            timestamps=True,
        )
        matched = [line for line in raw_lines if regex.search(line)]
        truncated = len(matched) > max_results_per_container
        page = matched[:max_results_per_container]

        structured = []
        display_lines = []
        for raw_line in page:
            ts, content = _split_docker_line(raw_line)
            structured.append({"timestamp": ts, "line": content})
            display_lines.append(raw_line if timestamps else content)

        return {
            "container_id": c.id,
            "container_name": _container_name(c),
            "matched_lines": display_lines,
            "matches": structured,
            "match_count": len(matched),
            "truncated": truncated,
        }

    results: list[dict] = []
    errors: list[dict] = []

    pool = ThreadPoolExecutor(max_workers=_GLOBAL_SEARCH_MAX_WORKERS)
    try:
        futures = {pool.submit(_search_one, c): c for c in containers}
        for c, result, error in _drain_futures(
            futures,
            _GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT,
            _batch_deadline(
                len(containers),
                _GLOBAL_SEARCH_MAX_WORKERS,
                _GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT,
            ),
        ):
            if error:
                errors.append({
                    "container_id": c.id,
                    "container_name": _container_name(c),
                    "error": "search timeout" if error == "timeout" else error,
                })
            elif result["match_count"] > 0:
                results.append(result)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    results.sort(key=lambda r: r["container_name"])
    total_matched = sum(r["match_count"] for r in results)

    return {
        "pattern": pattern,
        "containers_searched": len(containers),
        "containers_with_matches": len(results),
        "total_matched": total_matched,
        "results": results,
        "errors": errors,
    }


def _pivot_window(pivot: str, window_seconds: int) -> tuple[int, int, str, str]:
    """Return (since_unix, until_unix, since_iso, until_iso) for a pivot ± window."""
    dt = _parse_pivot_datetime(pivot)
    since_dt = dt - timedelta(seconds=window_seconds)
    until_dt = dt + timedelta(seconds=window_seconds)
    return (
        int(since_dt.timestamp()),
        int(until_dt.timestamp()),
        since_dt.isoformat(),
        until_dt.isoformat(),
    )


def get_logs_context(
    container_id: str,
    pivot: str,
    window_seconds: int = 60,
    timestamps: bool = False,
) -> dict:
    """Return logs for a single container within ±window_seconds of pivot."""
    since_unix, until_unix, since_iso, until_iso = _pivot_window(pivot, window_seconds)
    lines = get_logs(
        container_id,
        tail=10000,
        since=since_unix,
        until=until_unix,
        timestamps=timestamps,
    )
    return {
        "pivot": pivot,
        "window_seconds": window_seconds,
        "since": since_iso,
        "until": until_iso,
        "container_id": container_id,
        "lines": lines,
        "count": len(lines),
    }


def global_logs_context(
    pivot: str,
    window_seconds: int = 60,
    timestamps: bool = False,
    running_only: bool = True,
) -> dict:
    """Return logs from all containers within ±window_seconds of pivot, in parallel."""
    since_unix, until_unix, since_iso, until_iso = _pivot_window(pivot, window_seconds)

    containers = _list_scoped_containers(not running_only, sparse=True)

    def _fetch_one(c) -> dict:
        lines = get_logs(
            c.id,
            tail=10000,
            since=since_unix,
            until=until_unix,
            timestamps=timestamps,
        )
        return {
            "container_id": c.id,
            "container_name": _container_name(c),
            "lines": lines,
            "count": len(lines),
        }

    results: list[dict] = []
    errors: list[dict] = []

    pool = ThreadPoolExecutor(max_workers=_GLOBAL_SEARCH_MAX_WORKERS)
    try:
        futures = {pool.submit(_fetch_one, c): c for c in containers}
        for c, result, error in _drain_futures(
            futures,
            _GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT,
            _batch_deadline(
                len(containers),
                _GLOBAL_SEARCH_MAX_WORKERS,
                _GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT,
            ),
        ):
            if error:
                errors.append({
                    "container_id": c.id,
                    "container_name": _container_name(c),
                    "error": "fetch timeout" if error == "timeout" else error,
                })
            elif result["count"] > 0:
                results.append(result)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    results.sort(key=lambda r: r["container_name"])
    return {
        "pivot": pivot,
        "window_seconds": window_seconds,
        "since": since_iso,
        "until": until_iso,
        "containers_searched": len(containers),
        "containers_with_logs": len(results),
        "results": results,
        "errors": errors,
    }


def stream_logs(
    container_id: str,
    tail: int = 50,
    since: Optional[str] = None,
    timestamps: bool = False,
) -> Generator[str, None, None]:
    """Generator that yields log lines as they arrive (for WebSocket/SSE)."""
    client = _docker_client()
    c = client.containers.get(container_id)
    kwargs: dict = {
        "stdout": True,
        "stderr": True,
        "stream": True,
        "follow": True,
        "timestamps": timestamps,
        "tail": tail,
    }
    if since:
        kwargs["since"] = since

    for chunk in c.logs(**kwargs):
        yield chunk.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Image operations
# ---------------------------------------------------------------------------

def _image_summary(img) -> dict:
    return {
        "id": img.id,
        "short_id": img.short_id,
        "tags": img.tags,
        "created": img.attrs.get("Created", ""),
        "size_bytes": img.attrs.get("Size", 0),
        "labels": (img.attrs.get("Config") or {}).get("Labels") or {},
    }


def _image_detail(img) -> dict:
    base = _image_summary(img)
    cfg = img.attrs.get("Config") or {}
    base.update(
        {
            "architecture": img.attrs.get("Architecture"),
            "os": img.attrs.get("Os"),
            "author": img.attrs.get("Author"),
            "comment": img.attrs.get("Comment"),
            "exposed_ports": cfg.get("ExposedPorts") or {},
            "env": cfg.get("Env") or [],
            "cmd": cfg.get("Cmd"),
            "entrypoint": cfg.get("Entrypoint"),
        }
    )
    return base


def list_images(all_images: bool = False) -> list[dict]:
    client = _docker_client()
    return [_image_summary(i) for i in client.images.list(all=all_images)]


def get_image(image_id: str) -> dict:
    client = _docker_client()
    img = client.images.get(image_id)
    return _image_detail(img)


def remove_image(image_id: str, force: bool = False, no_prune: bool = False) -> None:
    client = _docker_client()
    client.images.remove(image_id, force=force, noprune=no_prune)


def pull_image(repository: str, tag: Optional[str] = None) -> dict:
    client = _docker_client()
    img = client.images.pull(repository, tag=tag)
    return _image_detail(img)


def prune_images() -> dict:
    client = _docker_client()
    return client.images.prune()


# ---------------------------------------------------------------------------
# Network operations
# ---------------------------------------------------------------------------

def _network_summary(net) -> dict:
    containers_info = {}
    for cid, cdata in (net.attrs.get("Containers") or {}).items():
        containers_info[cid] = {
            "name": cdata.get("Name", ""),
            "ipv4": cdata.get("IPv4Address", ""),
            "ipv6": cdata.get("IPv6Address", ""),
            "mac": cdata.get("MacAddress", ""),
        }
    return {
        "id": net.id,
        "name": net.name,
        "driver": net.attrs.get("Driver", ""),
        "scope": net.attrs.get("Scope", ""),
        "internal": net.attrs.get("Internal", False),
        "attachable": net.attrs.get("Attachable", False),
        "ipam": net.attrs.get("IPAM") or {},
        "labels": net.attrs.get("Labels") or {},
        "containers": containers_info,
        "created": net.attrs.get("Created", ""),
    }


def list_networks() -> list[dict]:
    # Networks are host-wide reference resources — intentionally not scoped to
    # COMPOSE_PROJECT (unlike containers/volumes).
    client = _docker_client()
    return [_network_summary(n) for n in client.networks.list()]


def get_network(network_id: str) -> dict:
    client = _docker_client()
    net = client.networks.get(network_id)
    return _network_summary(net)


def create_network(
    name: str,
    driver: str = "bridge",
    internal: bool = False,
    labels: Optional[dict] = None,
) -> dict:
    client = _docker_client()
    net = client.networks.create(
        name=name,
        driver=driver,
        internal=internal,
        labels=labels or {},
    )
    return _network_summary(net)


def remove_network(network_id: str) -> None:
    client = _docker_client()
    net = client.networks.get(network_id)
    net.remove()


# ---------------------------------------------------------------------------
# Volume operations
# ---------------------------------------------------------------------------

def _volume_summary(vol) -> dict:
    return {
        "name": vol.name,
        "driver": vol.attrs.get("Driver", ""),
        "mountpoint": vol.attrs.get("Mountpoint", ""),
        "labels": vol.attrs.get("Labels") or {},
        "scope": vol.attrs.get("Scope", ""),
        "created": vol.attrs.get("CreatedAt"),
    }


def list_volumes() -> list[dict]:
    return [_volume_summary(v) for v in _list_scoped_volumes()]


def get_volume(volume_name: str) -> dict:
    client = _docker_client()
    vol = client.volumes.get(volume_name)
    return _volume_summary(vol)


def create_volume(
    name: str,
    driver: str = "local",
    labels: Optional[dict] = None,
) -> dict:
    client = _docker_client()
    vol = client.volumes.create(
        name=name,
        driver=driver,
        labels=labels or {},
    )
    return _volume_summary(vol)


def remove_volume(volume_name: str, force: bool = False) -> None:
    client = _docker_client()
    vol = client.volumes.get(volume_name)
    vol.remove(force=force)


def prune_volumes() -> dict:
    client = _docker_client()
    return client.volumes.prune()


# ---------------------------------------------------------------------------
# System operations
# ---------------------------------------------------------------------------

def get_system_info() -> dict:
    client = _docker_client()
    info = client.info()
    version = client.version()
    return {
        "docker_version": version.get("Version", ""),
        "api_version": version.get("ApiVersion", ""),
        "kernel_version": info.get("KernelVersion", ""),
        "os": info.get("OperatingSystem", ""),
        "os_type": info.get("OSType", ""),
        "architecture": info.get("Architecture", ""),
        "total_memory_bytes": info.get("MemTotal", 0),
        "ncpu": info.get("NCPU", 0),
        "containers_running": info.get("ContainersRunning", 0),
        "containers_paused": info.get("ContainersPaused", 0),
        "containers_stopped": info.get("ContainersStopped", 0),
        "images_count": info.get("Images", 0),
        "server_version": info.get("ServerVersion", ""),
    }


_df_cache: dict = {"fetched_at": 0.0, "data": None}
_df_lock = threading.Lock()


def _raw_disk_usage(force_refresh: bool = False) -> dict:
    """`docker system df`, memoised for DISK_USAGE_CACHE_TTL seconds.

    On hosts with hundreds of images this call takes many seconds — long enough
    that an auto-refreshing dashboard never finishes a request before starting
    the next one. Disk usage moves slowly, so a short cache is safe.
    """
    ttl = settings.DISK_USAGE_CACHE_TTL
    with _df_lock:
        age = time.monotonic() - _df_cache["fetched_at"]
        if not force_refresh and _df_cache["data"] is not None and age < ttl:
            return _df_cache["data"]

        try:
            raw = _disk_usage_client().df()
        except Exception:
            logger.warning("docker system df failed", exc_info=True)
            raise
        _df_cache["data"] = raw
        _df_cache["fetched_at"] = time.monotonic()
        return raw


def get_disk_usage(force_refresh: bool = False) -> dict:
    """Normalised disk-usage breakdown.

    Docker returns CamelCase SDK payloads; everything else in this service layer
    speaks snake_case, so the entries are flattened to the fields the API
    actually documents.
    """
    df = _raw_disk_usage(force_refresh=force_refresh)

    images = [
        {
            "id": img.get("Id", ""),
            "tags": img.get("RepoTags") or [],
            "created": img.get("Created"),
            "size_bytes": img.get("Size", 0) or 0,
            "shared_size_bytes": img.get("SharedSize", 0) or 0,
            "containers": img.get("Containers", 0),
        }
        for img in (df.get("Images") or [])
    ]

    containers = [
        {
            "id": ct.get("Id", ""),
            "name": (ct.get("Names") or [""])[0].lstrip("/"),
            "image": ct.get("Image", ""),
            "state": ct.get("State", ""),
            "status": ct.get("Status", ""),
            "size_bytes": ct.get("SizeRw", 0) or 0,
            "size_root_fs_bytes": ct.get("SizeRootFs", 0) or 0,
        }
        for ct in (df.get("Containers") or [])
    ]

    volumes = [
        {
            "name": vol.get("Name", ""),
            "driver": vol.get("Driver", ""),
            "size_bytes": (vol.get("UsageData") or {}).get("Size", 0) or 0,
            "ref_count": (vol.get("UsageData") or {}).get("RefCount", 0) or 0,
        }
        for vol in (df.get("Volumes") or [])
    ]

    build_cache = [
        {
            "id": entry.get("ID", ""),
            "type": entry.get("Type", ""),
            "in_use": entry.get("InUse", False),
            "shared": entry.get("Shared", False),
            "size_bytes": entry.get("Size", 0) or 0,
        }
        for entry in (df.get("BuildCache") or [])
    ]

    def _total(items: list[dict]) -> int:
        return sum(item["size_bytes"] for item in items)

    return {
        "images": images,
        "containers": containers,
        "volumes": volumes,
        "build_cache": build_cache,
        "summary": {
            "images_bytes": _total(images),
            "containers_bytes": _total(containers),
            "volumes_bytes": _total(volumes),
            "build_cache_bytes": _total(build_cache),
            "total_bytes": _total(images) + _total(containers) + _total(volumes) + _total(build_cache),
        },
    }


# ---------------------------------------------------------------------------
# Batch container stats
# ---------------------------------------------------------------------------

def get_all_container_stats(
    timeout_seconds: float = 5.0,
    max_workers: int = 20,
) -> dict:
    """
    Fetch resource stats for ALL running containers in parallel.

    Returns {containers: [...], count: N, errors: [...]}.
    Containers that time out or raise are included in `errors` rather than
    raising, so a single unhealthy container does not abort the whole call.
    """
    running = _list_scoped_containers(False, sparse=True)

    stats_list: list[dict] = []
    errors: list[dict] = []

    def _fetch(c) -> dict:
        return get_container_stats(c.id)

    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(_fetch, c): c for c in running}
        deadline = _batch_deadline(len(running), max_workers, timeout_seconds)
        for c, result, error in _drain_futures(futures, timeout_seconds, deadline):
            if error:
                errors.append({
                    "container_id": c.id,
                    "name": _container_name(c),
                    "error": "stats timeout" if error == "timeout" else error,
                })
            else:
                stats_list.append(result)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    stats_list.sort(key=lambda s: s["name"])
    return {"containers": stats_list, "count": len(stats_list), "errors": errors}


# ---------------------------------------------------------------------------
# Compose project grouping
# ---------------------------------------------------------------------------

def get_compose_groups() -> list[dict]:
    """
    Group all containers (running + stopped) by com.docker.compose.project label.
    Containers without that label are omitted.
    Returns list sorted by project name.
    """
    all_containers = _list_scoped_containers(True)

    groups: dict[str, dict] = {}
    for c in all_containers:
        s = _container_summary(c)
        project = s.get("compose_project")
        if not project:
            continue
        if project not in groups:
            groups[project] = {
                "project": project,
                "total": 0, "running": 0, "paused": 0, "stopped": 0,
                "services": [],
            }
        groups[project]["total"] += 1
        state = s.get("state", "")
        if state == "running":
            groups[project]["running"] += 1
        elif state == "paused":
            groups[project]["paused"] += 1
        else:
            groups[project]["stopped"] += 1
        groups[project]["services"].append({
            "name": s.get("compose_service"),
            "container_name": s["name"],
            "short_id": s["short_id"],
            "state": state,
            "uptime_seconds": s.get("uptime_seconds"),
            "image": s.get("image"),
        })

    return sorted(groups.values(), key=lambda g: g["project"])


# ---------------------------------------------------------------------------
# Docker overview snapshot  (for /api/v1/overview)
# ---------------------------------------------------------------------------

def get_docker_overview() -> dict:
    """
    Minimal Docker snapshot for the overview endpoint.

    Host-wide, this makes two Docker API calls: info() and a (cached) df().
    When COMPOSE_PROJECT is set, info()'s host-wide counts no longer describe
    the project, so container counts are derived from a sparse (no-inspect)
    scoped listing and volumes are narrowed to the project's labelled volumes.
    Images are always host-wide.
    """
    client = _docker_client()
    project = project_scope()
    df = _raw_disk_usage()

    images_list = df.get("Images") or []
    total_image_bytes = sum((img.get("Size") or 0) for img in images_list)
    reclaimable_image_bytes = sum(
        (img.get("Size") or 0) for img in images_list
        if not img.get("Containers")
    )

    volumes_list = df.get("Volumes") or []

    if project:
        scoped = _list_scoped_containers(True, sparse=True)
        running = paused = stopped = 0
        for c in scoped:
            state = (c.attrs.get("State") or "").lower()
            if state == "running":
                running += 1
            elif state == "paused":
                paused += 1
            else:
                stopped += 1
        container_counts = {
            "running": running,
            "paused": paused,
            "stopped": stopped,
            "total": len(scoped),
        }
        images_count = len(images_list)
        scoped_volume_names = {v.name for v in _list_scoped_volumes()}
        volumes_list = [v for v in volumes_list if v.get("Name") in scoped_volume_names]
    else:
        info = client.info()
        container_counts = {
            "running": info.get("ContainersRunning", 0),
            "paused": info.get("ContainersPaused", 0),
            "stopped": info.get("ContainersStopped", 0),
            "total": info.get("Containers", 0),
        }
        images_count = info.get("Images", 0)

    total_volume_bytes = sum(
        ((v.get("UsageData") or {}).get("Size") or 0) for v in volumes_list
    )

    compose_projects = get_compose_groups()

    return {
        "status": "ok",
        "project_scope": project,
        "containers": container_counts,
        "images": {
            "count": images_count,
            "total_bytes": total_image_bytes,
            "reclaimable_bytes": reclaimable_image_bytes,
        },
        "volumes": {
            "count": len(volumes_list),
            "total_bytes": total_volume_bytes,
        },
        "compose_project_count": len(compose_projects),
        "compose_projects": compose_projects,
    }


def stream_events(
    since: Optional[str] = None,
    until: Optional[str] = None,
    filters: Optional[dict] = None,
) -> Generator[dict, None, None]:
    """Generator yielding Docker daemon events."""
    client = _docker_client()
    kwargs: dict = {"decode": True}
    if since:
        kwargs["since"] = since
    if until:
        kwargs["until"] = until
    if filters:
        kwargs["filters"] = filters
    for event in client.events(**kwargs):
        yield event
