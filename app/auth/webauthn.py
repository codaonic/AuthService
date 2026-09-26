from urllib.parse import urlparse

from redis.asyncio import Redis
from webauthn.helpers import bytes_to_base64url
from webauthn import base64url_to_bytes

from app.config import get_settings

REG_CHALLENGE_PREFIX = "webauthn_reg_challenge:"
AUTH_CHALLENGE_PREFIX = "webauthn_auth_challenge:"


def relying_party() -> tuple[str, str]:
    """Derive the WebAuthn RP ID and expected origin from ISSUER.

    RP ID must be the deployment's real domain (no scheme/port); origin is
    the full scheme+host+port the browser sees. Both come from the same
    config value the rest of the app already trusts for cookie/HTTPS logic,
    so there's nothing new to configure.
    """
    parsed = urlparse(get_settings().issuer)
    return parsed.hostname or "localhost", f"{parsed.scheme}://{parsed.netloc}"


async def store_registration_challenge(redis: Redis, user_id: str, challenge: bytes) -> None:
    settings = get_settings()
    await redis.set(
        f"{REG_CHALLENGE_PREFIX}{user_id}", bytes_to_base64url(challenge), ex=settings.webauthn_challenge_ttl_seconds
    )


async def pop_registration_challenge(redis: Redis, user_id: str) -> bytes | None:
    key = f"{REG_CHALLENGE_PREFIX}{user_id}"
    value = await redis.get(key)
    if value is None:
        return None
    await redis.delete(key)
    return base64url_to_bytes(value)


async def store_authentication_challenge(redis: Redis, flow_id: str, challenge: bytes) -> None:
    settings = get_settings()
    await redis.set(
        f"{AUTH_CHALLENGE_PREFIX}{flow_id}",
        bytes_to_base64url(challenge),
        ex=settings.webauthn_challenge_ttl_seconds,
    )


async def pop_authentication_challenge(redis: Redis, flow_id: str) -> bytes | None:
    key = f"{AUTH_CHALLENGE_PREFIX}{flow_id}"
    value = await redis.get(key)
    if value is None:
        return None
    await redis.delete(key)
    return base64url_to_bytes(value)
