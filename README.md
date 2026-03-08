# Portcullis + Streamlit Dashboard

A Docker and Redis management platform consisting of:

| Service | Description | Default URL |
|---|---|---|
| **Streamlit UI** | Multi-page dashboard | http://localhost:8501 |
| **Portcullis** | FastAPI REST backend | http://localhost:8000/api/v1/docs |
| **Redis** | Data store (internal) | localhost:6379 (not exposed) |

---

## Quickstart — Docker Compose

Everything runs with a single command. No pre-setup required.

```bash
docker compose up --build
```

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
Live overview combining Docker + Redis metrics on one screen. Auto-refreshes every 10 seconds.

- Container counts (running / paused / stopped)
- Image and volume counts
- Redis: connected clients, memory, keyspace size, ops/sec, hit rate
- Container state pie chart
- Top queues bar chart

### Containers
- Full container list with state, image, status, uptime, and ports
- Per-container lifecycle controls: **Start / Stop / Restart / Pause / Unpause / Remove**
- Live stats tab: CPU%, memory%, network I/O, block I/O
- Compose project grouping tab

### Images
- List all images with tags, size, and creation date
- Pull a new image by name (e.g. `nginx:latest`)
- Remove images (with confirmation)

### Networks
- List networks with driver, scope, and attached container count
- Create a new network (choose driver, set internal flag)
- Inspect: see which containers are attached
- Remove (built-in networks are protected)

### Volumes
- List volumes with driver and mountpoint
- Create a new volume
- Remove (with confirmation)

### System
- Docker daemon version, kernel, OS, CPU count, total memory
- Disk usage breakdown: images / containers / volumes / build cache
- Disk usage bar chart

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
3. Restart: `docker compose up --build`

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
    ├── pages/               # One file per page (auto-discovered by Streamlit)
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
