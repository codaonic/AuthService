import secrets
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.mfa import verify_totp
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import create_session, get_session_user
from app.config import get_settings
from app.db.models import Client, Consent, User
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.middleware.rate_limit import limiter
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


async def _load_client(db: AsyncSession, client_id: str) -> Client:
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(400, "invalid_client")
    return client


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
        # A session cookie from a different, isolated user pool must not
        # grant access here -- fall through to login/signup for this client.
        user = await db.get(User, uuid.UUID(user_id))
        if user is None or user.user_pool_id != client.user_pool_id:
            user_id = None

    if user_id is None:
        return templates.TemplateResponse(
            request, "login.html", {"flow_id": flow_id, "client_id": client_id, "error": None}
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
        request, "login.html", {"flow_id": flow_id, "client_id": client.client_id, "error": None}
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

    result = await db.execute(
        select(User).where(User.email == email, User.user_pool_id == client.user_pool_id)
    )
    user = result.scalar_one_or_none()

    if user is None or user.status != "active" or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"flow_id": flow_id, "client_id": client.client_id, "error": "Invalid email or password"},
            status_code=401,
        )

    if user.mfa_secret and not verify_totp(user.mfa_secret, totp_code):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"flow_id": flow_id, "client_id": client.client_id, "error": "Invalid or missing MFA code"},
            status_code=401,
        )

    session_id = await create_session(redis, str(user.id))
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
    return templates.TemplateResponse(
        request, "signup.html", {"flow_id": flow_id, "client_id": client.client_id, "error": None}
    )


@router.post("/signup")
async def signup(
    request: Request,
    flow_id: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    settings = get_settings()
    client = await _get_flow_client(db, redis, flow_id)

    def error(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"flow_id": flow_id, "client_id": client.client_id, "error": message, "email": email},
            status_code=status_code,
        )

    if password != confirm_password:
        return error("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        return error(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    existing = await db.execute(
        select(User).where(User.email == email, User.user_pool_id == client.user_pool_id)
    )
    if existing.scalar_one_or_none() is not None:
        return error("An account with that email already exists")

    user = User(user_pool_id=client.user_pool_id, email=email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    session_id = await create_session(redis, str(user.id))
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

    params = {"code": code, "iss": settings.issuer}
    if flow["state"]:
        params["state"] = flow["state"]
    return RedirectResponse(f"{flow['redirect_uri']}?{urlencode(params)}", status_code=303)
