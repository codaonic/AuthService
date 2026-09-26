import logging

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.config import get_settings
from app.db.models import AdminUser
from app.db.session import async_session_factory

logger = logging.getLogger("app.admin")


async def ensure_default_admin() -> None:
    settings = get_settings()
    async with async_session_factory() as db:
        result = await db.execute(select(AdminUser).limit(1))
        if result.scalar_one_or_none() is not None:
            return

        db.add(
            AdminUser(
                email=settings.default_admin_email,
                password_hash=hash_password(settings.default_admin_password),
                must_change_password=True,
            )
        )
        await db.commit()

    logger.warning(
        "Seeded default admin account (%s / %s) -- sign in at /admin/login and change the password immediately.",
        settings.default_admin_email,
        settings.default_admin_password,
    )
