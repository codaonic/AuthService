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

from app.auth.sessions import create_session, get_session_user
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
from app.oidc.authorize import _continue_flow, _get_flow_client

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _current_user(request: Request, db: AsyncSession, redis: Redis) -> User | None:
    settings = get_settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    user_id = await get_session_user(redis, session_id)
    if user_id is None:
        return None
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

    result = await db.execute(
        select(User).where(User.email == email, User.user_pool_id == client.user_pool_id)
    )
    user = result.scalar_one_or_none()

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
    if user is None or user.user_pool_id != client.user_pool_id:
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


def _credential_id_from_json(credential_json: str) -> str:
    return json.loads(credential_json)["id"]


# --- Managing passkeys from the account page (requires an existing session) ---


@router.get("/account")
async def account_page(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    user = await _current_user(request, db, redis)
    if user is None:
        return templates.TemplateResponse(request, "account.html", {"user": None, "credentials": []})

    result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id).order_by(WebAuthnCredential.created_at)
    )
    credentials = result.scalars().all()
    return templates.TemplateResponse(request, "account.html", {"user": user, "credentials": credentials})


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
