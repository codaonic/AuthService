import json
import logging
import secrets
import time
from email.message import EmailMessage

import aiosmtplib
from redis.asyncio import Redis

from app.audit import log_event
from app.config import get_settings

logger = logging.getLogger("app.email")


def is_smtp_configured() -> bool:
    """Return True if an SMTP host is configured."""
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_host.strip())


async def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()

    if not is_smtp_configured():
        raise RuntimeError("SMTP is not configured (smtp_host is empty or unset)")

    message = EmailMessage()
    message["From"] = f"{settings.email_from_name} <{settings.email_from_address}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=settings.smtp_use_tls,
    )
    logger.info("Sent email to %s: %s", to, subject)


# When an email can't go out (no SMTP set up, or sending failed), its link is
# held here for the admin console's Dashboard instead of being printed to the
# terminal, where it would also end up in container logs. Each one lives in
# Redis only until the link itself expires, and the link never goes into the
# Activity log: a stored reset link is a working way into that account.
OUTBOX_PREFIX = "email_outbox:"
OUTBOX_INDEX = "email_outbox_index"


async def _hold_link(redis: Redis, kind: str, to: str, link: str, ttl_seconds: int, reason: str) -> None:
    held_id = secrets.token_urlsafe(12)
    now = time.time()
    record = {
        "id": held_id,
        "kind": kind,
        "email": to,
        "link": link,
        "reason": reason,
        "created": round(now, 3),
        "expires": round(now + ttl_seconds, 3),
    }
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(f"{OUTBOX_PREFIX}{held_id}", json.dumps(record), ex=ttl_seconds)
        pipe.zadd(OUTBOX_INDEX, {held_id: now + ttl_seconds})
        await pipe.execute()
    log_event("email_link_held", level=logging.WARNING, kind=kind, email=to, reason=reason)
    logger.warning("Couldn't email the %s link for %s (%s); it's on the admin console's Dashboard", kind, to, reason)


async def held_links(redis: Redis) -> list[dict]:
    """Links waiting to be passed on by an admin, newest first."""
    await redis.zremrangebyscore(OUTBOX_INDEX, "-inf", time.time())
    ids = await redis.zrange(OUTBOX_INDEX, 0, -1)
    if not ids:
        return []
    records = [json.loads(r) for r in await redis.mget([f"{OUTBOX_PREFIX}{i}" for i in ids]) if r]
    return sorted(records, key=lambda r: r["created"], reverse=True)


async def dismiss_held_link(redis: Redis, held_id: str) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(f"{OUTBOX_PREFIX}{held_id}")
        pipe.zrem(OUTBOX_INDEX, held_id)
        await pipe.execute()


async def _send_or_hold(redis: Redis, kind: str, to: str, link: str, ttl_seconds: int, subject: str, body: str) -> bool:
    """True if the email went out, False if its link is held for the console."""
    if not is_smtp_configured():
        await _hold_link(redis, kind, to, link, ttl_seconds, "smtp_not_configured")
        return False
    try:
        await send_email(to, subject, body)
    except Exception:
        logger.exception("Failed to send the %s email to %s", kind, to)
        await _hold_link(redis, kind, to, link, ttl_seconds, "smtp_failed")
        return False
    return True


async def send_password_reset_email(redis: Redis, to: str, token: str) -> bool:
    """Send a password reset link to the given email address.

    Best-effort: a delivery failure shouldn't surface to the caller --
    the response is always the same regardless of whether the email exists
    or the send succeeded, to avoid leaking either fact. A link that can't
    be emailed is held for the admin console instead (see _hold_link).
    Returns whether it was emailed, for the console's own "send reset".
    """
    settings = get_settings()
    link = f"{settings.issuer.rstrip('/')}/reset-password?token={token}"
    return await _send_or_hold(
        redis,
        "password_reset",
        to,
        link,
        settings.password_reset_ttl_seconds,
        "Reset your password",
        f"Someone requested a password reset for this account.\n\n"
        f"Reset it here (expires in {settings.password_reset_ttl_seconds // 60} minutes):\n{link}\n\n"
        f"If you didn't request this, you can ignore this email.",
    )


async def send_verification_email(redis: Redis, to: str, token: str) -> bool:
    """Best-effort -- see send_password_reset_email. Verification is
    informational here, not a login gate, so a failed send must not break
    signup or the resend flow.
    """
    settings = get_settings()
    link = f"{settings.issuer.rstrip('/')}/verify-email?token={token}"
    return await _send_or_hold(
        redis,
        "email_verification",
        to,
        link,
        settings.email_verification_ttl_seconds,
        "Verify your email",
        f"Confirm your email address here (expires in "
        f"{settings.email_verification_ttl_seconds // 3600} hours):\n{link}",
    )
