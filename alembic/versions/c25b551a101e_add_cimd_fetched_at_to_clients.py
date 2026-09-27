"""add cimd_fetched_at to clients

Revision ID: c25b551a101e
Revises: a7011a5ff68e
Create Date: 2026-09-27 12:14:04.377965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c25b551a101e'
down_revision: Union[str, Sequence[str], None] = 'a7011a5ff68e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("clients", sa.Column("cimd_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clients", "cimd_fetched_at")
