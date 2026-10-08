import argparse
import asyncio
import secrets
import sys

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db.models import Client, Resource, User, UserPool
from app.db.pools import get_or_create_pool
from app.db.session import async_session_factory
from app.db.tenant import bypass_tenant_rls


async def register_client(args: argparse.Namespace) -> None:
    is_public = args.type == "public"
    client_secret = None if is_public else (args.secret or secrets.token_urlsafe(32))

    async with async_session_factory() as db:
        existing = await db.execute(select(Client).where(Client.client_id == args.client_id))
        if existing.scalar_one_or_none() is not None:
            print(f"error: client '{args.client_id}' already exists", file=sys.stderr)
            raise SystemExit(1)

        pool = await get_or_create_pool(db, args.user_pool) if args.user_pool else None

        db.add(
            Client(
                user_pool_id=pool.id if pool else None,
                client_id=args.client_id,
                client_secret_hash=hash_password(client_secret) if client_secret else None,
                client_type=args.type,
                redirect_uris=args.redirect_uri or [],
                grant_types=args.grant_type,
                allowed_scope=args.scope or "",
                registration_method="static",
                application_type=args.application_type,
                mtls_cert_thumbprint=args.mtls_thumbprint,
                logo_url=args.logo_url,
                brand_color=args.brand_color,
            )
        )
        await db.commit()

    pool_str = f" in pool '{args.user_pool}'" if args.user_pool else " (standalone, no pool)"
    print(f"registered client '{args.client_id}' ({args.type}){pool_str}")
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
        await bypass_tenant_rls(db)

        client = (await db.execute(select(Client).where(Client.client_id == args.client_id))).scalar_one_or_none()
        if client is None:
            print(f"error: client '{args.client_id}' not found", file=sys.stderr)
            raise SystemExit(1)

        existing = await db.execute(
            select(User).where(User.email == args.email, User.client_id == args.client_id)
        )
        if existing.scalar_one_or_none() is not None:
            print(f"error: user '{args.email}' already exists in app '{args.client_id}'", file=sys.stderr)
            raise SystemExit(1)

        db.add(
            User(client_id=args.client_id, email=args.email, password_hash=hash_password(args.password))
        )
        await db.commit()

    print(f"created user '{args.email}' in app '{args.client_id}'")


async def list_clients(_args: argparse.Namespace) -> None:
    from sqlalchemy.orm import outerjoin as _outerjoin
    async with async_session_factory() as db:
        result = await db.execute(
            select(Client, UserPool.name).outerjoin(UserPool, Client.user_pool_id == UserPool.id)
        )
        for client, pool_name in result.all():
            pool_str = f"pool={pool_name}" if pool_name else "standalone"
            print(f"{client.client_id}\t{client.client_type}\t{client.registration_method}\t{pool_str}")


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
        "--mtls-thumbprint",
        help=(
            "Hex cert thumbprint of this client's certificate, for mutual-TLS client "
            "auth instead of a shared secret -- must match whatever hash algorithm "
            "your reverse proxy forwards (stock nginx sends SHA-1). Requires your "
            "reverse proxy to verify client certs and forward the result -- see "
            "README's mTLS section."
        ),
    )
    p.add_argument(
        "--logo-url", help="Shown on this client's login/signup/consent pages instead of the default icon"
    )
    p.add_argument(
        "--brand-color", help="CSS color (e.g. #1d4ed8) applied to this client's login/signup/consent pages"
    )
    p.add_argument(
        "--user-pool",
        default=None,
        help=(
            "Assign this client to a named login group (created if it doesn't exist). "
            "Clients sharing a pool share one set of users. Leave blank for a standalone "
            "client with its own isolated users."
        ),
    )
    p.set_defaults(func=register_client)

    p = subparsers.add_parser("register-resource", help="Register a protected resource (API or MCP server)")
    p.add_argument("--resource-id", required=True, help="The resource indicator / aud value, e.g. a URL")
    p.add_argument("--name", required=True)
    p.add_argument("--metadata-url", help="Optional URL to the resource's own metadata document")
    p.set_defaults(func=register_resource)

    p = subparsers.add_parser("create-user", help="Create a login user for a specific application")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--client-id", required=True, help="The application (client_id) to add this user to")
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
