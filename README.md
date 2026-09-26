# Auth Service

A custom **OAuth 2.1 / OIDC authorization server**, written in Python, shared by the website, MCP servers, and any other internal or partner service. It replaces Keycloak: one service owns identity and tokens, while every consumer — regardless of language — talks to it over plain HTTP/JSON/JWT as a standards-compliant resource server.

> Status: **Core AS implemented** — users, clients, `/authorize` + PKCE, `/token`, `/jwks.json`, discovery, dynamic client registration, refresh rotation, revocation. See [Roadmap](#roadmap) for what's next.

---

## Table of contents

- [Why a custom service](#why-a-custom-service)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
  - [Option A — Docker Compose](#option-a--docker-compose-recommended)
  - [Option B — Local dev with uv](#option-b--local-dev-with-uv)
- [Configuration](#configuration)
- [Database migrations](#database-migrations)
- [API surface](#api-surface)
- [Core flows](#core-flows)
- [Integrating your applications and MCP servers](#integrating-your-applications-and-mcp-servers)
- [Security](#security)
- [Testing](#testing)
- [Roadmap](#roadmap)

---

## Why a custom service

OAuth 2.1 / OIDC is a wire protocol (HTTP + JSON + JWT), not a Python library. A client written in JavaScript, Go, Swift, Kotlin, Rust, or another Python service all talk to this service the exact same way. Nothing about the server being Python limits who can *use* it — you're not shipping an SDK, you're running a standards-compliant service that any OAuth/OIDC client (including MCP clients) works against with zero custom glue.

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │        AUTH SERVICE (Python/FastAPI)      │
                         │  /authorize  /token  /register  /revoke   │
                         │  /.well-known/openid-configuration        │
                         │  /.well-known/oauth-protected-resource    │
                         │  /jwks.json  /userinfo                    │
                         │  Login UI, MFA, consent screen            │
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
│   │   ├── models.py            # SQLAlchemy models: User, Client, Resource, Consent, RefreshToken
│   │   ├── session.py           # async engine + session factory
│   │   └── redis_client.py      # Redis connection
│   ├── oidc/
│   │   ├── discovery.py         # GET /.well-known/openid-configuration
│   │   ├── prm.py                # GET /.well-known/oauth-protected-resource
│   │   ├── authorize.py          # GET /authorize, POST /login, POST /consent (PKCE + login + consent flow)
│   │   ├── token.py              # POST /token (auth code, refresh, client_credentials)
│   │   ├── refresh.py            # refresh-token issuance/rotation/revocation (Redis + Postgres audit)
│   │   ├── clients.py            # client authentication (confidential/public)
│   │   ├── pkce.py               # PKCE S256 verification
│   │   ├── keys.py               # RSA key generation/rotation, JWKS
│   │   ├── tokens.py             # JWT minting
│   │   ├── jwks.py               # GET /jwks.json
│   │   ├── register.py           # POST /register (Dynamic Client Registration, RFC 7591)
│   │   ├── revoke.py             # POST /revoke
│   │   └── userinfo.py           # GET /userinfo
│   ├── auth/
│   │   ├── passwords.py          # argon2 hashing
│   │   ├── mfa.py                 # TOTP generate/verify
│   │   └── sessions.py            # Redis-backed login sessions
│   ├── middleware/
│   │   └── rate_limit.py          # slowapi limiter
│   ├── templates/                 # Jinja2 login/consent pages (base.html + login.html + consent.html)
│   └── static/                    # CSS/JS for the login/consent UI
├── alembic/                       # migrations (env.py wired to app.db.models.Base.metadata)
├── tests/                         # pytest + httpx ASGI client, fakeredis, in-memory SQLite
├── sdk/python/                     # auth-service-sdk: TokenValidator + FastAPI helpers for resource servers
│   └── auth_service_sdk/           # standalone package, its own pyproject.toml/uv.lock, zero app.* dependency
├── examples/
│   ├── example_api/                # runnable protected API built on the SDK
│   └── mcp_server/                 # runnable MCP-server auth pattern built on the SDK
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml / uv.lock
├── .env / .env.example
└── plan/                          # design doc this service is built from (not committed)
```

## Getting started

### Option A — Docker Compose (recommended)

Brings up Postgres, Redis, and the service together, wired by container network hostnames.

```bash
cp .env.example .env   # adjust values if needed; defaults match docker-compose
docker compose up -d --build
docker compose exec auth-service uv run alembic upgrade head
```

The service is now on `http://localhost:8000`. Interactive API docs: `http://localhost:8000/docs`.

### Option B — Local dev with uv

Runs the app directly on the host (faster iteration), pointing at Postgres/Redis however you have them available (e.g. `docker compose up -d postgres redis` published to host ports, or local installs).

```bash
uv sync                          # installs runtime + dev dependencies from uv.lock
cp .env.example .env             # set DB_HOST/REDIS_HOST to localhost, matching your local services
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Configuration

All configuration is environment-driven (`app/config.py`, loaded from `.env`). Connection URLs are **never** set directly — they're composed in code from discrete parts, so no full connection string (with embedded credentials) needs to be passed around or logged.

| Variable | Default | Purpose |
|---|---|---|
| `ISSUER` | `http://localhost:8000` | This service's own URL; stamped into every token's `iss` claim and the discovery doc |
| `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `DB_NAME` | `auth` / `auth` / `localhost` / `5432` / `auth` | Postgres connection, composed into `DATABASE_URL` |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD` | `localhost` / `6379` / `0` / *(none)* | Redis connection, composed into `REDIS_URL` |
| `SIGNING_KEY_DIR` | `./keys` | Where RSA signing keys are generated and persisted (mounted as a volume in Docker) |
| `ACCESS_TOKEN_TTL_SECONDS` | `600` | Access token lifetime |
| `REFRESH_TOKEN_TTL_SECONDS` | `2592000` (30d) | Refresh token lifetime |
| `SESSION_TTL_SECONDS` | `604800` (7d) | Login session cookie lifetime |
| `RATE_LIMIT_TOKEN` / `RATE_LIMIT_AUTHORIZE` | `20/minute` / `30/minute` | Per-IP rate limits on the two most sensitive endpoints |
| `COMPOSE_DB_HOST` / `COMPOSE_REDIS_HOST` | `postgres` / `redis` | **Compose-only**: not read by the app — used purely for `docker-compose.yml` variable interpolation so container-network hostnames aren't hardcoded in the compose file |
| `HOST_PORT` (shell env, not `.env`) | `8000` | **Compose-only**: which host port `docker compose up` publishes the service on, e.g. `HOST_PORT=8080 docker compose up -d` if `8000` is already taken locally |

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
| `POST /login`, `POST /consent` | Login and consent-screen form submissions |
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

**Token validation (every consumer, every language).** Fetch `/jwks.json` once, cache it, verify signature + `exp` + `aud` + `iss` locally. No call back to this service required — that's the cross-language guarantee.

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

MCP clients don't need manual registration — they self-register at connect time via `POST /register` (Dynamic Client Registration), which is exactly what `/.well-known/oauth-protected-resource` + `/.well-known/openid-configuration` exist to point them at.

### 2. Validate tokens in the resource server

This is the part every app/MCP server has to do, and it's the same three steps in any language (fetch JWKS → cache it → verify signature/`exp`/`aud`/`iss` locally, no call back to this service per-request). Two ways to do it:

- **Python**: use [`sdk/python`](sdk/python) (`auth-service-sdk`) — a `TokenValidator` plus FastAPI dependency helpers (`make_auth_dependency`, `make_scope_dependency`) and a router that serves your resource's own RFC 9728 metadata. See [`sdk/python/README.md`](sdk/python/README.md).
- **Any other language**: reimplement the same ~20-line pattern — there's a mature JWT + JWKS library in every mainstream language (`jose`/`jwks-rsa` in Node, `github.com/coreos/go-oidc` in Go, `jose4j` in Java). No dependency on this being a Python service.

Two runnable, tested examples built on the SDK:

- [`examples/example_api`](examples/example_api) — a plain protected API (`/me`, a scope-gated `/profile`)
- [`examples/mcp_server`](examples/mcp_server) — the same pattern shaped for an MCP server's auth hook (401 challenge + PRM + per-call validation); swap the FastAPI routes for your actual MCP SDK's request handling, the `TokenValidator` plugs into whatever transport you use

```bash
cd examples/example_api
uv sync
uv run uvicorn main:app --reload --port 9001
```

## Security

- PKCE (S256) mandatory on every authorization code exchange
- Refresh tokens are one-time-use: each refresh rotates the token and invalidates the previous one; reuse is rejected
- Refresh token validity lives in Redis (fast revocation check); Postgres keeps the full audit trail (`rotated_from`, `revoked_at`)
- Passwords hashed with Argon2; TOTP MFA supported per-user
- Access tokens are short-lived JWTs (default 10 min), scoped to a single `resource` (RFC 8707) — no ambient all-access tokens
- Rate limiting on `/token` and `/authorize`
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` whenever served over HTTPS
- No credentials or connection strings are hardcoded anywhere — `docker-compose.yml` sources them from `.env` via variable interpolation, and the app itself composes URLs from discrete env vars at runtime

## Testing

```bash
uv run pytest
```

The suite uses `httpx`'s ASGI transport (no running server needed), `fakeredis` in place of Redis, and an in-memory SQLite database — so it runs with zero external dependencies. It covers discovery/JWKS, dynamic client registration, and the full authorize → login → consent → token → refresh-rotation → revoke lifecycle for both authorization-code and client-credentials grants.

## Roadmap

Following the build order this service was planned against:

- [x] Core AS: users, clients, `/authorize`, `/token` (auth code + PKCE), `/jwks.json`, discovery doc
- [x] Client credentials grant (service-to-service)
- [x] Dynamic Client Registration, refresh rotation, revocation denylist
- [x] Polished login/consent UI
- [x] Admin CLI for registering resources/clients/users; resource-server SDK + example integrations
- [ ] Website integration: BFF pattern, end-to-end session cookie test against a real frontend
- [ ] MCP support: validated against a real MCP client
- [ ] CIMD support (once MCP client ecosystem expects it)
- [ ] Policy layer: OPA sidecar for fine-grained authz
- [ ] Gateway hardening: Envoy JWT validation in front of resource servers
- [ ] mTLS between gateway and resource servers / `client_credentials` clients
- [ ] Observability: structured audit logs, anomalous-issuance alerting
- [ ] Pen test before production traffic
