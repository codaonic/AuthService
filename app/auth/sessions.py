import secrets
import time

from redis.asyncio import Redis

from app.config import get_settings

SESSION_KEY_PREFIX = "session:"
USER_SESSIONS_PREFIX = "user_sessions:"


async def create_session(
    redis: Redis, user_id: str, *, ip: str | None = None, user_agent: str | None = None
) -> str:
    settings = get_settings()
    session_id = secrets.token_urlsafe(32)
    key = f"{SESSION_KEY_PREFIX}{session_id}"
    await redis.hset(
        key,
        mapping={
            "user_id": user_id,
            "created_at": str(round(time.time())),
            "ip": ip or "",
            "user_agent": (user_agent or "")[:200],
        },
    )
    await redis.expire(key, settings.session_ttl_seconds)
    await redis.sadd(f"{USER_SESSIONS_PREFIX}{user_id}", session_id)
    await redis.expire(f"{USER_SESSIONS_PREFIX}{user_id}", settings.session_ttl_seconds)
    return session_id


async def get_session_user(redis: Redis, session_id: str | None) -> str | None:
    if not session_id:
        return None
    return await redis.hget(f"{SESSION_KEY_PREFIX}{session_id}", "user_id")


async def delete_session(redis: Redis, session_id: str) -> None:
    await redis.delete(f"{SESSION_KEY_PREFIX}{session_id}")


async def revoke_all_sessions_for_user(redis: Redis, user_id: str) -> None:
    """Log the user out everywhere -- used after a password reset."""
    key = f"{USER_SESSIONS_PREFIX}{user_id}"
    session_ids = await redis.smembers(key)
    if session_ids:
        await redis.delete(*(f"{SESSION_KEY_PREFIX}{sid}" for sid in session_ids))
    await redis.delete(key)


async def list_sessions_for_user(redis: Redis, user_id: str) -> list[dict]:
    """Active sessions for the account page, newest first -- lets someone spot
    and revoke a single sign-in (e.g. a lost device) instead of only being
    able to sign out everywhere.
    """
    key = f"{USER_SESSIONS_PREFIX}{user_id}"
    session_ids = await redis.smembers(key)
    sessions = []
    stale = []
    for session_id in session_ids:
        data = await redis.hgetall(f"{SESSION_KEY_PREFIX}{session_id}")
        if not data:
            stale.append(session_id)
            continue
        sessions.append({"id": session_id, **data})
    if stale:
        await redis.srem(key, *stale)
    sessions.sort(key=lambda s: s.get("created_at", "0"), reverse=True)
    return sessions


async def revoke_other_sessions(redis: Redis, user_id: str, keep_session_id: str) -> None:
    """Sign out every other session for this user, keeping the one making the
    request alive -- used by the "sign out other devices" account action.
    """
    key = f"{USER_SESSIONS_PREFIX}{user_id}"
    session_ids = await redis.smembers(key)
    others = [sid for sid in session_ids if sid != keep_session_id]
    if others:
        await redis.delete(*(f"{SESSION_KEY_PREFIX}{sid}" for sid in others))
        await redis.srem(key, *others)


async def revoke_session(redis: Redis, session_id: str, user_id: str) -> bool:
    """Revoke one session, but only if it actually belongs to `user_id` --
    stops a user from revoking someone else's session by guessing an id.
    """
    key = f"{SESSION_KEY_PREFIX}{session_id}"
    owner = await redis.hget(key, "user_id")
    if owner != user_id:
        return False
    await redis.delete(key)
    await redis.srem(f"{USER_SESSIONS_PREFIX}{user_id}", session_id)
    return True
