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
from app.auth.identity import accounts_for_email, normalize_email
from app.auth.teams import has_app_access
from app.auth.lockout import clear_login_failures, login_locked, record_login_failure
from app.auth.passwords import burn_password_check, hash_password_async, verify_password_async
from app.auth.sessions import app_auth_time, get_session_user, sign_in
from app.config import get_settings
from app.db.contacts import upsert_contact
from app.db.models import Client, ClientAccessGrant, ClientRole, Consent, Resource, TeamMember, User, UserRoleAssignment
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls
from app.email import send_verification_email
from app.middleware.rate_limit import limiter
from app.oidc import embed as embedding
from app.oidc.cimd import is_cimd_client_id, resolve_cimd_client
from app.oidc.id_token import public_sid
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
    matches = await accounts_for_email(db, email, client)
    if len(matches) <= 1:
        return matches[0] if matches else None
    # Two accounts for one person in one login group (made before this was
    # prevented). Only the one registered with this very app is
    # unambiguous; otherwise refuse rather than guess whose account it is.
    own = [u for u in matches if u.client_id == client.client_id]
    if len(own) == 1:
        return own[0]
    log_event(
        "duplicate_account_in_login_group",
        level=logging.WARNING,
        client_id=client.client_id,
        email=normalize_email(email),
        count=len(matches),
    )
    return None


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
    """On a restricted app's list, personally or through a team."""
    return await has_app_access(db, client_id, user_id)


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


SUPPORTED_PROMPTS = {"none", "login", "consent", "select_account"}


def _resolve_requested_scope(requested: str, client: Client) -> str:
    """`openid` is always allowed: it only asks for an ID token, which says
    who signed in. Everything else must be in the app's allowed scope."""
    words = requested.split()
    rest = " ".join(w for w in words if w != "openid")
    if "openid" not in words:
        return resolve_scope(requested, client.allowed_scope)
    if not rest:
        return "openid"
    return " ".join(["openid", resolve_scope(rest, client.allowed_scope)])


async def _flow_error(request: Request, redis: Redis, flow_id: str, error: str):
    """End a sign-in by telling the app why, without showing anything --
    what prompt=none needs (login_required, consent_required, ...)."""
    settings = get_settings()
    flow = await redis.hgetall(f"{FLOW_KEY_PREFIX}{flow_id}")
    await redis.delete(f"{FLOW_KEY_PREFIX}{flow_id}")
    embed = embedding.decode(flow.get("embed"))
    if embed:
        response = templates.TemplateResponse(
            request, "embed_complete.html", {"embed": embed, "code": "", "error": error, "state": flow.get("state", "")}
        )
        response.headers["Content-Security-Policy"] = embedding.frame_ancestors(embed["origin"])
        response.headers["Cache-Control"] = "no-store"
        return response
    params = {"error": error, "iss": settings.issuer_url}
    if flow.get("state"):
        params["state"] = flow["state"]
    separator = "&" if "?" in flow["redirect_uri"] else "?"
    return RedirectResponse(f"{flow['redirect_uri']}{separator}{urlencode(params)}", status_code=303)


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
    # OpenID Connect: nonce goes back in the ID token; prompt=none checks for
    # an existing sign-in without showing anything; prompt=login and max_age
    # ask for the password again; login_hint fills in the email.
    nonce: str | None = None,
    prompt: str = "",
    max_age: int | None = None,
    login_hint: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()

    prompts = set(prompt.split())
    if prompts - SUPPORTED_PROMPTS or ("none" in prompts and len(prompts) > 1):
        raise HTTPException(400, "invalid_request: unsupported prompt value")
    if max_age is not None and max_age < 0:
        raise HTTPException(400, "invalid_request: max_age must not be negative")
    if nonce is not None and len(nonce) > 512:
        raise HTTPException(400, "invalid_request: nonce is too long")

    if response_type != "code":
        raise HTTPException(400, "unsupported_response_type")
    if code_challenge_method not in SUPPORTED_CHALLENGE_METHODS:
        raise HTTPException(400, "invalid_request: code_challenge_method must be S256")

    client = await _load_client(db, client_id)
    embed = ""
    if response_mode == "web_message":
        if not origin or origin not in embedding.allowed_embed_origins(client) or not embedding.valid_frame_id(frame_id):
            raise HTTPException(400, "invalid_request: this page may not embed sign-in for this application")
        embed = embedding.encode(origin, frame_id, embedding.parse_appearance(appearance))
        redirect_uri = origin
    elif response_mode != "query":
        raise HTTPException(400, "unsupported_response_mode")
    elif redirect_uri is None or redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "invalid_redirect_uri")
    scope = _resolve_requested_scope(scope, client)

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
        "nonce": nonce or "",
        "prompt": " ".join(sorted(prompts)),
        "login_hint": (login_hint or "")[:320],
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
        # The app asked for a fresh password: prompt=login, or a sign-in no
        # older than max_age seconds.
        elif "login" in prompts or (max_age is not None and (max_age == 0 or time.time() - auth_time > max_age)):
            user_id = None

    if "none" in prompts:
        # Nothing may be shown: either an existing sign-in carries straight
        # on, or the app is told why it can't.
        if user_id is None:
            return await _flow_error(request, redis, flow_id, "login_required")
        return await _continue_flow(request, db, redis, flow_id, user_id, auth_time=auth_time, session_id=session_id)

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
                "email": flow["login_hint"],
                "error": None,
            },
        )

    return await _continue_flow(request, db, redis, flow_id, user_id, auth_time=auth_time, session_id=session_id)


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

    if await login_locked(redis, email, client_ip(request)):
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
        await record_login_failure(redis, email, client_ip(request))
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
            await record_login_failure(redis, email, client_ip(request))
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

    await clear_login_failures(redis, email, client_ip(request))
    log_event("login_success", client_id=client.client_id, user_id=str(user.id), ip=client_ip(request))
    session_id = await sign_in(
        redis,
        request.cookies.get(settings.session_cookie_name),
        str(user.id),
        client.client_id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response = await _continue_flow(request, db, redis, flow_id, str(user.id), session_id=session_id)
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

    email = normalize_email(email)
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
    if client.signup_team_id:
        # The app's signup team: its access and roles from the first sign-in.
        db.add(TeamMember(team_id=client.signup_team_id, user_id=user.id))
    await db.commit()
    await db.refresh(user)
    log_event("signup_success", client_id=client.client_id, user_id=str(user.id), ip=client_ip(request))

    # A failed send shouldn't block account creation. For an app that
    # requires a verified email, _continue_flow below holds them on the
    # "check your email" page until they've clicked the link.
    await _send_verification_once(redis, user)

    session_id = await sign_in(
        redis,
        request.cookies.get(settings.session_cookie_name),
        str(user.id),
        client.client_id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response = await _continue_flow(request, db, redis, flow_id, str(user.id), session_id=session_id)
    response.set_cookie(
        settings.session_cookie_name,
        session_id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )
    return response


# How long a sign-in waits on the "check your email" page, and how often
# that page can send another link.
VERIFY_WAIT_SECONDS = 30 * 60
VERIFY_RESEND_SECONDS = 60


async def _send_verification_once(redis: Redis, user: User) -> bool:
    """Sends a verification link unless one went out in the last minute.
    Returns whether it sent one."""
    if not await redis.set(f"verify_sent:{user.id}", "1", nx=True, ex=VERIFY_RESEND_SECONDS):
        return False
    token = await create_email_verification_token(redis, str(user.id))
    await send_verification_email(redis, user.email, token)
    return True


async def _verified_email_required(db: AsyncSession, client: Client, resource_id: str | None) -> bool:
    """Required by the application, or by the API or MCP server the token is
    for -- the second covers apps that register themselves as they connect."""
    if client.require_verified_email:
        return True
    if not resource_id:
        return False
    return bool(
        await db.scalar(select(Resource.require_verified_email).where(Resource.resource_id == resource_id))
    )


async def _check_email_page(request: Request, redis: Redis, flow_id: str, client: Client, user: User, resent: bool | None = None):
    return await _page(
        redis,
        request,
        "check_email.html",
        {"flow_id": flow_id, "client_id": client.client_id, **_branding(client), "email": user.email, "resent": resent},
    )


async def _continue_flow(
    request: Request,
    db: AsyncSession,
    redis: Redis,
    flow_id: str,
    user_id: str,
    auth_time: int | None = None,
    session_id: str | None = None,
):
    """`session_id` is the browser session this sign-in belongs to (its
    hashed form becomes the ID token's `sid`). `auth_time` is when the user actually authenticated -- now, unless an
    existing session is being reused. It rides along on the flow so the
    tokens issued at the end can't outlive the application's sign-in timeout.
    """
    flow = await redis.hgetall(f"{FLOW_KEY_PREFIX}{flow_id}")
    if not flow:
        raise HTTPException(400, "invalid_request: expired or unknown flow")
    flow["auth_time"] = str(auth_time or round(time.time()))
    await redis.hset(f"{FLOW_KEY_PREFIX}{flow_id}", "auth_time", flow["auth_time"])
    if session_id:
        flow["sid"] = public_sid(session_id)
        await redis.hset(f"{FLOW_KEY_PREFIX}{flow_id}", "sid", flow["sid"])
    silent = "none" in flow.get("prompt", "").split()

    client = await _load_client(db, flow["client_id"])
    requested_scopes = set(flow["scope"].split()) if flow["scope"] else set()

    if client.restrict_access and not await _has_client_access(db, client.client_id, user_id):
        log_event(
            "access_denied_not_assigned",
            level=logging.WARNING,
            client_id=client.client_id,
            user_id=user_id,
        )
        if silent:
            return await _flow_error(request, redis, flow_id, "access_denied")
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

    if await _verified_email_required(db, client, flow.get("resource")):
        await bypass_tenant_rls(db)
        user = await db.get(User, uuid.UUID(user_id))
        if user is not None and not user.email_verified and silent:
            return await _flow_error(request, redis, flow_id, "interaction_required")
        if user is not None and not user.email_verified:
            # Every way in (signup, password, passkey, an existing session)
            # comes through here, so none of them skips this. The flow waits
            # longer than usual, since the email can take a while.
            key = f"{FLOW_KEY_PREFIX}{flow_id}"
            async with redis.pipeline(transaction=True) as pipe:
                await pipe.hset(key, "pending_user_id", user_id).expire(key, VERIFY_WAIT_SECONDS).execute()
            await _send_verification_once(redis, user)
            log_event("email_verification_required", client_id=client.client_id, user_id=user_id, email=user.email)
            return await _check_email_page(request, redis, flow_id, client, user)

    result = await db.execute(
        select(Consent).where(
            Consent.user_id == uuid.UUID(user_id), Consent.client_id == client.client_id
        )
    )
    consent = result.scalar_one_or_none()
    force_consent = "consent" in flow.get("prompt", "").split() and not flow.get("embed")
    if force_consent or consent is None or not requested_scopes.issubset(set(consent.scopes)):
        if silent and not flow.get("embed"):
            return await _flow_error(request, redis, flow_id, "consent_required")
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
                "nonce": flow.get("nonce", ""),
                "sid": flow.get("sid") or public_sid(request.cookies.get(settings.session_cookie_name)) or "",
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


# --- Waiting for a verified email ---


async def _pending(db: AsyncSession, redis: Redis, flow_id: str) -> tuple[dict, User | None]:
    """The sign-in waiting on the "check your email" page, and its person."""
    flow = await redis.hgetall(f"{FLOW_KEY_PREFIX}{flow_id}")
    if not flow.get("pending_user_id"):
        return flow, None
    await bypass_tenant_rls(db)
    return flow, await db.get(User, uuid.UUID(flow["pending_user_id"]))


@router.get("/verify-email/status")
async def verification_status(flow_id: str, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    """Asked every few seconds by the "check your email" page, so it can
    carry on by itself once the link has been clicked (in any tab or device)."""
    _, user = await _pending(db, redis, flow_id)
    if user is None:
        return {"verified": False, "expired": True}
    return {"verified": user.email_verified, "expired": False}


@router.post("/verify-email/continue")
async def continue_after_verification(
    request: Request,
    flow_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    flow, user = await _pending(db, redis, flow_id)
    if user is None:
        raise HTTPException(400, "invalid_request: this sign-in has expired -- start again from the application")
    client = await _load_client(db, flow["client_id"])
    if not user.email_verified:
        return await _check_email_page(request, redis, flow_id, client, user)
    await redis.hdel(f"{FLOW_KEY_PREFIX}{flow_id}", "pending_user_id")
    auth_time = int(flow["auth_time"]) if flow.get("auth_time") else None
    return await _continue_flow(request, db, redis, flow_id, str(user.id), auth_time=auth_time)


@router.post("/verify-email/resend")
@limiter.limit(get_settings().rate_limit_signup)
async def resend_while_waiting(
    request: Request,
    flow_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    flow, user = await _pending(db, redis, flow_id)
    if user is None:
        raise HTTPException(400, "invalid_request: this sign-in has expired -- start again from the application")
    client = await _load_client(db, flow["client_id"])
    return await _check_email_page(request, redis, flow_id, client, user, resent=await _send_verification_once(redis, user))

