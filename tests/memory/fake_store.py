"""In-memory MemoryStore for tests — no ChromaDB required."""

from typing import Any

from memory.interfaces import MemoryStore
from memory.schemas import MemoryDocument, MemorySearchResult


class FakeMemoryStore(MemoryStore):
    """Thread-safe in-memory store. Documents keyed by (collection, id)."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, MemoryDocument]] = {}  # collection → id → doc

    def _col(self, collection: str) -> dict[str, MemoryDocument]:
        return self._docs.setdefault(collection, {})

    async def add_document(self, collection: str, doc: MemoryDocument) -> None:
        self._col(collection)[doc.id] = doc

    async def query_documents(
        self,
        collection: str,
        query_text: str,
        filters: dict[str, Any],
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        symbol = filters.get("symbol")
        col = self._col(collection)
        results = [
            MemorySearchResult(
                id=doc.id,
                symbol=doc.symbol,
                document_type=doc.document_type,
                title=doc.title,
                content=doc.content,
                metadata=doc.metadata,
                distance=0.1,
                relevance_score=0.9,
            )
            for doc in col.values()
            if symbol is None or doc.symbol == symbol
        ]
        results.sort(key=lambda r: r.metadata.get("created_at_ts", 0), reverse=True)
        return results[:limit]

    def count(self, collection: str) -> int:
        return len(self._col(collection))

    def clear(self) -> None:
        self._docs.clear()
