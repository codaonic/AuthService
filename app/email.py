import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

logger = logging.getLogger("app.email")


async def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()

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


async def send_password_reset_email(to: str, token: str) -> None:
    """Best-effort: a delivery failure shouldn't surface to the caller --
    the response is always the same regardless of whether the email exists
    or the send succeeded, to avoid leaking either fact.
    """
    settings = get_settings()
    link = f"{settings.issuer.rstrip('/')}/reset-password?token={token}"
    try:
        await send_email(
            to,
            "Reset your password",
            f"Someone requested a password reset for this account.\n\n"
            f"Reset it here (expires in {settings.password_reset_ttl_seconds // 60} minutes):\n{link}\n\n"
            f"If you didn't request this, you can ignore this email.",
        )
    except Exception:
        logger.exception("Failed to send password reset email to %s", to)


async def send_verification_email(to: str, token: str) -> None:
    """Best-effort -- see send_password_reset_email. Verification is
    informational here, not a login gate, so a failed send must not break
    signup or the resend flow.
    """
    settings = get_settings()
    link = f"{settings.issuer.rstrip('/')}/verify-email?token={token}"
    try:
        await send_email(
            to,
            "Verify your email",
            f"Confirm your email address here (expires in "
            f"{settings.email_verification_ttl_seconds // 3600} hours):\n{link}",
        )
    except Exception:
        logger.exception("Failed to send verification email to %s", to)
