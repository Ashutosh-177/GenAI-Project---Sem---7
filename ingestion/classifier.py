"""Document classification at ingest time — the Pillar 2 gap flagged
repeatedly and never built until now. Runs once per document (not per
chunk, since "what kind of document is this" is a document-level fact),
tagging every chunk from it with a document_type and a QCI board/division
category.

Uses QCI's REAL organisational structure — NABL, NABH, NABET, NABCB, NBQP,
PPID, NDIE, PADD, SPD — read directly from the RFP itself (QCI.pdf, section
I), not a generic placeholder taxonomy. This matters concretely: the RFP's
own security section uses "NABH vs. NABL" as its literal example of what
department-scoped access control should look like — this classification is
the metadata that access control (Pillar 1, still deferred) would eventually
filter on."""
import re

from generation.llm_client import chat as _llm_chat

DOCUMENT_TYPES = ["Proposal", "MoU", "Agreement", "Work Order", "Tender", "Circular", "EoI", "Other"]

# QCI's real boards + project divisions, from QCI.pdf section I (Introduction).
QCI_CATEGORIES = [
    "NABL",  # National Accreditation Board for Testing and Calibration Laboratories
    "NABH",  # National Accreditation Board for Hospitals & Healthcare Providers
    "NABET",  # National Accreditation Board for Education and Training
    "NABCB",  # National Accreditation Board for Certification Bodies
    "NBQP",  # National Board for Quality Promotion
    "PPID",  # Project Planning & Implementation Division
    "NDIE",  # NDIE Division
    "PADD",  # Project Analysis and Documentation Division
    "SPD",   # Strategy and Policy Division
    "General/Unclassified",  # doesn't clearly map to a specific board
]

_TYPE_PATTERN = re.compile(r"TYPE:\s*([^\n]+)", re.IGNORECASE)
_CATEGORY_PATTERN = re.compile(r"CATEGORY:\s*([^\n]+)", re.IGNORECASE)


def _best_match(value: str, allowed: list[str]) -> str | None:
    """Case-insensitive exact match first, then substring match (a model
    will often add extra words around the right answer, e.g. "Agreement -
    consultancy type" instead of just "Agreement")."""
    value = value.strip().lower()
    for a in allowed:
        if a.lower() == value:
            return a
    for a in allowed:
        if a.lower() in value:
            return a
    return None


def classify_document(source_name: str, sample_text: str) -> tuple[str, str]:
    """Returns (document_type, category). Defensive parsing throughout —
    same lesson as every other guardrail in this codebase: a 3B model asked
    for a constrained categorical answer will still sometimes go off-script.
    Confirmed by debugging (scripts/debug_classifier.py): the model reliably
    drops the TYPE line entirely and answers only CATEGORY when both are
    asked for in one combined-line format — so each field is now parsed
    independently, and a missing/unparseable field falls back to a safe
    default without dragging the other, successfully-parsed field down with it."""
    prompt = f"""Classify this document. Respond in exactly two lines, nothing else:
TYPE: <one of {", ".join(DOCUMENT_TYPES)}>
CATEGORY: <one of {", ".join(QCI_CATEGORIES)}>

CATEGORY should reflect which QCI board/division this document most relates to \
based on its subject matter (e.g. content about labs/testing -> NABL, hospitals \
-> NABH, education/training -> NABET, certification bodies -> NABCB). If it \
doesn't clearly relate to a specific board, use General/Unclassified.

Document filename: {source_name}
Document excerpt:
{sample_text[:1500]}

Your two-line answer:"""

    try:
        raw = _llm_chat(prompt).strip()

        type_match = _TYPE_PATTERN.search(raw)
        category_match = _CATEGORY_PATTERN.search(raw)

        doc_type = _best_match(type_match.group(1), DOCUMENT_TYPES) if type_match else None
        category = _best_match(category_match.group(1), QCI_CATEGORIES) if category_match else None

        return doc_type or "Other", category or "General/Unclassified"
    except Exception:
        # Classification failing should never block ingestion itself — a
        # document with unknown metadata is still searchable, just untagged.
        return "Other", "General/Unclassified"
