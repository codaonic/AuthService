from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Resource
from app.db.session import get_db

router = APIRouter()


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(
    resource: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    result = await db.execute(select(Resource).where(Resource.resource_id == resource))
    resource_row = result.scalar_one_or_none()
    if resource_row is None:
        raise HTTPException(404, "unknown_resource")

    return {
        "resource": resource_row.resource_id,
        "authorization_servers": [settings.issuer_url],
        "bearer_methods_supported": ["header"],
        "resource_name": resource_row.name,
    }
