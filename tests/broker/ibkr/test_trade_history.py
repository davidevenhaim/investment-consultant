"""Tests for IBKR trade history fetch and mapper."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from broker.ibkr.mapper import map_execution
from broker.ibkr.schemas import IBKRExecution

# ── Mapper tests ──────────────────────────────────────────────────────────────


def _make_exec_obj(
    exec_id: str = "0001.DU123456.12345.01",
    symbol: str = "AAPL",
    side: str = "BOT",
    shares: float = 10.0,
    price: float = 150.0,
    time: str = "20250110  10:00:00",
    currency: str = "USD",
    exchange: str = "NASDAQ",
) -> MagicMock:
    obj = MagicMock()
    obj.execId = exec_id
    obj.side = side
    obj.shares = shares
    obj.price = price
    obj.time = time
    obj.currency = currency
    obj.exchange = exchange
    obj.orderRef = ""
    obj.commission = 1.0
    contract = MagicMock()
    contract.symbol = symbol
    obj.contract = contract
    return obj


def test_mapper_bot_side_maps_to_buy() -> None:
    obj = _make_exec_obj(side="BOT")
    ex = map_execution(obj, "DU999")
    assert ex.side == "BUY"


def test_mapper_sld_side_maps_to_sell() -> None:
    obj = _make_exec_obj(side="SLD")
    ex = map_execution(obj, "DU999")
    assert ex.side == "SELL"


def test_mapper_buy_passthrough() -> None:
    obj = _make_exec_obj(side="BUY")
    ex = map_execution(obj, "DU999")
    assert ex.side == "BUY"


def test_mapper_unknown_side_raises() -> None:
    obj = _make_exec_obj(side="UNKNOWN")
    with pytest.raises(ValueError, match="Unknown side"):
        map_execution(obj, "DU999")


def test_mapper_parses_ibkr_timestamp_format() -> None:
    obj = _make_exec_obj(time="20250315  14:30:00")
    ex = map_execution(obj, "DU999")
    assert ex.executed_at.year == 2025
    assert ex.executed_at.month == 3
    assert ex.executed_at.day == 15
    assert ex.executed_at.hour == 14


def test_mapper_correct_symbol() -> None:
    obj = _make_exec_obj(symbol="NVDA")
    ex = map_execution(obj, "DU999")
    assert ex.symbol == "NVDA"


def test_mapper_correct_quantity_price() -> None:
    obj = _make_exec_obj(shares=25.5, price=200.0)
    ex = map_execution(obj, "DU999")
    assert ex.quantity == pytest.approx(25.5)
    assert ex.price == pytest.approx(200.0)


def test_mapper_sets_account_id() -> None:
    obj = _make_exec_obj()
    ex = map_execution(obj, "DU123456")
    assert ex.account_id_ibkr == "DU123456"


def test_mapper_returns_ibkr_execution_schema() -> None:
    obj = _make_exec_obj()
    ex = map_execution(obj, "DU999")
    assert isinstance(ex, IBKRExecution)


# ── fetch_executions diagnostics ─────────────────────────────────────────────


def _make_mock_client(fills: list[Any]) -> MagicMock:
    """Build a mock IBKRClient whose ib returns the given fills."""
    ib_mock = MagicMock()
    ib_mock.managedAccounts.return_value = ["DU123456"]
    ib_mock.reqCurrentTime.return_value = 1234567890
    ib_mock.reqExecutionsAsync = AsyncMock(return_value=fills)

    client_mock = MagicMock()
    client_mock.ib = ib_mock
    client_mock.broker_account_id = "test-ba-id"
    return client_mock


def _patch_ib_insync() -> Any:
    """Return a context manager that stubs out the ib_insync module import."""
    import sys

    fake_module = MagicMock()
    fake_module.ExecutionFilter = MagicMock  # ExecutionFilter(**kwargs) returns a mock
    return patch.dict(sys.modules, {"ib_insync": fake_module})


@pytest.mark.asyncio
async def test_fetch_executions_zero_raw_returns_empty() -> None:
    """0 raw fills → 0 mapped executions, no mapper error."""
    from broker.ibkr.trade_history import fetch_executions

    client = _make_mock_client(fills=[])
    with _patch_ib_insync():
        result = await fetch_executions(client, months=12)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_executions_maps_valid_fills() -> None:
    """Valid fills → correctly mapped executions."""
    from broker.ibkr.trade_history import fetch_executions

    fill = MagicMock()
    exec_obj = _make_exec_obj(exec_id="e001", symbol="AAPL", side="BOT")
    fill.execution = exec_obj

    client = _make_mock_client(fills=[fill])
    with _patch_ib_insync():
        result = await fetch_executions(client, months=12)
    assert len(result) == 1
    assert result[0].symbol == "AAPL"
    assert result[0].side == "BUY"
    assert result[0].exec_id == "e001"


@pytest.mark.asyncio
async def test_fetch_executions_deduplicates_same_exec_id() -> None:
    """Duplicate exec_id fills are counted once."""
    from broker.ibkr.trade_history import fetch_executions

    exec_obj = _make_exec_obj(exec_id="dup-001")
    fill1, fill2 = MagicMock(), MagicMock()
    fill1.execution = exec_obj
    fill2.execution = exec_obj

    client = _make_mock_client(fills=[fill1, fill2])
    with _patch_ib_insync():
        result = await fetch_executions(client, months=12)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_fetch_executions_skips_bad_mapper_does_not_crash() -> None:
    """Mapper error on one fill → that fill skipped, rest returned."""
    from broker.ibkr.trade_history import fetch_executions

    good_fill = MagicMock()
    good_fill.execution = _make_exec_obj(exec_id="good-001", side="BOT")

    bad_fill = MagicMock()
    bad_exec = MagicMock()
    bad_exec.execId = "bad-001"
    bad_exec.side = "UNKNOWN_SIDE"
    bad_exec.shares = 5.0
    bad_exec.price = 100.0
    bad_exec.time = "20250101  09:30:00"
    bad_exec.currency = "USD"
    bad_exec.exchange = "NYSE"
    bad_exec.orderRef = ""
    bad_exec.commission = 1.0
    bad_exec.contract = MagicMock(symbol="BAD")
    bad_fill.execution = bad_exec

    client = _make_mock_client(fills=[good_fill, bad_fill])
    with _patch_ib_insync():
        result = await fetch_executions(client, months=12)

    assert len(result) == 1
    assert result[0].exec_id == "good-001"


@pytest.mark.asyncio
async def test_fetch_executions_sorted_ascending() -> None:
    """Returned executions are sorted by executed_at ascending."""
    from broker.ibkr.trade_history import fetch_executions

    fill_late = MagicMock()
    fill_late.execution = _make_exec_obj(exec_id="late", time="20250315  14:00:00")

    fill_early = MagicMock()
    fill_early.execution = _make_exec_obj(exec_id="early", time="20250110  10:00:00")

    client = _make_mock_client(fills=[fill_late, fill_early])
    with _patch_ib_insync():
        result = await fetch_executions(client, months=12)

    assert result[0].exec_id == "early"
    assert result[1].exec_id == "late"


# ── fetch_session_diagnostics ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_session_diagnostics_zero_executions() -> None:
    from broker.ibkr.trade_history import fetch_session_diagnostics

    client = _make_mock_client(fills=[])
    with _patch_ib_insync():
        diag = await fetch_session_diagnostics(client)

    assert diag["managed_accounts"] == ["DU123456"]
    assert diag["raw_execution_count"] == 0
    assert diag["mapped_execution_count"] == 0
    assert diag["first_execution_at"] is None
    assert diag["last_execution_at"] is None
    assert "note" in diag


@pytest.mark.asyncio
async def test_fetch_session_diagnostics_with_executions() -> None:
    from broker.ibkr.trade_history import fetch_session_diagnostics

    fill = MagicMock()
    fill.execution = _make_exec_obj(exec_id="d001", time="20250110  10:00:00")

    client = _make_mock_client(fills=[fill])
    with _patch_ib_insync():
        diag = await fetch_session_diagnostics(client)

    assert diag["raw_execution_count"] == 1
    assert diag["mapped_execution_count"] == 1
    assert diag["first_execution_at"] is not None
    assert diag["last_execution_at"] is not None


# ── sync_runner diagnostics path ──────────────────────────────────────────────


def test_run_diagnostics_isolated_returns_dict_shape() -> None:
    from broker.ibkr.client import IBKRConnectionConfig
    from broker.ibkr.sync_runner import run_diagnostics_isolated

    config = IBKRConnectionConfig(
        host="localhost", port=7497, client_id=1, readonly=True, timeout_seconds=5
    )
    fake_diag = {
        "managed_accounts": ["DU999"],
        "server_time": "1234567890",
        "raw_execution_count": 3,
        "mapped_execution_count": 3,
        "first_execution_at": "2025-01-10T10:00:00+00:00",
        "last_execution_at": "2025-03-15T14:00:00+00:00",
        "note": "test note",
    }

    with patch("broker.ibkr.sync_runner.asyncio.run", return_value=fake_diag):
        result = run_diagnostics_isolated(config)

    assert result["managed_accounts"] == ["DU999"]
    assert result["raw_execution_count"] == 3
    assert result["mapped_execution_count"] == 3


def test_run_diagnostics_isolated_zero_executions() -> None:
    from broker.ibkr.client import IBKRConnectionConfig
    from broker.ibkr.sync_runner import run_diagnostics_isolated

    config = IBKRConnectionConfig(
        host="localhost", port=7497, client_id=1, readonly=True, timeout_seconds=5
    )
    fake_diag = {
        "managed_accounts": ["DU999"],
        "server_time": "1234567890",
        "raw_execution_count": 0,
        "mapped_execution_count": 0,
        "first_execution_at": None,
        "last_execution_at": None,
        "note": "test",
    }

    with patch("broker.ibkr.sync_runner.asyncio.run", return_value=fake_diag):
        result = run_diagnostics_isolated(config)

    assert result["raw_execution_count"] == 0
    assert result["first_execution_at"] is None


# ── sync with 0 executions still marks broker account success ─────────────────


@pytest.mark.asyncio
async def test_sync_zero_executions_marks_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0 executions returned → sync_ibkr_executions returns 0 inserted, no error."""
    from unittest.mock import AsyncMock

    import portfolio.trade_history_service as svc

    session = AsyncMock()
    ba_id = __import__("uuid").UUID("00000000-0000-0000-0000-000000000001")

    ibkr_repo_mock = AsyncMock()
    ibkr_repo_mock.exists_by_exec_id.return_value = False
    ibkr_repo_mock.create.return_value = MagicMock()

    ba_repo_mock = AsyncMock()
    ba_repo_mock.mark_sync_success.return_value = None

    monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: ibkr_repo_mock)
    monkeypatch.setattr(svc, "BrokerAccountRepository", lambda s: ba_repo_mock)

    from portfolio.trade_history_service import sync_ibkr_executions

    inserted = await sync_ibkr_executions(session, [], broker_account_id=ba_id)
    assert inserted == 0
    ba_repo_mock.mark_sync_success.assert_called_once_with(ba_id)


# ── sync with executions persists them ───────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_with_executions_persists_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N executions returned → all inserted, success marked."""
    from unittest.mock import AsyncMock

    import portfolio.trade_history_service as svc
    from broker.ibkr.fake_client import _FAKE_EXECUTIONS

    session = AsyncMock()
    ba_id = __import__("uuid").UUID("00000000-0000-0000-0000-000000000002")

    ibkr_repo_mock = AsyncMock()
    ibkr_repo_mock.exists_by_exec_id.return_value = False
    ibkr_repo_mock.create.return_value = MagicMock()

    ba_repo_mock = AsyncMock()
    ba_repo_mock.mark_sync_success.return_value = None

    monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: ibkr_repo_mock)
    monkeypatch.setattr(svc, "BrokerAccountRepository", lambda s: ba_repo_mock)

    from portfolio.trade_history_service import sync_ibkr_executions

    inserted = await sync_ibkr_executions(session, _FAKE_EXECUTIONS, broker_account_id=ba_id)
    assert inserted == len(_FAKE_EXECUTIONS)
    assert ibkr_repo_mock.create.call_count == len(_FAKE_EXECUTIONS)
    ba_repo_mock.mark_sync_success.assert_called_once_with(ba_id)
