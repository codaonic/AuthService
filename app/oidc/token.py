import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import client_ip, log_event
from app.config import get_settings
from app.db.models import User
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import set_tenant_pool
from app.middleware.rate_limit import limiter
from app.oidc.clients import get_and_validate_client
from app.oidc.pkce import verify_pkce
from app.oidc.refresh import issue_refresh_token, validate_and_rotate_refresh_token
from app.oidc.scope import resolve_scope
from app.oidc.tokens import mint_access_token

router = APIRouter()

CODE_KEY_PREFIX = "code:"


@router.post("/token")
@limiter.limit(get_settings().rate_limit_token)
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    code_verifier: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    refresh_token: str | None = Form(None),
    client_id: str = Form(...),
    client_secret: str | None = Form(None),
    resource: str | None = Form(None),
    scope: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    client = await get_and_validate_client(db, client_id, client_secret, request)
    if grant_type not in client.grant_types:
        raise HTTPException(400, "unauthorized_client")

    if grant_type == "authorization_code":
        if not code:
            raise HTTPException(400, "invalid_request")
        key = f"{CODE_KEY_PREFIX}{code}"
        auth_code = await redis.hgetall(key)
        if not auth_code or auth_code["client_id"] != client_id:
            raise HTTPException(400, "invalid_grant")
        await redis.delete(key)

        if redirect_uri and redirect_uri != auth_code["redirect_uri"]:
            raise HTTPException(400, "invalid_grant")
        if not verify_pkce(auth_code["code_challenge"], code_verifier):
            raise HTTPException(400, "invalid_grant")

        subject = auth_code["user_id"]
        resource = auth_code["resource"]
        scope = auth_code["scope"]

    elif grant_type == "client_credentials":
        if not resource:
            raise HTTPException(400, "invalid_request: resource is required")
        subject = client_id
        scope = resolve_scope(scope, client.allowed_scope)

    elif grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(400, "invalid_request")
        rt = await validate_and_rotate_refresh_token(db, redis, refresh_token, client_id)
        subject = rt["user_id"]
        resource = resource or rt["resource"]
        scope = resolve_scope(scope, rt["scope"])

    else:
        raise HTTPException(400, "unsupported_grant_type")

    if grant_type != "client_credentials":
        # A user disabled after issuing this code/refresh token shouldn't be
        # able to keep minting access tokens from it. set_tenant_pool is
        # called here, not earlier, since the refresh_token branch above
        # commits (rotating the token), which resets the transaction-scoped
        # RLS context set before it.
        await set_tenant_pool(db, client.user_pool_id)
        user = await db.get(User, uuid.UUID(subject))
        if user is None or user.status != "active":
            raise HTTPException(400, "invalid_grant")

    access_token, expires_in = mint_access_token(
        sub=subject, aud=resource, client_id=client_id, scope=scope
    )
    log_event(
        "token_issued",
        grant_type=grant_type,
        client_id=client_id,
        subject=subject,
        resource=resource,
        scope=scope,
        ip=client_ip(request),
    )

    response = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": scope,
    }

    if grant_type != "client_credentials":
        response["refresh_token"] = await issue_refresh_token(
            db, redis, subject, client_id, resource, scope=scope
        )

    return response
