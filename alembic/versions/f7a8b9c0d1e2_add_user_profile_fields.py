"""add user profile fields (username, first_name, last_name, phone)

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-08 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(), nullable=True))
    op.add_column("users", sa.Column("first_name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(), nullable=True))

    op.create_index("ix_users_username", "users", ["username"])
    # Partial unique index: username must be unique per client, but only when set.
    op.create_index(
        "uq_users_client_username",
        "users",
        ["client_id", "username"],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_client_username", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "phone")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "username")
