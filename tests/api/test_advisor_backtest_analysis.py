"""API tests for /api/v1/backtesting/advisor-runs/{id}/analysis — M11.3.

All tests use mocked Ollama — no real network calls.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from db.models import AdvisorBacktestAnalysis, AdvisorBacktestRun
from local_llm.service import OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION, build_prompt_input
from sqlalchemy import select
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Helpers ───────────────────────────────────────────────────────────────────


def _valid_analysis_payload() -> dict[str, Any]:
    return {
        "headline": "Outperformed S&P 500 by 69%",
        "plain_english_summary": "The advisor made money with 169% relative outperformance.",
        "performance_drivers": [],
        "risk_notes": [],
        "trade_commentary": [],
        "what_the_advisor_should_learn": ["buy dips"],
        "data_quality_warnings": ["synthetic data"],
        "confidence": 0.6,
    }


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_analysis_ollama_disabled_returns_503(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OLLAMA_ENABLED=false → 503 with clear message."""
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from core.config import get_settings
    get_settings.cache_clear()
    # Create a run via API so it belongs to the current test user
    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
            "initial_cash": 10000,
            "benchmark_symbol": "SPY",
        },
    )
    assert backtest_resp.status_code == 201
    run_id = backtest_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
        json={"force": False},
    )
    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_analysis_invalid_uuid_returns_422(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs/not-a-uuid/analysis",
        json={"force": False},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_analysis_no_analysis_returns_404(
    api_client: AsyncClient,
) -> None:
    """No analysis exists → 404."""
    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
            "initial_cash": 10000,
            "benchmark_symbol": "SPY",
        },
    )
    assert backtest_resp.status_code == 201
    run_id = backtest_resp.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/backtesting/advisor-runs/{run_id}/analysis")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_analysis_returns_existing(
    api_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET returns pre-existing completed analysis."""
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    # Create run via API so user ownership is correct
    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
            "initial_cash": 10000,
            "benchmark_symbol": "SPY",
        },
    )
    run_id = backtest_resp.json()["data"]["id"]

    # Inject completed analysis via service mock
    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_payload())
    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        post_resp = await api_client.post(
            f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
            json={"force": False},
        )
    assert post_resp.status_code == 200

    run_row = (
        await db_session.execute(
            select(AdvisorBacktestRun)
            .options(
                selectinload(AdvisorBacktestRun.trades),
                selectinload(AdvisorBacktestRun.equity_points),
            )
            .where(AdvisorBacktestRun.id == UUID(run_id))
        )
    ).scalar_one()
    expected_headline = build_prompt_input(run_row)["deterministic_headline"]

    get_resp = await api_client.get(
        f"/api/v1/backtesting/advisor-runs/{run_id}/analysis"
    )
    assert get_resp.status_code == 200
    data = get_resp.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["prompt_version"] == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION
    assert data["analysis_json"]["headline"] == expected_headline
    assert data["analysis_json"].get("model_headline") == _valid_analysis_payload()["headline"]


@pytest.mark.asyncio
async def test_post_analysis_with_mocked_ollama_stores_completed(
    api_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST with mocked Ollama → COMPLETED row, correct response shape."""
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
            "initial_cash": 10000,
            "benchmark_symbol": "SPY",
        },
    )
    run_id = backtest_resp.json()["data"]["id"]

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_payload())
    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        resp = await api_client.post(
            f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
            json={"force": False},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["prompt_version"] == OLLAMA_BACKTEST_ANALYST_PROMPT_VERSION
    run_row = (
        await db_session.execute(
            select(AdvisorBacktestRun)
            .options(
                selectinload(AdvisorBacktestRun.trades),
                selectinload(AdvisorBacktestRun.equity_points),
            )
            .where(AdvisorBacktestRun.id == UUID(run_id))
        )
    ).scalar_one()
    assert data["analysis_json"]["headline"] == build_prompt_input(run_row)["deterministic_headline"]
    assert data["analysis_json"].get("model_headline") == _valid_analysis_payload()["headline"]
    assert data["analysis_json"]["confidence"] == 0.6
    assert "provider" in data
    assert "model" in data
    assert "prompt_version" in data
    # user_id must NOT be in response
    assert "user_id" not in data


@pytest.mark.asyncio
async def test_response_schema_does_not_expose_user_id(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2026-01-01", "end_date": "2026-03-01", "initial_cash": 5000},
    )
    run_id = backtest_resp.json()["data"]["id"]

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_payload())
    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        resp = await api_client.post(
            f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
            json={"force": False},
        )

    assert resp.status_code == 200
    assert "user_id" not in resp.json()["data"]


@pytest.mark.asyncio
async def test_post_analysis_force_true_regenerates(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """force=True always calls Ollama even when a completed analysis exists."""
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2026-01-01", "end_date": "2026-03-01", "initial_cash": 5000},
    )
    run_id = backtest_resp.json()["data"]["id"]

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_payload())
    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        # First call
        await api_client.post(
            f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
            json={"force": False},
        )
        # Second call with force=True — must call Ollama again
        await api_client.post(
            f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
            json={"force": True},
        )

    assert mock_client.chat_json.call_count == 2


@pytest.mark.asyncio
async def test_get_analysis_404_when_only_stale_v1_exists(
    api_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET must not return v1 analyses after prompt_version upgrade to v2."""
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
            "initial_cash": 10000,
            "benchmark_symbol": "SPY",
        },
    )
    assert backtest_resp.status_code == 201
    run_id = backtest_resp.json()["data"]["id"]
    run_row = (
        await db_session.execute(select(AdvisorBacktestRun).where(AdvisorBacktestRun.id == UUID(run_id)))
    ).scalar_one()

    stale = AdvisorBacktestAnalysis(
        user_id=run_row.user_id,
        advisor_backtest_run_id=run_row.id,
        provider="ollama",
        model="llama3.1:8b",
        prompt_version="ollama_backtest_analyst_v1",
        status="COMPLETED",
        analysis_json={"headline": "stale"},
        prompt_input_json={},
    )
    db_session.add(stale)
    await db_session.flush()

    get_resp = await api_client.get(f"/api/v1/backtesting/advisor-runs/{run_id}/analysis")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_post_force_false_reuses_v2_completed_without_calling_ollama(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    backtest_resp = await api_client.post(
        "/api/v1/backtesting/advisor-runs",
        json={"start_date": "2026-01-01", "end_date": "2026-03-01", "initial_cash": 10000},
    )
    assert backtest_resp.status_code == 201
    run_id = backtest_resp.json()["data"]["id"]

    mock_client = AsyncMock()
    mock_client.chat_json = AsyncMock(return_value=_valid_analysis_payload())
    with patch("local_llm.service.OllamaClient", return_value=mock_client):
        first = await api_client.post(
            f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
            json={"force": False},
        )
        assert first.status_code == 200
        second = await api_client.post(
            f"/api/v1/backtesting/advisor-runs/{run_id}/analysis",
            json={"force": False},
        )
        assert second.status_code == 200

    mock_client.chat_json.assert_called_once()


@pytest.mark.asyncio
async def test_get_analysis_unknown_run_returns_404(api_client: AsyncClient) -> None:
    resp = await api_client.get(
        f"/api/v1/backtesting/advisor-runs/{uuid.uuid4()}/analysis"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_analysis_unknown_run_returns_404(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    resp = await api_client.post(
        f"/api/v1/backtesting/advisor-runs/{uuid.uuid4()}/analysis",
        json={"force": False},
    )
    assert resp.status_code == 404
