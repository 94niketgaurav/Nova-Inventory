from app.core.config import Settings, settings


def test_settings_has_required_fields():
    assert hasattr(settings, "database_url")
    assert hasattr(settings, "environment")
    assert hasattr(settings, "log_level")


def test_environment_default():
    assert settings.environment in ("development", "production", "test")


def test_database_url_built_from_parts():
    url = settings.database_url
    assert "asyncpg" in url
    assert settings.db_host in url
    assert settings.db_name in url


def test_local_defaults_are_set():
    assert settings.db_host == "localhost"
    assert settings.db_port == 5432
    assert settings.db_name == "nova_inventory"


def test_redis_url_has_default():
    assert settings.redis_url.startswith("redis://")


def test_auth_disabled_by_default():
    assert settings.require_auth is False


def test_valid_api_keys_parsing():
    s = Settings(api_keys="key1, key2,  key3 ")
    assert "key1" in s.valid_api_keys
    assert "key2" in s.valid_api_keys
    assert "key3" in s.valid_api_keys
    assert len(s.valid_api_keys) == 3


def test_empty_api_keys_returns_empty_frozenset():
    s = Settings(api_keys="")
    assert s.valid_api_keys == frozenset()
