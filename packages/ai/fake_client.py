"""FakeClaudeClient — deterministic LLM client for tests. No network calls."""
import json

from core.errors import LLMError

from ai.interfaces import LLMClient

# Deterministic valid response that passes all schema validations.
# No forbidden fields (action, score, recommendation, etc.).
_FAKE_RESPONSE: dict[str, object] = {
    "thesis": {
        "symbol": "AAPL",
        "short_thesis": (
            "Strong fundamentals with high margins and steady growth, "
            "but valuation is stretched relative to peers."
        ),
        "bullish_points": [
            "Revenue growth above sector median.",
            "Best-in-class profit margins demonstrate pricing power.",
            "Strong free cash flow generation supports capital returns.",
        ],
        "bearish_points": [
            "Forward valuation multiples price in continued high growth.",
            "Slowing unit volume growth in key product categories.",
        ],
        "what_changed_since_last_run": [
            "No significant change detected from prior analysis."
        ],
        "previous_thesis_alignment": "UNCHANGED",
        "confidence": 0.78,
    },
    "risk": {
        "symbol": "AAPL",
        "key_risks": [
            "Valuation premium leaves limited margin of safety.",
            "Earnings sensitivity to macro headwinds.",
        ],
        "valuation_risks": [
            "Current PE above 5-year average; requires sustained growth to justify.",
        ],
        "business_risks": [
            "Competitive pressure in services segment.",
            "Supply chain concentration risk.",
        ],
        "technical_risks": [
            "RSI approaching historically overbought range.",
        ],
        "near_term_watch_items": [
            "Next earnings guidance commentary.",
            "Macro interest rate trajectory.",
        ],
        "confidence": 0.75,
    },
    "missing_details": {
        "symbol": "AAPL",
        "blocking_missing_details": [],
        "non_blocking_missing_details": [
            "News analysis not yet available (M8 pending).",
            "Portfolio context not available (M9 pending).",
            "SEC filings not ingested.",
        ],
        "should_reduce_confidence": False,
        "confidence_penalty": 0.05,
        "confidence": 0.85,
    },
    "critic": {
        "symbol": "AAPL",
        "strongest_counterargument": (
            "The current valuation assumes sustained premium growth "
            "that may not materialize if macro conditions worsen."
        ),
        "weak_points_in_analysis": [
            "Absence of news data may miss near-term catalysts or risks.",
        ],
        "potential_overclaims": [
            "Historical margin strength may not persist under competitive pressure.",
        ],
        "should_cap_strong_buy": False,
        "should_reduce_confidence": False,
        "confidence_penalty": 0.03,
        "confidence": 0.80,
    },
}


class FakeClaudeClient(LLMClient):
    """
    Deterministic in-memory LLM client for tests.
    Never makes network calls.
    FakeClaudeClient(fail=True) raises LLMError for failure tests.
    """

    def __init__(self, fail: bool = False, response: dict[str, object] | None = None) -> None:
        self._fail = fail
        self._response = response or _FAKE_RESPONSE

    async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
        if self._fail:
            raise LLMError("FakeClaudeClient configured to fail.", {})
        return json.dumps(self._response)
