import pytest
from sqlalchemy import select

from app.admin import seed
from app.config import Settings
from app.db.models import AdminUser
from tests.helpers import create_admin


@pytest.mark.asyncio
async def test_ensure_default_admin_does_nothing_when_env_vars_unset(db_session, monkeypatch):
    monkeypatch.setattr(seed, "async_session_factory", lambda: db_session)
    # _env_file=None: this repo's own .env (a real dev file, not test config)
    # would otherwise leak its DEFAULT_ADMIN_* values into this "nothing set"
    # case, since Settings() reads it by default (see model_config).
    monkeypatch.setattr(seed, "get_settings", lambda: Settings(_env_file=None))

    await seed.ensure_default_admin()

    result = await db_session.execute(select(AdminUser))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_ensure_default_admin_creates_one_when_env_vars_set(db_session, monkeypatch):
    monkeypatch.setattr(seed, "async_session_factory", lambda: db_session)
    monkeypatch.setattr(
        seed,
        "get_settings",
        lambda: Settings(default_admin_email="admin@example.com", default_admin_password="scripted-deploy-pw!"),
    )

    await seed.ensure_default_admin()

    result = await db_session.execute(select(AdminUser))
    admins = result.scalars().all()
    assert len(admins) == 1
    assert admins[0].email == "admin@example.com"
    assert admins[0].must_change_password is True


@pytest.mark.asyncio
async def test_ensure_default_admin_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(seed, "async_session_factory", lambda: db_session)
    monkeypatch.setattr(
        seed,
        "get_settings",
        lambda: Settings(default_admin_email="admin@example.com", default_admin_password="scripted-deploy-pw!"),
    )
    await create_admin(db_session, email="existing@example.com")

    await seed.ensure_default_admin()

    result = await db_session.execute(select(AdminUser))
    admins = result.scalars().all()
    assert len(admins) == 1
    assert admins[0].email == "existing@example.com"
