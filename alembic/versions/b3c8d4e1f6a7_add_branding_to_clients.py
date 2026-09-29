"""add branding to clients

Revision ID: b3c8d4e1f6a7
Revises: f1a6b7c9d3e2
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c8d4e1f6a7'
down_revision: Union[str, Sequence[str], None] = 'f1a6b7c9d3e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("clients", sa.Column("logo_url", sa.String(), nullable=True))
    op.add_column("clients", sa.Column("brand_color", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clients", "brand_color")
    op.drop_column("clients", "logo_url")
