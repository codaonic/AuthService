"""index consents and refresh_tokens by user and client

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-10-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every authorization looks up the user's consent for the client, and
    # logout / password reset look up a user's refresh tokens -- both were
    # full table scans.
    op.create_index("ix_consents_user_client", "consents", ["user_id", "client_id"])
    op.create_index("ix_refresh_tokens_user_client", "refresh_tokens", ["user_id", "client_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_client", table_name="refresh_tokens")
    op.drop_index("ix_consents_user_client", table_name="consents")
