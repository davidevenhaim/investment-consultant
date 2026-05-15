"""Tests for local_llm.service — advisor backtest analysis generation.

DB-bound tests use the shared db_session fixture.
Ollama is always mocked — no real network calls.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from local_llm.schemas import OllamaConnectionError, OllamaParseError
from local_llm.service import (
    _SYSTEM_PROMPT,
    OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION,
    _sample_equity_points,
    build_prompt_input,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_run(
    *,
    user_id: uuid.UUID | None = None,
    initial_cash: float = 10_000.0,
    final_equity: float = 11_000.0,
    total_trades: int = 3,
    winning_trades: int = 2,
    losing_trades: int = 1,
    n_equity_points: int = 10,
    n_trades: int = 2,
) -> Any:
    """Build a minimal fake AdvisorBacktestRun-like object (no DB needed)."""
    import datetime as dt

    class _FakeEquityPoint:
        def __init__(self, i: int) -> None:
            self.date = dt.date(2026, 1, 1) + dt.timedelta(days=i)
            self.equity = initial_cash + i * 100
            self.cash = initial_cash + i * 100
            self.positions_value = 0.0
            self.drawdown_pct = -0.01 * i if i > 0 else 0.0
            self.benchmark_value = None

    class _FakeTrade:
        def __init__(self, i: int) -> None:
            self.trade_date = dt.datetime(2026, 1, 2 + i, 10, 0, 0)
            self.symbol = "AAPL"
            self.action = "BUY_CANDIDATE"
            self.trade_type = "BUY"
            self.price = 150.0 + i
            self.quantity = 10.0
            self.cash_delta = -(150.0 + i) * 10
            self.reason = "test buy"

    class _FakeRun:
        start_date = dt.date(2026, 1, 1)
        end_date = dt.date(2026, 3, 1)
        benchmark_symbol = "SPY"
        assumptions_json: dict[str, Any] = {"seeded": True}
        status = "COMPLETED"

        def __init__(self) -> None:
            self.id = uuid.uuid4()
            self.user_id = user_id
            self.initial_cash = initial_cash
            self.final_equity = final_equity
            self.total_return_pct = (final_equity - initial_cash) / initial_cash
            self.benchmark_return_pct = 0.05
            self.relative_return_pct = self.total_return_pct - 0.05
            self.max_drawdown_pct = -0.05
            self.total_trades = total_trades
            self.winning_trades = winning_trades
            self.losing_trades = losing_trades
            self.equity_points = [_FakeEquityPoint(i) for i in range(n_equity_points)]
            self.trades = [_FakeTrade(i) for i in range(n_trades)]

    return _FakeRun()


def _valid_analysis_dict() -> dict[str, Any]:
    return {
        "headline": "Outperformed benchmark by 169%",
        "plain_english_summary": "The advisor made money.",
        "performance_drivers": [{"title": "AAPL", "explanation": "went up", "symbols": ["AAPL"]}],
        "risk_notes": [{"title": "Small sample", "explanation": "only 3 trades", "severity": "HIGH"}],
        "trade_commentary": [{"symbol": "AAPL", "comment": "good entry"}],
        "what_the_advisor_should_learn": ["buy dips"],
        "data_quality_warnings": ["synthetic data"],
        "confidence": 0.6,
    }


# ── Unit tests: pure functions (no DB) ────────────────────────────────────────


def test_sample_equity_points_empty() -> None:
    assert _sample_equity_points([]) == []


def test_sample_equity_points_one() -> None:
    p = {"date": "2026-01-01", "equity": 100.0, "drawdown_pct": 0.0}
    assert _sample_equity_points([p]) == [p]


def test_sample_equity_points_does_not_return_full_curve() -> None:
    pts = [
        {"date": f"2026-01-{i:02d}", "equity": float(100 + i), "drawdown_pct": -float(i) / 100}
        for i in range(1, 31)
    ]
    result = _sample_equity_points(pts, max_extra=5)
    # Should be much smaller than 30
    assert len(result) < 15


def test_sample_equity_points_includes_first_and_last() -> None:
    pts = [
        {"date": f"2026-01-{i:02d}", "equity": float(100 + i), "drawdown_pct": -float(i) / 100}
        for i in range(1, 20)
    ]
    result = _sample_equity_points(pts)
    dates = [p["date"] for p in result]
    assert "2026-01-01" in dates
    assert "2026-01-19" in dates


def test_sample_equity_points_includes_worst_drawdown() -> None:
    pts = [
        {"date": "2026-01-01", "equity": 100.0, "drawdown_pct": 0.0},
        {"date": "2026-01-10", "equity": 80.0, "drawdown_pct": -0.20},   # worst
        {"date": "2026-01-20", "equity": 90.0, "drawdown_pct": -0.10},
        {"date": "2026-01-30", "equity": 95.0, "drawdown_pct": -0.05},
    ]
    result = _sample_equity_points(pts)
    assert any(p["drawdown_pct"] == -0.20 for p in result)


def test_build_prompt_input_includes_summary_fields() -> None:
    run = _make_run()
    inp = build_prompt_input(run)
    assert inp["initial_cash"] == 10_000.0
    assert inp["final_equity"] == 11_000.0
    assert inp["total_trades"] == 3
    assert inp["winning_trades"] == 2
    assert inp["benchmark_symbol"] == "SPY"
    assert "assumptions_json" in inp
    assert "display_metrics" in inp
    assert "deterministic_headline" in inp


def test_build_prompt_input_display_metrics_formatted() -> None:
    run = _make_run()
    run.total_return_pct = 0.2543
    run.benchmark_return_pct = 0.0851
    run.relative_return_pct = 0.1692
    run.max_drawdown_pct = -0.0319
    run.initial_cash = 10_000.0
    run.final_equity = 12_543.53
    dm = build_prompt_input(run)["display_metrics"]
    assert dm["initial_cash_display"] == "$10,000.00"
    assert dm["final_equity_display"] == "$12,543.53"
    assert dm["profit_loss_display"] == "+$2,543.53"
    assert dm["advisor_return_display"] == "+25.43%"
    assert dm["benchmark_return_display"] == "+8.51%"
    assert dm["relative_return_display"] == "+16.92 percentage points"
    assert dm["max_drawdown_display"] == "-3.19%"
    assert dm["total_trades_display"] == "3"


def test_build_prompt_input_display_metrics_na_without_benchmark() -> None:
    run = _make_run()
    run.benchmark_return_pct = None
    run.relative_return_pct = None
    dm = build_prompt_input(run)["display_metrics"]
    assert dm["benchmark_return_display"] == "N/A"
    assert dm["relative_return_display"] == "N/A"


def test_build_prompt_input_deterministic_headline_matches_expected() -> None:
    run = _make_run()
    run.total_return_pct = 0.2543
    run.benchmark_return_pct = 0.0851
    run.relative_return_pct = 0.1692
    inp = build_prompt_input(run)
    assert (
        inp["deterministic_headline"]
        == "Advisor return +25.43% vs SPY +8.51% (+16.92 percentage points)."
    )


def test_system_prompt_includes_numeric_guardrails() -> None:
    assert "display_metrics" in _SYSTEM_PROMPT
    assert "percentage points" in _SYSTEM_PROMPT
    assert "Do NOT recompute" in _SYSTEM_PROMPT
    assert "deterministic_headline" in _SYSTEM_PROMPT


def test_build_prompt_input_includes_trades() -> None:
    run = _make_run(n_trades=3)
    inp = build_prompt_input(run)
    assert len(inp["trades"]) == 3
    t = inp["trades"][0]
    assert "symbol" in t
    assert "trade_type" in t
    assert "price" in t


def test_build_prompt_input_skips_skip_trades() -> None:
    """SKIP trades must not appear in the prompt."""
    import datetime as dt

    run = _make_run(n_trades=0)

    class _SkipTrade:
        trade_date = dt.datetime(2026, 1, 5)
        symbol = "AAPL"
        action = "HOLD"
        trade_type = "SKIP"
        price = None
        quantity = None
        cash_delta = None
        reason = "no action"

    run.trades = [_SkipTrade()]
    inp = build_prompt_input(run)
    assert inp["trades"] == []
    assert inp["skipped_recommendations"] == 1


def test_build_prompt_input_equity_summary_not_full_curve() -> None:
    """equity_summary must be a sample, not all 30 points."""
    run = _make_run(n_equity_points=30)
    inp = build_prompt_input(run)
    assert len(inp["equity_summary"]) < 20


# ── DB-bound tests ─────────────────────────────────────────────────────────────


async def _seed_run(db_session: Any, user_id: uuid.UUID) -> Any:
    from db.models import AdvisorBacktestRun

    run = AdvisorBacktestRun(
        user_id=user_id,
        name="test run",
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 3, 1),
        initial_cash=10_000.0,
        final_equity=11_000.0,
        cash_final=11_000.0,
        total_return_pct=0.10,
        benchmark_symbol="SPY",
        benchmark_return_pct=0.05,
        relative_return_pct=0.05,
        max_drawdown_pct=-0.05,
        total_trades=2,
        winning_trades=2,
        losing_trades=0,
        status="COMPLETED",
        assumptions_json={"seeded": True},
        summary_json={},
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_service_not_found_raises_value_error(db_session: Any) -> None:
    from local_llm.service import generate_advisor_backtest_analysis

    user_id = uuid.uuid4()
    with pytest.raises(ValueError, match="not found"):
        await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_service_wrong_user_raises_value_error(db_session: Any) -> None:
    from local_llm.service import generate_advisor_backtest_analysis

    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    run = await _seed_run(db_session, owner_id)

    with pytest.raises(ValueError, match="not found"):
        await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=other_id,
            advisor_backtest_run_id=run.id,
        )


@pytest.mark.asyncio
async def test_service_returns_existing_when_force_false(db_session: Any, monkeypatch: Any) -> None:
    from db.models import AdvisorBacktestAnalysis
    from local_llm.service import generate_advisor_backtest_analysis

    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    run = await _seed_run(db_session, user_id)

    # Pre-seed a COMPLETED analysis
    existing = AdvisorBacktestAnalysis(
        user_id=user_id,
        advisor_backtest_run_id=run.id,
        provider="ollama",
        model="llama3.1:8b",
        prompt_version=OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION,
        status="COMPLETED",
        analysis_json={"headline": "existing"},
        prompt_input_json={},
    )
    db_session.add(existing)
    await db_session.flush()

    with patch("local_llm.service.OllamaClient") as mock_cls:
        result = await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=run.id,
            force=False,
        )

    mock_cls.assert_not_called()
    assert result.analysis_json == {"headline": "existing"}
    assert result.prompt_version == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION


@pytest.mark.asyncio
async def test_service_v1_completed_not_reused_when_prompt_is_v2(
    db_session: Any, monkeypatch: Any
) -> None:
    """Stale v1 cache must not satisfy force=false after upgrading to v2."""
    from db.models import AdvisorBacktestAnalysis
    from local_llm.service import generate_advisor_backtest_analysis

    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    run = await _seed_run(db_session, user_id)
    existing = AdvisorBacktestAnalysis(
        user_id=user_id,
        advisor_backtest_run_id=run.id,
        provider="ollama",
        model="llama3.1:8b",
        prompt_version="ollama_backtest_analyst_v1",
        status="COMPLETED",
        analysis_json={"headline": "old v1"},
        prompt_input_json={},
    )
    db_session.add(existing)
    await db_session.flush()

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_dict())

    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        result = await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=run.id,
            force=False,
        )

    mock_client.chat_json.assert_called_once()
    assert result.prompt_version == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION
    assert (
        result.analysis_json["headline"]
        == "Advisor return +10.00% vs SPY +5.00% (+5.00 percentage points)."
    )
    assert result.analysis_json.get("model_headline") == "Outperformed benchmark by 169%"


@pytest.mark.asyncio
async def test_service_regenerates_when_force_true(db_session: Any, monkeypatch: Any) -> None:
    from local_llm.service import generate_advisor_backtest_analysis

    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    run = await _seed_run(db_session, user_id)

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_dict())

    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        result = await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=run.id,
            force=True,
        )

    assert result.status == "COMPLETED"
    assert (
        result.analysis_json["headline"]
        == "Advisor return +10.00% vs SPY +5.00% (+5.00 percentage points)."
    )
    assert result.analysis_json.get("model_headline") == "Outperformed benchmark by 169%"
    assert result.prompt_version == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION
    mock_client.chat_json.assert_called_once()


@pytest.mark.asyncio
async def test_service_disabled_raises_without_persisting(
    db_session: Any, monkeypatch: Any
) -> None:
    from db.models import AdvisorBacktestAnalysis
    from local_llm.schemas import OllamaDisabledError
    from local_llm.service import generate_advisor_backtest_analysis
    from sqlalchemy import select

    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from core.config import get_settings
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    run = await _seed_run(db_session, user_id)

    with pytest.raises(OllamaDisabledError):
        await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=run.id,
        )

    # No row should be persisted
    rows = (
        await db_session.execute(
            select(AdvisorBacktestAnalysis).where(
                AdvisorBacktestAnalysis.advisor_backtest_run_id == run.id
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_service_connection_error_persists_failed_row(
    db_session: Any, monkeypatch: Any
) -> None:
    from db.models import AdvisorBacktestAnalysis
    from local_llm.service import generate_advisor_backtest_analysis
    from sqlalchemy import select

    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    run = await _seed_run(db_session, user_id)

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(side_effect=OllamaConnectionError("refused"))

    with patch("local_llm.service.OllamaClient", return_value=mock_client), pytest.raises(OllamaConnectionError):
        await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=run.id,
        )

    rows = (
        await db_session.execute(
            select(AdvisorBacktestAnalysis).where(
                AdvisorBacktestAnalysis.advisor_backtest_run_id == run.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "FAILED"
    assert "refused" in (rows[0].error_message or "")
    assert rows[0].prompt_version == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION


@pytest.mark.asyncio
async def test_service_parse_error_persists_failed_row(
    db_session: Any, monkeypatch: Any
) -> None:
    from db.models import AdvisorBacktestAnalysis
    from local_llm.service import generate_advisor_backtest_analysis
    from sqlalchemy import select

    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    run = await _seed_run(db_session, user_id)

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(side_effect=OllamaParseError("invalid JSON"))

    with patch("local_llm.service.OllamaClient", return_value=mock_client), pytest.raises(OllamaParseError):
        await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=run.id,
        )

    rows = (
        await db_session.execute(
            select(AdvisorBacktestAnalysis).where(
                AdvisorBacktestAnalysis.advisor_backtest_run_id == run.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "FAILED"
    assert rows[0].prompt_version == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION


@pytest.mark.asyncio
async def test_service_successful_call_stores_completed_row(
    db_session: Any, monkeypatch: Any
) -> None:
    from db.models import AdvisorBacktestAnalysis
    from local_llm.service import generate_advisor_backtest_analysis
    from sqlalchemy import select

    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    run = await _seed_run(db_session, user_id)

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_dict())

    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        result = await generate_advisor_backtest_analysis(
            session=db_session,
            user_id=user_id,
            advisor_backtest_run_id=run.id,
        )

    assert result.status == "COMPLETED"
    assert result.analysis_json["confidence"] == 0.6
    assert (
        result.analysis_json["headline"]
        == "Advisor return +10.00% vs SPY +5.00% (+5.00 percentage points)."
    )
    assert result.prompt_version == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION
    assert result.analysis_json.get("model_headline") == "Outperformed benchmark by 169%"
    assert "display_metrics" in result.prompt_input_json

    rows = (
        await db_session.execute(
            select(AdvisorBacktestAnalysis).where(
                AdvisorBacktestAnalysis.advisor_backtest_run_id == run.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "COMPLETED"
