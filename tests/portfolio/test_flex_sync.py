"""Tests for Flex sync service layer."""

from __future__ import annotations

import textwrap
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from broker.ibkr.flex_schemas import FlexExecution
from core.errors import IBKRFlexError


def _make_flex_exec(exec_id: str = "flex-001", symbol: str = "AAPL") -> FlexExecution:
    import datetime as dt

    return FlexExecution(
        exec_id=exec_id,
        account_id_ibkr="DU999",
        symbol=symbol,
        side="BUY",
        quantity=10.0,
        price=150.0,
        executed_at=dt.datetime(2025, 1, 10, 10, 0, tzinfo=dt.UTC),
        raw_json={"source": "IBKR_FLEX"},
    )


def _make_ba_repo_mock() -> AsyncMock:
    m = AsyncMock()
    m.mark_sync_success.return_value = None
    m.mark_sync_failure.return_value = None
    return m


def _make_ibkr_repo_mock(exists: bool = False) -> AsyncMock:
    m = AsyncMock()
    m.exists_by_exec_id.return_value = exists
    m.create.return_value = MagicMock()
    return m


def _make_profile_snapshot() -> MagicMock:
    snap = MagicMock()
    snap.id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    return snap


# ── sync_ibkr_flex_executions ─────────────────────────────────────────────────

VALID_XML = textwrap.dedent("""\
    <?xml version="1.0"?>
    <FlexQueryResponse queryName="test" type="AF">
      <FlexStatements count="1">
        <FlexStatement accountId="DU999">
          <Trades>
            <Trade tradeID="t001" symbol="AAPL" buySell="BUY"
                   quantity="10" tradePrice="150.00"
                   ibCommission="-1.00" currency="USD"
                   tradeDate="20250110" tradeTime="10:00:00"
                   exchange="NASDAQ" orderReference=""/>
          </Trades>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
""")


@pytest.mark.asyncio
async def test_flex_sync_inserts_new_executions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    ba_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    import portfolio.trade_history_service as svc

    ibkr_repo = _make_ibkr_repo_mock(exists=False)
    ba_repo = _make_ba_repo_mock()
    snap = _make_profile_snapshot()

    monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: ibkr_repo)
    monkeypatch.setattr(svc, "BrokerAccountRepository", lambda s: ba_repo)
    monkeypatch.setattr(svc, "build_and_save_profile", AsyncMock(return_value=snap))

    flex_mock = AsyncMock()
    flex_mock.fetch_statement = AsyncMock(return_value=VALID_XML)

    with patch("portfolio.trade_history_service.FlexClient") as flex_cls:
        flex_cls.from_settings.return_value = flex_mock
        result = await svc.sync_ibkr_flex_executions(session, ba_id, "tok", "qid")

    assert result["fetched"] == 1
    assert result["inserted"] == 1
    assert result["profile_snapshot_id"] == str(snap.id)
    ba_repo.mark_sync_success.assert_called_once_with(ba_id)


@pytest.mark.asyncio
async def test_flex_sync_skips_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    ba_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    import portfolio.trade_history_service as svc

    ibkr_repo = _make_ibkr_repo_mock(exists=True)  # all already exist
    ba_repo = _make_ba_repo_mock()
    snap = _make_profile_snapshot()

    monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: ibkr_repo)
    monkeypatch.setattr(svc, "BrokerAccountRepository", lambda s: ba_repo)
    monkeypatch.setattr(svc, "build_and_save_profile", AsyncMock(return_value=snap))

    flex_mock = AsyncMock()
    flex_mock.fetch_statement = AsyncMock(return_value=VALID_XML)

    with patch("portfolio.trade_history_service.FlexClient") as flex_cls:
        flex_cls.from_settings.return_value = flex_mock
        result = await svc.sync_ibkr_flex_executions(session, ba_id, "tok", "qid")

    assert result["fetched"] == 1
    assert result["inserted"] == 0
    ibkr_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_flex_sync_attaches_broker_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    ba_id = uuid.UUID("00000000-0000-0000-0000-000000000003")

    import portfolio.trade_history_service as svc

    ibkr_repo = _make_ibkr_repo_mock(exists=False)
    ba_repo = _make_ba_repo_mock()
    snap = _make_profile_snapshot()

    monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: ibkr_repo)
    monkeypatch.setattr(svc, "BrokerAccountRepository", lambda s: ba_repo)
    monkeypatch.setattr(svc, "build_and_save_profile", AsyncMock(return_value=snap))

    flex_mock = AsyncMock()
    flex_mock.fetch_statement = AsyncMock(return_value=VALID_XML)

    with patch("portfolio.trade_history_service.FlexClient") as flex_cls:
        flex_cls.from_settings.return_value = flex_mock
        await svc.sync_ibkr_flex_executions(session, ba_id, "tok", "qid")

    create_kwargs = ibkr_repo.create.call_args.kwargs
    assert create_kwargs.get("broker_account_id") == ba_id


@pytest.mark.asyncio
async def test_flex_sync_rebuilds_trading_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    ba_id = uuid.UUID("00000000-0000-0000-0000-000000000004")

    import portfolio.trade_history_service as svc

    ibkr_repo = _make_ibkr_repo_mock(exists=False)
    ba_repo = _make_ba_repo_mock()
    snap = _make_profile_snapshot()
    build_mock = AsyncMock(return_value=snap)

    monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: ibkr_repo)
    monkeypatch.setattr(svc, "BrokerAccountRepository", lambda s: ba_repo)
    monkeypatch.setattr(svc, "build_and_save_profile", build_mock)

    flex_mock = AsyncMock()
    flex_mock.fetch_statement = AsyncMock(return_value=VALID_XML)

    with patch("portfolio.trade_history_service.FlexClient") as flex_cls:
        flex_cls.from_settings.return_value = flex_mock
        await svc.sync_ibkr_flex_executions(session, ba_id, "tok", "qid")

    build_mock.assert_called_once()
    call_kwargs = build_mock.call_args.kwargs
    assert call_kwargs.get("broker_account_id") == ba_id


@pytest.mark.asyncio
async def test_flex_sync_marks_failure_on_flex_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    ba_id = uuid.UUID("00000000-0000-0000-0000-000000000005")

    import portfolio.trade_history_service as svc

    ba_repo = _make_ba_repo_mock()
    monkeypatch.setattr(svc, "BrokerAccountRepository", lambda s: ba_repo)
    monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: _make_ibkr_repo_mock())

    flex_mock = AsyncMock()
    flex_mock.fetch_statement = AsyncMock(side_effect=IBKRFlexError("Connection failed"))

    with (
        patch("portfolio.trade_history_service.FlexClient") as flex_cls,
        pytest.raises(IBKRFlexError),
    ):
        flex_cls.from_settings.return_value = flex_mock
        await svc.sync_ibkr_flex_executions(session, ba_id, "tok", "qid")

    ba_repo.mark_sync_failure.assert_called_once()
    call_args = ba_repo.mark_sync_failure.call_args
    assert call_args[0][0] == ba_id


@pytest.mark.asyncio
async def test_flex_sync_repeated_same_broker_is_idempotent(
    db_session,
) -> None:
    from db.models import BrokerAccount
    from portfolio.trade_history_service import sync_ibkr_flex_executions

    broker_account = BrokerAccount(
        provider="IBKR",
        display_name="Flex Idempotency Broker",
        connection_mode="LOCAL_TWS",
        client_id=1,
        readonly=True,
        is_active=True,
        metadata_json={},
    )
    db_session.add(broker_account)
    await db_session.flush()

    flex_mock = AsyncMock()
    flex_mock.fetch_statement = AsyncMock(return_value=VALID_XML)

    with patch("portfolio.trade_history_service.FlexClient") as flex_cls:
        flex_cls.from_settings.return_value = flex_mock
        first = await sync_ibkr_flex_executions(db_session, broker_account.id, "tok", "qid")
        second = await sync_ibkr_flex_executions(db_session, broker_account.id, "tok", "qid")

    assert first["fetched"] == 1
    assert first["inserted"] == 1
    assert second["fetched"] == 1
    assert second["inserted"] == 0
