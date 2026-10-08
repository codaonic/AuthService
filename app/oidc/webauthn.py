import json
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement

from app.audit import client_ip, log_event
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import (
    create_session,
    get_session_user,
    list_sessions_for_user,
    revoke_other_sessions,
    revoke_session,
)
from app.auth.webauthn import (
    pop_authentication_challenge,
    pop_registration_challenge,
    relying_party,
    store_authentication_challenge,
    store_registration_challenge,
)
from app.config import get_settings
from app.db.models import User, WebAuthnCredential
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls
from app.oidc.authorize import (
    _continue_flow,
    _find_user_for_client,
    _get_flow_client,
    _user_can_access_client,
    asset_version,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["asset_version"] = asset_version


async def _current_user(request: Request, db: AsyncSession, redis: Redis) -> User | None:
    settings = get_settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    user_id = await get_session_user(redis, session_id)
    if user_id is None:
        return None
    # Authorized by the session cookie, not pool membership -- /account is
    # reached directly, with no client/pool in scope.
    await bypass_tenant_rls(db)
    return await db.get(User, uuid.UUID(user_id))


# --- Login with a passkey (alternative to password, within an existing /authorize flow) ---


@router.post("/webauthn/login/options")
async def webauthn_login_options(
    request: Request,
    flow_id: str = Form(...),
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    await bypass_tenant_rls(db)

    user = await _find_user_for_client(db, email, client)

    credentials: list[WebAuthnCredential] = []
    if user is not None:
        cred_result = await db.execute(
            select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
        )
        credentials = list(cred_result.scalars().all())

    if not credentials:
        # Same message whether the account doesn't exist or just has no passkey --
        # matches the existing login form's generic "Invalid email or password".
        raise HTTPException(400, "No passkey is registered for this account")

    rp_id, _ = relying_party()
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=c.credential_id, transports=c.transports) for c in credentials
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    await store_authentication_challenge(redis, flow_id, options.challenge)

    return Response(content=options_to_json(options), media_type="application/json")


@router.post("/webauthn/login/verify")
async def webauthn_login_verify(
    request: Request,
    flow_id: str = Form(...),
    credential: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await _get_flow_client(db, redis, flow_id)
    await bypass_tenant_rls(db)
    settings = get_settings()

    challenge = await pop_authentication_challenge(redis, flow_id)
    if challenge is None:
        raise HTTPException(400, "This passkey request has expired -- try again")

    raw_id = base64url_to_bytes(_credential_id_from_json(credential))
    result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id == raw_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise HTTPException(400, "Unknown passkey")

    user = await db.get(User, stored.user_id)
    if user is None or not await _user_can_access_client(db, user, client) or user.status != "active":
        raise HTTPException(400, "Unknown passkey")

    rp_id, origin = relying_party()
    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=False,
        )
    except Exception as exc:
        raise HTTPException(400, "Passkey verification failed") from exc

    stored.sign_count = verification.new_sign_count
    await db.commit()
    log_event("webauthn_login_success", client_id=client.client_id, user_id=str(user.id), ip=client_ip(request))

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


def _credential_id_from_json(credential_json: str) -> str:
    return json.loads(credential_json)["id"]


# --- Managing passkeys from the account page (requires an existing session) ---


MIN_PASSWORD_LENGTH = 8


async def _account_context(request: Request, db: AsyncSession, redis: Redis, user: User, **extra) -> dict:
    settings = get_settings()
    result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id).order_by(WebAuthnCredential.created_at)
    )
    credentials = result.scalars().all()
    sessions = await list_sessions_for_user(redis, str(user.id))
    current_session_id = request.cookies.get(settings.session_cookie_name)
    return {
        "user": user,
        "credentials": credentials,
        "sessions": sessions,
        "current_session_id": current_session_id,
        "error": None,
        "success": None,
        **extra,
    }


@router.get("/account")
async def account_page(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    user = await _current_user(request, db, redis)
    if user is None:
        return templates.TemplateResponse(request, "account.html", {"user": None, "credentials": []})

    return templates.TemplateResponse(request, "account.html", await _account_context(request, db, redis, user))


@router.post("/account/password")
async def change_account_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user = await _current_user(request, db, redis)
    if user is None:
        raise HTTPException(401, "Not signed in")

    async def error(message: str, status_code: int = 400):
        ctx = await _account_context(request, db, redis, user, error=message)
        return templates.TemplateResponse(request, "account.html", ctx, status_code=status_code)

    if not verify_password(current_password, user.password_hash):
        return await error("Current password is incorrect")
    if new_password != confirm_password:
        return await error("New passwords do not match")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return await error(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    user.password_hash = hash_password(new_password)
    await db.commit()
    log_event("password_changed", user_id=str(user.id), ip=client_ip(request))

    settings = get_settings()
    current_session_id = request.cookies.get(settings.session_cookie_name)
    if current_session_id:
        await revoke_other_sessions(redis, str(user.id), current_session_id)

    ctx = await _account_context(request, db, redis, user, success="Password updated")
    return templates.TemplateResponse(request, "account.html", ctx)


@router.post("/account/sessions/{session_id}/revoke")
async def revoke_account_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user = await _current_user(request, db, redis)
    if user is None:
        raise HTTPException(401, "Not signed in")

    settings = get_settings()
    current_session_id = request.cookies.get(settings.session_cookie_name)
    revoked = await revoke_session(redis, session_id, str(user.id))
    if revoked:
        log_event("session_revoked", user_id=str(user.id), ip=client_ip(request))

    if session_id == current_session_id:
        response = RedirectResponse("/account", status_code=303)
        response.delete_cookie(settings.session_cookie_name)
        return response

    return RedirectResponse("/account", status_code=303)


@router.post("/account/sessions/revoke-others")
async def revoke_other_account_sessions(
    request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
):
    user = await _current_user(request, db, redis)
    if user is None:
        raise HTTPException(401, "Not signed in")

    settings = get_settings()
    current_session_id = request.cookies.get(settings.session_cookie_name)
    if current_session_id:
        await revoke_other_sessions(redis, str(user.id), current_session_id)
        log_event("sessions_revoked_others", user_id=str(user.id), ip=client_ip(request))

    return RedirectResponse("/account", status_code=303)


@router.post("/account/webauthn/register/options")
async def webauthn_register_options(
    request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
):
    user = await _current_user(request, db, redis)
    if user is None:
        raise HTTPException(401, "Not signed in")

    result = await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))
    existing = result.scalars().all()

    rp_id, _ = relying_party()
    settings = get_settings()
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=user.id.bytes,
        user_name=user.email,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing],
    )
    await store_registration_challenge(redis, str(user.id), options.challenge)

    return Response(content=options_to_json(options), media_type="application/json")


@router.post("/account/webauthn/register/verify")
async def webauthn_register_verify(
    request: Request,
    credential: str = Form(...),
    nickname: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user = await _current_user(request, db, redis)
    if user is None:
        raise HTTPException(401, "Not signed in")

    challenge = await pop_registration_challenge(redis, str(user.id))
    if challenge is None:
        raise HTTPException(400, "This registration request has expired -- try again")

    rp_id, origin = relying_party()
    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=False,
        )
    except Exception as exc:
        raise HTTPException(400, "Passkey registration failed") from exc

    db.add(
        WebAuthnCredential(
            user_id=user.id,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            nickname=nickname or None,
        )
    )
    await db.commit()
    log_event("webauthn_registered", user_id=str(user.id), ip=client_ip(request))

    return RedirectResponse("/account", status_code=303)


@router.post("/account/webauthn/{credential_id}/delete")
async def webauthn_delete_credential(
    credential_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    user = await _current_user(request, db, redis)
    if user is None:
        raise HTTPException(401, "Not signed in")

    cred = await db.get(WebAuthnCredential, uuid.UUID(credential_id))
    if cred is not None and cred.user_id == user.id:
        await db.delete(cred)
        await db.commit()

    return RedirectResponse("/account", status_code=303)
