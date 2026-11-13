from redis.asyncio import Redis

from app.config import get_settings

LOCKOUT_KEY_PREFIX = "login_lockout:"


def _key(scope: str, identifier: str) -> str:
    return f"{LOCKOUT_KEY_PREFIX}{scope}:{identifier.strip().lower()}"


async def is_locked(redis: Redis, scope: str, identifier: str, limit: int | None = None) -> bool:
    """Too many recent wrong passwords or 2FA codes for this identifier.

    Keyed by the identifier the attacker types (an email), not by whether an
    account exists, so a locked response reveals nothing about which emails
    are registered. Per-IP rate limits can be spread across many addresses;
    this cap is what stops a distributed guessing run against one account.
    """
    count = await redis.get(_key(scope, identifier))
    return count is not None and int(count) >= (limit or get_settings().login_max_failures)


async def record_failure(redis: Redis, scope: str, identifier: str) -> None:
    key = _key(scope, identifier)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, get_settings().login_lockout_seconds)


async def clear_failures(redis: Redis, scope: str, identifier: str) -> None:
    await redis.delete(_key(scope, identifier))


# Someone typing a stranger's email wrong must not lock that person out of
# everywhere. So the usual cap counts per email *and* address; only a much
# larger number of failures for one email (a guessing run spread over many
# addresses) locks the email for everyone.
EMAIL_WIDE_FACTOR = 5


def _pair(email: str, ip: str | None) -> str:
    return f"{email.strip().lower()}|{ip or '-'}"


async def login_locked(redis: Redis, email: str, ip: str | None) -> bool:
    return await is_locked(redis, "user", _pair(email, ip)) or await is_locked(
        redis, "user", email, limit=get_settings().login_max_failures * EMAIL_WIDE_FACTOR
    )


async def record_login_failure(redis: Redis, email: str, ip: str | None) -> None:
    await record_failure(redis, "user", _pair(email, ip))
    await record_failure(redis, "user", email)


async def clear_login_failures(redis: Redis, email: str, ip: str | None) -> None:
    await clear_failures(redis, "user", _pair(email, ip))
    await clear_failures(redis, "user", email)
