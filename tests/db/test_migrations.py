"""Tests that the Alembic migration applies cleanly."""
import asyncio
import concurrent.futures

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/postgres"
_TEMP_DB = "investment_alembic_test"
_TEMP_URL = f"postgresql+asyncpg://postgres:postgres@localhost:5433/{_TEMP_DB}"


@pytest.mark.asyncio
async def test_all_tables_exist(db_engine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        tables = {row[0] for row in result}

    expected = {
        "strategy_versions", "prompt_versions", "watchlist_symbols",
        "investor_profiles", "research_runs", "research_run_tickers",
        "neutral_recommendations", "personalized_recommendations",
        "recommendation_evidence", "job_events", "audit_logs",
    }
    assert not (expected - tables), f"Missing: {expected - tables}"


def _run_alembic_in_thread() -> None:
    """Sequential asyncio.run() calls — never nested, safe from a thread."""
    async def _create_db() -> None:
        engine = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {_TEMP_DB}"))
            await conn.execute(text(f"CREATE DATABASE {_TEMP_DB}"))
        await engine.dispose()

    async def _drop_db() -> None:
        engine = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {_TEMP_DB} WITH (FORCE)"))
        await engine.dispose()

    # Step 1: create DB (sync asyncio.run, no nesting)
    asyncio.run(_create_db())

    # Step 2: run alembic (internally calls asyncio.run — safe because step 1 is done)
    from alembic.config import Config

    from alembic import command
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _TEMP_URL)
    command.upgrade(cfg, "head")

    # Step 3: drop DB (sync asyncio.run, no nesting)
    asyncio.run(_drop_db())


def test_alembic_migration_applies() -> None:
    """Alembic upgrade head on a fresh DB. Proves migration script is correct."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_run_alembic_in_thread).result(timeout=60)
    except Exception as exc:
        if any(k in str(exc).lower() for k in ("connect", "refused", "nodename", "timeout")):
            pytest.skip(f"DB not available: {exc}")
        raise
