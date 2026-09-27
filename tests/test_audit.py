import json
import logging

import pytest

from app.audit import FAILED_LOGIN_THRESHOLD, log_event, record_failed_login
from tests.helpers import create_client, create_resource, create_user, extract_hidden_value

REDIRECT_URI = "https://client.example.com/callback"
RESOURCE = "https://api.example.com"


def test_log_event_emits_structured_json(caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    log_event("something_happened", foo="bar", count=3)

    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].message)
    assert payload["event"] == "something_happened"
    assert payload["foo"] == "bar"
    assert payload["count"] == 3
    assert payload["level"] == "INFO"
    assert "ts" in payload


def test_log_event_respects_level(caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    log_event("anomalous_activity", level=logging.WARNING, reason="test")

    assert caplog.records[0].levelno == logging.WARNING
    assert json.loads(caplog.records[0].message)["level"] == "WARNING"


@pytest.mark.asyncio
async def test_record_failed_login_fires_exactly_at_threshold(redis_client):
    results = [await record_failed_login(redis_client, "alice@example.com") for _ in range(FAILED_LOGIN_THRESHOLD + 2)]

    assert results[: FAILED_LOGIN_THRESHOLD - 1] == [False] * (FAILED_LOGIN_THRESHOLD - 1)
    assert results[FAILED_LOGIN_THRESHOLD - 1] is True  # the Nth attempt crosses the threshold
    assert results[FAILED_LOGIN_THRESHOLD] is False  # doesn't fire again on every attempt after


async def _get_flow_id(client, db_session):
    await create_client(db_session, client_id="test-client", redirect_uris=(REDIRECT_URI,))
    await create_resource(db_session, resource_id=RESOURCE)
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 200
    return extract_hidden_value(resp.text, "flow_id")


@pytest.mark.asyncio
async def test_login_success_is_logged(client, db_session, caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    await create_user(db_session, email="alice@example.com", password="pw-12345!")
    flow_id = await _get_flow_id(client, db_session)

    await client.post("/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "pw-12345!"})

    events = [json.loads(r.message) for r in caplog.records]
    assert any(e["event"] == "login_success" and e["client_id"] == "test-client" for e in events)


@pytest.mark.asyncio
async def test_repeated_login_failures_trigger_anomaly(client, db_session, caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    await create_user(db_session, email="alice@example.com", password="pw-12345!")
    flow_id = await _get_flow_id(client, db_session)

    for _ in range(FAILED_LOGIN_THRESHOLD):
        await client.post(
            "/login", data={"flow_id": flow_id, "email": "alice@example.com", "password": "wrong-password"}
        )

    events = [json.loads(r.message) for r in caplog.records]
    failures = [e for e in events if e["event"] == "login_failure"]
    anomalies = [e for e in events if e["event"] == "anomalous_activity"]

    assert len(failures) == FAILED_LOGIN_THRESHOLD
    assert len(anomalies) == 1
    assert anomalies[0]["email"] == "alice@example.com"
    assert anomalies[0]["level"] == "WARNING"
