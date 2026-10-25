from fastapi import APIRouter, Response

from app.oidc.keys import get_key_manager

router = APIRouter()


@router.get("/jwks.json")
async def jwks(response: Response):
    # Resource servers fetch this to verify tokens; let them (and any proxy)
    # reuse it for a few minutes instead of asking on every request. Short
    # enough that a newly rotated key is seen well before old tokens expire.
    response.headers["Cache-Control"] = "public, max-age=300"
    return get_key_manager().jwks()
