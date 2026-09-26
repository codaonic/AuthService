#!/bin/sh
set -e

echo "Applying database migrations..."
uv run alembic upgrade head

exec "$@"
