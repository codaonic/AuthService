# Auth Service

A custom OAuth 2.1 / OIDC authorization server built with Python and FastAPI.

## Requirements

- Docker + Docker Compose (for the standard setup)
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (for local development)

## Setup — Docker (recommended)

```bash
cp .env.example .env
# edit .env with your own values
docker compose up -d --build
```

Migrations run automatically before the app starts. The service is available at `http://localhost:8113` — OAuth endpoints at root, setup UI at `/admin`, API docs at `/docs`.

## Setup — Local development

```bash
uv sync
cp .env.example .env
# edit .env to point at your local Postgres/Redis
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Configuration

All configuration is environment-driven. Copy `.env.example` to `.env` and set your own values — it documents every variable (database, Redis, issuer URL, signing keys, admin credentials, rate limits).

## Testing

```bash
uv run pytest
```

Runs fully offline (in-memory database, fake Redis) — no external services required.
