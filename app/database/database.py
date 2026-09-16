from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.database.models import Base

logger = logging.getLogger("mico.database")


class Database:
    """
    Manages SQLAlchemy async engine and session lifecycle.
    Supports PostgreSQL (asyncpg) in production and SQLite (aiosqlite) in development/testing.
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            echo=False,
            future=True,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def init_models(self) -> None:
        """Create all tables defined on Base metadata."""
        logger.info("Initializing database tables for %s", self.database_url)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully")

    async def close(self) -> None:
        """Dispose the underlying engine pool."""
        logger.info("Closing database engine")
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager yielding a transactional async session."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


_db_instance: Database | None = None


def get_database(settings: Settings | None = None) -> Database:
    """Return the application database singleton."""
    global _db_instance
    if _db_instance is None:
        cfg = settings or get_settings()
        _db_instance = Database(cfg.database_url)
    return _db_instance


def set_database(db: Database | None) -> None:
    """Set or reset the database singleton (useful in tests)."""
    global _db_instance
    _db_instance = db


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for injecting an async database session."""
    db = get_database()
    async with db.session() as session:
        yield session
