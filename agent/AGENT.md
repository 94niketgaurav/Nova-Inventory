# Nova Inventory Service — Claude Agent Instructions

> **REQUIRED:** When a Claude agent picks up this file, immediately invoke the skill:
> `superpowers:executing-plans`
>
> Then follow the parallel execution waves below.

---

## What You Are Building

A production-ready **Inventory & Stock Consistency Service** in Python 3.13 + FastAPI + PostgreSQL 16 + Redis.

Full implementation plan: `../docs/plans/2026-02-26-inventory-stock-service.md`
Design document: `../docs/plans/2026-02-26-inventory-stock-service-design.md`

Working directory for all commands: `/Users/admin2/PycharmProjects/PythonProject/Nova`

---

## Critical Rules Before You Write Any Code

### Configuration
1. **All variable names come from `constants.py`.** Never hardcode string literals like `"nova:stock:"`, `"X-API-Key"`, or `"100/minute"` in service or middleware code — import from `app.core.constants`.
2. **Individual DB env vars, not DATABASE_URL.** Settings uses `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — each with local-dev defaults. The full `database_url` is assembled as a `@property`.
3. **Server starts with zero configuration** against local Postgres/Redis with default credentials. No `.env` needed for local dev.

### Database — singletons
4. `_engine` and `_session_factory` are module-level singletons in `app/db/session.py`. `create_async_engine` is called **once** at import. Do not call it anywhere else.
5. The Redis client `_redis_client` is a module-level singleton in `app/core/cache.py`. Created once at import via `redis.asyncio.from_url()`.
6. On shutdown (lifespan exit): call both `close_engine()` and `close_redis()`.

### Migrations
7. **Validate migrations on startup.** `_validate_migrations()` in `app/main.py` lifespan checks all Alembic revisions are applied before accepting requests. Raises `RuntimeError` with instructions if behind.
8. **No psycopg2 anywhere.** Alembic uses asyncpg too (`async_engine_from_config`). URL in `alembic.ini` is a placeholder; real URL comes from `settings.database_url` (asyncpg).

### Data integrity
9. **Append-only `stock_movements`.** Never `UPDATE` or `DELETE` rows. Only `INSERT`.
10. **Stock deduction is atomic.** `confirm_order()` uses `SELECT FOR UPDATE` on `menu_items` row. No two transactions modify stock simultaneously.
11. **Order transitions use optimistic locking.** `orders.version` checked on every UPDATE. 0 rows affected → `ConflictError`.

### Cache
12. **Write-through cache.** Every stock mutation (`confirm_order`, `cancel_order`, `adjust_stock`, `create_item`) writes to Redis via `CacheService.set_stock()` after DB commit. `get_stock` reads from Redis first, falls back to DB on miss.
13. **Graceful degradation.** All `CacheService` methods catch exceptions and log at WARN — never raise. DB is always the source of truth.

### Auth & Rate Limiting
14. **Auth is optional.** `ApiKeyMiddleware` is always registered but only enforces when `settings.require_auth = True`. GET requests are always public. Only write methods (POST/PATCH/PUT/DELETE) require `X-API-Key` header.
15. **Rate limiter on stock reads.** `GET /api/v1/stock/{item_id}` is explicitly rate-limited via `@limiter.limit(settings.rate_limit_stock_read)`. This protects the most read-heavy endpoint even when auth is disabled.

### Docker
16. **Multi-stage Dockerfile.** Stage 1 builds venv with uv. Stage 2 (runtime) copies only `.venv` + app code — no uv, no pip, no build tools. Use `python -m alembic` and `python -m uvicorn` in entrypoint.
17. **`docker-compose.yml` has zero hardcoded app credentials.** Only `DB_HOST: db` and `REDIS_URL: redis://redis:6379` are set as overrides (Docker network hostnames). Everything else uses `Settings` defaults. Use `env_file: .env` with `required: false` for user overrides.

### Python 3.13
18. Use `str | None` not `Optional[str]`, `list[X]` not `List[X]`, `dict[K, V]` not `Dict[K, V]`.
19. Use `uv run pytest`, `uv run alembic`, `uv run uvicorn` for all commands.

---

## Parallel Execution Waves

### Wave 1 — Foundation (strictly sequential)

| Task | Component |
|---|---|
| Task 1 | `pyproject.toml` (with `redis`, `slowapi`), `alembic.ini`, `.env.example`, folder scaffold, `uv sync` |
| Task 2 | `app/core/config.py` — individual DB parts + Redis + auth + rate-limit settings |
| Task 2b | `app/core/constants.py` — CacheKeys, Headers, RateLimits, LogFields |
| Task 3 | `app/db/base.py`, `app/db/session.py` (singleton engine), `app/domain/enums.py` |
| Task 4 | `app/domain/models/` — MenuItem, Order, StockMovement ORM models |
| Task 5 | `migrations/env.py` (async/asyncpg, URL from settings), `migrations/versions/0001_initial_schema.py` |

**After Wave 1:** `uv run alembic upgrade head` must succeed.

---

### Wave 2 — Core Logic

**Dispatch Tasks 6 and 7 in parallel:**

| Task | Component |
|---|---|
| Task 6 | `app/repositories/` — ItemRepository (with FOR UPDATE), OrderRepository (optimistic), StockRepository |
| Task 7 | `app/core/exceptions.py` — NotFoundError, InsufficientStockError, InvalidTransitionError, ConflictError |

**After 6+7, dispatch Tasks 8 and 9 in parallel:**

| Task | Component |
|---|---|
| Task 8 | `app/services/` — ItemService, OrderService (locking + state machine), StockService |
| Task 9 | `app/schemas/` — ItemCreate/Response, OrderCreate/Response, stock schemas, analytics schemas |

**After Task 8, dispatch Task 8b:**

| Task | Component |
|---|---|
| Task 8b | `app/core/cache.py` (singleton Redis, CacheService with graceful degradation) + update item/order/stock services to write-through |

---

### Wave 3 — API + Infrastructure

**Dispatch Tasks 10 and 12 in parallel:**

| Task | Component |
|---|---|
| Task 10 | `app/api/v1/` — items.py, orders.py, stock.py, analytics.py, router.py |
| Task 12 | **Slim** multi-stage Dockerfile, docker-compose.yml (`env_file`, only Docker hostname overrides), docker-entrypoint.sh |

**After Task 10, dispatch Tasks 10b and 11 in parallel:**

| Task | Component |
|---|---|
| Task 10b | `app/middleware/auth.py` (ApiKeyMiddleware) + rate limiter setup + apply `@limiter.limit` to stock read |
| Task 11 | `app/main.py` — lifespan with `_validate_migrations()`, CORSMiddleware, auth middleware, logging middleware, health endpoint |

---

### Wave 4 — Tests (Task 13 first, then 14/15/16/17 in parallel)

| Task | Component |
|---|---|
| Task 13 | `tests/conftest.py` — testcontainers postgres, per-test rollback isolation |

**After Task 13, dispatch all in parallel:**

| Task | Component |
|---|---|
| Task 14 | `tests/integration/test_order_lifecycle.py` |
| Task 15 | `tests/integration/test_concurrent_orders.py` — race condition test |
| Task 16 | `tests/integration/test_stock_alerts.py` |
| Task 17 | `app/services/analytics_service.py`, `app/api/v1/analytics.py`, `tests/integration/test_analytics.py` |

---

### Wave 5 — Docs & Verification

| Task | Component |
|---|---|
| Task 18 | `README.md` |
| Task 19 | `uv run pytest tests/ -v`, `docker compose build`, `git tag v0.1.0` |

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | Postgres host (`db` in Docker) |
| `DB_PORT` | `5432` | Postgres port |
| `DB_NAME` | `nova_inventory` | Database name |
| `DB_USER` | `postgres` | Postgres user |
| `DB_PASSWORD` | `postgres` | Postgres password |
| `REDIS_URL` | `redis://localhost:6379` | Redis URL (`redis://redis:6379` in Docker) |
| `CACHE_TTL_SECONDS` | `300` | Safety TTL for write-through cache entries |
| `REQUIRE_AUTH` | `false` | Enable API key enforcement |
| `API_KEYS` | `` | Comma-separated valid API keys |
| `RATE_LIMIT_STOCK_READ` | `100/minute` | Rate limit for GET /stock/{id} |
| `RATE_LIMIT_DEFAULT` | `200/minute` | Default rate limit |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## Key File Map

```
Nova/
├── app/
│   ├── main.py                        ← lifespan + migration validation + middleware
│   ├── api/v1/
│   │   ├── items.py
│   │   ├── orders.py
│   │   ├── stock.py                   ← @limiter.limit on get_stock
│   │   ├── analytics.py               ← /summary /stock /orders /movements
│   │   └── router.py
│   ├── core/
│   │   ├── config.py                  ← Settings (individual env parts + @property database_url)
│   │   ├── constants.py               ← CacheKeys, Headers, RateLimits, LogFields
│   │   ├── logging.py                 ← structlog JSON/console
│   │   ├── exceptions.py              ← domain exceptions
│   │   └── cache.py                   ← SINGLETON Redis client + CacheService (write-through)
│   ├── db/
│   │   ├── base.py                    ← DeclarativeBase + TimestampMixin
│   │   └── session.py                 ← SINGLETON engine + session factory
│   ├── domain/
│   │   ├── enums.py                   ← OrderStatus (state machine), MovementType
│   │   └── models/
│   │       ├── item.py
│   │       ├── order.py
│   │       └── stock_movement.py      ← append-only audit log
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py                    ← ApiKeyMiddleware (optional, write-only guard)
│   ├── repositories/
│   │   ├── item_repo.py               ← get_by_id_with_lock() → SELECT FOR UPDATE
│   │   ├── order_repo.py              ← transition_status() → optimistic lock UPDATE
│   │   └── stock_repo.py
│   ├── services/
│   │   ├── item_service.py            ← writes cache after stock mutations
│   │   ├── order_service.py           ← writes cache after confirm/cancel
│   │   ├── stock_service.py           ← reads cache first, DB on miss
│   │   └── analytics_service.py       ← aggregation queries (no N+1)
│   └── schemas/
│       ├── item.py
│       ├── order.py
│       ├── stock.py
│       └── analytics.py
├── migrations/
│   ├── env.py                         ← async Alembic, asyncpg, URL from settings
│   └── versions/0001_initial_schema.py
├── tests/
│   ├── conftest.py                    ← testcontainers postgres, rollback isolation
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_constants.py
│   │   ├── test_enums.py
│   │   ├── test_models.py
│   │   ├── test_schemas.py
│   │   ├── test_exceptions.py
│   │   ├── test_cache.py              ← CacheService unit tests (mocked Redis)
│   │   ├── test_auth_middleware.py    ← ApiKeyMiddleware unit tests
│   │   └── test_order_state_machine.py
│   └── integration/
│       ├── test_order_lifecycle.py
│       ├── test_concurrent_orders.py
│       ├── test_stock_alerts.py
│       └── test_analytics.py
├── agent/
│   └── AGENT.md                       ← YOU ARE HERE
├── docs/plans/
│   ├── 2026-02-26-inventory-stock-service.md          ← full implementation plan
│   └── 2026-02-26-inventory-stock-service-design.md   ← design decisions
├── Dockerfile                         ← multi-stage slim build
├── docker-compose.yml                 ← env_file only, DB_HOST + REDIS_URL overrides
├── docker-entrypoint.sh               ← python -m alembic + python -m uvicorn
├── alembic.ini                        ← placeholder URL (overridden by settings)
├── pyproject.toml                     ← uv-managed, python >=3.13
└── README.md
```

---

## Analytics Endpoints

| Endpoint | What it answers |
|---|---|
| `GET /api/v1/analytics/summary?days=30` | Dashboard: stock + orders + movements |
| `GET /api/v1/analytics/stock` | Total items, units, value, low/out-of-stock counts |
| `GET /api/v1/analytics/orders?days=30` | Status breakdown, revenue (delivered), refund value (cancelled) |
| `GET /api/v1/analytics/movements?days=30` | Deductions, restorations, net stock change |

---

## Test Commands

```bash
# Unit tests (no DB/Redis required)
uv run pytest tests/unit/ -v

# All tests (requires Docker for testcontainers)
uv run pytest tests/ -v --tb=short

# Critical race condition test
uv run pytest tests/integration/test_concurrent_orders.py -v -s

# Coverage
uv run pytest tests/ --cov=app --cov-report=html
```

---

## Pre-flight Checklist Before Claiming Done

- [ ] `uv run pytest tests/ -v` → all green
- [ ] `uv run python -c "from app.main import app; print('OK')"` → no import errors
- [ ] `uv run alembic upgrade head` → succeeds against local Postgres
- [ ] Starting server with stale migration → `RuntimeError` with clear instructions
- [ ] `docker compose build` → succeeds, no uv in final image
- [ ] `GET /health` → `{"status": "ok"}`
- [ ] `GET /docs` → shows all routes including `/api/v1/analytics/*`
- [ ] `GET /api/v1/stock/{id}` without auth → 200 (public read)
- [ ] `POST /api/v1/items` without key when `REQUIRE_AUTH=true` → 401
- [ ] `POST /api/v1/items` with valid key when `REQUIRE_AUTH=true` → 201
