from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.admin import api as admin_api
from app.admin.seed import ensure_default_admin
from app.db.session import init_db_schema, wait_for_database
from app.middleware.rate_limit import limiter
from app.oidc import (
    authorize,
    discovery,
    jwks,
    logout,
    password_reset,
    prm,
    register,
    revoke,
    token,
    userinfo,
    webauthn,
)


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
app.include_router(password_reset.router)
app.include_router(webauthn.router)
app.include_router(token.router)
app.include_router(register.router)
app.include_router(revoke.router)
app.include_router(logout.router)
app.include_router(userinfo.router)

# JSON API for the admin console (React SPA, served below).
app.include_router(admin_api.router)

# Operator-facing admin console -- a React SPA built by `frontend/` (see its
# README) into `frontend/dist`. Registered after admin_api.router so
# /admin/api/* is matched by the real API above, not swallowed by the
# catch-all below. Any other /admin/* path returns the SPA shell and React
# Router takes over client-side.
FRONTEND_DIST = Path("frontend/dist")
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/admin/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="admin-assets")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/{full_path:path}", include_in_schema=False)
async def admin_spa(full_path: str = ""):
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.is_file():
        raise HTTPException(
            503,
            "Admin console isn't built yet -- run `npm install && npm run build` in frontend/, "
            "or `npm run dev` there for local development against this API.",
        )
    return FileResponse(index_file)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
