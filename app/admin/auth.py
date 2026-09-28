import uuid

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import get_session_user
from app.config import get_settings
from app.db.models import AdminUser
from app.db.tenant import bypass_tenant_rls


async def get_current_admin(request: Request, db: AsyncSession, redis: Redis) -> AdminUser | None:
    """Also lifts the per-pool RLS restriction on `users` for the rest of
    this request -- the admin console legitimately spans every pool. Only
    done once we've confirmed a real admin session, not before.
    """
    settings = get_settings()
    session_id = request.cookies.get(settings.admin_session_cookie_name)
    admin_id = await get_session_user(redis, session_id)
    if admin_id is None:
        return None
    admin = await db.get(AdminUser, uuid.UUID(admin_id))
    if admin is not None:
        await bypass_tenant_rls(db)
    return admin
