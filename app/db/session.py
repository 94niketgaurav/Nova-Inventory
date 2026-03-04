# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# ── Singleton engine — created once, reused for the process lifetime ──────────
_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# ── Singleton session factory — bound to the engine above ─────────────────────
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


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency — yields a session, commits on success, rolls back on error.

    HTTPException is treated as a controlled outcome (e.g. an order correctly
    transitioned to REJECTED before the 422 is raised) so we commit rather than
    roll back in that branch.  Unexpected exceptions trigger a rollback.
    """
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except HTTPException:
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """Gracefully dispose the engine on shutdown (called from lifespan)."""
    await _engine.dispose()
