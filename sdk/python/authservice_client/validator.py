import time

import httpx
from jose import JWTError, jwt


class TokenValidationError(Exception):
    pass


class TokenValidator:
    """Fetches and caches the auth service's JWKS, and verifies bearer tokens locally.

    No network call to the auth service happens per request -- only when the
    JWKS cache is cold or a token references an unknown `kid` (e.g. right
    after key rotation).
    """

    def __init__(
        self,
        issuer: str,
        resource_id: str,
        jwks_url: str | None = None,
        cache_ttl: int = 300,
        http_client: httpx.Client | None = None,
    ):
        self.issuer = issuer
        self.resource_id = resource_id
        self.jwks_url = jwks_url or f"{issuer.rstrip('/')}/jwks.json"
        self.cache_ttl = cache_ttl
        self._http = http_client or httpx.Client(timeout=3)
        self._jwks: dict = {}
        self._cache_expiry = 0.0

    def _get_jwks(self, force_refresh: bool = False) -> dict:
        if force_refresh or time.time() > self._cache_expiry:
            resp = self._http.get(self.jwks_url)
            resp.raise_for_status()
            self._jwks = resp.json()
            self._cache_expiry = time.time() + self.cache_ttl
        return self._jwks

    def _find_key(self, kid: str) -> dict | None:
        jwks = self._get_jwks()
        key = next((k for k in jwks.get("keys", []) if k["kid"] == kid), None)
        if key is None:
            jwks = self._get_jwks(force_refresh=True)
            key = next((k for k in jwks.get("keys", []) if k["kid"] == kid), None)
        return key

    def validate(self, token: str) -> dict:
        """Verify signature, `exp`, `iss`, and `aud` (must equal this resource_id).

        Returns the decoded claims on success, or raises TokenValidationError.
        """
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise TokenValidationError("malformed token") from exc

        kid = header.get("kid")
        key = self._find_key(kid) if kid else None
        if key is None:
            raise TokenValidationError("unknown signing key")

        try:
            return jwt.decode(
                token,
                key,
                algorithms=[header.get("alg", "RS256")],
                audience=self.resource_id,
                issuer=self.issuer,
            )
        except JWTError as exc:
            raise TokenValidationError(str(exc)) from exc

    @staticmethod
    def has_scope(claims: dict, scope: str) -> bool:
        return scope in (claims.get("scope") or "").split()
