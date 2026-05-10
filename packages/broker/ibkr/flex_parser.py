"""Parse IBKR Flex Query XML into normalized FlexExecution records.

IBKR Flex XML structure (relevant fragment):
    <FlexQueryResponse queryName="..." type="...">
      <FlexStatements>
        <FlexStatement accountId="DU123456" ...>
          <Trades>
            <Trade ibExecID="..." tradeID="..." symbol="AAPL"
                   buySell="BUY" quantity="10" tradePrice="150.00"
                   ibCommission="-1.00" currency="USD"
                   dateTime="20250110;10:00:00"
                   tradeDate="20250110" tradeTime="10:00:00"
                   exchange="NASDAQ" orderReference="" ... />
          </Trades>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>

Fields vary by query config. Parser is defensive — missing fields get defaults.
exec_id priority: ibExecID > tradeID > transactionID > deterministic hash.
quantity is always stored positive; side is taken from buySell attribute.
Never persist the full raw XML. Only store a safe subset in raw_json.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from xml.etree import ElementTree as ET

from broker.ibkr.flex_schemas import FlexExecution

logger = logging.getLogger(__name__)

# IBKR date/time formats used in Flex XML
_DATE_FMT = "%Y%m%d"
_TIME_FMT = "%H:%M:%S"
_DATETIME_FMT = "%Y%m%d %H:%M:%S"
_DATETIME_FMT2 = "%Y-%m-%d"
# dateTime attribute: IBKR uses semicolon + no-colon time: "20250613;111628"
_DATETIME_SEMICOLON_FMT = "%Y%m%d;%H%M%S"
# Some IBKR configs include colons: "20250613;11:16:28"
_DATETIME_SEMICOLON_COLON_FMT = "%Y%m%d;%H:%M:%S"


def _parse_side(val: str) -> str:
    """BUY / SELL / BOT / SLD → canonical BUY / SELL."""
    s = val.strip().upper()
    if s in ("BUY", "BOT"):
        return "BUY"
    if s in ("SELL", "SLD"):
        return "SELL"
    raise ValueError(f"Unrecognised Flex buySell value: {val!r}")


def _parse_datetime(trade_date: str, trade_time: str) -> dt.datetime:
    """Combine IBKR tradeDate + tradeTime into an aware UTC datetime.

    Also accepts the dateTime attribute ("20250110;10:00:00") passed as trade_date
    with trade_time left empty.
    """
    date_raw = trade_date.strip()
    time_raw = trade_time.strip()

    # dateTime attribute: "YYYYMMDD;HHMMSS" (real IBKR) or "YYYYMMDD;HH:MM:SS" (some configs)
    if ";" in date_raw:
        for semicolon_fmt in (_DATETIME_SEMICOLON_FMT, _DATETIME_SEMICOLON_COLON_FMT):
            try:
                return dt.datetime.strptime(date_raw, semicolon_fmt).replace(tzinfo=dt.UTC)
            except ValueError:
                pass

    combined = f"{date_raw} {time_raw}"
    # "YYYYMMDD HH:MM:SS"
    try:
        return dt.datetime.strptime(combined, _DATETIME_FMT).replace(tzinfo=dt.UTC)
    except ValueError:
        pass
    # "YYYY-MM-DD HH:MM:SS"
    try:
        return dt.datetime.strptime(combined, f"{_DATETIME_FMT2} {_TIME_FMT}").replace(
            tzinfo=dt.UTC
        )
    except ValueError:
        pass
    # date only (midnight UTC)
    try:
        return dt.datetime.strptime(date_raw, _DATE_FMT).replace(tzinfo=dt.UTC)
    except ValueError:
        pass
    raise ValueError(f"Cannot parse Flex date/time: {trade_date!r} {trade_time!r}")


def _derive_exec_id(
    account_id: str,
    symbol: str,
    side: str,
    quantity: str,
    price: str,
    date_str: str,
    time_str: str,
    source: str = "IBKR_FLEX",
) -> str:
    """Generate a deterministic exec_id when no IBKR-provided ID is available."""
    raw = f"{source}|{account_id}|{symbol}|{side}|{quantity}|{price}|{date_str}|{time_str}"
    return "flex-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _safe_float(val: str | None, name: str) -> float | None:
    """Parse float; return None on missing/blank/zero-placeholder."""
    if not val or val.strip() in ("", "--", "N/A"):
        return None
    try:
        return float(val)
    except ValueError:
        logger.debug("flex_float_parse_failed", extra={"field": name, "value": val})
        return None


def _safe_positive_float(val: str | None, name: str) -> float | None:
    result = _safe_float(val, name)
    if result is not None and result <= 0:
        return None
    return result


def _parse_trade_element(
    elem: ET.Element, account_id: str, query_id_hash: str
) -> FlexExecution | None:
    """Parse a single <Trade> element. Returns None if required fields are missing."""
    get = elem.get

    symbol = (get("symbol") or "").strip().upper()
    if not symbol:
        logger.debug("flex_trade_no_symbol", extra={"attribs": list(elem.keys())[:5]})
        return None

    buy_sell_raw = get("buySell") or get("openCloseIndicator") or ""
    try:
        side = _parse_side(buy_sell_raw)
    except ValueError as exc:
        logger.debug("flex_trade_bad_side", extra={"error": str(exc), "symbol": symbol})
        return None

    qty_str = get("quantity") or get("shares") or ""
    price_str = get("tradePrice") or get("price") or ""
    # Use abs(qty) — IBKR reports SELL quantity as negative; side comes from buySell
    qty_raw = _safe_float(qty_str, "quantity")
    qty = abs(qty_raw) if qty_raw is not None and qty_raw != 0 else None
    price = _safe_positive_float(price_str, "tradePrice")
    if qty is None or price is None:
        logger.debug(
            "flex_trade_bad_qty_price",
            extra={"symbol": symbol, "qty": qty_str, "price": price_str},
        )
        return None

    # Prefer dateTime attribute ("YYYYMMDD;HH:MM:SS") over separate tradeDate/tradeTime
    date_time_attr = get("dateTime") or ""
    if date_time_attr.strip():
        trade_date = date_time_attr.strip()
        trade_time = ""
    else:
        trade_date = get("tradeDate") or get("settleDate") or ""
        trade_time = get("tradeTime") or "00:00:00"
    try:
        executed_at = _parse_datetime(trade_date, trade_time)
    except ValueError as exc:
        logger.debug("flex_trade_bad_datetime", extra={"error": str(exc), "symbol": symbol})
        return None

    # exec_id priority: ibExecID > tradeID > transactionID > deterministic hash
    ib_exec_id = (get("ibExecID") or "").strip()
    trade_id = (get("tradeID") or get("transactionID") or "").strip()
    if ib_exec_id:
        exec_id = f"flex-{ib_exec_id}"
    elif trade_id:
        exec_id = f"flex-{trade_id}"
    else:
        exec_id = _derive_exec_id(
            account_id, symbol, side, qty_str, price_str, trade_date, trade_time
        )

    commission_str = get("ibCommission") or get("commission") or ""
    commission_val = _safe_float(commission_str, "ibCommission")
    # IBKR reports commission as negative — store as positive
    if commission_val is not None:
        commission_val = abs(commission_val)

    currency = (get("currency") or "USD").strip().upper()
    exchange = (get("exchange") or "").strip() or None
    order_ref = (get("orderReference") or get("orderRef") or "").strip() or None

    # Safe raw_json — no credentials, no full XML, no tokens
    raw: dict[str, object] = {
        "source": "IBKR_FLEX",
        "flex_query_id_hash": query_id_hash,
        "imported_via": "flex",
        "ib_exec_id": ib_exec_id or None,
        "trade_id": trade_id or None,
        "exchange": exchange,
        "order_ref": order_ref,
    }

    return FlexExecution(
        exec_id=exec_id,
        account_id_ibkr=account_id,
        symbol=symbol,
        exchange=exchange,
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        price=price,
        commission=commission_val,
        currency=currency,
        executed_at=executed_at,
        order_ref=order_ref,
        raw_json=raw,
    )


def parse_flex_xml(xml_text: str, query_id_hash: str = "") -> list[FlexExecution]:
    """Parse IBKR Flex XML → list of FlexExecution records.

    Raises ValueError if XML is malformed or contains an IBKR error.
    Returns empty list if no Trade elements found.
    """
    try:
        root = ET.fromstring(xml_text.strip())  # noqa: S314
    except ET.ParseError as exc:
        raise ValueError(f"Flex XML parse error: {exc}") from exc

    # IBKR returns error responses in the same XML envelope
    # <FlexQueryResponse ...><Error>...</Error></FlexQueryResponse>
    error_el = root.find(".//Error")
    if error_el is not None and error_el.text:
        raise ValueError(f"IBKR Flex error: {error_el.text.strip()}")

    executions: list[FlexExecution] = []
    seen_ids: set[str] = set()
    parse_errors = 0

    for stmt in root.iter("FlexStatement"):
        account_id = stmt.get("accountId") or ""
        # Trades can be nested under <Trades> or directly under <FlexStatement>
        for trade in stmt.iter("Trade"):
            ex = _parse_trade_element(trade, account_id, query_id_hash)
            if ex is None:
                parse_errors += 1
                continue
            if ex.exec_id in seen_ids:
                continue
            seen_ids.add(ex.exec_id)
            executions.append(ex)

    executions.sort(key=lambda e: e.executed_at)
    logger.info(
        "flex_xml_parsed",
        extra={
            "total_parsed": len(executions),
            "parse_errors": parse_errors,
            "accounts": list({e.account_id_ibkr for e in executions}),
        },
    )
    return executions
