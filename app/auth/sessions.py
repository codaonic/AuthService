import secrets

from redis.asyncio import Redis

from app.config import get_settings

SESSION_KEY_PREFIX = "session:"
USER_SESSIONS_PREFIX = "user_sessions:"


async def create_session(redis: Redis, user_id: str) -> str:
    settings = get_settings()
    session_id = secrets.token_urlsafe(32)
    await redis.set(f"{SESSION_KEY_PREFIX}{session_id}", user_id, ex=settings.session_ttl_seconds)
    await redis.sadd(f"{USER_SESSIONS_PREFIX}{user_id}", session_id)
    await redis.expire(f"{USER_SESSIONS_PREFIX}{user_id}", settings.session_ttl_seconds)
    return session_id


async def get_session_user(redis: Redis, session_id: str | None) -> str | None:
    if not session_id:
        return None
    return await redis.get(f"{SESSION_KEY_PREFIX}{session_id}")


async def delete_session(redis: Redis, session_id: str) -> None:
    await redis.delete(f"{SESSION_KEY_PREFIX}{session_id}")


async def revoke_all_sessions_for_user(redis: Redis, user_id: str) -> None:
    """Log the user out everywhere -- used after a password reset."""
    key = f"{USER_SESSIONS_PREFIX}{user_id}"
    session_ids = await redis.smembers(key)
    if session_ids:
        await redis.delete(*(f"{SESSION_KEY_PREFIX}{sid}" for sid in session_ids))
    await redis.delete(key)
