"""OpenID Connect ID tokens: the app's signed proof of who signed in.

Issued from /token whenever the granted scope includes `openid` -- both for
the authorization code and on refresh. Audience is the application itself
(never an API), so it isn't usable as an access token.
"""

import base64
import hashlib
import time
import uuid

from joserfc import jwt

from app.config import get_settings
from app.db.models import User
from app.oidc.keys import get_key_manager

# Claim names an app may not choose for its roles: they mean something else.
RESERVED_CLAIMS = frozenset(
    {
        "iss", "sub", "aud", "exp", "iat", "nbf", "jti", "azp", "nonce", "auth_time", "acr", "amr",
        "at_hash", "c_hash", "sid", "scope", "client_id", "email", "email_verified", "name",
        "given_name", "family_name", "preferred_username", "phone_number", "events", "cnf",
    }
)


def public_sid(session_id: str | None) -> str | None:
    """A stable id for one browser session, safe to put in tokens: a hash of
    the session cookie, so it can't be turned back into the cookie."""
    if not session_id:
        return None
    digest = hashlib.sha256(f"sid:{session_id}".encode()).digest()
    return base64.urlsafe_b64encode(digest[:18]).rstrip(b"=").decode()


def _left_half_hash(value: str) -> str:
    """at_hash for RS256 (OIDC Core 3.1.3.6)."""
    digest = hashlib.sha256(value.encode()).digest()
    return base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()


def profile_claims(user: User, scope: set[str]) -> dict:
    """The person's details an app asked for, by scope (also used by /userinfo)."""
    claims: dict = {}
    if "email" in scope:
        claims["email"] = user.email
        claims["email_verified"] = user.email_verified
    if "profile" in scope:
        name = " ".join(p for p in (user.first_name, user.last_name) if p)
        if name:
            claims["name"] = name
        if user.first_name:
            claims["given_name"] = user.first_name
        if user.last_name:
            claims["family_name"] = user.last_name
        if user.username:
            claims["preferred_username"] = user.username
    return claims


def mint_id_token(
    *,
    user: User,
    client_id: str,
    scope: str,
    access_token: str,
    auth_time: int | None,
    nonce: str | None = None,
    sid: str | None = None,
    roles: list[str] | None = None,
    roles_claim: str = "roles",
) -> str:
    settings = get_settings()
    kid, key = get_key_manager().signing_key()
    now = int(time.time())
    payload = {
        "iss": settings.issuer_url,
        "sub": str(user.id),
        "aud": client_id,
        "azp": client_id,
        "iat": now,
        "exp": now + settings.access_token_ttl_seconds,
        "jti": str(uuid.uuid4()),
        "at_hash": _left_half_hash(access_token),
        **profile_claims(user, set(scope.split())),
    }
    if auth_time:
        payload["auth_time"] = auth_time
    if nonce:
        payload["nonce"] = nonce
    if sid:
        payload["sid"] = sid
    if roles is not None:
        payload[roles_claim] = roles
    return jwt.encode(
        {"alg": settings.signing_key_algorithm, "kid": kid, "typ": "JWT"},
        payload,
        key,
        algorithms=[settings.signing_key_algorithm],
    )
