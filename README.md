# Auth Service

A self-hosted **OAuth 2.1 / OIDC authorization server**, written in Python and built MCP-native from day one. One service owns identity and tokens, while every consumer, regardless of language, talks to it over plain HTTP/JSON/JWT as a standards-compliant resource server.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688)
![License](https://img.shields.io/badge/license-MIT-green)

> Status: **Feature-complete against its planned scope** — full OAuth 2.1/OIDC surface, DCR + CIMD, passkeys, mTLS, user pools, and an admin UI. See [Roadmap](#roadmap) for the checklist.

## Quickstart

```bash
docker network create nginx-proxy-net   # once, if it doesn't already exist
cp .env.example .env
docker compose up -d --build && docker compose exec auth-service uv run alembic upgrade head
```

That's a real, running instance at `http://localhost:8113` (admin console at `/admin`, default login logged to `docker compose logs auth-service`). See [Getting started](#getting-started) below for local (non-Docker) development, or to set real production values first.

---

## Table of contents

- [Quickstart](#quickstart)
- [Why a custom service](#why-a-custom-service)
- [Features](#features)
- [Getting started](#getting-started)
  - [Local development](#local-development)
  - [Server / production deployment](#server--production-deployment-docker-compose)
- [Configuration](#configuration)
- [Database migrations](#database-migrations)
- [Row-level security](#row-level-security)
- [API surface](#api-surface)
- [Core flows](#core-flows)
- [User pools](#user-pools)
- [Admin UI](#admin-ui)
- [Integrating your applications and MCP servers](#integrating-your-applications-and-mcp-servers)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Security](#security)
- [Mutual TLS for `client_credentials` clients](#mutual-tls-for-client_credentials-clients)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why a custom service

OAuth 2.1 / OIDC is a wire protocol (HTTP + JSON + JWT), not a Python library. A client written in JavaScript, Go, Swift, Kotlin, Rust, or another Python service all talk to this service the exact same way. Nothing about the server being Python limits who can *use* it — you're not shipping an SDK, you're running a standards-compliant service that any OAuth/OIDC client (including MCP clients) works against with zero custom glue.

## Features

- **Full OAuth 2.1 / OIDC surface** — Authorization Code + mandatory PKCE, `client_credentials`, refresh token rotation with one-time-use enforcement, revocation
- **MCP-native client registration** — Dynamic Client Registration (RFC 7591), Protected Resource Metadata (RFC 9728), and [CIMD](https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/) (`client_id`-as-URL), which the MCP spec's 2026-07-28 revision formally deprecates DCR in favor of
- **Self-service signup, password recovery, and email verification** — with admin-managed users as an alternative, toggled per client
- **Passkey (WebAuthn) login** alongside password + TOTP, not instead of it
- **Embeddable popup widget** (`auth-widget.js`) so a site can trigger login/signup from its own styled button without a full-page redirect, plus optional per-client branding (logo, color) on the hosted form itself — see [§4](#4-making-it-feel-embedded-the-popup-widget)
- **User pools** — clients can share one identity (SSO across your own apps) or be fully isolated, your choice, per client, with optional [Postgres Row-Level Security](#row-level-security) as a database-level backstop
- **Web admin UI** (`/admin`) — pools, clients, resources, users, all clickable, with a CLI equivalent for scripting
- **Resource-server SDK** (Python, [`authservice-client`](https://github.com/codaonic/AuthService_Client), its own repo) plus a documented ~20-line pattern for any other language
- **mTLS client authentication** for `client_credentials` clients, stronger than a shared secret
- **Structured (JSON-lines) audit logging** with anomalous-activity flagging, ready for any log aggregator
- **Argon2 password hashing, TOTP MFA, rotating RS256 signing keys, rate limiting**
- **No external services required to test** — `uv run pytest` runs fully offline against `fakeredis` and an in-memory SQLite database, no Postgres or Redis needed

## Getting started

There are two very different setups here — pick based on what you're doing:

### Local development

Runs the app directly on the host with `uv` — fastest iteration (actual `--reload`, no image rebuild per change), while still using the **same** Postgres/Redis this project's own `docker-compose.yml` manages, so you're not maintaining a second set of data.

`docker-compose.yml` publishes both to **loopback-only** host ports — reachable from this same machine, never from the network, regardless of firewall rules, even if this same compose file is the one running on a real server:

```bash
docker compose up -d postgres redis   # just these two services, not auth-service
```

- Postgres: `127.0.0.1:5434` (not the standard `5432` — a host often already has its own)
- Redis: `127.0.0.1:6381` (likewise, not the standard `6379`)

Override `DB_HOST_PORT`/`REDIS_HOST_PORT` in `.env` if either collides with something else on your machine.

Then run the backend directly on the host, pointed at those ports — `.env`'s own `DB_HOST`/`REDIS_HOST` are for `docker-compose.yml`'s internal container names (`auth_pgsql`/`auth_redis`, unreachable from outside Docker), so override them inline instead of editing the file:

```bash
uv sync                          # installs runtime + dev dependencies from uv.lock
cp .env.example .env             # fill in the same DB_*/REDIS_PASSWORD .env already uses for Docker
uv run alembic upgrade head
DB_HOST=127.0.0.1 DB_PORT=5434 REDIS_HOST=127.0.0.1 REDIS_PORT=6381 \
  uv run uvicorn app.main:app --reload
```

Uvicorn defaults to port `8000` here (no `--port` given), so `ISSUER=http://localhost:8000` in `.env.example` is correct as-is for this path.

The admin console at `/admin` is a separate React app (`frontend/`) that FastAPI serves as a
built static bundle — `uv run uvicorn` alone won't have anything to serve there until you build
it once:

```bash
cd frontend
npm install
npm run build     # outputs frontend/dist, which app/main.py serves at /admin
```

Iterating on the admin UI itself is faster with Vite's own dev server instead, which proxies
`/admin/api/*` to the FastAPI backend (see `frontend/vite.config.ts`) and hot-reloads on save:

```bash
cd frontend
npm run dev        # serves the SPA itself at http://localhost:5173/admin
```

### Server / production deployment (Docker Compose)

`docker-compose.yml` builds and runs Postgres, Redis, and the app together as a stack, on port **8113** internally, meant to sit behind a **reverse proxy that already exists on the host** — it does not serve the public internet directly, and it expects an external Docker network named `nginx-proxy-net` for that proxy to reach it on. If that network doesn't exist yet:

> **Naming note:** commands below mix two different names for the same thing. `postgres`, `redis`, and `auth-service` are the *compose service names* (what `docker compose exec <name> ...` takes); `auth_pgsql`, `auth_redis`, and `auth_backend` are the *container names* (what plain `docker exec <name> ...` or `docker logs <name>` take). Either works, but they're not interchangeable with the wrong command.

```bash
docker network create nginx-proxy-net
```

Then:

```bash
cp .env.example .env
# set real values: ISSUER=https://your-domain (not localhost), real DB/Redis credentials
docker compose up -d --build
docker compose exec auth-service uv run alembic upgrade head
```

Open `/admin` and you'll land on a setup screen to create your own admin email/password — there's no default credential to know about or change. (`DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD` in [Configuration](#configuration) are an escape hatch for scripted deployments that can't drive that screen, not something you need for a normal setup.)

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
| `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `DB_NAME` | `auth` / `auth` / `localhost` / `5432` / `auth` | Postgres connection, composed into `DATABASE_URL`. Used for migrations, the CLI, and first-boot schema bootstrap — these need DDL rights |
| `DB_APP_USER` / `DB_APP_PASSWORD` | *(none — falls back to `DB_USER`/`DB_PASSWORD`)* | The role the running app actually connects as to serve requests. See "Row-level security" below — this is what makes that protection real instead of a no-op |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD` | `localhost` / `6379` / `0` / *(none)* | Redis connection, composed into `REDIS_URL` |
| `SIGNING_KEY_DIR` | `./keys` | Where RSA signing keys are generated and persisted (mounted as a volume in Docker) |
| `ACCESS_TOKEN_TTL_SECONDS` | `600` | Access token lifetime |
| `REFRESH_TOKEN_TTL_SECONDS` | `2592000` (30d) | Refresh token lifetime |
| `SESSION_TTL_SECONDS` | `604800` (7d) | Login session cookie lifetime |
| `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` | *(unset)* | Optional, for scripted/automated deployments only. Left unset (the default), no admin is seeded at all — the first person to open `/admin` gets an interactive setup screen to choose their own email/password, so no known credential is ever created. Set both only if something needs a working admin login without a human driving that screen on first boot |
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

## Row-level security

Isolation here is pool-based (see "User pools" below, and its note on what pools are *not*
for): every user belongs to exactly one pool, and application code filters every query by
it. Postgres Row-Level Security adds a database-level backstop for that — a query on
`users` that forgot its `user_pool_id` filter returns zero rows instead of another pool's
data, instead of relying on
application code alone getting it right every time.

**This only takes effect if the app connects as a non-superuser role.** Postgres exempts
superusers from RLS unconditionally, and the role in `DB_USER` is commonly a superuser by
default in the official Postgres Docker image (it's the bootstrap role from `initdb`). To
actually enable it:

```bash
docker compose exec postgres psql -U "$DB_USER" -d "$DB_NAME" \
  -c "ALTER ROLE auth_app_runtime WITH PASSWORD 'choose-a-strong-one';"
```

The `auth_app_runtime` role itself is created by a migration (`alembic upgrade head`) with
no usable password until you set one — it can `SELECT`/`INSERT`/`UPDATE`/`DELETE` on the
app's tables, nothing else (no DDL, no superuser). Then set `DB_APP_USER=auth_app_runtime`
and `DB_APP_PASSWORD=<what you chose>` in `.env` and restart. `DB_USER`/`DB_PASSWORD` keep
being used for migrations and the CLI, which still need DDL rights.

Until both steps are done, the app keeps using the same credentials as before — this is
opt-in, not a breaking change on upgrade.

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/openid-configuration` | OpenID Connect Discovery |
| `GET /.well-known/oauth-authorization-server` | The same document under its RFC 8414 path — several MCP clients probe this one first |
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

Everything the CLI can do is also available as a web UI at `/admin`, for operators who'd rather click than run commands. It's a React SPA (`frontend/`) that talks to a JSON API at `/admin/api/*` (`app/admin/api.py`), authenticated by the same admin session cookie as before — see [Local development](#local-development) for how to build/run it:

- **Dashboard** — counts of pools/clients/resources/users, plus a recent-activity preview.
- **User pools** — create pools by name.
- **Clients** — register clients (public or confidential), pick their user pool, toggle **"allow signup"** per client, set/rotate a client's **mTLS certificate thumbprint**, and **disable/re-enable** a client without deleting it (blocks all sign-in and token refresh immediately — for a compromised secret or a retired app, while keeping its history). Clients that registered themselves (DCR or CIMD) are marked with a **Source** badge and can't be edited here.
- **Resources** — register protected APIs/MCP servers.
- **Users** — the manual add-a-user path, for clients with signup disabled; lists/filters existing users by pool; **disable an account** (revokes all sessions and refresh tokens immediately, not just future logins) or **sign it out everywhere** without disabling it.
- **Activity log** — a live, in-memory view of recent logins, token issuance, and security events on this process (also written to stdout as JSON lines — point a real log aggregator there for durable history).
- **Account** — change the admin password.

End users get their own self-service page at `/account` once signed in: change password, manage passkeys, and see/revoke active sessions per device.

The first time `/admin` is opened with no admin account yet in the database, it shows a setup screen instead of a login screen — whoever fills it in becomes the admin, with the email and password they chose themselves. No default credential exists unless you explicitly set `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD` (see [Configuration](#configuration)) for a scripted deployment, in which case that account is seeded flagged `must_change_password` and logged clearly at startup instead. Admin sessions are a separate cookie from end-user sessions, so being signed into `/admin` never grants access to any client's login.

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

MCP clients don't need manual registration — they self-register at connect time, either via `POST /register` (Dynamic Client Registration) or, increasingly, by hosting a JSON document at their own `client_id` URL ([CIMD](https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/), which the MCP spec's 2026-07-28 revision now prefers over DCR — this server supports both, resolving whichever style of `client_id` a request presents). Either way, it's `/.well-known/oauth-protected-resource` + `/.well-known/openid-configuration` that point clients at this server in the first place.

Service-to-service `client_credentials` clients can authenticate with a certificate instead of a shared secret — see [Mutual TLS](#mutual-tls-for-client_credentials-clients).

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

### 3. For a website: the BFF pattern

A website's own backend is a **client** (it logs users in), not a resource server. The pattern that keeps tokens safe: the browser only ever holds an opaque, `HttpOnly` session cookie for *your* backend — access/refresh tokens live server-side and never reach the browser or its JavaScript. When your site needs to call another API on the user's behalf, your backend does it directly and returns the result.

[`examples/website_bff`](examples/website_bff) is a complete, runnable reference for this — register, log in, exchange the code, call a downstream API server-side, log out:

```bash
cd examples/website_bff
uv sync
uv run uvicorn main:app --reload --port 9003
```

### 4. Making it feel embedded: the popup widget

The BFF pattern above still means a full-page navigation away to this service's own `/login` and back. `app/static/js/auth-widget.js` (served at `<issuer>/static/js/auth-widget.js` by every deployment, no build step or install) opens that same login/signup in a **popup** instead — your own button, your own page, your own design; the popup is still this service's own hosted form, so the password still never touches your site's code:

```html
<script src="https://auth.yourdomain.com/static/js/auth-widget.js"></script>
<button id="sign-in">Sign in</button>
<script>
  document.getElementById("sign-in").addEventListener("click", () => {
    AuthWidget.openPopup("/login?popup=1")     // your own login-initiation route
      .then(() => location.reload())            // your session cookie is already set
      .catch((err) => { if (err.message !== "cancelled") alert(err.message); });
  });
</script>
```

Your backend's login/callback routes need two small additions (both shown in [`examples/website_bff/main.py`](examples/website_bff/main.py)):

1. Your `/login` route remembers (alongside its PKCE verifier) that this particular attempt is a popup.
2. Your `/callback` route, after its normal server-side code exchange, returns a tiny HTML page instead of redirecting when it's a popup — one that tells its opener it's done and closes itself:
   ```html
   <script>
     window.opener.postMessage({type: "auth-widget:complete", success: true}, window.location.origin);
     window.close();
   </script>
   ```

For actual branding of the popup's contents (not just the button that opens it), a client can carry a `logo_url` and `brand_color` — set at creation via the admin UI/CLI, or updated any time with `POST /admin/api/clients/{client_id}/branding` — applied to that client's login/signup/consent pages (`app/templates/base.html`).

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
| Admin console | React + Vite + TypeScript + React Router | SPA at `/admin`, talking to a JSON API (`app/admin/api.py`) over the admin session cookie |

## Project structure

```
auth_service/
├── app/
│   ├── main.py                  # FastAPI app entrypoint, router + middleware wiring
│   ├── config.py                # env-based settings (pydantic-settings); builds DB/Redis URLs from parts
│   ├── cli.py                    # admin CLI: register-client, register-resource, create-user, list-*
│   ├── audit.py                  # structured (JSON-lines) audit logging + failed-login anomaly tracking
│   ├── email.py                   # SMTP sender (password reset + verification emails)
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models: UserPool, User, AdminUser, Client, Resource, Consent, RefreshToken, WebAuthnCredential
│   │   ├── pools.py              # get_or_create_pool() -- pools are created implicitly by name
│   │   ├── session.py           # async engine + session factory
│   │   └── redis_client.py      # Redis connection
│   ├── oidc/                     # standard OAuth/OIDC surface, all at root
│   │   ├── discovery.py         # GET /.well-known/openid-configuration
│   │   ├── prm.py                # GET /.well-known/oauth-protected-resource
│   │   ├── authorize.py          # /authorize, /login, /signup, /consent (PKCE + login/signup + consent flow)
│   │   ├── password_reset.py     # /forgot-password, /reset-password, /verify-email, /resend-verification
│   │   ├── webauthn.py           # /webauthn/* (passkey register + login), /account (manage passkeys)
│   │   ├── token.py              # POST /token (auth code, refresh, client_credentials)
│   │   ├── refresh.py            # refresh-token issuance/rotation/revocation (Redis + Postgres audit)
│   │   ├── clients.py            # client authentication (confidential/public/mTLS)
│   │   ├── cimd.py               # Client ID Metadata Document resolution (client_id-as-URL)
│   │   ├── scope.py              # scope resolution against a client's allowed_scope
│   │   ├── pkce.py               # PKCE S256 verification
│   │   ├── keys.py               # RSA key generation/rotation, JWKS
│   │   ├── tokens.py             # JWT minting
│   │   ├── jwks.py               # GET /jwks.json
│   │   ├── register.py           # POST /register (Dynamic Client Registration, RFC 7591)
│   │   ├── revoke.py             # POST /revoke
│   │   └── userinfo.py           # GET /userinfo
│   ├── admin/                     # backs /admin -- operator setup UI (see frontend/ for the SPA itself)
│   │   ├── auth.py                # get_current_admin() session lookup, shared by api.py
│   │   ├── seed.py                # optional admin seeding from DEFAULT_ADMIN_EMAIL/PASSWORD (scripted deployments only)
│   │   └── api.py                 # JSON API under /admin/api/*: login/logout, dashboard, pools, clients, resources, users, account
│   ├── auth/
│   │   ├── passwords.py          # argon2 hashing
│   │   ├── mfa.py                 # TOTP generate/verify
│   │   ├── sessions.py            # Redis-backed login sessions (shared by end-user and admin sessions)
│   │   ├── password_reset.py      # Redis-backed reset/verification tokens
│   │   └── webauthn.py            # WebAuthn RP ID/origin + Redis-backed challenge storage
│   ├── middleware/
│   │   └── rate_limit.py          # slowapi limiter
│   ├── templates/                 # Jinja2 pages: base.html, login.html, signup.html, consent.html, account.html
│   └── static/                    # CSS/JS for the login/consent/account UI (incl. webauthn.js, auth-widget.js)
├── frontend/                      # React SPA for /admin (Vite + TypeScript + React Router)
│   ├── src/
│   │   ├── main.tsx / App.tsx     # entry point, route table
│   │   ├── api.ts                  # typed fetch client for /admin/api/*
│   │   ├── AdminContext.tsx        # current-admin auth state
│   │   ├── theme.ts                # light/dark toggle, persisted to localStorage
│   │   ├── components/             # Layout, Modal, Drawer, Menu, Badge, ConfirmDialog, CopyableId, EmptyState, ToastProvider, PasswordInput
│   │   └── pages/                  # Login, Dashboard, Applications, Users, LoginGroups, Resources, AuditLog, Account
│   └── dist/                      # `npm run build` output; served by app/main.py at /admin (gitignored)
├── alembic/                       # migrations (env.py wired to app.db.models.Base.metadata)
├── tests/                         # pytest + httpx ASGI client, fakeredis, in-memory SQLite
├── examples/
│   ├── example_api/                # runnable protected API built on the SDK
│   ├── mcp_server/                 # runnable MCP-server auth pattern built on the SDK
│   └── website_bff/                 # runnable BFF-pattern website client (no SDK needed -- it's a client, not a resource server)
├── docs/
│   └── architecture.md            # deeper design notes than this README's [Architecture](#architecture) section
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml / uv.lock
├── .env.example                   # copy to .env (gitignored) and fill in real values -- see Configuration
├── SECURITY.md                    # how to report a vulnerability privately
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
└── LICENSE
```

## Security

Found a vulnerability? See [SECURITY.md](SECURITY.md) for how to report it privately instead of opening a public issue.

- PKCE (S256) mandatory on every authorization code exchange
- Refresh tokens are one-time-use: each refresh rotates the token and invalidates the previous one; reuse is rejected
- Refresh token validity lives in Redis (fast revocation check); Postgres keeps the full audit trail (`rotated_from`, `revoked_at`)
- Passwords hashed with Argon2; TOTP MFA supported per-user
- Access tokens are short-lived JWTs (default 10 min), scoped to a single `resource` (RFC 8707) — no ambient all-access tokens
- Rate limiting on `/token`, `/authorize`, and `/admin/login`
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` whenever served over HTTPS; admin sessions use a separate cookie from end-user sessions
- No credentials or connection strings are hardcoded anywhere — `docker-compose.yml` sources them from `.env` via variable interpolation, and the app itself composes URLs from discrete env vars at runtime
- No default admin credential exists — the first person to open `/admin` chooses their own email/password via an interactive setup screen. `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD` (unset by default) are an opt-in escape hatch for scripted deployments only; that account is flagged `must_change_password` until changed via `/admin/account`
- Structured (JSON-lines) audit logging on stdout for every login, signup, token issuance/revocation, admin login, password reset, and DCR registration — `anomalous_activity` events (e.g. repeated failed logins) log at `WARNING` so they're easy to filter for. Wiring these into an actual alert (Slack, PagerDuty, email) is a log-aggregator choice left to your deployment, same as any other 12-factor app.

## Mutual TLS for `client_credentials` clients

For service-to-service clients, a certificate is a stronger authentication method than a shared secret — it proves possession of a private key, not just knowledge of a string. This is disabled by default (`MTLS_TRUSTED_PROXY_SECRET` empty in `.env`) and requires your reverse proxy to actually verify client certificates, since this app itself sits behind nginx and never sees the raw TLS connection.

**1. Register the client with its certificate's thumbprint:**

```bash
uv run python -m app.cli register-client \
  --client-id some-service --type confidential \
  --grant-type client_credentials \
  --mtls-thumbprint "$(openssl x509 -in client.crt -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f')"
```

**2. Generate a proxy secret and set it in `.env`:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**3. Add this to your nginx site config, on the `/token` and `/revoke` locations** (adjust `ssl_client_certificate` to your CA bundle):

```nginx
ssl_client_certificate /etc/nginx/certs/client-ca.pem;
ssl_verify_client optional;  # "optional" so non-mTLS clients still reach /token normally

location ~ ^/(token|revoke)$ {
    proxy_pass http://auth_backend:8113;
    proxy_set_header X-Internal-Proxy-Secret "REPLACE_WITH_THE_SECRET_FROM_STEP_2";
    proxy_set_header X-Client-Cert-Verify $ssl_client_verify;
    proxy_set_header X-Client-Cert-Fingerprint $ssl_client_fingerprint;
}
```

`$ssl_client_fingerprint` is **SHA-1, always** in stock nginx (`ngx_http_ssl_module` has no built-in SHA-256 variant) — step 1's command above registers a SHA-1 thumbprint to match it, no extra tooling required. If you specifically need SHA-256 (stronger collision resistance, but SHA-1 is only used here as an equality-checked lookup key, not for anything cryptographically load-bearing), you'd compute it yourself from `$ssl_client_raw_cert` via an njs (`ngx_http_js_module`) or OpenResty/Lua handler and register that hash instead — nginx doesn't expose it as a plain variable. Whichever you pick, the algorithm on both sides must match.

Once configured for a client, mTLS is *required* for it — a correct `client_secret` alone is no longer accepted, since allowing either would make the certificate requirement pointless.

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
- [x] `/admin` setup UI (pools, clients, resources, users, per-client signup toggle) with an interactive first-run admin setup screen — no default credential
- [x] MCP support: RFC 8707 resource indicators, RFC 9728 protected resource metadata, RFC 7591 Dynamic Client Registration
- [x] Password recovery and email verification
- [x] Passkey (WebAuthn) login, alongside password + TOTP
- [x] Embeddable popup login/signup widget, with per-client branding (logo, color)
- [x] Website integration: BFF pattern (`examples/website_bff`)
- [x] CIMD support: `client_id`-as-URL resolution, per the MCP spec's 2026-07-28 revision preferring it over DCR
- [x] mTLS for `client_credentials` clients (RFC 8705-style cert-thumbprint binding, via reverse-proxy header handoff)
- [x] Observability: structured audit logs, anomalous-issuance alerting

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, running the test suite, and the PR process. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT — see [LICENSE](LICENSE).
