# Contributing

Thanks for considering a contribution. This is a self-hosted OAuth 2.1 / OIDC
authorization server — changes here affect every service that trusts its
tokens, so please read this before opening a PR.

## Dev setup

```bash
git clone https://github.com/codaonic/AuthService.git
cd AuthService
uv sync
cp .env.example .env   # fill in DB/Redis settings for local dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Running tests

```bash
uv run pytest
```

The suite is fully offline — in-memory SQLite and `fakeredis`, no real
Postgres/Redis needed. It must pass before a PR is merged; CI runs it
automatically on every push and PR.

## Making a change

1. Fork the repo and create a branch off `main`.
2. Keep the change focused — one concern per PR is much easier to review
   than a bundle of unrelated fixes.
3. Add or update tests for any behavior change. A bug fix without a
   regression test is easy to reintroduce later.
4. Run `uv run pytest` locally before pushing.
5. Open a PR describing *why* the change is needed, not just what it does —
   the diff already shows what changed.

## Reporting bugs vs. security issues

Regular bugs: open a GitHub issue.

Anything that could lead to token forgery, signature bypass, credential
exposure, or cross-tenant (cross-pool) data leakage: **do not open a public
issue** — see [SECURITY.md](SECURITY.md) instead.

## Code style

- Match the existing style in the file you're editing — this codebase
  doesn't use a heavy framework of abstractions; keep additions similarly
  direct.
- No new dependencies for something a few lines of stdlib/existing deps can
  do.
- Comments explain *why*, not *what* — the code should already say what it
  does.

## Code of Conduct

Participation in this project is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).
