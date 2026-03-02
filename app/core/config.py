from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database — individual parts, all with local-dev defaults
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "nova_inventory"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # Redis / Cache
    redis_url: str = "redis://localhost:6379"
    cache_ttl_seconds: int = 300
    enable_cache: bool = True   # Set ENABLE_CACHE=false to bypass Redis entirely

    # Auth
    require_auth: bool = False
    api_keys: str = ""

    # Rate limiting
    rate_limit_stock_read: str = "100/minute"
    rate_limit_default: str = "200/minute"

    # App
    environment: str = "development"
    log_level: str = "INFO"
    low_stock_default_threshold: int = 10

    @property
    def database_url(self) -> str:
        """Async URL (asyncpg) — used by both SQLAlchemy engine AND Alembic."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def valid_api_keys(self) -> frozenset[str]:
        if not self.api_keys:
            return frozenset()
        return frozenset(k.strip() for k in self.api_keys.split(",") if k.strip())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton — instantiated once, cached forever."""
    return Settings()


settings = get_settings()
