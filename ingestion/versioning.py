"""Document versioning for the SOURCE knowledge base — distinct from draft
versioning (generation/drafting.py's v1/v2/v3 for GENERATED documents, which
already existed). This tracks changes to INGESTED documents: re-ingesting the
same filename with different content is treated as a new version, per the
RFP's "auto-versioned, last 3 versions retained, full history archived"
deliverable spec.

Scoped deliberately: this tracks version NUMBERS and a compact history
(hash, chunk count, timestamp) per version, not full-content archival of old
versions — archiving complete old text would need a real blob store design,
out of scope for a PoC. What it does guarantee is correctness: a changed
document doesn't leave its old chunks behind as stale, still-retrievable
ghosts (see delete_stale_chunks in retrieval/store.py, called alongside
this)."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "document_registry.json"


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def _save_registry(registry: dict):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def is_unchanged(source: str, combined_text: str) -> bool:
    """Cheap pre-check so scripts/ingest.py can skip classification/chunking/
    embedding entirely for documents that haven't changed since last run —
    those are the expensive steps (LLM + embedding-model calls), and a full
    corpus re-ingest was taking ~20 minutes even when only 2 of 23 documents
    were actually new. Uses the same hash register_ingestion() would compute,
    just without writing anything."""
    registry = _load_registry()
    entry = registry.get(source)
    return bool(entry and entry["current_hash"] == content_hash(combined_text))


def register_ingestion(source: str, combined_text: str, chunk_count: int) -> tuple[int, bool]:
    """Returns (version, changed). changed=False means this exact content
    was already registered at this version — nothing to do downstream."""
    registry = _load_registry()
    doc_hash = content_hash(combined_text)
    entry = registry.get(source)

    if entry and entry["current_hash"] == doc_hash:
        return entry["version"], False

    version = (entry["version"] + 1) if entry else 1
    history = entry["history_recent"] if entry else []
    history.append({
        "version": version, "hash": doc_hash, "chunk_count": chunk_count,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    })
    registry[source] = {
        "current_hash": doc_hash,
        "version": version,
        "history_recent": history[-3:],  # RFP spec: last 3 versions retained
        "total_versions_ever": (entry["total_versions_ever"] + 1) if entry else 1,  # "full history archived" (count; not full content — see module docstring)
    }
    _save_registry(registry)
    return version, True
