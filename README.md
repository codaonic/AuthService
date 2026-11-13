# Auth Service

A self-hosted **OAuth 2.1 and OpenID Connect** authorization server for your websites, mobile apps, APIs and MCP servers. One service owns sign-in, accounts and tokens; everything else verifies standard JWTs.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688)
![License](https://img.shields.io/badge/license-MIT-green)

## Quickstart

```bash
docker network create nginx-proxy-net   # once
cp .env.example .env
docker compose up -d --build
docker compose exec app uv run alembic upgrade head
```

Open `http://localhost:8113/admin` and create the first admin account.

## Contents

- [Features](#features)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Concepts](#concepts)
- [Integrating](#integrating)
- [Endpoints](#endpoints)
- [Admin console](#admin-console)
- [Security](#security)
- [Operations](#operations)
- [Development](#development)
- [Roadmap](#roadmap)
- [Contributing](#contributing) · [License](#license)

## Features

**Standards**
- OAuth 2.1: authorization code with mandatory PKCE (S256), refresh-token rotation, `client_credentials`
- OpenID Connect: ID tokens, discovery, `/userinfo`, `prompt` (`none`, `login`, `consent`), `max_age`, `login_hint`
- Token introspection (RFC 7662) and revocation (RFC 7009), `client_secret_basic` and `client_secret_post`
- Back-channel logout (OIDC), sent only to the app being signed out of
- Resource indicators (RFC 8707), protected resource metadata (RFC 9728)
- Dynamic client registration (RFC 7591) and client ID metadata documents (CIMD) for MCP clients
- mTLS client authentication for service-to-service clients

**Sign-in**
- Hosted login, signup, password reset and email verification
- Passkeys (WebAuthn) and TOTP two-factor
- Redirect, popup (`auth-widget.js`) or embedded in your own page (`auth-elements.js`)
- Optional "verified email required" per app or per API
- Per-app sign-in timeout and per-app logout

**Access control**
- Login groups: apps that share one account per person (single sign-on)
- Restricted apps: only chosen people or teams can sign in
- Teams with sub-teams, granting app access and roles
- Composite roles, delivered in access tokens, ID tokens and `/userinfo`
- Access that ends on a date, and an access review per app
- Losing access takes effect immediately, including for tokens already issued

**Operations**
- Admin console with live updates, analytics and an activity log
- Audit events stored in Postgres; JSON lines on stdout
- Argon2 passwords, rotating RS256 keys, rate limits and lockouts
- Optional Postgres row-level security as a backstop

## Getting started

### Docker Compose (server)

The stack runs Postgres, Redis and the app on port **8113**, behind a reverse proxy on the external Docker network `nginx-proxy-net`.

```bash
docker network create nginx-proxy-net
cp .env.example .env      # set ISSUER=https://auth.yourdomain.com and real credentials
docker compose up -d --build
docker compose exec app uv run alembic upgrade head
```

Point your proxy at `http://auth_backend:8113`. The OAuth endpoints are at the root, the admin console at `/admin`, API docs at `/docs` (set `API_DOCS_ENABLED=false` in production).

The container runs as uid `10001`. Keep the signing keys owner-only:

```bash
sudo chown -R 10001:10001 data/signing_keys
sudo chmod 700 data/signing_keys && sudo chmod 600 data/signing_keys/*
```

Migrations are not automatic: run `alembic upgrade head` after every upgrade.

### Local development

Use the Compose databases (published on loopback only) and run the app on the host:

```bash
docker compose up -d postgres redis      # 127.0.0.1:5434 and 127.0.0.1:6381
uv sync
uv run alembic upgrade head
DB_HOST=127.0.0.1 DB_PORT=5434 REDIS_HOST=127.0.0.1 REDIS_PORT=6381 \
  uv run uvicorn app.main:app --reload    # http://localhost:8000
```

Build the admin console once, or run its dev server with hot reload:

```bash
cd frontend && npm install
npm run build    # served by the app at /admin
npm run dev      # http://localhost:5173/admin, proxies /admin/api to :8000
```

## Configuration

Settings come from `.env` (see `.env.example`). Connection URLs are built from the parts below and never set directly.

| Variable | Default | Purpose |
|---|---|---|
| `ISSUER` | `http://localhost:8000` | Public URL of this service; the `iss` of every token |
| `DB_USER` `DB_PASSWORD` `DB_HOST` `DB_PORT` `DB_NAME` | `auth` `auth` `localhost` `5432` `auth` | Postgres, used for migrations and the CLI |
| `DB_APP_USER` `DB_APP_PASSWORD` | same as `DB_USER` | Role the running app uses; see [Row-level security](#row-level-security) |
| `REDIS_HOST` `REDIS_PORT` `REDIS_DB` `REDIS_PASSWORD` | `localhost` `6379` `0` | Redis |
| `SIGNING_KEY_DIR` | `./keys` | RSA signing keys |
| `ACCESS_TOKEN_TTL_SECONDS` | `600` | Access and ID token lifetime |
| `REFRESH_TOKEN_TTL_SECONDS` | `2592000` (30 days) | Refresh token lifetime |
| `SESSION_TTL_SECONDS` | `604800` (7 days) | Browser sign-in session |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` | unset, `587` | Email. Without it, links show on the dashboard to send by hand |
| `EMAIL_FROM_ADDRESS` `EMAIL_FROM_NAME` | `no-reply@localhost` | Email sender |
| `LOGIN_MAX_FAILURES` `LOGIN_LOCKOUT_SECONDS` | `10`, `900` | Failed-login lockout |
| `RATE_LIMIT_*` | see `app/config.py` | Per-IP limits on sensitive endpoints |
| `AUDIT_RETENTION_DAYS` | `90` | How long activity is kept |
| `MTLS_TRUSTED_PROXY_SECRET` | unset | Enables mTLS; see [mTLS](#mtls-for-service-clients) |
| `API_DOCS_ENABLED` | `true` | Serve `/docs` |
| `DEFAULT_ADMIN_EMAIL` `DEFAULT_ADMIN_PASSWORD` | unset | Seed an admin for scripted installs only |
| `HOST_PORT` (shell) | `8113` | Host port for `docker compose up` |

## Concepts

| Concept | Meaning |
|---|---|
| **Application** | Anything that signs people in or requests tokens (an OAuth client) |
| **API / MCP server** | A resource: the audience of an access token |
| **Account** | Belongs to the application it was created through |
| **Login group** | Applications that share accounts. One email is one account in a group |
| **Team** | People who get the same app access and roles. Sub-teams inherit everything |

Rules:
1. Applications are isolated unless they are in the same login group.
2. A restricted application lets in only the people and teams you choose.
3. Teams never reach outside a login group.
4. Signing out of one application leaves the others signed in.
5. Removing access ends that sign-in at once: refresh stops, `/introspect` reports the token inactive, and the app's back-channel logout URL is called.

## Integrating

The admin console's **Integration Guide** generates ready-to-copy code for each application and API.

### Websites and apps (OpenID Connect)

Any OIDC library works. Configure it with:

| Setting | Value |
|---|---|
| Discovery URL | `https://auth.yourdomain.com/.well-known/openid-configuration` |
| Client ID / secret | From the admin console |
| Scopes | `openid email profile` (add `offline_access` for mobile) |
| Extra parameter | `resource=https://api.yourdomain.com` |

You receive an access token for your API, an ID token for your app, and a refresh token. Roles appear in both tokens when the application uses roles.

For logout, send the browser to `/logout?id_token_hint=...&post_logout_redirect_uri=...`. To have your server told about sign-outs, set a **back-channel logout URL** on the application.

### APIs and MCP servers

Verify the access token locally with the JWKS: signature (RS256), `iss`, `aud` (your resource ID) and `exp`. The [`auth-client`](https://github.com/codaonic/auth-client) SDK does this for Python, Node and Go:

```python
from auth_client import TokenValidator
from auth_client.fastapi import make_auth_dependency

validator = TokenValidator(issuer="https://auth.yourdomain.com/", resource_id="https://api.yourdomain.com")
require_auth = make_auth_dependency(validator)
```

For MCP, answer unauthenticated requests with `401` and `WWW-Authenticate: Bearer resource_metadata="<issuer>/.well-known/oauth-protected-resource?resource=<your id>"`. Claude, Cursor and other clients then discover this service and register themselves.

To reject tokens the moment access is removed, call `/introspect` with a confidential application's credentials.

### Service to service

```bash
curl -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d grant_type=client_credentials -d resource=https://api.yourdomain.com \
  https://auth.yourdomain.com/token
```

### Embedded and popup sign-in

- `auth-elements.js` shows sign-in inside your page in your colors; the password stays in a frame served by this service.
- `auth-widget.js` opens sign-in in a popup from your own button.

Examples: [`examples/website_bff`](examples/website_bff), [`examples/example_api`](examples/example_api), [`examples/mcp_server`](examples/mcp_server).

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/openid-configuration` | OIDC discovery (also at `/.well-known/oauth-authorization-server`) |
| `GET /.well-known/oauth-protected-resource` | Protected resource metadata, per `resource=` |
| `GET /jwks.json` | Signing keys |
| `GET /authorize` | Start a sign-in |
| `POST /token` | Code, refresh and `client_credentials` grants |
| `GET /userinfo` | Profile and roles for an access token |
| `POST /introspect` | Is this token still good? (RFC 7662) |
| `POST /revoke` | Revoke an access or refresh token (RFC 7009) |
| `GET` `POST /logout` | Sign out of one application |
| `POST /register` | Dynamic client registration |
| `GET /account` | People's own page: password, passkeys, devices, signed-in apps, teams they manage |
| `GET /healthz` | Liveness |

Full schemas are at `/docs`.

## Admin console

`/admin` covers:

- **Dashboard**: counts, last 7 days, recent activity, emails that couldn't be sent
- **Applications**: sign-in settings, people and access, roles, branding, back-channel logout, integration guide
- **APIs & MCP servers**: register, require a verified email, stop issuing tokens
- **Users**: search, edit, verify email, reset password, sign out, teams
- **Login groups** and **Teams**
- **Analytics** and **Activity log**, updating live

The first visit shows a setup screen to create the admin. There is no default password. Everything is also available through `/admin/api/*` and the CLI (`uv run python -m app.cli --help`).

## Security

Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

- PKCE required; refresh tokens are single-use, and a replayed one ends that sign-in
- Access tokens last 10 minutes and are bound to one API (`aud`)
- Refresh and `/introspect` re-check the account, the login group and access on every call
- Lockout counts failures per email and IP, so others can't lock a person out
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` over HTTPS; admin sessions are separate
- No credentials in code or Compose files; no default admin

### Row-level security

Postgres row-level security on `users` returns no rows unless a request declares its scope. It applies only when the app connects as a non-superuser:

```bash
docker compose exec postgres psql -U "$DB_USER" -d "$DB_NAME" \
  -c "ALTER ROLE auth_app_runtime WITH PASSWORD 'choose-a-strong-one';"
```

Then set `DB_APP_USER=auth_app_runtime` and `DB_APP_PASSWORD` in `.env` and restart. Details: [docs/architecture.md](docs/architecture.md#63-row-level-security).

### mTLS for service clients

1. Register the client with its certificate's SHA-1 thumbprint:
   ```bash
   uv run python -m app.cli register-client --client-id some-service --type confidential \
     --grant-type client_credentials \
     --mtls-thumbprint "$(openssl x509 -in client.crt -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f')"
   ```
2. Set `MTLS_TRUSTED_PROXY_SECRET` in `.env` to a random value.
3. Have nginx verify the certificate and forward it on `/token` and `/revoke`:
   ```nginx
   ssl_client_certificate /etc/nginx/certs/client-ca.pem;
   ssl_verify_client optional;

   location ~ ^/(token|revoke)$ {
       proxy_pass http://auth_backend:8113;
       proxy_set_header X-Internal-Proxy-Secret "<the secret>";
       proxy_set_header X-Client-Cert-Verify $ssl_client_verify;
       proxy_set_header X-Client-Cert-Fingerprint $ssl_client_fingerprint;
   }
   ```

Once set, the certificate is required for that client; a secret alone is refused.

## Operations

**Upgrading:** pull, `docker compose up -d --build`, then `docker compose exec app uv run alembic upgrade head`. New settings default to the previous behaviour.

**Changed `DB_PASSWORD` after the first start?** Postgres keeps the original password. Update it in place:

```bash
set -a; source .env; set +a
docker exec -it auth_pgsql psql -U "$DB_USER" -d "$DB_NAME" -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
```

**Container names:** Compose services are `app`, `postgres`, `redis`; containers are `auth_backend`, `auth_pgsql`, `auth_redis`.

## Development

```bash
uv run pytest                 # offline: in-memory SQLite and fakeredis
uv run alembic revision --autogenerate -m "describe the change"
cd frontend && npx tsc --noEmit
```

Row-level security is Postgres-only and isn't covered by the test suite. Some older tests still target the previous user model.

```
app/
  oidc/      OAuth and OIDC endpoints, tokens, logout, introspection
  auth/      passwords, sessions, teams, access checks, lockout
  admin/     admin API
  db/        models, sessions, row-level security helpers
frontend/    admin console (React, Vite)
alembic/     migrations
examples/    runnable integrations
docs/        architecture notes
```

## Roadmap

- [x] OAuth 2.1 and OpenID Connect core, discovery, JWKS
- [x] Dynamic client registration, CIMD, resource indicators, protected resource metadata
- [x] Passkeys, TOTP, password reset, email verification
- [x] Login groups, restricted apps, per-app sign-in timeout and logout
- [x] Popup and embedded sign-in (`auth-widget.js`, `auth-elements.js`)
- [x] mTLS for service clients
- [x] Admin console with analytics and live activity
- [x] One account per email in a login group
- [x] Teams, composite roles, roles in tokens
- [x] ID tokens, introspection, back-channel logout
- [ ] Port the remaining tests to the per-application user model
- [ ] Sign in with Google, Microsoft or any OIDC provider, per application
- [ ] Webhooks for user and sign-in events
- [ ] Multi-tenant hosting: per-tenant issuer, keys, admins and settings
- Not planned unless needed: SAML, LDAP / Active Directory

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT. See [LICENSE](LICENSE).
