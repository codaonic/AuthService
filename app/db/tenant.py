import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Postgres session variables read by the Row-Level Security policy on
# `users` (see alembic/versions/*_enable_users_rls.py). `SET LOCAL` is
# transaction-scoped and resets automatically at commit/rollback -- using a
# plain `SET` here would leak one request's tenant into whatever unrelated
# request next checks out the same pooled connection.
_POOL_VAR = "app.tenant_pool_id"
_CLIENT_VAR = "app.tenant_client_id"
_BYPASS_VAR = "app.rls_bypass"


def _is_postgres(db: AsyncSession) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


async def set_tenant_client(db: AsyncSession, client_id: str) -> None:
    """Scope the rest of this transaction's `users` queries to one client.

    Used for direct (non-pool) user lookups in the OIDC flow -- standalone
    apps where a user can only belong to one specific client.
    """
    if not _is_postgres(db):
        return
    if not isinstance(client_id, str):
        raise TypeError(f"client_id must be a str, got {type(client_id)!r}")
    await db.execute(text(f"SET LOCAL {_CLIENT_VAR} = '{client_id}'"))


async def set_tenant_pool(db: AsyncSession, pool_id: uuid.UUID) -> None:
    """Scope the rest of this transaction's `users` queries to one pool.

    A database-level backstop, not the primary access control -- every query
    should still filter by `user_pool_id` itself. This just means a query
    that forgets to returns zero rows instead of another tenant's data.
    No-op outside Postgres (the test suite runs on SQLite, where RLS
    doesn't exist).
    """
    if not _is_postgres(db):
        return
    if not isinstance(pool_id, uuid.UUID):
        raise TypeError(f"pool_id must be a uuid.UUID, got {type(pool_id)!r}")
    await db.execute(text(f"SET LOCAL {_POOL_VAR} = '{pool_id}'"))


async def bypass_tenant_rls(db: AsyncSession) -> None:
    """Lift the per-pool restriction for this transaction.

    For contexts that legitimately span every pool: the admin console, the
    CLI, and point lookups already authorized by something other than pool
    membership (a signed JWT, a session cookie, a single-use email token) --
    those fetch one specific row proven by that other credential, so a pool
    filter wouldn't add protection, only a way to break them.
    """
    if not _is_postgres(db):
        return
    await db.execute(text(f"SET LOCAL {_BYPASS_VAR} = 'on'"))
