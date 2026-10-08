"""drop client soft delete

Client delete is a real DELETE now, not a soft one -- see api_delete_client,
which cascades through everything that pointed at the client_id first. User
delete is unaffected and stays soft (users.deleted_at is untouched).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("clients", "deleted_at")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("clients", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
