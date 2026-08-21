"""Splits parsed page/slide units into overlapping chunks sized for the
embedding model's context, carrying source metadata through so retrieval
can cite exactly where an answer came from — this is what makes the
"mandatory citation per claim" requirement possible downstream."""
from dataclasses import dataclass

from config import CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS
from ingestion.parser import PageUnit


@dataclass
class Chunk:
    chunk_id: str
    source: str
    unit_label: str
    extraction_method: str
    text: str
    document_type: str = "Other"
    category: str = "General/Unclassified"


def chunk_units(units: list[PageUnit], document_type: str = "Other",
                 category: str = "General/Unclassified") -> list[Chunk]:
    """document_type/category are classified once per document (see
    ingestion/classifier.py) and stamped onto every chunk from it — this is
    what makes department/board-scoped filtering possible later, even though
    the access-control enforcement itself (Pillar 1) is still deferred."""
    chunks = []
    for unit in units:
        pieces = _split_text(unit.text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)
        for i, piece in enumerate(pieces):
            chunk_id = f"{unit.source}::{unit.unit_label}::chunk{i}"
            chunks.append(Chunk(chunk_id, unit.source, unit.unit_label, unit.extraction_method,
                                 piece, document_type, category))
    return chunks


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    """Word-boundary-safe sliding window — avoids severing a sentence mid-word,
    which would otherwise degrade embedding quality at chunk edges."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    words = text.split()
    pieces, current, current_len = [], [], 0
    for word in words:
        current.append(word)
        current_len += len(word) + 1
        if current_len >= size:
            pieces.append(" ".join(current))
            # step back by roughly `overlap` chars worth of words for the next window
            overlap_words = []
            back_len = 0
            for w in reversed(current):
                back_len += len(w) + 1
                overlap_words.insert(0, w)
                if back_len >= overlap:
                    break
            current, current_len = overlap_words, sum(len(w) + 1 for w in overlap_words)
    if current:
        pieces.append(" ".join(current))
    return pieces
