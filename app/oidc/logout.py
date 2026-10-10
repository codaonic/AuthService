from urllib.parse import urlencode

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
from app.oidc.refresh import refresh_token_owner, revoke_all_refresh_tokens_for_user

router = APIRouter()

# Both forms sign the user out of ONE application: their sign-in to every
# other application, including ones in the same login group, is left alone.
# Neither renders a page -- the application owns its own logout UI.


async def _sign_out(db: AsyncSession, redis: Redis, request: Request, user_id: str, client_id: str, via: str) -> None:
    await sign_out_app(redis, user_id, client_id)
    await revoke_all_refresh_tokens_for_user(db, redis, user_id, client_id=client_id)
    log_event("logout", client_id=client_id, user_id=user_id, via=via, ip=client_ip(request))


@router.get("/logout")
async def logout_redirect(
    request: Request,
    client_id: str,
    post_logout_redirect_uri: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Browser form: send the user's browser here, identified by the
    service's own session cookie, and it comes straight back to
    `post_logout_redirect_uri`.
    """
    settings = get_settings()
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
