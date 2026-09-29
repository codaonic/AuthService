import logging

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.config import get_settings
from app.db.models import AdminUser
from app.db.session import async_session_factory

logger = logging.getLogger("app.admin")


async def ensure_default_admin() -> None:
    """Seeds an admin account from DEFAULT_ADMIN_EMAIL/DEFAULT_ADMIN_PASSWORD,
    but only if both are explicitly set -- for scripted/automated deployments
    that need a working login without driving the interactive setup screen.

    Left unset (the default), this does nothing: no admin exists until the
    first person to open /admin completes setup themselves via
    POST /admin/api/setup, so no known/documented credential is ever seeded.
    """
    settings = get_settings()
    if settings.default_admin_email is None or settings.default_admin_password is None:
        return

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
        "Seeded default admin account (%s) from DEFAULT_ADMIN_EMAIL/DEFAULT_ADMIN_PASSWORD -- "
        "sign in at /admin/login and change the password immediately.",
        settings.default_admin_email,
    )
