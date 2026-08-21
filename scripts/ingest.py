"""Phase 1 entry point: parse every document in data/samples/, classify it,
chunk it, embed it, and upsert into Qdrant. Run this once, then use
scripts/query.py to sanity-check retrieval quality by hand."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion.parser import parse_document
from ingestion.chunker import chunk_units
from ingestion.classifier import classify_document
from ingestion.versioning import register_ingestion, is_unchanged
from retrieval.store import upsert_chunks, delete_stale_chunks
from config import QDRANT_MODE, QDRANT_LOCAL_PATH, MAX_FILE_SIZE_BYTES

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
SUPPORTED_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".ppt"}


def main():
    print(f"[ingest] Qdrant mode: {QDRANT_MODE}" + (f" ({QDRANT_LOCAL_PATH})" if QDRANT_MODE == "local" else ""))
    files = [f for f in SAMPLES_DIR.iterdir() if f.suffix.lower() in SUPPORTED_EXT]
    if not files:
        print(f"[ingest] No documents found in {SAMPLES_DIR}")
        return

    total_chunks = 0
    skipped = 0
    for f in files:
        t0 = time.time()

        size = f.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            print(f"[ingest] SKIPPED {f.name}: {size / 1_048_576:.1f}MB exceeds the "
                  f"{MAX_FILE_SIZE_BYTES / 1_048_576:.0f}MB per-file limit")
            continue

        try:
            units = parse_document(f)
        except Exception as e:
            print(f"[ingest] FAILED to parse {f.name}: {e}")
            continue

        combined_text = "\n".join(u.text for u in units)

        if is_unchanged(f.name, combined_text):
            # Same content as last run — skip the expensive steps entirely
            # (classification + embedding are LLM/model calls). Correctness
            # is unaffected: the chunks already in Qdrant are still valid.
            print(f"[ingest] {f.name}: unchanged since last ingest, skipped")
            skipped += 1
            continue

        doc_type, category = classify_document(f.name, combined_text)

        ocr_pages = sum(1 for u in units if u.extraction_method == "ocr")
        chunks = chunk_units(units, document_type=doc_type, category=category)

        version, changed = register_ingestion(f.name, combined_text, len(chunks))
        upsert_chunks(chunks)
        removed = 0
        if changed and version > 1:
            # Content changed from a previous version — clean up chunks that
            # existed under the old version but don't exist in this one,
            # rather than leaving them as stale, still-retrievable ghosts.
            removed = delete_stale_chunks(f.name, {c.chunk_id for c in chunks})

        total_chunks += len(chunks)
        elapsed = time.time() - t0
        version_note = f", v{version}" + (f" ({removed} stale chunk(s) removed)" if removed else "") if version > 1 else ""
        print(f"[ingest] {f.name}: [{doc_type} / {category}] {len(units)} unit(s) ({ocr_pages} via OCR), "
              f"{len(chunks)} chunk(s){version_note}, {elapsed:.1f}s")

    print(f"\n[ingest] Done. {len(files)} file(s) seen, {len(files) - skipped} processed, "
          f"{skipped} unchanged/skipped, {total_chunks} chunk(s) (re-)indexed.")


if __name__ == "__main__":
    main()
