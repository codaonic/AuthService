from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import session as session_module


class _FailingConnectContext:
    def __init__(self, fail_times: int, state: dict):
        self.fail_times = fail_times
        self.state = state

    async def __aenter__(self):
        self.state["calls"] += 1
        if self.state["calls"] <= self.fail_times:
            raise ConnectionError("not ready yet")
        conn = MagicMock()
        conn.execute = AsyncMock()
        return conn

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_wait_for_database_retries_then_succeeds(monkeypatch):
    state = {"calls": 0}
    fake_engine = MagicMock()
    fake_engine.connect.side_effect = lambda: _FailingConnectContext(2, state)
    monkeypatch.setattr(session_module, "engine", fake_engine)

    await session_module.wait_for_database(max_attempts=5, delay_seconds=0)

    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_wait_for_database_raises_after_exhausting_attempts(monkeypatch):
    state = {"calls": 0}
    fake_engine = MagicMock()
    fake_engine.connect.side_effect = lambda: _FailingConnectContext(999, state)
    monkeypatch.setattr(session_module, "engine", fake_engine)

    with pytest.raises(ConnectionError):
        await session_module.wait_for_database(max_attempts=3, delay_seconds=0)

    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_wait_for_database_succeeds_immediately(monkeypatch):
    state = {"calls": 0}
    fake_engine = MagicMock()
    fake_engine.connect.side_effect = lambda: _FailingConnectContext(0, state)
    monkeypatch.setattr(session_module, "engine", fake_engine)

    await session_module.wait_for_database(max_attempts=5, delay_seconds=0)

    assert state["calls"] == 1
