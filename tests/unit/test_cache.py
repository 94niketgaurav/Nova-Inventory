# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
"""
Unit tests for CacheService — both enabled (mocked Redis) and disabled (None) modes.
"""
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.cache import CacheService
from app.core.constants import CacheKeys

# ── Enabled mode (Redis injected) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_stock_stores_with_ttl():
    redis = AsyncMock()
    cache = CacheService(redis)
    item_id = uuid.uuid4()

    await cache.set_stock(item_id, 42)

    redis.setex.assert_called_once()
    call_args_str = str(redis.setex.call_args)
    assert CacheKeys.stock(item_id) in call_args_str
    assert "42" in call_args_str


@pytest.mark.asyncio
async def test_get_stock_returns_int_on_hit():
    redis = AsyncMock()
    redis.get.return_value = b"15"
    cache = CacheService(redis)

    result = await cache.get_stock(uuid.uuid4())

    assert result == 15


@pytest.mark.asyncio
async def test_get_stock_returns_none_on_miss():
    redis = AsyncMock()
    redis.get.return_value = None
    cache = CacheService(redis)

    result = await cache.get_stock(uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_cache_degrades_gracefully_on_read_error():
    redis = AsyncMock()
    redis.get.side_effect = Exception("Redis down")
    cache = CacheService(redis)

    # Must not raise — caller falls back to DB
    result = await cache.get_stock(uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_cache_degrades_gracefully_on_write_error():
    redis = AsyncMock()
    redis.setex.side_effect = Exception("Redis down")
    cache = CacheService(redis)

    # Must not raise
    await cache.set_stock(uuid.uuid4(), 99)


# ── Disabled mode (redis=None) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_get_stock_returns_none():
    """CacheService(None) is a no-op — callers fall back to DB."""
    cache = CacheService(None)
    result = await cache.get_stock(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_disabled_set_stock_is_noop():
    """CacheService(None) write is silent no-op — no errors."""
    cache = CacheService(None)
    await cache.set_stock(uuid.uuid4(), 42)  # must not raise


@pytest.mark.asyncio
async def test_disabled_invalidate_is_noop():
    cache = CacheService(None)
    await cache.invalidate_stock(uuid.uuid4())  # must not raise
