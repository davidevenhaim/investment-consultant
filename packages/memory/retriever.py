"""Retrieve previous research memory for a symbol from ChromaDB."""

from typing import Any

from core.errors import MemoryStoreError
from core.logging import get_logger

from memory.collections import RECOMMENDATION_REPORTS
from memory.interfaces import MemoryStore
from memory.schemas import MemoryContext, MemorySearchResult

logger = get_logger(__name__)


def _parse_previous_recommendation(result: MemorySearchResult) -> dict[str, Any] | None:
    """
    Extract recommendation fields from a memory search result.
    Returns None if the doc lacks the required action or research_run_id fields.
    research_run_id presence distinguishes real research runs from test/manual docs.
    """
    meta = result.metadata
    if not meta.get("action"):
        return None
    if not meta.get("research_run_id"):
        return None
    return {
        "action": meta.get("action"),
        "personal_action": meta.get("personal_action"),
        "score": meta.get("score"),
        "confidence": meta.get("confidence"),
        "price_at_recommendation": meta.get("price_at_recommendation"),
        "as_of_time": meta.get("as_of_time"),
        "research_run_id": meta.get("research_run_id"),
    }


def _find_latest_recommendation(
    results: list[MemorySearchResult],
) -> MemorySearchResult | None:
    """
    Return the most recent result (already sorted by created_at_ts DESC)
    that looks like a real research run (has action + research_run_id).
    """
    for r in results:
        if r.metadata.get("action") and r.metadata.get("research_run_id"):
            return r
    return None


def _build_memory_summary(symbol: str, results: list[MemorySearchResult]) -> str:
    if not results:
        return f"No previous research found for {symbol}. First run."
    latest = _find_latest_recommendation(results)
    if latest is None:
        n = len(results)
        noun = "report" if n == 1 else "reports"
        return f"Found {n} {noun} for {symbol} but none are valid recommendation reports."
    meta = latest.metadata
    action = meta.get("action", "UNKNOWN")
    score = meta.get("score", "?")
    price = meta.get("price_at_recommendation")
    as_of = meta.get("as_of_time", "")[:10] if meta.get("as_of_time") else "unknown date"
    price_str = f" at ${price:.2f}" if price else ""
    n = len(results)
    noun = "report" if n == 1 else "reports"
    return (
        f"Found {n} previous research {noun} for {symbol}. "
        f"Last action: {action}, score {score}{price_str} on {as_of}."
    )


async def retrieve_symbol_memory(
    symbol: str,
    limit: int = 5,
    store: MemoryStore | None = None,
) -> MemoryContext:
    """
    Retrieve previous research memories for symbol.
    Returns empty MemoryContext on any failure — never raises.
    Symbol filter is always applied — never returns cross-symbol results.
    previous_recommendation always uses the newest real research run doc
    (requires research_run_id in metadata) to avoid test/manual doc pollution.
    """
    if store is None:
        from memory.service import _get_default_store

        store = _get_default_store()

    try:
        results = await store.query_documents(
            collection=RECOMMENDATION_REPORTS,
            query_text=f"{symbol} research recommendation",
            filters={"symbol": symbol},
            limit=limit,
        )

        if not results:
            return MemoryContext(
                symbol=symbol,
                memory_summary=f"No previous research found for {symbol}. First run.",
                memory_count=0,
            )

        latest = _find_latest_recommendation(results)
        prev_rec = _parse_previous_recommendation(latest) if latest else None
        prev_thesis = latest.content if latest else None
        summary = _build_memory_summary(symbol, results)

        logger.info(
            "memory_retrieved",
            symbol=symbol,
            count=len(results),
            last_action=prev_rec.get("action") if prev_rec else None,
        )
        return MemoryContext(
            symbol=symbol,
            previous_recommendation=prev_rec,
            previous_thesis=prev_thesis,
            relevant_memories=results,
            memory_summary=summary,
            memory_count=len(results),
        )

    except MemoryStoreError as exc:
        logger.warning("memory_retrieve_failed", symbol=symbol, error=str(exc))
        return MemoryContext(
            symbol=symbol,
            memory_summary=f"Memory retrieval failed for {symbol}. Continuing without history.",
            memory_count=0,
        )
    except Exception as exc:
        logger.warning("memory_retrieve_unexpected", symbol=symbol, error=str(exc))
        return MemoryContext(
            symbol=symbol,
            memory_summary=f"Memory retrieval failed for {symbol}. Continuing without history.",
            memory_count=0,
        )
