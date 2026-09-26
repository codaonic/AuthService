from fastapi import APIRouter

from app.oidc.keys import get_key_manager

router = APIRouter()


@router.get("/jwks.json")
async def jwks():
    return get_key_manager().jwks()
