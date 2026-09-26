from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import verify_password
from app.db.models import Client


async def get_and_validate_client(
    db: AsyncSession, client_id: str, client_secret: str | None
) -> Client:
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(401, "invalid_client")

    if client.client_type == "confidential":
        if not client_secret or client.client_secret_hash is None:
            raise HTTPException(401, "invalid_client")
        if not verify_password(client_secret, client.client_secret_hash):
            raise HTTPException(401, "invalid_client")
    elif client_secret:
        raise HTTPException(401, "invalid_client")

    return client
