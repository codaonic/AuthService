"""add webauthn credentials

Revision ID: 19a3d326d5e7
Revises: 52813a37d057
Create Date: 2026-09-27 03:02:58.735204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19a3d326d5e7'
down_revision: Union[str, Sequence[str], None] = '52813a37d057'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("transports", sa.JSON(), nullable=False),
        sa.Column("nickname", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_webauthn_credentials_credential_id"), "webauthn_credentials", ["credential_id"], unique=True
    )
    op.create_index(op.f("ix_webauthn_credentials_user_id"), "webauthn_credentials", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_webauthn_credentials_user_id"), table_name="webauthn_credentials")
    op.drop_index(op.f("ix_webauthn_credentials_credential_id"), table_name="webauthn_credentials")
    op.drop_table("webauthn_credentials")
