"""Tests for memory indexer — document building."""

from unittest.mock import MagicMock

from memory.indexer import build_manual_note_document, build_recommendation_document
from memory.schemas import MemoryDocument


def _make_neutral_rec(action: str = "HOLD", score: int = 60) -> MagicMock:
    rec = MagicMock()
    rec.action.value = action
    rec.score = score
    rec.confidence = 0.75
    bd = MagicMock()
    bd.total_score = score
    bd.technical_score = 12.0
    bd.risk_score = 10.0
    bd.fundamental_score = 14.0
    bd.valuation_score = 9.0
    bd.news_score = 5.0
    bd.portfolio_fit_score = 7.0
    rec.score_breakdown = bd
    rec.main_reasons = ["Reason A", "Reason B"]
    rec.main_risks = ["Risk X"]
    rec.missing_details = ["Earnings date unknown"]
    rec.final_reason = "Neutral stance given mixed signals."
    return rec


def _make_personalized_rec(action: str = "HOLD") -> MagicMock:
    rec = MagicMock()
    rec.personal_action.value = action
    return rec


def test_build_recommendation_document_structure() -> None:
    doc = build_recommendation_document(
        symbol="AAPL",
        neutral_rec=_make_neutral_rec("HOLD", 60),
        personalized_rec=_make_personalized_rec("HOLD"),
        run_id="run-abc-123",
        neutral_rec_id="nr-001",
        personalized_rec_id="pr-001",
        price_at_recommendation=190.50,
        strategy_version_id="sv-001",
    )
    assert isinstance(doc, MemoryDocument)
    assert doc.id == "rec_run-abc-123_AAPL"
    assert doc.symbol == "AAPL"
    assert doc.document_type == "recommendation_report"
    assert "AAPL" in doc.title
    assert "HOLD" in doc.title
    assert "60" in doc.title


def test_build_recommendation_document_content() -> None:
    doc = build_recommendation_document(
        symbol="AAPL",
        neutral_rec=_make_neutral_rec("BUY_CANDIDATE", 75),
        personalized_rec=None,
        run_id="run-xyz",
        neutral_rec_id=None,
        personalized_rec_id=None,
        price_at_recommendation=None,
        strategy_version_id=None,
    )
    assert "Action: BUY_CANDIDATE" in doc.content
    assert "Score: 75/100" in doc.content
    assert "Reason A" in doc.content
    assert "Risk X" in doc.content
    assert "Earnings date unknown" in doc.content
    assert "Price at recommendation: N/A" in doc.content


def test_build_recommendation_document_metadata_keys() -> None:
    doc = build_recommendation_document(
        symbol="NVDA",
        neutral_rec=_make_neutral_rec("STRONG_BUY", 90),
        personalized_rec=_make_personalized_rec("STRONG_BUY"),
        run_id="run-999",
        neutral_rec_id="nr-999",
        personalized_rec_id="pr-999",
        price_at_recommendation=950.00,
        strategy_version_id="sv-v1",
    )
    meta = doc.metadata
    required = {
        "symbol",
        "document_type",
        "title",
        "research_run_id",
        "action",
        "personal_action",
        "score",
        "confidence",
        "as_of_time",
        "price_at_recommendation",
        "strategy_version_id",
        "created_at_ts",
    }
    assert required.issubset(meta.keys())
    assert meta["symbol"] == "NVDA"
    assert meta["action"] == "STRONG_BUY"
    assert meta["score"] == 90
    assert meta["price_at_recommendation"] == 950.00
    assert isinstance(meta["created_at_ts"], int)


def test_build_recommendation_document_deterministic_id() -> None:
    doc1 = build_recommendation_document(
        symbol="TSLA",
        neutral_rec=_make_neutral_rec(),
        personalized_rec=None,
        run_id="same-run",
        neutral_rec_id=None,
        personalized_rec_id=None,
        price_at_recommendation=None,
        strategy_version_id=None,
    )
    doc2 = build_recommendation_document(
        symbol="TSLA",
        neutral_rec=_make_neutral_rec(),
        personalized_rec=None,
        run_id="same-run",
        neutral_rec_id=None,
        personalized_rec_id=None,
        price_at_recommendation=None,
        strategy_version_id=None,
    )
    assert doc1.id == doc2.id  # upsert-safe re-indexing


def test_build_manual_note_document() -> None:
    doc = build_manual_note_document("AAPL", "Earnings watch", "Watch Q3 EPS closely.")
    assert doc.symbol == "AAPL"
    assert doc.document_type == "manual_note"
    assert doc.title == "Earnings watch"
    assert "Q3 EPS" in doc.content
    assert doc.id.startswith("note_AAPL_")
    assert doc.metadata["symbol"] == "AAPL"
