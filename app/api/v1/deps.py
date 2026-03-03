# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from app.core.cache import CacheService, get_redis


def get_cache() -> CacheService:
    """FastAPI dependency — returns CacheService backed by Redis (or no-op if disabled)."""
    return CacheService(get_redis())
