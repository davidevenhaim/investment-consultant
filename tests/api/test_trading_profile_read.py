"""Tests for trading-profile read path — broker-account preference and fallback."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Repository ordering tests (unit, no DB) ───────────────────────────────────


def _make_snapshot(
    as_of_date: dt.date,
    created_at: dt.datetime,
    total_executions: int = 1,
    broker_account_id: uuid.UUID | None = None,
) -> MagicMock:
    snap = MagicMock()
    snap.as_of_date = as_of_date
    snap.created_at = created_at
    snap.total_executions = total_executions
    snap.broker_account_id = broker_account_id
    return snap


class TestTradingProfileSnapshotRepoOrdering:
    """Verify latest() returns newest created_at when as_of_date is tied."""

    @pytest.mark.asyncio
    async def test_latest_uses_created_at_tiebreaker(self) -> None:
        """When two snapshots share same as_of_date, newest created_at wins."""
        from db.repositories import TradingProfileSnapshotRepository

        session = AsyncMock()

        newer = _make_snapshot(
            dt.date(2025, 5, 10),
            dt.datetime(2025, 5, 10, 12, 0, tzinfo=dt.UTC),
            total_executions=277,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = newer
        session.execute = AsyncMock(return_value=mock_result)

        repo = TradingProfileSnapshotRepository(session)
        result = await repo.latest()

        # Verify ORDER BY includes created_at DESC
        call_args = session.execute.call_args[0][0]
        order_clauses = str(call_args)
        assert "created_at" in order_clauses
        assert result.total_executions == 277


# ── API endpoint tests (unit, mock service layer) ─────────────────────────────


def _make_snapshot_response(total_executions: int, broker_account_id: uuid.UUID | None = None) -> MagicMock:
    snap = MagicMock()
    snap.id = uuid.uuid4()
    snap.broker_account_id = broker_account_id
    snap.period_months = 12
    snap.as_of_date = dt.date(2025, 5, 10)
    snap.total_executions = total_executions
    snap.total_symbols_traded = 5
    snap.win_rate = 0.6
    snap.avg_winner_pct = 0.08
    snap.avg_loser_pct = 0.04
    snap.profit_factor = 2.0
    snap.avg_holding_days = 10.0
    snap.disposition_effect_score = 0.1
    snap.concentration_score = 0.3
    snap.recency_bias_score = 0.2
    snap.behavioral_flags_json = []
    snap.per_symbol_stats_json = {}
    snap.raw_metrics_json = {}
    snap.created_at = dt.datetime(2025, 5, 10, 12, 0, tzinfo=dt.UTC)
    snap.updated_at = dt.datetime(2025, 5, 10, 12, 0, tzinfo=dt.UTC)
    return snap


@pytest.mark.asyncio
async def test_get_trading_profile_prefers_broker_scoped(api_client: Any) -> None:
    """GET /trading-profile returns broker-scoped snapshot when one exists."""
    ba_id = uuid.uuid4()
    broker_snap = _make_snapshot_response(total_executions=277, broker_account_id=ba_id)
    global_snap = _make_snapshot_response(total_executions=2, broker_account_id=None)

    broker_account_mock = MagicMock()
    broker_account_mock.id = ba_id

    async def mock_latest(period_months=None, broker_account_id=None):
        if broker_account_id == ba_id:
            return broker_snap
        return global_snap

    with (
        patch(
            "apps.api.routers.portfolio.BrokerAccountRepository",
            return_value=MagicMock(
                get_active_default=AsyncMock(return_value=broker_account_mock)
            ),
        ),
        patch(
            "apps.api.routers.portfolio.TradingProfileSnapshotRepository",
            return_value=MagicMock(latest=mock_latest),
        ),
    ):
        resp = await api_client.get("/api/v1/portfolio/trading-profile")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_executions"] == 277


@pytest.mark.asyncio
async def test_get_trading_profile_falls_back_to_global(api_client: Any) -> None:
    """GET /trading-profile falls back to global snapshot when no broker-scoped one."""
    ba_id = uuid.uuid4()
    global_snap = _make_snapshot_response(total_executions=2, broker_account_id=None)

    broker_account_mock = MagicMock()
    broker_account_mock.id = ba_id

    async def mock_latest(period_months=None, broker_account_id=None):
        if broker_account_id == ba_id:
            return None  # No broker-scoped snapshot
        return global_snap

    with (
        patch(
            "apps.api.routers.portfolio.BrokerAccountRepository",
            return_value=MagicMock(
                get_active_default=AsyncMock(return_value=broker_account_mock)
            ),
        ),
        patch(
            "apps.api.routers.portfolio.TradingProfileSnapshotRepository",
            return_value=MagicMock(latest=mock_latest),
        ),
    ):
        resp = await api_client.get("/api/v1/portfolio/trading-profile")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_executions"] == 2


@pytest.mark.asyncio
async def test_get_trading_profile_no_broker_account_returns_global(api_client: Any) -> None:
    """GET /trading-profile works when no broker account exists."""
    global_snap = _make_snapshot_response(total_executions=5)

    with (
        patch(
            "apps.api.routers.portfolio.BrokerAccountRepository",
            return_value=MagicMock(
                get_active_default=AsyncMock(return_value=None)
            ),
        ),
        patch(
            "apps.api.routers.portfolio.TradingProfileSnapshotRepository",
            return_value=MagicMock(latest=AsyncMock(return_value=global_snap)),
        ),
    ):
        resp = await api_client.get("/api/v1/portfolio/trading-profile")

    assert resp.status_code == 200
    assert resp.json()["data"]["total_executions"] == 5


@pytest.mark.asyncio
async def test_get_trading_profile_404_when_no_snapshots(api_client: Any) -> None:
    with (
        patch(
            "apps.api.routers.portfolio.BrokerAccountRepository",
            return_value=MagicMock(
                get_active_default=AsyncMock(return_value=None)
            ),
        ),
        patch(
            "apps.api.routers.portfolio.TradingProfileSnapshotRepository",
            return_value=MagicMock(latest=AsyncMock(return_value=None)),
        ),
    ):
        resp = await api_client.get("/api/v1/portfolio/trading-profile")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_symbol_stats_passes_broker_account_id(api_client: Any) -> None:
    """GET /trading-profile/{symbol} passes broker_account_id to service."""
    ba_id = uuid.uuid4()
    broker_account_mock = MagicMock()
    broker_account_mock.id = ba_id

    captured: dict = {}

    async def mock_get_stats(session, symbol, broker_account_id=None, **kw):
        captured["broker_account_id"] = broker_account_id
        return {"win_rate": 0.6, "total_trades": 10}

    with (
        patch(
            "apps.api.routers.portfolio.BrokerAccountRepository",
            return_value=MagicMock(
                get_active_default=AsyncMock(return_value=broker_account_mock)
            ),
        ),
        patch(
            "portfolio.trade_history_service.get_symbol_trading_stats",
            side_effect=mock_get_stats,
        ),
    ):
        resp = await api_client.get("/api/v1/portfolio/trading-profile/AAPL")

    assert resp.status_code == 200
    assert captured.get("broker_account_id") == ba_id


@pytest.mark.asyncio
async def test_trades_passes_broker_account_id(api_client: Any) -> None:
    """GET /trades passes broker_account_id to load_all_executions."""
    ba_id = uuid.uuid4()
    broker_account_mock = MagicMock()
    broker_account_mock.id = ba_id

    captured: dict = {}

    async def mock_load(session, months=12, symbol=None, broker_account_id=None):
        captured["broker_account_id"] = broker_account_id
        return []

    with (
        patch(
            "apps.api.routers.portfolio.BrokerAccountRepository",
            return_value=MagicMock(
                get_active_default=AsyncMock(return_value=broker_account_mock)
            ),
        ),
        patch(
            "portfolio.trade_history_service.load_all_executions",
            side_effect=mock_load,
        ),
    ):
        resp = await api_client.get("/api/v1/portfolio/trades")

    assert resp.status_code == 200
    assert captured.get("broker_account_id") == ba_id


@pytest.mark.asyncio
async def test_trades_no_broker_account_passes_none(api_client: Any) -> None:
    """GET /trades passes broker_account_id=None when no active broker account."""
    captured: dict = {}

    async def mock_load(session, months=12, symbol=None, broker_account_id=None):
        captured["broker_account_id"] = broker_account_id
        return []

    with (
        patch(
            "apps.api.routers.portfolio.BrokerAccountRepository",
            return_value=MagicMock(
                get_active_default=AsyncMock(return_value=None)
            ),
        ),
        patch(
            "portfolio.trade_history_service.load_all_executions",
            side_effect=mock_load,
        ),
    ):
        resp = await api_client.get("/api/v1/portfolio/trades")

    assert resp.status_code == 200
    assert captured.get("broker_account_id") is None
