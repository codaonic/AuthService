import pytest
from sqlalchemy import select

from app import cli
from app.db.models import Client, Resource, User, UserPool


def _args(**kwargs):
    kwargs.setdefault("user_pool", "default")
    kwargs.setdefault("mtls_thumbprint", None)
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


@pytest.mark.asyncio
async def test_clients_sharing_pool_name_share_one_pool(db_session, monkeypatch):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)

    await cli.register_client(
        _args(
            client_id="acme-web",
            type="public",
            redirect_uri=["https://acme.example.com/cb"],
            grant_type=["authorization_code"],
            scope=None,
            application_type="web",
            secret=None,
            user_pool="acme",
        )
    )
    await cli.register_client(
        _args(
            client_id="acme-mobile",
            type="public",
            redirect_uri=["acme://cb"],
            grant_type=["authorization_code"],
            scope=None,
            application_type="native",
            secret=None,
            user_pool="acme",
        )
    )

    result = await db_session.execute(select(Client).where(Client.client_id.in_(["acme-web", "acme-mobile"])))
    clients = result.scalars().all()
    assert len({c.user_pool_id for c in clients}) == 1


@pytest.mark.asyncio
async def test_clients_with_different_pool_names_are_isolated(db_session, monkeypatch):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)

    await cli.register_client(
        _args(
            client_id="tenant-a",
            type="public",
            redirect_uri=["https://a.example.com/cb"],
            grant_type=["authorization_code"],
            scope=None,
            application_type="web",
            secret=None,
            user_pool="tenant-a",
        )
    )
    await cli.register_client(
        _args(
            client_id="tenant-b",
            type="public",
            redirect_uri=["https://b.example.com/cb"],
            grant_type=["authorization_code"],
            scope=None,
            application_type="web",
            secret=None,
            user_pool="tenant-b",
        )
    )

    result = await db_session.execute(select(Client).where(Client.client_id.in_(["tenant-a", "tenant-b"])))
    clients = result.scalars().all()
    assert len({c.user_pool_id for c in clients}) == 2


@pytest.mark.asyncio
async def test_list_pools(db_session, monkeypatch):
    monkeypatch.setattr(cli, "async_session_factory", lambda: db_session)
    await cli.create_user(_args(email="a@example.com", password="s3cret-password!", user_pool="acme"))

    result = await db_session.execute(select(UserPool).where(UserPool.name == "acme"))
    assert result.scalar_one() is not None
