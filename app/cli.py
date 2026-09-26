import argparse
import asyncio
import secrets
import sys

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db.models import Client, Resource, User, UserPool
from app.db.pools import DEFAULT_POOL_NAME, get_or_create_pool
from app.db.session import async_session_factory


async def register_client(args: argparse.Namespace) -> None:
    is_public = args.type == "public"
    client_secret = None if is_public else (args.secret or secrets.token_urlsafe(32))

    async with async_session_factory() as db:
        existing = await db.execute(select(Client).where(Client.client_id == args.client_id))
        if existing.scalar_one_or_none() is not None:
            print(f"error: client '{args.client_id}' already exists", file=sys.stderr)
            raise SystemExit(1)

        pool = await get_or_create_pool(db, args.user_pool)

        db.add(
            Client(
                user_pool_id=pool.id,
                client_id=args.client_id,
                client_secret_hash=hash_password(client_secret) if client_secret else None,
                client_type=args.type,
                redirect_uris=args.redirect_uri or [],
                grant_types=args.grant_type,
                allowed_scope=args.scope or "",
                registration_method="static",
                application_type=args.application_type,
            )
        )
        await db.commit()

    print(f"registered client '{args.client_id}' ({args.type}) in user pool '{args.user_pool}'")
    if client_secret:
        print(f"client_secret: {client_secret}")
        print("store this now -- it is not saved anywhere in retrievable form")


async def register_resource(args: argparse.Namespace) -> None:
    async with async_session_factory() as db:
        existing = await db.execute(select(Resource).where(Resource.resource_id == args.resource_id))
        if existing.scalar_one_or_none() is not None:
            print(f"error: resource '{args.resource_id}' already exists", file=sys.stderr)
            raise SystemExit(1)

        db.add(
            Resource(
                resource_id=args.resource_id,
                name=args.name,
                metadata_url=args.metadata_url,
            )
        )
        await db.commit()

    print(f"registered resource '{args.resource_id}'")


async def create_user(args: argparse.Namespace) -> None:
    async with async_session_factory() as db:
        pool = await get_or_create_pool(db, args.user_pool)

        existing = await db.execute(
            select(User).where(User.email == args.email, User.user_pool_id == pool.id)
        )
        if existing.scalar_one_or_none() is not None:
            print(f"error: user '{args.email}' already exists in pool '{args.user_pool}'", file=sys.stderr)
            raise SystemExit(1)

        db.add(
            User(user_pool_id=pool.id, email=args.email, password_hash=hash_password(args.password))
        )
        await db.commit()

    print(f"created user '{args.email}' in user pool '{args.user_pool}'")


async def list_clients(_args: argparse.Namespace) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Client, UserPool.name).join(UserPool))
        for client, pool_name in result.all():
            print(f"{client.client_id}\t{client.client_type}\t{client.registration_method}\tpool={pool_name}")


async def list_resources(_args: argparse.Namespace) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Resource))
        for resource in result.scalars():
            print(f"{resource.resource_id}\t{resource.name}")


async def list_pools(_args: argparse.Namespace) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(UserPool))
        for pool in result.scalars():
            print(f"{pool.name}\t{pool.id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Auth service admin CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("register-client", help="Register a static OAuth client")
    p.add_argument("--client-id", required=True)
    p.add_argument("--type", choices=["public", "confidential"], required=True)
    p.add_argument("--redirect-uri", action="append", help="Repeatable")
    p.add_argument(
        "--grant-type",
        action="append",
        default=["authorization_code", "refresh_token"],
        help="Repeatable; defaults to authorization_code + refresh_token",
    )
    p.add_argument("--scope", help="Space-separated allowed scopes")
    p.add_argument("--application-type", default="web", choices=["web", "native", "service"])
    p.add_argument("--secret", help="Confidential clients only; generated if omitted")
    p.add_argument(
        "--user-pool",
        default=DEFAULT_POOL_NAME,
        help=(
            "Which user pool this client's users belong to (created if it doesn't exist). "
            "Clients sharing a pool name share one set of users; give a client its own "
            "unique name to isolate it. Defaults to the shared 'default' pool."
        ),
    )
    p.set_defaults(func=register_client)

    p = subparsers.add_parser("register-resource", help="Register a protected resource (API or MCP server)")
    p.add_argument("--resource-id", required=True, help="The resource indicator / aud value, e.g. a URL")
    p.add_argument("--name", required=True)
    p.add_argument("--metadata-url", help="Optional URL to the resource's own metadata document")
    p.set_defaults(func=register_resource)

    p = subparsers.add_parser("create-user", help="Create a login user")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--user-pool", default=DEFAULT_POOL_NAME)
    p.set_defaults(func=create_user)

    p = subparsers.add_parser("list-clients", help="List registered clients")
    p.set_defaults(func=list_clients)

    p = subparsers.add_parser("list-resources", help="List registered resources")
    p.set_defaults(func=list_resources)

    p = subparsers.add_parser("list-pools", help="List user pools")
    p.set_defaults(func=list_pools)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
