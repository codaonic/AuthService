from fastapi import Depends, HTTPException, Request

from .validator import TokenValidationError, TokenValidator


def _challenge_headers(request: Request, error: str | None = None) -> dict:
    resource_metadata_url = str(request.base_url).rstrip("/") + "/.well-known/oauth-protected-resource"
    challenge = f'Bearer resource_metadata="{resource_metadata_url}"'
    if error:
        challenge += f', error="{error}"'
    return {"WWW-Authenticate": challenge}


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="missing_bearer_token", headers=_challenge_headers(request)
        )
    return header.removeprefix("Bearer ").strip()


def make_auth_dependency(validator: TokenValidator):
    """Build a FastAPI dependency that validates the bearer token and returns its claims."""

    def require_auth(request: Request, token: str = Depends(bearer_token)) -> dict:
        try:
            return validator.validate(token)
        except TokenValidationError as exc:
            raise HTTPException(
                status_code=401,
                detail=str(exc),
                headers=_challenge_headers(request, "invalid_token"),
            ) from exc

    return require_auth


def make_scope_dependency(validator: TokenValidator, *required_scopes: str):
    """Build a dependency that validates the token AND requires all given scopes."""

    require_auth = make_auth_dependency(validator)

    def require_scope(claims: dict = Depends(require_auth)) -> dict:
        granted = set((claims.get("scope") or "").split())
        missing = set(required_scopes) - granted
        if missing:
            raise HTTPException(status_code=403, detail=f"missing_scope: {', '.join(sorted(missing))}")
        return claims

    return require_scope
