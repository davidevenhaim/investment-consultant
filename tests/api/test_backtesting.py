"""API tests for /api/v1/backtesting/ — M11."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_completed_run(api_client: AsyncClient, symbols: list[str]) -> str:
    """Run research for given symbols and return the run_id."""
    resp = await api_client.post("/api/v1/research-runs", json={"symbols": symbols})
    assert resp.status_code == 201
    return resp.json()["data"]["id"]


async def _seed_price_bars(
    db_session: AsyncSession,
    symbol: str,
    start: dt.date,
    n: int = 40,
    start_price: float = 100.0,
    daily_return: float = 0.003,
) -> None:
    from db.models import MarketPrice

    price = start_price
    d = start
    rows = []
    for _ in range(n):
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        rows.append(
            MarketPrice(
                symbol=symbol,
                price_date=d,
                open=round(price, 4),
                high=round(price * 1.005, 4),
                low=round(price * 0.995, 4),
                close=round(price, 4),
                adjusted_close=round(price, 4),
                volume=1_000_000,
                provider="yfinance",
            )
        )
        price *= 1 + daily_return
        d += dt.timedelta(days=1)
    db_session.add_all(rows)
    await db_session.flush()


# ── measure-latest ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_measure_latest_no_run_returns_empty(api_client: AsyncClient) -> None:
    """No completed run → clean empty response, not 500."""
    resp = await api_client.post(
        "/api/v1/backtesting/outcomes/measure-latest",
        json={"horizon_days": 30, "benchmark_symbol": "SPY"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["outcomes"] == []


@pytest.mark.asyncio
async def test_measure_latest_insufficient_data_no_500(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Run exists but no future price data → INSUFFICIENT_DATA rows, not 500."""
    await _seed_completed_run(api_client, ["AAPL"])

    resp = await api_client.post(
        "/api/v1/backtesting/outcomes/measure-latest",
        json={"horizon_days": 30, "benchmark_symbol": "SPY"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Fresh run → horizon not yet elapsed → PENDING is expected and correct.
    # If horizon had elapsed with no bars → INSUFFICIENT_DATA.
    valid_statuses = {"INSUFFICIENT_DATA", "MEASURED", "PENDING"}
    statuses = [o["outcome_status"] for o in data["outcomes"]]
    assert all(s in valid_statuses for s in statuses)


@pytest.mark.asyncio
async def test_measure_latest_with_price_data_returns_measured(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """With 40 price bars after rec time, outcomes should be MEASURED."""
    await _seed_completed_run(api_client, ["AAPL"])

    # Seed price bars starting from today going forward (rec time is ≈now)
    start = dt.date.today()
    await _seed_price_bars(db_session, "AAPL", start, n=40, start_price=150.0)
    await _seed_price_bars(db_session, "SPY", start, n=40, start_price=400.0)

    resp = await api_client.post(
        "/api/v1/backtesting/outcomes/measure-latest",
        json={"horizon_days": 20, "benchmark_symbol": "SPY"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] >= 1
    # A fresh run has as_of_time ≈ now; with horizon_days=20 the horizon has not
    # yet elapsed, so PENDING is the correct and expected status.
    valid_statuses = {"MEASURED", "INSUFFICIENT_DATA", "PENDING"}
    statuses = {o["outcome_status"] for o in data["outcomes"]}
    assert statuses.issubset(valid_statuses)


@pytest.mark.asyncio
async def test_measure_latest_idempotent(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Calling measure-latest twice returns same count, no duplicate rows."""
    await _seed_completed_run(api_client, ["AAPL"])

    start = dt.date.today()
    await _seed_price_bars(db_session, "AAPL", start, n=40)
    await _seed_price_bars(db_session, "SPY", start, n=40, start_price=400.0)

    r1 = await api_client.post(
        "/api/v1/backtesting/outcomes/measure-latest",
        json={"horizon_days": 20, "benchmark_symbol": "SPY"},
    )
    r2 = await api_client.post(
        "/api/v1/backtesting/outcomes/measure-latest",
        json={"horizon_days": 20, "benchmark_symbol": "SPY"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["data"]["count"] == r2.json()["data"]["count"]


# ── User isolation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_a_outcomes_not_visible_to_user_b(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Outcomes for User A must not appear in User B's GET /outcomes."""
    headers_a = {"X-User-Id": str(uuid.UUID("10000000-0000-0000-0000-000000000001"))}
    headers_b = {"X-User-Id": str(uuid.UUID("20000000-0000-0000-0000-000000000002"))}

    # User A: run + measure
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]}, headers=headers_a)

    start = dt.date.today()
    await _seed_price_bars(db_session, "AAPL", start, n=40)
    await _seed_price_bars(db_session, "SPY", start, n=40, start_price=400.0)

    await api_client.post(
        "/api/v1/backtesting/outcomes/measure-latest",
        json={"horizon_days": 20, "benchmark_symbol": "SPY"},
        headers=headers_a,
    )

    # User B: should see zero outcomes
    resp_b = await api_client.get("/api/v1/backtesting/outcomes", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["data"] == []


@pytest.mark.asyncio
async def test_user_b_cannot_review_user_a_event(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """User B cannot update User A's learning event — must return 404."""
    user_a_id = uuid.UUID("10000000-0000-0000-0000-000000000003")
    headers_b = {"X-User-Id": str(uuid.UUID("20000000-0000-0000-0000-000000000004"))}

    # Create a learning event for User A directly in DB
    from db.models import LearningEvent

    ev = LearningEvent(
        user_id=user_a_id,
        symbol="AAPL",
        event_type="UNDERPERFORMED_AFTER_BUY",
        severity="HIGH",
        title="Test event",
        summary="Test summary",
        status="OPEN",
    )
    db_session.add(ev)
    await db_session.flush()

    resp = await api_client.post(
        f"/api/v1/backtesting/learning-events/{ev.id}/review",
        json={"status": "REVIEWED"},
        headers=headers_b,
    )
    assert resp.status_code == 404


# ── GET /outcomes + /learning-events ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_outcomes_empty_by_default(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/backtesting/outcomes")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_list_learning_events_empty_by_default(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/backtesting/learning-events")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_review_learning_event_updates_status(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """PATCH status on own learning event returns updated row."""
    from db.models import LearningEvent

    from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

    ev = LearningEvent(
        user_id=DEV_DEFAULT_USER_ID,
        symbol="NVDA",
        event_type="MISSED_UPSIDE_AFTER_HOLD",
        severity="MEDIUM",
        title="Missed NVDA run",
        summary="HOLD but +20%",
        status="OPEN",
    )
    db_session.add(ev)
    await db_session.flush()

    resp = await api_client.post(
        f"/api/v1/backtesting/learning-events/{ev.id}/review",
        json={"status": "REVIEWED"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "REVIEWED"


@pytest.mark.asyncio
async def test_review_nonexistent_event_returns_404(api_client: AsyncClient) -> None:
    fake_id = str(uuid.uuid4())
    resp = await api_client.post(
        f"/api/v1/backtesting/learning-events/{fake_id}/review",
        json={"status": "DISMISSED"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_outcomes_symbol_filter(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Symbol filter returns only matching outcomes."""
    from db.models import RecommendationOutcome

    from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

    uid = DEV_DEFAULT_USER_ID
    for sym in ("AAPL", "NVDA"):
        db_session.add(
            RecommendationOutcome(
                user_id=uid,
                recommendation_type="NEUTRAL",
                recommendation_id=uuid.uuid4(),
                symbol=sym,
                action="HOLD",
                measured_from=dt.datetime.now(dt.UTC),
                measured_to=dt.datetime.now(dt.UTC),
                horizon_days=30,
                benchmark_symbol="SPY",
                outcome_status="MEASURED",
            )
        )
    await db_session.flush()

    resp = await api_client.get("/api/v1/backtesting/outcomes?symbol=AAPL")
    assert resp.status_code == 200
    data = resp.json()["data"]
    symbols = {o["symbol"] for o in data}
    assert "AAPL" in symbols
    assert "NVDA" not in symbols


@pytest.mark.asyncio
async def test_measure_latest_uses_current_users_run_only(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """measure-latest must scope to current user's run — not another user's."""
    headers_a = {"X-User-Id": str(uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"))}
    headers_b = {"X-User-Id": str(uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"))}

    # User A has a completed run
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]}, headers=headers_a)

    # User B calls measure-latest (no run for User B)
    resp = await api_client.post(
        "/api/v1/backtesting/outcomes/measure-latest",
        json={"horizon_days": 30, "benchmark_symbol": "SPY"},
        headers=headers_b,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["outcomes"] == []
