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
        "introspection_endpoint": f"{issuer}/introspect",
        "end_session_endpoint": f"{issuer}/logout",
        "jwks_uri": f"{issuer}/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
        "revocation_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
        "introspection_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "response_modes_supported": ["query", "web_message"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [settings.signing_key_algorithm],
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat", "auth_time", "nonce", "azp", "at_hash", "sid",
            "email", "email_verified", "name", "given_name", "family_name", "preferred_username",
        ],
        "claims_parameter_supported": False,
        "request_parameter_supported": False,
        "request_uri_parameter_supported": False,
        "prompt_values_supported": ["none", "login", "consent", "select_account"],
        "authorization_response_iss_parameter_supported": True,
        # Back-channel logout goes only to the one app being signed out of.
        "backchannel_logout_supported": True,
        "backchannel_logout_session_supported": True,
        "frontchannel_logout_supported": False,
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
