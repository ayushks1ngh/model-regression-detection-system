"""Async engine and session lifecycle management."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    """Create an async engine for the configured database URL."""
    return create_async_engine(database_url, future=True, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to an engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def database_ready(engine: AsyncEngine) -> bool:
    """Return whether the database answers a trivial query."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def dispose_engine(engine: AsyncEngine) -> None:
    """Dispose engine connections on shutdown."""
    await engine.dispose()
