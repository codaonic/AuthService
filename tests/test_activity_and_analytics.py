import time
import uuid

import pytest

from app import audit
from app.admin.analytics import analytics, outcome
from app.config import get_settings
from tests.helpers import create_admin, create_client, create_user


def _event(event, level="INFO", ts=None, **fields):
    return {"id": str(uuid.uuid4()), "ts": ts or time.time(), "level": level, "event": event, **fields}


async def _login_admin(client, db_session):
    await create_admin(db_session, email="admin@example.com", password="admin-password!")
    await client.post("/admin/api/login", json={"email": "admin@example.com", "password": "admin-password!"})


@pytest.fixture(autouse=True)
def fresh_memory(monkeypatch):
    # Each test starts with an empty in-memory buffer, like a restarted app.
    monkeypatch.setattr(audit, "_recent_events", audit.deque(maxlen=500))


# --- Activity log is stored, so it survives a restart ---


@pytest.mark.asyncio
async def test_stored_events_are_shown_after_a_restart(db_session):
    await audit.store_events(db_session, [_event("login_success", client_id="shop", email="ana@example.com")])
    assert len(audit._recent_events) == 0  # nothing in memory, as after a restart

    events = await audit.recent_events(db_session)
    assert [e["event"] for e in events] == ["login_success"]
    assert events[0]["client_id"] == "shop"


@pytest.mark.asyncio
async def test_events_not_stored_yet_are_shown_once(db_session):
    audit.log_event("signup_success", client_id="shop")
    stored = audit._recent_events[-1]
    assert [e["event"] for e in await audit.recent_events(db_session)] == ["signup_success"]

    # Once the writer has stored it, it still appears only once.
    await audit.store_events(db_session, [stored])
    assert [e["event"] for e in await audit.recent_events(db_session)] == ["signup_success"]


@pytest.mark.asyncio
async def test_old_events_are_pruned(db_session):
    old = time.time() - (get_settings().audit_retention_days + 1) * 86400
    await audit.store_events(db_session, [_event("login_success", ts=old), _event("logout")])
    await audit.prune_events(db_session)
    assert [e["event"] for e in await audit.recent_events(db_session)] == ["logout"]


@pytest.mark.asyncio
async def test_audit_endpoint_filters_and_pages(client, db_session):
    await _login_admin(client, db_session)
    now = time.time()
    await audit.store_events(
        db_session,
        [
            _event("login_failure", "WARNING", ts=now - 30, email="ana@shop.test"),
            _event("login_success", ts=now - 20, email="bo@shop.test"),
            _event("login_success", ts=now - 10, email="ana@shop.test"),
        ],
    )

    errors = (await client.get("/admin/api/audit", params={"outcome": "error", "q": "shop.test"})).json()
    assert [e["event"] for e in errors] == ["login_failure"]
    assert errors[0]["outcome"] == "error"
    successes = (await client.get("/admin/api/audit", params={"outcome": "success", "q": "shop.test"})).json()
    assert [e["event"] for e in successes] == ["login_success", "login_success"]

    ana = (await client.get("/admin/api/audit", params={"q": "ANA@shop"})).json()
    assert {e["event"] for e in ana} == {"login_failure", "login_success"}

    first = (await client.get("/admin/api/audit", params={"limit": 1, "q": "shop.test"})).json()
    older = (await client.get("/admin/api/audit", params={"limit": 5, "q": "shop.test", "before": first[0]["ts"]})).json()
    assert [e["event"] for e in first + older] == ["login_success", "login_success", "login_failure"]


# --- Links that couldn't be emailed go to the console, not the terminal ---


@pytest.mark.asyncio
async def test_reset_link_without_smtp_is_held_for_the_console(client, db_session, monkeypatch, capsys):
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    await _login_admin(client, db_session)
    await create_client(db_session)
    user = await create_user(db_session, email="ana@example.com")

    resp = await client.post(f"/admin/api/users/{user.id}/send-reset")
    assert resp.json() == {"emailed": False}

    body = (await client.get("/admin/api/email-links")).json()
    assert body["smtp_configured"] is False
    [held] = body["links"]
    assert held["kind"] == "password_reset" and held["email"] == "ana@example.com"
    assert "/reset-password?token=" in held["link"]

    token = held["link"].split("token=")[1]
    assert token not in capsys.readouterr().out
    # The activity log says a link is waiting, without the link itself.
    events = (await client.get("/admin/api/audit")).json()
    assert any(e["event"] == "email_link_held" for e in events)
    assert all(token not in str(e) for e in events)

    resp = await client.delete(f"/admin/api/email-links/{held['id']}")
    assert resp.status_code == 204
    assert (await client.get("/admin/api/email-links")).json()["links"] == []


@pytest.mark.asyncio
async def test_failed_send_is_held_too(client, db_session, monkeypatch, redis_client):
    async def broken_send(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("app.email.send_email", broken_send)
    from app.email import held_links, send_verification_email

    await send_verification_email(redis_client, "bo@example.com", "tok")
    [held] = await held_links(redis_client)
    assert held["reason"] == "smtp_failed" and held["kind"] == "email_verification"


# --- Analytics ---


def test_outcome():
    assert outcome("login_failure", "WARNING") == "error"
    assert outcome("mtls_auth_failed", "INFO") == "error"
    assert outcome("anomalous_activity", "WARNING") == "warning"
    assert outcome("login_success", "INFO") == "success"


@pytest.mark.asyncio
async def test_analytics_counts_per_application_and_person(db_session):
    await audit.store_events(
        db_session,
        [
            _event("login_success", client_id="shop", email="ana@example.com"),
            _event("login_success", client_id="shop", email="ana@example.com"),
            _event("login_failure", "WARNING", client_id="shop", email="bo@example.com"),
            _event("anomalous_activity", "WARNING", client_id="blog", email="bo@example.com"),
            _event("signup_success", client_id="blog", user_id="u-1"),
            _event("login_success", ts=time.time() - 40 * 86400, client_id="shop"),  # outside 30 days
        ],
    )

    result = await analytics(db_session, days=30)
    assert result["totals"] == {"success": 3, "warning": 1, "error": 1}
    assert len(result["series"]) == 30
    assert sum(d["success"] for d in result["series"]) == 3

    apps = {a["client_id"]: a for a in result["applications"]}
    assert apps["shop"] == {"client_id": "shop", "success": 2, "warning": 0, "error": 1, "total": 3}
    assert apps["blog"]["warning"] == 1 and apps["blog"]["success"] == 1

    people = {u["user"]: u for u in result["users"]}
    assert people["ana@example.com"]["success"] == 2
    assert people["bo@example.com"]["error"] == 1 and people["bo@example.com"]["warning"] == 1
    assert people["u-1"]["success"] == 1

    shop = await analytics(db_session, days=30, client_id="shop")
    assert shop["totals"] == {"success": 2, "warning": 0, "error": 1}
    bo = await analytics(db_session, days=30, user="bo@example.com")
    assert bo["totals"] == {"success": 0, "warning": 1, "error": 1}


@pytest.mark.asyncio
async def test_analytics_endpoint_names_applications(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="shop")
    await audit.store_events(db_session, [_event("login_success", client_id="shop")])

    resp = await client.get("/admin/api/analytics", params={"days": 7})
    assert resp.status_code == 200
    [app_row] = resp.json()["applications"]
    assert app_row["client_id"] == "shop" and "client_name" in app_row


@pytest.mark.asyncio
async def test_pools_list_how_many_people_each_has(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session, client_id="shop", pool_name="acme")
    await create_client(db_session, client_id="blog", pool_name="acme")
    await create_client(db_session, client_id="tool", pool_name="empty")
    await create_user(db_session, email="ana@example.com", client_id="shop")
    await create_user(db_session, email="bo@example.com", client_id="blog")

    pools = {p["name"]: p["user_count"] for p in (await client.get("/admin/api/pools")).json()}
    assert pools["acme"] == 2 and pools["empty"] == 0


@pytest.mark.asyncio
async def test_resources_list_tokens_issued_in_last_30_days(client, db_session):
    await _login_admin(client, db_session)
    await client.post("/admin/api/resources", json={"resource_id": "https://api.example.com", "name": "API"})
    await audit.store_events(
        db_session,
        [
            _event("token_issued", resource="https://api.example.com"),
            _event("token_issued", resource="https://api.example.com"),
            _event("token_issued", resource="https://api.example.com", ts=time.time() - 31 * 86400),
        ],
    )

    [res] = (await client.get("/admin/api/resources")).json()
    assert res["tokens_30d"] == 2


@pytest.mark.asyncio
async def test_send_reset_for_unknown_user_is_404(client, db_session):
    await _login_admin(client, db_session)
    resp = await client.post(f"/admin/api/users/{uuid.uuid4()}/send-reset")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deleting_a_user_keeps_their_activity(client, db_session):
    await _login_admin(client, db_session)
    await create_client(db_session)
    user = await create_user(db_session, email="ana@example.com")
    await audit.store_events(db_session, [_event("login_success", email="ana@example.com", user_id=str(user.id))])

    resp = await client.delete(f"/admin/api/users/{user.id}")
    assert resp.status_code == 204

    events = (await client.get("/admin/api/audit", params={"q": "ana@example.com"})).json()
    assert {e["event"] for e in events} >= {"login_success", "user_deleted"}
    assert (await analytics(db_session, days=30, user="ana@example.com"))["totals"]["success"] >= 1
