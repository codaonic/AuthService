"""ID-token roles claim name, back-channel logout, signup team, composite
roles, team managers, access that ends by itself, restricted-by-default groups

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-13 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every default keeps existing apps, groups and people working as before.
    op.add_column("clients", sa.Column("roles_claim", sa.String(), nullable=False, server_default="roles"))
    op.add_column("clients", sa.Column("backchannel_logout_uri", sa.String(), nullable=True))
    op.add_column("clients", sa.Column("signup_team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=True))
    op.add_column("user_pools", sa.Column("restrict_new_apps", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("client_access_grants", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("team_members", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("team_members", sa.Column("is_manager", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "client_role_includes",
        sa.Column("client_id", sa.String(), primary_key=True),
        sa.Column("role", sa.String(), primary_key=True),
        sa.Column("includes", sa.String(), primary_key=True),
        sa.ForeignKeyConstraint(["client_id", "role"], ["client_roles.client_id", "client_roles.name"]),
        sa.ForeignKeyConstraint(["client_id", "includes"], ["client_roles.client_id", "client_roles.name"]),
    )


def downgrade() -> None:
    op.drop_table("client_role_includes")
    op.drop_column("team_members", "is_manager")
    op.drop_column("team_members", "expires_at")
    op.drop_column("client_access_grants", "expires_at")
    op.drop_column("user_pools", "restrict_new_apps")
    op.drop_column("clients", "signup_team_id")
    op.drop_column("clients", "backchannel_logout_uri")
    op.drop_column("clients", "roles_claim")
