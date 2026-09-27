"""add mtls cert thumbprint to clients

Revision ID: a7011a5ff68e
Revises: 19a3d326d5e7
Create Date: 2026-09-27 12:09:46.864179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7011a5ff68e'
down_revision: Union[str, Sequence[str], None] = '19a3d326d5e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("clients", sa.Column("mtls_cert_thumbprint", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clients", "mtls_cert_thumbprint")
