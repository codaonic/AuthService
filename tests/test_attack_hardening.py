import pyotp
import pytest

from app.auth.passwords import hash_password
from app.config import get_settings
from app.db.models import AdminUser, Client, User
from app.middleware.rate_limit import limiter
from tests.helpers import extract_hidden_value, make_pkce_pair

REDIRECT_URI = "https://client.example.com/callback"
EMAIL = "alice@example.com"
PASSWORD = "s3cret-password!"


async def _setup(db_session, mfa_secret=None):
    db_session.add(
        Client(
            client_id="app",
            client_type="public",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            allowed_scope="profile email",
        )
    )
    db_session.add(User(client_id="app", email=EMAIL, password_hash=hash_password(PASSWORD), mfa_secret=mfa_secret))
    await db_session.commit()


async def _flow_id(client):
    _, challenge = make_pkce_pair()
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "app",
            "redirect_uri": REDIRECT_URI,
            "resource": "https://api.example.com",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    return extract_hidden_value(resp.text, "flow_id")


async def _login(client, flow_id, password, totp_code=""):
    return await client.post(
        "/login", data={"flow_id": flow_id, "email": EMAIL, "password": password, "totp_code": totp_code}
    )


@pytest.mark.asyncio
async def test_account_locks_after_repeated_wrong_passwords(client, db_session, redis_client):
    await _setup(db_session)
    flow_id = await _flow_id(client)
    limit = get_settings().login_max_failures

    for _ in range(limit):
        limiter.reset()  # isolate the per-account lock from the per-IP limit
        assert (await _login(client, flow_id, "wrong-password")).status_code == 401
    limiter.reset()

    # Even the right password is refused while locked.
    locked = await _login(client, flow_id, PASSWORD)
    assert locked.status_code == 429
    assert "Too many failed attempts" in locked.text


@pytest.mark.asyncio
async def test_lockout_does_not_reveal_whether_an_account_exists(client, db_session):
    await _setup(db_session)
    flow_id = await _flow_id(client)

    for _ in range(get_settings().login_max_failures):
        limiter.reset()
        await client.post("/login", data={"flow_id": flow_id, "email": "nobody@example.com", "password": "x"})
    limiter.reset()
    resp = await client.post("/login", data={"flow_id": flow_id, "email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_wrong_2fa_codes_count_towards_the_lock(client, db_session):
    secret = pyotp.random_base32()
    await _setup(db_session, mfa_secret=secret)
    flow_id = await _flow_id(client)

    # Submitting the right password without a code is just the prompt -- not a failure.
    for _ in range(3):
        limiter.reset()
        assert (await _login(client, flow_id, PASSWORD)).status_code == 401

    for _ in range(get_settings().login_max_failures):
        limiter.reset()
        await _login(client, flow_id, PASSWORD, totp_code="000000")
    limiter.reset()
    resp = await _login(client, flow_id, PASSWORD, totp_code=pyotp.TOTP(secret).now())
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_successful_login_clears_earlier_failures(client, db_session, redis_client):
    await _setup(db_session)
    flow_id = await _flow_id(client)
    for _ in range(get_settings().login_max_failures - 1):
        await _login(client, flow_id, "wrong-password")
    assert (await _login(client, flow_id, PASSWORD)).status_code == 200

    assert await redis_client.get(f"login_lockout:user:{EMAIL}") is None


@pytest.mark.asyncio
async def test_login_is_rate_limited_per_ip(client, db_session):
    await _setup(db_session)
    flow_id = await _flow_id(client)
    limit = int(get_settings().rate_limit_login.split("/")[0])

    statuses = [
        (await client.post("/login", data={"flow_id": flow_id, "email": f"u{i}@example.com", "password": "x"})).status_code
        for i in range(limit + 1)
    ]
    assert statuses[:limit] == [401] * limit
    assert statuses[limit] == 429


@pytest.mark.asyncio
async def test_admin_login_locks_after_repeated_failures(client, db_session):
    db_session.add(AdminUser(email="admin@example.com", password_hash=hash_password("admin-password!")))
    await db_session.commit()

    for _ in range(get_settings().login_max_failures):
        limiter.reset()
        await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "wrong"})
    limiter.reset()
    resp = await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_security_headers_are_set(client):
    resp = await client.get("/.well-known/openid-configuration")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "Strict-Transport-Security" not in resp.headers  # plain-HTTP test server
