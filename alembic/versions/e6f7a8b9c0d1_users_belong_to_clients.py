"""users belong to clients instead of pools

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-10-08 00:00:00.000000

Changes:
- users.user_pool_id  →  users.client_id  (FK to clients.client_id)
- Unique constraint uq_users_pool_email  →  uq_users_client_email
- clients.user_pool_id becomes nullable (pool is now optional grouping)
- RLS policy updated to check client_id instead of user_pool_id
- Orphaned users (in pools with no clients) are deleted with cascade
- Orphaned pools with no clients are deleted
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------ #
    # 1. Add client_id column (nullable for now so we can populate it)    #
    # ------------------------------------------------------------------ #
    op.add_column(
        "users",
        sa.Column("client_id", sa.String(), nullable=True),
    )

    # ------------------------------------------------------------------ #
    # 2. Delete users whose pool has no clients (orphaned users).         #
    #    Cascade to dependent tables first.                               #
    # ------------------------------------------------------------------ #
    orphaned_user_ids = conn.execute(
        sa.text(
            """
            SELECT u.id
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM clients c WHERE c.user_pool_id = u.user_pool_id
            )
            """
        )
    ).fetchall()

    if orphaned_user_ids:
        ids = tuple(str(r[0]) for r in orphaned_user_ids)
        # Use ANY with an array cast for clean parameterised deletion
        conn.execute(
            sa.text(
                "DELETE FROM user_role_assignments WHERE user_id = ANY(:ids)"
            ),
            {"ids": list(ids)},
        )
        conn.execute(
            sa.text(
                "DELETE FROM client_access_grants WHERE user_id = ANY(:ids)"
            ),
            {"ids": list(ids)},
        )
        conn.execute(
            sa.text("DELETE FROM consents WHERE user_id = ANY(:ids)"),
            {"ids": list(ids)},
        )
        conn.execute(
            sa.text(
                "DELETE FROM webauthn_credentials WHERE user_id = ANY(:ids)"
            ),
            {"ids": list(ids)},
        )
        conn.execute(
            sa.text(
                "DELETE FROM refresh_tokens WHERE user_id = ANY(:ids)"
            ),
            {"ids": list(ids)},
        )
        conn.execute(
            sa.text("DELETE FROM users WHERE id = ANY(:ids)"),
            {"ids": list(ids)},
        )

    # ------------------------------------------------------------------ #
    # 3. Populate client_id from the pool→first-client mapping.          #
    #    For each user, pick the "first" client in the same pool          #
    #    (ordered by client_id for determinism).                          #
    # ------------------------------------------------------------------ #
    conn.execute(
        sa.text(
            """
            UPDATE users u
            SET client_id = sub.client_id
            FROM (
                SELECT DISTINCT ON (c.user_pool_id)
                       c.client_id,
                       c.user_pool_id
                FROM clients c
                WHERE c.user_pool_id IS NOT NULL
                ORDER BY c.user_pool_id, c.client_id
            ) sub
            WHERE u.user_pool_id = sub.user_pool_id
            """
        )
    )

    # ------------------------------------------------------------------ #
    # 4. Make client_id NOT NULL and add FK + unique constraint.          #
    # ------------------------------------------------------------------ #
    op.alter_column("users", "client_id", nullable=False)

    op.create_foreign_key(
        "fk_users_client_id",
        "users",
        "clients",
        ["client_id"],
        ["client_id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("uq_users_pool_email", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_client_email", "users", ["client_id", "email"]
    )

    op.create_index("ix_users_client_id", "users", ["client_id"])

    # ------------------------------------------------------------------ #
    # 5. Drop old RLS policy (it references user_pool_id — must go       #
    #    before the column is dropped).                                   #
    # ------------------------------------------------------------------ #
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")

    # ------------------------------------------------------------------ #
    # 6. Drop users.user_pool_id.                                         #
    # ------------------------------------------------------------------ #
    op.drop_index("ix_users_user_pool_id", table_name="users")
    op.drop_column("users", "user_pool_id")

    # ------------------------------------------------------------------ #
    # 7. Make clients.user_pool_id nullable.                              #
    # ------------------------------------------------------------------ #
    op.alter_column("clients", "user_pool_id", nullable=True)

    # ------------------------------------------------------------------ #
    # 8. Delete orphaned pools (no clients assigned).                     #
    # ------------------------------------------------------------------ #
    conn.execute(
        sa.text(
            """
            DELETE FROM user_pools
            WHERE id NOT IN (
                SELECT DISTINCT user_pool_id
                FROM clients
                WHERE user_pool_id IS NOT NULL
            )
            """
        )
    )

    # ------------------------------------------------------------------ #
    # 9. Create new RLS policy checking client_id.                        #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE POLICY tenant_isolation ON users
        USING (
            current_setting('app.rls_bypass', true) = 'on'
            OR client_id = current_setting('app.tenant_client_id', true)
        )
        WITH CHECK (
            current_setting('app.rls_bypass', true) = 'on'
            OR client_id = current_setting('app.tenant_client_id', true)
        )
        """
    )


def downgrade() -> None:
    # Restore old RLS policy
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")
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

    op.alter_column("clients", "user_pool_id", nullable=False)

    op.add_column(
        "users",
        sa.Column(
            "user_pool_id",
            sa.Uuid(),
            sa.ForeignKey("user_pools.id"),
            nullable=True,
        ),
    )

    # Repopulate user_pool_id from clients
    op.get_bind().execute(
        sa.text(
            """
            UPDATE users u
            SET user_pool_id = c.user_pool_id
            FROM clients c
            WHERE c.client_id = u.client_id
            """
        )
    )

    op.alter_column("users", "user_pool_id", nullable=False)
    op.create_index("ix_users_user_pool_id", "users", ["user_pool_id"])

    op.drop_index("ix_users_client_id", table_name="users")
    op.drop_constraint("uq_users_client_email", "users", type_="unique")
    op.drop_constraint("fk_users_client_id", "users", type_="foreignkey")
    op.create_unique_constraint(
        "uq_users_pool_email", "users", ["user_pool_id", "email"]
    )
    op.drop_column("users", "client_id")
