# QCI AI Knowledge Hub — PoC

Prototype for QCI's RFP (ref. QCI/0826/550): AI-powered Knowledge Hub & Workflow
Automation Platform. Scoped to **Pillars 2–4** (Knowledge Repository, AI Outputs,
Deployment/Ops) — login/RBAC (Pillar 1) deliberately deferred.

## Stack

- **LLM (local, non-Chinese):** Llama 3.2 3B via Ollama for dev iteration.
  Swap to Llama 3.1/3.3 or Mistral for quality checks once dev machine allows,
  and to AWS Bedrock / EC2-GPU inside QCI's account for actual deployment.
- **OCR:** Tesseract (printed text)
- **PDF/Doc parsing:** pdfplumber, PyMuPDF, python-docx, openpyxl, python-pptx
- **Doc generation:** docxtpl (templated `.docx` output)
- **Embeddings:** sentence-transformers (target: multilingual-e5-large)
- **Vector store:** Qdrant (client installed; server run separately, see below)
- **RAG orchestration:** llama-index
- **API:** FastAPI + uvicorn

## Setup (already done for this machine)

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
winget install Ollama.Ollama
winget install UB-Mannheim.TesseractOCR
ollama pull llama3.2:3b
```

Copy `.env.example` to `.env` and adjust if paths differ.

## Verify everything works

```
venv\Scripts\python.exe scripts\verify_setup.py
```

Checks Ollama connectivity + generation, Tesseract, PDF/DOCX parsers, FastAPI,
and embeddings — run this after any environment change.

## Project layout

```
ingestion/    - file parsing, OCR routing, chunking
retrieval/    - embedding + vector store + retrieval logic
generation/   - RAG Q&A, drafting engine (templates), citation enforcement
guardrails/   - hallucination checks, "no info found" / "access denied" logic
api/          - FastAPI endpoints
data/samples/ - test documents (gitignored — don't commit real QCI data)
scripts/      - setup/verification/one-off scripts
```

## OCR fallback — now validated

None of the 5 real sample docs ever triggered OCR (even the "scanned" 2001 circular
had native text), so this path was built but unproven. Closed the gap by
manufacturing a genuinely image-only PDF (`scripts/test_ocr.py` — rendered text
baked into a raster image, saved as PDF, zero text layer) with known ground-truth
content:

```
venv\Scripts\python.exe scripts\test_ocr.py
```

Results: the `<40`-char threshold correctly detected it as scan-like and routed
to Tesseract. Raw comparison scored 90.6%, but that number was noisy — OCR
preserves line-wrap newlines that the ground truth string doesn't have, which
`difflib` counts as edits. After normalizing whitespace, **real accuracy is
99.5%**, comfortably clearing the RFP's benchmark. The only actual misread across
the whole paragraph: capital **"I" → "l"**, twice, both times in "AI-powered" /
"AI-enabled" — the classic I/l/1 sans-serif ambiguity. Worth watching in
production since this corpus's subject matter means "AI" appears constantly.

## Not yet installed (needed for later phases)

- **multilingual-e5-large** — the production embedding model (~2GB download),
  intentionally not pulled yet; verify script uses a tiny model instead.
- **Llama 3.1 8B** — optional quality-check model, pull via `ollama pull llama3.1:8b`
  when needed (see RAM notes in project chat — close other apps first).

## Docker / Qdrant

**Working.** Root cause of the earlier "restart didn't fix it" issue: Windows
Fast Startup (`HiberbootEnabled=1`) makes "Shut down" hibernate the kernel
instead of truly restarting it, so the pending WSL feature install never
applied until an actual "Restart" was used. Post-restart: WSL2 came up clean,
Docker Desktop was launched, and Qdrant is running as a real container:

```
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

`.env` now has `QDRANT_MODE=server` (was `local`). Re-ran `scripts/ingest.py`
against it — same 304 chunks, confirmed via `scripts/query.py`. The local
embedded-mode data in `./qdrant_storage/` (the folder, not the Docker volume of
the same name) is now redundant and can be deleted once you're confident the
server mode is staying.

## Sample documents

5 real government/QCI PDFs in `data/samples/` (see `SOURCES.md` for provenance) —
covers a real QCI procurement doc, a Govt of India MoU, two tender/work-order
docs, and one older scan-quality circular for OCR testing.

## Phase 1 — Ingestion → Retrieval

```
venv\Scripts\python.exe scripts\ingest.py                    # parse + chunk + embed + index
venv\Scripts\python.exe scripts\query.py "your question" 5   # manual retrieval check, no LLM involved
```

Results so far (5 sample docs, 304 chunks, embedded Qdrant in `./qdrant_storage`):
top-1 cosine scores of 0.82–0.86, correct document discrimination, citations traceable
to exact source file + page. None of the 5 sample docs triggered the OCR fallback
(the "scanned" circular turned out to have native embedded text) — still need a
genuinely image-only PDF to validate that path before calling OCR done.

`retrieval/store.py` supports both `QDRANT_MODE=local` (current, embedded, no
Docker) and `QDRANT_MODE=server` (flip after restarting, points at the Docker
container) — same code either way.

## Status

- [x] Phase 0: repo, venv, Ollama + Llama 3.2 3B, Tesseract, verified
- [x] Docker Desktop + CLI installed (restart pending to activate)
- [x] 5 sample documents downloaded
- [x] Phase 1: ingestion pipeline (parse/OCR-fallback/chunk/embed/index) built and validated
- [x] Retrieval sanity-checked — strong scores, correct citations
- [ ] **Restart the machine** to activate WSL2/Docker, then switch `QDRANT_MODE=server`
- [ ] Find/create a real scanned (image-only) PDF to validate the OCR fallback path
- [x] Phase 2: RAG Q&A with citation enforcement + "no info found" guardrail
- [x] Phase 3: Document drafting engine (Work Order template)
- [x] Demo UI (Streamlit, both Q&A and drafting tabs) — `streamlit run scripts\demo_app.py`

## Phase 3 — Document drafting

```
venv\Scripts\python.exe scripts\test_draft.py    # non-interactive smoke test
venv\Scripts\python.exe scripts\draft.py         # interactive CLI
# or use the "Draft a Work Order" tab in the Streamlit demo
```

`generation/drafting.py`: fixed, deterministic field schema (not LLM-improvised —
a work order's required fields are procedural fact, not judgment) drives the
clarifying-questions flow; the LLM only expands two narrative sections (scope of
work, terms & conditions), grounded by retrieving similar ingested documents for
tone/structure. Auto-versions (v1, v2...) per work order number.

**Two real bugs caught by actually reading the generated output, not just
checking the file was created:**
1. `docxtpl` doesn't XML-escape substituted values — a bare `&` (e.g. "IT & Digital
   Initiatives") produced invalid XML that silently corrupted on read-back into
   "IT  Digital Initiatives". Fixed by escaping every string field before render.
2. The 3B model wrapped output in meta-commentary ("Here is a formal paragraph...",
   trailing "Note: consult a lawyer...") and fabricated a specific "10% penalty"
   figure despite being told not to invent numbers — same instruction-following
   gap as Phase 2's guardrail bug. Fixed with a stricter prompt (explicit
   "[to be specified]" instruction for unknown figures) plus a post-processing
   strip of known preamble/postamble patterns, same defense-in-depth approach as
   the Phase 2 guardrails rather than trusting the prompt alone.

## Phase 2 — RAG Q&A with guardrails

```
venv\Scripts\python.exe scripts\ask.py "your question"
```

Three-layer defense against ungrounded answers:
1. **Retrieval-score fallback** — below `RETRIEVAL_SCORE_THRESHOLD`, skip the LLM entirely.
2. **LLM self-report** — prompted to output exactly `NO_INFO_FOUND` when the excerpts don't support an answer (checked as substring anywhere in the response, not just a prefix — see finding below).
3. **Citation validation** — post-hoc check that the answer actually cited sources, and that every cited index maps to a real retrieved chunk (`guardrails/citation.py`).

Every interaction (question, answer, retrieved chunks, citations, guardrail pass/fail) is logged to `data/processed/audit_log.jsonl`.

**Finding from testing, not glossed over:** the naive version of this failed. Initial
`RETRIEVAL_SCORE_THRESHOLD=0.45` did nothing — on this corpus, clearly relevant
queries scored 0.80–0.87 and clearly *irrelevant* ones still scored 0.74–0.77
(multilingual-e5 cosine similarity isn't a calibrated relevance scale). An
off-topic question got past retrieval, and the 3B model then partially answered
one part of a multi-part question while burying `NO_INFO_FOUND` mid-response
around a fabricated citation — which the original `startswith()` check missed
entirely. Fixed by: raising the threshold to 0.78 (see `scripts/calibrate_threshold.py`,
flagged in config as corpus-specific and due for re-calibration as real data
comes in), checking for the token anywhere in the output, and instructing the
model to fully refuse rather than partially answer multi-part questions.
Retested against the same failure case — now catches cleanly.
