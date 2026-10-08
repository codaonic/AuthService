import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import client_ip, log_event
from app.auth.passwords import hash_password
from app.auth.password_reset import (
    consume_email_verification_token,
    consume_password_reset_token,
    create_email_verification_token,
    create_password_reset_token,
)
from app.auth.sessions import revoke_all_sessions_for_user
from app.config import get_settings
from app.db.models import User
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls
from app.email import send_password_reset_email, send_verification_email
from app.middleware.rate_limit import limiter
from app.oidc.authorize import _find_user_for_client, _get_flow_client, asset_version
from app.oidc.refresh import revoke_all_refresh_tokens_for_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["asset_version"] = asset_version

MIN_PASSWORD_LENGTH = 8


@router.get("/forgot-password")
async def forgot_password_page(
    request: Request,
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    return templates.TemplateResponse(
        request, "forgot_password.html", {"flow_id": flow_id, "client_id": client.client_id, "sent": False}
    )


@router.post("/forgot-password")
@limiter.limit(get_settings().rate_limit_forgot_password)
async def forgot_password_submit(
    request: Request,
    flow_id: str = Form(...),
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    await bypass_tenant_rls(db)

    user = await _find_user_for_client(db, email, client)
    if user is not None and user.status == "active":
        token = await create_password_reset_token(redis, str(user.id))
        await send_password_reset_email(user.email, token)
        log_event("password_reset_requested", client_id=client.client_id, user_id=str(user.id), ip=client_ip(request))

    # Always the same response -- never reveal whether the account exists.
    return templates.TemplateResponse(
        request, "forgot_password.html", {"flow_id": flow_id, "client_id": client.client_id, "sent": True}
    )


@router.get("/reset-password")
async def reset_password_page(request: Request, token: str):
    return templates.TemplateResponse(request, "reset_password.html", {"token": token, "error": None})


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    def error(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request, "reset_password.html", {"token": token, "error": message}, status_code=status_code
        )

    if password != confirm_password:
        return error("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        return error(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    user_id = await consume_password_reset_token(redis, token)
    if user_id is None:
        return error("This reset link is invalid or has expired. Request a new one.")

    # Authorized by possession of the single-use token, not pool membership --
    # there's no client/pool in scope on this email-link flow.
    await bypass_tenant_rls(db)
    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        return error("This reset link is invalid or has expired. Request a new one.")

    user.password_hash = hash_password(password)
    await db.commit()

    # A password reset should kill every other session/token this user has.
    await revoke_all_sessions_for_user(redis, str(user.id))
    await revoke_all_refresh_tokens_for_user(db, redis, str(user.id))
    log_event("password_reset_completed", user_id=str(user.id), ip=client_ip(request))

    return templates.TemplateResponse(request, "reset_password_done.html", {})


@router.get("/verify-email")
async def verify_email(request: Request, token: str, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    user_id = await consume_email_verification_token(redis, token)
    if user_id is None:
        return templates.TemplateResponse(
            request, "verify_email_result.html", {"success": False}, status_code=400
        )

    await bypass_tenant_rls(db)
    user = await db.get(User, uuid.UUID(user_id))
    if user is not None:
        user.email_verified = True
        await db.commit()
        log_event("email_verified", user_id=str(user.id))

    return templates.TemplateResponse(request, "verify_email_result.html", {"success": True})


@router.get("/resend-verification")
async def resend_verification_page(
    request: Request,
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    return templates.TemplateResponse(
        request, "resend_verification.html", {"flow_id": flow_id, "client_id": client.client_id, "sent": False}
    )


@router.post("/resend-verification")
@limiter.limit(get_settings().rate_limit_forgot_password)
async def resend_verification_submit(
    request: Request,
    flow_id: str = Form(...),
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    await bypass_tenant_rls(db)

    user = await _find_user_for_client(db, email, client)
    if user is not None and not user.email_verified:
        token = await create_email_verification_token(redis, str(user.id))
        await send_verification_email(user.email, token)

    return templates.TemplateResponse(
        request, "resend_verification.html", {"flow_id": flow_id, "client_id": client.client_id, "sent": True}
    )
