from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contact


async def upsert_contact(
    db: AsyncSession,
    *,
    email: str,
    pool_name: str | None = None,
    app_name: str | None = None,
) -> None:
    """Insert a contact row for this email if one doesn't exist yet.

    Intentionally a no-op on duplicate email — first_seen_at and the
    originating pool/app are set once and never overwritten.
    """
    existing = await db.execute(select(Contact).where(Contact.email == email))
    if existing.scalar_one_or_none() is not None:
        return
    db.add(Contact(email=email, first_pool=pool_name, first_app=app_name))
