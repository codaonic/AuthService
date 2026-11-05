import asyncio
import json
import logging
import time
import uuid
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

# The admin console's Activity log is stored in the `audit_events` table so it
# survives restarts. log_event() stays synchronous and never waits on the
# database: it hands the event to a background writer (started in the app's
# lifespan) and also keeps the newest ones in memory, so an event shows up in
# the console straight away, before the writer has stored it.
_RECENT_EVENTS_MAXLEN = 500
_recent_events: deque[dict] = deque(maxlen=_RECENT_EVENTS_MAXLEN)
_queue: asyncio.Queue[dict] | None = None
_writer: asyncio.Task | None = None
# Every event is also published here, so open admin console pages update
# without a refresh (see GET /admin/api/stream).
LIVE_CHANNEL = "audit_live"
_WRITE_BATCH = 200
_PRUNE_EVERY_SECONDS = 60 * 60


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one structured (JSON-lines) audit record.

    This is a log line, not a notification -- wiring it into a paging
    system (Slack, PagerDuty, email) is a deployment choice left to
    whatever log aggregator you point at stdout, same as any other
    12-factor app. `anomalous_activity` events are logged at WARNING so
    they're easy to filter for regardless of what that downstream is.
    """
    payload = {
        "id": str(uuid.uuid4()),
        "ts": round(time.time(), 3),
        "level": logging.getLevelName(level),
        "event": event,
        **fields,
    }
    audit_logger.log(level, json.dumps(payload, default=str))
    _recent_events.append(payload)
    if _queue is not None:
        _queue.put_nowait(payload)


async def start_audit_writer(session_factory=None, redis=None) -> None:
    """Defaults to the app's own database and Redis; tests pass their own."""
    global _queue, _writer
    if session_factory is None:
        from app.db.session import runtime_session_factory as session_factory
    if redis is None:
        from app.db.redis_client import get_redis

        redis = get_redis()
    _queue = asyncio.Queue()
    _writer = asyncio.create_task(_write_forever(_queue, session_factory, redis))


async def stop_audit_writer() -> None:
    """Store whatever is still queued, then stop."""
    global _queue, _writer
    if _queue is None or _writer is None:
        return
    queue, writer = _queue, _writer
    _queue = None
    await queue.join()
    writer.cancel()
    try:
        await writer
    except asyncio.CancelledError:
        pass
    _writer = None


async def _write_forever(queue: asyncio.Queue[dict], session_factory, redis) -> None:
    last_prune = 0.0
    while True:
        batch = [await queue.get()]
        while len(batch) < _WRITE_BATCH and not queue.empty():
            batch.append(queue.get_nowait())
        try:
            # Published before storing, so open consoles see it straight away.
            async with redis.pipeline(transaction=False) as pipe:
                for p in batch:
                    pipe.publish(LIVE_CHANNEL, json.dumps(p, default=str))
                await pipe.execute()
        except Exception:
            logging.getLogger("app.audit.writer").exception("Couldn't publish %d activity log entries", len(batch))
        try:
            async with session_factory() as db:
                await store_events(db, batch)
                if time.time() - last_prune > _PRUNE_EVERY_SECONDS:
                    await prune_events(db)
                    last_prune = time.time()
        except Exception:
            # The events already went to stdout, which stays the source of
            # truth; losing them from the console must not stop the writer.
            logging.getLogger("app.audit.writer").exception("Couldn't store %d activity log entries", len(batch))
        finally:
            for _ in batch:
                queue.task_done()


async def store_events(db, payloads: list[dict]) -> None:
    from app.db.models import AuditEvent

    for p in payloads:
        db.add(
            AuditEvent(
                id=uuid.UUID(p["id"]),
                ts=p["ts"],
                level=p["level"],
                event=p["event"],
                data=json.loads(json.dumps({k: v for k, v in p.items() if k not in ("id", "ts", "level", "event")}, default=str)),
            )
        )
    await db.commit()


async def prune_events(db) -> None:
    from sqlalchemy import delete

    from app.config import get_settings
    from app.db.models import AuditEvent

    cutoff = time.time() - get_settings().audit_retention_days * 86400
    await db.execute(delete(AuditEvent).where(AuditEvent.ts < cutoff))
    await db.commit()


def _matches(payload: dict, outcome: str | None, search: str | None) -> bool:
    from app.admin.analytics import outcome as outcome_of

    if outcome and outcome_of(payload["event"], payload["level"]) != outcome:
        return False
    return not search or search.lower() in json.dumps(payload, default=str).lower()


async def recent_events(
    db, limit: int = 200, before: float | None = None, outcome: str | None = None, search: str | None = None
) -> list[dict]:
    """Newest first: what's stored, plus anything the writer hasn't stored yet.

    `before` (a timestamp) pages back through older entries; `outcome` is
    success, warning or error (see app/admin/analytics.py).
    """
    from sqlalchemy import String, cast, func, select

    from app.admin.analytics import outcome_filter
    from app.db.models import AuditEvent

    query = select(AuditEvent).order_by(AuditEvent.ts.desc()).limit(limit)
    if before is not None:
        query = query.where(AuditEvent.ts < before)
    if outcome:
        query = query.where(outcome_filter(outcome))
    if search:
        needle = f"%{search.lower()}%"
        query = query.where(
            func.lower(AuditEvent.event).like(needle) | func.lower(cast(AuditEvent.data, String)).like(needle)
        )
    stored = [
        {"id": str(e.id), "ts": e.ts, "level": e.level, "event": e.event, **(e.data or {})}
        for e in (await db.execute(query)).scalars().all()
    ]

    seen = {e["id"] for e in stored}
    pending = [
        e
        for e in _recent_events
        if e["id"] not in seen and (before is None or e["ts"] < before) and _matches(e, outcome, search)
    ]
    return sorted(stored + pending, key=lambda e: e["ts"], reverse=True)[:limit]


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
