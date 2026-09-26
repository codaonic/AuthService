import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import get_current_admin
from app.auth.passwords import hash_password, verify_password
from app.db.models import AdminUser, Client, Resource, User, UserPool
from app.db.pools import get_or_create_pool
from app.db.redis_client import get_redis
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ALL_GRANT_TYPES = ["authorization_code", "refresh_token", "client_credentials"]
NOT_LOGGED_IN = RedirectResponse("/admin/login", status_code=303)


def _ctx(admin: AdminUser, active: str, **extra) -> dict:
    return {"active": active, "must_change_password": admin.must_change_password, **extra}


@router.get("/admin")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    counts = {}
    for label, model in [("pools", UserPool), ("clients", Client), ("resources", Resource), ("users", User)]:
        result = await db.execute(select(func.count()).select_from(model))
        counts[label] = result.scalar_one()

    return templates.TemplateResponse(
        request, "admin/dashboard.html", _ctx(admin, "dashboard", counts=counts)
    )


@router.get("/admin/pools")
async def list_pools(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    result = await db.execute(select(UserPool).order_by(UserPool.name))
    pools = result.scalars().all()
    return templates.TemplateResponse(request, "admin/pools.html", _ctx(admin, "pools", pools=pools, error=None))


@router.post("/admin/pools")
async def create_pool(
    request: Request,
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    await get_or_create_pool(db, name)
    return RedirectResponse("/admin/pools", status_code=303)


@router.get("/admin/resources")
async def list_resources(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    result = await db.execute(select(Resource).order_by(Resource.name))
    resources = result.scalars().all()
    return templates.TemplateResponse(
        request, "admin/resources.html", _ctx(admin, "resources", resources=resources, error=None)
    )


@router.post("/admin/resources")
async def create_resource(
    request: Request,
    resource_id: str = Form(...),
    name: str = Form(...),
    metadata_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    existing = await db.execute(select(Resource).where(Resource.resource_id == resource_id))
    if existing.scalar_one_or_none() is not None:
        result = await db.execute(select(Resource).order_by(Resource.name))
        resources = result.scalars().all()
        return templates.TemplateResponse(
            request,
            "admin/resources.html",
            _ctx(admin, "resources", resources=resources, error=f"'{resource_id}' already exists"),
            status_code=400,
        )

    db.add(Resource(resource_id=resource_id, name=name, metadata_url=metadata_url or None))
    await db.commit()
    return RedirectResponse("/admin/resources", status_code=303)


@router.get("/admin/clients")
async def list_clients(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    result = await db.execute(select(Client, UserPool.name).join(UserPool).order_by(Client.client_id))
    clients = result.all()
    pools_result = await db.execute(select(UserPool).order_by(UserPool.name))
    pools = pools_result.scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/clients.html",
        _ctx(admin, "clients", clients=clients, pools=pools, grant_types=ALL_GRANT_TYPES, error=None),
    )


@router.post("/admin/clients")
async def create_client(
    request: Request,
    client_id: str = Form(...),
    client_type: str = Form(...),
    redirect_uris: str = Form(""),
    grant_types: list[str] = Form([]),
    scope: str = Form(""),
    application_type: str = Form("web"),
    user_pool: str = Form("default"),
    allow_signup: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    async def render_error(message: str):
        result = await db.execute(select(Client, UserPool.name).join(UserPool).order_by(Client.client_id))
        clients = result.all()
        pools_result = await db.execute(select(UserPool).order_by(UserPool.name))
        pools = pools_result.scalars().all()
        return templates.TemplateResponse(
            request,
            "admin/clients.html",
            _ctx(admin, "clients", clients=clients, pools=pools, grant_types=ALL_GRANT_TYPES, error=message),
            status_code=400,
        )

    existing = await db.execute(select(Client).where(Client.client_id == client_id))
    if existing.scalar_one_or_none() is not None:
        return await render_error(f"client '{client_id}' already exists")

    is_public = client_type == "public"
    client_secret = None if is_public else secrets.token_urlsafe(32)
    pool = await get_or_create_pool(db, user_pool)

    db.add(
        Client(
            user_pool_id=pool.id,
            client_id=client_id,
            client_secret_hash=hash_password(client_secret) if client_secret else None,
            client_type=client_type,
            redirect_uris=[u.strip() for u in redirect_uris.splitlines() if u.strip()],
            grant_types=grant_types or ["authorization_code", "refresh_token"],
            allowed_scope=scope,
            registration_method="static",
            application_type=application_type,
            allow_signup=allow_signup,
        )
    )
    await db.commit()

    return templates.TemplateResponse(
        request,
        "admin/client_created.html",
        _ctx(admin, "clients", client_id=client_id, user_pool=user_pool, client_secret=client_secret),
    )


@router.post("/admin/clients/{client_id}/toggle-signup")
async def toggle_client_signup(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if client is not None:
        client.allow_signup = not client.allow_signup
        await db.commit()

    return RedirectResponse("/admin/clients", status_code=303)


@router.get("/admin/users")
async def list_users(
    request: Request,
    pool: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    query = select(User, UserPool.name).join(UserPool).order_by(User.email)
    if pool:
        query = query.where(UserPool.name == pool)
    result = await db.execute(query)
    users = result.all()

    pools_result = await db.execute(select(UserPool).order_by(UserPool.name))
    pools = pools_result.scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        _ctx(admin, "users", users=users, pools=pools, selected_pool=pool or "", error=None),
    )


@router.post("/admin/users")
async def create_user_route(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    user_pool: str = Form("default"),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    pool = await get_or_create_pool(db, user_pool)
    existing = await db.execute(
        select(User).where(User.email == email, User.user_pool_id == pool.id)
    )
    if existing.scalar_one_or_none() is not None:
        result = await db.execute(select(User, UserPool.name).join(UserPool).order_by(User.email))
        users = result.all()
        pools_result = await db.execute(select(UserPool).order_by(UserPool.name))
        pools = pools_result.scalars().all()
        return templates.TemplateResponse(
            request,
            "admin/users.html",
            _ctx(
                admin,
                "users",
                users=users,
                pools=pools,
                selected_pool="",
                error=f"'{email}' already exists in pool '{user_pool}'",
            ),
            status_code=400,
        )

    db.add(User(user_pool_id=pool.id, email=email, password_hash=hash_password(password)))
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/admin/account")
async def account_page(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    return templates.TemplateResponse(request, "admin/account.html", _ctx(admin, "account", error=None, success=None))


@router.post("/admin/account")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    admin = await get_current_admin(request, db, redis)
    if admin is None:
        return NOT_LOGGED_IN

    if not verify_password(current_password, admin.password_hash):
        return templates.TemplateResponse(
            request,
            "admin/account.html",
            _ctx(admin, "account", error="Current password is incorrect", success=None),
            status_code=400,
        )
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            "admin/account.html",
            _ctx(admin, "account", error="New passwords do not match", success=None),
            status_code=400,
        )
    if len(new_password) < 8:
        return templates.TemplateResponse(
            request,
            "admin/account.html",
            _ctx(admin, "account", error="Password must be at least 8 characters", success=None),
            status_code=400,
        )

    admin.password_hash = hash_password(new_password)
    admin.must_change_password = False
    await db.commit()

    return templates.TemplateResponse(
        request,
        "admin/account.html",
        {"active": "account", "must_change_password": False, "error": None, "success": "Password updated"},
    )
