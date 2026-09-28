import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import get_current_admin
from app.audit import client_ip, log_event, record_failed_login, recent_events
from app.auth.password_reset import create_password_reset_token
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import create_session, delete_session, revoke_all_sessions_for_user
from app.config import get_settings
from app.db.models import AdminUser, Client, Resource, User, UserPool
from app.db.pools import get_or_create_pool
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.email import send_password_reset_email
from app.middleware.rate_limit import limiter
from app.oidc.refresh import revoke_all_refresh_tokens_for_user

router = APIRouter(prefix="/admin/api")

ALL_GRANT_TYPES = ["authorization_code", "refresh_token", "client_credentials"]
MIN_PASSWORD_LENGTH = 8


async def require_admin(
    request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> AdminUser:
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        raise HTTPException(401, "not_authenticated")
    return admin


def _admin_json(admin: AdminUser) -> dict:
    return {"id": str(admin.id), "email": admin.email, "must_change_password": admin.must_change_password}


def _client_json(client: Client, pool_name: str) -> dict:
    return {
        "id": str(client.id),
        "client_id": client.client_id,
        "client_name": client.client_name,
        "client_type": client.client_type,
        "registration_method": client.registration_method,
        "application_type": client.application_type,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "allowed_scope": client.allowed_scope,
        "allow_signup": client.allow_signup,
        "enabled": client.enabled,
        "mtls_cert_thumbprint": client.mtls_cert_thumbprint,
        "cimd_fetched_at": client.cimd_fetched_at.isoformat() if client.cimd_fetched_at else None,
        "pool_name": pool_name,
    }


def _user_json(user: User, pool_name: str) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "pool_name": pool_name,
        "status": user.status,
        "email_verified": user.email_verified,
    }


def _pool_json(pool: UserPool) -> dict:
    return {"id": str(pool.id), "name": pool.name}


def _resource_json(resource: Resource) -> dict:
    return {"resource_id": resource.resource_id, "name": resource.name, "metadata_url": resource.metadata_url}


def _format_events(raw_events: list[dict]) -> list[dict]:
    events = []
    for raw in raw_events:
        ts, level, event = raw["ts"], raw["level"], raw["event"]
        extra = {k: v for k, v in raw.items() if k not in ("ts", "level", "event")}
        events.append(
            {
                "time": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "level": level,
                "event": event,
                "extra": extra,
            }
        )
    return events


# --- Auth ---


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
@limiter.limit(get_settings().rate_limit_admin_login)
async def api_login(
    request: Request,
    body: LoginBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()
    result = await db.execute(select(AdminUser).where(AdminUser.email == body.email))
    admin = result.scalar_one_or_none()

    if admin is None or not verify_password(body.password, admin.password_hash):
        ip = client_ip(request)
        log_event("admin_login_failure", level=logging.WARNING, email=body.email, ip=ip)
        if await record_failed_login(redis, f"admin:{body.email}"):
            log_event(
                "anomalous_activity", level=logging.WARNING, reason="repeated_admin_login_failures",
                email=body.email, ip=ip,
            )
        raise HTTPException(401, "Invalid email or password")

    log_event("admin_login_success", admin_id=str(admin.id), ip=client_ip(request))
    session_id = await create_session(
        redis, str(admin.id), ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    response.set_cookie(
        settings.admin_session_cookie_name,
        session_id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.admin_session_ttl_seconds,
    )
    return _admin_json(admin)


@router.post("/logout", status_code=204)
async def api_logout(request: Request, response: Response, redis: Redis = Depends(get_redis)):
    settings = get_settings()
    session_id = request.cookies.get(settings.admin_session_cookie_name)
    if session_id:
        await delete_session(redis, session_id)
    response.delete_cookie(settings.admin_session_cookie_name)


@router.get("/me")
async def api_me(admin: AdminUser = Depends(require_admin)):
    return _admin_json(admin)


# --- Dashboard ---


@router.get("/dashboard")
async def api_dashboard(admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    counts = {}
    for label, model in [("pools", UserPool), ("clients", Client), ("resources", Resource), ("users", User)]:
        result = await db.execute(select(func.count()).select_from(model))
        counts[label] = result.scalar_one()

    return {"counts": counts, "recent": _format_events(recent_events(8))}


# --- Login groups (pools) ---


@router.get("/pools")
async def api_list_pools(admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserPool).order_by(UserPool.name))
    return [_pool_json(p) for p in result.scalars().all()]


class CreatePoolBody(BaseModel):
    name: str


@router.post("/pools", status_code=201)
async def api_create_pool(
    body: CreatePoolBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    pool = await get_or_create_pool(db, body.name)
    return _pool_json(pool)


# --- Resources ---


@router.get("/resources")
async def api_list_resources(admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Resource).order_by(Resource.name))
    return [_resource_json(r) for r in result.scalars().all()]


class CreateResourceBody(BaseModel):
    resource_id: str
    name: str
    metadata_url: str = ""


@router.post("/resources", status_code=201)
async def api_create_resource(
    body: CreateResourceBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    existing = await db.execute(select(Resource).where(Resource.resource_id == body.resource_id))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(400, f"'{body.resource_id}' already exists")

    resource = Resource(resource_id=body.resource_id, name=body.name, metadata_url=body.metadata_url or None)
    db.add(resource)
    await db.commit()
    return _resource_json(resource)


# --- Clients (applications) ---


@router.get("/clients")
async def api_list_clients(admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Client, UserPool.name).join(UserPool).order_by(Client.client_id))
    return [_client_json(c, pool_name) for c, pool_name in result.all()]


class CreateClientBody(BaseModel):
    client_id: str
    client_type: str
    redirect_uris: str = ""
    grant_types: list[str] = []
    scope: str = ""
    application_type: str = "web"
    user_pool: str = "default"
    allow_signup: bool = False


@router.post("/clients", status_code=201)
async def api_create_client(
    body: CreateClientBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    existing = await db.execute(select(Client).where(Client.client_id == body.client_id))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(400, f"client '{body.client_id}' already exists")

    is_public = body.client_type == "public"
    client_secret = None if is_public else secrets.token_urlsafe(32)
    pool = await get_or_create_pool(db, body.user_pool)

    client = Client(
        user_pool_id=pool.id,
        client_id=body.client_id,
        client_secret_hash=hash_password(client_secret) if client_secret else None,
        client_type=body.client_type,
        redirect_uris=[u.strip() for u in body.redirect_uris.splitlines() if u.strip()],
        grant_types=body.grant_types or ["authorization_code", "refresh_token"],
        allowed_scope=body.scope,
        registration_method="static",
        application_type=body.application_type,
        allow_signup=body.allow_signup,
    )
    db.add(client)
    await db.commit()

    result = {**_client_json(client, pool.name), "client_secret": client_secret}
    return result


class MtlsBody(BaseModel):
    thumbprint: str = ""


@router.post("/clients/{client_id}/mtls")
async def api_set_client_mtls(
    client_id: str, body: MtlsBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(404, "unknown_client")
    client.mtls_cert_thumbprint = body.thumbprint.strip().upper() or None
    await db.commit()
    pool = await db.get(UserPool, client.user_pool_id)
    return _client_json(client, pool.name)


@router.post("/clients/{client_id}/toggle-signup")
async def api_toggle_client_signup(
    client_id: str, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(404, "unknown_client")
    client.allow_signup = not client.allow_signup
    await db.commit()
    pool = await db.get(UserPool, client.user_pool_id)
    return _client_json(client, pool.name)


@router.post("/clients/{client_id}/toggle-enabled")
async def api_toggle_client_enabled(
    client_id: str,
    request: Request,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(404, "unknown_client")
    client.enabled = not client.enabled
    await db.commit()
    log_event(
        "client_" + ("enabled" if client.enabled else "disabled"), client_id=client_id, admin_id=str(admin.id)
    )
    pool = await db.get(UserPool, client.user_pool_id)
    return _client_json(client, pool.name)


# --- Users ---


@router.get("/users")
async def api_list_users(
    pool: str | None = None, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    query = select(User, UserPool.name).join(UserPool).order_by(User.email)
    if pool:
        query = query.where(UserPool.name == pool)
    result = await db.execute(query)
    return [_user_json(u, pool_name) for u, pool_name in result.all()]


class CreateUserBody(BaseModel):
    email: str
    password: str
    user_pool: str = "default"


@router.post("/users", status_code=201)
async def api_create_user(
    body: CreateUserBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    pool = await get_or_create_pool(db, body.user_pool)
    existing = await db.execute(select(User).where(User.email == body.email, User.user_pool_id == pool.id))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(400, f"'{body.email}' already exists in pool '{body.user_pool}'")

    user = User(user_pool_id=pool.id, email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    return _user_json(user, pool.name)


@router.post("/users/{user_id}/toggle-status")
async def api_toggle_user_status(
    user_id: str,
    request: Request,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(404, "unknown_user")

    user.status = "disabled" if user.status == "active" else "active"
    await db.commit()
    if user.status == "disabled":
        await revoke_all_sessions_for_user(redis, str(user.id))
        await revoke_all_refresh_tokens_for_user(db, redis, str(user.id))
    log_event("user_" + user.status, user_id=str(user.id), email=user.email, admin_id=str(admin.id))

    pool = await db.get(UserPool, user.user_pool_id)
    return _user_json(user, pool.name)


@router.post("/users/{user_id}/sign-out", status_code=204)
async def api_sign_out_user(
    user_id: str,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user = await db.get(User, uuid.UUID(user_id))
    if user is not None:
        await revoke_all_sessions_for_user(redis, str(user.id))
        await revoke_all_refresh_tokens_for_user(db, redis, str(user.id))
        log_event("user_signed_out_by_admin", user_id=str(user.id), admin_id=str(admin.id))


@router.post("/users/{user_id}/send-reset", status_code=204)
async def api_send_password_reset(
    user_id: str,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user = await db.get(User, uuid.UUID(user_id))
    if user is not None:
        token = await create_password_reset_token(redis, str(user.id))
        await send_password_reset_email(user.email, token)


# --- Audit log ---


@router.get("/audit")
async def api_audit_log(admin: AdminUser = Depends(require_admin)):
    return _format_events(recent_events())


# --- Admin's own account ---


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


@router.post("/account/password")
async def api_change_password(
    body: ChangePasswordBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    if not verify_password(body.current_password, admin.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if body.new_password != body.confirm_password:
        raise HTTPException(400, "New passwords do not match")
    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    admin.password_hash = hash_password(body.new_password)
    admin.must_change_password = False
    await db.commit()
    return _admin_json(admin)
