import logging
from email.message import EmailMessage

import aiosmtplib

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


async def send_password_reset_email(to: str, token: str) -> str:
    """Send a password reset link to the given email address.

    Best-effort: a delivery failure shouldn't surface to the caller --
    the response is always the same regardless of whether the email exists
    or the send succeeded, to avoid leaking either fact.

    If SMTP setup is not done (or if delivery fails), the reset link is
    printed to the terminal so developers/admins can still reset passwords
    in local or development environments.
    """
    settings = get_settings()
    link = f"{settings.issuer.rstrip('/')}/reset-password?token={token}"

    if not is_smtp_configured():
        terminal_msg = (
            f"\n"
            f"======================================================================\n"
            f"[PASSWORD RESET] SMTP is not configured.\n"
            f"Target email : {to}\n"
            f"Reset link   : {link}\n"
            f"======================================================================\n"
        )
        print(terminal_msg, flush=True)
        logger.warning(
            "[PASSWORD RESET] SMTP is not configured. Password reset link for %s: %s",
            to,
            link,
        )
        return link

    try:
        await send_email(
            to,
            "Reset your password",
            f"Someone requested a password reset for this account.\n\n"
            f"Reset it here (expires in {settings.password_reset_ttl_seconds // 60} minutes):\n{link}\n\n"
            f"If you didn't request this, you can ignore this email.",
        )
    except Exception:
        terminal_msg = (
            f"\n"
            f"======================================================================\n"
            f"[PASSWORD RESET] Failed to send email via SMTP ({settings.smtp_host}:{settings.smtp_port}).\n"
            f"Target email : {to}\n"
            f"Reset link   : {link}\n"
            f"======================================================================\n"
        )
        print(terminal_msg, flush=True)
        logger.exception("Failed to send password reset email to %s. Reset link: %s", to, link)

    return link


async def send_verification_email(to: str, token: str) -> str:
    """Best-effort -- see send_password_reset_email. Verification is
    informational here, not a login gate, so a failed send must not break
    signup or the resend flow.

    If SMTP setup is not done (or if delivery fails), the verification link
    is printed to the terminal so developers/admins can still verify accounts
    in local or development environments.
    """
    settings = get_settings()
    link = f"{settings.issuer.rstrip('/')}/verify-email?token={token}"

    if not is_smtp_configured():
        terminal_msg = (
            f"\n"
            f"======================================================================\n"
            f"[EMAIL VERIFICATION] SMTP is not configured.\n"
            f"Target email      : {to}\n"
            f"Verification link : {link}\n"
            f"======================================================================\n"
        )
        print(terminal_msg, flush=True)
        logger.warning(
            "[EMAIL VERIFICATION] SMTP is not configured. Verification link for %s: %s",
            to,
            link,
        )
        return link

    try:
        await send_email(
            to,
            "Verify your email",
            f"Confirm your email address here (expires in "
            f"{settings.email_verification_ttl_seconds // 3600} hours):\n{link}",
        )
    except Exception:
        terminal_msg = (
            f"\n"
            f"======================================================================\n"
            f"[EMAIL VERIFICATION] Failed to send email via SMTP ({settings.smtp_host}:{settings.smtp_port}).\n"
            f"Target email      : {to}\n"
            f"Verification link : {link}\n"
            f"======================================================================\n"
        )
        print(terminal_msg, flush=True)
        logger.exception("Failed to send verification email to %s. Verification link: %s", to, link)

    return link
