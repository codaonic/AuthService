"""add client_name to clients

Revision ID: f1a6b7c9d3e2
Revises: ccaefb51cc6b
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a6b7c9d3e2'
down_revision: Union[str, Sequence[str], None] = 'ccaefb51cc6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("clients", sa.Column("client_name", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clients", "client_name")
