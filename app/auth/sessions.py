import secrets

from redis.asyncio import Redis

from app.config import get_settings

SESSION_KEY_PREFIX = "session:"


async def create_session(redis: Redis, user_id: str) -> str:
    settings = get_settings()
    session_id = secrets.token_urlsafe(32)
    await redis.set(f"{SESSION_KEY_PREFIX}{session_id}", user_id, ex=settings.session_ttl_seconds)
    return session_id


async def get_session_user(redis: Redis, session_id: str | None) -> str | None:
    if not session_id:
        return None
    return await redis.get(f"{SESSION_KEY_PREFIX}{session_id}")


async def delete_session(redis: Redis, session_id: str) -> None:
    await redis.delete(f"{SESSION_KEY_PREFIX}{session_id}")
