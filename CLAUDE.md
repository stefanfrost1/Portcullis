# CLAUDE.md — MyEngineAPI

This file provides context, conventions, and workflows for AI assistants (and human developers) working in this repository.

---

## Repository Overview

| Field       | Value                                                                 |
|-------------|-----------------------------------------------------------------------|
| **Name**    | MyEngineAPI                                                           |
| **Remote**  | stefanfrost1/MyEngineAPI                                              |
| **Branch**  | Work on feature branches; never push directly to `main`              |
| **Purpose** | REST + WebSocket bridge between a UI and Docker daemon / Redis       |
| **Runtime** | Python 3.12, FastAPI 0.115, Uvicorn 0.34                            |
| **Version** | 3.1.0 (see `src/main.py`)                                            |

---

## What This Service Does

MyEngineAPI shields a UI from direct Docker socket and Redis access. It exposes two groups of functionality over a single FastAPI application:

1. **Docker management** — containers (list, inspect, stats, lifecycle, remove), images, networks, volumes, system info, disk usage, and a real-time Docker events WebSocket stream.
2. **Redis management** — key browser (string/hash/list/set/zset/stream CRUD), server ops (INFO, CONFIG, BGSAVE, FLUSHDB, …), pub/sub, MONITOR stream, keyspace analysis, slow log, memory stats, latency tracking, and queue-depth monitoring.
3. **Aggregate overview** — a single `GET /api/v1/overview` endpoint that combines Docker + Redis high-level stats for monitoring dashboards.

Neither the Docker socket nor Redis is exposed to the UI directly.

---

## Repository Structure

```
MyEngineAPI/
├── CLAUDE.md                    # This file
├── Dockerfile                   # Python 3.12-slim, non-root user, port 8000
├── docker-compose.yml           # Drop-in service definition with Docker socket mount
├── requirements.txt             # Python dependencies
└── src/
    ├── main.py                  # FastAPI app, middleware, router registration
    ├── config.py                # Pydantic-settings config (env vars)
    ├── __init__.py
    ├── models/
    │   ├── schemas.py           # Docker-facing Pydantic models + APIResponse envelope
    │   └── redis_schemas.py     # Redis request/body Pydantic models
    ├── routers/
    │   ├── containers.py        # /containers — list, inspect, stats, lifecycle
    │   ├── logs.py              # /containers/{id}/logs/…
    │   ├── images.py            # /images — list, inspect, pull, remove
    │   ├── networks.py          # /networks — list, inspect, create, remove
    │   ├── volumes.py           # /volumes — list, inspect, create, remove
    │   ├── system.py            # /system/info, /system/df, WS /system/events, /health
    │   ├── overview.py          # /overview — combined Docker + Redis snapshot
    │   ├── redis_keys.py        # /redis/keys — key browser + type operations
    │   ├── redis_server.py      # /redis — server ops, pub/sub, MONITOR WS, analysis
    │   ├── redis_queues.py      # /redis/queues — queue depth monitoring
    │   └── _docker_errors.py    # Shared Docker exception → HTTPException helper
    └── services/
        ├── docker_service.py    # Docker SDK wrapper (lazy singleton client)
        └── redis_service.py     # Redis connection pool wrapper
```

---

## API Reference

All endpoints are under the base path `/api/v1`.

### Interactive docs

| UI       | URL                     |
|----------|-------------------------|
| Swagger  | `/api/v1/docs`          |
| ReDoc    | `/api/v1/redoc`         |
| OpenAPI  | `/api/v1/openapi.json`  |

### Docker endpoints

| Method | Path                              | Description                                  |
|--------|-----------------------------------|----------------------------------------------|
| GET    | `/containers`                     | List all (or running-only) containers        |
| GET    | `/containers/stats/all`           | Parallel CPU/mem/IO stats for all containers |
| GET    | `/containers/groups`              | Containers grouped by Compose project        |
| GET    | `/containers/{id}`                | Inspect a single container                   |
| GET    | `/containers/{id}/stats`          | Single-container resource stats              |
| POST   | `/containers/{id}/start`          | Start container                              |
| POST   | `/containers/{id}/stop`           | Stop container                               |
| POST   | `/containers/{id}/restart`        | Restart container                            |
| POST   | `/containers/{id}/pause`          | Pause container                              |
| POST   | `/containers/{id}/unpause`        | Unpause container                            |
| DELETE | `/containers/{id}`                | Remove container                             |
| GET    | `/containers/{id}/logs/…`         | Log streaming (see logs router)              |
| GET    | `/images`                         | List images                                  |
| GET    | `/images/{id}`                    | Inspect image                                |
| POST   | `/images/pull`                    | Pull an image                                |
| DELETE | `/images/{id}`                    | Remove image                                 |
| GET    | `/networks`                       | List networks                                |
| GET    | `/networks/{id}`                  | Inspect network                              |
| POST   | `/networks`                       | Create network                               |
| DELETE | `/networks/{id}`                  | Remove network                               |
| GET    | `/volumes`                        | List volumes                                 |
| GET    | `/volumes/{name}`                 | Inspect volume                               |
| POST   | `/volumes`                        | Create volume                                |
| DELETE | `/volumes/{name}`                 | Remove volume                                |
| GET    | `/system/info`                    | Docker daemon info + version                 |
| GET    | `/system/df`                      | Disk usage breakdown                         |
| WS     | `/system/events`                  | Real-time Docker events stream               |
| GET    | `/health`                         | Health check (Docker reachability)           |

### Redis endpoints

| Method | Path                                    | Description                                  |
|--------|-----------------------------------------|----------------------------------------------|
| GET    | `/redis/keys`                              | Scan keys (pattern, type, cursor, count)        |
| GET    | `/redis/keys/count`                        | DBSIZE shortcut                                 |
| GET    | `/redis/keys/{key}`                        | Get key value + TTL                             |
| PUT    | `/redis/keys/{key}`                        | Set / update a key                              |
| DELETE | `/redis/keys/{key}`                        | Delete a key                                    |
| DELETE | `/redis/keys`                              | Bulk delete (body: list of keys, max 1000)      |
| GET    | `/redis/keys/{key}/ttl`                    | TTL + PTTL                                      |
| POST   | `/redis/keys/{key}/expire`                 | Set TTL or PERSIST                              |
| POST   | `/redis/keys/{key}/persist`                | Remove TTL (PERSIST)                            |
| POST   | `/redis/keys/{key}/rename`                 | Rename (optionally NX)                          |
| POST   | `/redis/keys/{key}/copy`                   | Copy to another key/DB                          |
| GET    | `/redis/keys/{key}/metadata`               | Type, encoding, refcount, idletime, memory      |
| GET    | `/redis/keys/{key}/dump`                   | DUMP (base64-encoded binary serialization)      |
| *many* | `/redis/keys/{key}/hash\|list\|set\|zset\|stream` | Type-specific field/member operations  |
| GET    | `/redis/info`                              | Redis INFO [section]                            |
| GET    | `/redis/databases`                         | Per-DB key counts                               |
| GET    | `/redis/dbsize`                            | DBSIZE                                          |
| GET    | `/redis/summary`                           | Dashboard summary (server, clients, memory, performance, keyspace, replication) |
| GET    | `/redis/replication`                       | Replication status — role, replicas, offsets, lag |
| GET    | `/redis/performance`                       | Performance metrics — ops/sec, hit rate, eviction, I/O |
| GET    | `/redis/config`                            | CONFIG GET                                      |
| POST   | `/redis/config`                            | CONFIG SET                                      |
| POST   | `/redis/config/rewrite`                    | CONFIG REWRITE                                  |
| POST   | `/redis/config/resetstat`                  | CONFIG RESETSTAT                                |
| POST   | `/redis/bgsave`                            | BGSAVE                                          |
| POST   | `/redis/bgrewriteaof`                      | BGREWRITEAOF                                    |
| POST   | `/redis/flushdb`                           | FLUSHDB (requires `?confirm=true`)              |
| POST   | `/redis/flushall`                          | FLUSHALL (requires `?confirm=true`)             |
| GET    | `/redis/clients`                           | CLIENT LIST                                     |
| POST   | `/redis/clients/kill`                      | CLIENT KILL                                     |
| GET    | `/redis/slowlog`                           | SLOWLOG GET                                     |
| GET    | `/redis/slowlog/len`                       | SLOWLOG LEN — number of entries                 |
| POST   | `/redis/slowlog/reset`                     | SLOWLOG RESET                                   |
| GET    | `/redis/memory/stats`                      | MEMORY STATS + MEMORY DOCTOR                    |
| GET    | `/redis/memory/malloc-stats`               | MEMORY MALLOC-STATS                             |
| GET    | `/redis/latency/latest`                    | LATENCY LATEST                                  |
| GET    | `/redis/latency/history/{event}`           | LATENCY HISTORY                                 |
| POST   | `/redis/latency/reset`                     | LATENCY RESET                                   |
| GET    | `/redis/pubsub/channels`                   | PUBSUB CHANNELS                                 |
| GET    | `/redis/pubsub/numsub`                     | PUBSUB NUMSUB — subscriber count per channel    |
| GET    | `/redis/pubsub/numpat`                     | PUBSUB NUMPAT — number of pattern subscriptions |
| POST   | `/redis/pubsub/publish`                    | PUBLISH                                         |
| WS     | `/redis/pubsub/subscribe`                  | Live SUBSCRIBE stream                           |
| WS     | `/redis/monitor`                           | MONITOR command stream                          |
| GET    | `/redis/analysis/keyspace`                 | Type + prefix + TTL distribution                |
| GET    | `/redis/analysis/memory-top`               | Top-N keys by memory (sample)                   |
| GET    | `/redis/analysis/expiring-soon`            | Keys expiring within N seconds                  |
| POST   | `/redis/eval`                              | EVAL (Lua script)                               |
| GET    | `/redis/health`                            | Redis connectivity check                        |
| GET    | `/redis/queues`                            | Queue depth for List + Stream keys              |

### Overview

| Method | Path        | Description                                       |
|--------|-------------|---------------------------------------------------|
| GET    | `/overview` | Combined Docker + Redis snapshot in a single call |

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

Or via Docker Compose (recommended — includes Docker socket mount):

```bash
# First time only:
docker network create internal

docker compose up --build
```

### Environment Variables

All settings are in `src/config.py` and loaded from environment. Safe defaults allow the app to start without any configuration.

| Variable          | Default                                      | Description                                         |
|-------------------|----------------------------------------------|-----------------------------------------------------|
| `PORT`            | `8000`                                       | Uvicorn listen port                                 |
| `CORS_ORIGINS`    | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed origins; `*` only for local |
| `API_KEY_ENABLED` | `false`                                      | Set `true` to require `X-API-Key` on all requests   |
| `API_KEY`         | `""`                                         | The expected key value when auth is enabled         |
| `DEBUG`           | `false`                                      | Enables `DEBUG`-level logging                       |
| `REDIS_HOST`      | `redis`                                      | Redis hostname (use service name in Compose)        |
| `REDIS_PORT`      | `6379`                                       | Redis port                                          |
| `REDIS_PASSWORD`  | `null`                                       | Redis password (omit if not set)                    |
| `REDIS_DB`        | `0`                                          | Default Redis database index (0–15)                 |

**Production checklist:**

- Set `API_KEY_ENABLED=true` and `API_KEY=<strong-secret>`
- Set `CORS_ORIGINS` to your UI's actual origin(s) — never `*`
- Never commit secrets to the repository

---

## Architecture Notes

### Middleware stack (applied in order)

1. **CORS** — configured from `CORS_ORIGINS`; `allow_credentials=True` is automatically disabled when `*` is used
2. **Security headers** — `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`
3. **Request ID** — attaches/echoes `X-Request-ID` header on every response
4. **Request logging** — logs method, path, status, latency, and request ID
5. **API key auth** — checks `X-API-Key` header when `API_KEY_ENABLED=true`; docs, OpenAPI, `/health`, and `/` are always exempt

### Service layer

- `docker_service.py` — lazy-initialised singleton `docker.DockerClient`. All methods return plain dicts/primitives; no SDK objects leak into routers.
- `redis_service.py` — connection pool wrapper. Pools are closed cleanly on shutdown via the FastAPI lifespan handler.

### Error handling

- **Router level:** Docker exceptions are translated by `_docker_errors.handle_docker_exc()` into typed `HTTPException` responses (`404`, `409`, `503`, etc.).
- **Global fallback:** `unhandled_exception_handler` in `main.py` logs the full traceback internally and returns a generic `500` — stack traces are never exposed to clients.

### WebSocket endpoints

| Path                          | Description                        |
|-------------------------------|------------------------------------|
| `/api/v1/system/events`       | Docker daemon event stream         |
| `/api/v1/redis/pubsub/subscribe` | Redis pub/sub subscription      |
| `/api/v1/redis/monitor`       | Redis MONITOR command stream       |

### Lifespan

On startup the app pings both Docker and Redis and logs warnings (not errors) if either is unreachable — endpoints return `503` dynamically if a dependency is unavailable, but the service always starts. On shutdown, `close_docker_client()` and `rs.close_all_pools()` are called.

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

```bash
# Build image
docker build -t myengineapi .

# Run standalone (Docker socket + Redis required)
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e REDIS_HOST=<redis-host> \
  -p 8000:8000 \
  myengineapi
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
feat(redis): add LATENCY HISTORY endpoint
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
2. Catches service-layer exceptions and raises `HTTPException`
3. Wraps return values in `APIResponse(data=...)`

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
- Destructive operations (`flushdb`, `flushall`) require an explicit `?confirm=true` query parameter

---

## For AI Assistants

### Key Principles

1. **Read before editing.** Always read relevant files before making changes.
2. **Minimal changes.** Only change what is necessary to fulfill the request.
3. **No speculation.** Do not add features, error handling, or abstractions that weren't asked for.
4. **Branch discipline.** Always work on the designated branch; never push to `main` directly.
5. **Commit clearly.** Write descriptive commit messages that explain the "why."
6. **No secrets.** Never commit environment variables, tokens, or credentials.

### Branch for AI Work

Claude agents must develop on branches matching the pattern `claude/<session-id>`. Push to that branch and open a PR — do not merge to `main`.

### Common Tasks

| Task                 | Command                                     |
|----------------------|---------------------------------------------|
| Install dependencies | `pip install -r requirements.txt`           |
| Run dev server       | `uvicorn src.main:app --reload --port 8000` |
| Run with Docker      | `docker compose up --build`                 |
| Run tests            | `pytest` (no tests yet — add to `tests/`)   |
| Lint                 | `flake8 src/` or `ruff check src/`          |
| Format               | `black src/`                                |
| Type check           | `mypy src/`                                 |

### Adding a new router

1. Create `src/routers/<name>.py` with an `APIRouter`
2. Import and register it in `src/main.py` with `app.include_router(..., prefix=API_PREFIX)`
3. Add request/response models to `src/models/schemas.py` or `src/models/redis_schemas.py`
4. Add service logic to the appropriate file in `src/services/`

### Adding a new environment variable

1. Add a typed field with a default to the `Settings` class in `src/config.py`
2. Document it in the Environment Variables table in this file

---

## Maintenance

This CLAUDE.md should be updated whenever:

- New routers, endpoints, or services are added
- Environment variables change
- Development workflows change
- New conventions are adopted by the team

*Last updated: 2026-02-28 (full rewrite — codebase fully scaffolded at v3.1.0)*
