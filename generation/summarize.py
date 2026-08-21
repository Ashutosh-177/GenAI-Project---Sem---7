"""Document summarisation — a named Pillar 3 scope item ("intelligent
summarisation") that was never built despite Q&A and drafting both existing.
Reuses the same retrieval/LLM building blocks as everything else — the only
new problem is size: a document like the 555-chunk tender doc has far more
text than fits comfortably in one prompt, so this uses map-reduce:
summarise in batches, then summarise the summaries."""
import re

from generation.llm_client import chat as _llm_chat, LLMRefusalError
from retrieval.store import get_document_chunks

# Per-batch character budget. Originally a tight 6000 chars, calibrated for
# a local 3B model's small context window (see Memory.md — this project
# moved LLM reasoning to Claude via the Anthropic API); Claude's much
# larger context window doesn't need batches that small, so this is raised
# to cut down on unnecessary extra map-reduce round trips for large docs.
BATCH_CHAR_BUDGET = 40000

_PREAMBLE_PATTERNS = [
    r"^here (is|are)[^\n:]*:\s*",
    r"^sure[,!]?\s*here[^\n:]*:\s*",
    r"^(certainly|of course)[,!]?\s*",
]


def _clean(text: str) -> str:
    text = text.strip()
    for pattern in _PREAMBLE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def _llm(prompt: str) -> str:
    return _clean(_llm_chat(prompt))


def _batch_chunks(chunks: list[dict], budget: int) -> list[list[dict]]:
    batches, current, current_len = [], [], 0
    for c in chunks:
        if current and current_len + len(c["text"]) > budget:
            batches.append(current)
            current, current_len = [], 0
        current.append(c)
        current_len += len(c["text"])
    if current:
        batches.append(current)
    return batches


def summarize_document(source: str) -> dict:
    """Returns {summary, chunk_count, batches_used, is_fallback}. Empty
    document (nothing indexed under that source) is a real, distinct case
    from "summarization failed" — surfaced explicitly rather than as a
    generic error."""
    chunks = get_document_chunks(source)
    if not chunks:
        return {"summary": f"No indexed content found for '{source}'.", "chunk_count": 0,
                "batches_used": 0, "is_fallback": True}

    batches = _batch_chunks(chunks, BATCH_CHAR_BUDGET)

    if len(batches) == 1:
        text = "\n\n".join(c["text"] for c in batches[0])
        summary = _llm(
            f"Summarise the following document excerpt in 3-6 sentences. "
            f"Only state what's actually in the text below — do not add outside "
            f"knowledge or invent details. Output ONLY the summary, no preamble.\n\n{text}\n\nSummary:"
        )
        return {"summary": summary, "chunk_count": len(chunks), "batches_used": 1, "is_fallback": False}

    # Map: summarise each batch independently. A single batch being refused
    # must not sink the whole document — real case in this corpus: a
    # badly-scanned page produced garbled OCR character-soup that tripped a
    # safety classifier ("bio" false positive), and the crash took the entire
    # 138-chunk document's summary with it. Skip the batch, keep the rest,
    # and report honestly rather than silently returning a partial summary as
    # if it were complete.
    partial_summaries = []
    skipped = 0
    for batch in batches:
        text = "\n\n".join(c["text"] for c in batch)
        try:
            partial_summaries.append(_llm(
                f"Summarise this excerpt from a larger document in 2-4 sentences. "
                f"Only state what's actually in the text below. Output ONLY the summary.\n\n{text}\n\nSummary:"
            ))
        except LLMRefusalError:
            skipped += 1

    if not partial_summaries:
        return {"summary": f"Could not summarise '{source}' — every section was declined by the model "
                           f"(commonly caused by unreadable OCR text).",
                "chunk_count": len(chunks), "batches_used": len(batches),
                "sections_skipped": skipped, "is_fallback": True}

    # Reduce: summarise the summaries into one coherent final summary.
    combined = "\n\n".join(f"- {s}" for s in partial_summaries)
    final = _llm(
        f"These are summaries of consecutive sections of one document, in order. "
        f"Combine them into a single coherent 4-8 sentence summary of the whole "
        f"document. Do not add anything not present in these section summaries. "
        f"Output ONLY the summary.\n\n{combined}\n\nOverall summary:"
    )
    if skipped:
        final += (f"\n\n(Note: {skipped} of {len(batches)} sections could not be processed "
                  f"and are not reflected above.)")
    return {"summary": final, "chunk_count": len(chunks), "batches_used": len(batches),
            "sections_skipped": skipped, "is_fallback": False}
