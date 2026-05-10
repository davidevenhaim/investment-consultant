"""Normalize ib_insync execution objects to IBKRExecution Pydantic models."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from broker.ibkr.schemas import IBKRExecution


def _parse_side(side_str: str) -> str:
    """BOT / SLD → BUY / SELL."""
    s = side_str.upper().strip()
    if s in ("BOT", "BUY"):
        return "BUY"
    if s in ("SLD", "SELL"):
        return "SELL"
    raise ValueError(f"Unknown side: {side_str!r}")


def _to_raw(obj: Any) -> dict[str, object]:
    try:
        result: dict[str, object] = json.loads(json.dumps(obj, default=str))
        return result
    except Exception:
        return {}


def map_execution(exec_obj: Any, account_id: str) -> IBKRExecution:
    """Map an ib_insync Execution + Fill → IBKRExecution."""
    raw = _to_raw(vars(exec_obj) if hasattr(exec_obj, "__dict__") else exec_obj)

    # ib_insync Execution fields
    exec_id: str = str(exec_obj.execId)
    symbol: str = (
        str(exec_obj.contract.symbol) if hasattr(exec_obj, "contract")
        else str(raw.get("symbol", ""))
    )
    exchange: str | None = (
        str(exec_obj.exchange) if hasattr(exec_obj, "exchange") and exec_obj.exchange else None
    )
    side = _parse_side(str(exec_obj.side))
    quantity = float(exec_obj.shares)
    price = float(exec_obj.price)
    commission: float | None = (
        float(exec_obj.commission) if hasattr(exec_obj, "commission") else None
    )

    # Parse datetime from "YYYYMMDD  HH:MM:SS" format
    time_str: str = str(exec_obj.time)
    try:
        executed_at = dt.datetime.strptime(time_str.strip(), "%Y%m%d  %H:%M:%S").replace(
            tzinfo=dt.UTC
        )
    except ValueError:
        executed_at = dt.datetime.fromisoformat(time_str).replace(tzinfo=dt.UTC)

    order_ref: str | None = (
        str(exec_obj.orderRef)
        if hasattr(exec_obj, "orderRef") and exec_obj.orderRef
        else None
    )
    currency: str = (
        str(exec_obj.currency) if hasattr(exec_obj, "currency") and exec_obj.currency else "USD"
    )

    return IBKRExecution(
        exec_id=exec_id,
        account_id_ibkr=account_id,
        symbol=symbol,
        exchange=exchange,
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        price=price,
        commission=commission,
        currency=currency,
        executed_at=executed_at,
        order_ref=order_ref,
        raw_json=raw,
    )
