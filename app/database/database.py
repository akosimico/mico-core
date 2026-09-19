from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import inspect, text

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
        self._bot_lease_connection: AsyncConnection | None = None

    async def init_models(self) -> None:
        """Create all tables defined on Base metadata."""
        logger.info("Initializing database tables for %s", self.database_url)
        async with self.engine.begin() as conn:
            # Compose starts the API and Discord worker together. ``create_all``
            # is a check-then-create operation, so PostgreSQL needs a small
            # cross-process lock to prevent both services creating a table at
            # the same time during a clean startup.
            if self.engine.dialect.name == "postgresql":
                await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('mico-schema-init'))"))
            await conn.run_sync(Base.metadata.create_all)
            # This project currently uses metadata creation rather than Alembic.
            # Preserve existing local databases when Milestone 5 adds task projects.
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            if "tasks" in tables:
                columns = await conn.run_sync(
                    lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("tasks")}
                )
                if "project_id" not in columns:
                    await conn.execute(text("ALTER TABLE tasks ADD COLUMN project_id INTEGER"))
                    logger.info("Added project_id column to existing tasks table")
        logger.info("Database tables initialized successfully")

    async def close(self) -> None:
        """Dispose the underlying engine pool."""
        logger.info("Closing database engine")
        await self.release_bot_lease()
        await self.engine.dispose()

    async def acquire_bot_lease(self) -> bool:
        """Ensure only one Discord gateway worker consumes events for this database.

        PostgreSQL advisory locks are held by a dedicated connection for the
        bot's lifetime. SQLite is used only for local/test mode and has no
        equivalent cross-process lock, so it remains single-process by design.
        """
        if self._bot_lease_connection is not None:
            return True
        if self.engine.dialect.name != "postgresql":
            return True
        connection = await self.engine.connect()
        acquired = bool((await connection.execute(
            text("SELECT pg_try_advisory_lock(hashtext('mico-discord-bot'))")
        )).scalar_one())
        if acquired:
            self._bot_lease_connection = connection
            return True
        await connection.close()
        return False

    async def release_bot_lease(self) -> None:
        if self._bot_lease_connection is None:
            return
        try:
            await self._bot_lease_connection.execute(text("SELECT pg_advisory_unlock(hashtext('mico-discord-bot'))"))
        finally:
            await self._bot_lease_connection.close()
            self._bot_lease_connection = None

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
