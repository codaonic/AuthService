from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.middleware.rate_limit import limiter
from app.oidc import authorize, discovery, jwks, prm, register, revoke, token, userinfo

app = FastAPI(title="Auth Service")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(discovery.router)
app.include_router(prm.router)
app.include_router(jwks.router)
app.include_router(authorize.router)
app.include_router(token.router)
app.include_router(register.router)
app.include_router(revoke.router)
app.include_router(userinfo.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
