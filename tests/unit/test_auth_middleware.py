import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.middleware.auth import ApiKeyMiddleware
from app.core.constants import Headers


def _make_app(require_auth: bool, valid_keys: set[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware, require_auth=require_auth, valid_keys=valid_keys)

    @app.post("/write")
    def write_endpoint():
        return {"ok": True}

    @app.get("/read")
    def read_endpoint():
        return {"ok": True}

    return app


def test_auth_disabled_allows_all_requests():
    client = TestClient(_make_app(require_auth=False, valid_keys={"secret"}))
    assert client.post("/write").status_code == 200


def test_auth_enabled_rejects_missing_key_on_write():
    client = TestClient(_make_app(require_auth=True, valid_keys={"secret"}))
    assert client.post("/write").status_code == 401


def test_auth_enabled_rejects_wrong_key():
    client = TestClient(_make_app(require_auth=True, valid_keys={"secret"}))
    assert client.post("/write", headers={Headers.API_KEY: "wrong"}).status_code == 403


def test_auth_enabled_accepts_valid_key():
    client = TestClient(_make_app(require_auth=True, valid_keys={"secret"}))
    assert client.post("/write", headers={Headers.API_KEY: "secret"}).status_code == 200


def test_get_requests_always_public_when_auth_enabled():
    """GET routes remain public even when auth is on."""
    client = TestClient(_make_app(require_auth=True, valid_keys={"secret"}))
    assert client.get("/read").status_code == 200
