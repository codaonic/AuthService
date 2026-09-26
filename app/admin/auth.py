import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import verify_password
from app.auth.sessions import create_session, delete_session, get_session_user
from app.config import get_settings
from app.db.models import AdminUser
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.middleware.rate_limit import limiter

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def get_current_admin(request: Request, db: AsyncSession, redis: Redis) -> AdminUser | None:
    settings = get_settings()
    session_id = request.cookies.get(settings.admin_session_cookie_name)
    admin_id = await get_session_user(redis, session_id)
    if admin_id is None:
        return None
    return await db.get(AdminUser, uuid.UUID(admin_id))


@router.get("/admin/login")
async def admin_login_page(request: Request):
    return templates.TemplateResponse(request, "admin/login.html", {"error": None})


@router.post("/admin/login")
@limiter.limit(get_settings().rate_limit_admin_login)
async def admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()
    result = await db.execute(select(AdminUser).where(AdminUser.email == email))
    admin = result.scalar_one_or_none()

    if admin is None or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            request, "admin/login.html", {"error": "Invalid email or password"}, status_code=401
        )

    session_id = await create_session(redis, str(admin.id))
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        settings.admin_session_cookie_name,
        session_id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.admin_session_ttl_seconds,
    )
    return response


@router.post("/admin/logout")
async def admin_logout(request: Request, redis: Redis = Depends(get_redis)):
    settings = get_settings()
    session_id = request.cookies.get(settings.admin_session_cookie_name)
    if session_id:
        await delete_session(redis, session_id)
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(settings.admin_session_cookie_name)
    return response
