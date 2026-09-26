import httpx
import pytest

from authservice_client import TokenValidationError, TokenValidator
from tests.helpers import ISSUER, RESOURCE_ID, make_token


def _validator(mock_transport) -> TokenValidator:
    return TokenValidator(
        issuer=ISSUER,
        resource_id=RESOURCE_ID,
        jwks_url="https://auth.example.com/jwks.json",
        http_client=httpx.Client(transport=mock_transport),
    )


def test_valid_token_returns_claims(keypair, mock_transport):
    validator = _validator(mock_transport)
    token = make_token(keypair, sub="user-123")

    claims = validator.validate(token)

    assert claims["sub"] == "user-123"
    assert claims["aud"] == RESOURCE_ID


def test_wrong_audience_rejected(keypair, mock_transport):
    validator = _validator(mock_transport)
    token = make_token(keypair, aud="https://other.example.com")

    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_wrong_issuer_rejected(keypair, mock_transport):
    validator = _validator(mock_transport)
    token = make_token(keypair, iss="https://not-the-real-as.example.com")

    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_expired_token_rejected(keypair, mock_transport):
    validator = _validator(mock_transport)
    token = make_token(keypair, ttl=-60)

    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_unknown_kid_rejected(keypair):
    empty_jwks_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": []}))
    validator = TokenValidator(
        issuer=ISSUER,
        resource_id=RESOURCE_ID,
        jwks_url="https://auth.example.com/jwks.json",
        http_client=httpx.Client(transport=empty_jwks_transport),
    )
    token = make_token(keypair)

    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_has_scope(keypair, mock_transport):
    validator = _validator(mock_transport)
    token = make_token(keypair, scope="profile email")
    claims = validator.validate(token)

    assert validator.has_scope(claims, "profile") is True
    assert validator.has_scope(claims, "admin") is False


def test_jwks_cached_across_calls(keypair):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=keypair["jwks"])

    validator = TokenValidator(
        issuer=ISSUER,
        resource_id=RESOURCE_ID,
        jwks_url="https://auth.example.com/jwks.json",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    token = make_token(keypair)

    validator.validate(token)
    validator.validate(token)

    assert calls["count"] == 1
