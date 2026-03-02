"""
Plug-and-play Redis cache for stock quantities.

Usage:
  - CacheService(redis_client)  → full read/write-through cache
  - CacheService(None)          → all methods are no-ops; callers fall back to DB

The global singleton `get_redis()` returns None when `settings.enable_cache=False`,
so the rest of the app never needs to branch on cache availability — it just works.
"""
import uuid
import redis.asyncio as aioredis
import structlog
from app.core.config import settings
from app.core.constants import CacheKeys

logger = structlog.get_logger(__name__)

# ── Singleton Redis client — created once at import time ─────────────────────
# If enable_cache is False the singleton is still created (cheap) but get_redis()
# returns None, which makes CacheService a no-op everywhere.
_redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=False,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def get_redis() -> aioredis.Redis | None:
    """
    Return the Redis singleton when caching is enabled, else None.
    Inject None into CacheService to get a no-op (straight-to-DB) path.
    """
    if not settings.enable_cache:
        return None
    return _redis_client


async def close_redis() -> None:
    """Gracefully close the connection pool on shutdown (called from lifespan)."""
    await _redis_client.aclose()


class CacheService:
    """
    Write-through stock cache.

    Designed for dependency injection — pass a Redis client to enable caching,
    or pass None to disable it entirely (all methods become no-ops).

    All Redis operations catch exceptions and degrade gracefully; DB is always
    the source of truth.

    Examples:
        # Enabled (production / local dev with Redis)
        cache = CacheService(get_redis())

        # Disabled (testing, or ENABLE_CACHE=false)
        cache = CacheService(None)

        # FastAPI dependency (auto-selects based on settings):
        def get_cache() -> CacheService:
            return CacheService(get_redis())
    """

    def __init__(self, redis: aioredis.Redis | None) -> None:
        self._redis = redis

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_stock(self, item_id: uuid.UUID) -> int | None:
        """
        Return cached stock quantity, or None on miss/error/disabled.
        Callers treat None as "go to DB".
        """
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(CacheKeys.stock(item_id))
            if value is None:
                return None
            return int(value)
        except Exception as exc:
            logger.warning("cache_read_error", item_id=str(item_id), error=str(exc))
            return None

    # ── Write ─────────────────────────────────────────────────────────────────

    async def set_stock(self, item_id: uuid.UUID, quantity: int) -> None:
        """
        Write stock quantity to cache with TTL.
        No-op if Redis is None or unavailable — never raises.
        """
        if self._redis is None:
            return
        try:
            await self._redis.setex(
                CacheKeys.stock(item_id),
                settings.cache_ttl_seconds,
                str(quantity),
            )
            logger.debug("cache_write", item_id=str(item_id), quantity=quantity)
        except Exception as exc:
            logger.warning("cache_write_error", item_id=str(item_id), error=str(exc))

    async def invalidate_stock(self, item_id: uuid.UUID) -> None:
        """Remove a key from cache. No-op if Redis is None or unavailable."""
        if self._redis is None:
            return
        try:
            await self._redis.delete(CacheKeys.stock(item_id))
        except Exception as exc:
            logger.warning("cache_invalidate_error", item_id=str(item_id), error=str(exc))
