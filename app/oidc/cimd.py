"""Client ID Metadata Documents (CIMD).

A CIMD client's `client_id` IS an HTTPS URL, rather than an opaque string
this server assigned. That URL serves a JSON document describing the
client (redirect_uris, grant_types, etc.) -- the document's existence and
self-consistency (its own `client_id` field must match the URL it was
fetched from) is the registration. There's no POST /register step at all.

This is a newer alternative to Dynamic Client Registration (RFC 7591) --
the MCP authorization spec's 2026-07-28 revision prefers it and deprecated
DCR, though DCR remains supported (a MAY) for backward compatibility, and
this server still supports it too (see register.py).

The underlying IETF draft (draft-ietf-oauth-client-id-metadata-document)
is still active, not yet an RFC -- the document schema below matches every
implementation surveyed as of 2026-09, but could still shift before it's
finalized.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_event
from app.db.models import Client

logger = logging.getLogger("app.oidc.cimd")

ALLOWED_GRANT_TYPES = {"authorization_code", "refresh_token"}
FETCH_TIMEOUT_SECONDS = 5.0
# A simplification over full HTTP cache-header compliance (Cache-Control/ETag) --
# a fixed refetch interval is far less code and good enough for how often a
# client's own metadata realistically changes. Worth revisiting if that
# proves wrong in practice.
CACHE_TTL_SECONDS = 60 * 60


def is_cimd_client_id(client_id: str) -> bool:
    return client_id.startswith("https://")


def _is_stale(client: Client) -> bool:
    if client.cimd_fetched_at is None:
        return True
    fetched_at = client.cimd_fetched_at
    if fetched_at.tzinfo is None:
        # Postgres round-trips DateTime(timezone=True) as UTC-aware; SQLite
        # (used in tests, and by anyone self-hosting on it) doesn't have a
        # real timezone-aware type and hands it back naive. We always write
        # this as UTC, so a naive value read back is UTC too.
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - fetched_at
    return age > timedelta(seconds=CACHE_TTL_SECONDS)


async def resolve_cimd_client(db: AsyncSession, client_id: str) -> Client:
    """Resolve a CIMD client_id to a (cached, upserted) Client row.

    Reuses the existing `clients` table rather than a separate code path --
    a resolved CIMD client behaves exactly like a DCR-registered one for
    everything downstream (consent, pools, redirect_uri validation).
    """
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    existing = result.scalar_one_or_none()

    if existing is not None and not _is_stale(existing):
        return existing

    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as http:
            resp = await http.get(client_id)
            resp.raise_for_status()
            doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        if existing is not None:
            # Serve the stale cache rather than hard-failing every login
            # because the client's metadata host had one bad moment.
            logger.warning("CIMD refetch failed for %s, serving cached copy: %s", client_id, exc)
            return existing
        raise HTTPException(400, "invalid_client_metadata: could not fetch or parse CIMD document") from exc

    if doc.get("client_id") != client_id:
        raise HTTPException(400, "invalid_client_metadata: document client_id does not match its URL")

    redirect_uris = doc.get("redirect_uris") or []
    grant_types = [g for g in doc.get("grant_types", ["authorization_code"]) if g in ALLOWED_GRANT_TYPES]
    if not grant_types:
        grant_types = ["authorization_code"]
    scope = doc.get("scope", "") if isinstance(doc.get("scope"), str) else ""
    application_type = doc.get("application_type", "native")
    client_name = doc.get("client_name") if isinstance(doc.get("client_name"), str) else None

    now = datetime.now(timezone.utc)

    if existing is not None:
        existing.redirect_uris = redirect_uris
        existing.grant_types = grant_types
        existing.allowed_scope = scope
        existing.application_type = application_type
        existing.client_name = client_name
        existing.cimd_fetched_at = now
    else:
        client = Client(
            user_pool_id=None,
            client_id=client_id,
            client_name=client_name,
            client_secret_hash=None,  # CIMD clients are always public -- no secret to hold
            client_type="public",
            redirect_uris=redirect_uris,
            grant_types=grant_types,
            allowed_scope=scope,
            registration_method="cimd",
            application_type=application_type,
            cimd_fetched_at=now,
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
        log_event("client_registered", client_id=client_id, registration_method="cimd", grant_types=grant_types)
        return client

    await db.commit()
    await db.refresh(existing)
    return existing
