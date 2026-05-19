"""Tests for IBKR Flex XML parser."""

from __future__ import annotations

import datetime as dt
import textwrap

import pytest
from broker.ibkr.flex_parser import (
    _derive_exec_id,
    _parse_datetime,
    _parse_side,
    parse_flex_xml,
)
from broker.ibkr.flex_schemas import FlexExecution

# ── minimal valid Flex XML ────────────────────────────────────────────────────

_SINGLE_BUY = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <FlexQueryResponse queryName="test" type="AF">
      <FlexStatements count="1">
        <FlexStatement accountId="DU123456" fromDate="20250101" toDate="20250501">
          <Trades>
            <Trade tradeID="111001" symbol="AAPL" buySell="BUY"
                   quantity="10" tradePrice="150.00"
                   ibCommission="-1.00" currency="USD"
                   tradeDate="20250110" tradeTime="10:00:00"
                   exchange="NASDAQ" orderReference=""/>
          </Trades>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
""")

_SINGLE_SELL = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <FlexQueryResponse queryName="test" type="AF">
      <FlexStatements count="1">
        <FlexStatement accountId="DU123456" fromDate="20250101" toDate="20250501">
          <Trades>
            <Trade tradeID="222001" symbol="NVDA" buySell="SLD"
                   quantity="-5" tradePrice="350.00"
                   ibCommission="-1.50" currency="USD"
                   tradeDate="20250315" tradeTime="14:30:00"
                   exchange="NASDAQ" orderReference=""/>
          </Trades>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
""")

# Real-world format: ibExecID + dateTime attribute (semicolon, no colons in time)
# Matches actual IBKR output: dateTime="YYYYMMDD;HHMMSS"
_REAL_FORMAT = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <FlexQueryResponse queryName="ai-consultant-v1" type="AF">
      <FlexStatements count="1">
        <FlexStatement accountId="U16497342" fromDate="20250509" toDate="20260508">
          <Trades>
            <Trade ibExecID="0001e621.aaaa.bbbb.0001" tradeID="999001"
                   symbol="AAPL" buySell="BUY"
                   quantity="10" tradePrice="197.25"
                   ibCommission="-1.05" currency="USD"
                   dateTime="20250510;093000"
                   exchange="NASDAQ" orderReference=""/>
            <Trade ibExecID="0001e621.aaaa.bbbb.0002" tradeID="999002"
                   symbol="AAPL" buySell="SELL"
                   quantity="-10" tradePrice="226.09"
                   ibCommission="-1.10" currency="USD"
                   dateTime="20250515;140000"
                   exchange="NASDAQ" orderReference=""/>
          </Trades>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
""")

_MULTI_TRADE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <FlexQueryResponse queryName="test" type="AF">
      <FlexStatements count="1">
        <FlexStatement accountId="DU123456">
          <Trades>
            <Trade tradeID="300" symbol="AAPL" buySell="BUY"
                   quantity="10" tradePrice="150.00"
                   ibCommission="-1.00" currency="USD"
                   tradeDate="20250110" tradeTime="09:30:00" exchange="NASDAQ" orderReference=""/>
            <Trade tradeID="301" symbol="NVDA" buySell="SLD"
                   quantity="-5" tradePrice="400.00"
                   ibCommission="-1.00" currency="USD"
                   tradeDate="20250315" tradeTime="14:00:00" exchange="NASDAQ" orderReference=""/>
            <Trade tradeID="302" symbol="TSLA" buySell="BUY"
                   quantity="8" tradePrice="200.00"
                   ibCommission="-0.80" currency="USD"
                   tradeDate="20250305" tradeTime="10:00:00" exchange="NASDAQ" orderReference=""/>
          </Trades>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
""")

_ERROR_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <FlexQueryResponse queryName="" type="">
      <Error>No data available for the specified period</Error>
    </FlexQueryResponse>
""")

_DUPLICATE_TRADE_ID = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <FlexQueryResponse queryName="test" type="AF">
      <FlexStatements count="1">
        <FlexStatement accountId="DU123456">
          <Trades>
            <Trade tradeID="dup001" symbol="AAPL" buySell="BUY"
                   quantity="10" tradePrice="150.00"
                   ibCommission="-1.00" currency="USD"
                   tradeDate="20250110" tradeTime="10:00:00" exchange="" orderReference=""/>
            <Trade tradeID="dup001" symbol="AAPL" buySell="BUY"
                   quantity="10" tradePrice="150.00"
                   ibCommission="-1.00" currency="USD"
                   tradeDate="20250110" tradeTime="10:00:00" exchange="" orderReference=""/>
          </Trades>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
""")


# ── side parsing ──────────────────────────────────────────────────────────────


def test_parse_side_buy() -> None:
    assert _parse_side("BUY") == "BUY"


def test_parse_side_bot() -> None:
    assert _parse_side("BOT") == "BUY"


def test_parse_side_sell() -> None:
    assert _parse_side("SELL") == "SELL"


def test_parse_side_sld() -> None:
    assert _parse_side("SLD") == "SELL"


def test_parse_side_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unrecognised"):
        _parse_side("LONG")


# ── datetime parsing ──────────────────────────────────────────────────────────


def test_parse_datetime_standard() -> None:
    ts = _parse_datetime("20250110", "10:00:00")
    assert ts == dt.datetime(2025, 1, 10, 10, 0, 0, tzinfo=dt.UTC)


def test_parse_datetime_midnight_fallback() -> None:
    ts = _parse_datetime("20250110", "")
    assert ts.date() == dt.date(2025, 1, 10)


def test_parse_datetime_semicolon_no_colons() -> None:
    """Real IBKR dateTime attribute: YYYYMMDD;HHMMSS (no colons in time)."""
    ts = _parse_datetime("20250613;111628", "")
    assert ts == dt.datetime(2025, 6, 13, 11, 16, 28, tzinfo=dt.UTC)


def test_parse_datetime_semicolon_with_colons() -> None:
    """Some IBKR configs use YYYYMMDD;HH:MM:SS (with colons)."""
    ts = _parse_datetime("20250510;09:30:00", "")
    assert ts == dt.datetime(2025, 5, 10, 9, 30, 0, tzinfo=dt.UTC)


def test_parse_datetime_invalid_raises() -> None:
    with pytest.raises(ValueError):
        _parse_datetime("BADDATE", "BADTIME")


# ── deterministic exec_id ─────────────────────────────────────────────────────


def test_derive_exec_id_stable() -> None:
    id1 = _derive_exec_id("DU999", "AAPL", "BUY", "10", "150.00", "20250110", "10:00:00")
    id2 = _derive_exec_id("DU999", "AAPL", "BUY", "10", "150.00", "20250110", "10:00:00")
    assert id1 == id2


def test_derive_exec_id_different_for_different_trades() -> None:
    id1 = _derive_exec_id("DU999", "AAPL", "BUY", "10", "150.00", "20250110", "10:00:00")
    id2 = _derive_exec_id("DU999", "NVDA", "BUY", "10", "150.00", "20250110", "10:00:00")
    assert id1 != id2


def test_derive_exec_id_starts_with_flex() -> None:
    exec_id = _derive_exec_id("DU999", "AAPL", "BUY", "10", "150", "20250110", "10:00:00")
    assert exec_id.startswith("flex-")


# ── parse_flex_xml ────────────────────────────────────────────────────────────


def test_parse_single_buy() -> None:
    execs = parse_flex_xml(_SINGLE_BUY)
    assert len(execs) == 1
    ex = execs[0]
    assert ex.symbol == "AAPL"
    assert ex.side == "BUY"
    assert ex.quantity == pytest.approx(10.0)
    assert ex.price == pytest.approx(150.0)
    assert ex.currency == "USD"
    assert ex.account_id_ibkr == "DU123456"
    assert ex.exec_id == "flex-111001"


def test_parse_single_sell() -> None:
    execs = parse_flex_xml(_SINGLE_SELL)
    assert len(execs) == 1
    ex = execs[0]
    assert ex.symbol == "NVDA"
    assert ex.side == "SELL"
    assert ex.price == pytest.approx(350.0)


def test_parse_sell_quantity_positive() -> None:
    """SELL trades have negative quantity in IBKR XML; parser converts to positive."""
    execs = parse_flex_xml(_SINGLE_SELL)
    assert execs[0].quantity == pytest.approx(5.0)


def test_parse_commission_absolute_value() -> None:
    """Commission stored as positive even though IBKR reports it negative."""
    execs = parse_flex_xml(_SINGLE_BUY)
    assert execs[0].commission == pytest.approx(1.0)


def test_parse_multiple_trades_sorted() -> None:
    execs = parse_flex_xml(_MULTI_TRADE)
    assert len(execs) == 3
    # Sorted ascending by executed_at
    assert execs[0].symbol == "AAPL"  # Jan 10
    assert execs[1].symbol == "TSLA"  # Mar 5
    assert execs[2].symbol == "NVDA"  # Mar 15


def test_parse_error_xml_raises() -> None:
    with pytest.raises(ValueError, match="IBKR Flex error"):
        parse_flex_xml(_ERROR_XML)


def test_parse_malformed_xml_raises() -> None:
    with pytest.raises(ValueError, match="parse error"):
        parse_flex_xml("<not valid xml >>>")


def test_parse_deduplicates_same_trade_id() -> None:
    execs = parse_flex_xml(_DUPLICATE_TRADE_ID)
    assert len(execs) == 1


def test_parse_exec_id_uses_trade_id() -> None:
    execs = parse_flex_xml(_SINGLE_BUY)
    assert execs[0].exec_id == "flex-111001"


def test_parse_exec_id_prefers_ib_exec_id() -> None:
    """ibExecID takes priority over tradeID for exec_id."""
    execs = parse_flex_xml(_REAL_FORMAT)
    assert execs[0].exec_id == "flex-0001e621.aaaa.bbbb.0001"


def test_parse_real_format_datetime_attribute() -> None:
    """dateTime attribute with YYYYMMDD;HHMMSS parsed correctly."""
    execs = parse_flex_xml(_REAL_FORMAT)
    assert execs[0].executed_at == dt.datetime(2025, 5, 10, 9, 30, 0, tzinfo=dt.UTC)
    assert execs[1].executed_at == dt.datetime(2025, 5, 15, 14, 0, 0, tzinfo=dt.UTC)


def test_parse_real_format_sell_quantity_positive() -> None:
    """Real-world SELL with quantity='-10' → stored as 10.0."""
    execs = parse_flex_xml(_REAL_FORMAT)
    sell = next(e for e in execs if e.side == "SELL")
    assert sell.quantity == pytest.approx(10.0)


def test_parse_real_format_buy_and_sell_sides() -> None:
    execs = parse_flex_xml(_REAL_FORMAT)
    sides = {e.side for e in execs}
    assert sides == {"BUY", "SELL"}


def test_parse_symbol_uppercased() -> None:
    xml = _SINGLE_BUY.replace('symbol="AAPL"', 'symbol="aapl"')
    execs = parse_flex_xml(xml)
    assert execs[0].symbol == "AAPL"


def test_parse_raw_json_has_source_marker() -> None:
    execs = parse_flex_xml(_SINGLE_BUY, query_id_hash="abc123")
    assert execs[0].raw_json.get("source") == "IBKR_FLEX"
    assert execs[0].raw_json.get("imported_via") == "flex"
    assert execs[0].raw_json.get("flex_query_id_hash") == "abc123"


def test_parse_raw_json_includes_ib_exec_id() -> None:
    execs = parse_flex_xml(_REAL_FORMAT)
    assert execs[0].raw_json.get("ib_exec_id") == "0001e621.aaaa.bbbb.0001"


def test_parse_missing_required_fields_skipped() -> None:
    """Trade with missing quantity/price → skipped, rest parsed."""
    xml = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <FlexQueryResponse queryName="test" type="AF">
          <FlexStatements count="1">
            <FlexStatement accountId="DU123456">
              <Trades>
                <Trade tradeID="bad01" symbol="BAD" buySell="BUY"
                       quantity="" tradePrice="" currency="USD"
                       tradeDate="20250110" tradeTime="10:00:00" exchange="" orderReference=""/>
                <Trade tradeID="good01" symbol="AAPL" buySell="BUY"
                       quantity="10" tradePrice="150.00" currency="USD"
                       tradeDate="20250110" tradeTime="10:00:00" exchange="" orderReference=""/>
              </Trades>
            </FlexStatement>
          </FlexStatements>
        </FlexQueryResponse>
    """)
    execs = parse_flex_xml(xml)
    assert len(execs) == 1
    assert execs[0].symbol == "AAPL"


def test_parse_empty_trades_returns_empty() -> None:
    xml = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <FlexQueryResponse queryName="test" type="AF">
          <FlexStatements count="1">
            <FlexStatement accountId="DU123456">
              <Trades/>
            </FlexStatement>
          </FlexStatements>
        </FlexQueryResponse>
    """)
    execs = parse_flex_xml(xml)
    assert execs == []


def test_parse_flex_execution_is_schema() -> None:
    execs = parse_flex_xml(_SINGLE_BUY)
    assert all(isinstance(e, FlexExecution) for e in execs)
