"""add email_verified to users

Revision ID: 52813a37d057
Revises: ee110671bd92
Create Date: 2026-09-27 02:48:43.421520

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52813a37d057'
down_revision: Union[str, Sequence[str], None] = 'ee110671bd92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "email_verified")
