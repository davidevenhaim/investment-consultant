"""Build structured recommendation report documents for ChromaDB indexing."""

import uuid
from datetime import UTC, datetime
from typing import Any

from memory.schemas import MemoryDocument


def build_recommendation_document(
    symbol: str,
    neutral_rec: Any,
    personalized_rec: Any,
    run_id: str,
    neutral_rec_id: str | None,
    personalized_rec_id: str | None,
    price_at_recommendation: float | None,
    strategy_version_id: str | None,
) -> MemoryDocument:
    """
    Build a structured human-readable document from a recommendation.
    Document ID is deterministic: rec_{run_id}_{symbol} so re-indexing upserts.
    """
    action = neutral_rec.action.value if neutral_rec else "UNKNOWN"
    score = neutral_rec.score if neutral_rec else 0
    confidence = neutral_rec.confidence if neutral_rec else 0.0

    now = datetime.now(UTC)
    now_iso = now.isoformat()
    now_ts = int(now.timestamp() * 1000)  # milliseconds — avoids same-second sort collision

    personal_action = personalized_rec.personal_action.value if personalized_rec else action

    # Build human-readable content
    title = f"{symbol} research report — {action} — score {score} — {now.strftime('%Y-%m-%d')}"

    lines: list[str] = [
        f"Symbol: {symbol}",
        f"Action: {action}",
        f"Score: {score}/100",
        f"Confidence: {confidence:.2f}",
        f"Price at recommendation: ${price_at_recommendation:.2f}"
        if price_at_recommendation
        else "Price at recommendation: N/A",
        f"As of: {now_iso}",
        "",
    ]

    if neutral_rec and neutral_rec.score_breakdown:
        bd = neutral_rec.score_breakdown
        lines += [
            "Score breakdown:",
            f"- Technical (real): {bd.technical_score:.0f}/20",
            f"- Risk (real): {bd.risk_score:.0f}/15",
            f"- Fundamental (real): {bd.fundamental_score:.0f}/20",
            f"- Valuation (real): {bd.valuation_score:.0f}/15",
            f"- News stub: {bd.news_score:.0f}/15",
            f"- Portfolio stub: {bd.portfolio_fit_score:.0f}/15",
            "",
        ]

    if neutral_rec and neutral_rec.main_reasons:
        lines.append("Main reasons:")
        for r in neutral_rec.main_reasons:
            lines.append(f"- {r}")
        lines.append("")

    if neutral_rec and neutral_rec.main_risks:
        lines.append("Main risks:")
        for r in neutral_rec.main_risks:
            lines.append(f"- {r}")
        lines.append("")

    if neutral_rec and neutral_rec.missing_details:
        lines.append("Missing details:")
        for d in neutral_rec.missing_details:
            lines.append(f"- {d}")
        lines.append("")

    if neutral_rec:
        lines += [
            "Final reason:",
            neutral_rec.final_reason,
        ]

    content = "\n".join(lines)

    metadata: dict[str, Any] = {
        "symbol": symbol,
        "document_type": "recommendation_report",
        "title": title,
        "research_run_id": run_id,
        "neutral_recommendation_id": neutral_rec_id or "",
        "personalized_recommendation_id": personalized_rec_id or "",
        "action": action,
        "personal_action": personal_action,
        "score": score,
        "confidence": confidence,
        "as_of_time": now_iso,
        "price_at_recommendation": (
            float(price_at_recommendation) if price_at_recommendation else 0.0
        ),
        "strategy_version_id": strategy_version_id or "",
        "created_at_ts": now_ts,
    }

    doc_id = f"rec_{run_id}_{symbol}"

    return MemoryDocument(
        id=doc_id,
        symbol=symbol,
        document_type="recommendation_report",
        title=title,
        content=content,
        metadata=metadata,
        created_at=now,
    )


def build_manual_note_document(
    symbol: str,
    title: str,
    content: str,
) -> MemoryDocument:
    now = datetime.now(UTC)
    doc_id = f"note_{symbol}_{uuid.uuid4().hex[:8]}"
    return MemoryDocument(
        id=doc_id,
        symbol=symbol,
        document_type="manual_note",
        title=title,
        content=content,
        metadata={
            "symbol": symbol,
            "document_type": "manual_note",
            "title": title,
            "created_at_ts": int(now.timestamp() * 1000),
        },
        created_at=now,
    )
