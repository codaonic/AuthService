"""add per-client session timeout and post-logout redirect URIs

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-10-10 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("session_ttl_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    # 0 = no per-application limit, which is how everything behaved before
    # this column existed. Only admin-registered websites start with a
    # 7-day limit; API, MCP and other self-registered clients keep the old rules.
    op.execute(
        "UPDATE clients SET session_ttl_seconds = 604800 "
        "WHERE application_type = 'web' AND registration_method = 'static'"
    )
    op.add_column(
        "clients",
        sa.Column("post_logout_redirect_uris", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("clients", "post_logout_redirect_uris")
    op.drop_column("clients", "session_ttl_seconds")
