import pytest
from sqlalchemy import select

from app import cli
from app.db.models import Client, Resource, User


def _args(**kwargs):
    return cli.argparse.Namespace(**kwargs)


@pytest.mark.asyncio
async def test_register_public_client(db_session, monkeypatch):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)

    await cli.register_client(
        _args(
            client_id="cli-public",
            type="public",
            redirect_uri=["https://app.example.com/cb"],
            grant_type=["authorization_code", "refresh_token"],
            scope="profile",
            application_type="native",
            secret=None,
        )
    )

    result = await db_session.execute(select(Client).where(Client.client_id == "cli-public"))
    client = result.scalar_one()
    assert client.client_type == "public"
    assert client.client_secret_hash is None


@pytest.mark.asyncio
async def test_register_confidential_client_generates_secret(db_session, monkeypatch, capsys):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)

    await cli.register_client(
        _args(
            client_id="cli-confidential",
            type="confidential",
            redirect_uri=None,
            grant_type=["client_credentials"],
            scope=None,
            application_type="service",
            secret=None,
        )
    )

    result = await db_session.execute(select(Client).where(Client.client_id == "cli-confidential"))
    client = result.scalar_one()
    assert client.client_secret_hash is not None
    assert "client_secret:" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_register_duplicate_client_exits(db_session, monkeypatch):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)
    args = _args(
        client_id="dup-client",
        type="public",
        redirect_uri=["https://app.example.com/cb"],
        grant_type=["authorization_code"],
        scope=None,
        application_type="web",
        secret=None,
    )
    await cli.register_client(args)

    with pytest.raises(SystemExit):
        await cli.register_client(args)


@pytest.mark.asyncio
async def test_register_resource(db_session, monkeypatch):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)

    await cli.register_resource(
        _args(resource_id="https://mcp.example.com", name="Example MCP Server", metadata_url=None)
    )

    result = await db_session.execute(
        select(Resource).where(Resource.resource_id == "https://mcp.example.com")
    )
    resource = result.scalar_one()
    assert resource.name == "Example MCP Server"


@pytest.mark.asyncio
async def test_create_user(db_session, monkeypatch):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)

    await cli.create_user(_args(email="cli-user@example.com", password="s3cret-password!"))

    result = await db_session.execute(select(User).where(User.email == "cli-user@example.com"))
    user = result.scalar_one()
    assert user.email == "cli-user@example.com"
