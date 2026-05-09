"""Domain schemas for research memory — provider-agnostic."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MemoryDocument(BaseModel):
    id: str
    symbol: str
    document_type: str
    title: str
    content: str
    metadata: dict[str, Any]
    created_at: datetime


class MemorySearchResult(BaseModel):
    id: str
    symbol: str
    document_type: str
    title: str
    content: str
    metadata: dict[str, Any]
    distance: float | None = None
    relevance_score: float | None = None


class MemoryContext(BaseModel):
    """Aggregated memory for one symbol, consumed by graph nodes."""

    symbol: str
    previous_recommendation: dict[str, Any] | None = None
    previous_thesis: str | None = None
    relevant_memories: list[MemorySearchResult] = []
    memory_summary: str | None = None
    memory_count: int = 0
