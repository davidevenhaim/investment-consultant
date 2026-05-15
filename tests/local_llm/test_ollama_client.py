"""Tests for local_llm.ollama_client — no real network calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from local_llm.ollama_client import OllamaClient
from local_llm.schemas import OllamaConnectionError, OllamaMessage, OllamaParseError


def _mock_http_post(content: str) -> AsyncMock:
    """Build an httpx mock that returns valid Ollama chat structure."""
    resp = MagicMock()
    resp.json.return_value = {
        "model": "llama3.1:8b",
        "message": {"role": "assistant", "content": content},
        "done": True,
    }
    resp.raise_for_status = MagicMock()
    return AsyncMock(return_value=resp)


def _client() -> OllamaClient:
    return OllamaClient("http://localhost:11434", "llama3.1:8b", 60)


@pytest.mark.asyncio
async def test_chat_json_returns_parsed_dict() -> None:
    """Happy path: Ollama returns valid JSON content."""
    data = {"headline": "ok", "confidence": 0.8}
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = _mock_http_post(json.dumps(data))
        result = await _client().chat_json([OllamaMessage(role="user", content="analyze")])

    assert result == data


@pytest.mark.asyncio
async def test_chat_json_raises_connection_error_on_connect_fail() -> None:
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(OllamaConnectionError, match="Cannot connect"):
            await _client().chat_json([OllamaMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_json_raises_connection_error_on_timeout() -> None:
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ReadTimeout("timed out")
        )
        with pytest.raises(OllamaConnectionError, match="timed out"):
            await _client().chat_json([OllamaMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_json_raises_connection_error_on_http_status() -> None:
    resp = MagicMock()
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock(status_code=500))
    )
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=resp)
        with pytest.raises(OllamaConnectionError, match="HTTP 500"):
            await _client().chat_json([OllamaMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_json_raises_parse_error_on_invalid_json() -> None:
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = _mock_http_post("not {{ json")
        with pytest.raises(OllamaParseError, match="not valid JSON"):
            await _client().chat_json([OllamaMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_json_raises_parse_error_on_missing_message_key() -> None:
    resp = MagicMock()
    resp.json.return_value = {"model": "llama3.1:8b", "done": True}  # no "message" key
    resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=resp)
        with pytest.raises(OllamaParseError):
            await _client().chat_json([OllamaMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_json_sends_system_and_user_messages() -> None:
    """Verify both system and user messages are forwarded to Ollama."""
    captured: list[dict] = []

    async def fake_post(url: str, json: dict, **_) -> MagicMock:
        captured.append(json)
        resp = MagicMock()
        resp.json.return_value = {
            "message": {"role": "assistant", "content": '{"x": 1}'},
            "done": True,
        }
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = fake_post
        await _client().chat_json([
            OllamaMessage(role="system", content="be brief"),
            OllamaMessage(role="user", content="analyze"),
        ])

    assert len(captured) == 1
    msgs = captured[0]["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert captured[0]["format"] == "json"
    assert captured[0]["stream"] is False
