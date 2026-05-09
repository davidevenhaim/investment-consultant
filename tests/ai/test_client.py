"""Tests for LLM client implementations."""
import pytest
from ai.fake_client import FakeClaudeClient
from ai.interfaces import LLMClient
from core.errors import LLMError


@pytest.mark.asyncio
async def test_fake_client_returns_valid_json() -> None:
    client = FakeClaudeClient()
    result = await client.complete("test prompt")
    import json
    parsed = json.loads(result)
    assert "thesis" in parsed
    assert "risk" in parsed
    assert "missing_details" in parsed
    assert "critic" in parsed


@pytest.mark.asyncio
async def test_fake_client_response_has_no_forbidden_fields() -> None:
    import json
    client = FakeClaudeClient()
    result = await client.complete("test prompt")
    parsed = json.loads(result)
    from ai.schemas import check_forbidden_keys
    assert check_forbidden_keys(parsed) == []


@pytest.mark.asyncio
async def test_fake_client_fail_raises_llm_error() -> None:
    client = FakeClaudeClient(fail=True)
    with pytest.raises(LLMError):
        await client.complete("test prompt")


@pytest.mark.asyncio
async def test_fake_client_custom_response() -> None:
    import json
    custom = {
        "thesis": {
            "symbol": "NVDA",
            "short_thesis": "Custom thesis.",
            "bullish_points": [],
            "bearish_points": [],
            "what_changed_since_last_run": [],
            "previous_thesis_alignment": "NO_PREVIOUS_THESIS",
            "confidence": 0.9,
        },
        "risk": {
            "symbol": "NVDA",
            "key_risks": [],
            "valuation_risks": [],
            "business_risks": [],
            "technical_risks": [],
            "near_term_watch_items": [],
            "confidence": 0.9,
        },
        "missing_details": {
            "symbol": "NVDA",
            "blocking_missing_details": [],
            "non_blocking_missing_details": [],
            "should_reduce_confidence": False,
            "confidence_penalty": 0.0,
            "confidence": 0.9,
        },
        "critic": {
            "symbol": "NVDA",
            "strongest_counterargument": "custom",
            "weak_points_in_analysis": [],
            "potential_overclaims": [],
            "should_cap_strong_buy": False,
            "should_reduce_confidence": False,
            "confidence_penalty": 0.0,
            "confidence": 0.9,
        },
    }
    client = FakeClaudeClient(response=custom)
    result = await client.complete("any prompt")
    assert json.loads(result)["thesis"]["symbol"] == "NVDA"


def test_fake_client_is_llm_client_subclass() -> None:
    assert isinstance(FakeClaudeClient(), LLMClient)


def test_anthropic_client_importable() -> None:
    from ai.client import AnthropicLLMClient
    assert issubclass(AnthropicLLMClient, LLMClient)
