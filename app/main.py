from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.admin import auth as admin_auth
from app.admin import routes as admin_routes
from app.admin.seed import ensure_default_admin
from app.db.session import init_db_schema, wait_for_database
from app.middleware.rate_limit import limiter
from app.oidc import authorize, discovery, jwks, prm, register, revoke, token, userinfo


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await wait_for_database()
    await init_db_schema()
    await ensure_default_admin()
    yield


app = FastAPI(title="Auth Service", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(discovery.router)
app.include_router(prm.router)
app.include_router(jwks.router)
app.include_router(authorize.router)
app.include_router(token.router)
app.include_router(register.router)
app.include_router(revoke.router)
app.include_router(userinfo.router)

# Operator-facing setup UI: pools, clients, resources, users.
app.include_router(admin_auth.router)
app.include_router(admin_routes.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
