from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserPool

DEFAULT_POOL_NAME = "default"


async def get_or_create_pool(db: AsyncSession, name: str) -> UserPool:
    """Look up a user pool by name, creating it if it doesn't exist yet.

    Pools are created implicitly by name so registering clients/users never
    requires a separate pool-management step: reuse a name to share users
    across clients, use a new name to isolate them.
    """
    result = await db.execute(select(UserPool).where(UserPool.name == name))
    pool = result.scalar_one_or_none()
    if pool is None:
        pool = UserPool(name=name)
        db.add(pool)
        await db.commit()
        await db.refresh(pool)
    return pool
