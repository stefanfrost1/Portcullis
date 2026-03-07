"""
Thin wrapper around the Docker SDK.

All methods return plain dicts or primitives so that routers can
serialize them with Pydantic without touching the SDK objects directly.
"""

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from typing import Generator, Optional

import docker
from docker.errors import DockerException, NotFound, APIError
from docker.models.containers import Container

logger = logging.getLogger(__name__)

from datetime import timedelta

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


def _docker_client() -> docker.DockerClient:
    """Return a cached Docker client (lazy-initialised singleton)."""
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def close_docker_client() -> None:
    """Close the Docker client connection. Called from the app lifespan shutdown."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


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


# ---------------------------------------------------------------------------
# Container operations
# ---------------------------------------------------------------------------

def list_containers(all_containers: bool = True) -> list[dict]:
    client = _docker_client()
    containers = client.containers.list(all=all_containers)
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
    since: Optional[str] = None,
    until: Optional[str] = None,
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

    client = _docker_client()
    containers = client.containers.list(all=not running_only)

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
            "container_name": c.name.lstrip("/"),
            "matched_lines": display_lines,
            "matches": structured,
            "match_count": len(matched),
            "truncated": truncated,
        }

    results: list[dict] = []
    errors: list[dict] = []

    with ThreadPoolExecutor(max_workers=_GLOBAL_SEARCH_MAX_WORKERS) as pool:
        futures = {pool.submit(_search_one, c): c for c in containers}
        for future in as_completed(futures, timeout=_GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT + 5):
            c = futures[future]
            try:
                result = future.result(timeout=_GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT)
                if result["match_count"] > 0:
                    results.append(result)
            except FutureTimeoutError:
                errors.append({
                    "container_id": c.id,
                    "container_name": c.name.lstrip("/"),
                    "error": "search timeout",
                })
            except Exception as exc:
                errors.append({
                    "container_id": c.id,
                    "container_name": c.name.lstrip("/"),
                    "error": str(exc),
                })

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


def _pivot_window(pivot: str, window_seconds: int) -> tuple[str, str, str, str]:
    """Return (since_unix, until_unix, since_iso, until_iso) for a pivot ± window."""
    dt = datetime.fromisoformat(pivot.replace("Z", "+00:00"))
    since_dt = dt - timedelta(seconds=window_seconds)
    until_dt = dt + timedelta(seconds=window_seconds)
    return (
        str(int(since_dt.timestamp())),
        str(int(until_dt.timestamp())),
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

    client = _docker_client()
    containers = client.containers.list(all=not running_only)

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
            "container_name": c.name.lstrip("/"),
            "lines": lines,
            "count": len(lines),
        }

    results: list[dict] = []
    errors: list[dict] = []

    with ThreadPoolExecutor(max_workers=_GLOBAL_SEARCH_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, c): c for c in containers}
        for future in as_completed(futures, timeout=_GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT + 5):
            c = futures[future]
            try:
                result = future.result(timeout=_GLOBAL_SEARCH_PER_CONTAINER_TIMEOUT)
                if result["count"] > 0:
                    results.append(result)
            except FutureTimeoutError:
                errors.append({
                    "container_id": c.id,
                    "container_name": c.name.lstrip("/"),
                    "error": "fetch timeout",
                })
            except Exception as exc:
                errors.append({
                    "container_id": c.id,
                    "container_name": c.name.lstrip("/"),
                    "error": str(exc),
                })

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
    client = _docker_client()
    return [_volume_summary(v) for v in client.volumes.list()]


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


def get_disk_usage() -> dict:
    client = _docker_client()
    df = client.df()
    return {
        "images": df.get("Images") or [],
        "containers": df.get("Containers") or [],
        "volumes": df.get("Volumes") or [],
        "build_cache": df.get("BuildCache") or [],
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
    client = _docker_client()
    running = client.containers.list(all=False)

    stats_list: list[dict] = []
    errors: list[dict] = []

    def _fetch(c) -> dict:
        return get_container_stats(c.id)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch, c): c for c in running}
        for future in as_completed(futures, timeout=timeout_seconds + 5):
            c = futures[future]
            try:
                result = future.result(timeout=timeout_seconds)
                stats_list.append(result)
            except FutureTimeoutError:
                errors.append({"container_id": c.id, "name": c.name.lstrip("/"), "error": "stats timeout"})
            except Exception as exc:
                errors.append({"container_id": c.id, "name": c.name.lstrip("/"), "error": str(exc)})

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
    client = _docker_client()
    all_containers = client.containers.list(all=True)

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
    Makes two Docker API calls: info() and df().
    """
    client = _docker_client()
    info = client.info()
    df = client.df()

    images_list = df.get("Images") or []
    total_image_bytes = sum(img.get("Size", 0) for img in images_list)
    reclaimable_image_bytes = sum(
        img.get("Size", 0) for img in images_list
        if not img.get("Containers")
    )

    volumes_list = df.get("Volumes") or []
    total_volume_bytes = sum(
        (v.get("UsageData") or {}).get("Size", 0) for v in volumes_list
    )

    compose_projects = get_compose_groups()

    return {
        "containers": {
            "running": info.get("ContainersRunning", 0),
            "paused": info.get("ContainersPaused", 0),
            "stopped": info.get("ContainersStopped", 0),
            "total": info.get("Containers", 0),
        },
        "images": {
            "count": info.get("Images", 0),
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
