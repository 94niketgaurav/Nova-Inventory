import uuid
from app.core.constants import CacheKeys, Headers, RateLimits, LogFields


def test_stock_cache_key_format():
    item_id = uuid.uuid4()
    key = CacheKeys.stock(item_id)
    assert key.startswith("nova:stock:")
    assert str(item_id) in key


def test_stock_cache_key_is_consistent():
    item_id = uuid.uuid4()
    assert CacheKeys.stock(item_id) == CacheKeys.stock(item_id)


def test_different_items_have_different_keys():
    assert CacheKeys.stock(uuid.uuid4()) != CacheKeys.stock(uuid.uuid4())


def test_headers_defined():
    assert Headers.REQUEST_ID == "X-Request-ID"
    assert Headers.API_KEY == "X-API-Key"


def test_rate_limits_are_slowapi_format():
    # slowapi expects "N/period" strings
    assert "/" in RateLimits.STOCK_READ
    assert "/" in RateLimits.DEFAULT


def test_log_fields_are_strings():
    assert isinstance(LogFields.ITEM_ID, str)
    assert isinstance(LogFields.ORDER_ID, str)
    assert isinstance(LogFields.STOCK_BEFORE, str)
    assert isinstance(LogFields.STOCK_AFTER, str)
