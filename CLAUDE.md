# CLAUDE.md — Portcullis

This file provides context, conventions, and workflows for AI assistants (and human developers) working in this repository.

---

## Repository Overview

| Field       | Value                                                                 |
|-------------|-----------------------------------------------------------------------|
| **Name**    | Portcullis                                                            |
| **Remote**  | stefanfrost1/Portcullis                                               |
| **Branch**  | Work on feature branches; never push directly to `main`              |
| **Purpose** | REST + WebSocket bridge between a UI and Docker daemon / Redis       |
| **Runtime** | Python 3.12, FastAPI 0.115, Uvicorn 0.34                            |
| **Version** | 3.1.0 (see `src/main.py`)                                            |

---

## What This Service Does

Portcullis shields a UI from direct Docker socket and Redis access. It exposes three groups of functionality over a single FastAPI application:

1. **Docker management** — containers (list, inspect, stats, lifecycle), images, networks, volumes, system info, disk usage, and a real-time Docker events WebSocket stream.
2. **Log access** — per-container tail/stream/search and a cross-container global search with timestamp-aware context windows.
3. **Redis management** — key browser (string/hash/list/set/zset/stream CRUD), server ops (INFO, CONFIG, BGSAVE, FLUSHDB, …), pub/sub, MONITOR stream, keyspace analysis, slow log, memory stats, latency tracking, and queue-depth monitoring.
4. **Aggregate overview** — a single `GET /api/v1/overview` endpoint that combines Docker + Redis high-level stats for monitoring dashboards.

Neither the Docker socket nor Redis is exposed to the UI directly. Destructive and administrative operations are restricted to the `admin` role via Caddy-injected headers (see [RBAC](#rbac--caddy-header-auth) below).

---

## Repository Structure

```
Portcullis/
├── CLAUDE.md                    # This file
├── Dockerfile                   # Python 3.12-slim, non-root user, port 8000
├── build.sh                     # Manual build/push helper (Linux/macOS)
├── build.ps1                    # Manual build/push helper (Windows)
├── docker-compose.yml           # Full stack: prebuilt images + Redis
├── requirements.txt             # Backend Python dependencies
├── .github/
│   └── workflows/
│       └── docker-build.yml     # CI: build + push both images to Docker Hub
├── frontend/
│   ├── Dockerfile               # Python 3.12-slim, Streamlit, port 8501
│   ├── app.py                   # Streamlit app entrypoint + navigation
│   ├── requirements.txt         # Frontend Python dependencies
│   ├── .streamlit/
│   │   └── config.toml          # Streamlit server config
│   ├── app_pages/
│   │   ├── Dashboard.py         # Combined Docker + Redis overview
│   │   ├── 1_Containers.py      # Container list, inspect, lifecycle
│   │   ├── 2_Images.py          # Image list, pull, remove
│   │   ├── 3_Networks.py        # Network list, inspect, create, remove
│   │   ├── 4_Volumes.py         # Volume list, inspect, create, remove
│   │   ├── 5_System.py          # Docker system info and disk usage
│   │   ├── 6_Redis_Keys.py      # Redis key browser
│   │   ├── 7_Redis_Server.py    # Redis server ops and monitoring
│   │   ├── 8_Redis_Analysis.py  # Keyspace analysis, memory-top, expiring-soon
│   │   ├── 9_Redis_Queues.py    # Queue depth monitoring
│   │   └── 10_Log_Search.py     # Per-container and global log search
│   └── utils/
│       ├── api_client.py        # Typed API client for all backend endpoints
│       └── formatting.py        # Shared display helpers
└── src/
    ├── main.py                  # FastAPI app, middleware, router registration
    ├── config.py                # Pydantic-settings config (env vars)
    ├── __init__.py
    ├── models/
    │   ├── schemas.py           # Docker-facing Pydantic models + APIResponse envelope
    │   └── redis_schemas.py     # Redis request/body Pydantic models
    ├── routers/
    │   ├── _auth.py             # RBAC dependency (get_role / require_admin)
    │   ├── _docker_errors.py    # Shared Docker exception → HTTPException helper
    │   ├── containers.py        # /containers — list, inspect, stats, lifecycle
    │   ├── logs.py              # /containers/{id}/logs + /logs global router
    │   ├── images.py            # /images — list, inspect, pull, remove, prune
    │   ├── networks.py          # /networks — list, inspect, create, remove
    │   ├── volumes.py           # /volumes — list, inspect, create, remove, prune
    │   ├── system.py            # /system/info, /system/df, WS /system/events, /health
    │   ├── overview.py          # /overview — combined Docker + Redis snapshot
    │   ├── redis_keys.py        # /redis/keys — key browser + type operations
    │   ├── redis_server.py      # /redis — server ops, pub/sub, MONITOR WS, analysis
    │   └── redis_queues.py      # /redis/queues — queue depth monitoring
    └── services/
        ├── docker_service.py    # Docker SDK wrapper (lazy singleton client)
        └── redis_service.py     # Redis connection pool wrapper
```

---

## API Reference

All endpoints are under the base path `/api/v1`. Paths in the tables below are relative to that prefix.

### Interactive docs

| UI       | URL                     |
|----------|-------------------------|
| Swagger  | `/api/v1/docs`          |
| ReDoc    | `/api/v1/redoc`         |
| OpenAPI  | `/api/v1/openapi.json`  |

### Admin restriction legend

🔒 = requires `admin` role (Caddy `X-User-Groups: authp/admin` header). See [RBAC](#rbac--caddy-header-auth).

### Container endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/containers` | List all (or running-only) containers |
| GET | `/containers/stats/all` | Parallel CPU/mem/IO stats for all running containers |
| GET | `/containers/groups` | Containers grouped by Compose project label |
| GET | `/containers/{id}` | 🔒 Inspect a single container |
| GET | `/containers/{id}/stats` | Single-snapshot CPU/mem/net/block I/O stats |
| POST | `/containers/{id}/start` | Start a container |
| POST | `/containers/{id}/stop` | 🔒 Stop a container (`timeout` param) |
| POST | `/containers/{id}/restart` | 🔒 Restart a container (`timeout` param) |
| POST | `/containers/{id}/pause` | 🔒 Pause a running container |
| POST | `/containers/{id}/unpause` | 🔒 Unpause a paused container |
| DELETE | `/containers/{id}` | **Always 403** — container removal is disabled |

### Log endpoints

Per-container (router prefix `/containers`):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/containers/{id}/logs` | Fetch up to 2000 tail lines (`since`, `until`, `timestamps` params) |
| GET | `/containers/{id}/logs/search` | Egrep-style regex search within one container's logs |
| GET | `/containers/{id}/logs/context` | Lines within ±`window_seconds` of an ISO pivot timestamp |
| WS  | `/containers/{id}/logs/stream` | WebSocket live log tail (one JSON object per line) |
| GET | `/containers/{id}/logs/stream` | SSE live log tail (alternative to WebSocket) |

Global cross-container (router prefix `/logs`):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/logs` | Fetch last N lines from all running containers in parallel |
| GET | `/logs/search` | Egrep-style regex search across all containers (parallel) |
| GET | `/logs/context` | Lines from all containers within ±`window_seconds` of a pivot |

### Image endpoints

All image endpoints require 🔒 admin.

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/images` | List images (`all_images` includes intermediate layers) |
| GET    | `/images/{id}` | Inspect image |
| POST   | `/images/pull` | Pull image from registry (body: `{repository, tag}`) |
| POST   | `/images/prune` | Remove dangling images |
| DELETE | `/images/{id}` | Remove image (`force`, `no_prune` params) |

### Network endpoints

All network endpoints require 🔒 admin.

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/networks` | List networks |
| GET    | `/networks/{id}` | Inspect network |
| POST   | `/networks` | Create network (body: `{name, driver, internal, labels}`); returns 201 |
| DELETE | `/networks/{id}` | Remove network |

### Volume endpoints

All volume endpoints require 🔒 admin.

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/volumes` | List volumes |
| GET    | `/volumes/{name}` | Inspect volume |
| POST   | `/volumes` | Create volume (body: `{name, driver, labels}`); returns 201 |
| POST   | `/volumes/prune` | Remove unused volumes |
| DELETE | `/volumes/{name}` | Remove volume (`force` param) |

### System endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/system/info` | Docker daemon info + version |
| GET | `/system/df` | Disk usage breakdown (cached `DISK_USAGE_CACHE_TTL` seconds; own longer `DISK_USAGE_TIMEOUT`; `?refresh=true` to recompute; 503 with reason if the daemon call times out/fails) |
| WS  | `/system/events` | Real-time Docker daemon event stream |
| GET | `/health` | Health check — 200 if Docker reachable, 503 otherwise |

### Redis — Key browser

Read operations are open; write/destructive operations require 🔒 admin.

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/redis/keys` | SCAN keys (pattern, type, cursor, count) |
| GET    | `/redis/keys/count` | DBSIZE shortcut |
| DELETE | `/redis/keys` | 🔒 DEL multiple keys (body: `{keys: [...]}`) |
| GET    | `/redis/keys/{key}` | Get key value + metadata (auto-detects type, paginates) |
| PUT    | `/redis/keys/{key}` | 🔒 Create/overwrite key |
| DELETE | `/redis/keys/{key}` | 🔒 DEL single key |
| GET    | `/redis/keys/{key}/ttl` | TTL + PTTL |
| POST   | `/redis/keys/{key}/expire` | 🔒 Set TTL (EXPIRE); `ttl≤0` calls PERSIST |
| POST   | `/redis/keys/{key}/persist` | 🔒 Remove TTL (PERSIST) |
| GET    | `/redis/keys/{key}/metadata` | type, encoding, refcount, idletime, memory |
| GET    | `/redis/keys/{key}/dump` | DUMP key as base64 |
| POST   | `/redis/keys/{key}/rename` | 🔒 RENAME / RENAMENX |
| POST   | `/redis/keys/{key}/copy` | 🔒 COPY key (optionally to another DB) |
| GET    | `/redis/keys/{key}/hash` | HGETALL |
| GET    | `/redis/keys/{key}/hash/fields` | HKEYS |
| GET    | `/redis/keys/{key}/hash/{field}` | HGET single field |
| POST   | `/redis/keys/{key}/hash/{field}` | 🔒 HSET single field |
| DELETE | `/redis/keys/{key}/hash/{field}` | 🔒 HDEL single field |
| GET    | `/redis/keys/{key}/list` | LRANGE (paginated) |
| POST   | `/redis/keys/{key}/list/push` | 🔒 LPUSH / RPUSH |
| POST   | `/redis/keys/{key}/list/pop` | 🔒 LPOP / RPOP |
| POST   | `/redis/keys/{key}/list/remove` | 🔒 LREM — remove by value |
| PUT    | `/redis/keys/{key}/list/{index}` | 🔒 LSET — set item at index |
| GET    | `/redis/keys/{key}/set` | SMEMBERS |
| GET    | `/redis/keys/{key}/set/random` | SRANDMEMBER |
| POST   | `/redis/keys/{key}/set/add` | 🔒 SADD |
| GET    | `/redis/keys/{key}/set/{member}/ismember` | SISMEMBER |
| DELETE | `/redis/keys/{key}/set/{member}` | 🔒 SREM |
| GET    | `/redis/keys/{key}/zset` | ZRANGE with scores (paginated; `reverse` param) |
| GET    | `/redis/keys/{key}/zset/range-by-score` | ZRANGEBYSCORE (`min`/`max` score filter) |
| POST   | `/redis/keys/{key}/zset/add` | 🔒 ZADD (`nx`/`xx` flags) |
| GET    | `/redis/keys/{key}/zset/{member}/score` | ZSCORE + ZRANK + ZREVRANK |
| DELETE | `/redis/keys/{key}/zset/{member}` | 🔒 ZREM |
| GET    | `/redis/keys/{key}/stream` | XRANGE (paginated) |
| GET    | `/redis/keys/{key}/stream/info` | XINFO STREAM |
| POST   | `/redis/keys/{key}/stream/add` | 🔒 XADD — append stream entry |
| DELETE | `/redis/keys/{key}/stream/{entry_id}` | 🔒 XDEL — remove stream entry |

### Redis — Server

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/redis/info` | Redis INFO (optional `section` param) |
| GET  | `/redis/databases` | Per-DB key/expire counts |
| GET  | `/redis/dbsize` | DBSIZE |
| GET  | `/redis/summary` | Dashboard summary — server, clients, memory, perf, keyspace, replication |
| GET  | `/redis/replication` | Replication status — role, replicas, offsets, lag |
| GET  | `/redis/performance` | Performance metrics — ops/sec, hit rate, eviction, I/O |
| GET  | `/redis/config` | CONFIG GET (`pattern` param) |
| POST | `/redis/config` | 🔒 CONFIG SET (body: `{parameter, value}`) |
| POST | `/redis/config/rewrite` | 🔒 CONFIG REWRITE |
| POST | `/redis/config/resetstat` | 🔒 CONFIG RESETSTAT |
| POST | `/redis/bgsave` | 🔒 BGSAVE |
| POST | `/redis/bgrewriteaof` | 🔒 BGREWRITEAOF |
| POST | `/redis/flushdb` | 🔒 FLUSHDB (requires `?confirm=true`) |
| POST | `/redis/flushall` | 🔒 FLUSHALL (requires `?confirm=true`) |
| GET  | `/redis/clients` | CLIENT LIST |
| POST | `/redis/clients/kill` | 🔒 CLIENT KILL by `addr` or `client_id` |
| GET  | `/redis/slowlog` | SLOWLOG GET (`count` param) |
| GET  | `/redis/slowlog/len` | SLOWLOG LEN |
| POST | `/redis/slowlog/reset` | 🔒 SLOWLOG RESET |
| GET  | `/redis/memory/stats` | MEMORY STATS + MEMORY DOCTOR |
| GET  | `/redis/memory/malloc-stats` | MEMORY MALLOC-STATS |
| GET  | `/redis/latency/latest` | LATENCY LATEST |
| GET  | `/redis/latency/history/{event}` | LATENCY HISTORY for one event |
| POST | `/redis/latency/reset` | 🔒 LATENCY RESET |
| GET  | `/redis/pubsub/channels` | PUBSUB CHANNELS (`pattern` param) |
| GET  | `/redis/pubsub/numsub` | PUBSUB NUMSUB (repeatable `channels` param) |
| GET  | `/redis/pubsub/numpat` | PUBSUB NUMPAT |
| POST | `/redis/pubsub/publish` | 🔒 PUBLISH (body: `{channel, message}`) |
| WS   | `/redis/pubsub/subscribe` | Live pub/sub subscriber stream |
| WS   | `/redis/monitor` | 🔒 MONITOR command stream |
| GET  | `/redis/analysis/keyspace` | Type + prefix + TTL distribution (sample-based) |
| GET  | `/redis/analysis/memory-top` | Top-N keys by memory (sample-based) |
| GET  | `/redis/analysis/expiring-soon` | Keys expiring within N seconds |
| POST | `/redis/eval` | 🔒 EVAL — execute Lua script (body: `{script, keys, args}`) |
| GET  | `/redis/health` | Redis connectivity check |

### Redis — Queues

| Method | Path | Description |
|--------|------|-------------|
| GET | `/redis/queues` | Scan for List + Stream keys; return depths sorted descending |
| GET | `/redis/queues/{key}` | Deep-dive: List depth + sample, or Stream groups + pending |

### Overview

| Method | Path | Description |
|--------|------|-------------|
| GET | `/overview` | Combined Docker + Redis snapshot; always returns HTTP 200 |

### Response envelope

All REST responses use this JSON shape:

```json
{ "data": { ... }, "error": null }
```

Error response:

```json
{
  "data": null,
  "error": { "code": "NOT_FOUND", "message": "Resource not found" }
}
```

HTTP status codes are used semantically. The `/overview` endpoint always returns 200; check the `"status": "error"` field inside each subsection for partial failures.

---

## Development Setup

### Prerequisites

- Python 3.12+
- Docker daemon running (socket at `/var/run/docker.sock`)
- Redis instance reachable at the configured host/port

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Locally

```bash
uvicorn src.main:app --reload --port 8000
```

Or via Docker Compose (recommended — includes Docker socket mount and Redis):

```bash
docker compose up --build
```

### Environment Variables

Application settings live in `src/config.py` and are loaded from environment. Build/deploy variables (`REGISTRY`, `IMAGE_TAG`) are read by `docker-compose.yml` — not by the app at runtime.

| Variable                | Default                                      | Description                                         |
|-------------------------|----------------------------------------------|-----------------------------------------------------|
| `PORT`                  | `8000`                                       | Uvicorn listen port                                 |
| `CORS_ORIGINS`          | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed origins; `*` only for local |
| `API_KEY_ENABLED`       | `false`                                      | Set `true` to require `X-API-Key` on all requests   |
| `API_KEY`               | `""`                                         | The expected key value when auth is enabled         |
| `DEBUG`                 | `false`                                      | Enables `DEBUG`-level logging                       |
| `DOCKER_TIMEOUT`        | `30`                                         | Docker SDK client timeout (seconds)                 |
| `DOCKER_MAX_POOL_SIZE`  | `32`                                         | Docker SDK connection pool size                     |
| `DISK_USAGE_CACHE_TTL`  | `60`                                         | Seconds to cache `GET /system/df` results           |
| `DISK_USAGE_TIMEOUT`    | `120`                                        | Dedicated (longer) socket timeout for the expensive `docker system df` call |
| `COMPOSE_PROJECT`       | `""`                                         | Scope operational Docker views (containers/volumes/logs) to one exact Compose project (see [Project scoping](#project-scoping)); empty = host-wide |
| `COMPOSE_PROJECTS`      | `""`                                         | Comma-separated list of exact Compose project names to scope to (OR) |
| `COMPOSE_PROJECT_PREFIX`| `""`                                         | Scope to every Compose project whose name starts with this prefix |
| `REDIS_HOST`            | `redis`                                      | Redis hostname (use service name in Compose)        |
| `REDIS_PORT`            | `6379`                                       | Redis port                                          |
| `REDIS_PASSWORD`        | `null`                                       | Redis password (omit if not set)                    |
| `REDIS_DB`              | `0`                                          | Default Redis database index (0–15)                 |

Build/deploy-only variables (not app config):

| Variable    | Used by | Default | Description |
|-------------|---------|---------|-------------|
| `REGISTRY`  | docker-compose | `simplitics1` | Docker Hub namespace prefix for image names |
| `IMAGE_TAG` | docker-compose | `latest` | Tag of the prebuilt images Compose pulls |

The `build.sh`/`build.ps1` scripts take the registry and tag as flags (`-r`/`-t`, `-Registry`/`-Tag`) rather than environment variables; the tag defaults to the version in `src/main.py`.

**Production checklist:**

- Set `API_KEY_ENABLED=true` and `API_KEY=<strong-secret>`
- Set `CORS_ORIGINS` to your UI's actual origin(s) — never `*`
- Deploy behind Caddy (or another reverse proxy) that injects `X-User-Groups` for RBAC
- Never commit secrets to the repository

---

## Architecture Notes

### Middleware stack (applied in order)

1. **CORS** — configured from `CORS_ORIGINS`; `allow_credentials=True` is automatically disabled when `*` is used
2. **Security headers** — `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`
3. **Request ID** — attaches/echoes `X-Request-ID` header on every response
4. **Request logging** — logs method, path, response status, latency, caller host (`X-Forwarded-For` first hop, else socket peer), and request ID
5. **API key auth** — checks `X-API-Key` header when `API_KEY_ENABLED=true`; docs, OpenAPI, `/health`, and `/` are always exempt

### RBAC / Caddy header auth

`src/routers/_auth.py` provides two FastAPI dependencies:

- `get_role()` — reads the `X-User-Groups` header (injected by Caddy after authentication). Maps `authp/admin` → `admin`, `authp/user` → `developer`, anything else → `reader`.
- `require_admin()` — raises `HTTP 403` if the role is not `admin`.

Routers that perform mutations (write, delete, lifecycle actions) declare `require_admin` as a dependency on individual routes or at the router level. When running without Caddy (local dev), the header is absent, so all callers are treated as `reader` — admin-only endpoints will return 403 unless the header is spoofed or the dependency is bypassed in dev.

### Service layer

- `docker_service.py` — lazy-initialised singleton `docker.DockerClient`. All methods return plain dicts/primitives; no SDK objects leak into routers.
- `redis_service.py` — connection pool wrapper (separate decoded + binary pools per DB). Pools are closed cleanly on shutdown via the FastAPI lifespan handler.

### Project scoping

Scope the operational Docker views to one **or more** Compose projects via the
`com.docker.compose.project` label. Three selectors, combined with OR:

| Env var | Meaning |
|---------|---------|
| `COMPOSE_PROJECT` | a single exact project name |
| `COMPOSE_PROJECTS` | comma-separated list of exact project names |
| `COMPOSE_PROJECT_PREFIX` | match any project whose name starts with this prefix |

Use a single one, or combine them (e.g. a prefix plus a couple of extra exact
names). All empty (default) = host-wide, unchanged.

**How filtering happens** (`_project_filters()` + the `_list_scoped_*` helpers):

- A **single exact** name is pushed to the daemon as an exact label filter — the
  daemon returns only that project's resources (cheapest; no inspect of others).
- A **list or prefix** cannot be expressed by Docker's label filter (no OR, no
  prefix), so the daemon is asked only for resources that *have* a
  compose-project label and Portcullis narrows them in-process via
  `_project_matches()` (`_needs_client_narrow()` gates this).

Scope surface:

- **Scoped:** container list/stats/groups, the global log endpoints
  (`/logs`, `/logs/search`, `/logs/context`), volumes, and the
  container/volume/compose sections of `/overview` (which also carries a
  `project_scope` description field).
- **Not scoped (host-wide reference):** images and networks — reference
  resources, and Compose does not stamp the project label on pulled images, so
  filtering images would hide all of them. Also unscoped: single-resource
  inspects by id/name (a caller with an id already has the resource).

Independently of scoping, the fan-out helpers (`/containers/stats/all` and the
global log endpoints) list containers with `sparse=True` — they only need id +
name, so they skip the per-container inspect that the SDK's default listing
does. Use `_container_name()` to read a name off a sparse model, and
`_container_project()` to read its compose-project label.

The frontend's own `COMPOSE_PROJECT` (optional, cosmetic) only drives a
"Scoped to project" caption on the Containers, Volumes, and Dashboard pages; the actual
scoping is entirely backend-side.

### Error handling

- **Router level:** Docker exceptions are translated by `_docker_errors.handle_docker_exc()` into typed `HTTPException` responses (`404`, `409`, `503`, etc.).
- **Global fallback:** `unhandled_exception_handler` in `main.py` logs the full traceback internally and returns a generic `500` — stack traces are never exposed to clients.

### WebSocket / streaming endpoints

| Path | Description |
|------|-------------|
| `/api/v1/system/events` | Docker daemon event stream |
| `/api/v1/containers/{id}/logs/stream` | Live log tail (WebSocket) |
| `/api/v1/containers/{id}/logs/stream` | Live log tail (SSE, same path, HTTP GET) |
| `/api/v1/redis/pubsub/subscribe` | Redis pub/sub subscription stream |
| `/api/v1/redis/monitor` | 🔒 Redis MONITOR command stream |

### Lifespan

On startup the app pings both Docker and Redis and logs warnings (not errors) if either is unreachable — endpoints return `503` dynamically if a dependency is unavailable, but the service always starts. On shutdown, `close_docker_client()` and `rs.close_all_pools()` are called.

---

## Frontend

The Streamlit frontend (`frontend/`) uses Streamlit's explicit `st.navigation` API. Pages are grouped in the sidebar:

| Group | Page | File |
|-------|------|------|
| Overview | Dashboard (renamable) | `app_pages/Dashboard.py` |
| Docker | System | `app_pages/5_System.py` |
| Docker | Logs | `app_pages/10_Log_Search.py` |
| Docker | Containers | `app_pages/1_Containers.py` |
| Redis | Redis Server | `app_pages/7_Redis_Server.py` |
| Redis | Redis Queues | `app_pages/9_Redis_Queues.py` |
| Redis | Redis Keys | `app_pages/6_Redis_Keys.py` |
| Redis | Redis Analysis | `app_pages/8_Redis_Analysis.py` |
| Resources | Volumes | `app_pages/4_Volumes.py` |
| Resources | Networks | `app_pages/3_Networks.py` |
| Resources | Images | `app_pages/2_Images.py` |

Volumes, networks, and images sit in a **Resources** section below the day-to-day operational pages (volumes are still project-scoped when `COMPOSE_PROJECT` is set; networks and images stay host-wide). The Containers detail view has a **📋 View logs** button that preselects the container (via `st.session_state`) and jumps to the Logs page.

All API calls go through `frontend/utils/api_client.py`, which wraps every backend endpoint in a typed Python method. Add new API methods there when adding endpoints. `frontend/utils/formatting.py` holds shared display helpers (byte formatting, uptime strings, etc.).

The frontend connects to the backend via the `MYENGINE_URL` environment variable (default: `http://portcullis:8000`). Optional `MYENGINE_API_KEY` sets the `X-API-Key` header when the backend has key auth enabled. `DASHBOARD_TITLE` (or `PROJECT_NAME`) renames the overview page's nav item and header (default `Dashboard`). The scope-mirror vars (`COMPOSE_PROJECT` / `COMPOSE_PROJECTS` / `COMPOSE_PROJECT_PREFIX`) are cosmetic on the frontend — they only drive the "Scoped to project(s)" caption; set them to match the backend so the UI labels the subset.

---

## Testing

No automated tests exist yet. When adding tests:

- Place unit tests in `tests/unit/`
- Place integration tests in `tests/integration/`
- Run with `pytest`
- Do not commit code that breaks existing tests

The interactive Swagger UI at `/api/v1/docs` can be used for manual endpoint testing against a live Docker + Redis environment.

---

## Build & Deployment

### Images

| Image name | Source | Port |
|---|---|---|
| `portcullis` | `Dockerfile` (repo root) | 8000 |
| `portcullis-frontend` | `frontend/Dockerfile` | 8501 |

Both images are published to Docker Hub under the **`simplitics1`** namespace
(`simplitics1/portcullis`, `simplitics1/portcullis-frontend`) — the only place
they are published.

### GitHub Actions is the builder

`.github/workflows/docker-build.yml` is the canonical build path: it builds and
pushes both images to Docker Hub on every push to `main`, `master`,
`feature/**`, and `release/**` (and via manual `workflow_dispatch`). You
normally never build locally — merging to a branch is what publishes an image.
Tagging:

| Branch | Tag |
|--------|-----|
| `main` / `master` | `:latest` |
| `feature/foo` | `:feature-foo` |
| `release/1.2.0` | `:release-1.2.0` |

Requires repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

### Building locally (manual fallback)

For local iteration without waiting on CI. `build.sh` (Linux/macOS) and
`build.ps1` (Windows) build both images, default the tag to the version in
`src/main.py` (plus `latest`), and push to Docker Hub `simplitics1`:

```bash
./build.sh                 # build both; tag from src/main.py + latest
./build.sh -t 3.2.0 -p     # build and push (run 'docker login' first)
./build.sh -s frontend     # frontend only
./build.sh -r myorg -p     # override registry/namespace
```

```powershell
./build.ps1 -Tag 3.2.0 -Push
```

### Running the stack

`docker-compose.yml` pulls the prebuilt `simplitics1` images (the backend also
has a `build:` block, so `--build` still works). `IMAGE_TAG` selects the tag:

```bash
docker compose pull
docker compose up -d
IMAGE_TAG=3.1.0 docker compose up -d     # pin a specific tag
```

### Using pre-built images in other Compose setups

Reference the published images directly — no source code required:

```yaml
services:
  portcullis:
    image: simplitics1/portcullis:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - REDIS_HOST=redis

  frontend:
    image: simplitics1/portcullis-frontend:latest
    environment:
      - MYENGINE_URL=http://portcullis:8000
```

### Run standalone (no Compose)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e REDIS_HOST=<redis-host> \
  -p 8000:8000 \
  simplitics1/portcullis:latest
```

The Dockerfile uses `python:3.12-slim`, creates a non-root user (`appuser`, UID 1000), installs dependencies before copying source (layer-cache friendly), and exposes port `8000`.

---

## Git Workflow

### Branching

- `main` — stable, production-ready code; no direct pushes
- Feature branches: `feature/<short-description>`
- Bug fixes: `fix/<short-description>`
- Claude AI branches: `claude/<session-id>`

### Commit Messages

Use conventional commit format:

```
<type>(<scope>): <short summary>

<optional body>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples:
```
feat(logs): add global cross-container log search endpoint
fix(containers): handle 409 conflict on remove
docs: update CLAUDE.md with actual API surface
```

### Pull Requests

- All changes go through PRs; direct pushes to `main` are discouraged
- PRs should describe what changed and why
- Link relevant issues

---

## Code Conventions

### Language & Framework

- Python 3.12, FastAPI, Pydantic v2, `pydantic-settings`
- `snake_case` everywhere (Python convention)

### Router pattern

Each router module:
1. Declares an `APIRouter` with a `prefix` and `tags`
2. Uses `require_admin` dependency on routes that mutate state
3. Catches service-layer exceptions and raises `HTTPException`
4. Wraps return values in `APIResponse(data=...)`

### Model pattern

- `src/models/schemas.py` — Docker-domain models + generic `APIResponse` envelope
- `src/models/redis_schemas.py` — Redis request body models

Do not add fields to response models that the service layer does not actually return.

### Service layer

- Services hold the external-dependency logic (Docker SDK calls, Redis commands)
- Services return plain dicts/primitives — never SDK objects
- Connection lifecycle is managed by the lifespan context manager in `main.py`

### Security

- Never commit secrets or credentials
- Validate all user input at router boundaries (Pydantic models + Query params with `ge`/`le` constraints)
- Destructive operations (`flushdb`, `flushall`) require both admin role **and** `?confirm=true`
- Container removal is permanently disabled (returns 403) — remove containers via Docker directly

---

## For AI Assistants

### Key Principles

1. **Read before editing.** Always read relevant files before making changes.
2. **Minimal changes.** Only change what is necessary to fulfill the request.
3. **No speculation.** Do not add features, error handling, or abstractions that weren't asked for.
4. **Branch discipline.** Always work on the designated branch; never push to `main` directly.
5. **Commit clearly.** Write descriptive commit messages that explain the "why."
6. **No secrets.** Never commit environment variables, tokens, or credentials.
7. **Admin awareness.** New mutation endpoints must use `Depends(require_admin)` from `_auth.py`.

### Branch for AI Work

Claude agents must develop on branches matching the pattern `claude/<session-id>`. Push to that branch and open a PR — do not merge to `main`.

### Common Tasks

| Task | Command |
|------|---------|
| Install dependencies | `pip install -r requirements.txt` |
| Run dev server | `uvicorn src.main:app --reload --port 8000` |
| Run full stack | `docker compose up --build` |
| Run tests | `pytest` (no tests yet — add to `tests/`) |
| Lint | `flake8 src/` or `ruff check src/` |
| Format | `black src/` |
| Type check | `mypy src/` |
| Publish images | push to a branch — GitHub Actions builds + pushes to `simplitics1` |
| Build locally (manual) | `./build.sh` / `./build.ps1` |

### Adding a new router

1. Create `src/routers/<name>.py` with an `APIRouter`
2. Import `require_admin` from `_auth.py` and apply it to mutation routes
3. Import and register the router in `src/main.py` with `app.include_router(..., prefix=API_PREFIX)`
4. Add request/response models to `src/models/schemas.py` or `src/models/redis_schemas.py`
5. Add service logic to the appropriate file in `src/services/`
6. Add frontend API client methods to `frontend/utils/api_client.py`
7. Add a page to `frontend/app_pages/` and register it in `frontend/app.py`

### Adding a new environment variable

1. Add a typed field with a default to the `Settings` class in `src/config.py`
2. Document it in the Environment Variables table in this file

---

## Maintenance

This CLAUDE.md should be updated whenever:

- New routers, endpoints, or services are added
- The frontend gains new pages or navigation groups
- Environment variables change
- Development workflows change
- New conventions are adopted by the team

*Last updated: 2026-08-11 (re-synced on main after merge — Portcullis rename, RBAC, log search, GitHub Actions CI, build.sh/build.ps1 + Docker Hub simplitics1, df caching)*
