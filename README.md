# Portcullis + Streamlit Dashboard

A Redis management platform consisting of:

| Service | Description | Default URL |
|---|---|---|
| **Streamlit UI** | Multi-page dashboard | http://localhost:8501 |
| **Portcullis** | FastAPI REST backend | http://localhost:8000/api/v1/docs |
| **Redis** | Data store (internal) | localhost:6379 (not exposed) |

---

## Quickstart — Docker Compose

Everything runs from prebuilt images on Docker Hub (`simplitics1`). No build required.

```bash
docker compose pull
docker compose up -d
```

Pin a specific image tag with `IMAGE_TAG` (defaults to `latest`):

```bash
IMAGE_TAG=3.1.0 docker compose up -d          # bash
$env:IMAGE_TAG='3.1.0'; docker compose up -d  # PowerShell
```

### Building the images

Use the build script instead of `docker compose build`:

```bash
./build.sh                 # build both images, tag = version in src/main.py + latest
./build.sh -t 3.2.0 -p     # build and push to Docker Hub (docker login first)
./build.sh -s frontend     # frontend image only
```

```powershell
./build.ps1                    # same defaults on Windows
./build.ps1 -Tag 3.2.0 -Push
./build.ps1 -Service frontend
```

### CI builds

`.github/workflows/docker-build.yml` builds and pushes both images on every push to
`main`/`master`, `feature/**` and `release/**`. Other branches are not built.

| Branch          | Image tag        |
|-----------------|------------------|
| `main`/`master` | `latest`         |
| `feature/foo`   | `feature-foo`    |
| `release/1.2.0` | `release-1.2.0`  |

Requires two repository secrets: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

Then open:
- **Dashboard** → http://localhost:8501
- **API docs (Swagger)** → http://localhost:8000/api/v1/docs

To stop:
```bash
docker compose down
```

To stop and delete all Redis data:
```bash
docker compose down -v
```

---

## What the UI does

### Dashboard (`/`)
Live Redis overview on one screen. Auto-refreshes every 10 seconds.

- Redis: connected clients, memory, keyspace size, ops/sec, hit rate
- Top queues bar chart

### Redis Keys
- Paginated key browser with pattern and type filters
- View values for all types: string, hash, list, set, zset, stream
- Edit TTL (set or remove expiry)
- Delete single keys or bulk-delete with multi-select
- Create / overwrite keys

### Redis Server
Eight tabs covering:
- **Summary** — version, uptime, clients, memory, ops/sec, hit rate, replication role
- **Performance** — ops/sec, hit/miss rate, eviction, I/O
- **Replication** — role, connected replicas, offsets
- **Clients** — live CLIENT LIST
- **Slow Log** — recent slow commands with duration and reset button
- **Config** — searchable CONFIG GET/SET editor
- **Memory** — MEMORY STATS breakdown + MEMORY DOCTOR diagnosis
- **Latency** — LATENCY LATEST events + reset button
- BGSAVE, BGREWRITEAOF, and FLUSHDB (with double-confirmation)

### Redis Analysis
- **Keyspace** — type distribution (pie), top prefixes (bar), TTL buckets (histogram)
- **Memory Top** — top-N keys by memory usage (configurable 10–100)
- **Expiring Soon** — keys expiring within a configurable time window

### Redis Queues
- Auto-refreshing table of all List and Stream queue depths
- Bar chart of top queues
- Per-queue expander showing consumer group detail (for Streams)

---

## Configuration

All configuration is done via environment variables. The defaults work out of the box for local development.

### Frontend (`frontend/.env.example`)

| Variable | Default | Description |
|---|---|---|
| `MYENGINE_URL` | `http://localhost:8000` | Backend API URL |
| `MYENGINE_API_KEY` | _(empty)_ | API key (only needed if auth is enabled on the backend) |
| `REFRESH_INTERVAL` | `10` | Dashboard auto-refresh in seconds |

For local development without Docker:
```bash
cp frontend/.env.example frontend/.env
# edit .env if needed
cd frontend
pip install -r requirements.txt
MYENGINE_URL=http://localhost:8000 streamlit run app.py
```

### Backend (Portcullis)

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `redis` | Redis hostname (use service name in Compose) |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | _(none)_ | Redis password, if required |
| `REDIS_DB` | `0` | Default Redis database index (0–15) |
| `API_KEY_ENABLED` | `false` | Set `true` to require `X-API-Key` on all requests |
| `API_KEY` | _(empty)_ | The API key value (used when auth is enabled) |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed origins |
| `PORT` | `8000` | Uvicorn listen port |

---

## Enabling API key authentication

1. Uncomment these lines in `docker-compose.yml`:
   ```yaml
   # - API_KEY_ENABLED=true
   # - API_KEY=change-me-to-a-strong-secret
   ```
2. Set the same key in the frontend environment:
   ```yaml
   - MYENGINE_API_KEY=change-me-to-a-strong-secret
   ```
3. Restart: `docker compose up -d`

---

## Exposing Redis on the host

By default Redis is only reachable between containers (no host port). To connect with a local Redis client:

Uncomment in `docker-compose.yml`:
```yaml
# ports:
#   - "6379:6379"
```

---

## Redis data persistence

Redis is configured with AOF persistence (`--appendonly yes`) and a named volume (`redis_data`). Data survives `docker compose down` but is deleted by `docker compose down -v`.

---

## Project structure

```
Portcullis/
├── docker-compose.yml       # All three services: frontend, portcullis, redis
├── Dockerfile               # Portcullis backend image
├── requirements.txt         # Backend Python dependencies
├── src/                     # FastAPI backend source
│   ├── main.py
│   ├── config.py
│   ├── routers/
│   ├── models/
│   └── services/
└── frontend/                # Streamlit dashboard
    ├── app.py               # Dashboard entry point
    ├── app_pages/           # One file per page (routed explicitly from app.py)
    ├── utils/
    │   ├── api_client.py    # EngineClient — all API calls
    │   └── formatting.py    # Human-readable helpers
    ├── .streamlit/
    │   └── config.toml      # Dark theme, port 8501
    ├── Dockerfile
    ├── requirements.txt
    └── .env.example
```

---

## API documentation

The backend exposes interactive docs at:
- **Swagger UI** → http://localhost:8000/api/v1/docs
- **ReDoc** → http://localhost:8000/api/v1/redoc
- **OpenAPI JSON** → http://localhost:8000/api/v1/openapi.json
