"""add restricted runtime db role

Revision ID: ccaefb51cc6b
Revises: 3fd896078ff6
Create Date: 2026-09-27 00:00:00.000000

Creates a non-superuser Postgres role for the app to connect as while
serving requests, separate from the role that runs migrations. Row-Level
Security (see enable_users_rls) has no effect on a superuser connection --
this role is what makes it actually enforce anything.

The role is created with no usable password. Set one yourself, then point
DB_APP_USER/DB_APP_PASSWORD at it (see README's "Row-level security"
section):

    ALTER ROLE auth_app_runtime WITH PASSWORD 'choose-one';

Until you do both of those, the app keeps using the same (migration) role
as before -- this migration alone doesn't change how the app connects.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ccaefb51cc6b'
down_revision: Union[str, Sequence[str], None] = '3fd896078ff6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_NAME = "auth_app_runtime"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
                CREATE ROLE {ROLE_NAME} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE_NAME}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE_NAME}")
    # So tables added by future migrations are automatically readable/writable
    # by this role too, without editing this grant again -- applies to
    # objects created by whichever role runs `alembic upgrade head`, which is
    # this same migration role going forward.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE_NAME}"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {ROLE_NAME}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE_NAME}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE_NAME}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE_NAME}")
