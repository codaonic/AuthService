import json
import logging
import time
from collections import deque
from typing import Any

from fastapi import Request
from redis.asyncio import Redis

audit_logger = logging.getLogger("app.audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False
if not audit_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(_handler)

FAILED_LOGIN_PREFIX = "audit_failed_login:"
FAILED_LOGIN_THRESHOLD = 5
FAILED_LOGIN_WINDOW_SECONDS = 5 * 60

# In-memory only, capped, per-process -- lets the admin UI show "what just
# happened" without standing up a second durable store for audit data.
# stdout (via audit_logger above) stays the actual source of truth; point a
# real log aggregator at it for anything that needs to survive a restart or
# span multiple replicas.
_RECENT_EVENTS_MAXLEN = 500
_recent_events: deque[dict] = deque(maxlen=_RECENT_EVENTS_MAXLEN)


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one structured (JSON-lines) audit record.

    This is a log line, not a notification -- wiring it into a paging
    system (Slack, PagerDuty, email) is a deployment choice left to
    whatever log aggregator you point at stdout, same as any other
    12-factor app. `anomalous_activity` events are logged at WARNING so
    they're easy to filter for regardless of what that downstream is.
    """
    payload = {"ts": round(time.time(), 3), "level": logging.getLevelName(level), "event": event, **fields}
    audit_logger.log(level, json.dumps(payload, default=str))
    _recent_events.append(payload)


def recent_events(limit: int = 200) -> list[dict]:
    """Most-recent-first slice of this process's in-memory event buffer."""
    return list(_recent_events)[::-1][:limit]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def record_failed_login(redis: Redis, key: str) -> bool:
    """Track a failed login attempt against `key` (email or IP) in a sliding
    window. Returns True exactly once, the moment the count crosses the
    anomaly threshold within the window -- callers use that to log a single
    `anomalous_activity` event instead of one per attempt after the first.
    """
    redis_key = f"{FAILED_LOGIN_PREFIX}{key}"
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, FAILED_LOGIN_WINDOW_SECONDS)
    return count == FAILED_LOGIN_THRESHOLD
