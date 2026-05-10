"""IBKR Flex Query diagnostics CLI — read-only, no order placement.

Tests the full Flex Query flow: request → poll → parse.
Token is never printed.

Usage:
    docker compose exec api python -m apps.cli.ibkr_flex_diagnostics

Output JSON:
    {
      "flex_enabled": true,
      "has_token": true,
      "has_query_id": true,
      "send_request_url_redacted": "https://.../SendRequest?t=[REDACTED]&...",
      "send_request_status": 200,
      "send_request_content_type": "text/xml",
      "send_request_response_length": 312,
      "send_request_preview": "<FlexStatementResponse>...",
      "request_ok": true,
      "reference_code_received": true,
      "get_statement_url_redacted": "https://.../GetStatement?t=[REDACTED]&...",
      "get_statement_status": 200,
      "get_statement_content_type": "text/xml",
      "get_statement_response_length": 467039,
      "xml_received": true,
      "xml_length": 467039,
      "parsed_executions": N,
      "first_execution_at": "...",
      "last_execution_at": "...",
      "sample_symbols": ["AAPL", "NVDA", ...],
      "error": null
    }
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any


async def _run_flex_diagnostics(token: str, query_id: str) -> dict[str, Any]:
    from broker.ibkr.flex_client import FlexClient
    from broker.ibkr.flex_parser import parse_flex_xml
    from core.config import get_settings

    cfg = get_settings()
    result: dict[str, Any] = {
        "flex_enabled": cfg.ibkr_flex_enabled,
        "has_token": bool(token.strip()),
        "has_query_id": bool(query_id.strip()),
        # SendRequest diagnostics
        "send_request_url_redacted": None,
        "send_request_status": None,
        "send_request_content_type": None,
        "send_request_response_length": None,
        "send_request_preview": None,
        "request_ok": False,
        "reference_code_received": False,
        # GetStatement diagnostics
        "get_statement_url_redacted": None,
        "get_statement_status": None,
        "get_statement_content_type": None,
        "get_statement_response_length": None,
        "xml_received": False,
        "xml_length": 0,
        # Parse results
        "parsed_executions": 0,
        "first_execution_at": None,
        "last_execution_at": None,
        "sample_symbols": [],
        "error": None,
    }

    if not token.strip() or not query_id.strip():
        result["error"] = (
            "Token or query_id missing. "
            "Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in environment."
        )
        return result

    flex_client = FlexClient.from_settings()

    try:
        send_result = await flex_client.request_statement(token, query_id)
        di = flex_client.debug_info
        result["send_request_url_redacted"] = di.send_request_url_redacted
        result["send_request_status"] = di.send_request_status
        result["send_request_content_type"] = di.send_request_content_type
        result["send_request_response_length"] = di.send_request_response_length
        result["send_request_preview"] = di.send_request_preview
        result["request_ok"] = True
        result["reference_code_received"] = bool(send_result.reference_code)
    except Exception as exc:  # noqa: BLE001
        di = flex_client.debug_info
        result["send_request_url_redacted"] = di.send_request_url_redacted
        result["send_request_status"] = di.send_request_status
        result["send_request_content_type"] = di.send_request_content_type
        result["send_request_response_length"] = di.send_request_response_length
        result["send_request_preview"] = di.send_request_preview
        result["error"] = f"SendRequest failed: {exc}"
        return result

    try:
        await asyncio.sleep(cfg.ibkr_flex_poll_interval_seconds)
        xml_text = await flex_client.poll_statement(
            token,
            send_result.reference_code,
            poll_url=send_result.get_statement_url,
        )
        di = flex_client.debug_info
        result["get_statement_url_redacted"] = di.get_statement_url_redacted
        result["get_statement_status"] = di.get_statement_status
        result["get_statement_content_type"] = di.get_statement_content_type
        result["get_statement_response_length"] = di.get_statement_response_length
        result["xml_received"] = True
        result["xml_length"] = len(xml_text)
    except Exception as exc:  # noqa: BLE001
        di = flex_client.debug_info
        result["get_statement_url_redacted"] = di.get_statement_url_redacted
        result["get_statement_status"] = di.get_statement_status
        result["get_statement_content_type"] = di.get_statement_content_type
        result["get_statement_response_length"] = di.get_statement_response_length
        result["error"] = f"GetStatement failed: {exc}"
        return result

    # Show XML structure for debugging before attempting full parse
    try:
        from xml.etree import ElementTree as ET  # noqa: PLC0415

        root_el = ET.fromstring(xml_text.strip())  # noqa: S314
        stmts = list(root_el.iter("FlexStatement"))
        trades = list(root_el.iter("Trade"))
        result["xml_root_tag"] = root_el.tag
        result["xml_flex_statement_count"] = len(stmts)
        result["xml_trade_element_count"] = len(trades)
        if trades:
            result["xml_first_trade_attributes"] = dict(trades[0].attrib)
        if stmts:
            result["xml_first_stmt_account"] = stmts[0].get("accountId")
    except Exception as exc:  # noqa: BLE001
        result["xml_structure_error"] = str(exc)

    try:
        execs = parse_flex_xml(xml_text, query_id_hash="diagnostics")
        result["parsed_executions"] = len(execs)
        if execs:
            result["first_execution_at"] = str(execs[0].executed_at)
            result["last_execution_at"] = str(execs[-1].executed_at)
            seen: list[str] = []
            for ex in execs:
                if ex.symbol not in seen:
                    seen.append(ex.symbol)
                if len(seen) >= 5:
                    break
            result["sample_symbols"] = seen
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"XML parse failed: {exc}"

    return result


def main() -> None:
    from core.config import get_settings

    cfg = get_settings()
    token = cfg.ibkr_flex_token
    query_id = cfg.ibkr_flex_query_id

    result = asyncio.run(_run_flex_diagnostics(token, query_id))
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("xml_received") else 1)


if __name__ == "__main__":
    main()
