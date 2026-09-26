# auth-service-sdk

Token validation and FastAPI integration helpers for any service that sits behind the shared auth service — a website's API, an MCP server, or any other resource server. Nothing here talks to the auth service except to fetch and cache its JWKS; every request is verified locally.

## Install

From another project, either add it as a local/editable dependency, or copy the `auth_service_sdk/` package directly — it has exactly two runtime dependencies (`python-jose[cryptography]`, `httpx`), plus `fastapi` if you use the FastAPI helpers.

```bash
uv add --editable ../auth_service/sdk/python
# or, with the fastapi extra:
uv add --editable ../auth_service/sdk/python[fastapi]
```

## Framework-agnostic validation

```python
from auth_service_sdk import TokenValidator, TokenValidationError

validator = TokenValidator(
    issuer="https://auth.yourdomain.com",
    resource_id="https://api.yourdomain.com",  # must match the `resource=` this token was issued for
)

try:
    claims = validator.validate(token)  # verifies signature, exp, iss, aud
except TokenValidationError:
    ...  # reject the request
```

## FastAPI

```python
from fastapi import Depends, FastAPI

from auth_service_sdk import TokenValidator
from auth_service_sdk.fastapi import make_auth_dependency, make_scope_dependency
from auth_service_sdk.protected_resource import protected_resource_router

ISSUER = "https://auth.yourdomain.com"
RESOURCE_ID = "https://api.yourdomain.com"

validator = TokenValidator(issuer=ISSUER, resource_id=RESOURCE_ID)
require_auth = make_auth_dependency(validator)
require_profile_scope = make_scope_dependency(validator, "profile")

app = FastAPI()

# RFC 9728 metadata, served BY this resource server, pointing back at the auth service.
# MCP clients fetch this after a 401 to discover which authorization server to use.
app.include_router(protected_resource_router(RESOURCE_ID, ISSUER, resource_name="Your API"))


@app.get("/me")
async def me(claims: dict = Depends(require_auth)):
    return {"sub": claims["sub"]}


@app.get("/profile")
async def profile(claims: dict = Depends(require_profile_scope)):
    return {"sub": claims["sub"]}
```

A request with no/invalid token gets a `401` with a `WWW-Authenticate: Bearer resource_metadata="…"` header pointing at your `/.well-known/oauth-protected-resource` — the same 401-then-discover pattern an MCP client expects.

## Other languages

There's no SDK here for non-Python services, but the pattern is a handful of lines in any language with an HTTP client and a JWT library:

1. `GET {issuer}/jwks.json` once, cache it (refresh on a cache-miss `kid`, e.g. every 5–10 min).
2. Verify the token's signature, `exp`, `iss` (must equal `{issuer}`), and `aud` (must equal your `resource_id`).
3. Read `sub` / `scope` off the verified claims.

Equivalent libraries: `jose` or `jsonwebtoken` + `jwks-rsa` in Node, `github.com/coreos/go-oidc` in Go, `jose4j` in Java.

## Registering your service

Before any of this works, the auth service needs to know about your resource and your client. From the auth service's repo:

```bash
uv run python -m app.cli register-resource --resource-id "https://api.yourdomain.com" --name "Your API"
uv run python -m app.cli register-client --client-id your-app --type public --redirect-uri "https://yourdomain.com/callback"
```

Or, for a client that registers itself at runtime (e.g. an MCP client), use Dynamic Client Registration: `POST {issuer}/register`.

See `examples/` in the main repo for complete, runnable resource-server and MCP-server examples built on this SDK.
