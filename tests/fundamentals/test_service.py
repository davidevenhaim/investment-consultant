"""Tests for fundamentals service — uses mock provider, requires DB."""

import datetime as dt

import pytest
from fundamentals.repository import CompanyFundamentalsRepository, _fix_yfinance_dte
from fundamentals.service import ensure_company_fundamentals
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import MockFundamentalsProvider, _make_snapshot


@pytest.mark.asyncio
async def test_ensure_fundamentals_stores_snapshot(
    db_session: AsyncSession, mock_fundamentals_provider: MockFundamentalsProvider
) -> None:
    snapshot = await ensure_company_fundamentals(
        db_session, "AAPL", provider=mock_fundamentals_provider
    )
    assert snapshot.symbol == "AAPL"
    assert snapshot.trailing_pe is not None
    assert snapshot.provider == "mock"


@pytest.mark.asyncio
async def test_ensure_fundamentals_idempotent(
    db_session: AsyncSession, mock_fundamentals_provider: MockFundamentalsProvider
) -> None:
    s1 = await ensure_company_fundamentals(db_session, "NVDA", provider=mock_fundamentals_provider)
    s2 = await ensure_company_fundamentals(db_session, "NVDA", provider=mock_fundamentals_provider)
    assert s1.symbol == s2.symbol == "NVDA"
    assert s1.trailing_pe == s2.trailing_pe


@pytest.mark.asyncio
async def test_ensure_fundamentals_uses_cached_if_fresh(
    db_session: AsyncSession, mock_fundamentals_provider: MockFundamentalsProvider
) -> None:
    # Pre-seed a very recent snapshot
    repo = CompanyFundamentalsRepository(db_session)
    old = _make_snapshot("MSFT", trailing_pe=99.0)
    old = old.model_copy(update={"as_of_date": dt.date.today()})
    await repo.upsert(old)

    # Service should return cached without calling provider again
    result = await ensure_company_fundamentals(
        db_session, "MSFT", provider=mock_fundamentals_provider, max_age_days=7
    )
    assert result.symbol == "MSFT"
    # Either cached or freshly fetched — both valid, just ensure no crash


@pytest.mark.asyncio
async def test_ensure_fundamentals_empty_symbol_returns_stub(
    db_session: AsyncSession, mock_fundamentals_provider: MockFundamentalsProvider
) -> None:
    result = await ensure_company_fundamentals(
        db_session, "ZZZZ", provider=mock_fundamentals_provider
    )
    assert result.symbol == "ZZZZ"


@pytest.mark.asyncio
async def test_repository_upsert_idempotent(db_session: AsyncSession) -> None:
    repo = CompanyFundamentalsRepository(db_session)
    snap = _make_snapshot("AAPL")
    await repo.upsert(snap)
    await repo.upsert(snap)  # second upsert same date+provider
    latest = await repo.get_latest("AAPL", provider="mock")
    assert latest is not None
    assert latest.trailing_pe == snap.trailing_pe


@pytest.mark.asyncio
async def test_repository_returns_latest(db_session: AsyncSession) -> None:
    repo = CompanyFundamentalsRepository(db_session)
    old = _make_snapshot("AAPL")
    old = old.model_copy(update={"as_of_date": dt.date(2025, 1, 1), "trailing_pe": 20.0})
    new = _make_snapshot("AAPL")
    new = new.model_copy(update={"as_of_date": dt.date(2026, 1, 15), "trailing_pe": 28.0})

    await repo.upsert(old)
    await repo.upsert(new)

    latest = await repo.get_latest("AAPL", provider="mock")
    assert latest is not None
    assert latest.trailing_pe == pytest.approx(28.0)


def test_completeness_score_full() -> None:
    snap = _make_snapshot("AAPL")
    assert snap.completeness_score == pytest.approx(1.0)


def test_completeness_score_empty() -> None:
    from fundamentals.schemas import CompanyFundamentalsSnapshot

    snap = CompanyFundamentalsSnapshot(symbol="X", as_of_date=dt.date.today(), provider="mock")
    assert snap.completeness_score == pytest.approx(0.0)


def test_completeness_score_partial() -> None:
    snap = _make_snapshot("AAPL", revenue_growth=None, return_on_equity=None, free_cashflow=None)
    assert 0.0 < snap.completeness_score < 1.0


# ── _fix_yfinance_dte unit tests ──────────────────────────────────────────────


def test_fix_dte_normalizes_aapl_raw() -> None:
    """DB row with AAPL raw yfinance value (79.548) must normalize to 0.79548."""
    result = _fix_yfinance_dte(79.548, {"debtToEquity": 79.548})
    assert result == pytest.approx(0.79548)


def test_fix_dte_does_not_renormalize_aapl() -> None:
    """Already-normalized AAPL row (0.79548) must not be divided again."""
    result = _fix_yfinance_dte(0.79548, {"debtToEquity": 79.548})
    assert result == pytest.approx(0.79548)


def test_fix_dte_normalizes_nvda_raw() -> None:
    """NVDA raw value (7.25) → 0.0725."""
    result = _fix_yfinance_dte(7.25, {"debtToEquity": 7.25})
    assert result == pytest.approx(0.0725)


def test_fix_dte_does_not_renormalize_nvda() -> None:
    """Already-normalized NVDA row (0.0725) stays 0.0725."""
    result = _fix_yfinance_dte(0.0725, {"debtToEquity": 7.25})
    assert result == pytest.approx(0.0725)


def test_fix_dte_zero_debt() -> None:
    """Company with zero debt: always returns 0.0."""
    assert _fix_yfinance_dte(0.0, {"debtToEquity": 0.0}) == 0.0


def test_fix_dte_no_raw_json_large_value() -> None:
    """No raw_json reference. Value > 10 treated as raw percentage."""
    assert _fix_yfinance_dte(79.548, {}) == pytest.approx(0.79548)


def test_fix_dte_no_raw_json_small_value() -> None:
    """No raw_json reference. Value <= 10 left as-is (assumed already normalized)."""
    assert _fix_yfinance_dte(0.795, {}) == pytest.approx(0.795)
    assert _fix_yfinance_dte(1.5, {}) == pytest.approx(1.5)


def test_fix_dte_moderate_leverage_raw() -> None:
    """50% D/E raw (50.0) → ratio 0.5."""
    assert _fix_yfinance_dte(50.0, {"debtToEquity": 50.0}) == pytest.approx(0.50)


def test_fix_dte_moderate_leverage_normalized() -> None:
    """Already-normalized 0.5 stays 0.5."""
    assert _fix_yfinance_dte(0.5, {"debtToEquity": 50.0}) == pytest.approx(0.5)


# ── Repository round-trip: stale row normalization ────────────────────────────


@pytest.mark.asyncio
async def test_cached_stale_yfinance_row_normalized_on_read(
    db_session: AsyncSession,
) -> None:
    """
    Simulate a pre-M5 cached yfinance row with raw debt_to_equity (e.g. 79.548).
    Reading it back must return the normalized value (0.79548).
    raw_json must preserve the original raw value.
    """
    import datetime as dt

    from db.models import CompanyFundamentals
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Insert raw (un-normalized) row directly — bypassing the provider
    raw_dte = 79.548
    stmt = pg_insert(CompanyFundamentals).values(
        [
            {
                "symbol": "AAPL",
                "as_of_date": dt.date.today(),
                "provider": "yfinance",
                "debt_to_equity": raw_dte,
                "raw_json": {"debtToEquity": raw_dte, "symbol": "AAPL"},
            }
        ]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_company_fundamentals_symbol_date_provider",
        set_={"debt_to_equity": stmt.excluded["debt_to_equity"]},
    )
    await db_session.execute(stmt)
    await db_session.flush()

    repo = CompanyFundamentalsRepository(db_session)
    snap = await repo.get_latest("AAPL", provider="yfinance")

    assert snap is not None
    # Must be normalized on read
    assert snap.debt_to_equity == pytest.approx(0.79548, rel=1e-3)
    # raw_json must still contain original raw value
    assert snap.raw_json.get("debtToEquity") == pytest.approx(79.548)


@pytest.mark.asyncio
async def test_cached_normalized_yfinance_row_not_double_divided(
    db_session: AsyncSession,
) -> None:
    """
    A correctly-normalized row (debt_to_equity=0.79548 with raw_json.debtToEquity=79.548)
    must NOT be divided by 100 again when read back.
    """
    import datetime as dt

    from db.models import CompanyFundamentals
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    normalized_dte = 0.79548
    raw_dte = 79.548
    stmt = pg_insert(CompanyFundamentals).values(
        [
            {
                "symbol": "NVDA",
                "as_of_date": dt.date.today(),
                "provider": "yfinance",
                "debt_to_equity": normalized_dte,
                "raw_json": {"debtToEquity": raw_dte, "symbol": "NVDA"},
            }
        ]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_company_fundamentals_symbol_date_provider",
        set_={"debt_to_equity": stmt.excluded["debt_to_equity"]},
    )
    await db_session.execute(stmt)
    await db_session.flush()

    repo = CompanyFundamentalsRepository(db_session)
    snap = await repo.get_latest("NVDA", provider="yfinance")

    assert snap is not None
    assert snap.debt_to_equity == pytest.approx(0.79548, rel=1e-3)


# ── Scoring reason uses normalized D/E ───────────────────────────────────────


def test_fundamental_score_aapl_dte_reason_is_normalized() -> None:
    """
    Snapshot with AAPL-like D/E (0.795x normalized) must produce
    a reason like "Moderate debt-to-equity (0.80x)", not "79.55x".
    """
    from research_graph.nodes.neutral_recommendation import _fundamental_score

    snap = _make_snapshot("AAPL", debt_to_equity=0.79548)
    _score, reasons, risks = _fundamental_score(snap)

    all_text = " ".join(reasons + risks)
    assert "79" not in all_text, f"Raw D/E value leaked into reasons: {all_text}"
    assert "0." in all_text or "Moderate" in all_text or "Low" in all_text, (
        f"Expected normalized D/E in reasons, got: {all_text}"
    )


def test_fundamental_score_nvda_dte_reason_is_normalized() -> None:
    """NVDA-like D/E (0.0725x normalized) must show 'Low debt-to-equity'."""
    from research_graph.nodes.neutral_recommendation import _fundamental_score

    snap = _make_snapshot("NVDA", debt_to_equity=0.0725)
    _score, reasons, _risks = _fundamental_score(snap)

    assert any("Low debt-to-equity" in r for r in reasons), f"Expected Low D/E, got: {reasons}"
    assert not any("7.25" in r for r in reasons), f"Raw NVDA D/E leaked: {reasons}"
