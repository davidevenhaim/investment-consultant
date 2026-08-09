"""Tests for OllamaLLMClient (research-graph local model adapter)."""

import json

import pytest
from ai.ollama_llm_client import OllamaLLMClient
from ai.service import run_social_llm_analysis
from core.errors import LLMError
from local_llm.schemas import OllamaConnectionError, OllamaParseError


def _client(max_retries: int = 0) -> OllamaLLMClient:
    return OllamaLLMClient(
        base_url="http://localhost:11434",
        model="qwen3:32b",
        timeout_seconds=5,
        max_retries=max_retries,
    )


@pytest.mark.asyncio
async def test_complete_returns_json_string(monkeypatch) -> None:
    captured: dict = {}

    async def fake_chat_json(self, messages, think=None):
        captured["think"] = think
        captured["roles"] = [m.role for m in messages]
        return {"symbol": "AAPL", "overall_sentiment": "BULLISH"}

    monkeypatch.setattr(
        "local_llm.ollama_client.OllamaClient.chat_json", fake_chat_json
    )

    raw = await _client().complete("prompt text")
    assert json.loads(raw) == {"symbol": "AAPL", "overall_sentiment": "BULLISH"}
    assert captured["think"] is False, "qwen3 thinking must be disabled with format=json"
    assert captured["roles"] == ["system", "user"]


@pytest.mark.asyncio
async def test_connection_error_raises_llm_error(monkeypatch) -> None:
    async def fail(self, messages, think=None):
        raise OllamaConnectionError("Cannot connect")

    monkeypatch.setattr("local_llm.ollama_client.OllamaClient.chat_json", fail)

    with pytest.raises(LLMError):
        await _client().complete("prompt")


@pytest.mark.asyncio
async def test_parse_error_raises_llm_error(monkeypatch) -> None:
    async def fail(self, messages, think=None):
        raise OllamaParseError("not JSON")

    monkeypatch.setattr("local_llm.ollama_client.OllamaClient.chat_json", fail)

    with pytest.raises(LLMError):
        await _client().complete("prompt")


@pytest.mark.asyncio
async def test_retry_then_success(monkeypatch) -> None:
    calls = {"n": 0}

    async def flaky(self, messages, think=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OllamaConnectionError("first attempt fails")
        return {"ok": True}

    monkeypatch.setattr("local_llm.ollama_client.OllamaClient.chat_json", flaky)

    raw = await _client(max_retries=1).complete("prompt")
    assert json.loads(raw) == {"ok": True}
    assert calls["n"] == 2


# ── run_social_llm_analysis via OllamaLLMClient path ─────────────────────────


def _valid_social_payload() -> dict:
    return {
        "symbol": "AAPL",
        "overall_sentiment": "MIXED",
        "key_themes": ["earnings", "china"],
        "hype_or_manipulation_flags": [],
        "risk_flags": ["china demand"],
        "divergence_from_news": "",
        "should_reduce_confidence": False,
        "confidence_penalty": 0.0,
        "confidence": 0.7,
    }


@pytest.mark.asyncio
async def test_social_analysis_valid_payload(monkeypatch) -> None:
    async def ok(self, messages, think=None):
        return _valid_social_payload()

    monkeypatch.setattr("local_llm.ollama_client.OllamaClient.chat_json", ok)

    analysis, warnings = await run_social_llm_analysis(
        "AAPL", "prompt", _client(), "qwen3:32b"
    )
    assert warnings == []
    assert analysis.llm_enabled is True
    assert analysis.overall_sentiment == "MIXED"
    assert analysis.llm_model == "qwen3:32b"


@pytest.mark.asyncio
async def test_social_analysis_forbidden_key_rejected(monkeypatch) -> None:
    async def bad(self, messages, think=None):
        return {**_valid_social_payload(), "action": "BUY"}

    monkeypatch.setattr("local_llm.ollama_client.OllamaClient.chat_json", bad)

    analysis, warnings = await run_social_llm_analysis(
        "AAPL", "prompt", _client(), "qwen3:32b"
    )
    assert analysis.llm_enabled is False, "Forbidden key must degrade to empty analysis"
    assert warnings, "A warning must be recorded"


@pytest.mark.asyncio
async def test_social_analysis_connection_failure_degrades(monkeypatch) -> None:
    async def fail(self, messages, think=None):
        raise OllamaConnectionError("down")

    monkeypatch.setattr("local_llm.ollama_client.OllamaClient.chat_json", fail)

    analysis, warnings = await run_social_llm_analysis(
        "AAPL", "prompt", _client(), "qwen3:32b"
    )
    assert analysis.llm_enabled is False
    assert analysis.confidence_penalty == 0.0
    assert warnings
