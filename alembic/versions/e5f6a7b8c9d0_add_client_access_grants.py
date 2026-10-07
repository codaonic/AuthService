"""add client access grants

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("clients", sa.Column("restrict_access", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("clients", "restrict_access", server_default=None)

    op.create_table(
        "client_access_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.client_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "user_id", name="uq_client_access_grants_client_user"),
    )
    op.create_index("ix_client_access_grants_client_id", "client_access_grants", ["client_id"])
    op.create_index("ix_client_access_grants_user_id", "client_access_grants", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_client_access_grants_user_id", table_name="client_access_grants")
    op.drop_index("ix_client_access_grants_client_id", table_name="client_access_grants")
    op.drop_table("client_access_grants")
    op.drop_column("clients", "restrict_access")
