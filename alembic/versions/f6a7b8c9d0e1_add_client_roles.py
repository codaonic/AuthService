"""add client roles

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("clients", sa.Column("roles_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("clients", "roles_enabled", server_default=None)
    op.add_column(
        "clients", sa.Column("allow_signup_role_selection", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.alter_column("clients", "allow_signup_role_selection", server_default=None)

    # A role is just its name -- (client_id, name) is the identity, no
    # separate surrogate id.
    op.create_table(
        "client_roles",
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.client_id"]),
        sa.PrimaryKeyConstraint("client_id", "name"),
    )

    op.create_table(
        "user_role_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["client_id", "role"], ["client_roles.client_id", "client_roles.name"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "client_id", "role", name="uq_user_role_assignments"),
    )
    op.create_index("ix_user_role_assignments_user_id", "user_role_assignments", ["user_id"])
    op.create_index("ix_user_role_assignments_client_id", "user_role_assignments", ["client_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_user_role_assignments_client_id", table_name="user_role_assignments")
    op.drop_index("ix_user_role_assignments_user_id", table_name="user_role_assignments")
    op.drop_table("user_role_assignments")
    op.drop_table("client_roles")
    op.drop_column("clients", "allow_signup_role_selection")
    op.drop_column("clients", "roles_enabled")
