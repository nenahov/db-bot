from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine is not initialized")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database session factory is not initialized")
    return _session_factory


async def init_db(sqlite_path: Path) -> None:
    global _engine, _session_factory

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{sqlite_path.resolve().as_posix()}"
    _engine = create_async_engine(url, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(_ensure_schema)


def _ensure_schema(sync_conn: Connection) -> None:
    Base.metadata.create_all(sync_conn)
    columns = {
        col["name"] for col in inspect(sync_conn).get_columns("db_connections")
    }
    if "read_only" not in columns:
        sync_conn.execute(
            text(
                "ALTER TABLE db_connections "
                "ADD COLUMN read_only BOOLEAN NOT NULL DEFAULT 1"
            )
        )
    version = int(sync_conn.execute(text("PRAGMA user_version")).scalar() or 0)
    if version < 1:
        sync_conn.execute(text("UPDATE db_connections SET read_only = 1"))
        sync_conn.exec_driver_sql("PRAGMA user_version = 1")


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
