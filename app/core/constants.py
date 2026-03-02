"""
Single source of truth for all string constants used across the application.
Import from here — never hardcode these strings in business logic.
"""
import uuid


class CacheKeys:
    """Redis key prefixes and builders."""
    STOCK_PREFIX = "nova:stock:"
    ITEM_PREFIX = "nova:item:"

    @staticmethod
    def stock(item_id: uuid.UUID) -> str:
        """Write-through cache key for a single item's stock_quantity."""
        return f"{CacheKeys.STOCK_PREFIX}{item_id}"


class Headers:
    """HTTP header names."""
    REQUEST_ID = "X-Request-ID"
    API_KEY = "X-API-Key"


class RateLimits:
    """
    Rate limit strings for slowapi (format: "N/period").
    These are defaults; runtime values come from Settings.
    """
    STOCK_READ = "100/minute"
    DEFAULT = "200/minute"


class LogFields:
    """Structured log field names — keeps log schema consistent."""
    REQUEST_ID = "request_id"
    ITEM_ID = "item_id"
    ORDER_ID = "order_id"
    STOCK_BEFORE = "stock_before"
    STOCK_AFTER = "stock_after"
    DELTA = "delta"
    DURATION_MS = "duration_ms"
