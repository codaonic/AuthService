import hashlib
import secrets

from redis.asyncio import Redis

from app.config import get_settings

PASSWORD_RESET_PREFIX = "password_reset:"
EMAIL_VERIFY_PREFIX = "email_verify:"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_password_reset_token(redis: Redis, user_id: str) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    await redis.set(
        f"{PASSWORD_RESET_PREFIX}{_hash_token(token)}", user_id, ex=settings.password_reset_ttl_seconds
    )
    return token


async def consume_password_reset_token(redis: Redis, token: str) -> str | None:
    key = f"{PASSWORD_RESET_PREFIX}{_hash_token(token)}"
    user_id = await redis.get(key)
    if user_id is not None:
        await redis.delete(key)
    return user_id


async def create_email_verification_token(redis: Redis, user_id: str) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    await redis.set(
        f"{EMAIL_VERIFY_PREFIX}{_hash_token(token)}", user_id, ex=settings.email_verification_ttl_seconds
    )
    return token


async def consume_email_verification_token(redis: Redis, token: str) -> str | None:
    key = f"{EMAIL_VERIFY_PREFIX}{_hash_token(token)}"
    user_id = await redis.get(key)
    if user_id is not None:
        await redis.delete(key)
    return user_id
