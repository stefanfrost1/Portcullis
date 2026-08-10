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

    # Redis connection
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0  # Default database index


settings = Settings()
