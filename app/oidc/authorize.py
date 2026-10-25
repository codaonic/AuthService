import logging
import secrets
import time
import uuid
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import client_ip, log_event, record_failed_login
from app.auth.mfa import verify_totp
from app.auth.password_reset import create_email_verification_token
from app.auth.lockout import clear_failures, is_locked, record_failure
from app.auth.passwords import burn_password_check, hash_password_async, verify_password_async
from app.auth.sessions import app_auth_time, get_session_user, sign_in
from app.config import get_settings
from app.db.contacts import upsert_contact
from app.db.models import Client, ClientAccessGrant, ClientRole, Consent, User, UserRoleAssignment
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls
from app.email import send_verification_email
from app.middleware.rate_limit import limiter
from app.oidc import embed as embedding
from app.oidc.cimd import is_cimd_client_id, resolve_cimd_client
from app.oidc.scope import resolve_scope

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@lru_cache
def asset_version() -> str:
    """Appended to static asset URLs so browsers refetch them after a change.

    Worked out once per process -- it walks the whole static directory, which
    is too much to do on every page view. Static files only change with a
    deploy, which restarts the app anyway.
    """
    return str(int(max(p.stat().st_mtime for p in Path("app/static").rglob("*") if p.is_file())))


templates.env.globals["asset_version"] = asset_version

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


async def _page(redis: Redis, request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    """Render a page of a sign-in flow -- inside an application's own page
    when the flow is embedded (see app/oidc/embed.py), otherwise normally."""
    embed = embedding.decode(await redis.hget(f"{FLOW_KEY_PREFIX}{context['flow_id']}", "embed"))
    response = templates.TemplateResponse(request, name, {**context, "embed": embed}, status_code=status_code)
    if embed:
        response.headers["Content-Security-Policy"] = embedding.frame_ancestors(embed["origin"])
    return response


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
    resource: str,
    code_challenge: str,
    redirect_uri: str | None = None,
    code_challenge_method: str = "S256",
    scope: str = "",
    state: str | None = None,
    # Embedded sign-in (app/oidc/embed.py): the code goes back by postMessage
    # to `origin` instead of a redirect.
    response_mode: str = "query",
    origin: str | None = None,
    frame_id: str | None = None,
    appearance: str | None = None,
    screen: str = "login",
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()

    if response_type != "code":
        raise HTTPException(400, "unsupported_response_type")
    if code_challenge_method not in SUPPORTED_CHALLENGE_METHODS:
        raise HTTPException(400, "invalid_request: code_challenge_method must be S256")

    client = await _load_client(db, client_id)
    embed = ""
    if response_mode == "web_message":
        if not origin or origin not in (client.embed_origins or []) or not embedding.valid_frame_id(frame_id):
            raise HTTPException(400, "invalid_request: this page may not embed sign-in for this application")
        embed = embedding.encode(origin, frame_id, embedding.parse_appearance(appearance))
        redirect_uri = origin
    elif response_mode != "query":
        raise HTTPException(400, "unsupported_response_mode")
    elif redirect_uri is None or redirect_uri not in client.redirect_uris:
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
        "embed": embed,
    }
    async with redis.pipeline(transaction=True) as pipe:
        await pipe.hset(f"{FLOW_KEY_PREFIX}{flow_id}", mapping=flow).expire(f"{FLOW_KEY_PREFIX}{flow_id}", 600).execute()

    session_id = request.cookies.get(settings.session_cookie_name)
    user_id = await get_session_user(redis, session_id)

    auth_time = None
    if user_id is not None:
        # A session cookie from a different, isolated app/pool must not
        # grant access here -- fall through to login/signup for this client.
        user = await db.get(User, uuid.UUID(user_id))
        if user is None or not await _user_can_access_client(db, user, client):
            user_id = None

    if user_id is not None:
        # Signed out of this application specifically, or signed in longer
        # ago than this application allows -- ask for credentials again.
        auth_time = await app_auth_time(redis, session_id, client.client_id)
        limit = client.session_ttl_seconds  # 0 = no per-application limit
        if auth_time is None or (limit and time.time() - auth_time > limit):
            user_id = None

    if user_id is None and screen == "signup" and client.allow_signup:
        return await _page(
            redis,
            request,
            "signup.html",
            {
                "flow_id": flow_id,
                "client_id": client_id,
                **_branding(client),
                "roles": await _signup_roles(db, client),
                "error": None,
            },
        )

    if user_id is None:
        return await _page(
            redis,
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

    return await _continue_flow(request, db, redis, flow_id, user_id, auth_time=auth_time)


@router.get("/login")
async def login_page(
    request: Request,
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    return await _page(
        redis,
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
@limiter.limit(get_settings().rate_limit_login)
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

    if await is_locked(redis, "user", email):
        await _record_login_failure(redis, email, request, client.client_id, "locked_out")
        return await _page(
            redis,
            request,
            "login.html",
            {
                "flow_id": flow_id,
                "client_id": client.client_id,
                **_branding(client),
                "allow_signup": client.allow_signup,
                "show_totp": False,
                "error": "Too many failed attempts. Try again in a few minutes.",
            },
            status_code=429,
        )

    user = await _find_user_for_client(db, email, client)
    if user is None:
        await burn_password_check(password)

    if user is None or user.status != "active" or not await verify_password_async(password, user.password_hash):
        await record_failure(redis, "user", email)
        await _record_login_failure(redis, email, request, client.client_id, "invalid_credentials")
        return await _page(
            redis,
            request,
            "login.html",
            {
                "flow_id": flow_id,
                "client_id": client.client_id,
                **_branding(client),
                "allow_signup": client.allow_signup,
                "show_totp": False,
                "email": email,
                "error": "Invalid email or password",
            },
            status_code=401,
        )

    if user.mfa_secret and not verify_totp(user.mfa_secret, totp_code):
        if totp_code:  # a blank code is just the prompt for one, not a guess
            await record_failure(redis, "user", email)
        await _record_login_failure(redis, email, request, client.client_id, "invalid_mfa_code")
        return await _page(
            redis,
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

    await clear_failures(redis, "user", email)
    log_event("login_success", client_id=client.client_id, user_id=str(user.id), ip=client_ip(request))
    session_id = await sign_in(
        redis,
        request.cookies.get(settings.session_cookie_name),
        str(user.id),
        client.client_id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
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
    return await _page(
        redis,
        request,
        "signup.html",
        {"flow_id": flow_id, "client_id": client.client_id, **_branding(client), "roles": roles, "error": None},
    )


@router.post("/signup")
@limiter.limit(get_settings().rate_limit_signup)
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

    async def error(message: str, status_code: int = 400):
        return await _page(
            redis,
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
        return await error("First name is required")
    if not last_name.strip():
        return await error("Last name is required")
    if password != confirm_password:
        return await error("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        return await error(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    # Across the whole login group, not just this app: a second account with
    # the same email there would make the owner's own login ambiguous.
    if await _find_user_for_client(db, email, client) is not None:
        return await error("An account with that email already exists")

    user = User(
        client_id=client.client_id,
        email=email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        password_hash=await hash_password_async(password),
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

    session_id = await sign_in(
        redis,
        request.cookies.get(settings.session_cookie_name),
        str(user.id),
        client.client_id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
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
    request: Request,
    db: AsyncSession,
    redis: Redis,
    flow_id: str,
    user_id: str,
    auth_time: int | None = None,
):
    """`auth_time` is when the user actually authenticated -- now, unless an
    existing session is being reused. It rides along on the flow so the
    tokens issued at the end can't outlive the application's sign-in timeout.
    """
    flow = await redis.hgetall(f"{FLOW_KEY_PREFIX}{flow_id}")
    if not flow:
        raise HTTPException(400, "invalid_request: expired or unknown flow")
    flow["auth_time"] = str(auth_time or round(time.time()))
    await redis.hset(f"{FLOW_KEY_PREFIX}{flow_id}", "auth_time", flow["auth_time"])

    client = await _load_client(db, flow["client_id"])
    requested_scopes = set(flow["scope"].split()) if flow["scope"] else set()

    if client.restrict_access and not await _has_client_access(db, client.client_id, user_id):
        log_event(
            "access_denied_not_assigned",
            level=logging.WARNING,
            client_id=client.client_id,
            user_id=user_id,
        )
        return await _page(
            redis,
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
        if flow.get("embed"):
            # Embedding is something only an admin can turn on, for the
            # organisation's own applications -- and a consent screen inside
            # the requesting app's own page would be no real consent anyway.
            await _record_consent(db, consent, user_id, client.client_id, requested_scopes)
            return await _issue_code(request, redis, flow_id, flow, user_id)
        return await _page(
            redis,
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

    return await _issue_code(request, redis, flow_id, flow, user_id)


async def _record_consent(
    db: AsyncSession, existing: Consent | None, user_id: str, client_id: str, scopes: set[str]
) -> None:
    if existing is None:
        db.add(Consent(user_id=uuid.UUID(user_id), client_id=client_id, scopes=sorted(scopes)))
    else:
        existing.scopes = sorted(scopes | set(existing.scopes))
    await db.commit()


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
    await _record_consent(db, result.scalar_one_or_none(), user_id, flow["client_id"], requested_scopes)

    return await _issue_code(request, redis, flow_id, flow, user_id)


async def _issue_code(
    request: Request, redis: Redis, flow_id: str, flow: dict, user_id: str
) -> RedirectResponse | HTMLResponse:
    settings = get_settings()
    code = secrets.token_urlsafe(32)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(
            f"{CODE_KEY_PREFIX}{code}",
            mapping={
                "client_id": flow["client_id"],
                "user_id": user_id,
                "resource": flow["resource"],
                "code_challenge": flow["code_challenge"],
                "code_challenge_method": flow["code_challenge_method"],
                "redirect_uri": flow["redirect_uri"],
                "scope": flow["scope"],
                "auth_time": flow.get("auth_time") or str(round(time.time())),
            },
        )
        pipe.expire(f"{CODE_KEY_PREFIX}{code}", settings.authorization_code_ttl_seconds)
        pipe.delete(f"{FLOW_KEY_PREFIX}{flow_id}")
        await pipe.execute()

    embed = embedding.decode(flow.get("embed"))
    if embed:
        # Handed to the embedding page by postMessage, to its exact origin.
        response = templates.TemplateResponse(
            request, "embed_complete.html", {"embed": embed, "code": code, "state": flow["state"]}
        )
        response.headers["Content-Security-Policy"] = embedding.frame_ancestors(embed["origin"])
        response.headers["Cache-Control"] = "no-store"
        return response

    params = {"code": code, "iss": settings.issuer_url}
    if flow["state"]:
        params["state"] = flow["state"]
    return RedirectResponse(f"{flow['redirect_uri']}?{urlencode(params)}", status_code=303)
