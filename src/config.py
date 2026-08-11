"""
Application settings — loaded from environment variables.

All settings have safe defaults so the app works out-of-the-box for local development.
For production, set at least:
  API_KEY_ENABLED=true  API_KEY=<strong-random-secret>
  CORS_ORIGINS=https://your-ui-domain.com
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # CORS
    # Comma-separated list of allowed origins.
    # Use "*" only for local development — never in production.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # API key authentication (opt-in)
    # Set API_KEY_ENABLED=true and API_KEY=<secret> to require X-API-Key on all requests.
    # Docs, OpenAPI JSON, and /health endpoints are always exempt.
    API_KEY_ENABLED: bool = False
    API_KEY: str = ""

    # Debug mode — more verbose logging when True
    DEBUG: bool = False

    # Server
    PORT: int = 8000

    # Docker daemon
    # Socket read timeout in seconds, and the maximum number of concurrent
    # connections to the daemon (batch stats/log calls fan out across threads).
    DOCKER_TIMEOUT: int = 30
    DOCKER_MAX_POOL_SIZE: int = 32
    # `docker system df` is expensive on hosts with many images; results are
    # cached for this many seconds. Set to 0 to disable caching.
    DISK_USAGE_CACHE_TTL: int = 60
    # `docker system df` walks every image layer, container writable layer, and
    # volume, so on image-heavy hosts it can run far longer than a normal call.
    # It gets its own (larger) socket timeout so it does not trip DOCKER_TIMEOUT
    # and return a 500; the result is then cached for DISK_USAGE_CACHE_TTL.
    DISK_USAGE_TIMEOUT: int = 120

    # Compose project scope.
    # Scopes the operational Docker views (containers, their logs/stats/groups,
    # and volumes) to one or more Compose projects via the
    # `com.docker.compose.project` label. Three ways to select, combined with OR:
    #   COMPOSE_PROJECT         — a single exact project name
    #   COMPOSE_PROJECTS        — comma-separated list of exact project names
    #   COMPOSE_PROJECT_PREFIX  — match any project whose name starts with this
    # A single exact name is filtered entirely daemon-side (cheapest). A list or
    # prefix can't be expressed by Docker's label filter (no OR / no prefix), so
    # the daemon is asked only for compose-labelled resources and Portcullis
    # narrows the result in-process.
    # All empty (default) = no filter, i.e. the previous host-wide behaviour.
    # Images and networks stay host-wide (they are reference resources; Compose
    # does not stamp the project label on pulled images).
    COMPOSE_PROJECT: str = ""
    COMPOSE_PROJECTS: str = ""
    COMPOSE_PROJECT_PREFIX: str = ""

    # Custom-label scope (takes precedence over the COMPOSE_PROJECT* vars above).
    # Scope by any Docker label you add to your Compose services yourself, e.g.
    # `SCOPE_LABEL=com.acme.stack=dev`. A single exact `key=value` (or bare `key`
    # for "has this label") is filtered entirely daemon-side — no in-process
    # narrowing — so this is the cheapest and most explicit way to group several
    # Compose projects into one view. Note: Compose applies a service's `labels:`
    # to the container only, so add the same label to your `volumes:` (and
    # `networks:`) definitions if you want those scoped too.
    SCOPE_LABEL: str = ""

    # Redis connection
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0  # Default database index


settings = Settings()
