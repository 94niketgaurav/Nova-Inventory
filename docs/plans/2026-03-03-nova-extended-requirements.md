# Nova Inventory Service — Extended Requirements & Design Decisions

**Date:** 2026-03-03
**Status:** Implemented
**Stack:** Python 3.13, FastAPI, PostgreSQL 16, Redis, SQLAlchemy (async), Alembic, uv, slowapi, structlog

> **Context:** This document captures all requirements, design decisions, and edge-case thinking added *after* the original design document (`2026-02-26-inventory-stock-service-design.md`). It demonstrates deliberate architectural choices made during implementation to build a production-grade service.

---

## 1. Plug-and-Play Redis Cache

### Requirement
The stock read endpoint (`GET /api/v1/stock/{item_id}`) is the highest-volume read path. A caching layer should accelerate it without coupling the service to Redis being available.

### Design: Injectable No-Op Cache

```python
class CacheService:
    def __init__(self, redis: aioredis.Redis | None) -> None:
        self._redis = redis  # None → all methods are silent no-ops

    async def get_stock(self, item_id: UUID) -> int | None:
        if self._redis is None:
            return None  # cache disabled — caller falls through to DB
        ...
```

**Key decisions:**
- `CacheService(redis=None)` is a complete no-op — no Redis dependency in tests or when disabled
- `get_redis()` returns `None` when `ENABLE_CACHE=false` in environment
- Services accept `cache: CacheService | None = None` as an injectable constructor parameter, defaulting to `CacheService(get_redis())`
- FastAPI `get_cache()` dependency in `app/api/v1/deps.py` provides the right implementation per request
- Tests use `CacheService(None)` — no Redis required, complete isolation

### Write-Through Strategy

Every stock mutation synchronously updates the cache within the same service call:

```
create_item()   → set_stock(item.id, stock_quantity)
adjust_stock()  → set_stock(item.id, new_quantity)
confirm_order() → set_stock(item.id, item.stock_quantity)  # after deduction
cancel_order()  → set_stock(item.id, item.stock_quantity)  # after restoration
```

Cache-first reads in `StockService.get_stock()`:
1. `cache.get_stock(item_id)` → hit: inject into item object, skip DB quantity
2. Miss: return DB item as-is (DB is always authoritative)

**Redis key format:** `stock:{item_id}` · **TTL:** configurable via `CACHE_TTL_SECONDS` (default: 300s)

### Rationale
Write-through keeps cache consistent with DB without a separate invalidation step. The no-op pattern means zero test complexity — no mocking, no fake Redis.

---

## 2. Analytics Endpoints

### Requirement
Operators need aggregate views of inventory health and order activity without writing ad-hoc SQL.

### Endpoints Added

| Endpoint | Description |
|---|---|
| `GET /api/v1/analytics/summary` | Total items, total stock value, low-stock count, order counts by status |
| `GET /api/v1/analytics/stock` | Per-item stock snapshot with utilisation percentage |
| `GET /api/v1/analytics/orders` | Order volume by status, revenue (CONFIRMED/SHIPPED/DELIVERED), refunds (CANCELLED) |
| `GET /api/v1/analytics/movements` | Movement type breakdown (ADJUSTMENT/DEDUCTION/RESTORATION) with delta sums |

### Implementation Notes
- Pure aggregate SQL using `func.count`, `func.sum`, `func.coalesce`
- Revenue/refund subqueries require `.select_from(Order)` when `select()` has no entity columns — discovered and fixed during implementation
- Read-only: no locking, no side effects
- Located in `app/services/analytics_service.py` + `app/api/v1/analytics.py`

---

## 3. API Authentication Middleware

### Requirement
Write operations (create item, place/confirm/cancel order, adjust stock) should be protectable without requiring a full OAuth/JWT implementation.

### Design: `ApiKeyMiddleware`

```python
class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "GET":
            return await call_next(request)  # reads always public
        if not settings.require_auth:
            return await call_next(request)  # auth disabled (dev default)
        key = request.headers.get("X-API-Key", "")
        if not key:
            return JSONResponse({"detail": "Missing X-API-Key header"}, status_code=401)
        if key not in settings.api_keys:
            return JSONResponse({"detail": "Invalid API key"}, status_code=403)
        return await call_next(request)
```

**Key decisions:**
- GET always public — no auth for reads (analytics, stock queries, item listing)
- Write methods protected when `REQUIRE_AUTH=true`; default is `false` for development ergonomics
- Keys stored as comma-separated `API_KEYS` env var — no DB round-trip per request
- 401 = missing key; 403 = wrong key (semantically distinct)
- Middleware (not a FastAPI dependency) so it applies uniformly without per-route decoration

---

## 4. Rate Limiting

### Requirement
The stock read endpoint is the highest-traffic endpoint in production. Uncontrolled request rates could impact PostgreSQL and Redis performance.

### Design: `slowapi` with Configurable Limits

```python
limiter = Limiter(key_func=get_remote_address)

@router.get("/{item_id}")
@limiter.limit(settings.rate_limit_stock_read)
async def get_stock(request: Request, item_id: UUID, ...):
    ...
```

**Configuration:**
- `RATE_LIMIT_STOCK_READ=100/minute` — stock read endpoint (hot path)
- `RATE_LIMIT_DEFAULT=200/minute` — all other endpoints
- 429 Too Many Requests with `Retry-After` header on breach
- Key: remote IP address (appropriate for service-to-service; can be changed to API key if needed)

---

## 5. Edge Case Test Strategy

### Requirement
Beyond the happy path and the concurrent lock tests, a production service must handle invalid inputs, state violations, and boundary conditions gracefully.

### Categories Covered (`tests/e2e/test_edge_cases.py`)

**Input Validation (Pydantic layer)**
- Zero price → 422 Unprocessable Entity
- Negative price → 422
- Empty/whitespace name → 422
- Zero or negative order quantity → 422

**Integrity Violations (DB layer)**
- Duplicate item name → 409 Conflict (caught `IntegrityError` in `app/api/v1/items.py`)

**State Machine Violations**
- Double-confirm same order → 409 Conflict (optimistic lock catches stale version)
- Ship/deliver a PENDING order → 409 Invalid Transition
- Confirm/ship/deliver a CANCELLED order → 409 Invalid Transition
- No transitions allowed from terminal states (REJECTED, DELIVERED, CANCELLED)

**Stock Boundary Conditions**
- Order quantity exactly equals available stock → succeeds
- Order quantity one over stock → 422 Insufficient Stock
- Order against zero-stock item → 422 Insufficient Stock
- Sequential depletion: multiple orders deplete stock to zero, next fails correctly

**Not-Found Handling**
- All routes return 404 for nonexistent UUIDs

### Bug Fixed During Edge Case Testing
`IntegrityError` on duplicate item name was propagating as HTTP 500. Fixed by catching it in `app/api/v1/items.py`:
```python
except IntegrityError:
    raise HTTPException(status_code=409, detail="An item with this name already exists.")
```

### Test Case Documentation
All 87 test cases are catalogued in `tests/TEST_CASES.md` with:
- Business rule each test validates
- Locking mechanism exercised (if applicable)
- Expected HTTP status codes

---

## 6. Concurrent Order Tests (Race Condition Prevention)

### Requirement
The pessimistic locking strategy must be verified to work under real concurrent load — not just asserted in code comments.

### Test 1: Oversell Prevention (10 concurrent confirms, stock=5)

```python
async def confirm_one(order_id):
    async with engine.connect() as conn:
        # Each confirm uses its own connection to simulate separate clients
        ...

results = await asyncio.gather(
    *[confirm_one(oid) for oid in order_ids],
    return_exceptions=True
)
successes = [r for r in results if not isinstance(r, Exception)]
assert len(successes) == 5  # exactly stock quantity succeed
```

**What this validates:** `SELECT FOR UPDATE` on `menu_items` serialises concurrent confirms so only as many succeed as there is stock. The other 5 get `InsufficientStockError`.

### Test 2: Double-Cancel Prevention (2 concurrent cancels)

```python
results = await asyncio.gather(cancel(order_id), cancel(order_id), return_exceptions=True)
successes = [r for r in results if not isinstance(r, Exception)]
assert len(successes) == 1  # exactly one cancel wins
```

**What this validates:** Optimistic locking on `orders.version` means the second cancel sees a stale version and raises `ConflictError`.

### Technical Challenge: asyncpg Event Loop
asyncpg raises `"Future attached to a different loop"` when a session-scoped engine is reused across function-scoped event loops. Fixed by using **function-scoped engines** in `conftest.py` — each test gets its own engine bound to its own event loop.

---

## 7. API Documentation & Developer Tools

### Requirement
The API must be explorable without external documentation. Teams must be able to import a ready-to-use Postman collection.

### FastAPI Auto-Documentation
FastAPI automatically exposes:
- `/docs` — Swagger UI (interactive, always current)
- `/redoc` — ReDoc UI
- `/openapi.json` — OpenAPI 3.0 spec (live, reflects current code)

No manual maintenance required.

### Static Snapshot: `docs/openapi.json`
A committed snapshot for:
- Offline reference and code review
- CI diff detection (schema drift alerts)
- Kept in sync via pre-commit hook (see §8)

### Postman Collection: `docs/postman_collection.json`
Generated by `scripts/generate_postman.py`:
- Reads `app.openapi()` at generation time
- Converts OpenAPI 3.0 to Postman Collection v2.1 format
- 18 endpoints organised into 5 folders: **Analytics**, **Health**, **Items**, **Orders**, **Stock**
- Variables: `{{base_url}}` (default `http://localhost:8000`) and `{{api_key}}`
- Realistic example request bodies from `json_schema_extra` on schemas

---

## 8. Pre-commit Quality Gates

### Requirement
Every commit must pass linting, secret scanning, and documentation sync automatically — no manual steps.

### `.pre-commit-config.yaml`

| Hook | Tool | Purpose |
|---|---|---|
| `gitleaks` | gitleaks v8.18.4 | Block commits containing API keys, passwords, tokens |
| `ruff` | astral-sh/ruff-pre-commit v0.4.10 | Lint + auto-fix (isort, pyflakes, pyupgrade, bugbear) |
| `ruff-format` | same | Code formatting (Black-compatible) |
| `generate-openapi` | local | Regenerate `docs/openapi.json` + `docs/postman_collection.json` on any `app/` change |
| `check-copyright` | local | Block commits missing copyright header on `.py` files |

### Ruff Configuration
```toml
[tool.ruff]
target-version = "py313"
line-length = 100
src = ["app", "tests", "scripts"]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "N"]
ignore = [
    "E501",  # line-too-long (formatter handles it)
    "B008",  # function calls in default args (FastAPI pattern)
    "N805",  # cls not named self (false positive)
]
```

### Secret Scanning: `.gitleaks.toml`
Custom allowlist for test fixture UUIDs that superficially resemble secret patterns.

---

## 9. Copyright Protection

### Requirement
Protect intellectual property; prevent unauthorised copying or redistribution of the codebase.

### Implementation

**`LICENSE`** — Proprietary All Rights Reserved:
```
Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.

PROPRIETARY AND CONFIDENTIAL — unauthorised copying, redistribution,
or use is strictly prohibited.
```

**Copyright header on every `.py` file:**
```python
# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
```

**Pre-commit hook (`scripts/check_copyright.py`):**
- Checks every staged `.py` file for the copyright header as the first line
- Blocks the commit if any file is missing it
- Excludes `migrations/` (Alembic auto-generated) and `.venv/`

---

## 10. Design Decisions Summary

| Decision | Rationale |
|---|---|
| `CacheService(None)` = no-op | Zero test complexity; no Redis dependency in unit/integration tests |
| Write-through cache | Stock mutations are infrequent; keeping cache warm on writes avoids stale reads |
| Middleware auth (not FastAPI deps) | Uniform enforcement without per-route decoration; GET always public |
| Rate limit only the hot endpoint | Stock reads are the highest-volume path; other endpoints have lower abuse risk |
| E2E edge case tests separated | Integration tests cover happy path + locking; E2E covers input/state/boundary |
| Function-scoped engines in tests | asyncpg requires engine bound to same event loop as the test coroutine |
| Copyright via pre-commit hook | Automated enforcement; developers can't forget to add headers |
| Static `docs/openapi.json` committed | Enables CI schema drift detection and offline reference |
| Postman collection generated not hand-written | Always in sync with code; no manual maintenance drift |
