"""
Database & Redis Session Management.
Provides connection pools, FastAPI dependencies, and lifecycle management
for PostgreSQL (PostGIS) and Redis.
"""

import os
import sys
from typing import AsyncGenerator, Generator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from redis.asyncio import ConnectionPool, Redis

from backend.app.core.config import settings
from backend.app.db.models import Base, map_cameras_to_nearest_roads


def _is_testing_environment() -> bool:
    """Detects if code is executing within pytest or test runner."""
    return (
        "pytest" in sys.modules
        or "PYTEST_CURRENT_TEST" in os.environ
        or os.getenv("TESTING", "").lower() in ("true", "1", "yes")
    )


# ==============================================================================
# Async Engine & Session Factory (Primary for FastAPI routes & async workers)
# ==============================================================================
# In test environments, NullPool prevents asyncpg connections from binding to closed loops.
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    poolclass=NullPool if _is_testing_environment() else None,
    connect_args={"timeout": 1.0 if _is_testing_environment() else 3.0},
    **({} if _is_testing_environment() else {"pool_size": 10, "max_overflow": 20}),
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ==============================================================================
# Sync Engine & Session Factory (For CLI scripts, initial migrations & sync jobs)
# ==============================================================================
sync_engine = create_engine(
    settings.sync_database_url,
    echo=False,
    pool_pre_ping=True,
    poolclass=NullPool if _is_testing_environment() else None,
    **({} if _is_testing_environment() else {"pool_size": 5, "max_overflow": 10}),
)

SessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ==============================================================================
# Redis Connection Pool
# ==============================================================================
redis_pool = ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=20,
    decode_responses=True,
)


def get_redis_client() -> Redis:
    """
    Returns an asynchronous Redis client instance.
    In test environments, instantiates per-test client to avoid cross-loop issues.
    """
    if _is_testing_environment():
        return Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    return Redis(connection_pool=redis_pool)


# ==============================================================================
# FastAPI Dependencies
# ==============================================================================
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an AsyncSession for the duration of a request.
    Handles rollback on exception and automatic session cleanup.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_db() -> Generator[Session, None, None]:
    """
    Synchronous database session generator for tasks, tests, or scripts.
    """
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# ==============================================================================
# Lifecycle Helpers
# ==============================================================================
async def init_db() -> None:
    """Bootstrap local tests/development; deployed apps require explicit Alembic upgrades."""
    from sqlalchemy import text
    async with async_engine.begin() as conn:
        if getattr(settings, "APP_ENV", "development") in ("production", "staging"):
            await conn.run_sync(check_schema_revision)
            return
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_camera_ingestion_state_status_retry "
                "ON camera_ingestion_state (source_status, next_retry_at)"
            )
        )


def check_schema_revision(connection) -> None:
    """Fail closed on unversioned/outdated staging and production databases."""
    from pathlib import Path
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    current = set(MigrationContext.configure(connection).get_current_heads())
    if current != expected:
        raise RuntimeError("Database migrations required: run python -m alembic upgrade head before starting the app")


async def close_db() -> None:
    """
    Closes database engine connections and Redis pool on application shutdown.
    """
    try:
        await async_engine.dispose()
    except Exception:
        pass
    try:
        sync_engine.dispose()
    except Exception:
        pass
    try:
        await redis_pool.disconnect()
    except Exception:
        pass


__all__ = [
    "Base",
    "async_engine",
    "sync_engine",
    "AsyncSessionLocal",
    "SessionLocal",
    "get_db",
    "get_sync_db",
    "get_redis_client",
    "init_db",
    "close_db",
    "map_cameras_to_nearest_roads",
]
