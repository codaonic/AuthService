import time
import uuid

from joserfc import jwt

from app.config import get_settings
from app.oidc.keys import get_key_manager


def mint_access_token(sub: str, aud: str, client_id: str, scope: str) -> tuple[str, int]:
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
    token = jwt.encode(
        {"alg": settings.signing_key_algorithm, "kid": kid},
        payload,
        key,
        algorithms=[settings.signing_key_algorithm],
    )
    return token, ttl
