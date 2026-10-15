from redis.asyncio import Redis

from app.config import get_settings

LOCKOUT_KEY_PREFIX = "login_lockout:"


def _key(scope: str, identifier: str) -> str:
    return f"{LOCKOUT_KEY_PREFIX}{scope}:{identifier.strip().lower()}"


async def is_locked(redis: Redis, scope: str, identifier: str) -> bool:
    """Too many recent wrong passwords or 2FA codes for this identifier.

    Keyed by the identifier the attacker types (an email), not by whether an
    account exists, so a locked response reveals nothing about which emails
    are registered. Per-IP rate limits can be spread across many addresses;
    this cap is what stops a distributed guessing run against one account.
    """
    count = await redis.get(_key(scope, identifier))
    return count is not None and int(count) >= get_settings().login_max_failures


async def record_failure(redis: Redis, scope: str, identifier: str) -> None:
    key = _key(scope, identifier)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, get_settings().login_lockout_seconds)


async def clear_failures(redis: Redis, scope: str, identifier: str) -> None:
    await redis.delete(_key(scope, identifier))
