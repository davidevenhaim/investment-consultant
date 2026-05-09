"""Abstract memory store interface — swap ChromaDB → pgvector by replacing implementation."""

from abc import ABC, abstractmethod
from typing import Any

from memory.schemas import MemoryDocument, MemorySearchResult


class MemoryStore(ABC):
    @abstractmethod
    async def add_document(self, collection: str, doc: MemoryDocument) -> None:
        """Upsert document into collection. Raises MemoryStoreError on failure."""
        ...

    @abstractmethod
    async def query_documents(
        self,
        collection: str,
        query_text: str,
        filters: dict[str, Any],
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """
        Return documents matching query_text filtered by metadata.
        Symbol filter in `filters` is mandatory — always apply it first.
        Results ordered by recency (created_at_ts desc), then similarity.
        Raises MemoryStoreError on failure.
        """
        ...
