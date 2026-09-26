import base64
import hashlib
import secrets

from app.auth.passwords import hash_password
from app.db.models import Client, Resource, User


def make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def create_user(db_session, email="user@example.com", password="correct horse battery"):
    user = User(email=email, password_hash=hash_password(password))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def create_client(
    db_session,
    client_id="test-client",
    client_type="public",
    redirect_uris=("https://client.example.com/callback",),
    grant_types=("authorization_code", "refresh_token"),
    client_secret=None,
):
    client = Client(
        client_id=client_id,
        client_secret_hash=hash_password(client_secret) if client_secret else None,
        client_type=client_type,
        redirect_uris=list(redirect_uris),
        grant_types=list(grant_types),
        allowed_scope="profile email",
    )
    db_session.add(client)
    await db_session.commit()
    return client


async def create_resource(db_session, resource_id="https://api.example.com", name="API"):
    resource = Resource(resource_id=resource_id, name=name)
    db_session.add(resource)
    await db_session.commit()
    return resource


def extract_hidden_value(html: str, field_name: str) -> str:
    marker = f'name="{field_name}" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]
