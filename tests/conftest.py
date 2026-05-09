import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "packages"))
sys.path.insert(0, str(_root))

_ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/postgres"
TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/investment_test"


@pytest.fixture(autouse=True)
def override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("CHROMA_HOST", "localhost")
    monkeypatch.setenv("CHROMA_PORT", "8001")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLM_ENABLED", "false")
    from core.config import get_settings

    get_settings.cache_clear()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    import db.models  # noqa: F401
    from db.base import Base

    try:
        # Create isolated test database
        admin = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text("DROP DATABASE IF EXISTS investment_test"))
            await conn.execute(text("CREATE DATABASE investment_test"))
        await admin.dispose()

        engine = create_async_engine(TEST_DB_URL, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
        await engine.dispose()

        # Drop test database on teardown
        admin = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text("DROP DATABASE IF EXISTS investment_test WITH (FORCE)"))
        await admin.dispose()
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
        return


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test transactional session. commit() → flush() to enable rollback."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await session.begin()
        session.commit = session.flush  # type: ignore[method-assign]
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def fake_memory_store():
    from tests.memory.fake_store import FakeMemoryStore

    store = FakeMemoryStore()
    yield store
    store.clear()


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession, fake_memory_store) -> AsyncGenerator:
    from db.session import get_db
    from httpx import ASGITransport, AsyncClient

    from apps.api.main import app
    from tests.market_data.conftest import MockProvider

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    _mock_market_provider = MockProvider()

    from tests.fundamentals.conftest import MockFundamentalsProvider

    _mock_fund_provider = MockFundamentalsProvider()

    app.dependency_overrides[get_db] = override_get_db
    with (
        patch("market_data.service._default_provider", return_value=_mock_market_provider),
        patch("fundamentals.service._default_provider", return_value=_mock_fund_provider),
        patch("memory.service._get_default_store", return_value=fake_memory_store),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    app.dependency_overrides.pop(get_db, None)
