from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


def _metadata_document() -> dict:
    settings = get_settings()
    issuer = settings.issuer.rstrip("/")
    return {
        "issuer": settings.issuer_url,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "userinfo_endpoint": f"{issuer}/userinfo",
        "revocation_endpoint": f"{issuer}/revoke",
        "jwks_uri": f"{issuer}/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email"],
        "claims_supported": ["sub", "email"],
    }


@router.get("/.well-known/openid-configuration")
async def openid_configuration():
    return _metadata_document()


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server():
    """RFC 8414 authorization server metadata -- a superset-compatible alias
    of the OIDC discovery document above. Several MCP clients probe this
    path before falling back to /.well-known/openid-configuration; serving
    both avoids that extra round trip (and 404) on every connection.
    """
    return _metadata_document()
