import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.db")

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def wait_for_database(max_attempts: int = 10, delay_seconds: float = 2.0) -> None:
    """Retry the first DB connection instead of crashing on it.

    Postgres's `pg_isready`-based healthcheck can report "healthy" during its
    brief internal re-init cycle, before the configured role/db are actually
    ready for real connections -- so `depends_on: condition: service_healthy`
    alone isn't a reliable readiness guarantee on the very first boot against
    a fresh volume.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            if attempt == max_attempts:
                raise
            logger.warning(
                "Database not ready yet (attempt %d/%d): %s -- retrying in %.0fs",
                attempt,
                max_attempts,
                exc,
                delay_seconds,
            )
            await asyncio.sleep(delay_seconds)
