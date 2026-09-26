from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

import pytest

from app.db import session as session_module


@pytest.mark.asyncio
async def test_init_db_schema_creates_tables_on_empty_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(session_module, "engine", engine)

    stamped = {"calls": 0}
    monkeypatch.setattr(session_module, "_stamp_alembic_head", lambda: stamped.__setitem__("calls", stamped["calls"] + 1))

    await session_module.init_db_schema()

    async with engine.connect() as conn:
        has_admin_users = await conn.run_sync(lambda c: inspect(c).has_table("admin_users"))
    assert has_admin_users
    assert stamped["calls"] == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_schema_noop_when_already_migrated(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    monkeypatch.setattr(session_module, "engine", engine)

    stamped = {"calls": 0}
    monkeypatch.setattr(session_module, "_stamp_alembic_head", lambda: stamped.__setitem__("calls", stamped["calls"] + 1))

    await session_module.init_db_schema()

    async with engine.connect() as conn:
        has_admin_users = await conn.run_sync(lambda c: inspect(c).has_table("admin_users"))
    assert has_admin_users is False
    assert stamped["calls"] == 0
    await engine.dispose()
