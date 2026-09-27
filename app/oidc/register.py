import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_event
from app.auth.passwords import hash_password
from app.db.models import Client
from app.db.pools import DEFAULT_POOL_NAME, get_or_create_pool
from app.db.session import get_db

router = APIRouter()

ALLOWED_GRANT_TYPES = {"authorization_code", "refresh_token", "client_credentials"}


class ClientRegistrationRequest(BaseModel):
    redirect_uris: list[str] = Field(default_factory=list)
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    token_endpoint_auth_method: str = "client_secret_post"  # or "none" for public clients
    application_type: str = "web"
    scope: str = ""


@router.post("/register", status_code=201)
async def register_client(
    body: ClientRegistrationRequest,
    db: AsyncSession = Depends(get_db),
):
    if not set(body.grant_types).issubset(ALLOWED_GRANT_TYPES):
        raise HTTPException(400, "invalid_client_metadata: unsupported grant_types")

    is_public = body.token_endpoint_auth_method == "none"
    if not is_public and "authorization_code" in body.grant_types and not body.redirect_uris:
        raise HTTPException(400, "invalid_redirect_uri")

    client_id = secrets.token_urlsafe(16)
    client_secret = None if is_public else secrets.token_urlsafe(32)
    pool = await get_or_create_pool(db, DEFAULT_POOL_NAME)

    client = Client(
        user_pool_id=pool.id,
        client_id=client_id,
        client_secret_hash=None if client_secret is None else hash_password(client_secret),
        client_type="public" if is_public else "confidential",
        redirect_uris=body.redirect_uris,
        grant_types=body.grant_types,
        allowed_scope=body.scope,
        registration_method="dcr",
        application_type=body.application_type,
    )
    db.add(client)
    await db.commit()
    log_event(
        "client_registered",
        client_id=client_id,
        registration_method="dcr",
        client_type=client.client_type,
        grant_types=body.grant_types,
    )

    response = {
        "client_id": client_id,
        "redirect_uris": body.redirect_uris,
        "grant_types": body.grant_types,
        "token_endpoint_auth_method": body.token_endpoint_auth_method,
        "application_type": body.application_type,
    }
    if client_secret is not None:
        response["client_secret"] = client_secret
    return response
