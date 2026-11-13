"""Who an email address belongs to, inside a login group.

One person has one account per login group: every app in the group shares
it. Emails are compared without regard to case or surrounding spaces, so
"Bo@Example.com " and "bo@example.com" are the same person.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _same_email(email: str):
    return func.lower(func.trim(User.email)) == normalize_email(email)


def _apps_sharing_users(client: Client):
    """The client_ids whose users can sign in to `client`: its whole login
    group, or just itself when it isn't in one."""
    if client.user_pool_id is None:
        return [client.client_id]
    return select(Client.client_id).where(Client.user_pool_id == client.user_pool_id)


async def accounts_for_email(db: AsyncSession, email: str, client: Client) -> list[User]:
    result = await db.execute(select(User).where(_same_email(email), User.client_id.in_(_apps_sharing_users(client))))
    return list(result.scalars().all())


async def email_taken(db: AsyncSession, email: str, client: Client, except_user: uuid.UUID | None = None) -> bool:
    """Would an account with this email clash with one the app's login group
    already has?"""
    return any(u.id != except_user for u in await accounts_for_email(db, email, client))


async def emails_clashing_on_join(db: AsyncSession, client: Client, pool_id: uuid.UUID) -> list[str]:
    """Emails that exist both in `client` and in another app of the login
    group it would join. Joining with any of these would leave one person
    with two accounts and no way to tell which one a sign-in means."""
    mine = select(func.lower(func.trim(User.email))).where(User.client_id == client.client_id)
    others = select(Client.client_id).where(Client.user_pool_id == pool_id, Client.client_id != client.client_id)
    result = await db.execute(
        select(func.lower(func.trim(User.email)))
        .where(User.client_id.in_(others), func.lower(func.trim(User.email)).in_(mine))
        .distinct()
        .order_by(func.lower(func.trim(User.email)))
    )
    return [email for (email,) in result.all()]
