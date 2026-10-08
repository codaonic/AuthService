import logging
import secrets
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import client_ip, log_event, record_failed_login
from app.auth.mfa import verify_totp
from app.auth.password_reset import create_email_verification_token
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import create_session, get_session_user
from app.config import get_settings
from app.db.contacts import upsert_contact
from app.db.models import Client, ClientAccessGrant, ClientRole, Consent, User, UserRoleAssignment
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls
from app.email import send_verification_email
from app.middleware.rate_limit import limiter
from app.oidc.cimd import is_cimd_client_id, resolve_cimd_client
from app.oidc.scope import resolve_scope

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

FLOW_KEY_PREFIX = "flow:"
CODE_KEY_PREFIX = "code:"
SUPPORTED_CHALLENGE_METHODS = {"S256"}
MIN_PASSWORD_LENGTH = 8

SCOPE_DESCRIPTIONS = {
    "openid": "Confirm your identity",
    "profile": "View your basic profile information",
    "email": "View your email address",
    "offline_access": "Maintain access when you're not present",
}


async def _record_login_failure(
    redis: Redis, email: str, request: Request, client_id: str, reason: str
) -> None:
    ip = client_ip(request)
    log_event("login_failure", level=logging.WARNING, client_id=client_id, email=email, ip=ip, reason=reason)

    email_anomaly = await record_failed_login(redis, f"email:{email}")
    ip_anomaly = ip is not None and await record_failed_login(redis, f"ip:{ip}")
    if email_anomaly or ip_anomaly:
        log_event(
            "anomalous_activity",
            level=logging.WARNING,
            reason="repeated_failed_logins",
            email=email if email_anomaly else None,
            ip=ip if ip_anomaly else None,
        )


async def _load_client(db: AsyncSession, client_id: str) -> Client:
    if is_cimd_client_id(client_id):
        client = await resolve_cimd_client(db, client_id)
    else:
        result = await db.execute(select(Client).where(Client.client_id == client_id))
        client = result.scalar_one_or_none()
        if client is None:
            raise HTTPException(400, "invalid_client")
    if not client.enabled:
        raise HTTPException(400, "invalid_client")
    return client


async def _signup_roles(db: AsyncSession, client: Client) -> list[str]:
    if not (client.roles_enabled and client.allow_signup_role_selection):
        return []
    result = await db.execute(
        select(ClientRole.name).where(ClientRole.client_id == client.client_id).order_by(ClientRole.name)
    )
    return [name for (name,) in result.all()]


async def _find_user_for_client(db: AsyncSession, email: str, client: Client) -> "User | None":
    """Find the user who can authenticate for this client.

    Checks: user registered directly with this client, OR registered with any
    other client in the same pool (shared identity across pooled apps).
    """
    if client.user_pool_id is not None:
        pool_client_ids = select(Client.client_id).where(Client.user_pool_id == client.user_pool_id)
        result = await db.execute(
            select(User).where(User.email == email, User.client_id.in_(pool_client_ids))
        )
    else:
        result = await db.execute(
            select(User).where(User.email == email, User.client_id == client.client_id)
        )
    return result.scalar_one_or_none()


async def _user_can_access_client(db: AsyncSession, user: "User", client: Client) -> bool:
    """Check if a user (by registration client) can authenticate for a given client."""
    if user.client_id == client.client_id:
        return True
    if client.user_pool_id is None:
        return False
    user_client = (
        await db.execute(select(Client).where(Client.client_id == user.client_id))
    ).scalar_one_or_none()
    return user_client is not None and user_client.user_pool_id == client.user_pool_id


async def _has_client_access(db: AsyncSession, client_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(ClientAccessGrant).where(
            ClientAccessGrant.client_id == client_id, ClientAccessGrant.user_id == uuid.UUID(user_id)
        )
    )
    return result.scalar_one_or_none() is not None


def _branding(client: Client) -> dict:
    """Fields every login/signup/consent template context includes so a
    client can brand these pages -- e.g. for a popup/embedded sign-in that
    should feel like it belongs to the site that opened it.
    """
    return {"client_name": client.client_name, "logo_url": client.logo_url, "brand_color": client.brand_color}


async def _get_flow_client(db: AsyncSession, redis: Redis, flow_id: str) -> Client:
    client_id = await redis.hget(f"{FLOW_KEY_PREFIX}{flow_id}", "client_id")
    if client_id is None:
        raise HTTPException(400, "invalid_request: expired or unknown flow")
    return await _load_client(db, client_id)


@router.get("/authorize")
@limiter.limit(get_settings().rate_limit_authorize)
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    resource: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    scope: str = "",
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()

    if response_type != "code":
        raise HTTPException(400, "unsupported_response_type")
    if code_challenge_method not in SUPPORTED_CHALLENGE_METHODS:
        raise HTTPException(400, "invalid_request: code_challenge_method must be S256")

    client = await _load_client(db, client_id)
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "invalid_redirect_uri")
    scope = resolve_scope(scope, client.allowed_scope)

    flow_id = secrets.token_urlsafe(16)
    flow = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "resource": resource,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scope,
        "state": state or "",
    }
    await redis.hset(f"{FLOW_KEY_PREFIX}{flow_id}", mapping=flow)
    await redis.expire(f"{FLOW_KEY_PREFIX}{flow_id}", 600)

    session_id = request.cookies.get(settings.session_cookie_name)
    user_id = await get_session_user(redis, session_id)

    if user_id is not None:
        # A session cookie from a different, isolated app/pool must not
        # grant access here -- fall through to login/signup for this client.
        user = await db.get(User, uuid.UUID(user_id))
        if user is None or not await _user_can_access_client(db, user, client):
            user_id = None

    if user_id is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "flow_id": flow_id,
                "client_id": client_id,
                **_branding(client),
                "allow_signup": client.allow_signup,
                "show_totp": False,
                "error": None,
            },
        )

    return await _continue_flow(request, db, redis, flow_id, user_id)


@router.get("/login")
async def login_page(
    request: Request,
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "flow_id": flow_id,
            "client_id": client.client_id,
            **_branding(client),
            "allow_signup": client.allow_signup,
            "show_totp": False,
            "error": None,
        },
    )


@router.post("/login")
async def login(
    request: Request,
    flow_id: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    totp_code: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()
    client = await _get_flow_client(db, redis, flow_id)
    await bypass_tenant_rls(db)

    user = await _find_user_for_client(db, email, client)

    if user is None or user.status != "active" or not verify_password(password, user.password_hash):
        await _record_login_failure(redis, email, request, client.client_id, "invalid_credentials")
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "flow_id": flow_id,
                "client_id": client.client_id,
                **_branding(client),
                "allow_signup": client.allow_signup,
                "show_totp": False,
                "error": "Invalid email or password",
            },
            status_code=401,
        )

    if user.mfa_secret and not verify_totp(user.mfa_secret, totp_code):
        await _record_login_failure(redis, email, request, client.client_id, "invalid_mfa_code")
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "flow_id": flow_id,
                "client_id": client.client_id,
                **_branding(client),
                "allow_signup": client.allow_signup,
                "show_totp": True,
                "email": email,
                "error": "Enter the code from your authenticator app" if not totp_code else "Invalid authentication code",
            },
            status_code=401,
        )

    log_event("login_success", client_id=client.client_id, user_id=str(user.id), ip=client_ip(request))
    session_id = await create_session(
        redis, str(user.id), ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    response = await _continue_flow(request, db, redis, flow_id, str(user.id))
    response.set_cookie(
        settings.session_cookie_name,
        session_id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )
    return response


@router.get("/signup")
async def signup_page(
    request: Request,
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    if not client.allow_signup:
        raise HTTPException(403, "signup_disabled")
    roles = await _signup_roles(db, client)
    return templates.TemplateResponse(
        request,
        "signup.html",
        {"flow_id": flow_id, "client_id": client.client_id, **_branding(client), "roles": roles, "error": None},
    )


@router.post("/signup")
async def signup(
    request: Request,
    flow_id: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    role: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()
    client = await _get_flow_client(db, redis, flow_id)
    if not client.allow_signup:
        raise HTTPException(403, "signup_disabled")
    await bypass_tenant_rls(db)
    roles = await _signup_roles(db, client)

    def error(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request,
            "signup.html",
            {
                "flow_id": flow_id,
                "client_id": client.client_id,
                **_branding(client),
                "roles": roles,
                "error": message,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
            },
            status_code=status_code,
        )

    if not first_name.strip():
        return error("First name is required")
    if not last_name.strip():
        return error("Last name is required")
    if password != confirm_password:
        return error("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        return error(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    existing = await db.execute(
        select(User).where(User.email == email, User.client_id == client.client_id)
    )
    if existing.scalar_one_or_none() is not None:
        return error("An account with that email already exists")

    user = User(
        client_id=client.client_id,
        email=email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    await upsert_contact(db, email=email, app_name=client.client_name or client.client_id)
    await db.flush()  # populates user.id, generated at flush time, not construction
    if client.restrict_access:
        # They signed up through this app's own signup page -- that's
        # itself the act of requesting access to it, so grant it
        # immediately rather than leaving a freshly-created account locked
        # out of the one app it just signed up for.
        db.add(ClientAccessGrant(client_id=client.client_id, user_id=user.id))
    if role and role in roles:
        db.add(UserRoleAssignment(user_id=user.id, client_id=client.client_id, role=role))
    await db.commit()
    await db.refresh(user)
    log_event("signup_success", client_id=client.client_id, user_id=str(user.id), ip=client_ip(request))

    # Verification is informational, not a login gate -- a failed send
    # shouldn't block account creation. See plan/password-recovery-mcp-passkeys-plan.md §5.2.
    token = await create_email_verification_token(redis, str(user.id))
    await send_verification_email(user.email, token)

    session_id = await create_session(
        redis, str(user.id), ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    response = await _continue_flow(request, db, redis, flow_id, str(user.id))
    response.set_cookie(
        settings.session_cookie_name,
        session_id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )
    return response


async def _continue_flow(
    request: Request, db: AsyncSession, redis: Redis, flow_id: str, user_id: str
):
    flow = await redis.hgetall(f"{FLOW_KEY_PREFIX}{flow_id}")
    if not flow:
        raise HTTPException(400, "invalid_request: expired or unknown flow")

    client = await _load_client(db, flow["client_id"])
    requested_scopes = set(flow["scope"].split()) if flow["scope"] else set()

    if client.restrict_access and not await _has_client_access(db, client.client_id, user_id):
        log_event(
            "access_denied_not_assigned",
            level=logging.WARNING,
            client_id=client.client_id,
            user_id=user_id,
        )
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "flow_id": flow_id,
                "client_id": client.client_id,
                **_branding(client),
                "allow_signup": client.allow_signup,
                "show_totp": False,
                "error": "Your account doesn't have access to this application. Contact an administrator.",
            },
            status_code=403,
        )

    result = await db.execute(
        select(Consent).where(
            Consent.user_id == uuid.UUID(user_id), Consent.client_id == client.client_id
        )
    )
    consent = result.scalar_one_or_none()
    if consent is None or not requested_scopes.issubset(set(consent.scopes)):
        return templates.TemplateResponse(
            request,
            "consent.html",
            {
                "flow_id": flow_id,
                "client_id": client.client_id,
                **_branding(client),
                "scopes": sorted(requested_scopes),
                "scope_descriptions": SCOPE_DESCRIPTIONS,
            },
        )

    return await _issue_code(redis, flow_id, flow, user_id)


@router.post("/consent")
async def consent(
    request: Request,
    flow_id: str = Form(...),
    approve: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()
    flow = await redis.hgetall(f"{FLOW_KEY_PREFIX}{flow_id}")
    if not flow:
        raise HTTPException(400, "invalid_request: expired or unknown flow")

    session_id = request.cookies.get(settings.session_cookie_name)
    user_id = await get_session_user(redis, session_id)
    if user_id is None:
        raise HTTPException(401, "login_required")

    if approve != "true":
        params = {"error": "access_denied"}
        if flow["state"]:
            params["state"] = flow["state"]
        await redis.delete(f"{FLOW_KEY_PREFIX}{flow_id}")
        return RedirectResponse(f"{flow['redirect_uri']}?{urlencode(params)}", status_code=303)

    requested_scopes = set(flow["scope"].split()) if flow["scope"] else set()
    result = await db.execute(
        select(Consent).where(
            Consent.user_id == uuid.UUID(user_id), Consent.client_id == flow["client_id"]
        )
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        db.add(
            Consent(
                user_id=uuid.UUID(user_id),
                client_id=flow["client_id"],
                scopes=sorted(requested_scopes),
            )
        )
    else:
        existing.scopes = sorted(requested_scopes | set(existing.scopes))
    await db.commit()

    return await _issue_code(redis, flow_id, flow, user_id)


async def _issue_code(redis: Redis, flow_id: str, flow: dict, user_id: str) -> RedirectResponse:
    settings = get_settings()
    code = secrets.token_urlsafe(32)
    await redis.hset(
        f"{CODE_KEY_PREFIX}{code}",
        mapping={
            "client_id": flow["client_id"],
            "user_id": user_id,
            "resource": flow["resource"],
            "code_challenge": flow["code_challenge"],
            "code_challenge_method": flow["code_challenge_method"],
            "redirect_uri": flow["redirect_uri"],
            "scope": flow["scope"],
        },
    )
    await redis.expire(f"{CODE_KEY_PREFIX}{code}", settings.authorization_code_ttl_seconds)
    await redis.delete(f"{FLOW_KEY_PREFIX}{flow_id}")

    params = {"code": code, "iss": settings.issuer_url}
    if flow["state"]:
        params["state"] = flow["state"]
    return RedirectResponse(f"{flow['redirect_uri']}?{urlencode(params)}", status_code=303)
