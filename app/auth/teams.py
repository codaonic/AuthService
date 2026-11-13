"""What a person gets from the teams they're in.

Someone in a team also counts as being in each of its parent teams, so a
member of "Support / Night shift" gets what "Support" gives. Everything a
team gives is per app, and only ever on top of the login group check: a team
can't let anyone into an app outside their login group.

Every sign-in and every token refresh goes through `has_app_access` and
`roles_for`, so a change to a team applies at the person's next refresh
(within one access-token lifetime), not at their next full sign-in.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ClientAccessGrant,
    ClientRoleInclude,
    Team,
    TeamAppAccess,
    TeamMember,
    TeamRole,
    UserRoleAssignment,
)


def _live(column):
    """Rows whose end time, if they have one, hasn't passed."""
    return or_(column.is_(None), column > datetime.now(timezone.utc))


async def parent_map(db: AsyncSession) -> dict[uuid.UUID, uuid.UUID | None]:
    return dict((await db.execute(select(Team.id, Team.parent_id))).all())


def with_ancestors(team_ids: set[uuid.UUID], parents: dict[uuid.UUID, uuid.UUID | None]) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    for team_id in team_ids:
        # The `found` check also stops a loop, should one ever be stored.
        while team_id is not None and team_id not in found:
            found.add(team_id)
            team_id = parents.get(team_id)
    return found


async def teams_of(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """The teams someone is in, directly or through a sub-team."""
    direct = {
        t
        for (t,) in (
            await db.execute(select(TeamMember.team_id).where(TeamMember.user_id == user_id, _live(TeamMember.expires_at)))
        ).all()
    }
    if not direct:
        return set()
    return with_ancestors(direct, await parent_map(db))


async def has_app_access(db: AsyncSession, client_id: str, user_id: uuid.UUID | str) -> bool:
    """For an app that restricts access: is this person on its list, either
    themselves or through a team?"""
    user_id = uuid.UUID(str(user_id))
    grant = await db.execute(
        select(ClientAccessGrant.id).where(
            ClientAccessGrant.client_id == client_id,
            ClientAccessGrant.user_id == user_id,
            _live(ClientAccessGrant.expires_at),
        )
    )
    if grant.first() is not None:
        return True
    teams = await teams_of(db, user_id)
    if not teams:
        return False
    via_team = await db.execute(
        select(TeamAppAccess.id).where(TeamAppAccess.client_id == client_id, TeamAppAccess.team_id.in_(teams))
    )
    return via_team.first() is not None


async def roles_for(db: AsyncSession, client_id: str, user_id: uuid.UUID | str) -> list[str]:
    """Someone's roles on one app: their own plus their teams'. Sorted, no repeats."""
    user_id = uuid.UUID(str(user_id))
    own = await db.execute(
        select(UserRoleAssignment.role).where(
            UserRoleAssignment.user_id == user_id, UserRoleAssignment.client_id == client_id
        )
    )
    roles = {r for (r,) in own.all()}
    teams = await teams_of(db, user_id)
    if teams:
        inherited = await db.execute(
            select(TeamRole.role).where(TeamRole.client_id == client_id, TeamRole.team_id.in_(teams))
        )
        roles |= {r for (r,) in inherited.all()}
    return sorted(await expand_roles(db, client_id, roles))


async def expand_roles(db: AsyncSession, client_id: str, roles: set[str]) -> set[str]:
    """Add every role the given ones include, through any number of levels."""
    if not roles:
        return roles
    includes: dict[str, set[str]] = {}
    for role, inc in (
        await db.execute(select(ClientRoleInclude.role, ClientRoleInclude.includes).where(ClientRoleInclude.client_id == client_id))
    ).all():
        includes.setdefault(role, set()).add(inc)
    found, todo = set(roles), list(roles)
    while todo:
        for inc in includes.get(todo.pop(), ()):
            if inc not in found:
                found.add(inc)
                todo.append(inc)
    return found
