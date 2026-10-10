# Architecture

This document defines every part of the system: what it's made of, how data
flows through it, what's stored where and why, and the trust boundaries that
keep it secure. It goes deeper than the README's Architecture section — read
that first for the one-page version; read this when you need to know exactly
how something works or where to change it.

## Contents

- [1. System context](#1-system-context)
- [2. Component map](#2-component-map)
- [3. Data model](#3-data-model)
- [4. Storage: what lives in Postgres vs. Redis](#4-storage-what-lives-in-postgres-vs-redis)
- [5. Request flows](#5-request-flows)
- [6. Identity model: applications, users, and login groups](#6-identity-model-applications-users-and-login-groups)
- [7. Token lifecycle](#7-token-lifecycle)
- [8. Client authentication methods](#8-client-authentication-methods)
- [9. Session model](#9-session-model)
- [10. Audit logging](#10-audit-logging)
- [11. Key management](#11-key-management)
- [12. Rate limiting](#12-rate-limiting)
- [13. Deployment topology](#13-deployment-topology)
- [14. Trust boundaries](#14-trust-boundaries)
- [15. Extension points](#15-extension-points)
- [16. Known limitations](#16-known-limitations)

---

## 1. System context

Who talks to this service, and as what:

```
                              ┌──────────────────────────┐
                              │                            │
      ┌──────────┐            │                            │            ┌──────────────┐
      │  Browser  │◄──────────┤      AUTH SERVICE          ├───────────►│  Downstream    │
      │  (end     │  cookie,   │  (this repo)                │  fetches   │  API / MCP     │
      │   user)   │  redirects │                            │  JWKS      │  server        │
      └──────────┘            │  - /authorize /login /consent│           │  (resource)    │
                              │  - /token /revoke /userinfo  │           └──────────────┘
      ┌──────────┐            │  - /jwks.json /.well-known/*│
      │  Website  │◄──────────┤  - /register (DCR/CIMD)      │
      │  backend  │  tokens    │  - /webauthn/* /account       │
      │  (client, │  (server-  │  - /forgot-password /verify- │
      │   BFF)    │  side only)│    email                      │
      └──────────┘            │  - /admin/* (operator UI)      │
                              │                                │
      ┌──────────┐            └──────────────┬─────────────────┘
      │  Admin    │◄──────────────────────────┘
      │  operator │  browser, /admin/*
      └──────────┘
                                          │
                       ┌──────────────────┼──────────────────┐
                       ▼                  ▼                  ▼
                 ┌──────────┐      ┌──────────┐      ┌──────────────┐
                 │ Postgres  │      │  Redis    │      │  SMTP server  │
                 │ (durable  │      │ (sessions,│      │  (password    │
                 │  records) │      │  flows,   │      │   reset +     │
                 │           │      │  caches)  │      │   verification│
                 └──────────┘      └──────────┘      │   emails)     │
                                                       └──────────────┘
```

Four kinds of external callers, each with a different relationship to the
service:

| Caller | Role | Ever holds a token? |
|---|---|---|
| End-user browser | Authenticates via `/login`, `/signup`, `/webauthn/*`, gets a session cookie | No — cookie only |
| Website/app backend | OAuth **client** — exchanges codes for tokens | Yes, server-side (BFF pattern — see [`examples/website_bff`](../examples/website_bff)) |
| Downstream API / MCP server | OAuth **resource** — validates tokens it's given | No — it only verifies, never issues |
| Admin operator | Configures the deployment via `/admin` | No — separate admin session, distinct cookie |

## 2. Component map

```
app/
├── oidc/        the standard-compliant OAuth/OIDC surface, mounted at root
├── auth/        low-level auth primitives (hashing, sessions, tokens) -- no HTTP here
├── admin/       the operator-facing setup UI, mounted under /admin
├── db/          SQLAlchemy models, session/Redis plumbing, login-group lookup, RLS scope helpers, contacts
├── audit.py     structured logging + failed-login anomaly tracking
├── email.py     SMTP sending
├── config.py    all settings, one place
└── cli.py       scriptable equivalent of the admin UI
```

Every file in `app/oidc/` maps to one concern:

| File | Owns |
|---|---|
| `authorize.py` | `/authorize`, `/login`, `/signup`, `/consent` — the whole interactive login+consent flow, plus `_load_client`/`_get_flow_client` (used by every other module that needs "which client is this request for") and `_find_user_for_client`/`_user_can_access_client` (the single definition of which users may sign in to which application — see [§6](#6-identity-model-applications-users-and-login-groups)) |
| `token.py` | `/token` — all three grant types share this one endpoint |
| `refresh.py` | Refresh token issuance, rotation, revocation (the logic; `revoke.py` is the HTTP wrapper) |
| `revoke.py` | `POST /revoke` |
| `clients.py` | `get_and_validate_client` — the single place client authentication happens (secret, mTLS, or CIMD-implied-public), called from both `token.py` and `revoke.py` |
| `cimd.py` | Resolves a `client_id` that's itself an HTTPS URL by fetching and caching its metadata document |
| `register.py` | `POST /register` — Dynamic Client Registration (RFC 7591) |
| `scope.py` | `resolve_scope()` — the one function that decides what scope a token actually gets |
| `pkce.py` | S256 challenge/verifier checking |
| `keys.py` / `tokens.py` | RSA key generation/rotation and JWT minting |
| `jwks.py` / `discovery.py` / `prm.py` | The three `.well-known` documents every client/resource bootstraps from |
| `userinfo.py` | `GET /userinfo` |
| `password_reset.py` | `/forgot-password`, `/reset-password`, `/verify-email`, `/resend-verification` |
| `webauthn.py` | `/webauthn/login/*`, `/webauthn/register/*` (via `/account`), `/account` itself |

`app/auth/` is deliberately HTTP-free — every file there is pure logic
(`passwords.py`, `mfa.py`, `sessions.py`, `password_reset.py`, `webauthn.py`)
so it's testable without a request/response cycle, and reusable from both
`oidc/` and `admin/`.

`app/db/` holds the persistence plumbing:

| File | Owns |
|---|---|
| `models.py` | Every table, as SQLAlchemy models — Alembic autogenerates against this |
| `session.py` | Two engines: an owner-privileged one for migrations, the CLI, and first-boot bootstrap, and a runtime one for serving requests (optionally a restricted role, see [§6.3](#63-row-level-security)); also `wait_for_database()` and `init_db_schema()` |
| `pools.py` | `get_or_create_pool()` — login groups are looked up, and created on first use, by name |
| `tenant.py` | The transaction-scoped session variables the Row-Level Security policy on `users` reads |
| `contacts.py` | `upsert_contact()` — the insert-once, first-seen record per email |
| `redis_client.py` | The Redis connection |

`app/admin/api.py` is the JSON API behind the React console in `frontend/`.
It is the only writer for login-group membership, access grants, and roles,
and it serves the user list with server-side search and pagination
(`GET /admin/api/users` returns `{items, total, page, page_size, pages}`;
`page_size` is capped at 200).

## 3. Data model

```
UserPool  (login group -- optional)
   ▲
   │ 0..1     clients.user_pool_id, nullable: NULL = standalone application
   │
Client  (application) ──────────< User ──────────< WebAuthnCredential
   │            users.client_id      │
   │                                 │
   ├──< Consent >────────────────────┤   user × client: scopes approved
   ├──< ClientAccessGrant >──────────┤   user × client: allow-list entry
   ├──< ClientRole                   │
   │        └──< UserRoleAssignment >┘   user × client × role
   └──< RefreshToken                     user_id is a plain string, see below

AdminUser              Resource                    Contact
(global to the         (no FK to anything;         (one row per email ever
 deployment, not        resource_id is referenced   seen; no FK to anything,
 tied to any            by value in RefreshToken    so it outlives users,
 application)           and in JWT `aud`)           applications, and groups)
```

The central relationship is **`users.client_id`**: every account is owned by
exactly one application. A login group does not own users — it only links
applications together, and [§6](#6-identity-model-applications-users-and-login-groups)
describes how that link widens who can sign in where.

| Table | Key columns beyond the obvious | Notes |
|---|---|---|
| `clients` | `client_id` (unique), `user_pool_id` (nullable), `client_type` (public/confidential), `registration_method` (static/dcr/cimd), `enabled`, `allow_signup`, `restrict_access`, `roles_enabled`, `allow_signup_role_selection`, `mtls_cert_thumbprint`, `cimd_fetched_at`, `logo_url`, `brand_color`, `session_ttl_seconds`, `post_logout_redirect_uris` | One table for every registration path — static (CLI/admin), DCR, and CIMD all produce the same row shape. DCR and CIMD rows are always created standalone |
| `users` | `client_id` (FK → `clients.client_id`), unique `(client_id, email)`, partial unique `(client_id, username) WHERE username IS NOT NULL`, `first_name`, `last_name`, `phone`, `status`, `email_verified`, `mfa_secret` | The same email can be two different accounts in two applications. Username and phone are optional; first and last name are required by the self-signup form but nullable in the schema, since admin- and CLI-created users may omit them |
| `user_pools` | `name` | A login group. Nothing but a name — membership is the `clients.user_pool_id` pointer. The name is not unique at the database level; `get_or_create_pool` is what keeps it unique in practice |
| `contacts` | `email` (unique), `first_seen_at`, `first_app`, `first_pool` | Insert-once: written the first time an email is seen at self-signup or admin user creation, never updated. `first_pool` is only filled in for admin-created users. Not written by the CLI's `create-user` |
| `admin_users` | `must_change_password` | Global to the deployment; no relationship to applications or groups |
| `resources` | `resource_id` (the audience string), `enabled` | No FK from anywhere — `resource_id` is referenced by value in `RefreshToken` and in JWT `aud` claims. A disabled resource makes `/token` refuse to mint tokens for that audience |
| `consents` | `user_id` FK, `client_id` FK, `scopes` (JSON list) | One row per user×client the first time they approve; checked on every subsequent `/authorize` to skip the consent screen |
| `client_access_grants` | unique `(client_id, user_id)` | The allow-list for an application with `restrict_access` on. Ignored otherwise |
| `client_roles` | composite PK `(client_id, name)` | A role name defined for one application. This service stores and reports roles; it never enforces what a role may do |
| `user_role_assignments` | unique `(user_id, client_id, role)`, composite FK → `client_roles` | A user can hold several roles on one application. Reported as the `roles` claim in `/userinfo` when the application has `roles_enabled` |
| `refresh_tokens` | `token_hash` (never the raw token), `rotated_from`, `revoked_at` | `user_id` is a plain string column, not a FK — it holds either a real user's UUID *or*, for `client_credentials` tokens, the client_id itself, since `sub` in that grant is the client |
| `webauthn_credentials` | `credential_id` (bytes, unique), `public_key` (bytes), `sign_count` | `sign_count` increments on every use — a value that goes *backwards* is the classic sign of a cloned authenticator |

Deletes are hard deletes. Removing an application removes its users and
every row that references either; removing a user removes their consents,
access grants, role assignments, and passkeys and revokes their sessions and
refresh tokens. The admin API performs these cascades explicitly
(`api_delete_client`, `_hard_delete_user` in `admin/api.py`) rather than
relying on database-level `ON DELETE` behaviour.

Full column-level detail is the migration history in `alembic/versions/` —
that's the authoritative source; this table is the "why," not a copy of
`\d` output that'll drift out of date.

## 4. Storage: what lives in Postgres vs. Redis

The rule: **Postgres holds anything that must survive a restart and be
queried later; Redis holds anything short-lived or purely for fast lookup.**

| In Postgres | In Redis (all namespaced by key prefix, all TTL'd) |
|---|---|
| Applications, users, login groups, consents, access grants, roles and role assignments, admin users, resources, contacts | `session:` / `admin_session:` — login sessions (`sessions.py`) |
| Refresh token records (hash, rotation chain, revocation) | `flow:` — an in-progress `/authorize` attempt (client, PKCE challenge, requested scope) |
| WebAuthn credentials | `code:` — an issued-but-not-yet-exchanged authorization code |
| Everything CIMD/DCR clients resolve to | `refresh:` — the *live* refresh token record, mirroring the Postgres row for O(1) lookup without a DB round-trip; deleted on rotation/revocation, Postgres keeps the historical row |
| | `password_reset:` / `email_verify:` — single-use tokens, deleted on use |
| | `webauthn_reg_challenge:` / `webauthn_auth_challenge:` — in-progress passkey ceremonies |
| | `audit_failed_login:` — sliding-window failed-login counters for anomaly detection |
| | `user_sessions:` — the *set* of session IDs per user, so a password reset can revoke all of them at once |
| | `session_apps:` — per session, when it last authenticated through each application |
| | `app_logout:` — per user, when they were signed out of each application |

Redis is a cache/coordination layer, never the source of truth for anything
that needs to survive a restart with certainty — if Redis is flushed, the
worst case is everyone's logged out and in-flight logins have to restart,
not data loss.

## 5. Request flows

### 5.1 Authorization Code + PKCE (password login)

```
Browser                    Auth Service                  Redis        Postgres
   │  GET /authorize?...code_challenge=...   │              │             │
   ├─────────────────────────────────────────►              │             │
   │                                          │─ store flow ─►             │
   │                                          │◄─ load client ─────────────┤
   │  ◄─────────────── login.html (flow_id) ──┤              │             │
   │  POST /login (email, password)           │              │             │
   ├─────────────────────────────────────────►│─ resolve user (§6), verify ►│
   │                                          │─ create_session ───────────►│
   │  ◄──── consent.html (or skip if consented already) ─────┤             │
   │  POST /consent (approve)                 │              │             │
   ├─────────────────────────────────────────►│─ issue code ──►             │
   │  ◄──── 303 → redirect_uri?code=...&state ┤              │             │
   │                                          │              │             │
   │  (client backend, not browser, from here)│              │             │
   │  POST /token (code, code_verifier, ...)  │              │             │
   ├─────────────────────────────────────────►│─ verify PKCE, consume code ►│
   │                                          │─ mint JWT, issue refresh ──►│
   │  ◄──────── access_token, refresh_token ──┤              │             │
```

Two details the diagram compresses:

- **"Resolve user"** is `_find_user_for_client`: the email is looked up among
  the application's own users, or — if the application is in a login group —
  among the users of every application in that group.
- **An existing session is re-checked, not trusted.** If the browser already
  carries a session cookie, `/authorize` loads that user and asks
  `_user_can_access_client` whether they are eligible for *this*
  application. If not, the cookie is ignored and the login page is shown; it
  is never an error and never grants access across the boundary.

After authentication, `_continue_flow` applies the application's own gate
(`restrict_access` → must hold a `client_access_grants` row, otherwise a 403
on the login page and an `access_denied_not_assigned` audit event) before
consent.

### 5.2 Authorization Code + PKCE (passkey login)

Identical to 5.1 except the browser step is:
```
GET /authorize → login.html
POST /webauthn/login/options (flow_id, email) → challenge + allowed credential IDs
  [browser's WebAuthn API prompts for fingerprint/PIN/security key]
POST /webauthn/login/verify (flow_id, signed assertion) → same _continue_flow()
  as password login from here on -- session created, consent/redirect identical
```

### 5.3 `client_credentials` (service-to-service, no user)

```
Service → POST /token (grant_type=client_credentials, client_id, client_secret OR mTLS)
        ← access_token only (no refresh_token -- there's no user session to renew)
```

`sub` in the resulting JWT is the `client_id` itself — there's no human
involved, so the "subject" is the calling service.

### 5.4 Refresh token rotation

```
Client → POST /token (grant_type=refresh_token, refresh_token=<old>)
Server: look up refresh:<hash> in Redis
        → not found or client mismatch → 400 invalid_grant
        → found → delete it immediately (one-time use), mark Postgres row
          revoked_at=now, mint a NEW access+refresh token pair, issue
Client ← new access_token + new refresh_token (old one is now dead)
```

Reuse of an already-rotated refresh token is rejected outright (the Redis
key is gone) — this is what "one-time-use" buys you: a stolen-and-replayed
old token doesn't work.

### 5.5 Dynamic Client Registration (DCR) vs. CIMD

Two different ways a client acquires a `client_id`, both converging on the
same `clients` table row:

```
DCR:   Client → POST /register {redirect_uris, grant_types, ...}
              ← {client_id: <random>, client_secret?: ...}
              (server generates the ID and, if confidential, the secret)

CIMD:  Client hosts https://client.example.com/metadata.json itself
       Client → GET /authorize?client_id=https://client.example.com/metadata.json&...
       Server: sees client_id looks like a URL → fetches it → checks the
               document's own "client_id" field matches the URL it came
               from → upserts a Client row (registration_method="cimd",
               client_type="public" always) → proceeds as normal
       (no POST step at all -- the document's existence IS the registration;
        re-fetched and refreshed at most once per hour, see cimd.py)
```

MCP's 2026-07-28 spec revision prefers CIMD over DCR; this server supports
both, resolving whichever style of `client_id` a request presents (see
`_load_client` in `authorize.py` and `get_and_validate_client` in
`clients.py` — both branch on `is_cimd_client_id()` before falling back to
a normal DB lookup).

### 5.6 mTLS client authentication

```
Client (with cert) → nginx (verifies cert against ssl_client_certificate CA)
                    → forwards to app with:
                        X-Internal-Proxy-Secret: <shared secret, proves this
                                                   came from nginx, not a
                                                   spoofed direct request>
                        X-Client-Cert-Verify: SUCCESS
                        X-Client-Cert-Fingerprint: <cert thumbprint -- SHA-1 from stock nginx>
App: if client.mtls_cert_thumbprint is set, ALL THREE headers must check out
     (proxy secret matches config, verify=SUCCESS, fingerprint matches) --
     otherwise reject, even if a valid client_secret was also sent
```

See the README's [Mutual TLS](../README.md#mutual-tls-for-client_credentials-clients)
section for the actual nginx config this depends on — that config lives on
your reverse proxy, not in this repo, so it's documented rather than shipped.

### 5.7 Password reset

```
POST /forgot-password (email) → if account exists: Redis token (30 min TTL,
                                  hashed key) + email sent
                               → IDENTICAL response either way (no account-
                                 enumeration leak)
POST /reset-password (token, new password) → consume token (single-use) →
    set new password_hash → revoke_all_sessions_for_user() +
    revoke_all_refresh_tokens_for_user() -- a password reset logs you out
    of every other session/device, on purpose
```

### 5.8 Signup

```
GET  /signup?flow_id=...   → 403 signup_disabled unless the application has allow_signup
POST /signup (first_name, last_name, email, password, confirm_password, [role])
     → validate: names non-empty, passwords match, minimum length
     → reject if (this application, email) already exists
     → INSERT users (client_id = this application, names, Argon2 hash)
     → upsert_contact(email)                       -- insert-once, see §3
     → if restrict_access: INSERT client_access_grants   (signing up through
          an application's own page is the request for access to it)
     → if a role was picked and role selection is enabled: INSERT user_role_assignments
     → create session, send verification email, continue to consent
```

The account is owned by the application whose signup page was used, even
when that application is in a login group. The duplicate check is against
that application only — see [§16](#16-known-limitations).

### 5.9 Email verification

```
Signup → create_email_verification_token() + send it (24h TTL), immediately
         continues the login flow regardless -- verification is
         informational, not a login gate (see plan/password-recovery-mcp-
         passkeys-plan.md §5.2 for why this default was chosen)
GET /verify-email?token=... → consume token → users.email_verified = true
```

### 5.10 Logout

Two forms, same effect — sign one user out of one application:

```
Backend:  POST /logout (client_id, [client_secret], refresh_token)
          → authenticate the client → look up whose refresh token this is
          → 200 {"status": "signed_out"}   |   400 invalid_grant

Browser:  GET /logout?client_id=…[&post_logout_redirect_uri=…&state=…]
          → user taken from the auth service's own session cookie
          → redirect URI must be in clients.post_logout_redirect_uris, else 400
          → 303 back to the application (or the same JSON if none was given)

Both:     app_logout:<user_id>[client_id] = now        (§9.2)
          revoke every refresh token (this user × this client)
          audit event `logout`
```

What is deliberately *not* done: the session and its cookie are kept, and no
other application's tokens are revoked — a logout from one application must
not be felt by another, even inside the same login group. The endpoint
renders no page; the application owns its logout UI. Access tokens already
issued stay valid until they expire, as with any offline-verified JWT.

## 6. Identity model: applications, users, and login groups

### 6.1 Ownership and reach

Two separate questions, answered by two separate columns:

| Question | Answered by | Cardinality |
|---|---|---|
| **Who owns this account?** | `users.client_id` | Exactly one application, always |
| **Which applications can this account sign in to?** | `clients.user_pool_id` on the owning application and on the target application | The owning application, plus every application in the same login group |

```
                    target application has no group        target application is in group G
                   ┌──────────────────────────────────┬───────────────────────────────────────┐
 user is owned by  │                                  │                                       │
 the target app    │              ALLOWED             │                ALLOWED                │
                   ├──────────────────────────────────┼───────────────────────────────────────┤
 user is owned by  │                                  │  ALLOWED if the owning application    │
 another app       │              DENIED              │  is also in G, otherwise DENIED       │
                   └──────────────────────────────────┴───────────────────────────────────────┘
```

Consequences worth stating outright:

- **Isolation is the default.** An application with `user_pool_id IS NULL`
  accepts only its own users. Self-registered clients (DCR, CIMD) are always
  created this way; an admin can group them afterwards.
- **A group is symmetric.** Adding application B to a group that contains A
  lets A's users into B *and* B's users into A.
- **Signup never crosses the boundary.** `/signup` and admin user creation
  always write `client_id` = the application in question, regardless of
  group membership.
- **Uniqueness is per application.** `(client_id, email)` is unique; there is
  no deployment-wide or group-wide uniqueness constraint on email. See
  [§16](#16-known-limitations) for what that means inside a group.
- **Authorization is layered on top.** Passing the check above only means the
  account may *authenticate*. An application with `restrict_access` on then
  also requires a `client_access_grants` row before `_continue_flow` lets the
  flow proceed — the same identity-versus-assignment split other identity
  providers call "app assignment".

### 6.2 Where the rule is enforced

The rule lives in two functions in `oidc/authorize.py`, and every
interactive path goes through one of them:

| Function | Used when you have… | Callers |
|---|---|---|
| `_find_user_for_client(db, email, client)` | an email and need the matching account | `POST /login`, `POST /forgot-password`, `POST /resend-verification`, `POST /webauthn/login/options` |
| `_user_can_access_client(db, user, client)` | an already-identified user and need a yes/no | `GET /authorize` (is the existing session cookie valid for *this* application?), `POST /webauthn/login/verify` |

The admin API applies the same same-application-or-same-group test before
granting access to a restricted application
(`POST /clients/{id}/access`) and before assigning a role
(`POST /users/{id}/roles`), so an admin cannot hand out access or a role to a
user the application could never authenticate anyway.

Paths that identify a user by something other than an application — a
verified JWT (`/userinfo`, the user-status check in `/token`), the session
cookie (`/account`), or a single-use emailed token (`/reset-password`,
`/verify-email`) — load the row by primary key and do not re-apply the rule.

### 6.3 Row-Level Security

The migrations enable and force Row-Level Security on `users`, with one policy:

```sql
CREATE POLICY tenant_isolation ON users
USING (
    current_setting('app.rls_bypass', true) = 'on'
    OR client_id = current_setting('app.tenant_client_id', true)
)
WITH CHECK ( /* same expression */ );
```

`app/db/tenant.py` sets those variables with `SET LOCAL`, so they are scoped
to the transaction and cannot leak to the next request that checks out the
same pooled connection. They also reset on every `COMMIT`, which matters for
any handler that touches `users` again after committing.

| Helper | Effect |
|---|---|
| `set_tenant_client(db, client_id)` | Only that application's rows are visible and writable |
| `bypass_tenant_rls(db)` | All rows; for paths authorized by something other than application membership |
| `set_tenant_pool(db, pool_id)` | Legacy. Sets `app.tenant_pool_id`, which no policy reads any more |

All three are no-ops outside Postgres, and Postgres only applies the policy
when the app connects as a non-superuser role (see the README's
[Row-level security](../README.md#row-level-security) section for the
`DB_APP_USER` setup).

**What it protects against today.** The policy fails closed: a query against
`users` in a transaction that declared nothing returns no rows. That catches
a new code path that reaches user data without having thought about scope
at all.

**What it does not protect against today.** Every request path that reads
users currently calls `bypass_tenant_rls` — necessarily so for group lookups,
which span several applications, and for the admin console — and relies on
its own `client_id` filter. No request path calls `set_tenant_client`. So a
bypassing path with a wrong or missing filter is not caught by the database.
Narrowing the standalone-application paths to `set_tenant_client` is the
natural next step and is listed in [§16](#16-known-limitations).

### 6.4 Lifecycle operations

| Operation | Entry point | Effect |
|---|---|---|
| Create a group | `POST /admin/api/pools`, or implicitly by naming one when registering an application | `get_or_create_pool` — idempotent by name |
| Add an application to a group | `POST /admin/api/pools/{name}/assign-client` | Sets `clients.user_pool_id`. An application is in at most one group, so this also moves it out of any previous one |
| Remove an application from a group | `POST /admin/api/pools/{name}/remove-client` | Sets `clients.user_pool_id = NULL`. The application keeps its own users |
| Delete a group | `DELETE /admin/api/pools/{name}` | Detaches every member application, then deletes the group. No users or applications are deleted |
| Delete an application | `DELETE /admin/api/clients/{client_id}` | Deletes its roles, role assignments, access grants, consents, and refresh tokens; hard-deletes each of its users; deletes the group too if this was its last application |
| Move a user | `PATCH /admin/api/users/{id}` with a new `client_id` | Changes ownership, then revokes all of the user's sessions and refresh tokens |
| Sweep empty groups | `POST /admin/api/maintenance/cleanup-empty-pools` | Deletes every group with no applications. Idempotent |

Changing group membership takes effect on the next `/authorize`, because
eligibility is re-evaluated there on every request, session cookie or not.

### 6.5 Upgrading from the pool-owned model

Earlier versions stored `users.user_pool_id`: accounts belonged to a pool and
every application had to be in one. Migration
`e6f7a8b9c0d1_users_belong_to_clients` converts that data in place, inside one
transaction:

1. Each user is assigned to **one** application from their former pool — the
   first by `client_id` order. Because that application stays in the same
   group, the user can still sign in to every application they could before.
2. Users whose pool had **no applications at all** are **deleted**, together
   with their consents, access grants, role assignments, passkeys, and
   refresh tokens. Such accounts had nothing to sign in to, but if you want
   them, attach an application to the pool before upgrading.
3. Pools left with no applications are deleted.
4. `clients.user_pool_id` becomes nullable, and the RLS policy is replaced
   with the `client_id`-based one above.

Two neighbouring migrations in the same release drop the `deleted_at`
soft-delete columns from `clients` and `users`; deletion is a hard delete
from here on. Take a database backup before running `alembic upgrade head`
across these revisions. A `downgrade()` exists and restores the old columns
and policy, but it cannot bring back rows deleted in step 2 or 3.

## 7. Token lifecycle

```
mint (tokens.py)              validate (any resource server,               expire
                                via authservice-client or equivalent)
  │                                    │                                     │
  ├─ short-lived JWT (default 10 min)  ├─ fetch JWKS (cached), verify        │
  ├─ signed RS256, kid-tagged          │  signature/exp/iss/aud locally --   │
  ├─ aud = the single `resource`       │  NO call back to this service       │
  │  it was requested for (RFC 8707)   │  per request                       │
  ├─ scope = resolve_scope() output    │                                    │
  │  (never wider than the client's    │                                    │
  │  allowed_scope, see §7.1)          │                                    │
  └────────────────────────────────────┴────────────────────────────────────┘
```

### 7.1 Scope resolution (`scope.py`)

`resolve_scope(requested, allowed)` is the one function every grant type
funnels through before minting a token. Its job: a client can never get a
token with more scope than it's `allowed_scope` permits, and an empty
`requested` scope doesn't silently mean "no scope" for `client_credentials`
or `refresh_token` grants (a real bug this function was written to fix —
see its docstring/tests).

### 7.2 Refresh tokens

Not JWTs — an opaque `secrets.token_urlsafe(48)` string. Only its SHA-256
hash is ever stored (Postgres `token_hash` column, Redis key). One-time use:
every refresh mints a new refresh token and immediately invalidates the one
just used (`rotated_from` links the chain in Postgres for audit purposes).

## 8. Client authentication methods

`get_and_validate_client()` in `clients.py` is the single chokepoint for
"is this client who it says it is" — every method below is a branch in that
one function, in this priority order:

1. **CIMD-implied public** — if `client_id` is a URL, it's always public
   (no secret possible, since there's no registration step to hand one out)
2. **mTLS** — if the client row has `mtls_cert_thumbprint` set, this is
   *required*; a correct `client_secret` is no longer sufficient once mTLS
   is configured (see [§5.6](#56-mtls-client-authentication))
3. **`client_secret_post`** — confidential clients, secret sent as a form
   field, checked against the Argon2 hash
4. **None** — public clients (native apps, SPAs, CIMD/most DCR clients)
   authenticate via PKCE alone; sending a secret when none is expected is
   rejected, not silently ignored

## 9. Session model

Two entirely separate session types, sharing the same underlying Redis
mechanism (`auth/sessions.py`) but different cookies and TTLs:

| | End-user session | Admin session |
|---|---|---|
| Cookie name | `auth_session` | `admin_session` |
| TTL | 7 days | 12 hours |
| Scoped to | The user's own application and its login group (re-checked on every `/authorize`) | The whole deployment |
| Created by | `/login`, `/signup`, `/webauthn/login/verify` | `/admin/login` |

### 9.1 Per-application sign-in timeout

The cookie is shared, but an application can decide for itself how long a
sign-in is good for (`clients.session_ttl_seconds`, 5 minutes to 30 days).
The measure is fixed time since the user last really authenticated —
activity does not extend it.

`0` means no per-application limit, and it is the column default: clients
that register themselves (DCR, CIMD — in practice MCP clients and AI
assistants), clients added from the CLI, and service clients all get it, and
behave exactly as they did before the setting existed. Only websites added
through the admin console start with a limit (7 days). Every check below is
skipped when the value is `0`.

- `sessions.sign_in()` records, in `session_apps:<session_id>`, the moment the
  session authenticated through a given application. It reuses the browser's
  existing session when it belongs to the same user.
- `sessions.app_auth_time()` answers "when did this session authenticate for
  application X?". An application the session has never signed in through
  inherits the session's most recent sign-in, which is what lets single
  sign-on work across a login group.
- `GET /authorize` shows the login page when that time is older than the
  application's timeout.
- The same time travels with the flow → authorization code → refresh token
  (`auth_time`). `issue_refresh_token` never gives a token a lifetime past
  `auth_time + session_ttl_seconds`, rotation carries `auth_time` forward
  unchanged, and `/token` re-checks it against the application's *current*
  setting — so shortening the timeout applies to people already signed in.

The global `SESSION_TTL_SECONDS` still bounds the cookie itself: an
application timeout longer than it only has an effect through refresh tokens.

### 9.2 Per-application logout

`sessions.sign_out_app()` writes the logout time to
`app_logout:<user_id>[client_id]`. From then on `app_auth_time()` ignores the
inherited sign-in for that application and accepts only a sign-in made
through that application itself, after the logout. Nothing else is touched:
the session, the cookie, and every other application's state stay as they
were. See [§5.10](#510-logout) for the endpoint.

Every session ID also gets added to a `user_sessions:<user_id>` Redis set,
so `revoke_all_sessions_for_user()` (used after a password reset) can find
and delete every session a user has, not just the current one.

## 10. Audit logging

`app/audit.py` emits one JSON object per line to stdout for every
security-relevant event — see the full list of event names and where each
fires in the table below. This is a log line, not a notification; wiring it
into an actual alert (Slack, PagerDuty, email) is a log-aggregator choice
left to your deployment, same as any other 12-factor app.

| Event | Fires when | Level |
|---|---|---|
| `login_success` / `login_failure` | Password login result | INFO / WARNING |
| `signup_success` | New account created | INFO |
| `access_denied_not_assigned` | Authenticated user isn't on a restricted application's allow-list | WARNING |
| `password_changed` / `session_revoked` / `sessions_revoked_others` | End user acts on their own `/account` page | INFO |
| `admin_setup_completed` | First-run admin account created | INFO |
| `admin_login_success` / `admin_login_failure` | Admin login result | INFO / WARNING |
| `webauthn_login_success` / `webauthn_registered` | Passkey used / added | INFO |
| `token_issued` | Every successful `/token` call, any grant type | INFO |
| `token_revoked` | `/revoke` called | INFO |
| `logout` | A user is signed out of one application (`via` = `browser` or `backchannel`) | INFO |
| `client_registered` | DCR or CIMD produces a new client row | INFO |
| `mtls_auth_failed` | mTLS required but verification failed | (via `login_failure`-style call sites) |
| `password_reset_requested` / `password_reset_completed` | Forgot-password flow | INFO |
| `email_verified` | Verification link used | INFO |
| `anomalous_activity` | 5+ failed logins for the same email or IP within 5 minutes | WARNING |
| `client_assigned_to_pool` / `client_removed_from_pool` | Admin changes an application's login group | INFO |
| `pool_deleted` / `cleanup_empty_pools` | Admin deletes a login group / sweeps empty ones | INFO |
| `client_enabled` / `client_disabled` / `client_deleted` | Admin changes an application's state | INFO |
| `client_restrict_access_enabled` / `client_restrict_access_disabled` | Admin toggles an application's allow-list | INFO |
| `client_access_granted` / `client_access_revoked` | Admin edits an allow-list | INFO |
| `user_role_assigned` / `user_role_unassigned` / `client_role_deleted` | Admin edits roles | INFO |
| `user_active` / `user_disabled` / `user_deleted` | Admin changes an account's state | INFO |
| `user_client_changed` | Admin moves a user to another application | INFO |
| `user_signed_out_by_admin` | Admin revokes a user's sessions and refresh tokens | INFO |
| `resource_created` / `resource_updated` / `resource_enabled` / `resource_disabled` / `resource_deleted` | Admin edits a protected resource | INFO |

Events for changes made in the admin console carry `admin_id`, so the log
answers "who changed this" as well as "what changed".

Anomaly detection (`record_failed_login` in `audit.py`) uses a Redis
counter with a sliding TTL window, separately keyed per email and per IP —
either crossing the threshold fires the event, so both "someone hammering
one account" and "one IP hammering many accounts" get caught.

## 11. Key management

- RSA keypairs, generated on first boot if none exist (`keys.py`), stored
  under `SIGNING_KEY_DIR` (bind-mounted in Docker so they survive container
  recreation — losing them would invalidate every outstanding token).
- Every key is `kid`-tagged; `/jwks.json` publishes all currently-valid
  public keys, so rotation is: generate a new key, start signing with it,
  keep the old public key published until every token signed with it has
  expired, then drop it.
- Resource servers cache the JWKS response and only re-fetch on a
  cache-miss `kid` — rotation doesn't require coordinating a flag day with
  every downstream service.

## 12. Rate limiting

`slowapi`, in-memory, keyed by remote address, applied per-endpoint via
`@limiter.limit(...)`:

| Endpoint | Default limit |
|---|---|
| `/token` | 20/minute |
| `/authorize` | 30/minute |
| `/admin/login` | 10/minute |
| `/forgot-password`, `/resend-verification` | 5/hour |

In-memory means single-process — if you horizontally scale the app behind
a load balancer, each instance rate-limits independently (a real limitation
worth knowing, not a hidden one).

## 13. Deployment topology

```
Internet ──► nginx (TLS termination, optional mTLS cert verification) ──► auth-service (Docker, port 8113)
                                                                                │
                                                              ┌─────────────────┼─────────────────┐
                                                              ▼                 ▼                 ▼
                                                          Postgres           Redis          SMTP (external)
                                                          (bind-mounted      (bind-mounted
                                                           volume)            volume, AOF off --
                                                                               see README's Redis
                                                                               persistence note)
```

- `init_db_schema()` bootstraps a genuinely empty database on first boot
  (creates tables, stamps Alembic to head) so a fresh deploy doesn't crash
  before anyone's run a migration — but it's a no-op the moment
  `alembic_version` exists, so it never touches an already-managed database.
  Schema *changes* after that point are always manual (`alembic upgrade
  head`), on purpose — see the README's Database migrations section for why
  auto-migrate-on-boot was explicitly rejected for this project.
- `wait_for_database()` retries the first DB connection instead of trusting
  Docker's `depends_on: condition: service_healthy` alone — `pg_isready`
  can report healthy during Postgres's brief internal re-init cycle on a
  fresh volume.

## 14. Trust boundaries

Explicitly, the things this service trusts and why:

- **nginx is trusted to terminate TLS and not lie about client certs.**
  This is why the mTLS headers require a separate shared secret
  (`X-Internal-Proxy-Secret`) — without it, "trust nginx" would silently
  become "trust whatever reaches the app on port 8113," which is a much
  bigger, unintended trust boundary the moment the app is reachable
  directly (e.g., misconfigured Docker networking).
- **CIMD documents are trusted only as far as their self-consistency
  check.** The server verifies the fetched document's `client_id` field
  matches the URL it was fetched from — this stops one client from
  presenting another's document, but it does *not* verify domain
  ownership beyond "this HTTPS URL served this content just now." That's
  the same trust model the IETF draft itself specifies, not a
  simplification made here.
- **Redis and Postgres are trusted implicitly** — anyone with network
  access to either has access to session tokens (Redis) or password
  hashes and refresh-token hashes (Postgres). Neither is exposed outside
  the Docker network in the reference `docker-compose.yml`.

## 15. Extension points

Where to actually make a change, for the most common asks:

| I want to... | Start here |
|---|---|
| Add a new OAuth grant type | `token.py`'s `if grant_type == ...` chain, plus `Client.grant_types` validation in `register.py`/`cli.py` |
| Add a new client authentication method | `clients.py::get_and_validate_client` — follow the mTLS branch as a template |
| Add a new login method (beyond password/TOTP/passkey) | A new module under `app/auth/`, a new router under `app/oidc/`, and a branch in `_continue_flow`'s callers, same shape as `webauthn.py`. Resolve the user with `_find_user_for_client` so the method inherits the login-group rule |
| Change who can sign in where | `authorize.py::_find_user_for_client` and `_user_can_access_client` — the only two places the rule is written down ([§6.2](#62-where-the-rule-is-enforced)) |
| Add a user profile field | `db/models.py` + a migration; `_user_json`, `CreateUserBody`, and `EditUserBody` in `admin/api.py`; `AppUser` in `frontend/src/api.ts`; the forms in `frontend/src/pages/Users.tsx`; `signup.html` and the `signup` handler if end users should supply it |
| Expose profile fields to applications | `userinfo.py` — it currently returns `sub`, `email`, and (when enabled) `roles` |
| Make another field searchable in the admin user list | The `or_(...)` clause in `admin/api.py::api_list_users` |
| Change what's in the JWT | `tokens.py::mint_access_token` |
| Add a new audit event | `app.audit.log_event(...)` at the relevant call site — no registration step, it's just a function call |
| Change session/token lifetimes | `config.py` — every TTL is a named setting, nothing hardcoded inline. Per-application sign-in timeout is `clients.session_ttl_seconds`, enforced in `auth/sessions.py`, `authorize.py`, and `token.py` |
| Change what logout does | `oidc/logout.py::_sign_out` |

## 16. Known limitations

Open items in the current implementation, stated plainly so nobody has to
rediscover them.

1. **Email is not unique across a login group.** Uniqueness is
   `(client_id, email)`. The self-signup duplicate check and the admin
   create-user check both look only at the target application, and grouping
   two applications does not check for overlap. If the same email ends up
   registered to two applications in one group, `_find_user_for_client`
   matches two rows and its `scalar_one_or_none()` raises, so password login,
   forgot-password, resend-verification, and passkey login fail with a server
   error for that email on every application in the group. Until this is
   enforced, check for overlapping emails before grouping applications, and
   point users at "Sign in" rather than "Sign up" on a second application in
   the same group.
2. **Row-Level Security is not yet narrowed per application.** As described in
   [§6.3](#63-row-level-security), every user-reading path uses the bypass.
   In addition, `GET /authorize` loads the session's user without declaring
   any RLS scope at all; under a restricted runtime role that lookup returns
   nothing, so an existing session is not recognised and the user is asked to
   sign in again. Separately, a database bootstrapped by `init_db_schema()` on
   first boot ([§13](#13-deployment-topology)) is built from the models and
   stamped to head without running any migration, so it has neither the
   policy nor the `auth_app_runtime` role. Deployments that rely on RLS
   should confirm the policy exists (`\d users` in `psql`) and re-verify the
   login, signup, and SSO paths end to end. (Identified by reading the code;
   RLS is not covered by the automated tests, which run on SQLite.)
3. **Regrouping does not revoke tokens already issued.** Removing an
   application from a group stops new sign-ins from the other applications'
   users at `/authorize`, but refresh tokens those users already hold for it
   keep working until they expire or are revoked — `/token` checks that the
   user is active, not that they are still eligible for the application. Use
   "sign out everywhere" on the affected users if the cut-off must be
   immediate.
4. **Group views in the admin console load at most 200 users.** The Login
   groups page and an application's Manage dialog request a single page of
   500, and `GET /admin/api/users` caps `page_size` at 200. Larger groups are
   listed incompletely there; the Users page, which paginates properly, is
   unaffected.
5. **Profile fields are admin-facing only.** `first_name`, `last_name`,
   `username`, and `phone` are stored and editable in the admin console but
   are not released to applications as `/userinfo` claims, and the CLI's
   `create-user` does not set them.
6. **The test suite predates this model.** `tests/helpers.py` still creates
   users with `user_pool_id`, the signup tests don't send first and last
   name, and the CLI tests call the old command signatures. At the time of
   writing 58 of 133 tests fail.
