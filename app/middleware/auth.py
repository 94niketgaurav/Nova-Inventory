# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.constants import Headers

# Routes that are always public regardless of auth setting
_PUBLIC_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/health")

# HTTP methods that require auth when auth is enabled
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """
    Optional API-key guard.
    - Disabled (require_auth=False): all requests pass through unchanged.
    - Enabled: write methods (POST/PATCH/PUT/DELETE) require X-API-Key header.
      GET requests remain public (read-only endpoints need no auth).
    """

    def __init__(self, app, require_auth: bool, valid_keys: set[str]) -> None:
        super().__init__(app)
        self._require_auth = require_auth
        self._valid_keys = valid_keys

    async def dispatch(self, request: Request, call_next):
        if not self._require_auth:
            return await call_next(request)

        # Public paths always pass
        path = request.url.path
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # GET requests are public reads — always allowed
        if request.method == "GET":
            return await call_next(request)

        # Write operations require a valid API key
        if request.method in _WRITE_METHODS:
            key = request.headers.get(Headers.API_KEY)
            if not key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": f"Missing {Headers.API_KEY} header"},
                )
            if key not in self._valid_keys:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid API key"},
                )

        return await call_next(request)
