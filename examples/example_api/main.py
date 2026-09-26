"""Minimal protected API, showing the auth-service-sdk integration pattern.

Run it with:
    uv sync
    uv run uvicorn main:app --reload --port 9001

Then, with an access token minted for resource_id="https://api.example.com":
    curl -H "Authorization: Bearer $TOKEN" http://localhost:9001/me
"""

from fastapi import Depends, FastAPI

from auth_service_sdk import TokenValidator
from auth_service_sdk.fastapi import make_auth_dependency, make_scope_dependency
from auth_service_sdk.protected_resource import protected_resource_router

ISSUER = "http://localhost:8000"
RESOURCE_ID = "https://api.example.com"

validator = TokenValidator(issuer=ISSUER, resource_id=RESOURCE_ID)
require_auth = make_auth_dependency(validator)
require_profile_scope = make_scope_dependency(validator, "profile")

app = FastAPI(title="Example API (protected resource)")
app.include_router(protected_resource_router(RESOURCE_ID, ISSUER, resource_name="Example API"))


@app.get("/me")
async def me(claims: dict = Depends(require_auth)):
    return {"sub": claims["sub"], "scope": claims.get("scope")}


@app.get("/profile")
async def profile(claims: dict = Depends(require_profile_scope)):
    return {"sub": claims["sub"], "profile": "this endpoint required the 'profile' scope"}
