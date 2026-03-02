import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.core.cache import CacheService
from app.db.base import Base
from app.db.session import get_db
from app.domain.models import MenuItem, Order, StockMovement  # noqa: F401 — register with metadata
from app.main import app
from app.api.v1.deps import get_cache


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(postgres_container):
    url = postgres_container.get_connection_url()
    # testcontainers returns a psycopg2 URL; convert to asyncpg
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
    """Each test gets its own rolled-back transaction for isolation."""
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            yield session
        await trans.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """FastAPI test client using the isolated DB session and a no-op cache."""

    async def override_get_db():
        yield db_session

    def override_get_cache() -> CacheService:
        # Use disabled cache in integration tests — tests DB behaviour directly
        return CacheService(None)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_cache] = override_get_cache

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
