# Security Policy

This service issues and validates the tokens every other internal service trusts
for identity — treat anything here that could lead to token forgery, signature
bypass, credential exposure, or cross-tenant (cross-pool) data leakage as a
security issue, not a regular bug.

## Reporting a vulnerability

Do not open a public GitHub issue for a suspected vulnerability.

Instead, use GitHub's private reporting: go to the **Security** tab of this
repository → **Report a vulnerability**. This opens a private advisory visible
only to the maintainers until a fix is ready.

Please include:

- The affected endpoint(s) or component
- Steps to reproduce, or a proof-of-concept token/request
- The potential impact (e.g. which trust boundary it crosses)

## Scope

In scope: the authorization/token endpoints, the admin UI and its auth, key
management/signing, and the resource-server SDK's token validation logic.

Out of scope: findings that require an already-compromised admin account,
or issues in third-party dependencies (report those upstream instead).
