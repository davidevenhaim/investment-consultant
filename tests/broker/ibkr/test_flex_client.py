"""Tests for IBKR Flex Query HTTP client."""

from __future__ import annotations

import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from broker.ibkr.flex_client import (
    FlexClient,
    FlexSendResult,
    _hash_token,
    _parse_poll_response,
    _parse_send_response,
)
from core.errors import IBKRFlexError

# base_url is the service ROOT — client appends /SendRequest and /GetStatement
_BASE = "https://flex.test"


def _make_client(
    max_polls: int = 3,
    poll_interval: int = 0,
) -> FlexClient:
    return FlexClient(
        base_url=_BASE,
        poll_url="",  # derived from base_url
        timeout_seconds=5,
        max_polls=max_polls,
        poll_interval_seconds=poll_interval,
    )


# ── token hashing ─────────────────────────────────────────────────────────────


def test_hash_token_does_not_return_token() -> None:
    token = "supersecrettoken12345"
    hashed = _hash_token(token)
    assert token not in hashed
    assert len(hashed) == 12


def test_hash_token_stable() -> None:
    assert _hash_token("abc") == _hash_token("abc")


# ── parse_send_response ───────────────────────────────────────────────────────


def test_parse_send_response_success() -> None:
    xml = textwrap.dedent("""\
        <FlexStatementResponse>
          <Status>Success</Status>
          <ReferenceCode>9876543210</ReferenceCode>
        </FlexStatementResponse>
    """)
    result = _parse_send_response(xml, fallback_poll_url="https://fallback/GetStatement")
    assert result.reference_code == "9876543210"
    assert result.get_statement_url == "https://fallback/GetStatement"


def test_parse_send_response_extracts_url() -> None:
    xml = textwrap.dedent("""\
        <FlexStatementResponse>
          <Status>Success</Status>
          <ReferenceCode>3998160486</ReferenceCode>
          <Url>https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>
        </FlexStatementResponse>
    """)
    result = _parse_send_response(xml, fallback_poll_url="https://fallback/GetStatement")
    assert result.reference_code == "3998160486"
    assert "gdcdyn" in result.get_statement_url
    assert "fallback" not in result.get_statement_url


def test_parse_send_response_returns_flex_send_result() -> None:
    xml = textwrap.dedent("""\
        <FlexStatementResponse>
          <Status>Success</Status>
          <ReferenceCode>1234</ReferenceCode>
          <Url>https://ibkr.test/GetStatement</Url>
        </FlexStatementResponse>
    """)
    result = _parse_send_response(xml)
    assert isinstance(result, FlexSendResult)


def test_parse_send_response_failure_raises() -> None:
    xml = textwrap.dedent("""\
        <FlexStatementResponse>
          <Status>Fail</Status>
          <ErrorMessage>Invalid token</ErrorMessage>
        </FlexStatementResponse>
    """)
    with pytest.raises(IBKRFlexError, match="Invalid token"):
        _parse_send_response(xml)


def test_parse_send_response_no_ref_code_raises() -> None:
    xml = "<FlexStatementResponse><Status>Success</Status></FlexStatementResponse>"
    with pytest.raises(IBKRFlexError, match="ReferenceCode"):
        _parse_send_response(xml)


def test_parse_send_response_malformed_xml_raises() -> None:
    with pytest.raises(IBKRFlexError, match="parse error"):
        _parse_send_response("<broken>>")


# ── parse_poll_response ───────────────────────────────────────────────────────


def test_parse_poll_response_queued_returns_not_ready() -> None:
    xml = textwrap.dedent("""\
        <FlexStatementResponse>
          <ErrorCode>1003</ErrorCode>
          <ErrorMessage>Statement is in queue</ErrorMessage>
        </FlexStatementResponse>
    """)
    is_ready, code = _parse_poll_response(xml)
    assert not is_ready
    assert code == "1003"


def test_parse_poll_response_generating_returns_not_ready() -> None:
    xml = textwrap.dedent("""\
        <FlexStatementResponse>
          <ErrorCode>1004</ErrorCode>
          <ErrorMessage>Statement is being generated</ErrorMessage>
        </FlexStatementResponse>
    """)
    is_ready, _ = _parse_poll_response(xml)
    assert not is_ready


def test_parse_poll_response_ready_when_flex_query_response() -> None:
    xml = textwrap.dedent("""\
        <?xml version="1.0"?>
        <FlexQueryResponse queryName="test" type="AF">
          <FlexStatements count="0"/>
        </FlexQueryResponse>
    """)
    is_ready, payload = _parse_poll_response(xml)
    assert is_ready
    assert "FlexQueryResponse" in payload


def test_parse_poll_response_error_code_raises() -> None:
    xml = textwrap.dedent("""\
        <FlexStatementResponse>
          <ErrorCode>9999</ErrorCode>
          <ErrorMessage>Unknown error occurred</ErrorMessage>
        </FlexStatementResponse>
    """)
    with pytest.raises(IBKRFlexError, match="Unknown error"):
        _parse_poll_response(xml)


# ── FlexClient.request_statement ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_statement_success() -> None:
    client = _make_client()
    xml_response = textwrap.dedent("""\
        <FlexStatementResponse>
          <Status>Success</Status>
          <ReferenceCode>1234567890</ReferenceCode>
          <Url>https://gdcdyn.test/GetStatement</Url>
        </FlexStatementResponse>
    """)

    mock_resp = MagicMock()
    mock_resp.text = xml_response
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/xml"}
    mock_resp.raise_for_status = MagicMock()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await client.request_statement("tok", "qid")

    assert isinstance(result, FlexSendResult)
    assert result.reference_code == "1234567890"
    assert "gdcdyn.test" in result.get_statement_url


@pytest.mark.asyncio
async def test_request_statement_logs_redacted_token(caplog: pytest.LogCaptureFixture) -> None:
    client = _make_client()
    raw_token = "super-secret-flex-token"
    xml_response = textwrap.dedent(f"""\
        <FlexStatementResponse>
          <Status>Success</Status>
          <ReferenceCode>1234567890</ReferenceCode>
          <Url>https://gdcdyn.test/GetStatement?t={raw_token}&amp;q=1234567890&amp;v=3</Url>
        </FlexStatementResponse>
    """)

    mock_resp = MagicMock()
    mock_resp.text = xml_response
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/xml"}
    mock_resp.raise_for_status = MagicMock()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with caplog.at_level("INFO", logger="broker.ibkr.flex_client"):
            await client.request_statement(raw_token, "qid")

    assert raw_token not in caplog.text
    urls = [
        getattr(record, "get_statement_url", "")
        for record in caplog.records
        if hasattr(record, "get_statement_url")
    ]
    assert any("[REDACTED]" in url for url in urls)
    assert all(raw_token not in url for url in urls)
    assert raw_token not in client.debug_info.send_request_url_redacted


@pytest.mark.asyncio
async def test_request_statement_uses_fallback_url_when_no_url_in_xml() -> None:
    client = _make_client()
    xml_response = textwrap.dedent("""\
        <FlexStatementResponse>
          <Status>Success</Status>
          <ReferenceCode>999</ReferenceCode>
        </FlexStatementResponse>
    """)

    mock_resp = MagicMock()
    mock_resp.text = xml_response
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/xml"}
    mock_resp.raise_for_status = MagicMock()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await client.request_statement("tok", "qid")

    # Fallback URL is base_url + "/GetStatement" when <Url> absent from response
    assert result.get_statement_url == f"{_BASE}/GetStatement"


@pytest.mark.asyncio
async def test_request_statement_http_error_raises_flex_error() -> None:
    import httpx

    client = _make_client()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock(status_code=403)
            )
        )
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(IBKRFlexError, match="HTTP error 403"):
            await client.request_statement("tok", "qid")


@pytest.mark.asyncio
async def test_request_statement_timeout_raises_flex_error() -> None:
    import httpx

    client = _make_client()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(IBKRFlexError, match="timed out"):
            await client.request_statement("tok", "qid")


# ── FlexClient.poll_statement ─────────────────────────────────────────────────


_READY_XML = textwrap.dedent("""\
    <?xml version="1.0"?>
    <FlexQueryResponse queryName="test" type="AF">
      <FlexStatements count="0"/>
    </FlexQueryResponse>
""")

_QUEUED_XML = textwrap.dedent("""\
    <FlexStatementResponse>
      <ErrorCode>1003</ErrorCode>
      <ErrorMessage>Statement is queued</ErrorMessage>
    </FlexStatementResponse>
""")


@pytest.mark.asyncio
async def test_poll_statement_ready_on_first_attempt() -> None:
    client = _make_client()

    mock_resp = MagicMock()
    mock_resp.text = _READY_XML
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/xml"}
    mock_resp.raise_for_status = MagicMock()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await client.poll_statement("tok", "refcode")

    assert "FlexQueryResponse" in result


@pytest.mark.asyncio
async def test_poll_statement_uses_provided_url() -> None:
    client = _make_client()
    custom_url = "https://custom.ibkr.test/GetStatement"

    mock_resp = MagicMock()
    mock_resp.text = _READY_XML
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/xml"}
    mock_resp.raise_for_status = MagicMock()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await client.poll_statement("tok", "refcode", poll_url=custom_url)

    call_url = mock_ctx.get.call_args[0][0]
    assert custom_url in call_url or call_url == custom_url


@pytest.mark.asyncio
async def test_poll_statement_queued_then_ready() -> None:
    client = _make_client(max_polls=3, poll_interval=0)

    queued_resp = MagicMock()
    queued_resp.text = _QUEUED_XML
    queued_resp.status_code = 200
    queued_resp.headers = {"content-type": "text/xml"}
    queued_resp.raise_for_status = MagicMock()

    ready_resp = MagicMock()
    ready_resp.text = _READY_XML
    ready_resp.status_code = 200
    ready_resp.headers = {"content-type": "text/xml"}
    ready_resp.raise_for_status = MagicMock()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(side_effect=[queued_resp, ready_resp])
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("broker.ibkr.flex_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.poll_statement("tok", "refcode")

    assert "FlexQueryResponse" in result


@pytest.mark.asyncio
async def test_poll_statement_max_polls_raises() -> None:
    client = _make_client(max_polls=2, poll_interval=0)

    queued_resp = MagicMock()
    queued_resp.text = _QUEUED_XML
    queued_resp.status_code = 200
    queued_resp.headers = {"content-type": "text/xml"}
    queued_resp.raise_for_status = MagicMock()

    with patch("broker.ibkr.flex_client.httpx.AsyncClient") as mock_client_cls:
        mock_ctx = AsyncMock()
        mock_ctx.get = AsyncMock(return_value=queued_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("broker.ibkr.flex_client.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(IBKRFlexError, match="not ready after"),
        ):
            await client.poll_statement("tok", "refcode")
