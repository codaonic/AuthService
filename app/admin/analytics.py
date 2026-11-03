"""Counts for the admin console's Analytics page, built from the Activity log
(the `audit_events` table, see app/audit.py).

Every event counts as one of three outcomes:

- error: something failed -- the event's name says so (login_failure,
  mtls_auth_failed, ...) or it was logged at ERROR.
- warning: logged at WARNING without being a failure, e.g.
  anomalous_activity or an email that couldn't be sent.
- success: everything else.
"""

import time
from collections import defaultdict

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent

OUTCOMES = ("success", "warning", "error")
DAY = 86400


def outcome(event: str, level: str) -> str:
    if level in ("ERROR", "CRITICAL") or "failure" in event or "failed" in event:
        return "error"
    if level == "WARNING":
        return "warning"
    return "success"


def outcome_filter(kind: str):
    """outcome() as a WHERE clause, for filtering the Activity log."""
    failed = AuditEvent.level.in_(("ERROR", "CRITICAL")) | AuditEvent.event.contains("failure") | AuditEvent.event.contains("failed")
    if kind == "error":
        return failed
    if kind == "warning":
        return (AuditEvent.level == "WARNING") & ~failed
    return (AuditEvent.level != "WARNING") & ~failed


def _empty() -> dict[str, int]:
    return dict.fromkeys(OUTCOMES, 0)


async def analytics(
    db: AsyncSession,
    days: int,
    client_id: str | None = None,
    user: str | None = None,
    top: int = 10,
) -> dict:
    """Totals, a per-day series, and the busiest applications, people and
    events over the last `days` days (UTC), optionally narrowed to one
    application and/or one person (their email or user ID)."""
    since = time.time() - days * DAY
    client_col = AuditEvent.data["client_id"].as_string()
    email_col = AuditEvent.data["email"].as_string()
    user_id_col = AuditEvent.data["user_id"].as_string()
    day_col = cast(AuditEvent.ts / DAY, Integer)

    filters = [AuditEvent.ts >= since]
    if client_id:
        filters.append(client_col == client_id)
    if user:
        filters.append((email_col == user) | (user_id_col == user))

    # One grouped query; outcomes are worked out per (event, level) group,
    # which stays small however many events there are.
    rows = (
        await db.execute(
            select(day_col, client_col, email_col, user_id_col, AuditEvent.event, AuditEvent.level, func.count())
            .where(*filters)
            .group_by(day_col, client_col, email_col, user_id_col, AuditEvent.event, AuditEvent.level)
        )
    ).all()

    totals = _empty()
    per_day: dict[int, dict[str, int]] = defaultdict(_empty)
    per_app: dict[str, dict[str, int]] = defaultdict(_empty)
    per_user: dict[str, dict[str, int]] = defaultdict(_empty)
    per_event: dict[tuple[str, str], int] = defaultdict(int)

    for day, app, email, user_id, event, level, count in rows:
        kind = outcome(event, level)
        totals[kind] += count
        per_day[day][kind] += count
        if app:
            per_app[app][kind] += count
        person = email or user_id
        if person:
            per_user[person][kind] += count
        per_event[(event, kind)] += count

    first_day = int(since // DAY) + 1
    today = int(time.time() // DAY)
    series = [{"day": d * DAY, **per_day.get(d, _empty())} for d in range(first_day, today + 1)]

    def ranked(groups: dict[str, dict[str, int]], key: str) -> list[dict]:
        items = [{key: k, **v, "total": sum(v.values())} for k, v in groups.items()]
        return sorted(items, key=lambda i: i["total"], reverse=True)[:top]

    return {
        "days": days,
        "totals": totals,
        "series": series,
        "applications": ranked(per_app, "client_id"),
        "users": ranked(per_user, "user"),
        "events": [
            {"event": e, "outcome": k, "count": c}
            for (e, k), c in sorted(per_event.items(), key=lambda i: i[1], reverse=True)[:top]
        ],
    }
