"""Qdrant wrapper. Runs in one of two modes controlled by QDRANT_MODE:

  "local"  - embedded, file-based Qdrant (no server process at all). This is
             the default so Phase 1 isn't blocked on Docker/WSL being ready.
  "server" - talks to a real Qdrant container at QDRANT_HOST:QDRANT_PORT.

Switching later is a one-line config change, not a code change — that's the
point of isolating this here instead of scattering QdrantClient(...) calls."""
import hashlib

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

from config import QDRANT_MODE, QDRANT_LOCAL_PATH, QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION
from ingestion.chunker import Chunk
from retrieval.embedder import embed_passages, embed_query, embedding_dim

_client = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        if QDRANT_MODE == "server":
            _client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        else:
            _client = QdrantClient(path=QDRANT_LOCAL_PATH)
    return _client


def ensure_collection():
    client = get_client()
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=embedding_dim(), distance=Distance.COSINE),
        )


def upsert_chunks(chunks: list[Chunk]):
    if not chunks:
        return
    ensure_collection()
    vectors = embed_passages([c.text for c in chunks])
    points = [
        PointStruct(
            id=int(hashlib.sha256(c.chunk_id.encode()).hexdigest()[:16], 16),
            vector=vec,
            payload={
                "chunk_id": c.chunk_id,
                "source": c.source,
                "unit_label": c.unit_label,
                "extraction_method": c.extraction_method,
                "text": c.text,
                "document_type": c.document_type,
                "category": c.category,
            },
        )
        for c, vec in zip(chunks, vectors)
    ]
    get_client().upsert(collection_name=QDRANT_COLLECTION, points=points)


def delete_stale_chunks(source: str, current_chunk_ids: set[str]) -> int:
    """When a document is re-ingested with different content, chunks from
    the old version that no longer exist in the new one (e.g. the doc got
    shorter, or a section was restructured) would otherwise sit in Qdrant
    forever as orphaned, still-retrievable stale data — silently wrong
    answers citing content that's no longer in the source document. Scrolls
    every point for this source and deletes anything not in the current
    chunk set. Returns how many were removed."""
    client = get_client()
    ensure_collection()
    to_delete = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))]),
            limit=256, offset=offset, with_payload=True, with_vectors=False,
        )
        to_delete.extend(p.id for p in points if p.payload.get("chunk_id") not in current_chunk_ids)
        if offset is None:
            break
    if to_delete:
        client.delete(collection_name=QDRANT_COLLECTION, points_selector=to_delete)
    return len(to_delete)


def get_document_chunks(source: str) -> list[dict]:
    """Fetches every chunk belonging to one document, in original order —
    used by summarization, which needs the whole document's text, not a
    top-k similarity match against a query."""
    client = get_client()
    ensure_collection()
    chunks = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))]),
            limit=256, offset=offset, with_payload=True, with_vectors=False,
        )
        chunks.extend({
            "chunk_id": p.payload["chunk_id"],
            "unit_label": p.payload["unit_label"],
            "text": p.payload["text"],
        } for p in points)
        if offset is None:
            break
    # chunk_id encodes "{source}::{unit_label}::chunk{i}" — sorting by it
    # restores original document order, which an unordered scroll doesn't guarantee.
    chunks.sort(key=lambda c: c["chunk_id"])
    return chunks


def list_sources() -> list[str]:
    """Distinct document filenames currently indexed — used to populate a
    document picker for summarization rather than requiring the exact
    filename to be typed."""
    client = get_client()
    ensure_collection()
    sources = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION, limit=256, offset=offset,
            with_payload=True, with_vectors=False,
        )
        sources.update(p.payload["source"] for p in points)
        if offset is None:
            break
    return sorted(sources)


def search(query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
    """`category` optionally scopes results to one QCI board/division (e.g.
    "NABL") — this is the metadata that department-scoped access control
    would eventually filter on, even though the enforcement layer itself
    (Pillar 1 RBAC) is still deferred. Filtering by it is available now so
    the capability exists ahead of that enforcement layer being built."""
    ensure_collection()
    query_vec = embed_query(query)
    query_filter = None
    if category:
        query_filter = Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])
    results = get_client().query_points(
        collection_name=QDRANT_COLLECTION, query=query_vec, limit=top_k, query_filter=query_filter
    ).points
    return [
        {
            "score": r.score,
            "chunk_id": r.payload["chunk_id"],
            "source": r.payload["source"],
            "unit_label": r.payload["unit_label"],
            "extraction_method": r.payload["extraction_method"],
            "text": r.payload["text"],
            # .get() with defaults — points ingested before this feature existed
            # won't have these fields yet, and shouldn't crash retrieval.
            "document_type": r.payload.get("document_type", "Other"),
            "category": r.payload.get("category", "General/Unclassified"),
        }
        for r in results
    ]
