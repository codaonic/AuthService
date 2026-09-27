import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls
from app.oidc.keys import get_key_manager

router = APIRouter()


def _get_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "missing_or_invalid_authorization_header")
    return auth_header.removeprefix("Bearer ").strip()


@router.get("/userinfo")
async def userinfo(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    token = _get_bearer_token(request)

    try:
        header = jwt.get_unverified_header(token)
        jwks = get_key_manager().jwks()
        key = next((k for k in jwks["keys"] if k["kid"] == header.get("kid")), None)
        if key is None:
            raise HTTPException(401, "invalid_token")
        claims = jwt.decode(
            token,
            key,
            algorithms=[settings.signing_key_algorithm],
            issuer=settings.issuer,
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(401, "invalid_token") from exc

    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, "invalid_token: not a user token") from exc

    # Authorized by the verified JWT signature, not pool membership -- there's
    # no client/pool in scope on this bearer-token-only endpoint.
    await bypass_tenant_rls(db)
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(401, "invalid_token")

    return {"sub": str(user.id), "email": user.email}
