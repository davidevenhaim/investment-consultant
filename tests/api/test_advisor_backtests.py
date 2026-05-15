"""API tests for /api/v1/backtesting/advisor-runs (M11.1)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

TYPE_CHECKING = False
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_market_bars(
    db_session: AsyncSession,
    symbol: str,
    start: dt.date,
    n: int = 60,
    start_price: float = 100.0,
    dr: float = 0.003,
) -> None:
    from db.models import MarketPrice

    price = start_price
    d = start
    rows = []
    for _ in range(n):
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        rows.append(MarketPrice(
            symbol=symbol.upper(), price_date=d,
            open=round(price, 4), high=round(price * 1.005, 4),
            low=round(price * 0.995, 4), close=round(price, 4),
            adjusted_close=round(price, 4), volume=1_000_000, provider="yfinance",
        ))
        price *= 1 + dr
        d += dt.timedelta(days=1)
    db_session.add_all(rows)
    await db_session.flush()


async def _seed_run_with_rec(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    symbol: str,
    action: str,
    rec_date: dt.date,
) -> None:
    from db.enums import ResearchRunStatus, ResearchRunType
    from db.models import NeutralRecommendation, ResearchRun

    run = ResearchRun(
        user_id=user_id,
        run_type=ResearchRunType.MANUAL.value,
        status=ResearchRunStatus.COMPLETED.value,
        started_at=dt.datetime.combine(rec_date, dt.time(9), tzinfo=dt.UTC),
        finished_at=dt.datetime.combine(rec_date, dt.time(10), tzinfo=dt.UTC),
    )
    db_session.add(run)
    await db_session.flush()

    rec_dt = dt.datetime.combine(rec_date, dt.time(10), tzinfo=dt.UTC)
    nr = NeutralRecommendation(
        research_run_id=run.id, symbol=symbol, action=action,
        score=70, confidence=0.75, final_reason="Test",
        score_breakdown_json={}, main_reasons_json=[], main_risks_json=[],
        missing_details_json=[], what_changed_json=[],
        as_of_time=rec_dt, price_at_recommendation=100.0,
    )
    nr.created_at = rec_dt  # type: ignore[assignment]
    db_session.add(nr)
    await db_session.flush()


# ── POST /advisor-runs ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_advisor_run_returns_201(api_client, db_session: AsyncSession) -> None:
    """POST advisor-runs returns 201 with run detail."""
    start = dt.date(2024, 3, 1)
    dt.date(2024, 4, 30)
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_run_with_rec(db_session, uuid.UUID("00000000-0000-0000-0000-000000000001"), "AAPL", "BUY_CANDIDATE", start)

    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 10000, "name": "test run"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "COMPLETED"
    assert "summary_json" in data
    assert "human_summary" in data["summary_json"]


@pytest.mark.asyncio
async def test_create_advisor_run_no_recs_still_completes(api_client, db_session: AsyncSession) -> None:
    """With no recs in range, run completes with no trades."""
    await _seed_market_bars(db_session, "AAPL", dt.date(2024, 1, 1), n=40)
    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-06-01", "end_date": "2024-07-31", "initial_cash": 5000},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] in ("COMPLETED", "INSUFFICIENT_DATA")
    assert data["summary_json"]["total_trades"] == 0


@pytest.mark.asyncio
async def test_response_includes_profit_loss_and_human_summary(api_client, db_session: AsyncSession) -> None:
    """summary_json contains profit_loss_amount and human_summary."""
    start = dt.date(2024, 3, 1)
    dt.date(2024, 4, 30)
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_run_with_rec(db_session, uuid.UUID("00000000-0000-0000-0000-000000000001"), "AAPL", "BUY_CANDIDATE", start)

    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 10000},
    )
    assert resp.status_code == 201
    s = resp.json()["data"]["summary_json"]
    assert "profit_loss_amount" in s
    assert "human_summary" in s
    assert "$10,000.00" in s["human_summary"]


@pytest.mark.asyncio
async def test_invalid_cash_rejected(api_client) -> None:
    """Negative or zero initial_cash must return 422."""
    for bad_cash in [-100, 0]:
        resp = await api_client.post(
            "/api/v1/backtesting/advisor-runs",
            json={"start_date": "2024-01-01", "end_date": "2024-03-01", "initial_cash": bad_cash},
        )
        assert resp.status_code == 422, f"Expected 422 for cash={bad_cash}"


@pytest.mark.asyncio
async def test_end_before_start_rejected(api_client) -> None:
    """end_date before start_date must return 422."""
    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-06-01", "end_date": "2024-01-01", "initial_cash": 1000},
    )
    assert resp.status_code == 422


# ── GET /advisor-runs ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_only_current_user_runs(api_client, db_session: AsyncSession) -> None:
    """User A's runs are not visible to User B."""
    headers_a = {"X-User-Id": str(uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"))}
    headers_b = {"X-User-Id": str(uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"))}

    start = dt.date(2024, 3, 1)
    dt.date(2024, 4, 30)
    user_a_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_run_with_rec(db_session, user_a_id, "AAPL", "BUY_CANDIDATE", start)

    await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 5000},
        headers=headers_a,
    )

    resp_b = await api_client.get("/api/v1/backtesting/advisor-runs", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["data"] == []


@pytest.mark.asyncio
async def test_list_empty_by_default(api_client) -> None:
    resp = await api_client.get("/api/v1/backtesting/advisor-runs")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


# ── GET /advisor-runs/{id} ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_detail_returns_trades_and_equity(api_client, db_session: AsyncSession) -> None:
    """Detail endpoint returns trades and equity_points lists."""
    start = dt.date(2024, 3, 1)
    dt.date(2024, 4, 30)
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_run_with_rec(
        db_session, uuid.UUID("00000000-0000-0000-0000-000000000001"), "AAPL", "BUY_CANDIDATE", start
    )

    create_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 10000},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["data"]["id"]

    detail = await api_client.get(f"/api/v1/backtesting/advisor-runs/{run_id}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert "trades" in data
    assert "equity_points" in data
    assert isinstance(data["trades"], list)
    assert isinstance(data["equity_points"], list)


@pytest.mark.asyncio
async def test_get_detail_another_user_returns_404(api_client, db_session: AsyncSession) -> None:
    """Detail endpoint returns 404 for a run owned by another user."""
    headers_a = {"X-User-Id": str(uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003"))}
    headers_b = {"X-User-Id": str(uuid.UUID("bbbbbbbb-0000-0000-0000-000000000004"))}

    start = dt.date(2024, 3, 1)
    dt.date(2024, 4, 30)
    user_a_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_run_with_rec(db_session, user_a_id, "AAPL", "BUY_CANDIDATE", start)

    create_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 5000},
        headers=headers_a,
    )
    run_id = create_resp.json()["data"]["id"]

    resp_b = await api_client.get(f"/api/v1/backtesting/advisor-runs/{run_id}", headers=headers_b)
    assert resp_b.status_code == 404


@pytest.mark.asyncio
async def test_get_nonexistent_run_returns_404(api_client) -> None:
    fake_id = str(uuid.uuid4())
    resp = await api_client.get(f"/api/v1/backtesting/advisor-runs/{fake_id}")
    assert resp.status_code == 404


# ── M11.5 enriched summary API tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_advisor_run_response_includes_enriched_summary(
    api_client, db_session: AsyncSession
) -> None:
    """POST /advisor-runs response summary_json contains all new enriched fields."""
    start = dt.date(2024, 3, 1)
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.003)
    await _seed_run_with_rec(
        db_session, uuid.UUID("00000000-0000-0000-0000-000000000001"), "AAPL", "BUY_CANDIDATE", start
    )

    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 10000},
    )
    assert resp.status_code == 201
    s = resp.json()["data"]["summary_json"]

    # display strings
    for key in (
        "profit_loss_display", "total_return_display",
        "benchmark_return_display", "relative_return_display",
        "max_drawdown_display", "final_cash_display", "final_positions_value_display",
    ):
        assert key in s, f"Missing display key: {key}"

    # portfolio state fields
    assert "final_cash" in s
    assert "final_positions_value" in s
    assert s["final_cash"] + s["final_positions_value"] == pytest.approx(
        s["final_equity"], rel=1e-4
    )

    # structural fields
    assert isinstance(s["open_positions"], list)
    assert isinstance(s["closed_positions"], list)
    assert isinstance(s["trade_breakdown"], dict)
    assert isinstance(s["skip_breakdown"], dict)
    assert isinstance(s["benchmark_summary"], dict)

    # relative_return uses "percentage points"
    assert "percentage points" in s["relative_return_display"] or s["relative_return_display"] == "N/A"

    # legacy fields preserved
    for legacy in ("initial_cash", "final_equity", "total_return_pct", "human_summary"):
        assert legacy in s, f"Legacy field missing: {legacy}"


@pytest.mark.asyncio
async def test_get_advisor_run_enriched_summary_persisted(
    api_client, db_session: AsyncSession
) -> None:
    """GET /advisor-runs/{id} returns the same enriched summary_json that was stored at creation."""
    start = dt.date(2024, 3, 1)
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.003)
    await _seed_run_with_rec(
        db_session, uuid.UUID("00000000-0000-0000-0000-000000000001"), "AAPL", "BUY_CANDIDATE", start
    )

    create_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 10000},
    )
    run_id = create_resp.json()["data"]["id"]

    get_resp = await api_client.get(f"/api/v1/backtesting/advisor-runs/{run_id}")
    assert get_resp.status_code == 200
    s = get_resp.json()["data"]["summary_json"]

    for key in (
        "profit_loss_display", "total_return_display", "trade_breakdown",
        "skip_breakdown", "open_positions", "closed_positions", "benchmark_summary",
    ):
        assert key in s, f"GET response missing enriched key: {key}"


@pytest.mark.asyncio
async def test_enriched_summary_backwards_compatible_shape(
    api_client, db_session: AsyncSession
) -> None:
    """All original summary_json fields are still present in the enriched response."""
    start = dt.date(2024, 3, 1)
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_run_with_rec(
        db_session, uuid.UUID("00000000-0000-0000-0000-000000000001"), "AAPL", "BUY_CANDIDATE", start
    )

    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 10000},
    )
    assert resp.status_code == 201
    s = resp.json()["data"]["summary_json"]

    legacy_keys = [
        "initial_cash", "final_equity", "profit_loss_amount", "total_return_pct",
        "benchmark_return_pct", "relative_return_pct", "max_drawdown_pct",
        "total_trades", "winning_trades", "losing_trades",
        "skipped_recommendations", "traded_symbols", "human_summary",
    ]
    for key in legacy_keys:
        assert key in s, f"Backwards-compat: legacy key missing: {key}"


@pytest.mark.asyncio
async def test_enriched_summary_no_user_id_leakage(
    api_client, db_session: AsyncSession
) -> None:
    """summary_json must not contain user_id or other cross-user data."""
    start = dt.date(2024, 3, 1)
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    await _seed_run_with_rec(db_session, user_id, "AAPL", "BUY_CANDIDATE", start)

    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2024-03-01", "end_date": "2024-04-30", "initial_cash": 10000},
    )
    assert resp.status_code == 201
    s = resp.json()["data"]["summary_json"]

    # summary_json must not contain the user_id string
    assert str(user_id) not in str(s), "user_id must not appear in summary_json"
    # No raw recommendation IDs or research run IDs in summary
    assert "research_run_id" not in str(s)
