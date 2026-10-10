import secrets
import time

from redis.asyncio import Redis

from app.config import get_settings

SESSION_KEY_PREFIX = "session:"
USER_SESSIONS_PREFIX = "user_sessions:"
SESSION_APPS_PREFIX = "session_apps:"
APP_LOGOUT_PREFIX = "app_logout:"


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


async def sign_in(
    redis: Redis,
    existing_session_id: str | None,
    user_id: str,
    client_id: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Record a fresh authentication through one application, reusing the
    browser's existing session when it already belongs to this user.
    """
    settings = get_settings()
    now = str(round(time.time()))
    if existing_session_id and await get_session_user(redis, existing_session_id) == user_id:
        session_id = existing_session_id
        await redis.hset(f"{SESSION_KEY_PREFIX}{session_id}", "last_auth", now)
        await redis.expire(f"{SESSION_KEY_PREFIX}{session_id}", settings.session_ttl_seconds)
        await redis.sadd(f"{USER_SESSIONS_PREFIX}{user_id}", session_id)
        await redis.expire(f"{USER_SESSIONS_PREFIX}{user_id}", settings.session_ttl_seconds)
    else:
        session_id = await create_session(redis, user_id, ip=ip, user_agent=user_agent)
    await redis.hset(f"{SESSION_APPS_PREFIX}{session_id}", client_id, now)
    await redis.expire(f"{SESSION_APPS_PREFIX}{session_id}", settings.session_ttl_seconds)
    return session_id


async def app_auth_time(redis: Redis, session_id: str | None, client_id: str) -> int | None:
    """When this session last authenticated for `client_id`, or None if it is
    signed out of that application (or the session is gone). An application
    the session has never touched inherits the session's last sign-in, which
    is what makes single sign-on across a login group work.
    """
    if not session_id:
        return None
    session = await redis.hgetall(f"{SESSION_KEY_PREFIX}{session_id}")
    if not session:
        return None
    own = await redis.hget(f"{SESSION_APPS_PREFIX}{session_id}", client_id)
    signed_out_at = await redis.hget(f"{APP_LOGOUT_PREFIX}{session['user_id']}", client_id)
    if signed_out_at:
        # After a logout only a sign-in made through this application itself
        # counts -- signing in to a sibling app must not quietly undo it.
        if not own or int(own) <= int(signed_out_at):
            return None
        return int(own)
    return int(own or session.get("last_auth") or session.get("created_at") or 0)


async def sign_out_app(redis: Redis, user_id: str, client_id: str) -> None:
    """Sign a user out of one application only -- their sign-in to every
    other application, including ones in the same login group, is unaffected.
    """
    key = f"{APP_LOGOUT_PREFIX}{user_id}"
    await redis.hset(key, client_id, str(round(time.time())))
    # Kept for the longest any sign-in can last, so a sign-in that predates
    # the logout can never come back to life.
    await redis.expire(key, get_settings().refresh_token_ttl_seconds)


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
