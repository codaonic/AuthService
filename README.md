# Auth Service

A custom **OAuth 2.1 / OIDC authorization server**, written in Python, shared by the website, MCP servers, and any other internal or partner service. It replaces Keycloak: one service owns identity and tokens, while every consumer — regardless of language — talks to it over plain HTTP/JSON/JWT as a standards-compliant resource server.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688)
![License](https://img.shields.io/badge/license-Proprietary-lightgrey)

> Status: **Core AS implemented** — users, clients, `/authorize` + PKCE, `/token`, `/jwks.json`, discovery, dynamic client registration, refresh rotation, revocation, an `/admin` setup UI. See [Roadmap](#roadmap) for what's next.

---

## Table of contents

- [Why a custom service](#why-a-custom-service)
- [Features](#features)
- [Getting started](#getting-started)
  - [Local development](#local-development)
  - [Server / production deployment](#server--production-deployment-docker-compose)
- [Configuration](#configuration)
- [Database migrations](#database-migrations)
- [API surface](#api-surface)
- [Core flows](#core-flows)
- [User pools](#user-pools)
- [Admin UI](#admin-ui)
- [Integrating your applications and MCP servers](#integrating-your-applications-and-mcp-servers)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Security](#security)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [License](#license)

---

## Why a custom service

OAuth 2.1 / OIDC is a wire protocol (HTTP + JSON + JWT), not a Python library. A client written in JavaScript, Go, Swift, Kotlin, Rust, or another Python service all talk to this service the exact same way. Nothing about the server being Python limits who can *use* it — you're not shipping an SDK, you're running a standards-compliant service that any OAuth/OIDC client (including MCP clients) works against with zero custom glue.

## Features

- **Full OAuth 2.1 / OIDC surface** — Authorization Code + mandatory PKCE, `client_credentials`, refresh token rotation with one-time-use enforcement, revocation, Dynamic Client Registration (RFC 7591), Protected Resource Metadata (RFC 9728)
- **Self-service signup and admin-managed users** — toggle per client: let end users register themselves, or restrict a client to admin-added users only
- **User pools** — clients can share one identity (SSO across your own apps) or be fully isolated, your choice, per client
- **Web admin UI** (`/admin`) — pools, clients, resources, users, all clickable, with a CLI equivalent for scripting
- **Resource-server SDK** (Python, [`authservice-client`](https://github.com/codaonic/AuthService_Client), its own repo) plus a documented ~20-line pattern for any other language
- **Argon2 password hashing, TOTP MFA, rotating RS256 signing keys, rate limiting**
- **Zero-dependency test suite** — `uv run pytest` runs fully offline, no database or Redis required

## Getting started

There are two very different setups here — pick based on what you're doing:

### Local development

Runs the app directly on the host with `uv` — fastest iteration, no Docker involved. Point it at any Postgres/Redis you have available locally (native install, or `docker run`/`docker compose up -d postgres redis` published to host ports).

```bash
uv sync                          # installs runtime + dev dependencies from uv.lock
cp .env.example .env             # set DB_HOST/REDIS_HOST to localhost, matching your local services
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Uvicorn defaults to port `8000` here (no `--port` given), so `ISSUER=http://localhost:8000` in `.env.example` is correct as-is for this path.

### Server / production deployment (Docker Compose)

`docker-compose.yml` builds and runs Postgres, Redis, and the app together as a stack, on port **8113** internally, meant to sit behind a **reverse proxy that already exists on the host** — it does not serve the public internet directly, and it expects an external Docker network named `nginx-proxy-net` for that proxy to reach it on. If that network doesn't exist yet:

```bash
docker network create nginx-proxy-net
```

Then:

```bash
cp .env.example .env
# set real values: ISSUER=https://your-domain (not localhost), real DB/Redis
# credentials, and DEFAULT_ADMIN_EMAIL/DEFAULT_ADMIN_PASSWORD before first boot
docker compose up -d --build
docker compose exec auth-service uv run alembic upgrade head
```

The app itself is reachable at `http://localhost:${HOST_PORT:-8113}` on the host (or just internally at `auth_backend:8113` on `nginx-proxy-net` for your reverse proxy) — OAuth surface at root, setup UI at `/admin`, API docs at `/docs`. Point your reverse proxy's `proxy_pass` at `http://auth_backend:8113`.

Migrations are **not** automatic — always run `alembic upgrade head` after `up` on a schema change or a fresh volume. Both Postgres and Redis have `restart: unless-stopped`, so a crash self-heals rather than sitting dead until someone notices.

> **Changed `DB_USER`/`DB_PASSWORD` in `.env` after the first `docker compose up`?** Postgres's official image only applies `POSTGRES_USER`/`POSTGRES_PASSWORD` the *first* time it initializes an empty data directory — editing `.env` afterward does nothing on its own, because `./data/postgres` already has a role/password baked in from that first run. You'll see `password authentication failed` from the app even though `.env` looks correct. Fix it by either wiping the volume for a truly fresh start (only if `./data/postgres` has nothing you need):
> ```bash
> docker compose down
> rm -rf ./data/postgres
> docker compose up -d
> ```
> or, to keep existing data, re-sync Postgres to whatever `.env` currently says (sourcing the file avoids any copy-paste mistakes with the password):
> ```bash
> set -a; source .env; set +a
> docker exec -it auth_pgsql psql -U "$DB_USER" -d "$DB_NAME" -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
> ```
> Either way, if you just wiped the volume, `alembic upgrade head` needs to run again before the app has any tables.
>
> **First boot after a fresh volume can briefly fail with the same error even when the password is correct.** Postgres's `pg_isready` healthcheck can report "healthy" during its internal re-init cycle, before it's truly ready for real connections — the app retries its first DB connection automatically (up to ~20s) to absorb this, so a transient failure here should self-resolve; it's only a real problem if it keeps failing well after startup.

## Configuration

All configuration is environment-driven (`app/config.py`, loaded from `.env`). Connection URLs are **never** set directly — they're composed in code from discrete parts, so no full connection string (with embedded credentials) needs to be passed around or logged.

| Variable | Default | Purpose |
|---|---|---|
| `ISSUER` | `http://localhost:8000` | This service's own URL; stamped into every token's `iss` claim and the discovery doc. The `.env.example` default matches local `uv run` dev (uvicorn's default port); for Docker set it to the real domain in front of the reverse proxy, e.g. `https://auth.yourdomain.com` — never `localhost` once anything else needs to reach it |
| `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `DB_NAME` | `auth` / `auth` / `localhost` / `5432` / `auth` | Postgres connection, composed into `DATABASE_URL` |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD` | `localhost` / `6379` / `0` / *(none)* | Redis connection, composed into `REDIS_URL` |
| `SIGNING_KEY_DIR` | `./keys` | Where RSA signing keys are generated and persisted (mounted as a volume in Docker) |
| `ACCESS_TOKEN_TTL_SECONDS` | `600` | Access token lifetime |
| `REFRESH_TOKEN_TTL_SECONDS` | `2592000` (30d) | Refresh token lifetime |
| `SESSION_TTL_SECONDS` | `604800` (7d) | Login session cookie lifetime |
| `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` | `admin@localhost` / `admin123!` | Seeded admin credentials, used only if no admin account exists yet. Change the password via `/admin/account` after first login; overriding these before first boot avoids the default ever existing at all |
| `RATE_LIMIT_TOKEN` / `RATE_LIMIT_AUTHORIZE` | `20/minute` / `30/minute` | Per-IP rate limits on the two most sensitive endpoints |
| `COMPOSE_DB_HOST` / `COMPOSE_REDIS_HOST` | `postgres` / `redis` | **Compose-only**: not read by the app — used purely for `docker-compose.yml` variable interpolation so container-network hostnames aren't hardcoded in the compose file |
| `HOST_PORT` (shell env, not `.env`) | `8113` | **Compose-only**: which host port `docker compose up` publishes the service on (the container always listens on `8113` internally), e.g. `HOST_PORT=8080 docker compose up -d` if `8113` is already taken |

`.env` is gitignored; `.env.example` documents every variable with safe local-dev defaults.

## Database migrations

Alembic is wired directly to the SQLAlchemy models (`app/db/models.py`), so schema changes are autogenerated rather than hand-written:

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/openid-configuration` | OIDC discovery (RFC 8414) |
| `GET /.well-known/oauth-protected-resource` | Protected Resource Metadata (RFC 9728), per `resource=` query param |
| `GET /jwks.json` | Public signing keys, `kid`-tagged |
| `GET /authorize` | Authorization Code + PKCE entry point |
| `GET`/`POST /login`, `GET`/`POST /signup`, `POST /consent` | Login, signup, and consent-screen pages/submissions |
| `POST /token` | Code exchange, refresh, and `client_credentials` grant |
| `POST /register` | Dynamic Client Registration (RFC 7591) |
| `GET /userinfo` | OIDC standard claims endpoint |
| `POST /revoke` | Refresh token revocation |
| `GET /healthz` | Liveness check |

Full request/response schemas: `/docs` (Swagger UI) once the service is running.

## Core flows

**Website login (browser, BFF pattern).** The website's backend redirects to `/authorize` with a PKCE challenge and its own `resource=` indicator. After login (+ optional MFA) and consent, the BFF exchanges the code server-side and stores tokens keyed to an HttpOnly session cookie — the browser never touches raw tokens.

**MCP / service access.** A client resolves this service via `/.well-known/oauth-protected-resource` → `/.well-known/openid-configuration`, registers (`/register`), and runs Authorization Code + PKCE with `resource=<target-service-id>` (RFC 8707) so the token is scoped to exactly one resource server.

**Service-to-service.** `POST /token` with `grant_type=client_credentials` and the service's own `client_id`/`client_secret` returns a short-lived, user-less JWT scoped to the calling service.

**User signup.** `/authorize` shows a login page with a "Sign up" link (`/signup`) for any client that doesn't recognize the email. A new account is created directly by this service (Argon2-hashed password), logged in, and carried straight into the same consent flow — no separate onboarding step needed.

**Token validation (every consumer, every language).** Fetch `/jwks.json` once, cache it, verify signature + `exp` + `aud` + `iss` locally. No call back to this service required — that's the cross-language guarantee.

## User pools

A single deployment of this service is meant to sit behind **all of one company's own apps, APIs, and MCP servers**. Within that one deployment, every client belongs to a **user pool**:

- Clients that share a pool name share one set of users — sign up through any one of them, log into all of them. This is the common case: one company, one identity, every internal service trusts the same login.
- Clients in different pool names are fully isolated — a user created via one can't log into the other, even though both run on this same instance. Use this for something that genuinely needs a separate user base (e.g. an internal admin tool vs. your public product).

Different *organizations* don't share a deployment at all — each company/provider runs its own separate instance of this service (own DB, own Redis, own signing keys, own domain). Pools are for grouping services *within* one deployment, not for multi-tenant hosting of unrelated companies.

Pools are created implicitly by name the first time you reference them — there's no separate "create a pool" step:

```bash
# These two share one pool ("acme") -- same users can log into both:
uv run python -m app.cli register-client --client-id acme-web --type public --redirect-uri "..." --user-pool acme
uv run python -m app.cli register-client --client-id acme-mobile --type public --redirect-uri "..." --user-pool acme

# This one is isolated in its own pool -- none of the "acme" users can log in here:
uv run python -m app.cli register-client --client-id acme-admin --type confidential --user-pool acme-admin-only
```

`--user-pool` defaults to `default` if omitted (including for DCR/`/register` self-registration), so the common "one company, one shared identity" case needs zero pool configuration at all.

## Admin UI

Everything the CLI can do is also available as a web UI at `/admin`, for operators who'd rather click than run commands:

- **Dashboard** — counts of pools/clients/resources/users.
- **User pools** — create pools by name.
- **Clients** — register clients (public or confidential), pick their user pool, and toggle **"allow signup"** per client — turn it off for a client where only admins should be able to add users (end users can still log in, just not self-register).
- **Resources** — register protected APIs/MCP servers.
- **Users** — the manual add-a-user path, for clients with signup disabled; lists/filters existing users by pool.
- **Account** — change the admin password.

A default admin account is seeded automatically on first startup (`admin@localhost` / `admin123!` unless overridden via `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD`), logged clearly at startup. Sign in at `/admin/login` and change it immediately — the UI shows a banner reminding you until you do. Admin sessions are a separate cookie from end-user sessions, so being signed into `/admin` never grants access to any client's login.

## Integrating your applications and MCP servers

Two things have to happen before a new app or MCP server can use this service: **register it**, then **validate tokens** in it. Nothing else — every resource server is stateless with respect to the auth service; it just needs a cached JWKS.

### 1. Register a resource and a client

Every protected app/API/MCP server is a **resource** (its identity as a token audience); every thing that requests tokens *on behalf of* a user or itself is a **client**. A website's BFF is usually both registered separately for its login flow (client) and the API it fronts (resource); an MCP server is typically just a resource, since MCP *clients* register themselves via DCR.

```bash
# From this repo, against a running instance:
uv run python -m app.cli register-resource --resource-id "https://mcp.yourdomain.com" --name "Your MCP Server"
uv run python -m app.cli register-client --client-id your-app --type public --redirect-uri "https://yourapp.com/callback"
# (in Docker: docker compose exec auth-service uv run python -m app.cli ...)
```

Add `--user-pool <name>` to either share users with your other clients or isolate them — see [User pools](#user-pools). Omit it and everything lands in one shared `default` pool.

MCP clients don't need manual registration — they self-register at connect time via `POST /register` (Dynamic Client Registration), which is exactly what `/.well-known/oauth-protected-resource` + `/.well-known/openid-configuration` exist to point them at.

### 2. Validate tokens in the resource server

This is the part every app/MCP server has to do, and it's the same three steps in any language (fetch JWKS → cache it → verify signature/`exp`/`aud`/`iss` locally, no call back to this service per-request). Two ways to do it:

- **Python**: use [`authservice-client`](https://github.com/codaonic/AuthService_Client) — its own repo, so it installs without needing access to this one — a `TokenValidator` plus FastAPI dependency helpers (`make_auth_dependency`, `make_scope_dependency`) and a router that serves your resource's own RFC 9728 metadata. Not on PyPI — install straight from GitHub:
  ```bash
  uv add "authservice-client @ git+https://github.com/codaonic/AuthService_Client.git@main"
  # pip install "authservice-client @ git+https://github.com/codaonic/AuthService_Client.git@main"
  # poetry add "git+https://github.com/codaonic/AuthService_Client.git#main"
  ```
  Full usage, versioning, and changelog: [codaonic/AuthService_Client](https://github.com/codaonic/AuthService_Client).
- **Any other language**: reimplement the same ~20-line pattern — there's a mature JWT + JWKS library in every mainstream language (`jose`/`jwks-rsa` in Node, `github.com/coreos/go-oidc` in Go, `jose4j` in Java). No dependency on this being a Python service.

Two runnable, tested examples built on the SDK:

- [`examples/example_api`](examples/example_api) — a plain protected API (`/me`, a scope-gated `/profile`)
- [`examples/mcp_server`](examples/mcp_server) — the same pattern shaped for an MCP server's auth hook (401 challenge + PRM + per-call validation); swap the FastAPI routes for your actual MCP SDK's request handling, the `TokenValidator` plugs into whatever transport you use

```bash
cd examples/example_api
uv sync
uv run uvicorn main:app --reload --port 9001
```

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │        AUTH SERVICE (Python/FastAPI)      │
                         │  /authorize  /token  /register  /revoke   │
                         │  /login  /signup  /consent  /userinfo     │
                         │  /.well-known/openid-configuration        │
                         │  /.well-known/oauth-protected-resource    │
                         │  /jwks.json                                │
                         │  /admin/*  -- operator setup UI: pools,   │
                         │    clients, resources, users, own login   │
                         └───────────────┬─────────────────────────┘
                                         │
                     ┌───────────────────┼───────────────────┐
                     ▼                   ▼                   ▼
              PostgreSQL           Redis                  Signing keys
          (users, clients,     (sessions, auth codes,     (rotating RSA
           resources, consents, refresh tokens,            keypairs on disk,
           refresh-token audit) revocation)                 kid-tagged)

                     ▲  JWKS + OIDC discovery, fetched & cached locally
                     │
      ┌──────────────┼──────────────────┬──────────────────────┐
      ▼                                  ▼                       ▼
┌──────────────┐                 ┌──────────────┐        ┌───────────────────┐
│   Website     │                 │  MCP servers  │        │  Other apps/APIs   │
│ (any language) │                 │ (Python, Go,  │        │ (mobile, partner    │
│                │                 │  Node, etc.)  │        │  services, any lang)│
└──────────────┘                 └──────────────┘        └───────────────────┘
```

Every consumer is a **resource server**: it never issues tokens, it only fetches this service's JWKS once, caches it, and verifies JWTs locally — no network call back to the auth service on the hot path.

## Tech stack

| Component | Choice | Why |
|---|---|---|
| Web framework | FastAPI | Async, native OpenAPI docs |
| Database | PostgreSQL via SQLAlchemy (async) + asyncpg | Users, clients, resources, consents, refresh-token audit trail |
| Cache / sessions / codes | Redis | Login sessions, authorization codes, active refresh tokens, one-time-use enforcement |
| JWT signing | `python-jose` + `cryptography` | RS256, `kid`-based key rotation |
| Password hashing | `argon2-cffi` | Memory-hard, current best practice |
| MFA | `pyotp` (TOTP) | Standard authenticator-app codes |
| Rate limiting | `slowapi` | Brute-force protection on `/token` and `/authorize` |
| Migrations | Alembic | Schema versioning |
| Package/dependency manager | `uv` | Fast, lockfile-based, single source of truth (`pyproject.toml` / `uv.lock`) |
| Templates | Jinja2 | Server-rendered login/consent pages |

## Project structure

```
auth_service/
├── app/
│   ├── main.py                  # FastAPI app entrypoint, router + middleware wiring
│   ├── config.py                # env-based settings (pydantic-settings); builds DB/Redis URLs from parts
│   ├── cli.py                    # admin CLI: register-client, register-resource, create-user, list-*
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models: UserPool, User, AdminUser, Client, Resource, Consent, RefreshToken
│   │   ├── pools.py              # get_or_create_pool() -- pools are created implicitly by name
│   │   ├── session.py           # async engine + session factory
│   │   └── redis_client.py      # Redis connection
│   ├── oidc/                     # standard OAuth/OIDC surface, all at root
│   │   ├── discovery.py         # GET /.well-known/openid-configuration
│   │   ├── prm.py                # GET /.well-known/oauth-protected-resource
│   │   ├── authorize.py          # /authorize, /login, /signup, /consent (PKCE + login/signup + consent flow)
│   │   ├── token.py              # POST /token (auth code, refresh, client_credentials)
│   │   ├── refresh.py            # refresh-token issuance/rotation/revocation (Redis + Postgres audit)
│   │   ├── clients.py            # client authentication (confidential/public)
│   │   ├── scope.py              # scope resolution against a client's allowed_scope
│   │   ├── pkce.py               # PKCE S256 verification
│   │   ├── keys.py               # RSA key generation/rotation, JWKS
│   │   ├── tokens.py             # JWT minting
│   │   ├── jwks.py               # GET /jwks.json
│   │   ├── register.py           # POST /register (Dynamic Client Registration, RFC 7591)
│   │   ├── revoke.py             # POST /revoke
│   │   └── userinfo.py           # GET /userinfo
│   ├── admin/                     # mounted under /admin -- operator setup UI
│   │   ├── auth.py                # admin login/logout, session handling
│   │   ├── seed.py                # seeds the default admin account on startup
│   │   └── routes.py              # dashboard, pools, clients, resources, users, account
│   ├── auth/
│   │   ├── passwords.py          # argon2 hashing
│   │   ├── mfa.py                 # TOTP generate/verify
│   │   └── sessions.py            # Redis-backed login sessions (shared by end-user and admin sessions)
│   ├── middleware/
│   │   └── rate_limit.py          # slowapi limiter
│   ├── templates/                 # Jinja2 pages: base.html, login.html, signup.html, consent.html, admin/*
│   └── static/                    # CSS/JS for both the login/consent UI and the admin UI
├── alembic/                       # migrations (env.py wired to app.db.models.Base.metadata)
├── tests/                         # pytest + httpx ASGI client, fakeredis, in-memory SQLite
├── examples/
│   ├── example_api/                # runnable protected API built on the SDK
│   └── mcp_server/                 # runnable MCP-server auth pattern built on the SDK
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml / uv.lock
├── .env / .env.example
└── plan/                          # design doc this service is built from (not committed)
```

## Security

- PKCE (S256) mandatory on every authorization code exchange
- Refresh tokens are one-time-use: each refresh rotates the token and invalidates the previous one; reuse is rejected
- Refresh token validity lives in Redis (fast revocation check); Postgres keeps the full audit trail (`rotated_from`, `revoked_at`)
- Passwords hashed with Argon2; TOTP MFA supported per-user
- Access tokens are short-lived JWTs (default 10 min), scoped to a single `resource` (RFC 8707) — no ambient all-access tokens
- Rate limiting on `/token`, `/authorize`, and `/admin/login`
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` whenever served over HTTPS; admin sessions use a separate cookie from end-user sessions
- No credentials or connection strings are hardcoded anywhere — `docker-compose.yml` sources them from `.env` via variable interpolation, and the app itself composes URLs from discrete env vars at runtime
- A default admin account is seeded on first run and flagged `must_change_password` until you change it via `/admin/account` — override `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD` before first boot if you don't want the default to exist even briefly

## Testing

```bash
uv run pytest
```

The suite uses `httpx`'s ASGI transport (no running server needed), `fakeredis` in place of Redis, and an in-memory SQLite database — so it runs with zero external dependencies. It covers discovery/JWKS, dynamic client registration, the full authorize → login/signup → consent → token → refresh-rotation → revoke lifecycle for both authorization-code and client-credentials grants, user-pool sharing/isolation, and the admin UI (login, seeding, pools/clients/resources/users CRUD, the signup toggle).

## Roadmap

Following the build order this service was planned against:

- [x] Core AS: users, clients, `/authorize`, `/token` (auth code + PKCE), `/jwks.json`, discovery doc
- [x] Client credentials grant (service-to-service)
- [x] Dynamic Client Registration, refresh rotation, revocation denylist
- [x] Polished login/consent UI
- [x] Admin CLI for registering resources/clients/users; resource-server SDK + example integrations
- [x] Self-service user signup, and user pools (shared vs. isolated identity across clients on one deployment)
- [x] `/admin` setup UI (pools, clients, resources, users, per-client signup toggle) with a seeded default admin account
- [ ] Website integration: BFF pattern, end-to-end session cookie test against a real frontend
- [ ] MCP support: validated against a real MCP client
- [ ] CIMD support (once MCP client ecosystem expects it)
- [ ] Policy layer: OPA sidecar for fine-grained authz
- [ ] Gateway hardening: Envoy JWT validation in front of resource servers
- [ ] mTLS between gateway and resource servers / `client_credentials` clients
- [ ] Observability: structured audit logs, anomalous-issuance alerting
- [ ] Pen test before production traffic

## License

Proprietary — internal use only. Not licensed for external distribution.
