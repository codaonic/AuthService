"""Signing people out of apps the moment they lose access to them.

Refresh and /introspect re-check access anyway, but that only bites at the
next refresh. These run right after an admin change, so the person is
signed out of the affected app now: refresh tokens revoked, access tokens
cut off, and the app told by back-channel logout. Other apps are untouched.
"""

import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.teams import has_app_access
from app.db.models import Client, RefreshToken, User
from app.db.tenant import bypass_tenant_rls
from app.oidc.refresh import revoke_all_refresh_tokens_for_user


async def _still_allowed(db: AsyncSession, user: User, client: Client) -> bool:
    from app.oidc.authorize import _user_can_access_client

    if not await _user_can_access_client(db, user, client):
        return False
    return not client.restrict_access or await has_app_access(db, client.client_id, user.id)


async def _enforce(db: AsyncSession, redis: Redis, query) -> None:
    await bypass_tenant_rls(db)
    pairs = (await db.execute(query.where(RefreshToken.revoked_at.is_(None)).distinct())).all()
    users: dict[str, User | None] = {}
    clients: dict[str, Client | None] = {}
    for user_id, client_id in pairs:
        if user_id not in users:
            users[user_id] = await db.get(User, uuid.UUID(user_id))
        if client_id not in clients:
            clients[client_id] = (await db.execute(select(Client).where(Client.client_id == client_id))).scalar_one_or_none()
        user, client = users[user_id], clients[client_id]
        if user is None or client is None or not await _still_allowed(db, user, client):
            await revoke_all_refresh_tokens_for_user(db, redis, user_id, client_id)


async def enforce_access(db: AsyncSession, redis: Redis, user_ids: set[uuid.UUID]) -> None:
    """After a change to these people (e.g. a team): every app they're signed
    in to that they may no longer use."""
    if user_ids:
        await _enforce(
            db,
            redis,
            select(RefreshToken.user_id, RefreshToken.client_id).where(RefreshToken.user_id.in_([str(u) for u in user_ids])),
        )


async def enforce_app(db: AsyncSession, redis: Redis, client_id: str) -> None:
    """After a change to an app (restricted, or moved out of a login group):
    everyone signed in to it who may no longer use it."""
    await _enforce(
        db, redis, select(RefreshToken.user_id, RefreshToken.client_id).where(RefreshToken.client_id == client_id)
    )
