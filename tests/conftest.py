import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.oidc.keys import get_key_manager


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest_asyncio.fixture
async def client(db_session, redis_client, tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNING_KEY_DIR", str(tmp_path / "keys"))
    get_settings.cache_clear()
    get_key_manager.cache_clear()

    from app.main import app
    from app.middleware.rate_limit import limiter

    # The limiter's storage is shared process-wide (all tests hit it as the
    # same "127.0.0.1" caller), so without a reset, unrelated tests eat into
    # each other's rate-limit budget purely based on run order/count.
    limiter.reset()

    async def override_get_db():
        yield db_session

    def override_get_redis():
        return redis_client

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    get_key_manager.cache_clear()
