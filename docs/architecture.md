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
- [6. Multi-tenancy: user pools](#6-multi-tenancy-user-pools)
- [7. Token lifecycle](#7-token-lifecycle)
- [8. Client authentication methods](#8-client-authentication-methods)
- [9. Session model](#9-session-model)
- [10. Audit logging](#10-audit-logging)
- [11. Key management](#11-key-management)
- [12. Rate limiting](#12-rate-limiting)
- [13. Deployment topology](#13-deployment-topology)
- [14. Trust boundaries](#14-trust-boundaries)
- [15. Extension points](#15-extension-points)

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
├── db/          SQLAlchemy models + session/pool/Redis plumbing
├── audit.py     structured logging + failed-login anomaly tracking
├── email.py     SMTP sending
├── config.py    all settings, one place
└── cli.py       scriptable equivalent of the admin UI
```

Every file in `app/oidc/` maps to one concern:

| File | Owns |
|---|---|
| `authorize.py` | `/authorize`, `/login`, `/signup`, `/consent` — the whole interactive login+consent flow, plus `_load_client`/`_get_flow_client` (used by every other module that needs "which client is this request for") |
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

## 3. Data model

```
UserPool ──┬──< User ──< Consent >── Client >── RefreshToken
           │              (user_id,             (client_id FK,
           │               client_id FK)          user_id as plain
           │                                       string, see below)
           └──< Client

User ──< WebAuthnCredential

AdminUser                    Resource
(entirely separate --        (standalone -- no FK
 not scoped to a pool)         to anything; resource_id
                                is just a string every
                                other table references
                                by value, e.g. RefreshToken
                                .resource_id, never a FK)
```

| Table | Key columns beyond the obvious | Notes |
|---|---|---|
| `user_pools` | `name` | The unit of identity isolation — see [§6](#6-multi-tenancy-user-pools) |
| `users` | `user_pool_id`, unique `(user_pool_id, email)`, `email_verified`, `mfa_secret` | Same email can exist in two different pools as two different accounts |
| `clients` | `user_pool_id`, `client_type` (public/confidential), `registration_method` (static/dcr/cimd), `mtls_cert_thumbprint`, `cimd_fetched_at` | One table for every registration path — static (CLI/admin), DCR, and CIMD all produce the same row shape |
| `admin_users` | — | Not pool-scoped at all; admins are global to the deployment, not per-tenant |
| `resources` | `resource_id` (the audience string) | No FK from anywhere — `resource_id` is referenced by value in `RefreshToken` and in JWT `aud` claims |
| `consents` | `user_id` FK, `client_id` FK, `scopes` (JSON list) | One row per user×client the first time they approve; checked on every subsequent `/authorize` to skip the consent screen |
| `refresh_tokens` | `token_hash` (never the raw token), `rotated_from`, `revoked_at` | `user_id` is a plain string column, not a FK — it holds either a real user's UUID *or*, for `client_credentials` tokens, the client_id itself, since `sub` in that grant is the client |
| `webauthn_credentials` | `credential_id` (bytes, unique), `public_key` (bytes), `sign_count` | `sign_count` increments on every use — a value that goes *backwards* is the classic sign of a cloned authenticator |

Full column-level detail is the migration history in `alembic/versions/` —
that's the authoritative source; this table is the "why," not a copy of
`\d` output that'll drift out of date.

## 4. Storage: what lives in Postgres vs. Redis

The rule: **Postgres holds anything that must survive a restart and be
queried later; Redis holds anything short-lived or purely for fast lookup.**

| In Postgres | In Redis (all namespaced by key prefix, all TTL'd) |
|---|---|
| Users, clients, consents, admin users, resources | `session:` / `admin_session:` — login sessions (`sessions.py`) |
| Refresh token records (hash, rotation chain, revocation) | `flow:` — an in-progress `/authorize` attempt (client, PKCE challenge, requested scope) |
| WebAuthn credentials | `code:` — an issued-but-not-yet-exchanged authorization code |
| Everything CIMD/DCR clients resolve to | `refresh:` — the *live* refresh token record, mirroring the Postgres row for O(1) lookup without a DB round-trip; deleted on rotation/revocation, Postgres keeps the historical row |
| | `password_reset:` / `email_verify:` — single-use tokens, deleted on use |
| | `webauthn_reg_challenge:` / `webauthn_auth_challenge:` — in-progress passkey ceremonies |
| | `audit_failed_login:` — sliding-window failed-login counters for anomaly detection |
| | `user_sessions:` — the *set* of session IDs per user, so a password reset can revoke all of them at once |

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
   ├─────────────────────────────────────────►│─ verify against users ────►│
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
                        X-Client-Cert-Fingerprint: <sha-256 of the cert>
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

### 5.8 Email verification

```
Signup → create_email_verification_token() + send it (24h TTL), immediately
         continues the login flow regardless -- verification is
         informational, not a login gate (see plan/password-recovery-mcp-
         passkeys-plan.md §5.2 for why this default was chosen)
GET /verify-email?token=... → consume token → users.email_verified = true
```

## 6. Multi-tenancy: user pools

A **pool** is the unit of identity isolation. Every `User` and every
`Client` belongs to exactly one pool.

- Two clients in the **same** pool: their users are the same set. A person
  who signs up on Client A can log into Client B with no new account — this
  is what "SSO across your own apps" means in practice.
- Two clients in **different** pools: fully isolated. The same email address
  can even exist as two unrelated accounts, one per pool (enforced by the
  `(user_pool_id, email)` unique constraint, not a global `email` unique
  constraint).
- A session cookie is checked against the requesting client's pool on every
  `/authorize` call (`authorize.py`'s pool guard) — a session from Pool A
  is silently ignored (falls through to a fresh login) if the client
  belongs to Pool B, rather than granting cross-pool access.

Self-registering clients (DCR and CIMD) always land in the `default` pool.
Admin-created clients can be assigned any pool name, created implicitly the
first time it's used — see `db/pools.py::get_or_create_pool`.

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
| Scoped to | One user pool (checked on every `/authorize`) | The whole deployment |
| Created by | `/login`, `/signup`, `/webauthn/login/verify` | `/admin/login` |

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
| `admin_login_success` / `admin_login_failure` | Admin login result | INFO / WARNING |
| `webauthn_login_success` / `webauthn_registered` | Passkey used / added | INFO |
| `token_issued` | Every successful `/token` call, any grant type | INFO |
| `token_revoked` | `/revoke` called | INFO |
| `client_registered` | DCR or CIMD produces a new client row | INFO |
| `mtls_auth_failed` | mTLS required but verification failed | (via `login_failure`-style call sites) |
| `password_reset_requested` / `password_reset_completed` | Forgot-password flow | INFO |
| `email_verified` | Verification link used | INFO |
| `anomalous_activity` | 5+ failed logins for the same email or IP within 5 minutes | WARNING |

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
| Add a new login method (beyond password/TOTP/passkey) | A new module under `app/auth/`, a new router under `app/oidc/`, and a branch in `_continue_flow`'s callers, same shape as `webauthn.py` |
| Change what's in the JWT | `tokens.py::mint_access_token` |
| Add a new audit event | `app.audit.log_event(...)` at the relevant call site — no registration step, it's just a function call |
| Change session/token lifetimes | `config.py` — every TTL is a named setting, nothing hardcoded inline |
