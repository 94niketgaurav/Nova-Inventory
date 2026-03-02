# Inventory & Stock Consistency Service — Design Document

**Date:** 2026-02-26
**Status:** Approved
**Stack:** Python 3.13, FastAPI, PostgreSQL 16, SQLAlchemy (async), Alembic, uv

---

## 1. Problem Statement

Build a backend service that manages inventory and ensures stock consistency under concurrent order placement. Key challenges:

- Atomic stock deduction under high concurrency
- No negative stock (oversell prevention)
- Full audit trail of all stock movements
- Clean domain modeling with a well-defined order lifecycle

---

## 2. Architecture: Layered Monolith

Chosen over CQRS/Event Sourcing (overkill) and Hexagonal (adds indirection without payoff for this scope).

```
HTTP Request
    │
    ▼
API Layer (FastAPI routers)
    │  validates input via Pydantic schemas
    ▼
Service Layer (business logic + transactions + locking)
    │  coordinates repositories, enforces state machine
    ▼
Repository Layer (SQLAlchemy queries)
    │  encapsulates all DB access
    ▼
PostgreSQL (via asyncpg)
```

---

## 3. Folder Structure

```
Nova/
├── app/
│   ├── main.py                        # FastAPI app factory + lifespan
│   ├── api/
│   │   └── v1/
│   │       ├── items.py               # Menu item endpoints
│   │       ├── orders.py              # Order lifecycle endpoints
│   │       └── stock.py               # Stock query + alert endpoints
│   ├── core/
│   │   ├── config.py                  # Settings via pydantic-settings
│   │   └── logging.py                 # structlog JSON/console setup
│   ├── db/
│   │   ├── session.py                 # Async SQLAlchemy session factory
│   │   └── base.py                    # Declarative base
│   ├── domain/
│   │   ├── models/
│   │   │   ├── item.py                # MenuItem ORM model
│   │   │   ├── order.py               # Order ORM model
│   │   │   └── stock_movement.py      # StockMovement ORM model (audit)
│   │   └── enums.py                   # OrderStatus, MovementType
│   ├── repositories/
│   │   ├── item_repo.py
│   │   ├── order_repo.py
│   │   └── stock_repo.py
│   ├── services/
│   │   ├── item_service.py
│   │   ├── order_service.py           # Core: locking + state machine
│   │   └── stock_service.py
│   └── schemas/                       # Pydantic request/response models
│       ├── item.py
│       ├── order.py
│       └── stock.py
├── migrations/                        # Alembic migration scripts
│   └── versions/
├── tests/
│   ├── conftest.py                    # testcontainers postgres fixture
│   ├── unit/
│   │   ├── test_order_state_machine.py
│   │   └── test_stock_service.py
│   └── integration/
│       ├── test_concurrent_orders.py  # 10 concurrent → only 5 succeed
│       ├── test_order_lifecycle.py
│       └── test_stock_alerts.py
├── docs/
│   └── plans/
│       └── 2026-02-26-inventory-stock-service-design.md
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── pyproject.toml                     # uv-managed deps
└── README.md
```

---

## 4. Data Model

### `menu_items`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK, default gen_random_uuid() |
| name | VARCHAR(255) | UNIQUE NOT NULL |
| description | TEXT | nullable |
| price | NUMERIC(10,2) | NOT NULL, > 0 |
| stock_quantity | INTEGER | NOT NULL, >= 0 (CHECK) |
| low_stock_threshold | INTEGER | NOT NULL, default 10 |
| version | INTEGER | NOT NULL, default 1 (optimistic lock) |
| created_at | TIMESTAMPTZ | NOT NULL, default now() |
| updated_at | TIMESTAMPTZ | NOT NULL, auto-updated |

### `orders`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| item_id | UUID | FK → menu_items.id |
| quantity | INTEGER | NOT NULL, > 0 (CHECK) |
| status | order_status ENUM | NOT NULL, default PENDING |
| customer_ref | VARCHAR(255) | nullable |
| version | INTEGER | NOT NULL, default 1 (optimistic lock) |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

### `stock_movements` (append-only audit log)
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| item_id | UUID | FK → menu_items.id |
| order_id | UUID | FK → orders.id, nullable |
| movement_type | movement_type ENUM | NOT NULL |
| quantity_delta | INTEGER | NOT NULL (negative = deduction) |
| stock_before | INTEGER | NOT NULL (snapshot) |
| stock_after | INTEGER | NOT NULL (snapshot) |
| reason | TEXT | nullable |
| created_at | TIMESTAMPTZ | NOT NULL |

---

## 5. Order State Machine

```
                     [stock < quantity]
  PENDING ─────────────────────────────────────► REJECTED
     │
     │  confirm_order()
     │  SELECT FOR UPDATE on menu_items row
     │  Deduct stock atomically + write StockMovement
     ▼
  CONFIRMED ──► ship_order() ──► SHIPPED ──► deliver_order() ──► DELIVERED
     │                              │
     │  cancel_order()              │  cancel_order()
     └──────────────────────────────┴────────────────────────► CANCELLED
                                                 (stock restored via StockMovement)
```

**Rules:**
- Stock deducted **only** on `PENDING → CONFIRMED`
- Stock restored **only** on cancellation from `CONFIRMED`, `SHIPPED`, or `DELIVERED`
- Cancelling a `PENDING` order does NOT restore stock (none was deducted)
- `REJECTED`, `DELIVERED`, and `CANCELLED` are terminal states — no further transitions allowed

---

## 6. Locking Strategy

### Pessimistic Locking (stock writes)
Used in `confirm_order()`:
```sql
SELECT * FROM menu_items WHERE id = :id FOR UPDATE;
```
Holds a row-level exclusive lock for the duration of the transaction. Prevents two concurrent confirms from both reading the same stock and both succeeding when only one should.

### Optimistic Locking (state transitions)
Used on `orders.version` for state transitions:
```sql
UPDATE orders SET status = :new_status, version = version + 1
WHERE id = :id AND version = :expected_version;
```
If 0 rows affected → stale read → raise `ConflictError`. Prevents double-cancellation or double-confirmation races.

---

## 7. API Endpoints

### Menu Items (`/api/v1/items`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/items` | Create item with initial stock |
| GET | `/api/v1/items` | List all items |
| GET | `/api/v1/items/{id}` | Get item + current stock |
| PATCH | `/api/v1/items/{id}/stock` | Manual stock adjustment |

### Orders (`/api/v1/orders`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/orders` | Place order → PENDING |
| POST | `/api/v1/orders/{id}/confirm` | Confirm → deduct stock atomically |
| POST | `/api/v1/orders/{id}/ship` | Transition CONFIRMED → SHIPPED |
| POST | `/api/v1/orders/{id}/deliver` | Transition SHIPPED → DELIVERED |
| POST | `/api/v1/orders/{id}/cancel` | Cancel + restore stock |
| GET | `/api/v1/orders/{id}` | Get order details |

### Stock (`/api/v1/stock`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/stock/{item_id}` | Current stock level |
| GET | `/api/v1/stock/{item_id}/movements` | Full audit trail |
| GET | `/api/v1/stock/alerts/low` | Items below threshold |

---

## 8. Tooling & Infrastructure

### Dependency Management
- `uv` for all package management (`pyproject.toml` + `uv.lock`)
- `uv sync` to install; `uv run` for all commands

### Structured Logging
- `structlog` with JSON output (prod) / colored console (dev)
- Every request: `request_id`, `method`, `path`, `status_code`, `duration_ms`
- Every stock movement: `item_id`, `order_id`, `delta`, `stock_before`, `stock_after`
- Lock contention events logged at WARN level

### Testing
| Layer | Tooling |
|---|---|
| Unit | `pytest`, pure Python, no DB |
| Integration | `pytest-asyncio` + `testcontainers[postgres]` (real Postgres) |
| API | `httpx` + `AsyncClient` |

**Critical test: concurrent stock deduction**
```python
# 10 concurrent confirm_order calls, stock=5 → exactly 5 succeed, 5 reject
results = await asyncio.gather(*[confirm_order(order_id) for order_id in orders], return_exceptions=True)
assert sum(1 for r in results if not isinstance(r, Exception)) == 5
```

### Docker
```yaml
services:
  db:       postgres:16-alpine, persistent volume
  migrate:  uv run alembic upgrade head (runs once, depends_on db)
  api:      uvicorn app.main:app, depends_on migrate
```

---

## 9. Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| FastAPI over Django | Async-native, auto OpenAPI, lighter weight for a service |
| asyncpg over psycopg2 | True async, better performance under concurrent load |
| SELECT FOR UPDATE | Absolute safety for stock writes; contention acceptable at service scale |
| Optimistic locking on orders | Lightweight protection for state transitions without serializing reads |
| Append-only stock_movements | Immutable audit trail; never update/delete, only insert |
| uv over pip/poetry | Faster, deterministic, modern Python tooling |
| testcontainers | Integration tests run against real Postgres, not mocks |
