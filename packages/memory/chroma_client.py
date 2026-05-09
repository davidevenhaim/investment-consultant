"""ChromaDB implementation of MemoryStore."""

from typing import Any

import chromadb
from core.errors import MemoryStoreError
from core.logging import get_logger

from memory.collections import ALL_COLLECTIONS
from memory.interfaces import MemoryStore
from memory.schemas import MemoryDocument, MemorySearchResult

logger = get_logger(__name__)


class ChromaMemoryStore(MemoryStore):
    """
    Async ChromaDB HTTP client.
    All failures are caught and re-raised as MemoryStoreError.
    Never raises raw chromadb exceptions — callers rely on this guarantee.
    """

    def __init__(self, host: str = "localhost", port: int = 8001) -> None:
        self._host = host
        self._port = port
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = await chromadb.AsyncHttpClient(host=self._host, port=self._port)
                # Ensure all collections exist on first connection
                for name in ALL_COLLECTIONS:
                    await self._client.get_or_create_collection(name)
                logger.info("chroma_connected", host=self._host, port=self._port)
            except Exception as exc:
                self._client = None
                url = f"http://{self._host}:{self._port}"
                logger.error(
                    "chroma_connection_failed",
                    url=url,
                    error=str(exc),
                    hint="Inside Docker use CHROMA_HOST=chroma CHROMA_PORT=8000; "
                    "on host use CHROMA_HOST=localhost CHROMA_PORT=8001",
                )
                raise MemoryStoreError(
                    f"ChromaDB connection failed at {url}: {exc}",
                    {"host": self._host, "port": self._port, "url": url},
                ) from exc
        return self._client

    async def add_document(self, collection: str, doc: MemoryDocument) -> None:
        try:
            client = await self._get_client()
            col = await client.get_or_create_collection(collection)
            await col.upsert(
                ids=[doc.id],
                documents=[doc.content],
                metadatas=[{**doc.metadata, "symbol": doc.symbol}],
            )
            logger.info(
                "chroma_document_added",
                collection=collection,
                doc_id=doc.id,
                symbol=doc.symbol,
            )
        except MemoryStoreError:
            raise
        except Exception as exc:
            raise MemoryStoreError(
                f"ChromaDB add_document failed: {exc}",
                {"collection": collection, "doc_id": doc.id},
            ) from exc

    async def query_documents(
        self,
        collection: str,
        query_text: str,
        filters: dict[str, Any],
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """
        Query with mandatory symbol filter. Symbol filter applied first via metadata where clause.
        Results capped at limit. Never returns cross-symbol results.
        """
        try:
            client = await self._get_client()
            col = await client.get_or_create_collection(collection)

            # Symbol filter is always required
            symbol = filters.get("symbol")
            if not symbol:
                raise MemoryStoreError(
                    "query_documents: symbol filter is mandatory",
                    {"collection": collection},
                )

            where: dict[str, Any] = {"symbol": {"$eq": symbol}}

            result = await col.query(
                query_texts=[query_text],
                n_results=limit,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

            ids = (result.get("ids") or [[]])[0]
            documents = (result.get("documents") or [[]])[0]
            metadatas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]

            out: list[MemorySearchResult] = []
            for i, doc_id in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) else {}
                out.append(
                    MemorySearchResult(
                        id=doc_id,
                        symbol=str(meta.get("symbol", symbol)),
                        document_type=str(meta.get("document_type", "")),
                        title=str(meta.get("title", "")),
                        content=documents[i] if i < len(documents) else "",
                        metadata=meta,
                        distance=float(distances[i]) if i < len(distances) else None,
                        relevance_score=(
                            max(0.0, 1.0 - float(distances[i])) if i < len(distances) else None
                        ),
                    )
                )

            # Sort by recency (created_at_ts desc) as primary, similarity secondary
            out.sort(key=lambda r: r.metadata.get("created_at_ts", 0), reverse=True)
            return out[:limit]

        except MemoryStoreError:
            raise
        except Exception as exc:
            raise MemoryStoreError(
                f"ChromaDB query_documents failed: {exc}",
                {"collection": collection, "symbol": filters.get("symbol")},
            ) from exc


    async def reset_collections(self, collections: tuple[str, ...] | None = None) -> None:
        """
        Delete and recreate collections. Used by dev reset CLI and integration test teardown.
        If collections is None, resets ALL_COLLECTIONS.
        Never raises — logs errors and continues.
        """
        from memory.collections import ALL_COLLECTIONS

        targets = collections or ALL_COLLECTIONS
        client = await self._get_client()
        for name in targets:
            try:
                await client.delete_collection(name)
                await client.create_collection(name)
                logger.info("chroma_collection_reset", collection=name)
            except Exception as exc:
                logger.warning("chroma_collection_reset_failed", collection=name, error=str(exc))

    async def delete_documents(self, collection: str, ids: list[str]) -> None:
        """Delete specific documents by ID. Used by integration test teardown."""
        try:
            client = await self._get_client()
            col = await client.get_or_create_collection(collection)
            await col.delete(ids=ids)
        except Exception as exc:
            logger.warning(
                "chroma_delete_documents_failed", collection=collection, error=str(exc)
            )


def make_chroma_store() -> ChromaMemoryStore:
    from core.config import get_settings

    s = get_settings()
    return ChromaMemoryStore(host=s.chroma_host, port=s.chroma_port)
