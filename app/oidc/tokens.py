import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import get_settings
from app.oidc.keys import get_key_manager


def mint_access_token(sub: str, aud: str, client_id: str, scope: str) -> tuple[str, int]:
    settings = get_settings()
    kid, private_pem = get_key_manager().signing_key()
    ttl = settings.access_token_ttl_seconds
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "aud": aud,
        "iss": settings.issuer,
        "client_id": client_id,
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        payload,
        private_pem.decode(),
        algorithm=settings.signing_key_algorithm,
        headers={"kid": kid},
    )
    return token, ttl
