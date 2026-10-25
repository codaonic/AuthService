"""add per-client embed origins for embedded sign-in

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-10-25 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Empty for every existing client: embedding stays off until an admin
    # lists the origins allowed to embed that application's sign-in.
    op.add_column("clients", sa.Column("embed_origins", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("clients", "embed_origins")
