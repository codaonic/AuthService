import time
import uuid

from joserfc import jwt

from app.config import get_settings
from app.oidc.keys import get_key_manager


def mint_access_token(
    sub: str, aud: str, client_id: str, scope: str, email_verified: bool | None = None,
    roles: list[str] | None = None,
    roles_claim: str = "roles",
) -> tuple[str, int]:
    """`email_verified` is set for tokens issued to a person, left out for
    client_credentials tokens, which have no person behind them."""
    settings = get_settings()
    kid, key = get_key_manager().signing_key()
    ttl = settings.access_token_ttl_seconds
    now = int(time.time())
    payload = {
        "sub": sub,
        "aud": aud,
        "iss": settings.issuer_url,
        "client_id": client_id,
        "scope": scope,
        "iat": now,
        "exp": now + ttl,
        "jti": str(uuid.uuid4()),
    }
    if email_verified is not None:
        payload["email_verified"] = email_verified
    if roles is not None:
        # Only for apps that turned roles on: an API can then decide from the
        # token alone. Never roles from other apps.
        payload[roles_claim] = roles
    token = jwt.encode(
        {"alg": settings.signing_key_algorithm, "kid": kid, "typ": "at+jwt"},
        payload,
        key,
        algorithms=[settings.signing_key_algorithm],
    )
    return token, ttl
