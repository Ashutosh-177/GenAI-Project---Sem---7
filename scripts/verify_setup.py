"""Phase 0 sanity check — run this after setup to confirm every piece
of the stack is actually reachable before building on top of it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, TESSERACT_CMD


def check_anthropic():
    # Ollama was the LLM-reasoning backend originally (see Memory.md for
    # the full history); Q&A/drafting/summarization/classification all
    # moved to Claude via the Anthropic API, so this checks that instead.
    # Embeddings/retrieval/voice transcription are still local and
    # unaffected — no check needed here for those to change.
    if not ANTHROPIC_API_KEY:
        print("[Anthropic] ANTHROPIC_API_KEY is not set in .env")
        return False
    from generation.llm_client import chat
    reply = chat("Reply with exactly: OK", max_tokens=10)
    print(f"[Anthropic] model={ANTHROPIC_MODEL} test generation -> {reply.strip()!r}")
    return True


def check_tesseract():
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    version = pytesseract.get_tesseract_version()
    print(f"[Tesseract] version {version} at {TESSERACT_CMD}")
    return True


def check_pdf_parsers():
    import pdfplumber  # noqa: F401
    import pymupdf  # noqa: F401
    print("[PDF parsers] pdfplumber + PyMuPDF import OK")
    return True


def check_docx_tools():
    import docx  # python-docx  # noqa: F401
    import docxtpl  # noqa: F401
    print("[DOCX tools] python-docx + docxtpl import OK")
    return True


def check_embeddings():
    from sentence_transformers import SentenceTransformer
    print("[Embeddings] loading a small model to confirm the library works "
          "(NOT the production e5-large — that's a separate, slower download)")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    vec = model.encode("test sentence")
    print(f"[Embeddings] sentence-transformers OK, vector dim={len(vec)}")
    return True


def check_fastapi():
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
    print("[FastAPI] import OK")
    return True


if __name__ == "__main__":
    checks = [
        ("Anthropic (Claude)", check_anthropic),
        ("Tesseract", check_tesseract),
        ("PDF parsers", check_pdf_parsers),
        ("DOCX tools", check_docx_tools),
        ("FastAPI", check_fastapi),
        ("Embeddings (sentence-transformers)", check_embeddings),
    ]
    results = {}
    for name, fn in checks:
        try:
            results[name] = fn()
        except Exception as e:
            print(f"[{name}] FAILED: {e}")
            results[name] = False
        print()

    print("=" * 50)
    for name, ok in results.items():
        print(f"{'OK  ' if ok else 'FAIL'} - {name}")
