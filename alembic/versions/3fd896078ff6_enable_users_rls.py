"""enable row-level security on users

Revision ID: 3fd896078ff6
Revises: 19efaadb0694
Create Date: 2026-09-27 00:00:00.000000

Adds a Postgres Row-Level Security policy to `users`, scoped by the session
variables `app.tenant_pool_id` / `app.rls_bypass` (see app/db/tenant.py).
This is a defense-in-depth backstop for the pool-based multi-tenancy this
service already does at the application layer -- it doesn't replace the
`user_pool_id` filters in application code, it means a query that forgets
one returns zero rows instead of another tenant's data.

`FORCE ROW LEVEL SECURITY` is required because the app connects as the same
role that owns these tables, and Postgres exempts table owners from RLS by
default.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3fd896078ff6'
down_revision: Union[str, Sequence[str], None] = '19efaadb0694'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON users
        USING (
            current_setting('app.rls_bypass', true) = 'on'
            OR user_pool_id::text = current_setting('app.tenant_pool_id', true)
        )
        WITH CHECK (
            current_setting('app.rls_bypass', true) = 'on'
            OR user_pool_id::text = current_setting('app.tenant_pool_id', true)
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
