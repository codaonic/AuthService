"""Admin API for teams: named sets of people that carry app access and roles.

See app/auth/teams.py for how membership turns into access and roles.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.api import _future, require_admin
from app.audit import log_event
from app.auth.enforce import enforce_access
from app.auth.teams import parent_map, with_ancestors
from app.db.models import (
    AdminUser,
    Client,
    ClientRole,
    Team,
    TeamAppAccess,
    TeamMember,
    TeamRole,
    User,
    UserPool,
)
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.tenant import bypass_tenant_rls

router = APIRouter(prefix="/admin/api")

MAX_NAME_LENGTH = 80


async def _members_of(db: AsyncSession, team_id: uuid.UUID) -> set[uuid.UUID]:
    """Everyone a team's access reaches: its people and its sub-teams' people."""
    parents = await parent_map(db)
    reached = {t for t in parents if team_id in with_ancestors({t}, parents)}
    rows = await db.execute(select(TeamMember.user_id).where(TeamMember.team_id.in_(reached)))
    return {u for (u,) in rows.all()}



def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise HTTPException(400, "Give the team a name")
    if len(name) > MAX_NAME_LENGTH:
        raise HTTPException(400, f"Keep the name under {MAX_NAME_LENGTH} characters")
    return name


async def _team(db: AsyncSession, team_id: str) -> Team:
    try:
        team = await db.get(Team, uuid.UUID(team_id))
    except ValueError:
        team = None
    if team is None:
        raise HTTPException(404, "unknown_team")
    return team


async def _name_taken(db: AsyncSession, name: str, except_id: uuid.UUID | None = None) -> bool:
    query = select(Team.id).where(func.lower(Team.name) == name.lower())
    if except_id is not None:
        query = query.where(Team.id != except_id)
    return (await db.execute(query)).first() is not None


async def _check_parent(db: AsyncSession, team_id: uuid.UUID | None, parent_id: str | None) -> uuid.UUID | None:
    """A parent must exist, and can't be the team itself or one of its own
    sub-teams (that would make a loop)."""
    if not parent_id:
        return None
    parent = await _team(db, parent_id)
    if team_id is not None and team_id in with_ancestors({parent.id}, await parent_map(db)):
        raise HTTPException(400, "A team can't sit inside itself or one of its own sub-teams")
    return parent.id


async def _teams_json(db: AsyncSession) -> list[dict]:
    teams = (await db.execute(select(Team).order_by(func.lower(Team.name)))).scalars().all()
    members = dict(
        (await db.execute(select(TeamMember.team_id, func.count(TeamMember.id)).group_by(TeamMember.team_id))).all()
    )
    apps: dict[uuid.UUID, list[dict]] = {}
    for team_id, client_id, client_name in (
        await db.execute(
            select(TeamAppAccess.team_id, Client.client_id, Client.client_name)
            .join(Client, Client.client_id == TeamAppAccess.client_id)
            .order_by(Client.client_id)
        )
    ).all():
        apps.setdefault(team_id, []).append({"client_id": client_id, "client_name": client_name})
    roles: dict[uuid.UUID, list[dict]] = {}
    for team_id, client_id, role in (
        await db.execute(select(TeamRole.team_id, TeamRole.client_id, TeamRole.role).order_by(TeamRole.client_id, TeamRole.role))
    ).all():
        roles.setdefault(team_id, []).append({"client_id": client_id, "role": role})
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description or "",
            "parent_id": str(t.parent_id) if t.parent_id else None,
            "member_count": members.get(t.id, 0),
            "apps": apps.get(t.id, []),
            "roles": roles.get(t.id, []),
        }
        for t in teams
    ]


async def _one_team_json(db: AsyncSession, team: Team) -> dict:
    return next(t for t in await _teams_json(db) if t["id"] == str(team.id))


@router.get("/teams")
async def api_list_teams(admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await _teams_json(db)


class RoleRef(BaseModel):
    client_id: str
    role: str


class TeamBody(BaseModel):
    name: str
    description: str = ""
    parent_id: str | None = None
    # Only on create: what the team gives, so it's set up in one step.
    apps: list[str] = []
    roles: list[RoleRef] = []
    members: list[str] = []


@router.post("/teams", status_code=201)
async def api_create_team(body: TeamBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    name = _clean_name(body.name)
    if await _name_taken(db, name):
        raise HTTPException(400, f"There's already a team called '{name}'")
    team = Team(name=name, description=body.description.strip() or None, parent_id=await _check_parent(db, None, body.parent_id))
    # Checked before anything is saved, so a bad pick leaves no half-made team.
    for client_id in set(body.apps):
        await _client(db, client_id)
    for ref in body.roles:
        if await db.get(ClientRole, (ref.client_id, ref.role)) is None:
            raise HTTPException(400, f"'{ref.client_id}' has no role called '{ref.role}'")
    await bypass_tenant_rls(db)
    member_ids = set()
    for user_id in set(body.members):
        try:
            user = await db.get(User, uuid.UUID(user_id))
        except ValueError:
            user = None
        if user is None:
            raise HTTPException(404, "unknown_user")
        member_ids.add(user.id)
    db.add(team)
    await db.flush()
    db.add_all(TeamAppAccess(team_id=team.id, client_id=c) for c in sorted(set(body.apps)))
    db.add_all(TeamRole(team_id=team.id, client_id=r.client_id, role=r.role) for r in {(r.client_id, r.role): r for r in body.roles}.values())
    db.add_all(TeamMember(team_id=team.id, user_id=u) for u in member_ids)
    await db.commit()
    log_event(
        "team_created",
        team=name,
        apps=sorted(set(body.apps)),
        roles=[f"{r.client_id}:{r.role}" for r in body.roles],
        members=len(member_ids),
        admin_id=str(admin.id),
    )
    return await _one_team_json(db, team)


@router.patch("/teams/{team_id}")
async def api_edit_team(
    team_id: str,
    body: TeamBody,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    team = await _team(db, team_id)
    name = _clean_name(body.name)
    if await _name_taken(db, name, except_id=team.id):
        raise HTTPException(400, f"There's already a team called '{name}'")
    team.name = name
    team.description = body.description.strip() or None
    moved = team.parent_id != (new_parent := await _check_parent(db, team.id, body.parent_id))
    team.parent_id = new_parent
    await db.commit()
    log_event("team_updated", team=name, admin_id=str(admin.id))
    if moved:  # it may have lost what its old parent gave
        await enforce_access(db, redis, await _members_of(db, team.id))
    return await _one_team_json(db, team)


@router.delete("/teams/{team_id}", status_code=204)
async def api_delete_team(
    team_id: str,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    team = await _team(db, team_id)
    if (await db.execute(select(Team.id).where(Team.parent_id == team.id))).first() is not None:
        raise HTTPException(409, "Move or delete this team's sub-teams first")
    affected = await _members_of(db, team.id)
    for model in (TeamMember, TeamAppAccess, TeamRole):
        await db.execute(delete(model).where(model.team_id == team.id))
    for app in (await db.execute(select(Client).where(Client.signup_team_id == team.id))).scalars().all():
        app.signup_team_id = None
    await db.delete(team)
    await db.commit()
    log_event("team_deleted", team=team.name, admin_id=str(admin.id))
    await enforce_access(db, redis, affected)


# --- Members ---


@router.get("/teams/{team_id}/members")
async def api_list_team_members(team_id: str, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    team = await _team(db, team_id)
    await bypass_tenant_rls(db)
    rows = await db.execute(
        select(
            User.id,
            User.email,
            User.first_name,
            User.last_name,
            User.client_id,
            Client.client_name,
            UserPool.name,
            TeamMember.expires_at,
            TeamMember.is_manager,
        )
        .join(TeamMember, TeamMember.user_id == User.id)
        .outerjoin(Client, Client.client_id == User.client_id)
        .outerjoin(UserPool, UserPool.id == Client.user_pool_id)
        .where(TeamMember.team_id == team.id)
        .order_by(User.email)
    )
    return [
        {
            "user_id": str(uid),
            "email": email,
            "name": " ".join(p for p in (first, last) if p),
            "client_id": client_id,
            "client_name": client_name,
            "pool_name": pool_name,
            "expires_at": expires.isoformat() if expires else None,
            "is_manager": manager,
        }
        for uid, email, first, last, client_id, client_name, pool_name, expires, manager in rows.all()
    ]


class MemberBody(BaseModel):
    user_id: str
    # Membership ends by itself then; None = no end.
    expires_at: datetime | None = None
    # Can add and remove this team's people from their own account page.
    is_manager: bool = False


@router.post("/teams/{team_id}/members", status_code=201)
async def api_add_team_member(
    team_id: str, body: MemberBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    team = await _team(db, team_id)
    await bypass_tenant_rls(db)
    try:
        user = await db.get(User, uuid.UUID(body.user_id))
    except ValueError:
        user = None
    if user is None:
        raise HTTPException(404, "unknown_user")
    expires = _future(body.expires_at)
    member = (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id))
    ).scalar_one_or_none()
    if member is None:
        db.add(TeamMember(team_id=team.id, user_id=user.id, expires_at=expires, is_manager=body.is_manager))
    else:
        member.expires_at, member.is_manager = expires, body.is_manager
    await db.commit()
    log_event(
        "team_member_added",
        team=team.name,
        user_id=str(user.id),
        email=user.email,
        expires_at=expires.isoformat() if expires else None,
        manager=body.is_manager,
        admin_id=str(admin.id),
    )
    return {"user_id": str(user.id), "email": user.email}


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
async def api_remove_team_member(
    team_id: str,
    user_id: str,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    team = await _team(db, team_id)
    result = await db.execute(
        delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == uuid.UUID(user_id))
    )
    if result.rowcount == 0:
        raise HTTPException(404, "not_a_member")
    await db.commit()
    log_event("team_member_removed", team=team.name, user_id=user_id, admin_id=str(admin.id))
    await enforce_access(db, redis, {uuid.UUID(user_id)})


# --- What the team gives ---


class AppBody(BaseModel):
    client_id: str


async def _client(db: AsyncSession, client_id: str) -> Client:
    client = (await db.execute(select(Client).where(Client.client_id == client_id))).scalar_one_or_none()
    if client is None:
        raise HTTPException(404, "unknown_client")
    return client


@router.post("/teams/{team_id}/apps", status_code=201)
async def api_add_team_app(
    team_id: str, body: AppBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    team = await _team(db, team_id)
    client = await _client(db, body.client_id)
    exists = await db.execute(
        select(TeamAppAccess.id).where(TeamAppAccess.team_id == team.id, TeamAppAccess.client_id == client.client_id)
    )
    if exists.first() is None:
        db.add(TeamAppAccess(team_id=team.id, client_id=client.client_id))
        await db.commit()
        log_event("team_app_access_added", team=team.name, client_id=client.client_id, admin_id=str(admin.id))
    return await _one_team_json(db, team)


@router.delete("/teams/{team_id}/apps/{client_id}")
async def api_remove_team_app(
    team_id: str,
    client_id: str,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    team = await _team(db, team_id)
    await db.execute(delete(TeamAppAccess).where(TeamAppAccess.team_id == team.id, TeamAppAccess.client_id == client_id))
    await db.commit()
    log_event("team_app_access_removed", team=team.name, client_id=client_id, admin_id=str(admin.id))
    await enforce_access(db, redis, await _members_of(db, team.id))
    return await _one_team_json(db, team)


class TeamRoleBody(BaseModel):
    client_id: str
    role: str


@router.post("/teams/{team_id}/roles", status_code=201)
async def api_add_team_role(
    team_id: str, body: TeamRoleBody, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    team = await _team(db, team_id)
    role = await db.get(ClientRole, (body.client_id, body.role))
    if role is None:
        raise HTTPException(400, f"'{body.client_id}' has no role called '{body.role}'")
    exists = await db.execute(
        select(TeamRole.id).where(
            TeamRole.team_id == team.id, TeamRole.client_id == body.client_id, TeamRole.role == body.role
        )
    )
    if exists.first() is None:
        db.add(TeamRole(team_id=team.id, client_id=body.client_id, role=body.role))
        await db.commit()
        log_event("team_role_added", team=team.name, client_id=body.client_id, role=body.role, admin_id=str(admin.id))
    return await _one_team_json(db, team)


@router.delete("/teams/{team_id}/roles/{client_id}/{role}")
async def api_remove_team_role(
    team_id: str, client_id: str, role: str, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    team = await _team(db, team_id)
    await db.execute(
        delete(TeamRole).where(TeamRole.team_id == team.id, TeamRole.client_id == client_id, TeamRole.role == role)
    )
    await db.commit()
    log_event("team_role_removed", team=team.name, client_id=client_id, role=role, admin_id=str(admin.id))
    return await _one_team_json(db, team)


# --- A person's teams ---


@router.get("/users/{user_id}/teams")
async def api_user_teams(user_id: str, admin: AdminUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """The teams someone is directly in (sub-team membership also gives
    what each parent team gives, shown on the Teams page)."""
    rows = await db.execute(
        select(Team.id, Team.name)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == uuid.UUID(user_id))
        .order_by(func.lower(Team.name))
    )
    return [{"id": str(tid), "name": name} for tid, name in rows.all()]


class UserTeamsBody(BaseModel):
    team_ids: list[str]


@router.put("/users/{user_id}/teams")
async def api_set_user_teams(
    user_id: str,
    body: UserTeamsBody,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Set exactly which teams someone is directly in, from their own panel."""
    await bypass_tenant_rls(db)
    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(404, "unknown_user")
    wanted = {(await _team(db, t)).id for t in set(body.team_ids)}
    current = {t for (t,) in (await db.execute(select(TeamMember.team_id).where(TeamMember.user_id == user.id))).all()}
    names = dict((await db.execute(select(Team.id, Team.name))).all())
    for team_id in wanted - current:
        db.add(TeamMember(team_id=team_id, user_id=user.id))
        log_event("team_member_added", team=names[team_id], user_id=str(user.id), email=user.email, admin_id=str(admin.id))
    if current - wanted:
        await db.execute(delete(TeamMember).where(TeamMember.user_id == user.id, TeamMember.team_id.in_(current - wanted)))
        for team_id in current - wanted:
            log_event("team_member_removed", team=names[team_id], user_id=str(user.id), email=user.email, admin_id=str(admin.id))
    await db.commit()
    if current - wanted:
        await enforce_access(db, redis, {user.id})
    return await api_user_teams(user_id, admin, db)


class MemberChangeBody(BaseModel):
    expires_at: datetime | None = None
    is_manager: bool = False


@router.patch("/teams/{team_id}/members/{user_id}")
async def api_change_team_member(
    team_id: str,
    user_id: str,
    body: MemberChangeBody,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set when someone's membership ends, and whether they manage the team."""
    team = await _team(db, team_id)
    member = (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == uuid.UUID(user_id)))
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(404, "not_a_member")
    member.expires_at = _future(body.expires_at)
    member.is_manager = body.is_manager
    await db.commit()
    log_event(
        "team_member_changed",
        team=team.name,
        user_id=user_id,
        expires_at=member.expires_at.isoformat() if member.expires_at else None,
        manager=member.is_manager,
        admin_id=str(admin.id),
    )
    return {"user_id": user_id, "expires_at": member.expires_at.isoformat() if member.expires_at else None, "is_manager": member.is_manager}
