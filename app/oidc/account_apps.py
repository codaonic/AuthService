"""The person's own account page: the apps they're signed in to (each can be
signed out of on its own), and the teams they manage.

A team manager can add and remove the team's people -- only accounts from
their own login group, and never other managers. What the team gives (apps
and roles) stays with the admin console.
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import client_ip, log_event
from app.auth.enforce import enforce_access
from app.auth.identity import accounts_for_email
from app.auth.sessions import sign_out_app
from app.config import get_settings
from app.db.models import Client, RefreshToken, Team, TeamMember, User
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.oidc.id_token import public_sid
from app.oidc.refresh import revoke_all_refresh_tokens_for_user

router = APIRouter()


async def signed_in_apps(db: AsyncSession, user: User) -> list[dict]:
    """Apps holding a live sign-in for this person."""
    rows = await db.execute(
        select(Client.client_id, Client.client_name, Client.logo_url)
        .join(RefreshToken, RefreshToken.client_id == Client.client_id)
        .where(RefreshToken.user_id == str(user.id), RefreshToken.revoked_at.is_(None))
        .distinct()
        .order_by(Client.client_id)
    )
    return [{"client_id": c, "name": n or c, "logo_url": logo} for c, n, logo in rows.all()]


async def managed_teams(db: AsyncSession, user: User) -> list[dict]:
    teams = (
        await db.execute(
            select(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user.id, TeamMember.is_manager.is_(True))
            .order_by(Team.name)
        )
    ).scalars().all()
    result = []
    for team in teams:
        people = await db.execute(
            select(User.id, User.email, User.first_name, User.last_name, TeamMember.is_manager)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team.id)
            .order_by(User.email)
        )
        result.append(
            {
                "id": str(team.id),
                "name": team.name,
                "members": [
                    {"id": str(uid), "email": e, "name": " ".join(p for p in (f, l) if p), "is_manager": m}
                    for uid, e, f, l, m in people.all()
                ],
            }
        )
    return result


async def _me(request: Request, db: AsyncSession, redis: Redis) -> User:
    from app.oidc.webauthn import _current_user

    user = await _current_user(request, db, redis)
    if user is None or user.status != "active":
        raise HTTPException(401, "Not signed in")
    return user


async def _managed(db: AsyncSession, me: User, team_id: str) -> Team:
    try:
        tid = uuid.UUID(team_id)
    except ValueError:
        raise HTTPException(404, "unknown_team")
    row = await db.execute(
        select(TeamMember.id).where(TeamMember.team_id == tid, TeamMember.user_id == me.id, TeamMember.is_manager.is_(True))
    )
    if row.first() is None:
        raise HTTPException(403, "You don't manage this team")
    return await db.get(Team, tid)


# Only these fixed messages can be shown after a redirect: free text in the
# URL would let anyone craft an /account link that says whatever they like.
MESSAGES = {
    "member_added": ("success", "Added to the team."),
    "member_removed": ("success", "Removed from the team. Their access ends now."),
    "no_such_person": ("error", "No one with that email has an account in your group."),
    "manager_protected": ("error", "Managers can only be removed from the admin console."),
    "app_signed_out": ("success", "Signed out of that app. Your other apps are still signed in."),
}


def _back(code: str, anchor: str = "teams") -> RedirectResponse:
    return RedirectResponse(f"/account?msg={code}#{anchor}", status_code=303)


@router.post("/account/apps/{client_id}/sign-out")
async def sign_out_of_app(
    client_id: str, request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
):
    """Sign out of one app from the account page; every other app stays signed in."""
    me = await _me(request, db, redis)
    await sign_out_app(redis, str(me.id), client_id)
    session_id = request.cookies.get(get_settings().session_cookie_name)
    await revoke_all_refresh_tokens_for_user(db, redis, str(me.id), client_id, sid=public_sid(session_id))
    log_event("logout", client_id=client_id, user_id=str(me.id), via="account_page", ip=client_ip(request))
    return _back("app_signed_out", "apps")


@router.post("/account/teams/{team_id}/members")
@limiter.limit("30/minute")
async def manager_add_member(
    team_id: str,
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    me = await _me(request, db, redis)
    team = await _managed(db, me, team_id)
    own_app = (await db.execute(select(Client).where(Client.client_id == me.client_id))).scalar_one_or_none()
    # Only someone with an account in the manager's own login group.
    matches = await accounts_for_email(db, email, own_app) if own_app else []
    if len(matches) != 1:
        return _back("no_such_person")
    person = matches[0]
    exists = await db.execute(select(TeamMember.id).where(TeamMember.team_id == team.id, TeamMember.user_id == person.id))
    if exists.first() is None:
        db.add(TeamMember(team_id=team.id, user_id=person.id))
        await db.commit()
        log_event("team_member_added", team=team.name, user_id=str(person.id), email=person.email, by_manager=str(me.id))
    return _back("member_added")


@router.post("/account/teams/{team_id}/members/{user_id}/remove")
async def manager_remove_member(
    team_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    me = await _me(request, db, redis)
    team = await _managed(db, me, team_id)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(404, "not_a_member")
    member = (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == uid))
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(404, "not_a_member")
    if member.is_manager:
        return _back("manager_protected")
    await db.execute(delete(TeamMember).where(TeamMember.id == member.id))
    await db.commit()
    log_event("team_member_removed", team=team.name, user_id=user_id, by_manager=str(me.id))
    await enforce_access(db, redis, {uid})
    return _back("member_removed")
