from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Generic envelope
# ---------------------------------------------------------------------------

class APIResponse(BaseModel):
    data: Any = None
    error: Optional[dict] = None


# ---------------------------------------------------------------------------
# Container schemas
# ---------------------------------------------------------------------------

class ContainerSummary(BaseModel):
    id: str
    short_id: str
    name: str
    image: str
    status: str          # running, exited, paused, …
    state: str           # created, running, paused, restarting, removing, exited, dead
    created: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    uptime_seconds: Optional[int] = None
    ports: dict
    labels: dict
    compose_project: Optional[str] = None
    compose_service: Optional[str] = None
    restart_policy: Optional[str] = None
    exit_code: Optional[int] = None


class ContainerDetail(ContainerSummary):
    image_id: str
    command: str
    env: list[str]
    mounts: list[dict]
    network_settings: dict
    host_config: dict
    platform: Optional[str] = None


class ContainerStats(BaseModel):
    id: str
    name: str
    cpu_percent: float
    memory_usage_bytes: int
    memory_limit_bytes: int
    memory_percent: float
    network_rx_bytes: int
    network_tx_bytes: int
    block_read_bytes: int
    block_write_bytes: int
    pids: int


# ---------------------------------------------------------------------------
# Log schemas
# ---------------------------------------------------------------------------

class LogOptions(BaseModel):
    tail: int = 100
    since: Optional[str] = None    # Unix timestamp or relative e.g. "1h"
    until: Optional[str] = None
    timestamps: bool = False


class LogSearchResult(BaseModel):
    container_id: str
    pattern: str
    matched_lines: list[str]
    total_matched: int
    truncated: bool


# ---------------------------------------------------------------------------
# Image schemas
# ---------------------------------------------------------------------------

class ImageSummary(BaseModel):
    id: str
    short_id: str
    tags: list[str]
    created: str
    size_bytes: int
    labels: dict


class ImageDetail(ImageSummary):
    architecture: Optional[str] = None
    os: Optional[str] = None
    author: Optional[str] = None
    comment: Optional[str] = None
    exposed_ports: dict
    env: list[str]
    cmd: Optional[list[str]] = None
    entrypoint: Optional[list[str]] = None


class ImagePullRequest(BaseModel):
    repository: str              # e.g. "nginx:latest"
    tag: Optional[str] = None


# ---------------------------------------------------------------------------
# Network schemas
# ---------------------------------------------------------------------------

class NetworkSummary(BaseModel):
    id: str
    name: str
    driver: str
    scope: str
    internal: bool
    attachable: bool
    ipam: dict
    labels: dict
    containers: dict             # container_id -> {name, ip}
    created: str


class NetworkCreateRequest(BaseModel):
    name: str
    driver: str = "bridge"
    internal: bool = False
    labels: Optional[dict] = None


# ---------------------------------------------------------------------------
# Volume schemas
# ---------------------------------------------------------------------------

class VolumeSummary(BaseModel):
    name: str
    driver: str
    mountpoint: str
    labels: dict
    scope: str
    created: Optional[str] = None


class VolumeCreateRequest(BaseModel):
    name: str
    driver: str = "local"
    labels: Optional[dict] = None


# ---------------------------------------------------------------------------
# System schemas
# ---------------------------------------------------------------------------

class SystemInfo(BaseModel):
    docker_version: str
    api_version: str
    kernel_version: str
    os: str
    os_type: str
    architecture: str
    total_memory_bytes: int
    ncpu: int
    containers_running: int
    containers_paused: int
    containers_stopped: int
    images_count: int
    server_version: str


class DiskUsage(BaseModel):
    images: list[dict]
    containers: list[dict]
    volumes: list[dict]
    build_cache: list[dict]
