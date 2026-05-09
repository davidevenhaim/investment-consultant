"""Memory service — orchestrates retriever + indexer, used by graph nodes."""

from typing import Any

from core.logging import get_logger

from memory.interfaces import MemoryStore

logger = get_logger(__name__)

_store: MemoryStore | None = None


def _get_default_store() -> MemoryStore:
    global _store
    if _store is None:
        from memory.chroma_client import make_chroma_store

        _store = make_chroma_store()
    return _store


async def index_recommendation_report(
    symbol: str,
    neutral_rec: Any,
    personalized_rec: Any,
    run_id: str,
    neutral_rec_id: str | None,
    personalized_rec_id: str | None,
    price_at_recommendation: float | None,
    strategy_version_id: str | None,
    llm_analysis: Any = None,
    store: MemoryStore | None = None,
) -> bool:
    """
    Index a recommendation report to ChromaDB.
    Returns True on success, False on failure.
    Never raises — Chroma failure must not crash a research run.
    """
    if store is None:
        store = _get_default_store()

    from memory.collections import RECOMMENDATION_REPORTS
    from memory.indexer import build_recommendation_document

    try:
        doc = build_recommendation_document(
            symbol=symbol,
            neutral_rec=neutral_rec,
            personalized_rec=personalized_rec,
            run_id=run_id,
            neutral_rec_id=neutral_rec_id,
            personalized_rec_id=personalized_rec_id,
            price_at_recommendation=price_at_recommendation,
            strategy_version_id=strategy_version_id,
            llm_analysis=llm_analysis,
        )
        await store.add_document(RECOMMENDATION_REPORTS, doc)
        logger.info("memory_indexed", symbol=symbol, doc_id=doc.id, run_id=run_id)
        return True
    except Exception as exc:
        logger.warning("memory_index_failed", symbol=symbol, run_id=run_id, error=str(exc))
        return False
