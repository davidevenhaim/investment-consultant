"""IBKR Flex Query Web Service client — read-only, no order placement.

IBKR Flex Query flow:
  1. GET {base_url}/SendRequest?t=token&q=queryId&v=3
     → returns <ReferenceCode> and <Url> for polling
  2. GET {Url}?t=token&q=referenceCode&v=3 (poll until XML ready)
  3. Parse the XML into trade records

base_url must be the service root (no path suffix), e.g.:
    https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService

Token and query ID are secrets — never logged raw.
All network calls via httpx.AsyncClient with timeout.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from core.errors import IBKRFlexError

logger = logging.getLogger(__name__)

# IBKR Flex response status codes (returned in the XML body)
_FLEX_STATUS_QUEUED = "1003"
_FLEX_STATUS_GENERATING = "1004"


def _hash_token(token: str) -> str:
    """Safe one-way hash for logging — never log the raw token."""
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def _redact_token(text: str, token: str) -> str:
    """Replace literal token in text with [REDACTED] for safe logging."""
    if not token:
        return text
    return text.replace(token, "[REDACTED]")


def _redact_url(url: str, token: str) -> str:
    """Remove token query param value from URL string for safe logging."""
    return _redact_token(url, token)


@dataclass
class FlexSendResult:
    """Typed result from SendRequest: reference code + the URL to poll."""

    reference_code: str
    get_statement_url: str


@dataclass
class FlexDebugInfo:
    """Diagnostic fields populated during FlexClient calls. Never contains raw token."""

    send_request_url_redacted: str = ""
    send_request_status: int = 0
    send_request_content_type: str = ""
    send_request_response_length: int = 0
    send_request_preview: str = ""
    get_statement_url_redacted: str = ""
    get_statement_status: int = 0
    get_statement_content_type: str = ""
    get_statement_response_length: int = 0
    get_statement_preview: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _parse_send_response(xml_text: str, fallback_poll_url: str = "") -> FlexSendResult:
    """Extract reference code and poll URL from SendRequest response XML.

    Expected:
        <FlexStatementResponse>
          <Status>Success</Status>
          <ReferenceCode>1234567890</ReferenceCode>
          <Url>https://gdcdyn.interactivebrokers.com/.../GetStatement</Url>
        </FlexStatementResponse>
    """
    text = xml_text.strip()
    if not text:
        raise IBKRFlexError("SendRequest returned an empty response body")

    try:
        root = ET.fromstring(text)  # noqa: S314
    except ET.ParseError as exc:
        raise IBKRFlexError(f"SendRequest XML parse error: {exc}") from exc

    status_el = root.find("Status")
    if status_el is not None and status_el.text and status_el.text.strip() != "Success":
        err_msg_el = root.find("ErrorMessage")
        msg = err_msg_el.text.strip() if err_msg_el is not None and err_msg_el.text else "unknown"
        raise IBKRFlexError(f"SendRequest failed: status={status_el.text!r} — {msg}")

    ref_el = root.find("ReferenceCode")
    if ref_el is None or not ref_el.text:
        raise IBKRFlexError("SendRequest response missing ReferenceCode")

    ref_code = ref_el.text.strip()

    url_el = root.find("Url")
    if url_el is not None and url_el.text and url_el.text.strip():
        poll_url = url_el.text.strip()
    else:
        poll_url = fallback_poll_url

    return FlexSendResult(reference_code=ref_code, get_statement_url=poll_url)


def _parse_poll_response(xml_text: str) -> tuple[bool, str]:
    """Check if a GetStatement response is ready or still pending.

    Returns (is_ready, xml_text_or_status_code).
    """
    stripped = xml_text.strip()
    if not stripped:
        return False, stripped

    try:
        root = ET.fromstring(stripped)  # noqa: S314
    except ET.ParseError:
        # Raw text errors sometimes returned by IBKR
        return False, stripped

    # Status XML: <FlexStatementResponse> with <ErrorCode> and optional <ErrorMessage>
    error_code_el = root.find("ErrorCode")
    if error_code_el is not None and error_code_el.text:
        code = error_code_el.text.strip()
        if code in (_FLEX_STATUS_QUEUED, _FLEX_STATUS_GENERATING):
            return False, code
        err_msg_el = root.find("ErrorMessage")
        msg = err_msg_el.text.strip() if err_msg_el is not None and err_msg_el.text else code
        raise IBKRFlexError(f"Flex GetStatement error {code}: {msg}")

    if root.tag == "FlexQueryResponse":
        return True, stripped

    return False, stripped


class FlexClient:
    """Async IBKR Flex Query client. All methods are read-only.

    base_url must be the service root without a trailing path, e.g.:
        https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService

    The client derives:
        send_url  = base_url + "/SendRequest"
        poll_url  = poll_url arg, or base_url + "/GetStatement" as fallback
    """

    def __init__(
        self,
        base_url: str,
        poll_url: str = "",
        timeout_seconds: int = 60,
        max_polls: int = 10,
        poll_interval_seconds: int = 3,
    ) -> None:
        root = base_url.strip().rstrip("/")
        self._base_url = root
        self._send_url = f"{root}/SendRequest"
        # Fallback poll URL when SendRequest response does not include <Url>
        stripped_poll = poll_url.strip()
        self._poll_url = stripped_poll.rstrip("/") if stripped_poll else f"{root}/GetStatement"
        self._timeout = timeout_seconds
        self._max_polls = max_polls
        self._poll_interval = poll_interval_seconds
        self.debug_info = FlexDebugInfo()

    async def request_statement(self, token: str, query_id: str) -> FlexSendResult:
        """Send Flex query request. Returns FlexSendResult. Token never logged."""
        token = token.strip()
        query_id = query_id.strip()
        token_hint = _hash_token(token)

        # Build full URL for logging (params added by httpx)
        self.debug_info.send_request_url_redacted = _redact_url(
            f"{self._send_url}?t={token}&q={query_id}&v=3", token
        )

        logger.info(
            "flex_send_request",
            extra={
                "send_url": self._send_url,
                "query_id": query_id,
                "token_hint": token_hint,
            },
        )
        params = {"t": token, "q": query_id, "v": "3"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(self._send_url, params=params)
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise IBKRFlexError(
                f"Flex SendRequest timed out after {self._timeout}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise IBKRFlexError(
                f"Flex SendRequest HTTP error {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise IBKRFlexError(f"Flex SendRequest network error: {exc}") from exc

        ct = resp.headers.get("content-type", "")
        body = resp.text
        self.debug_info.send_request_status = resp.status_code
        self.debug_info.send_request_content_type = ct
        self.debug_info.send_request_response_length = len(body)
        self.debug_info.send_request_preview = _redact_token(body[:500], token)

        logger.debug(
            "flex_send_response",
            extra={
                "status_code": resp.status_code,
                "content_type": ct,
                "response_length": len(body),
                "body_preview": _redact_token(body[:500], token),
            },
        )

        if not body.strip():
            raise IBKRFlexError(
                f"Flex SendRequest returned empty body "
                f"(status={resp.status_code}, content-type={ct!r}, "
                f"url={_redact_token(str(resp.url), token)!r})"
            )

        result = _parse_send_response(body, fallback_poll_url=self._poll_url)
        logger.info(
            "flex_reference_code_received",
            extra={
                "ref_code": result.reference_code,
                "get_statement_url": result.get_statement_url,
                "token_hint": token_hint,
            },
        )
        return result

    async def poll_statement(
        self,
        token: str,
        reference_code: str,
        poll_url: str | None = None,
    ) -> str:
        """Poll until statement XML is ready. Returns raw XML. Token never logged."""
        token = token.strip()
        token_hint = _hash_token(token)
        url = (poll_url or self._poll_url).strip().rstrip("/")
        params = {"t": token, "q": reference_code.strip(), "v": "3"}

        self.debug_info.get_statement_url_redacted = _redact_url(
            f"{url}?t={token}&q={reference_code}&v=3", token
        )

        for attempt in range(1, self._max_polls + 1):
            logger.debug(
                "flex_poll_attempt",
                extra={
                    "attempt": attempt,
                    "max": self._max_polls,
                    "ref_code": reference_code,
                    "token_hint": token_hint,
                    "poll_url": url,
                },
            )
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise IBKRFlexError(
                    f"Flex GetStatement timed out after {self._timeout}s"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise IBKRFlexError(
                    f"Flex GetStatement HTTP error {exc.response.status_code}"
                ) from exc
            except httpx.RequestError as exc:
                raise IBKRFlexError(f"Flex GetStatement network error: {exc}") from exc

            ct = resp.headers.get("content-type", "")
            body = resp.text
            self.debug_info.get_statement_status = resp.status_code
            self.debug_info.get_statement_content_type = ct
            self.debug_info.get_statement_response_length = len(body)
            self.debug_info.get_statement_preview = _redact_token(body[:500], token)

            logger.debug(
                "flex_poll_response",
                extra={
                    "attempt": attempt,
                    "status_code": resp.status_code,
                    "content_type": ct,
                    "response_length": len(body),
                    "body_preview": _redact_token(body[:500], token),
                },
            )

            is_ready, payload = _parse_poll_response(body)
            if is_ready:
                logger.info(
                    "flex_statement_ready",
                    extra={
                        "attempt": attempt,
                        "ref_code": reference_code,
                        "xml_length": len(payload),
                    },
                )
                return payload

            if attempt < self._max_polls:
                await asyncio.sleep(self._poll_interval)

        raise IBKRFlexError(
            f"Flex statement not ready after {self._max_polls} polls "
            f"(ref={reference_code})"
        )

    async def fetch_statement(self, token: str, query_id: str) -> str:
        """Full flow: request → poll → return XML. Token never logged."""
        send_result = await self.request_statement(token, query_id)
        # Brief pause before first poll — IBKR needs time to queue the request
        await asyncio.sleep(self._poll_interval)
        return await self.poll_statement(
            token,
            send_result.reference_code,
            poll_url=send_result.get_statement_url,
        )

    @classmethod
    def from_settings(cls) -> FlexClient:
        from core.config import get_settings  # noqa: PLC0415

        cfg = get_settings()
        base = cfg.ibkr_flex_base_url.strip().rstrip("/")
        # If poll_url not explicitly configured, derive from base (client will append /GetStatement)
        poll = cfg.ibkr_flex_poll_url.strip()
        return cls(
            base_url=base,
            poll_url=poll,
            timeout_seconds=cfg.ibkr_flex_timeout_seconds,
            max_polls=cfg.ibkr_flex_max_polls,
            poll_interval_seconds=cfg.ibkr_flex_poll_interval_seconds,
        )
