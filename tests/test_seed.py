import pytest
from sqlalchemy import select

from app.admin import seed
from app.db.models import AdminUser
from tests.helpers import create_admin


@pytest.mark.asyncio
async def test_ensure_default_admin_creates_one_when_none_exist(db_session, monkeypatch):
    monkeypatch.setattr(seed, "async_session_factory", lambda: db_session)

    await seed.ensure_default_admin()

    result = await db_session.execute(select(AdminUser))
    admins = result.scalars().all()
    assert len(admins) == 1
    assert admins[0].must_change_password is True


@pytest.mark.asyncio
async def test_ensure_default_admin_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(seed, "async_session_factory", lambda: db_session)
    await create_admin(db_session, email="existing@example.com")

    await seed.ensure_default_admin()

    result = await db_session.execute(select(AdminUser))
    admins = result.scalars().all()
    assert len(admins) == 1
    assert admins[0].email == "existing@example.com"
