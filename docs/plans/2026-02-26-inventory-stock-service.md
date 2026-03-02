# Inventory & Stock Consistency Service — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a production-ready FastAPI service that manages inventory stock with atomic deductions, an order state machine, full audit trail, and concurrency safety under race conditions.

**Architecture:** Layered monolith — API routers → Service layer (business logic + transactions + locking) → Repository layer → PostgreSQL. Pessimistic locking (`SELECT FOR UPDATE`) on stock writes, optimistic locking (version field) on order state transitions.

**Tech Stack:** Python 3.13, FastAPI, PostgreSQL 16, SQLAlchemy 2.x (async), asyncpg, Alembic, uv, structlog, pytest, pytest-asyncio, testcontainers, httpx, Docker

---

## Task 1: Project Scaffold & Dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `alembic.ini`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: Initialise the project with uv**

```bash
cd /Users/admin2/PycharmProjects/PythonProject/Nova
uv init --no-workspace
```

**Step 2: Replace the generated `pyproject.toml` with the full dependency spec**

Create `pyproject.toml`:

```toml
[project]
name = "nova-inventory"
version = "0.1.0"
description = "Inventory & Stock Consistency Service"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "structlog>=24.2.0",
    "python-ulid>=2.2.0",
    "redis[hiredis]>=5.0.0",     # write-through stock cache
    "slowapi>=0.1.9",            # rate limiting (wraps `limits` library)
]

[dependency-groups]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "testcontainers[postgres,redis]>=4.7.0",
    "factory-boy>=3.3.0",
    "pytest-cov>=5.0.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "testcontainers[postgres,redis]>=4.7.0",
    "factory-boy>=3.3.0",
    "pytest-cov>=5.0.0",
]
```

**Step 3: Install all dependencies**

```bash
uv sync --all-groups
```

Expected: resolves and installs all packages, creates `uv.lock`

**Step 4: Create `alembic.ini`**

Note: `alembic.ini` stores `sqlalchemy.url` as a placeholder only. The real URL is injected at runtime from `settings.database_url` (asyncpg) inside `migrations/env.py`, so no credentials ever live in the ini file. No psycopg2 needed — Alembic runs async via asyncpg.

```ini
[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = postgresql+psycopg2://placeholder/placeholder

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**Step 5: Create `.env.example`**

Each variable maps directly to a `Settings` field. All have safe local defaults so the server starts without any `.env` file when running against a local Postgres.

```
# Database — each part is independently overridable via env or .env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=nova_inventory
DB_USER=postgres
DB_PASSWORD=postgres

# App
ENVIRONMENT=development
LOG_LEVEL=INFO
LOW_STOCK_DEFAULT_THRESHOLD=10
```

**Step 6: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
.venv/
*.egg-info/
dist/
.pytest_cache/
.coverage
htmlcov/
```

**Step 7: Create all package directories**

```bash
mkdir -p app/api/v1 app/core app/db app/domain/models app/repositories app/services app/schemas
mkdir -p migrations/versions tests/unit tests/integration
touch app/__init__.py app/api/__init__.py app/api/v1/__init__.py
touch app/core/__init__.py app/db/__init__.py app/domain/__init__.py
touch app/domain/models/__init__.py app/repositories/__init__.py
touch app/services/__init__.py app/schemas/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

**Step 8: Commit**

```bash
git init
git add pyproject.toml alembic.ini .env.example .gitignore uv.lock
git commit -m "chore: initialise project scaffold with uv"
```

---

## Task 2: Core Config & Structured Logging

**Files:**
- Create: `app/core/config.py`
- Create: `app/core/logging.py`

**Step 1: Write the failing test**

Create `tests/unit/test_config.py`:

```python
from app.core.config import settings


def test_settings_has_required_fields():
    assert hasattr(settings, "database_url")
    assert hasattr(settings, "environment")
    assert hasattr(settings, "log_level")


def test_environment_default():
    assert settings.environment in ("development", "production", "test")


def test_database_url_built_from_parts():
    url = settings.database_url
    assert "asyncpg" in url          # single async driver for both app + alembic
    assert settings.db_host in url
    assert settings.db_name in url


def test_local_defaults_are_set():
    # Server starts without any .env
    assert settings.db_host == "localhost"
    assert settings.db_port == 5432
    assert settings.db_name == "nova_inventory"


def test_redis_url_has_default():
    assert settings.redis_url.startswith("redis://")


def test_auth_disabled_by_default():
    assert settings.require_auth is False


def test_valid_api_keys_parsing():
    from app.core.config import Settings
    s = Settings(api_keys="key1, key2,  key3 ")
    assert "key1" in s.valid_api_keys
    assert "key2" in s.valid_api_keys
    assert "key3" in s.valid_api_keys
    assert len(s.valid_api_keys) == 3
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.core.config'`

**Step 3: Implement `app/core/config.py`**

Individual env vars (e.g. `DB_HOST`, `DB_PORT`) are used so each part can be overridden independently. The full `database_url` is assembled as a `@property`. All fields have local-dev defaults — zero config needed to run locally.

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.constants import EnvVars


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "nova_inventory"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # ── Redis (write-through stock cache) ─────────────────────────────────────
    redis_url: str = "redis://localhost:6379"
    cache_ttl_seconds: int = 300        # safety TTL even for write-through

    # ── Auth ──────────────────────────────────────────────────────────────────
    require_auth: bool = False          # False = open in dev; True = enforce API key
    api_keys: str = ""                  # comma-separated; empty = all keys rejected when auth on

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_stock_read: str = "100/minute"
    rate_limit_default: str = "200/minute"

    # ── App ───────────────────────────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"
    low_stock_default_threshold: int = 10

    @property
    def database_url(self) -> str:
        """Async URL (asyncpg) — used by both SQLAlchemy engine AND Alembic migrations."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def valid_api_keys(self) -> frozenset[str]:
        if not self.api_keys:
            return frozenset()
        return frozenset(k.strip() for k in self.api_keys.split(",") if k.strip())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton — instantiated once, cached forever."""
    return Settings()


settings = get_settings()
```

**Step 4: Implement `app/core/logging.py`**

```python
import logging
import sys
import structlog
from app.core.config import settings


def configure_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.is_production:
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: 2 PASSED

**Step 6: Commit**

```bash
git add app/core/config.py app/core/logging.py tests/unit/test_config.py
git commit -m "feat: add core config and structured logging"
```

---

## Task 2b: Constants

**Files:**
- Create: `app/core/constants.py`

All magic strings in one place — env var names, cache key prefixes, HTTP headers, default values. Never repeat a string literal in two places.

### Step 1: Write failing test

Create `tests/unit/test_constants.py`:

```python
from app.core.constants import CacheKeys, Headers, RateLimits
import uuid


def test_stock_cache_key_format():
    item_id = uuid.uuid4()
    key = CacheKeys.stock(item_id)
    assert key.startswith("nova:stock:")
    assert str(item_id) in key


def test_headers_defined():
    assert Headers.REQUEST_ID == "X-Request-ID"
    assert Headers.API_KEY == "X-API-Key"


def test_rate_limits_are_strings():
    # slowapi expects "N/period" strings
    assert "/" in RateLimits.STOCK_READ
    assert "/" in RateLimits.DEFAULT
```

### Step 2: Run to verify it fails

```bash
uv run pytest tests/unit/test_constants.py -v
```

Expected: `ModuleNotFoundError`

### Step 3: Implement `app/core/constants.py`

```python
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
    Override via Settings.rate_limit_stock_read / Settings.rate_limit_default.
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
```

### Step 4: Run tests

```bash
uv run pytest tests/unit/test_constants.py -v
```

Expected: 3 PASSED

### Step 5: Commit

```bash
git add app/core/constants.py tests/unit/test_constants.py
git commit -m "feat: add constants module (cache keys, headers, rate limits)"
```

---

## Task 3: Database Base & Enums

**Files:**
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/domain/enums.py`

**Step 1: Write failing test**

Create `tests/unit/test_enums.py`:

```python
from app.domain.enums import OrderStatus, MovementType


def test_order_status_terminal_states():
    assert OrderStatus.REJECTED in OrderStatus.terminal_states()
    assert OrderStatus.DELIVERED in OrderStatus.terminal_states()
    assert OrderStatus.CANCELLED in OrderStatus.terminal_states()
    assert OrderStatus.PENDING not in OrderStatus.terminal_states()
    assert OrderStatus.CONFIRMED not in OrderStatus.terminal_states()


def test_order_status_stock_restore_states():
    restore = OrderStatus.stock_holding_states()
    assert OrderStatus.CONFIRMED in restore
    assert OrderStatus.SHIPPED in restore
    assert OrderStatus.DELIVERED in restore
    assert OrderStatus.PENDING not in restore


def test_movement_type_values():
    assert MovementType.DEDUCTION.value == "DEDUCTION"
    assert MovementType.RESTORATION.value == "RESTORATION"
    assert MovementType.ADJUSTMENT.value == "ADJUSTMENT"
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/unit/test_enums.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement `app/domain/enums.py`**

```python
import enum


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @classmethod
    def terminal_states(cls) -> frozenset["OrderStatus"]:
        return frozenset({cls.REJECTED, cls.DELIVERED, cls.CANCELLED})

    @classmethod
    def stock_holding_states(cls) -> frozenset["OrderStatus"]:
        """States where stock has been deducted and must be restored on cancel."""
        return frozenset({cls.CONFIRMED, cls.SHIPPED, cls.DELIVERED})

    @classmethod
    def valid_transitions(cls) -> dict["OrderStatus", frozenset["OrderStatus"]]:
        return {
            cls.PENDING: frozenset({cls.CONFIRMED, cls.REJECTED, cls.CANCELLED}),
            cls.CONFIRMED: frozenset({cls.SHIPPED, cls.CANCELLED}),
            cls.SHIPPED: frozenset({cls.DELIVERED, cls.CANCELLED}),
            cls.DELIVERED: frozenset(),
            cls.CANCELLED: frozenset(),
            cls.REJECTED: frozenset(),
        }

    def can_transition_to(self, next_status: "OrderStatus") -> bool:
        return next_status in self.valid_transitions().get(self, frozenset())


class MovementType(str, enum.Enum):
    DEDUCTION = "DEDUCTION"
    RESTORATION = "RESTORATION"
    ADJUSTMENT = "ADJUSTMENT"
```

**Step 4: Implement `app/db/base.py`**

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
```

**Step 5: Implement `app/db/session.py`**

The engine and session factory are module-level singletons. `create_async_engine` is called **once** at import time. `get_engine()` / `get_session_factory()` expose them for testing overrides without re-creating anything.

```python
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.core.config import settings

# ── Singleton engine — created once, reused for the lifetime of the process ──
_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,       # recycles stale connections transparently
    pool_recycle=3600,        # recycle connections after 1 hour
)

# ── Singleton session factory — bound to the engine above ──
_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


def get_engine() -> AsyncEngine:
    """Return the process-wide engine singleton."""
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory singleton."""
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session, commits on success, rolls back on error."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """Gracefully dispose the engine on shutdown (called from lifespan)."""
    await _engine.dispose()
```

**Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_enums.py -v
```

Expected: 3 PASSED

**Step 7: Commit**

```bash
git add app/db/base.py app/db/session.py app/domain/enums.py tests/unit/test_enums.py
git commit -m "feat: add db base, session factory, and domain enums"
```

---

## Task 4: Domain Models (ORM)

**Files:**
- Create: `app/domain/models/item.py`
- Create: `app/domain/models/order.py`
- Create: `app/domain/models/stock_movement.py`
- Modify: `app/domain/models/__init__.py`

**Step 1: Implement `app/domain/models/item.py`**

```python
import uuid
from decimal import Decimal
from sqlalchemy import CheckConstraint, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class MenuItem(Base, TimestampMixin):
    __tablename__ = "menu_items"
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_menu_items_stock_non_negative"),
        CheckConstraint("price > 0", name="ck_menu_items_price_positive"),
        CheckConstraint("low_stock_threshold >= 0", name="ck_menu_items_threshold_non_negative"),
        UniqueConstraint("name", name="uq_menu_items_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    orders: Mapped[list["Order"]] = relationship(back_populates="item")
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="item")

    @property
    def is_low_stock(self) -> bool:
        return self.stock_quantity <= self.low_stock_threshold
```

**Step 2: Implement `app/domain/models/order.py`**

```python
import uuid
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from app.domain.enums import OrderStatus


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        String(20), nullable=False, default=OrderStatus.PENDING
    )
    customer_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    item: Mapped["MenuItem"] = relationship(back_populates="orders")
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="order")
```

**Step 3: Implement `app/domain/models/stock_movement.py`**

```python
import uuid
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.domain.enums import MovementType
from datetime import datetime, timezone
from sqlalchemy import DateTime


class StockMovement(Base):
    """Append-only audit log. Never UPDATE or DELETE rows."""
    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True
    )
    movement_type: Mapped[MovementType] = mapped_column(
        Text, nullable=False
    )
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_before: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    item: Mapped["MenuItem"] = relationship(back_populates="stock_movements")
    order: Mapped["Order | None"] = relationship(back_populates="stock_movements")
```

**Step 4: Update `app/domain/models/__init__.py`**

```python
from app.domain.models.item import MenuItem
from app.domain.models.order import Order
from app.domain.models.stock_movement import StockMovement

__all__ = ["MenuItem", "Order", "StockMovement"]
```

**Step 5: Write a unit test for model properties**

Create `tests/unit/test_models.py`:

```python
from app.domain.models.item import MenuItem
from app.domain.enums import OrderStatus


def test_menu_item_is_low_stock_true():
    item = MenuItem(name="Burger", price=10.0, stock_quantity=5, low_stock_threshold=10)
    assert item.is_low_stock is True


def test_menu_item_is_low_stock_false():
    item = MenuItem(name="Burger", price=10.0, stock_quantity=15, low_stock_threshold=10)
    assert item.is_low_stock is False


def test_menu_item_is_low_stock_at_threshold():
    item = MenuItem(name="Burger", price=10.0, stock_quantity=10, low_stock_threshold=10)
    assert item.is_low_stock is True


def test_order_status_transitions():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.CONFIRMED) is True
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.SHIPPED) is False
    assert OrderStatus.DELIVERED.can_transition_to(OrderStatus.CANCELLED) is False
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.CANCELLED) is True
```

**Step 6: Run tests**

```bash
uv run pytest tests/unit/test_models.py tests/unit/test_enums.py -v
```

Expected: 7 PASSED

**Step 7: Commit**

```bash
git add app/domain/models/ tests/unit/test_models.py
git commit -m "feat: add domain ORM models (MenuItem, Order, StockMovement)"
```

---

## Task 5: Alembic Migrations

**Files:**
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_initial_schema.py`

**Step 1: Initialise Alembic**

```bash
uv run alembic init migrations
```

**Step 2: Replace `migrations/env.py` with async-aware version**

The URL is read from `settings.database_url_sync` (psycopg2/sync driver, required by Alembic). This means no credentials in `alembic.ini` — they come from env vars or `.env` at runtime.

Alembic runs fully async via asyncpg — no psycopg2 needed at all.

```python
import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from app.core.config import settings
from app.db.base import Base
from app.domain.models import MenuItem, Order, StockMovement  # noqa: F401 — register models

config = context.config

# Override URL from settings — asyncpg, no credentials in alembic.ini
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 3: Create the initial migration manually**

Create `migrations/versions/0001_initial_schema.py`:

```python
"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "menu_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("stock_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer, nullable=False, server_default="10"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_menu_items_stock_non_negative"),
        sa.CheckConstraint("price > 0", name="ck_menu_items_price_positive"),
        sa.CheckConstraint("low_stock_threshold >= 0", name="ck_menu_items_threshold_non_negative"),
        sa.UniqueConstraint("name", name="uq_menu_items_name"),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("customer_ref", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("movement_type", sa.Text, nullable=False),
        sa.Column("quantity_delta", sa.Integer, nullable=False),
        sa.Column("stock_before", sa.Integer, nullable=False),
        sa.Column("stock_after", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Indexes for common queries
    op.create_index("ix_orders_item_id", "orders", ["item_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_stock_movements_item_id", "stock_movements", ["item_id"])
    op.create_index("ix_stock_movements_order_id", "stock_movements", ["order_id"])


def downgrade() -> None:
    op.drop_table("stock_movements")
    op.drop_table("orders")
    op.drop_table("menu_items")
```

**Step 4: Commit**

```bash
git add migrations/ alembic.ini
git commit -m "feat: add alembic async migrations with initial schema"
```

---

## Task 6: Repositories

**Files:**
- Create: `app/repositories/item_repo.py`
- Create: `app/repositories/order_repo.py`
- Create: `app/repositories/stock_repo.py`

**Step 1: Implement `app/repositories/item_repo.py`**

```python
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.domain.models.item import MenuItem


class ItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: MenuItem) -> MenuItem:
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> MenuItem | None:
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_lock(self, item_id: uuid.UUID) -> MenuItem | None:
        """Acquires a row-level exclusive lock. Use inside a transaction."""
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.id == item_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[MenuItem]:
        result = await self._session.execute(select(MenuItem).order_by(MenuItem.name))
        return list(result.scalars().all())

    async def list_low_stock(self) -> list[MenuItem]:
        result = await self._session.execute(
            select(MenuItem).where(
                MenuItem.stock_quantity <= MenuItem.low_stock_threshold
            ).order_by(MenuItem.stock_quantity)
        )
        return list(result.scalars().all())

    async def save(self, item: MenuItem) -> MenuItem:
        await self._session.flush()
        await self._session.refresh(item)
        return item
```

**Step 2: Implement `app/repositories/order_repo.py`**

```python
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.models.order import Order
from app.domain.enums import OrderStatus


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.flush()
        await self._session.refresh(order)
        return order

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        result = await self._session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def transition_status(
        self,
        order_id: uuid.UUID,
        expected_version: int,
        new_status: OrderStatus,
    ) -> bool:
        """Optimistic locking: returns False if version mismatch (concurrent update)."""
        result = await self._session.execute(
            update(Order)
            .where(Order.id == order_id, Order.version == expected_version)
            .values(status=new_status, version=Order.version + 1)
            .returning(Order.id)
        )
        return result.scalar_one_or_none() is not None
```

**Step 3: Implement `app/repositories/stock_repo.py`**

```python
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.models.stock_movement import StockMovement


class StockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_movement(self, movement: StockMovement) -> StockMovement:
        self._session.add(movement)
        await self._session.flush()
        return movement

    async def list_movements_for_item(
        self, item_id: uuid.UUID, limit: int = 100
    ) -> list[StockMovement]:
        result = await self._session.execute(
            select(StockMovement)
            .where(StockMovement.item_id == item_id)
            .order_by(StockMovement.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
```

**Step 4: Commit**

```bash
git add app/repositories/
git commit -m "feat: add item, order, and stock repositories"
```

---

## Task 7: Custom Exceptions

**Files:**
- Create: `app/core/exceptions.py`

**Step 1: Implement `app/core/exceptions.py`**

```python
class NotFoundError(Exception):
    """Resource does not exist."""
    def __init__(self, resource: str, resource_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found")


class InsufficientStockError(Exception):
    """Stock is too low to fulfil the order."""
    def __init__(self, item_id: object, requested: int, available: int) -> None:
        self.item_id = item_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for item {item_id}: "
            f"requested {requested}, available {available}"
        )


class InvalidTransitionError(Exception):
    """Order state machine transition is not allowed."""
    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"Cannot transition order from {current} to {requested}")


class ConflictError(Exception):
    """Concurrent modification detected (optimistic lock failure)."""
    def __init__(self, resource: str, resource_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"Concurrent update conflict on {resource} {resource_id}")
```

**Step 2: Write unit tests**

Create `tests/unit/test_exceptions.py`:

```python
from app.core.exceptions import (
    NotFoundError, InsufficientStockError, InvalidTransitionError, ConflictError
)
import uuid


def test_not_found_error_message():
    item_id = uuid.uuid4()
    err = NotFoundError("MenuItem", item_id)
    assert str(item_id) in str(err)
    assert "MenuItem" in str(err)


def test_insufficient_stock_error():
    item_id = uuid.uuid4()
    err = InsufficientStockError(item_id, requested=10, available=3)
    assert err.requested == 10
    assert err.available == 3


def test_invalid_transition_error():
    err = InvalidTransitionError("DELIVERED", "CONFIRMED")
    assert "DELIVERED" in str(err)


def test_conflict_error():
    order_id = uuid.uuid4()
    err = ConflictError("Order", order_id)
    assert "Order" in str(err)
```

**Step 3: Run tests**

```bash
uv run pytest tests/unit/test_exceptions.py -v
```

Expected: 4 PASSED

**Step 4: Commit**

```bash
git add app/core/exceptions.py tests/unit/test_exceptions.py
git commit -m "feat: add domain exceptions"
```

---

## Task 8: Services

**Files:**
- Create: `app/services/item_service.py`
- Create: `app/services/order_service.py`
- Create: `app/services/stock_service.py`

**Step 1: Write unit tests for order state machine logic first**

Create `tests/unit/test_order_state_machine.py`:

```python
import pytest
from app.domain.enums import OrderStatus


def test_pending_can_confirm():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.CONFIRMED) is True

def test_pending_can_reject():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.REJECTED) is True

def test_pending_can_cancel():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.CANCELLED) is True

def test_pending_cannot_ship():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.SHIPPED) is False

def test_confirmed_can_ship():
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.SHIPPED) is True

def test_confirmed_can_cancel():
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.CANCELLED) is True

def test_confirmed_cannot_deliver():
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.DELIVERED) is False

def test_shipped_can_deliver():
    assert OrderStatus.SHIPPED.can_transition_to(OrderStatus.DELIVERED) is True

def test_shipped_can_cancel():
    assert OrderStatus.SHIPPED.can_transition_to(OrderStatus.CANCELLED) is True

def test_delivered_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.DELIVERED.can_transition_to(status) is False

def test_cancelled_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.CANCELLED.can_transition_to(status) is False

def test_rejected_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.REJECTED.can_transition_to(status) is False

def test_stock_holding_states_require_restoration():
    holding = OrderStatus.stock_holding_states()
    assert OrderStatus.CONFIRMED in holding
    assert OrderStatus.SHIPPED in holding
    assert OrderStatus.DELIVERED in holding
    assert OrderStatus.PENDING not in holding
    assert OrderStatus.REJECTED not in holding
```

**Step 2: Run to verify all pass (state machine already implemented)**

```bash
uv run pytest tests/unit/test_order_state_machine.py -v
```

Expected: 13 PASSED

**Step 3: Implement `app/services/item_service.py`**

```python
import uuid
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.domain.enums import MovementType
from app.domain.models.item import MenuItem
from app.domain.models.stock_movement import StockMovement
from app.repositories.item_repo import ItemRepository
from app.repositories.stock_repo import StockRepository

logger = get_logger(__name__)


class ItemService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._items = ItemRepository(session)
        self._stock = StockRepository(session)

    async def create_item(
        self,
        name: str,
        price: Decimal,
        stock_quantity: int,
        description: str | None = None,
        low_stock_threshold: int = 10,
    ) -> MenuItem:
        item = MenuItem(
            name=name,
            description=description,
            price=price,
            stock_quantity=stock_quantity,
            low_stock_threshold=low_stock_threshold,
        )
        item = await self._items.create(item)

        # Audit the initial stock
        await self._stock.create_movement(
            StockMovement(
                item_id=item.id,
                movement_type=MovementType.ADJUSTMENT,
                quantity_delta=stock_quantity,
                stock_before=0,
                stock_after=stock_quantity,
                reason="Initial stock on item creation",
            )
        )
        logger.info("item_created", item_id=str(item.id), name=name, stock=stock_quantity)
        return item

    async def adjust_stock(
        self, item_id: uuid.UUID, delta: int, reason: str
    ) -> MenuItem:
        item = await self._items.get_by_id_with_lock(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)

        stock_before = item.stock_quantity
        new_quantity = stock_before + delta
        if new_quantity < 0:
            from app.core.exceptions import InsufficientStockError
            raise InsufficientStockError(item_id, abs(delta), stock_before)

        item.stock_quantity = new_quantity
        item.version += 1
        await self._stock.create_movement(
            StockMovement(
                item_id=item.id,
                movement_type=MovementType.ADJUSTMENT,
                quantity_delta=delta,
                stock_before=stock_before,
                stock_after=new_quantity,
                reason=reason,
            )
        )
        await self._items.save(item)
        logger.info(
            "stock_adjusted",
            item_id=str(item_id),
            delta=delta,
            stock_before=stock_before,
            stock_after=new_quantity,
        )
        return item

    async def get_item(self, item_id: uuid.UUID) -> MenuItem:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)
        return item

    async def list_items(self) -> list[MenuItem]:
        return await self._items.list_all()

    async def list_low_stock(self) -> list[MenuItem]:
        return await self._items.list_low_stock()
```

**Step 4: Implement `app/services/order_service.py`**

```python
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import (
    ConflictError, InsufficientStockError, InvalidTransitionError, NotFoundError,
)
from app.core.logging import get_logger
from app.domain.enums import MovementType, OrderStatus
from app.domain.models.order import Order
from app.domain.models.stock_movement import StockMovement
from app.repositories.item_repo import ItemRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.stock_repo import StockRepository

logger = get_logger(__name__)


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._items = ItemRepository(session)
        self._stock = StockRepository(session)

    async def place_order(
        self, item_id: uuid.UUID, quantity: int, customer_ref: str | None = None
    ) -> Order:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)

        order = Order(
            item_id=item_id,
            quantity=quantity,
            status=OrderStatus.PENDING,
            customer_ref=customer_ref,
        )
        order = await self._orders.create(order)
        logger.info("order_placed", order_id=str(order.id), item_id=str(item_id), qty=quantity)
        return order

    async def confirm_order(self, order_id: uuid.UUID) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        if not order.status.can_transition_to(OrderStatus.CONFIRMED):
            raise InvalidTransitionError(order.status, OrderStatus.CONFIRMED)

        # Pessimistic lock on the item row — prevents concurrent oversell
        item = await self._items.get_by_id_with_lock(order.item_id)
        if not item:
            raise NotFoundError("MenuItem", order.item_id)

        if item.stock_quantity < order.quantity:
            # Reject the order — insufficient stock
            updated = await self._orders.transition_status(
                order_id, order.version, OrderStatus.REJECTED
            )
            if not updated:
                raise ConflictError("Order", order_id)
            logger.warning(
                "order_rejected_insufficient_stock",
                order_id=str(order_id),
                available=item.stock_quantity,
                requested=order.quantity,
            )
            raise InsufficientStockError(item.id, order.quantity, item.stock_quantity)

        # Deduct stock atomically within this locked transaction
        stock_before = item.stock_quantity
        item.stock_quantity -= order.quantity
        item.version += 1

        await self._stock.create_movement(
            StockMovement(
                item_id=item.id,
                order_id=order.id,
                movement_type=MovementType.DEDUCTION,
                quantity_delta=-order.quantity,
                stock_before=stock_before,
                stock_after=item.stock_quantity,
                reason=f"Stock deducted for order {order_id}",
            )
        )
        await self._items.save(item)

        updated = await self._orders.transition_status(
            order_id, order.version, OrderStatus.CONFIRMED
        )
        if not updated:
            raise ConflictError("Order", order_id)

        logger.info(
            "order_confirmed",
            order_id=str(order_id),
            stock_before=stock_before,
            stock_after=item.stock_quantity,
        )
        return await self._orders.get_by_id(order_id)

    async def ship_order(self, order_id: uuid.UUID) -> Order:
        return await self._transition(order_id, OrderStatus.SHIPPED)

    async def deliver_order(self, order_id: uuid.UUID) -> Order:
        return await self._transition(order_id, OrderStatus.DELIVERED)

    async def cancel_order(self, order_id: uuid.UUID) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        if not order.status.can_transition_to(OrderStatus.CANCELLED):
            raise InvalidTransitionError(order.status, OrderStatus.CANCELLED)

        should_restore = order.status in OrderStatus.stock_holding_states()

        if should_restore:
            item = await self._items.get_by_id_with_lock(order.item_id)
            if item:
                stock_before = item.stock_quantity
                item.stock_quantity += order.quantity
                item.version += 1
                await self._stock.create_movement(
                    StockMovement(
                        item_id=item.id,
                        order_id=order.id,
                        movement_type=MovementType.RESTORATION,
                        quantity_delta=order.quantity,
                        stock_before=stock_before,
                        stock_after=item.stock_quantity,
                        reason=f"Stock restored on cancellation of order {order_id}",
                    )
                )
                await self._items.save(item)
                logger.info(
                    "stock_restored",
                    order_id=str(order_id),
                    qty=order.quantity,
                    stock_after=item.stock_quantity,
                )

        updated = await self._orders.transition_status(
            order_id, order.version, OrderStatus.CANCELLED
        )
        if not updated:
            raise ConflictError("Order", order_id)

        return await self._orders.get_by_id(order_id)

    async def get_order(self, order_id: uuid.UUID) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        return order

    async def _transition(self, order_id: uuid.UUID, new_status: OrderStatus) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        if not order.status.can_transition_to(new_status):
            raise InvalidTransitionError(order.status, new_status)
        updated = await self._orders.transition_status(order_id, order.version, new_status)
        if not updated:
            raise ConflictError("Order", order_id)
        logger.info("order_transitioned", order_id=str(order_id), new_status=new_status)
        return await self._orders.get_by_id(order_id)
```

**Step 5: Implement `app/services/stock_service.py`**

```python
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError
from app.domain.models.item import MenuItem
from app.domain.models.stock_movement import StockMovement
from app.repositories.item_repo import ItemRepository
from app.repositories.stock_repo import StockRepository


class StockService:
    def __init__(self, session: AsyncSession) -> None:
        self._items = ItemRepository(session)
        self._stock = StockRepository(session)

    async def get_stock(self, item_id: uuid.UUID) -> MenuItem:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)
        return item

    async def get_movements(
        self, item_id: uuid.UUID, limit: int = 100
    ) -> list[StockMovement]:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)
        return await self._stock.list_movements_for_item(item_id, limit)

    async def get_low_stock_items(self) -> list[MenuItem]:
        return await self._items.list_low_stock()
```

**Step 6: Commit**

```bash
git add app/services/
git commit -m "feat: add item, order (with locking), and stock services"
```

---

## Task 8b: Write-Through Stock Cache

**Files:**
- Create: `app/core/cache.py`
- Modify: `app/services/item_service.py` — write cache on every stock mutation
- Modify: `app/services/order_service.py` — write cache on confirm/cancel
- Modify: `app/services/stock_service.py` — read cache first, DB on miss

**Why write-through?**
`GET /api/v1/stock/{item_id}` is read-heavy (always shown, polled frequently). Stock changes happen only on `confirm_order`, `cancel_order`, and `adjust_stock`. Writing to cache on every mutation means reads are almost always served from Redis — zero DB load for stock reads. Graceful degradation: if Redis is down, fall back to DB transparently.

### Step 1: Write failing tests

Create `tests/unit/test_cache.py`:

```python
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from app.core.cache import CacheService
from app.core.constants import CacheKeys


@pytest.mark.asyncio
async def test_set_stock_stores_with_ttl():
    redis = AsyncMock()
    cache = CacheService(redis)
    item_id = uuid.uuid4()

    await cache.set_stock(item_id, 42)
    redis.setex.assert_called_once()
    call_args = redis.setex.call_args
    assert CacheKeys.stock(item_id) in str(call_args)
    assert b"42" in str(call_args) or "42" in str(call_args)


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
async def test_cache_service_degrades_gracefully_on_redis_error():
    redis = AsyncMock()
    redis.get.side_effect = Exception("Redis down")
    cache = CacheService(redis)
    # Should not raise — returns None so caller falls back to DB
    result = await cache.get_stock(uuid.uuid4())
    assert result is None
```

### Step 2: Run to verify they fail

```bash
uv run pytest tests/unit/test_cache.py -v
```

Expected: `ModuleNotFoundError`

### Step 3: Implement `app/core/cache.py`

```python
import uuid
import redis.asyncio as aioredis
import structlog
from app.core.config import settings
from app.core.constants import CacheKeys

logger = structlog.get_logger(__name__)

# ── Singleton Redis client — created once at import time ─────────────────────
_redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=False,   # raw bytes for get; we decode manually
    socket_connect_timeout=2,
    socket_timeout=2,
)


def get_redis() -> aioredis.Redis:
    """Return the process-wide Redis singleton."""
    return _redis_client


async def close_redis() -> None:
    """Graceful shutdown (called from lifespan)."""
    await _redis_client.aclose()


class CacheService:
    """
    Write-through cache for stock quantities.
    All methods catch Redis errors and degrade gracefully to DB.
    """

    def __init__(self, redis: aioredis.Redis | None = None) -> None:
        self._redis = redis or get_redis()

    async def get_stock(self, item_id: uuid.UUID) -> int | None:
        """Return cached stock quantity, or None if miss/error."""
        try:
            value = await self._redis.get(CacheKeys.stock(item_id))
            if value is None:
                return None
            return int(value)
        except Exception as exc:
            logger.warning("cache_read_error", item_id=str(item_id), error=str(exc))
            return None

    async def set_stock(self, item_id: uuid.UUID, quantity: int) -> None:
        """Write stock quantity to cache with TTL. Fire-and-forget on error."""
        try:
            await self._redis.setex(
                CacheKeys.stock(item_id),
                settings.cache_ttl_seconds,
                str(quantity),
            )
            logger.debug("cache_write", item_id=str(item_id), quantity=quantity)
        except Exception as exc:
            logger.warning("cache_write_error", item_id=str(item_id), error=str(exc))

    async def invalidate_stock(self, item_id: uuid.UUID) -> None:
        """Remove from cache (used for safety on unexpected state)."""
        try:
            await self._redis.delete(CacheKeys.stock(item_id))
        except Exception as exc:
            logger.warning("cache_invalidate_error", item_id=str(item_id), error=str(exc))
```

### Step 4: Update `app/services/item_service.py` — add cache write-through

In `create_item()` and `adjust_stock()`, after every `save()`, add:

```python
from app.core.cache import CacheService

# Inside create_item(), after save:
await CacheService().set_stock(item.id, item.stock_quantity)

# Inside adjust_stock(), after save:
await CacheService().set_stock(item.id, item.stock_quantity)
```

### Step 5: Update `app/services/order_service.py` — add cache write-through

In `confirm_order()`, after `save(item)`:
```python
await CacheService().set_stock(item.id, item.stock_quantity)
```

In `cancel_order()`, after `save(item)`:
```python
await CacheService().set_stock(item.id, item.stock_quantity)
```

### Step 6: Update `app/services/stock_service.py` — cache-first read

```python
async def get_stock(self, item_id: uuid.UUID) -> MenuItem:
    # 1. Try cache first
    cached_qty = await CacheService().get_stock(item_id)
    item = await self._items.get_by_id(item_id)
    if not item:
        raise NotFoundError("MenuItem", item_id)

    # 2. Cache hit — inject cached value (avoid DB read for hot path)
    if cached_qty is not None:
        item.stock_quantity = cached_qty

    return item
```

### Step 7: Update `app/main.py` lifespan — close Redis on shutdown

```python
from app.core.cache import close_redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", ...)
    await _validate_migrations()
    yield
    logger.info("shutdown")
    await close_engine()
    await close_redis()     # ← add this
```

### Step 8: Run cache tests

```bash
uv run pytest tests/unit/test_cache.py -v
```

Expected: 4 PASSED

### Step 9: Commit

```bash
git add app/core/cache.py app/services/ tests/unit/test_cache.py
git commit -m "feat: add write-through Redis cache for stock reads"
```

---

## Task 9: Pydantic Schemas

**Files:**
- Create: `app/schemas/item.py`
- Create: `app/schemas/order.py`
- Create: `app/schemas/stock.py`
- Create: `app/schemas/common.py`

**Step 1: Create `app/schemas/common.py`**

```python
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    code: str
```

**Step 2: Create `app/schemas/item.py`**

```python
import uuid
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(..., gt=0, decimal_places=2)
    stock_quantity: int = Field(..., ge=0)
    low_stock_threshold: int = Field(default=10, ge=0)


class StockAdjustRequest(BaseModel):
    delta: int = Field(..., description="Positive to add, negative to remove")
    reason: str = Field(..., min_length=1)


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    stock_quantity: int
    low_stock_threshold: int
    is_low_stock: bool
    version: int
    created_at: datetime
    updated_at: datetime
```

**Step 3: Create `app/schemas/order.py`**

```python
import uuid
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from app.domain.enums import OrderStatus


class OrderCreate(BaseModel):
    item_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    customer_ref: str | None = Field(default=None, max_length=255)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    quantity: int
    status: OrderStatus
    customer_ref: str | None
    version: int
    created_at: datetime
    updated_at: datetime
```

**Step 4: Create `app/schemas/stock.py`**

```python
import uuid
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from app.domain.enums import MovementType


class StockLevelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: uuid.UUID
    stock_quantity: int
    low_stock_threshold: int
    is_low_stock: bool


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    order_id: uuid.UUID | None
    movement_type: MovementType
    quantity_delta: int
    stock_before: int
    stock_after: int
    reason: str | None
    created_at: datetime


class LowStockAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    stock_quantity: int
    low_stock_threshold: int
```

**Step 5: Write schema validation unit tests**

Create `tests/unit/test_schemas.py`:

```python
import pytest
from decimal import Decimal
from pydantic import ValidationError
from app.schemas.item import ItemCreate
from app.schemas.order import OrderCreate
import uuid


def test_item_create_valid():
    item = ItemCreate(name="Burger", price=Decimal("9.99"), stock_quantity=50)
    assert item.name == "Burger"
    assert item.low_stock_threshold == 10  # default


def test_item_create_negative_price_fails():
    with pytest.raises(ValidationError):
        ItemCreate(name="X", price=Decimal("-1.00"), stock_quantity=10)


def test_item_create_negative_stock_fails():
    with pytest.raises(ValidationError):
        ItemCreate(name="X", price=Decimal("5.00"), stock_quantity=-1)


def test_order_create_valid():
    order = OrderCreate(item_id=uuid.uuid4(), quantity=3)
    assert order.quantity == 3


def test_order_create_zero_quantity_fails():
    with pytest.raises(ValidationError):
        OrderCreate(item_id=uuid.uuid4(), quantity=0)
```

**Step 6: Run tests**

```bash
uv run pytest tests/unit/test_schemas.py -v
```

Expected: 5 PASSED

**Step 7: Commit**

```bash
git add app/schemas/ tests/unit/test_schemas.py
git commit -m "feat: add pydantic schemas for items, orders, and stock"
```

---

## Task 10: API Routers

**Files:**
- Create: `app/api/v1/items.py`
- Create: `app/api/v1/orders.py`
- Create: `app/api/v1/stock.py`
- Create: `app/api/v1/router.py`

**Step 1: Create `app/api/v1/items.py`**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import InsufficientStockError, NotFoundError
from app.db.session import get_db
from app.schemas.item import ItemCreate, ItemResponse, StockAdjustRequest
from app.services.item_service import ItemService

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(body: ItemCreate, db: AsyncSession = Depends(get_db)):
    svc = ItemService(db)
    return await svc.create_item(
        name=body.name,
        price=body.price,
        stock_quantity=body.stock_quantity,
        description=body.description,
        low_stock_threshold=body.low_stock_threshold,
    )


@router.get("", response_model=list[ItemResponse])
async def list_items(db: AsyncSession = Depends(get_db)):
    return await ItemService(db).list_items()


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await ItemService(db).get_item(item_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/{item_id}/stock", response_model=ItemResponse)
async def adjust_stock(
    item_id: uuid.UUID, body: StockAdjustRequest, db: AsyncSession = Depends(get_db)
):
    try:
        return await ItemService(db).adjust_stock(item_id, body.delta, body.reason)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InsufficientStockError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
```

**Step 2: Create `app/api/v1/orders.py`**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import (
    ConflictError, InsufficientStockError, InvalidTransitionError, NotFoundError,
)
from app.db.session import get_db
from app.schemas.order import OrderCreate, OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(body: OrderCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await OrderService(db).place_order(body.item_id, body.quantity, body.customer_ref)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await OrderService(db).get_order(order_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


def _transition_router(action: str):
    """Factory to reduce boilerplate for simple state transitions."""
    @router.post(f"/{{order_id}}/{action}", response_model=OrderResponse)
    async def transition(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
        svc = OrderService(db)
        method = getattr(svc, f"{action}_order")
        try:
            return await method(order_id)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except InvalidTransitionError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except InsufficientStockError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
    return transition


confirm_order = _transition_router("confirm")
ship_order = _transition_router("ship")
deliver_order = _transition_router("deliver")
cancel_order = _transition_router("cancel")
```

**Step 3: Create `app/api/v1/stock.py`**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.schemas.stock import LowStockAlertResponse, StockLevelResponse, StockMovementResponse
from app.services.stock_service import StockService

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/alerts/low", response_model=list[LowStockAlertResponse])
async def low_stock_alerts(db: AsyncSession = Depends(get_db)):
    return await StockService(db).get_low_stock_items()


@router.get("/{item_id}", response_model=StockLevelResponse)
async def get_stock(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        item = await StockService(db).get_stock(item_id)
        return StockLevelResponse(
            item_id=item.id,
            stock_quantity=item.stock_quantity,
            low_stock_threshold=item.low_stock_threshold,
            is_low_stock=item.is_low_stock,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{item_id}/movements", response_model=list[StockMovementResponse])
async def get_movements(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await StockService(db).get_movements(item_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
```

**Step 4: Create `app/api/v1/router.py`**

```python
from fastapi import APIRouter
from app.api.v1 import items, orders, stock

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(items.router)
api_router.include_router(orders.router)
api_router.include_router(stock.router)
```

**Step 5: Commit**

```bash
git add app/api/
git commit -m "feat: add API routers for items, orders, and stock"
```

---

## Task 10b: Auth Middleware & Rate Limiter

**Files:**
- Create: `app/middleware/auth.py`
- Create: `app/middleware/__init__.py`
- Modify: `app/main.py` — register middleware + rate limiter
- Modify: `app/api/v1/stock.py` — apply rate limit decorator to `get_stock`

**Auth design decision:** Simple API-key middleware (`X-API-Key` header). Enabled only when `settings.require_auth = True`. When disabled (default in dev), all requests pass through. Write routes (POST, PATCH, DELETE) are protected when auth is on. Read routes (GET) remain accessible. This is the minimal viable auth for a service like this without introducing OAuth/JWT complexity that isn't in the spec.

**Rate limiter design:** `slowapi` applies per-IP rate limits. The stock endpoint (`GET /stock/{item_id}`) is the most read-heavy — explicitly rate-limited. This also protects against scraping/DoS even when auth is disabled. Backed by Redis (same client as cache) in production; in-memory fallback for testing.

### Step 1: Write failing tests

Create `tests/unit/test_auth_middleware.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.middleware.auth import ApiKeyMiddleware
from app.core.constants import Headers


def _make_app(require_auth: bool, valid_keys: set[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware, require_auth=require_auth, valid_keys=valid_keys)

    @app.get("/test")
    def endpoint():
        return {"ok": True}

    return app


def test_auth_disabled_allows_all_requests():
    client = TestClient(_make_app(require_auth=False, valid_keys={"secret"}))
    resp = client.get("/test")
    assert resp.status_code == 200


def test_auth_enabled_rejects_missing_key():
    client = TestClient(_make_app(require_auth=True, valid_keys={"secret"}))
    resp = client.get("/test")
    assert resp.status_code == 401


def test_auth_enabled_rejects_wrong_key():
    client = TestClient(_make_app(require_auth=True, valid_keys={"secret"}))
    resp = client.get("/test", headers={Headers.API_KEY: "wrong"})
    assert resp.status_code == 403


def test_auth_enabled_accepts_valid_key():
    client = TestClient(_make_app(require_auth=True, valid_keys={"secret"}))
    resp = client.get("/test", headers={Headers.API_KEY: "secret"})
    assert resp.status_code == 200


def test_get_requests_pass_when_auth_disabled():
    """GET routes stay open regardless of auth setting (reads are public)."""
    client = TestClient(_make_app(require_auth=False, valid_keys=set()))
    resp = client.get("/test")
    assert resp.status_code == 200
```

### Step 2: Run to verify they fail

```bash
uv run pytest tests/unit/test_auth_middleware.py -v
```

Expected: `ModuleNotFoundError`

### Step 3: Implement `app/middleware/auth.py`

```python
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
```

### Step 4: Create `app/middleware/__init__.py`

```python
from app.middleware.auth import ApiKeyMiddleware

__all__ = ["ApiKeyMiddleware"]
```

### Step 5: Update `app/main.py` — register middleware and rate limiter

Add after the existing `CORSMiddleware`:

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from app.core.cache import get_redis
from app.core.config import settings
from app.middleware import ApiKeyMiddleware

# Rate limiter — backed by Redis (same pool as cache)
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth middleware — enabled via REQUIRE_AUTH=true env var
app.add_middleware(
    ApiKeyMiddleware,
    require_auth=settings.require_auth,
    valid_keys=settings.valid_api_keys,
)
```

### Step 6: Apply rate limit to the stock read endpoint in `app/api/v1/stock.py`

```python
from app.main import limiter   # import the singleton
from app.core.config import settings

@router.get("/{item_id}", response_model=StockLevelResponse)
@limiter.limit(settings.rate_limit_stock_read)
async def get_stock(request: Request, item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Note: Request must be the first parameter for slowapi to work
    try:
        item = await StockService(db).get_stock(item_id)
        ...
```

### Step 7: Run auth tests

```bash
uv run pytest tests/unit/test_auth_middleware.py -v
```

Expected: 5 PASSED

### Step 8: Commit

```bash
git add app/middleware/ tests/unit/test_auth_middleware.py
git commit -m "feat: add optional API-key auth middleware and slowapi rate limiter"
```

---

## Task 11: FastAPI App Factory + Middleware

**Files:**
- Create: `app/main.py`

**Step 1: Create `app/main.py`**

Startup sequence:
1. Configure structured logging
2. **Validate migrations** — refuse to start if the DB is behind schema
3. Serve requests
4. Shutdown — gracefully dispose the DB engine singleton

```python
import time
import uuid
from contextlib import asynccontextmanager
import structlog
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import close_engine, get_engine

configure_logging()
logger = structlog.get_logger(__name__)


async def _validate_migrations() -> None:
    """
    Abort startup if any migration has not been applied.
    This prevents running stale code against a schema it doesn't understand.
    """
    engine = get_engine()
    alembic_cfg = AlembicConfig("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    expected_heads = set(script.get_heads())

    async with engine.connect() as conn:
        def _get_current(sync_conn):
            ctx = MigrationContext.configure(sync_conn)
            return set(ctx.get_current_heads())

        current_heads = await conn.run_sync(_get_current)

    if current_heads != expected_heads:
        missing = expected_heads - current_heads
        raise RuntimeError(
            f"Database is not up to date. Missing revisions: {missing}. "
            f"Run: uv run alembic upgrade head"
        )
    logger.info("migrations_ok", heads=sorted(current_heads))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", environment=settings.environment, db_host=settings.db_host)
    await _validate_migrations()
    yield
    logger.info("shutdown")
    await close_engine()


app = FastAPI(
    title="Nova Inventory Service",
    description="Inventory & Stock Consistency Service — atomic stock management, order lifecycle, analytics",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": "0.1.0"}
```

**Step 2: Commit**

```bash
git add app/main.py
git commit -m "feat: add FastAPI app factory with logging middleware"
```

---

## Task 12: Docker Setup

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `docker-entrypoint.sh`

**Design goals:** Multi-stage build so the runtime image contains only the venv + app code — no uv, no build tools, no pip. `docker-compose.yml` passes **zero** application env vars; all settings use their defaults from `Settings`. Only `DB_HOST=db` must be injected at runtime (Docker network hostname). Users override anything via a `.env` file.

### Step 1: Create `Dockerfile` — multi-stage, slim runtime

```dockerfile
# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Copy uv binary — the only build tool we need
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install deps into an isolated venv (no-dev = production only)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy only the venv — no uv, no pip, no build tools in production
COPY --from=builder /build/.venv /app/.venv

# Copy application and migration code
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY docker-entrypoint.sh ./

RUN chmod +x docker-entrypoint.sh

# Activate venv for all subsequent commands
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
```

### Step 2: Create `docker-entrypoint.sh`

```bash
#!/bin/sh
set -e

echo "[nova] Running migrations..."
python -m alembic upgrade head

echo "[nova] Starting server..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Note: uses `python -m alembic` / `python -m uvicorn` — no uv needed in runtime image.

### Step 3: Create `docker-compose.yml`

No application env vars are hardcoded. Settings have safe defaults (`localhost`, `postgres`, etc.). The compose file only:
1. Provides the Postgres service with its own `POSTGRES_*` vars (required by the postgres image, not our app)
2. Sets `DB_HOST=db` so the API container resolves the Docker network hostname
3. Optionally loads a user `.env` file for overrides (e.g. production passwords)

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: nova_inventory
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - path: .env
        required: false          # Optional — uses Settings defaults if absent
    environment:
      DB_HOST: db                # Only override needed: Docker network hostname
      REDIS_URL: redis://redis:6379
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

volumes:
  postgres_data:
```

### Step 4: Commit

```bash
git add Dockerfile docker-compose.yml docker-entrypoint.sh
git commit -m "feat: slim multi-stage Dockerfile, env_file compose, no hardcoded creds"
```

---

## Task 13: Integration Test Infrastructure

**Files:**
- Create: `tests/conftest.py`

**Step 1: Create `tests/conftest.py`**

```python
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.db.base import Base
from app.db.session import get_db
from app.domain.models import MenuItem, Order, StockMovement  # noqa: F401
from app.main import app


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(postgres_container):
    url = postgres_container.get_connection_url()
    # testcontainers returns psycopg2 URL; convert to asyncpg
    return url.replace("psycopg2", "asyncpg").replace("postgresql://", "postgresql+asyncpg://")


@pytest_asyncio.fixture(scope="session")
async def db_engine(db_url):
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Each test gets a rolled-back transaction for isolation."""
    async with db_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            yield session
            await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """FastAPI test client using the test DB session."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
```

**Step 2: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add integration test infrastructure with testcontainers"
```

---

## Task 14: Integration Tests — Order Lifecycle

**Files:**
- Create: `tests/integration/test_order_lifecycle.py`

**Step 1: Write tests**

```python
import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def create_item(client: AsyncClient, stock: int = 20) -> dict:
    resp = await client.post("/api/v1/items", json={
        "name": f"Test Item {id(client)}",
        "price": "9.99",
        "stock_quantity": stock,
        "low_stock_threshold": 5,
    })
    assert resp.status_code == 201
    return resp.json()


async def place_order(client: AsyncClient, item_id: str, qty: int = 2) -> dict:
    resp = await client.post("/api/v1/orders", json={
        "item_id": item_id,
        "quantity": qty,
        "customer_ref": "test-customer",
    })
    assert resp.status_code == 201
    return resp.json()


async def test_full_happy_path(client: AsyncClient):
    """PENDING → CONFIRMED → SHIPPED → DELIVERED"""
    item = await create_item(client, stock=10)
    order = await place_order(client, item["id"], qty=3)
    assert order["status"] == "PENDING"

    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 200
    assert r.json()["status"] == "CONFIRMED"

    # Stock was deducted
    stock = await client.get(f"/api/v1/stock/{item['id']}")
    assert stock.json()["stock_quantity"] == 7  # 10 - 3

    r = await client.post(f"/api/v1/orders/{order['id']}/ship")
    assert r.status_code == 200
    assert r.json()["status"] == "SHIPPED"

    r = await client.post(f"/api/v1/orders/{order['id']}/deliver")
    assert r.status_code == 200
    assert r.json()["status"] == "DELIVERED"


async def test_cancel_confirmed_order_restores_stock(client: AsyncClient):
    item = await create_item(client, stock=10)
    order = await place_order(client, item["id"], qty=4)

    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    stock_after_confirm = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock_after_confirm["stock_quantity"] == 6

    r = await client.post(f"/api/v1/orders/{order['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"

    stock_after_cancel = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock_after_cancel["stock_quantity"] == 10  # restored


async def test_cancel_pending_order_does_not_restore_stock(client: AsyncClient):
    item = await create_item(client, stock=10)
    order = await place_order(client, item["id"], qty=4)

    # Cancel before confirming
    r = await client.post(f"/api/v1/orders/{order['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"

    # Stock unchanged — nothing was deducted
    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 10


async def test_reject_order_when_insufficient_stock(client: AsyncClient):
    item = await create_item(client, stock=2)
    order = await place_order(client, item["id"], qty=5)

    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 422  # InsufficientStockError

    # Stock must be unchanged
    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 2


async def test_delivered_order_cannot_cancel(client: AsyncClient):
    item = await create_item(client, stock=10)
    order = await place_order(client, item["id"], qty=1)

    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    await client.post(f"/api/v1/orders/{order['id']}/ship")
    await client.post(f"/api/v1/orders/{order['id']}/deliver")

    r = await client.post(f"/api/v1/orders/{order['id']}/cancel")
    assert r.status_code == 422


async def test_stock_movement_audit_trail(client: AsyncClient):
    item = await create_item(client, stock=10)
    order = await place_order(client, item["id"], qty=3)
    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    await client.post(f"/api/v1/orders/{order['id']}/cancel")

    movements = (await client.get(f"/api/v1/stock/{item['id']}/movements")).json()
    types = [m["movement_type"] for m in movements]
    assert "DEDUCTION" in types
    assert "RESTORATION" in types
```

**Step 2: Run integration tests**

```bash
uv run pytest tests/integration/test_order_lifecycle.py -v
```

Expected: 6 PASSED

**Step 3: Commit**

```bash
git add tests/integration/test_order_lifecycle.py
git commit -m "test: add order lifecycle integration tests"
```

---

## Task 15: Integration Tests — Concurrent Orders (Race Condition)

**Files:**
- Create: `tests/integration/test_concurrent_orders.py`

**Step 1: Write the critical concurrency test**

```python
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_db
from app.main import app


pytestmark = pytest.mark.asyncio


async def test_concurrent_orders_no_oversell(db_engine):
    """
    10 concurrent confirm requests against stock of 5.
    Exactly 5 must succeed; 5 must be rejected.
    Stock must never go negative.
    """
    STOCK = 5
    NUM_ORDERS = 10

    # Each concurrent request needs its own session (simulates separate connections)
    async def make_session():
        session_factory = async_sessionmaker(
            bind=db_engine, class_=AsyncSession, expire_on_commit=False
        )
        return session_factory()

    # Create item with a fresh direct session
    async with (await make_session()) as session:
        from app.services.item_service import ItemService
        item_svc = ItemService(session)
        item = await item_svc.create_item("Race Item", price=5.0, stock_quantity=STOCK)
        await session.commit()
        item_id = item.id

    # Place 10 orders (sequential — just creating state, not the race)
    order_ids = []
    async with (await make_session()) as session:
        from app.services.order_service import OrderService
        order_svc = OrderService(session)
        for _ in range(NUM_ORDERS):
            order = await order_svc.place_order(item_id, quantity=1)
            order_ids.append(order.id)
        await session.commit()

    # Confirm all 10 orders concurrently — THIS is the race condition test
    async def try_confirm(order_id):
        async with (await make_session()) as session:
            svc = OrderService(session)
            try:
                result = await svc.confirm_order(order_id)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                raise e

    results = await asyncio.gather(
        *[try_confirm(oid) for oid in order_ids],
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == STOCK, f"Expected {STOCK} successes, got {len(successes)}"
    assert len(failures) == NUM_ORDERS - STOCK, f"Expected {NUM_ORDERS - STOCK} failures"

    # Verify final stock is exactly 0
    async with (await make_session()) as session:
        from app.repositories.item_repo import ItemRepository
        repo = ItemRepository(session)
        final_item = await repo.get_by_id(item_id)
        assert final_item.stock_quantity == 0, (
            f"Stock should be 0, got {final_item.stock_quantity}"
        )
        assert final_item.stock_quantity >= 0, "Stock went negative — oversell detected!"


async def test_concurrent_cancellations_no_double_restore(db_engine):
    """
    Two concurrent cancel requests for the same confirmed order.
    Only one must succeed; stock must be restored exactly once.
    """
    async def make_session():
        session_factory = async_sessionmaker(
            bind=db_engine, class_=AsyncSession, expire_on_commit=False
        )
        return session_factory()

    INITIAL_STOCK = 10
    ORDER_QTY = 3

    async with (await make_session()) as session:
        from app.services.item_service import ItemService
        from app.services.order_service import OrderService
        item = await ItemService(session).create_item("Cancel Race", price=5.0, stock_quantity=INITIAL_STOCK)
        order = await OrderService(session).place_order(item.id, ORDER_QTY)
        await session.commit()
        item_id, order_id = item.id, order.id

    async with (await make_session()) as session:
        from app.services.order_service import OrderService
        await OrderService(session).confirm_order(order_id)
        await session.commit()

    # Two concurrent cancel calls
    async def try_cancel(oid):
        async with (await make_session()) as session:
            from app.services.order_service import OrderService
            try:
                result = await OrderService(session).cancel_order(oid)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                raise e

    results = await asyncio.gather(
        try_cancel(order_id), try_cancel(order_id), return_exceptions=True
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) == 1, "Exactly one cancel should succeed"

    # Stock must be restored exactly once → back to INITIAL_STOCK
    async with (await make_session()) as session:
        from app.repositories.item_repo import ItemRepository
        item = await ItemRepository(session).get_by_id(item_id)
        assert item.stock_quantity == INITIAL_STOCK
```

**Step 2: Run concurrency tests**

```bash
uv run pytest tests/integration/test_concurrent_orders.py -v -s
```

Expected: 2 PASSED — if locking is correct, these pass deterministically.

**Step 3: Commit**

```bash
git add tests/integration/test_concurrent_orders.py
git commit -m "test: add concurrent order race condition tests"
```

---

## Task 16: Integration Tests — Stock Alerts

**Files:**
- Create: `tests/integration/test_stock_alerts.py`

**Step 1: Write tests**

```python
import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_low_stock_alert_returns_items_below_threshold(client: AsyncClient):
    # Create item below threshold
    low_resp = await client.post("/api/v1/items", json={
        "name": "Low Item Alert",
        "price": "5.00",
        "stock_quantity": 3,
        "low_stock_threshold": 10,
    })
    assert low_resp.status_code == 201

    # Create item above threshold
    ok_resp = await client.post("/api/v1/items", json={
        "name": "OK Item Alert",
        "price": "5.00",
        "stock_quantity": 50,
        "low_stock_threshold": 10,
    })
    assert ok_resp.status_code == 201

    alerts = (await client.get("/api/v1/stock/alerts/low")).json()
    alert_ids = [a["id"] for a in alerts]

    assert low_resp.json()["id"] in alert_ids
    assert ok_resp.json()["id"] not in alert_ids


async def test_item_at_threshold_is_included_in_alerts(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "At Threshold",
        "price": "5.00",
        "stock_quantity": 10,
        "low_stock_threshold": 10,
    })
    assert resp.status_code == 201

    alerts = (await client.get("/api/v1/stock/alerts/low")).json()
    alert_ids = [a["id"] for a in alerts]
    assert resp.json()["id"] in alert_ids


async def test_stock_level_endpoint(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "Stock Level Test",
        "price": "5.00",
        "stock_quantity": 25,
        "low_stock_threshold": 10,
    })
    item_id = resp.json()["id"]

    stock = (await client.get(f"/api/v1/stock/{item_id}")).json()
    assert stock["stock_quantity"] == 25
    assert stock["is_low_stock"] is False
```

**Step 2: Run all tests**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: All tests PASSED

**Step 3: Commit**

```bash
git add tests/integration/test_stock_alerts.py
git commit -m "test: add stock alert and stock level integration tests"
```

---

## Task 17: Analytics — Schemas, Service & Router

**Files:**
- Create: `app/schemas/analytics.py`
- Create: `app/services/analytics_service.py`
- Create: `app/api/v1/analytics.py`
- Modify: `app/api/v1/router.py`

Business questions answered by the analytics endpoints:
- **Stock pile**: total items, total units in stock, total inventory value, out-of-stock and low-stock counts
- **Sales**: orders by status, revenue from delivered orders, average order size
- **Refunds**: count and value of restorations from cancellations
- **Cancellations / rejections**: counts and reasons breakdown over a time window

### Step 1: Write failing integration tests first (TDD)

Create `tests/integration/test_analytics.py`:

```python
import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def _seed(client: AsyncClient):
    """Create item, place + confirm + cancel some orders for analytics data."""
    item_r = await client.post("/api/v1/items", json={
        "name": "Analytics Item",
        "price": "10.00",
        "stock_quantity": 100,
        "low_stock_threshold": 20,
    })
    assert item_r.status_code == 201
    item_id = item_r.json()["id"]

    # Place 3 orders: confirm 2, cancel 1 (confirmed), reject 1 (no stock scenario skipped)
    orders = []
    for qty in [5, 3, 2]:
        r = await client.post("/api/v1/orders", json={"item_id": item_id, "quantity": qty})
        assert r.status_code == 201
        orders.append(r.json())

    await client.post(f"/api/v1/orders/{orders[0]['id']}/confirm")
    await client.post(f"/api/v1/orders/{orders[1]['id']}/confirm")
    await client.post(f"/api/v1/orders/{orders[2]['id']}/confirm")
    await client.post(f"/api/v1/orders/{orders[0]['id']}/cancel")  # restores 5

    return item_id, orders


async def test_business_summary_returns_expected_shape(client: AsyncClient):
    await _seed(client)
    r = await client.get("/api/v1/analytics/summary")
    assert r.status_code == 200
    data = r.json()
    assert "stock" in data
    assert "orders" in data
    assert "movements" in data
    assert "as_of" in data


async def test_stock_analytics(client: AsyncClient):
    await _seed(client)
    r = await client.get("/api/v1/analytics/stock")
    assert r.status_code == 200
    data = r.json()
    assert data["total_items"] >= 1
    assert data["total_stock_units"] >= 0
    assert "total_stock_value" in data
    assert "low_stock_count" in data
    assert "out_of_stock_count" in data


async def test_order_analytics_default_period(client: AsyncClient):
    await _seed(client)
    r = await client.get("/api/v1/analytics/orders")
    assert r.status_code == 200
    data = r.json()
    assert "period_days" in data
    assert "total_orders" in data
    assert "confirmed" in data
    assert "cancelled" in data
    assert "total_revenue" in data
    assert "cancelled_value" in data


async def test_movement_analytics(client: AsyncClient):
    await _seed(client)
    r = await client.get("/api/v1/analytics/movements")
    assert r.status_code == 200
    data = r.json()
    assert data["total_deductions"] >= 0
    assert data["total_restorations"] >= 0
    assert "net_stock_change" in data
```

### Step 2: Run to verify they fail

```bash
uv run pytest tests/integration/test_analytics.py -v
```

Expected: 404 errors (routes don't exist yet)

### Step 3: Implement `app/schemas/analytics.py`

```python
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class StockAnalytics(BaseModel):
    total_items: int
    total_stock_units: int
    total_stock_value: Decimal
    low_stock_count: int
    out_of_stock_count: int


class OrderAnalytics(BaseModel):
    period_days: int
    total_orders: int
    pending: int
    confirmed: int
    shipped: int
    delivered: int
    cancelled: int
    rejected: int
    total_revenue: Decimal        # price × qty for DELIVERED orders
    cancelled_value: Decimal      # price × qty for CANCELLED orders (refunds)
    avg_order_quantity: float


class MovementAnalytics(BaseModel):
    period_days: int
    total_deductions: int         # count of DEDUCTION movements
    total_restorations: int       # count of RESTORATION movements (refunds)
    total_adjustments: int        # count of manual ADJUSTMENT movements
    units_deducted: int           # sum of abs(delta) for deductions
    units_restored: int           # sum of delta for restorations
    net_stock_change: int         # sum of all deltas in period


class BusinessSummary(BaseModel):
    stock: StockAnalytics
    orders: OrderAnalytics
    movements: MovementAnalytics
    as_of: datetime
```

### Step 4: Implement `app/services/analytics_service.py`

Uses `func.sum`, `func.count`, `func.coalesce` for efficient single-query aggregations. No N+1 queries.

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.enums import MovementType, OrderStatus
from app.domain.models.item import MenuItem
from app.domain.models.order import Order
from app.domain.models.stock_movement import StockMovement
from app.schemas.analytics import (
    BusinessSummary, MovementAnalytics, OrderAnalytics, StockAnalytics,
)


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_stock_analytics(self) -> StockAnalytics:
        result = await self._session.execute(
            select(
                func.count(MenuItem.id).label("total_items"),
                func.coalesce(func.sum(MenuItem.stock_quantity), 0).label("total_stock_units"),
                func.coalesce(
                    func.sum(MenuItem.stock_quantity * MenuItem.price), 0
                ).label("total_stock_value"),
                func.count(
                    MenuItem.id
                ).filter(
                    MenuItem.stock_quantity <= MenuItem.low_stock_threshold
                ).label("low_stock_count"),
                func.count(MenuItem.id).filter(
                    MenuItem.stock_quantity == 0
                ).label("out_of_stock_count"),
            )
        )
        row = result.one()
        return StockAnalytics(
            total_items=row.total_items,
            total_stock_units=row.total_stock_units,
            total_stock_value=Decimal(str(row.total_stock_value)),
            low_stock_count=row.low_stock_count,
            out_of_stock_count=row.out_of_stock_count,
        )

    async def get_order_analytics(self, days: int = 30) -> OrderAnalytics:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Status counts
        status_result = await self._session.execute(
            select(Order.status, func.count(Order.id).label("cnt"))
            .where(Order.created_at >= since)
            .group_by(Order.status)
        )
        by_status: dict[str, int] = {row.status: row.cnt for row in status_result}
        total = sum(by_status.values())

        # Revenue from DELIVERED orders
        revenue_result = await self._session.execute(
            select(
                func.coalesce(
                    func.sum(Order.quantity * MenuItem.price), 0
                ).label("revenue"),
                func.coalesce(func.avg(Order.quantity), 0).label("avg_qty"),
            )
            .join(MenuItem, Order.item_id == MenuItem.id)
            .where(Order.status == OrderStatus.DELIVERED, Order.created_at >= since)
        )
        rev_row = revenue_result.one()

        # Value of cancelled orders (refunds)
        cancel_result = await self._session.execute(
            select(
                func.coalesce(
                    func.sum(Order.quantity * MenuItem.price), 0
                ).label("cancelled_value")
            )
            .join(MenuItem, Order.item_id == MenuItem.id)
            .where(Order.status == OrderStatus.CANCELLED, Order.created_at >= since)
        )
        cancel_row = cancel_result.one()

        return OrderAnalytics(
            period_days=days,
            total_orders=total,
            pending=by_status.get(OrderStatus.PENDING, 0),
            confirmed=by_status.get(OrderStatus.CONFIRMED, 0),
            shipped=by_status.get(OrderStatus.SHIPPED, 0),
            delivered=by_status.get(OrderStatus.DELIVERED, 0),
            cancelled=by_status.get(OrderStatus.CANCELLED, 0),
            rejected=by_status.get(OrderStatus.REJECTED, 0),
            total_revenue=Decimal(str(rev_row.revenue)),
            cancelled_value=Decimal(str(cancel_row.cancelled_value)),
            avg_order_quantity=float(rev_row.avg_qty),
        )

    async def get_movement_analytics(self, days: int = 30) -> MovementAnalytics:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self._session.execute(
            select(
                StockMovement.movement_type,
                func.count(StockMovement.id).label("cnt"),
                func.coalesce(func.sum(StockMovement.quantity_delta), 0).label("total_delta"),
            )
            .where(StockMovement.created_at >= since)
            .group_by(StockMovement.movement_type)
        )
        by_type: dict[str, tuple[int, int]] = {
            row.movement_type: (row.cnt, row.total_delta) for row in result
        }

        ded_cnt, ded_delta = by_type.get(MovementType.DEDUCTION, (0, 0))
        res_cnt, res_delta = by_type.get(MovementType.RESTORATION, (0, 0))
        adj_cnt, adj_delta = by_type.get(MovementType.ADJUSTMENT, (0, 0))

        return MovementAnalytics(
            period_days=days,
            total_deductions=ded_cnt,
            total_restorations=res_cnt,
            total_adjustments=adj_cnt,
            units_deducted=abs(ded_delta),
            units_restored=res_delta,
            net_stock_change=ded_delta + res_delta + adj_delta,
        )

    async def get_business_summary(self, days: int = 30) -> BusinessSummary:
        return BusinessSummary(
            stock=await self.get_stock_analytics(),
            orders=await self.get_order_analytics(days),
            movements=await self.get_movement_analytics(days),
            as_of=datetime.now(timezone.utc),
        )
```

### Step 5: Implement `app/api/v1/analytics.py`

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.analytics import BusinessSummary, MovementAnalytics, OrderAnalytics, StockAnalytics
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=BusinessSummary)
async def business_summary(
    days: int = Query(default=30, ge=1, le=365, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
):
    """Overall business dashboard: stock pile, sales, refunds, cancellations."""
    return await AnalyticsService(db).get_business_summary(days)


@router.get("/stock", response_model=StockAnalytics)
async def stock_analytics(db: AsyncSession = Depends(get_db)):
    """Inventory snapshot: total units, value, low-stock and out-of-stock counts."""
    return await AnalyticsService(db).get_stock_analytics()


@router.get("/orders", response_model=OrderAnalytics)
async def order_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Order breakdown by status, revenue from delivered orders, refund value from cancellations."""
    return await AnalyticsService(db).get_order_analytics(days)


@router.get("/movements", response_model=MovementAnalytics)
async def movement_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Stock movement analytics: deductions (sales), restorations (refunds), adjustments."""
    return await AnalyticsService(db).get_movement_analytics(days)
```

### Step 6: Update `app/api/v1/router.py` to include analytics

```python
from fastapi import APIRouter
from app.api.v1 import analytics, items, orders, stock

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(items.router)
api_router.include_router(orders.router)
api_router.include_router(stock.router)
api_router.include_router(analytics.router)
```

### Step 7: Run analytics tests

```bash
uv run pytest tests/integration/test_analytics.py -v
```

Expected: 4 PASSED

### Step 8: Commit

```bash
git add app/schemas/analytics.py app/services/analytics_service.py \
        app/api/v1/analytics.py app/api/v1/router.py \
        tests/integration/test_analytics.py
git commit -m "feat: add analytics API (stock pile, orders, refunds, movements)"
```

---

## Task 18: README

**Files:**
- Create: `README.md`

**Step 1: Create `README.md`**

```markdown
# Nova Inventory Service

A production-ready backend service for inventory management and stock consistency under concurrent order placement.

## Quick Start

### With Docker (recommended)

```bash
docker compose up --build
```

API available at http://localhost:8000
Docs at http://localhost:8000/docs

### Local Development

**Prerequisites:** Python 3.13+, PostgreSQL 16+, [uv](https://docs.astral.sh/uv/)

```bash
# Install dependencies
uv sync --all-groups

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL

# Run migrations
uv run alembic upgrade head

# Start server
uv run uvicorn app.main:app --reload
```

## Running Tests

```bash
# All tests (requires Docker for testcontainers)
uv run pytest tests/ -v

# Unit tests only (no DB required)
uv run pytest tests/unit/ -v

# With coverage
uv run pytest tests/ --cov=app --cov-report=html
```

## Architecture

```
HTTP Request → API Router → Service Layer → Repository → PostgreSQL
                           (business logic)  (queries)
```

**Layered monolith** — clean separation of concerns without over-engineering.

### Locking Strategy

| Scenario | Strategy |
|---|---|
| Stock deduction (`confirm_order`) | Pessimistic: `SELECT FOR UPDATE` on `menu_items` row |
| Order state transitions | Optimistic: `version` field + conditional UPDATE |

**Why this combination?** Stock writes are the critical path where oversell is catastrophic — row-level locking gives absolute safety. State transitions are lower-stakes and high-frequency; optimistic locking avoids contention while still preventing double-transitions.

### Order State Machine

```
PENDING → CONFIRMED → SHIPPED → DELIVERED
                               ↘
PENDING/CONFIRMED/SHIPPED ──────→ CANCELLED (restores stock)
PENDING → REJECTED (insufficient stock)
```

Stock is **deducted** only on `PENDING → CONFIRMED`.
Stock is **restored** only on cancellation from `CONFIRMED`, `SHIPPED`, or `DELIVERED`.

### Audit Trail

Every stock movement is recorded in `stock_movements` (append-only). Never updated or deleted. Each record captures `stock_before` and `stock_after` snapshots.

## API Documentation

Interactive OpenAPI docs: http://localhost:8000/docs

### Key Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/items` | Create menu item with stock |
| POST | `/api/v1/orders` | Place order (PENDING) |
| POST | `/api/v1/orders/{id}/confirm` | Confirm → atomically deduct stock |
| POST | `/api/v1/orders/{id}/cancel` | Cancel + restore stock |
| GET | `/api/v1/stock/alerts/low` | Low stock alert |
| GET | `/api/v1/stock/{item_id}/movements` | Full audit trail |

## Design Decisions

| Decision | Rationale |
|---|---|
| FastAPI | Async-native, auto OpenAPI generation, minimal boilerplate |
| asyncpg | True async Postgres driver — no thread pool overhead |
| SQLAlchemy 2.x async | ORM + raw SQL flexibility, works perfectly with asyncpg |
| Alembic | Industry-standard schema migrations with version control |
| uv | 10-100x faster than pip, deterministic lockfile |
| testcontainers | Integration tests run against real Postgres — no mock gaps |
| structlog | JSON-structured logs in production; human-friendly in dev |
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, architecture, and design decisions"
```

---

## Task 18: Final Verification

**Step 1: Run all tests**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: All tests PASSED, 0 failures

**Step 2: Check code with type hints (optional)**

```bash
uv run python -c "from app.main import app; print('Import OK')"
```

**Step 3: Start the server locally and verify OpenAPI**

```bash
# Start a local postgres first, then:
uv run uvicorn app.main:app --reload
# Visit http://localhost:8000/docs
```

**Step 4: Build Docker image**

```bash
docker compose build
```

Expected: Build succeeds with no errors

**Step 5: Spin up the full stack**

```bash
docker compose up
```

Expected: migrations run, API starts on port 8000

**Step 6: Final commit tag**

```bash
git tag v0.1.0
```

---

## Summary

| Task | Component | Parallel Wave |
|---|---|---|
| 1 | Project scaffold + uv + pyproject.toml (`redis`, `slowapi` included) | Wave 1 |
| 2 | Core config (individual DB env vars + defaults, Redis, auth, rate-limit settings) | Wave 1 |
| **2b** | **`app/core/constants.py`** — CacheKeys, Headers, RateLimits, LogFields | Wave 1 |
| 3 | DB base + **singleton** engine + session + enums | Wave 1 |
| 4 | Domain ORM models (MenuItem, Order, StockMovement) | Wave 1 |
| 5 | Alembic async migrations (asyncpg, URL from settings — no psycopg2) | Wave 1 |
| 6 | Repositories (pessimistic + optimistic locking) | Wave 2 |
| 7 | Custom exceptions | Wave 2 (parallel with 6) |
| 8 | Services (order: SELECT FOR UPDATE + state machine) | Wave 2 |
| **8b** | **Write-through Redis cache** — `app/core/cache.py` + service updates | Wave 2 (after 8) |
| 9 | Pydantic schemas | Wave 2 (parallel with 8b) |
| 10 | API routers (items, orders, stock, analytics) | Wave 3 |
| **10b** | **Auth middleware** (optional API key) + **slowapi rate limiter** on stock read | Wave 3 (after 10) |
| 11 | FastAPI app factory + **migration validation** on startup + close engine/redis | Wave 3 |
| 12 | **Slim multi-stage Dockerfile**, `docker-compose.yml` (`env_file`, only `DB_HOST` override) | Wave 3 (parallel with 11) |
| 13 | Integration test infrastructure (testcontainers postgres + redis) | Wave 4 |
| 14 | Integration tests: order lifecycle | Wave 4 |
| 15 | Integration tests: concurrent orders (race condition) | Wave 4 (parallel with 14) |
| 16 | Integration tests: stock alerts | Wave 4 (parallel with 14) |
| 17 | Analytics: schemas + service + router + tests | Wave 4 (parallel with 14) |
| 18 | README | Wave 5 |
| 19 | Final verification | Wave 5 |
