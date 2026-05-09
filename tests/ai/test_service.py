"""Tests for LLM analysis service — parse, validate, fallback."""
import json

import pytest
from ai.fake_client import _FAKE_RESPONSE, FakeClaudeClient
from ai.service import run_llm_analysis


@pytest.mark.asyncio
async def test_valid_response_parsed_correctly() -> None:
    client = FakeClaudeClient()
    analysis, warnings = await run_llm_analysis(
        symbol="AAPL", prompt="test", client=client, model="fake"
    )
    assert analysis.llm_enabled is True
    assert analysis.llm_model == "fake"
    assert analysis.thesis.short_thesis != ""
    assert len(analysis.risk.key_risks) > 0
    assert warnings == []


@pytest.mark.asyncio
async def test_total_confidence_penalty_computed_correctly() -> None:
    client = FakeClaudeClient()
    analysis, _ = await run_llm_analysis("AAPL", "p", client, "m")
    expected = min(
        0.25,
        min(0.15, _FAKE_RESPONSE["missing_details"]["confidence_penalty"])
        + min(0.15, _FAKE_RESPONSE["critic"]["confidence_penalty"]),
    )
    assert analysis.total_confidence_penalty == pytest.approx(expected)


@pytest.mark.asyncio
async def test_analysis_quality_is_average_of_confidences() -> None:
    client = FakeClaudeClient()
    analysis, _ = await run_llm_analysis("AAPL", "p", client, "m")
    raw = _FAKE_RESPONSE
    expected = (
        raw["thesis"]["confidence"]
        + raw["risk"]["confidence"]
        + raw["missing_details"]["confidence"]
        + raw["critic"]["confidence"]
    ) / 4
    assert analysis.analysis_quality_score == pytest.approx(expected, abs=0.01)


@pytest.mark.asyncio
async def test_llm_failure_returns_empty_analysis() -> None:
    client = FakeClaudeClient(fail=True)
    analysis, warnings = await run_llm_analysis("AAPL", "p", client, "m")
    assert analysis.llm_enabled is False
    assert len(warnings) == 1
    assert "AAPL" in warnings[0]


@pytest.mark.asyncio
async def test_llm_failure_never_raises() -> None:
    client = FakeClaudeClient(fail=True)
    # Should not raise — must return gracefully
    analysis, warnings = await run_llm_analysis("AAPL", "p", client, "m")
    assert analysis is not None


@pytest.mark.asyncio
async def test_invalid_json_returns_fallback() -> None:
    from ai.interfaces import LLMClient

    class BadJsonClient(LLMClient):
        async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
            return "not valid JSON {{{"

    analysis, warnings = await run_llm_analysis("AAPL", "p", BadJsonClient(), "m")
    assert analysis.llm_enabled is False
    assert any("JSON" in w or "parse" in w.lower() for w in warnings)


@pytest.mark.asyncio
async def test_missing_required_section_returns_fallback() -> None:
    from ai.interfaces import LLMClient

    class MissingKeyClient(LLMClient):
        async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
            return json.dumps({"thesis": {"symbol": "AAPL"}})  # missing risk, missing_details, critic

    analysis, warnings = await run_llm_analysis("AAPL", "p", MissingKeyClient(), "m")
    assert analysis.llm_enabled is False
    assert len(warnings) > 0


@pytest.mark.asyncio
async def test_forbidden_field_returns_fallback() -> None:
    from ai.interfaces import LLMClient

    class ActionFieldClient(LLMClient):
        async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
            bad = {**_FAKE_RESPONSE, "action": "STRONG_BUY"}
            return json.dumps(bad)

    analysis, warnings = await run_llm_analysis("AAPL", "p", ActionFieldClient(), "m")
    assert analysis.llm_enabled is False
    assert any("forbidden" in w.lower() for w in warnings)


@pytest.mark.asyncio
async def test_extra_field_in_subsection_returns_fallback() -> None:
    import copy

    from ai.interfaces import LLMClient

    class ExtraFieldClient(LLMClient):
        async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
            bad = copy.deepcopy(_FAKE_RESPONSE)
            bad["thesis"]["score"] = 90  # forbidden in sub-schema
            return json.dumps(bad)

    analysis, warnings = await run_llm_analysis("AAPL", "p", ExtraFieldClient(), "m")
    assert analysis.llm_enabled is False
