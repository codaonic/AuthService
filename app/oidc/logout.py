from urllib.parse import urlencode

from joserfc import jwt
from joserfc.errors import JoseError

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import client_ip, log_event
from app.auth.sessions import get_session_user, sign_out_app
from app.config import get_settings
from app.db.models import Client
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.oidc.clients import get_and_validate_client
from app.oidc.id_token import public_sid
from app.oidc.keys import get_key_manager
from app.oidc.refresh import refresh_token_owner, revoke_all_refresh_tokens_for_user

router = APIRouter()


def _client_from_id_token(token: str) -> str | None:
    """The app an ID token from this service was issued to. Its signature
    and issuer are checked; its expiry isn't, since apps often log out with
    an old one."""
    settings = get_settings()
    try:
        verified = jwt.decode(token, get_key_manager().public_key_set(), algorithms=[settings.signing_key_algorithm])
    except (JoseError, ValueError):
        return None
    claims = verified.claims
    if claims.get("iss") != settings.issuer_url or "at_hash" not in claims or not isinstance(claims.get("aud"), str):
        return None
    return claims["aud"]

# Both forms sign the user out of ONE application: their sign-in to every
# other application, including ones in the same login group, is left alone.
# Neither renders a page -- the application owns its own logout UI.


async def _sign_out(db: AsyncSession, redis: Redis, request: Request, user_id: str, client_id: str, via: str) -> None:
    await sign_out_app(redis, user_id, client_id)
    # The app's own server is told by back-channel logout -- unless it was
    # that server asking (via="backchannel"), which already knows.
    session_id = request.cookies.get(get_settings().session_cookie_name)
    await revoke_all_refresh_tokens_for_user(
        db, redis, user_id, client_id=client_id, sid=public_sid(session_id), notify_apps=via != "backchannel"
    )
    log_event("logout", client_id=client_id, user_id=user_id, via=via, ip=client_ip(request))


@router.get("/logout")
async def logout_redirect(
    request: Request,
    client_id: str | None = None,
    post_logout_redirect_uri: str | None = None,
    state: str | None = None,
    # OIDC RP-initiated logout: an app may name itself with an ID token it
    # was given (expired is fine) instead of its client_id.
    id_token_hint: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Browser form: send the user's browser here, identified by the
    service's own session cookie, and it comes straight back to
    `post_logout_redirect_uri`.
    """
    settings = get_settings()
    hinted = _client_from_id_token(id_token_hint) if id_token_hint else None
    if id_token_hint and hinted is None:
        raise HTTPException(400, "invalid_request: id_token_hint is not an ID token from this service")
    if client_id and hinted and client_id != hinted:
        raise HTTPException(400, "invalid_request: id_token_hint was issued to a different client")
    client_id = client_id or hinted
    if not client_id:
        raise HTTPException(400, "invalid_request: client_id or id_token_hint is required")
    # Looked up directly rather than via _load_client -- a disabled
    # application must still be able to sign its users out.
    client = (await db.execute(select(Client).where(Client.client_id == client_id))).scalar_one_or_none()
    if client is None:
        raise HTTPException(400, "invalid_client")
    if post_logout_redirect_uri and post_logout_redirect_uri not in (client.post_logout_redirect_uris or []):
        raise HTTPException(400, "invalid_request: post_logout_redirect_uri is not registered for this client")

    user_id = await get_session_user(redis, request.cookies.get(settings.session_cookie_name))
    if user_id is not None:
        await _sign_out(db, redis, request, user_id, client.client_id, via="browser")

    if post_logout_redirect_uri:
        target = post_logout_redirect_uri
        if state:
            separator = "&" if "?" in target else "?"
            target = f"{target}{separator}{urlencode({'state': state})}"
        return RedirectResponse(target, status_code=303)
    return {"status": "signed_out", "client_id": client.client_id}


@router.post("/logout")
async def logout_backchannel(
    request: Request,
    client_id: str = Form(...),
    refresh_token: str = Form(...),
    client_secret: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Server-to-server form: the application's backend calls this directly,
    authenticating as itself and naming the user by the refresh token it holds.
    """
    await get_and_validate_client(db, client_id, client_secret, request)
    user_id = await refresh_token_owner(redis, refresh_token, client_id)
    if user_id is None:
        raise HTTPException(400, "invalid_grant")
    await _sign_out(db, redis, request, user_id, client_id, via="backchannel")
    return {"status": "signed_out", "client_id": client_id}
