# Nova Inventory Service

A production-ready **Inventory & Stock Consistency Service** built with Python 3.13, FastAPI, PostgreSQL 16, and Redis. Designed for atomic stock management, concurrent order safety, full audit trails, and plug-and-play caching.

---

## Table of Contents

- [Architecture](#architecture)
- [Order State Machine](#order-state-machine)
- [Locking & Concurrency](#locking--concurrency)
- [Folder Structure](#folder-structure)
- [Quick Start — Local Dev](#quick-start--local-dev)
- [Python Version](#python-version)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [API Documentation](#api-documentation)
- [Quick Start — Docker](#quick-start--docker)
- [Caching](#caching)
- [Auth & Rate Limiting](#auth--rate-limiting)
- [Testing](#testing)
- [Pre-commit Hooks](#pre-commit-hooks)
- [Tech Stack](#tech-stack)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        HTTP Clients                              │
│                (Browser · Postman · curl · SDKs)                 │
└───────────────────────────────┬──────────────────────────────────┘
                                │ HTTP
┌───────────────────────────────▼──────────────────────────────────┐
│                     FastAPI Application                          │
│                                                                  │
│  ┌───────────────┐  ┌─────────────────┐  ┌────────────────────┐ │
│  │ ApiKeyMiddleware│  │ slowapi Limiter │  │ Logging Middleware │ │
│  │ (write-only   │  │ (per-IP, Redis- │  │ (structlog JSON,   │ │
│  │  X-API-Key)   │  │  backed)        │  │  X-Request-ID)     │ │
│  └───────────────┘  └─────────────────┘  └────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  API Routers  /api/v1/                   │   │
│  │  /items    /orders    /stock    /analytics               │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬──────────────────────────────────┘
                                │ call
┌───────────────────────────────▼──────────────────────────────────┐
│                       Service Layer                              │
│                                                                  │
│  ┌──────────────┐  ┌────────────────────────┐  ┌─────────────┐  │
│  │ ItemService  │  │     OrderService        │  │ StockService│  │
│  │              │  │  ┌──────────────────┐  │  │             │  │
│  │ write-through│  │  │ SELECT FOR UPDATE│  │  │ cache-first │  │
│  │ cache on     │  │  │ (pessimistic)    │  │  │ read path   │  │
│  │ every stock  │  │  ├──────────────────┤  │  │             │  │
│  │ mutation     │  │  │ version field    │  │  │             │  │
│  │              │  │  │ (optimistic)     │  │  │             │  │
│  └──────┬───────┘  │  └──────────────────┘  │  └──────┬──────┘  │
│         │          └────────────┬───────────┘         │         │
│         │            ┌──────────▼──────────┐          │         │
│         └────────────►   Redis CacheService ◄──────────┘         │
│                      │  CacheService(redis) │                    │
│                      │  · write-through     │                    │
│                      │  · graceful degrade  │                    │
│                      │  CacheService(None)  │                    │
│                      │  · no-op / DB only   │                    │
│                      └──────────┬──────────┘                    │
└─────────────────────────────────┼────────────────────────────────┘
                                  │
┌─────────────────────────────────▼────────────────────────────────┐
│                      Repository Layer                            │
│  ItemRepository    OrderRepository    StockRepository            │
│  · get_by_id()     · create()         · create_movement()        │
│  · get_by_id_      · get_by_id()      · list_movements_          │
│    with_lock() ◄── · transition_       for_item()                │
│    (FOR UPDATE)    │  status()                                   │
│                    │  (optimistic)                               │
└─────────────────────────────────┬────────────────────────────────┘
                                  │ asyncpg
┌─────────────────────────────────▼────────────────────────────────┐
│                      PostgreSQL 16                               │
│                                                                  │
│  ┌─────────────┐  ┌─────────┐  ┌───────────────────────────┐   │
│  │ menu_items  │  │ orders  │  │   stock_movements          │   │
│  │ · id (UUID) │  │ · id    │  │   (append-only audit log)  │   │
│  │ · name      │  │ · item_id│  │ · item_id / order_id       │   │
│  │ · price     │  │ · qty   │  │ · movement_type            │   │
│  │ · stock_qty │  │ · status│  │ · quantity_delta           │   │
│  │ · version   │  │ · version│  │ · stock_before/after       │   │
│  └─────────────┘  └─────────┘  └───────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Order State Machine

```
                   [stock < qty]
  PENDING ─────────────────────────────────────► REJECTED  ─ (terminal)
     │
     │  confirm_order()
     │  SELECT FOR UPDATE on menu_items row
     │  Deduct stock atomically + write StockMovement
     ▼
  CONFIRMED ──► ship_order() ──► SHIPPED ──► deliver_order() ──► DELIVERED ─ (terminal)
     │                              │
     │  cancel_order()              │  cancel_order()
     └──────────────────────────────┴──────────────────────────► CANCELLED ─ (terminal)
                                                   (stock restored via StockMovement)
```

**Rules:**
- Stock is deducted **only** on `PENDING → CONFIRMED`
- Stock is restored **only** on cancellation from `CONFIRMED`, `SHIPPED`, or `DELIVERED`
- Cancelling a `PENDING` order does **not** restore stock (none was deducted)
- `REJECTED`, `DELIVERED`, and `CANCELLED` are terminal — no further transitions

---

## Locking & Concurrency

| Scenario | Strategy | Why |
|---|---|---|
| Concurrent `confirm_order` | **Pessimistic — `SELECT FOR UPDATE`** | Holds a row-level exclusive lock for the full transaction, preventing two confirms from both reading the same stock level simultaneously |
| State transitions | **Optimistic — `version` field** | Low-contention; `UPDATE orders SET version=v+1 WHERE version=v` — if 0 rows affected, another transaction won the race → `ConflictError` |
| Manual stock adjust | **Pessimistic — `SELECT FOR UPDATE`** | Same safety guarantee as confirm |

**Race condition tests** — see [`tests/integration/test_concurrent_orders.py`](./tests/integration/test_concurrent_orders.py):
- `test_concurrent_orders_no_oversell` — 10 concurrent confirms against stock=5 → exactly 5 succeed, stock=0, never negative
- `test_concurrent_cancellations_no_double_restore` — 2 concurrent cancels → exactly 1 succeeds, stock restored once

---

## Folder Structure

```
Nova/
├── app/
│   ├── main.py                     # FastAPI factory + lifespan + migration validation
│   ├── api/v1/
│   │   ├── deps.py                 # Shared FastAPI dependencies (get_cache)
│   │   ├── items.py                # Menu item CRUD + stock adjust
│   │   ├── orders.py               # Order lifecycle endpoints
│   │   ├── stock.py                # Stock level, movements, low-stock alerts
│   │   ├── analytics.py            # Business analytics endpoints
│   │   └── router.py               # Top-level router (prefix /api/v1)
│   ├── core/
│   │   ├── config.py               # Settings (pydantic-settings, individual DB env vars)
│   │   ├── constants.py            # CacheKeys, Headers, RateLimits, LogFields
│   │   ├── logging.py              # structlog JSON/console setup
│   │   ├── exceptions.py           # Domain exceptions (NotFoundError, InsufficientStockError…)
│   │   └── cache.py                # Singleton Redis client + CacheService (plug-and-play)
│   ├── db/
│   │   ├── base.py                 # DeclarativeBase + TimestampMixin
│   │   └── session.py              # Singleton async engine + session factory
│   ├── domain/
│   │   ├── enums.py                # OrderStatus (state machine), MovementType
│   │   └── models/
│   │       ├── item.py             # MenuItem ORM
│   │       ├── order.py            # Order ORM (optimistic-lock version field)
│   │       └── stock_movement.py   # StockMovement ORM (append-only)
│   ├── middleware/
│   │   └── auth.py                 # ApiKeyMiddleware (optional write guard)
│   ├── repositories/
│   │   ├── item_repo.py            # ItemRepository.get_by_id_with_lock() → SELECT FOR UPDATE
│   │   ├── order_repo.py           # OrderRepository.transition_status() → optimistic lock
│   │   └── stock_repo.py           # StockRepository (append-only inserts)
│   ├── services/
│   │   ├── item_service.py         # ItemService (cache write-through)
│   │   ├── order_service.py        # OrderService (locking + state machine + cache)
│   │   ├── stock_service.py        # StockService (cache-first reads)
│   │   └── analytics_service.py    # AnalyticsService (aggregate queries, no N+1)
│   └── schemas/
│       ├── item.py                 # ItemCreate, ItemResponse, ItemStockAdjust
│       ├── order.py                # OrderCreate, OrderResponse
│       ├── stock.py                # StockResponse, StockMovementResponse, LowStockAlert
│       └── analytics.py            # StockAnalytics, OrderAnalytics, AnalyticsSummary
├── migrations/
│   ├── env.py                      # Async Alembic (asyncpg, URL from settings)
│   └── versions/
│       └── 0001_initial_schema.py
├── tests/
│   ├── TEST_CASES.md               # Full test catalogue (85+ tests with business rules)
│   ├── conftest.py                 # Fixtures: DB engine, session rollback, ASGI client
│   ├── unit/                       # Pure Python — no DB, no Redis required
│   ├── integration/                # Real Postgres (testcontainers or local)
│   └── e2e/                        # Edge cases and boundary conditions
├── scripts/
│   └── generate_postman.py         # Generates docs/postman_collection.json from OpenAPI
├── docs/
│   ├── openapi.json                # Static OpenAPI 3.0 spec snapshot
│   ├── postman_collection.json     # Postman Collection v2.1 (18 endpoints)
│   └── plans/                      # Design doc + implementation plan
├── Dockerfile                      # Multi-stage slim build (uv builder → python runtime)
├── docker-compose.yml              # PostgreSQL + Redis + API service
├── docker-entrypoint.sh            # alembic upgrade head → uvicorn
├── alembic.ini                     # Placeholder URL (overridden by settings at runtime)
├── pyproject.toml                  # uv-managed deps, Python ≥ 3.13
├── .pre-commit-config.yaml         # ruff + gitleaks + openapi regeneration
└── README.md
```

---

## Quick Start — Local Dev

### Prerequisites

- **Python 3.13+** — see [Python Version](#python-version) below
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **PostgreSQL 16** running locally (default: `localhost:5432`, user `postgres`, password `postgres`)
- **Redis** running locally (default: `localhost:6379`) — optional, set `ENABLE_CACHE=false` to skip

```bash
# 1. Clone and enter the project
cd Nova

# 2. Install all dependencies (creates .venv automatically)
uv sync --all-groups

# 3. Create the database
psql -U postgres -c "CREATE DATABASE nova_inventory;"

# 4. Copy environment config
cp .env.example .env

# 5. Run migrations
uv run alembic upgrade head

# 6. Start the server
uv run uvicorn app.main:app --reload

# Server is live at http://localhost:8000
# Swagger UI:  http://localhost:8000/docs
# ReDoc:       http://localhost:8000/redoc
# Health:      http://localhost:8000/health
```

---

## Python Version

This project requires **Python 3.13** or later. It uses modern syntax exclusively:
- `str | None` instead of `Optional[str]`
- `list[X]` / `dict[K, V]` instead of `List[X]` / `Dict[K, V]`
- `match` statements and other 3.10+ features

```bash
# Check your version
python --version        # must be 3.13+

# Pin via uv if needed
uv python pin 3.13

# Install a specific version via uv
uv python install 3.13
```

The `.python-version` file in the repo root pins the version for `uv` and `pyenv` automatically.

---

## Environment Variables

All settings have safe local-dev defaults — the server starts with **zero configuration** against a local Postgres/Redis.

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | PostgreSQL host (`db` in Docker) |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `nova_inventory` | Database name |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | `postgres` | PostgreSQL password |
| `REDIS_URL` | `redis://localhost:6379` | Redis URL (`redis://redis:6379` in Docker) |
| `ENABLE_CACHE` | `true` | Set `false` to disable Redis and go straight to DB |
| `CACHE_TTL_SECONDS` | `300` | TTL for write-through cache entries |
| `REQUIRE_AUTH` | `false` | Enable API key enforcement on write routes |
| `API_KEYS` | `` | Comma-separated valid API keys |
| `RATE_LIMIT_STOCK_READ` | `100/minute` | Rate limit for `GET /stock/{id}` |
| `RATE_LIMIT_DEFAULT` | `200/minute` | Default rate limit |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | Logging level |

Copy `.env.example` to `.env` for local overrides.

---

## API Endpoints

### Menu Items
| Method | Path | Description | Auth required |
|---|---|---|---|
| `POST` | `/api/v1/items` | Create item with initial stock | Write (if enabled) |
| `GET` | `/api/v1/items` | List all items | Never |
| `GET` | `/api/v1/items/{id}` | Get item details | Never |
| `PATCH` | `/api/v1/items/{id}/stock` | Manual stock adjustment | Write (if enabled) |

### Orders
| Method | Path | Description | Auth |
|---|---|---|---|
| `POST` | `/api/v1/orders` | Place order → `PENDING` | Write |
| `GET` | `/api/v1/orders/{id}` | Get order details | Never |
| `POST` | `/api/v1/orders/{id}/confirm` | Confirm → deduct stock atomically | Write |
| `POST` | `/api/v1/orders/{id}/ship` | `CONFIRMED → SHIPPED` | Write |
| `POST` | `/api/v1/orders/{id}/deliver` | `SHIPPED → DELIVERED` | Write |
| `POST` | `/api/v1/orders/{id}/cancel` | Cancel + restore stock | Write |

### Stock
| Method | Path | Description | Rate-limited |
|---|---|---|---|
| `GET` | `/api/v1/stock/{item_id}` | Current stock level | ✓ 100/min |
| `GET` | `/api/v1/stock/{item_id}/movements` | Full audit trail | — |
| `GET` | `/api/v1/stock/alerts/low` | Items below threshold | — |

### Analytics
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/analytics/summary?days=30` | Dashboard: stock + orders + movements |
| `GET` | `/api/v1/analytics/stock` | Inventory value, counts |
| `GET` | `/api/v1/analytics/orders?days=30` | Revenue, refund value, status breakdown |
| `GET` | `/api/v1/analytics/movements?days=30` | Deductions, restorations, net change |

### Other
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/docs` | **Swagger UI** (interactive testing) |
| `GET` | `/redoc` | ReDoc documentation |
| `GET` | `/openapi.json` | Live OpenAPI 3.0 spec |

---

## API Documentation

### Interactive Swagger UI
The live server exposes full interactive documentation at **`http://localhost:8000/docs`**.
It is always in sync with the code — no manual updates needed.

### Static Exports
Static snapshots committed to this repo (regenerated automatically by the pre-commit hook):

| File | Format | Use |
|---|---|---|
| [`docs/openapi.json`](./docs/openapi.json) | OpenAPI 3.0 | Import into Insomnia, Stoplight, ReadMe, or any API tool |
| [`docs/postman_collection.json`](./docs/postman_collection.json) | Postman v2.1 | Import directly into Postman — all 18 endpoints ready |

**Importing into Postman:**
1. Open Postman → Import → File → select `docs/postman_collection.json`
2. Set the `base_url` variable to `http://localhost:8000`
3. Set `api_key` if `REQUIRE_AUTH=true`

**Regenerating after schema changes:**
```bash
uv run python scripts/generate_postman.py
# Or let the pre-commit hook do it automatically on git commit
```

> **Note:** The live server's `/openapi.json` and `/docs` are **always** up-to-date because FastAPI generates them dynamically from the code. The static files in `docs/` are snapshots for tooling integration; the pre-commit hook keeps them in sync.

---

## Quick Start — Docker

Requires Docker + Docker Compose.

```bash
# Build and start all services (Postgres + Redis + API)
docker compose up --build

# The API waits for healthy DB/Redis, runs migrations, then starts.
# Swagger UI: http://localhost:8000/docs

# Stop
docker compose down

# Stop and wipe volumes
docker compose down -v
```

The `Dockerfile` is a **multi-stage build**:
- **Stage 1 (builder)**: Uses `uv` to install production deps into `.venv`
- **Stage 2 (runtime)**: Copies only `.venv` + app code — **no uv, no pip, no build tools in the final image**

See [`Dockerfile`](./Dockerfile) and [`docker-compose.yml`](./docker-compose.yml).

---

## Caching

`GET /api/v1/stock/{item_id}` is the most read-heavy endpoint. Redis acts as a **write-through cache**:

- Every stock mutation (confirm, cancel, adjust) writes to Redis immediately after the DB commit
- Reads check Redis first; if the key is absent or Redis is unreachable, fall back to DB
- `ENABLE_CACHE=false` disables Redis entirely — `CacheService(None)` becomes a no-op

**Plug-and-play injection** — inject a different `CacheService` via FastAPI's `get_cache()` dependency:
```python
# In tests — use no-op cache
def override_get_cache() -> CacheService:
    return CacheService(None)

app.dependency_overrides[get_cache] = override_get_cache
```

---

## Auth & Rate Limiting

**Authentication** (`REQUIRE_AUTH=true`):
- Write routes (`POST`, `PATCH`, `PUT`, `DELETE`) require `X-API-Key: <key>` header
- `GET` routes are always public
- `API_KEYS=key1,key2` — comma-separated list of valid keys

**Rate Limiting** (powered by `slowapi` + Redis):
- `GET /api/v1/stock/{item_id}` → `100/minute` per IP (configurable via `RATE_LIMIT_STOCK_READ`)
- Exceeding the limit returns `429 Too Many Requests`

---

## Testing

See **[`tests/TEST_CASES.md`](./tests/TEST_CASES.md)** for a full catalogue of all 87 tests with their business rules and edge cases.

```bash
# Unit tests — no DB or Redis required
uv run pytest tests/unit/ -v

# Integration tests — requires local Postgres (localhost/nova_test)
uv run pytest tests/integration/ -v --tb=short

# Edge case and boundary tests
uv run pytest tests/e2e/ -v --tb=short

# Critical race condition test (verbose)
uv run pytest tests/integration/test_concurrent_orders.py -v -s

# Full suite with HTML coverage report
uv run pytest tests/ --cov=app --cov-report=html -v
# Open htmlcov/index.html to view
```

### Test Database

Integration tests connect to `postgresql+asyncpg://postgres@localhost/nova_test` by default.
Override with `TEST_DATABASE_URL` env var. If Docker is available, tests spin up a disposable container automatically via `testcontainers`.

Each test runs inside a **rolled-back transaction** — no cleanup fixtures needed, full isolation guaranteed.

---

## Pre-commit Hooks

Code quality is enforced before every commit:

```bash
# Install hooks (one-time setup)
uv run pre-commit install

# Run manually against all files
uv run pre-commit run --all-files
```

Hooks configured in [`.pre-commit-config.yaml`](./.pre-commit-config.yaml):

| Hook | What it does |
|---|---|
| `ruff` | Lints and auto-fixes Python code (replaces flake8, isort, pyupgrade) |
| `ruff-format` | Formats Python code (replaces black) |
| `gitleaks` | Scans for accidental secrets / credentials in committed files |
| `generate-openapi` | Regenerates `docs/openapi.json` and `docs/postman_collection.json` when schemas change |
| `check-copyright` | Blocks commits missing the copyright header on any `.py` file |

---

## Tech Stack

| Component | Technology | Version |
|---|---|---|
| Language | Python | ≥ 3.13 |
| Web framework | FastAPI | ≥ 0.115 |
| ASGI server | Uvicorn | ≥ 0.30 |
| Database | PostgreSQL | 16 |
| ORM | SQLAlchemy (async) | ≥ 2.0 |
| DB driver | asyncpg | ≥ 0.29 |
| Migrations | Alembic | ≥ 1.13 |
| Cache | Redis | ≥ 7 |
| Redis client | redis-py (asyncio) | ≥ 5.0 |
| Rate limiting | slowapi | ≥ 0.1.9 |
| Validation | Pydantic v2 | ≥ 2.7 |
| Settings | pydantic-settings | ≥ 2.3 |
| Logging | structlog | ≥ 24.2 |
| Package manager | uv | latest |
| Containerisation | Docker + Compose | see [`Dockerfile`](./Dockerfile) |
| Testing | pytest + pytest-asyncio | ≥ 8.2 / ≥ 0.23 |
| Integration tests | testcontainers | ≥ 4.7 |
| HTTP test client | httpx | ≥ 0.27 |
| Linting | ruff | ≥ 0.4 |
| Secret scanning | gitleaks | ≥ 8 |
