# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import get_cache
from app.core.cache import CacheService
from app.db.base import Base
from app.db.session import get_db
from app.domain.models import MenuItem, Order, StockMovement  # noqa: F401 — register with metadata
from app.main import app


def _docker_available() -> bool:
    """Return True when a Docker daemon is reachable."""
    import socket
    sockets = [
        "/var/run/docker.sock",
        "/run/docker.sock",
        os.path.expanduser("~/.docker/run/docker.sock"),
    ]
    for path in sockets:
        if os.path.exists(path):
            return True
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        host, _, port = docker_host[len("tcp://"):].partition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=1):
                return True
        except OSError:
            pass
    return False


def _local_pg_url() -> str:
    return os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres@localhost/nova_test",
    )


# ---------------------------------------------------------------------------
# Session-scoped: spin up the container (or resolve the local URL) once.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _resolved_db_url():
    """Return the DB URL for the test session (container or local PG)."""
    if _docker_available():
        from testcontainers.postgres import PostgresContainer
        with PostgresContainer("postgres:16-alpine") as pg:
            raw = pg.get_connection_url()
            url = raw.replace("psycopg2", "asyncpg").replace(
                "postgresql://", "postgresql+asyncpg://"
            )
            import asyncio

            from sqlalchemy.ext.asyncio import create_async_engine as _make

            async def _create_tables(u):
                eng = _make(u, echo=False)
                async with eng.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                await eng.dispose()

            asyncio.run(_create_tables(url))
            yield url
    else:
        url = _local_pg_url()
        import asyncio

        from sqlalchemy.ext.asyncio import create_async_engine as _make

        async def _create_tables(u):
            eng = _make(u, echo=False)
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await eng.dispose()

        asyncio.run(_create_tables(url))
        yield url


# ---------------------------------------------------------------------------
# Function-scoped engine — each test gets its own engine tied to its own
# event loop.  This prevents "Future attached to a different loop" errors
# that arise when a session-scoped asyncpg engine is reused across
# function-scoped event loops (pytest-asyncio default).
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_engine(_resolved_db_url):
    """Per-test async engine.  Concurrent tests use this to create sessions."""
    engine = create_async_engine(_resolved_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped session — rolls back after each test for isolation.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session(_resolved_db_url) -> AsyncSession:
    """Each test gets its own connection + rolled-back transaction."""
    engine = create_async_engine(_resolved_db_url, echo=False)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            session_factory = async_sessionmaker(
                bind=conn, class_=AsyncSession, expire_on_commit=False
            )
            async with session_factory() as session:
                yield session
            await trans.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """FastAPI test client using the isolated DB session and a no-op cache."""

    async def override_get_db():
        yield db_session

    def override_get_cache() -> CacheService:
        return CacheService(None)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_cache] = override_get_cache

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
