"""Memory endpoints — read previous research and add manual notes."""

from typing import Any

from core.responses import api_response
from fastapi import APIRouter, Body, HTTPException, Request
from memory.retriever import retrieve_symbol_memory

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/{symbol}")
async def get_symbol_memory(
    symbol: str,
    request: Request,
    limit: int = 5,
) -> dict[str, Any]:
    """Return ChromaDB research memory for a symbol."""
    ctx = await retrieve_symbol_memory(symbol.upper(), limit=limit)
    prev_rec = ctx.previous_recommendation or {}
    return api_response(
        {
            "symbol": ctx.symbol,
            "memory_count": ctx.memory_count,
            "memory_summary": ctx.memory_summary,
            "previous_recommendation": prev_rec,
            "previous_thesis": ctx.previous_thesis,
            "relevant_memories": [
                {
                    "id": r.id,
                    "title": r.title,
                    "document_type": r.document_type,
                    "relevance_score": r.relevance_score,
                    "as_of_time": r.metadata.get("as_of_time"),
                    "action": r.metadata.get("action"),
                    "score": r.metadata.get("score"),
                }
                for r in ctx.relevant_memories
            ],
        },
        request,
    )


@router.post("/{symbol}/note")
async def add_manual_note(
    symbol: str,
    request: Request,
    title: str = Body(...),
    content: str = Body(...),
) -> dict[str, Any]:
    """Index a manual research note to ChromaDB for a symbol."""
    from memory.collections import MANUAL_NOTES
    from memory.indexer import build_manual_note_document
    from memory.service import _get_default_store

    if not title.strip() or not content.strip():
        raise HTTPException(status_code=422, detail="title and content must not be empty")

    doc = build_manual_note_document(symbol.upper(), title.strip(), content.strip())
    store = _get_default_store()
    try:
        await store.add_document(MANUAL_NOTES, doc)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ChromaDB unavailable: {exc}") from exc

    return api_response({"doc_id": doc.id, "symbol": doc.symbol, "title": doc.title}, request)
