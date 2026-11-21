# CLAUDE.md — MyEngineAPI

This file provides context, conventions, and workflows for AI assistants (and human developers) working in this repository.

---

## Repository Overview

| Field       | Value                                                                 |
|-------------|-----------------------------------------------------------------------|
| **Name**    | MyEngineAPI                                                           |
| **Remote**  | stefanfrost1/MyEngineAPI                                              |
| **Branch**  | Work on feature branches; never push directly to `main`              |
| **Purpose** | REST + WebSocket bridge between a UI and Redis                       |
| **Runtime** | Python 3.12, FastAPI 0.115, Uvicorn 0.34                            |
| **Version** | 4.0.0 (see `src/main.py`)                                            |

---

## What This Service Does

MyEngineAPI shields a UI from direct Redis access. It exposes the following over a single FastAPI application:

1. **Redis management** — key browser (string/hash/list/set/zset/stream CRUD), server ops (INFO, CONFIG, BGSAVE, FLUSHDB, …), pub/sub, MONITOR stream, keyspace analysis, slow log, memory stats, latency tracking, and queue-depth monitoring.
2. **Aggregate overview** — a single `GET /api/v1/overview` endpoint with Redis high-level stats and top queue depths for monitoring dashboards.

Redis is never exposed to the UI directly.

> Docker management (containers, images, networks, volumes, logs, system) was removed in v4.0.0 as the deployment target moved from Docker to Kubernetes.

---

## Repository Structure

```
MyEngineAPI/
├── CLAUDE.md                    # This file
├── Dockerfile                   # Python 3.12-slim, non-root user, port 8000
├── docker-compose.yml           # Local stack: frontend, portcullis, redis
├── requirements.txt             # Python dependencies
└── src/
    ├── main.py                  # FastAPI app, middleware, router registration
    ├── config.py                # Pydantic-settings config (env vars)
    ├── __init__.py
    ├── models/
    │   ├── schemas.py           # Generic APIResponse envelope
    │   └── redis_schemas.py     # Redis request/body Pydantic models
    ├── routers/
    │   ├── overview.py          # /overview — Redis snapshot; /health — Redis reachability
    │   ├── redis_keys.py        # /redis/keys — key browser + type operations
    │   ├── redis_server.py      # /redis — server ops, pub/sub, MONITOR WS, analysis
    │   ├── redis_queues.py      # /redis/queues — queue depth monitoring
    │   └── _auth.py             # Role helpers from Caddy X-User-Groups header
    └── services/
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
| GET    | `/overview` | Redis snapshot + top queues in a single call      |
| GET    | `/health`   | Health check (Redis reachability)                 |

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

HTTP status codes are used semantically. The `/overview` endpoint always returns 200; check the `"status": "error"` field inside the `redis` section for failures.

---

## Development Setup

### Prerequisites

- Python 3.12+
- Redis instance reachable at the configured host/port

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Locally

```bash
uvicorn src.main:app --reload --port 8000
```

Or via Docker Compose (local stack with Redis + frontend):

```bash
# First time only:
docker network create internal

docker compose up --build
```

### Environment Variables

All settings are in `src/config.py` and loaded from environment. Safe defaults allow the app to start without any configuration.

| Variable          | Default                                      | Description                                         |
|-------------------|----------------------------------------------|-----------------------------------------------------|
| `REGISTRY`        | `ghcr.io/stefanfrost1`                       | Container registry prefix for `make build/push`     |
| `TAG`             | `latest`                                     | Image tag for `make build/push` and Compose         |
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

- `redis_service.py` — connection pool wrapper. Pools are closed cleanly on shutdown via the FastAPI lifespan handler.

### Error handling

- **Router level:** `RedisError` exceptions are caught in each router and raised as `HTTPException`.
- **Global fallback:** `unhandled_exception_handler` in `main.py` logs the full traceback internally and returns a generic `500` — stack traces are never exposed to clients.

### WebSocket endpoints

| Path                          | Description                        |
|-------------------------------|------------------------------------|
| `/api/v1/redis/pubsub/subscribe` | Redis pub/sub subscription      |
| `/api/v1/redis/monitor`       | Redis MONITOR command stream       |

### Lifespan

On startup the app pings Redis and logs a warning (not an error) if it is unreachable — endpoints return errors dynamically while Redis is unavailable, but the service always starts. On shutdown, `rs.close_all_pools()` is called.

---

## Testing

No automated tests exist yet. When adding tests:

- Place unit tests in `tests/unit/`
- Place integration tests in `tests/integration/`
- Run with `pytest`
- Do not commit code that breaks existing tests

The interactive Swagger UI at `/api/v1/docs` can be used for manual endpoint testing against a live Redis instance.

---

## Build & Deployment

### Images

| Image name | Source | Port |
|---|---|---|
| `portcullis` | `Dockerfile` (repo root) | 8000 |
| `portcullis-frontend` | `frontend/Dockerfile` | 8501 |

Default registry: `ghcr.io/stefanfrost1`. Override with `REGISTRY=` and `TAG=`.

### Build and push (Makefile)

```bash
# Build both images
make build

# Build individually
make build-backend
make build-frontend

# Push both to registry
make push

# Build + push in one step
make release

# Override registry or tag
make release REGISTRY=docker.io/myorg TAG=1.2.3
```

### Using pre-built images in other Compose setups

Reference the published images directly — no source code required:

```yaml
services:
  portcullis:
    image: ghcr.io/stefanfrost1/portcullis:latest
    environment:
      - REDIS_HOST=redis

  frontend:
    image: ghcr.io/stefanfrost1/portcullis-frontend:latest
    environment:
      - MYENGINE_URL=http://portcullis:8000
```

### Run standalone (no Compose)

```bash
docker run --rm \
  -e REDIS_HOST=<redis-host> \
  -p 8000:8000 \
  ghcr.io/stefanfrost1/portcullis:latest
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

- `src/models/schemas.py` — generic `APIResponse` envelope
- `src/models/redis_schemas.py` — Redis request body models

Do not add fields to response models that the service layer does not actually return.

### Service layer

- Services hold the external-dependency logic (Redis commands)
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

*Last updated: 2026-11-21 (v4.0.0 — Docker management removed; Redis-only)*
