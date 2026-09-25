# AI Drafting & Knowledge Hub

An AI-powered platform that (1) answers questions over your own document corpus with
enforced citations, and (2) drafts formatted, print-ready legal/business documents —
Work Orders, MoUs, Agreements, and Proposals — complete with auto-generated
architecture/data-flow diagrams and AI-designed UI mockups.

Built originally as a PoC for a government RFP (Quality Council of India, tender ref.
QCI/0826/550), then pivoted into **Source Soft Solutions'** own branded drafting
platform. Both identities are supported via `generation/template_settings.py`; the
default branding is Source Soft Solutions.

## What it does

- **Conversational Q&A (RAG)** — ask a question in plain English, get an answer
  grounded in your ingested documents with numbered citations back to the source
  chunk. Three-layer guardrail against hallucination (see below).
- **Document drafting** — 13 templates across 4 document types (Work Order, MoU,
  Agreement, Proposal). Give it a short brief; Claude expands it into full narrative
  sections, grounded by retrieval and by explicit "known facts" (party names, project
  title) so it can't invent organisation names.
- **Diagrams from content, not hand-drawn** — architecture layer diagrams and
  Gane-Sarson data-flow diagrams (entities/processes/data stores) are derived from
  the proposal's own content and rendered deterministically with matplotlib, so text
  never garbles the way an image-generation model's text sometimes does.
- **AI-generated UI mockups** — for the Technical Proposal template, Claude writes a
  real self-contained HTML page for the product's home/admin screens, which gets
  screenshotted (headless Chrome) and embedded as an image — validated before use,
  with a template-based fallback if the screenshot doesn't look like a real page.
- **Document summarization** — map-reduce summarization for large ingested documents.
- **Voice input** — speech-to-text via faster-whisper (English, validated at 97%
  character accuracy; Hindi/Hinglish was built, tested against real recordings, found
  unreliable, and deliberately dropped rather than shipped broken).
- **PDF export** — one-click DOCX → PDF via Word automation.
- **Cost estimate before you generate** — drafting calls a paid LLM API; the UI shows
  an estimated cost (based on which fields will trigger a call) before you commit.

## Stack

| Purpose | Choice |
|---|---|
| LLM (drafting, Q&A, summarization, classification) | Claude (Anthropic API) — model configurable via `.env` |
| Embeddings | `intfloat/multilingual-e5-large` (local, sentence-transformers) |
| Vector store | Qdrant (local embedded mode, or a Docker container) |
| OCR | Tesseract |
| Voice transcription | faster-whisper |
| Document generation | docxtpl (Jinja-templated `.docx`) + python-docx for layout |
| Diagram rendering | matplotlib (deterministic, not image-generation) |
| AI mockup screenshots | headless Chrome |
| PDF export | docx2pdf (Word COM automation) |
| Demo UI | Streamlit |

Embeddings, vector search, and voice transcription run locally. Only LLM reasoning
calls (drafting text, Q&A answers, summaries, classification) go to the Anthropic API.

## Setup

```powershell
python -m venv venv
venv\Scripts\pip install -r requirements.txt
winget install UB-Mannheim.TesseractOCR
```

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` at minimum — everything
else has a working default (`QDRANT_MODE=local` needs no Docker to get started).

```powershell
copy .env.example .env
# edit .env, add your ANTHROPIC_API_KEY
```

Verify the stack is healthy:

```powershell
venv\Scripts\python.exe scripts\verify_setup.py
```

## Running it

```powershell
# ingest the sample/reference documents (parse + OCR fallback + chunk + embed + index)
venv\Scripts\python.exe scripts\ingest.py

# launch the demo UI — Conversational Search, Draft a Document, Summarize a Document
venv\Scripts\python.exe -m streamlit run scripts\demo_app.py
```

Open `http://localhost:8501`. Drafting and Q&A make real, billed API calls — the
drafting tab shows a cost estimate before you hit Generate.

### Optional: real Qdrant server instead of embedded mode

```powershell
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

Set `QDRANT_MODE=server` in `.env`, then re-run `scripts\ingest.py`.

## Project layout

```
ingestion/       parser.py (PDF/DOCX/XLSX/PPTX + OCR fallback), chunker.py,
                 classifier.py (document type/category), versioning.py
retrieval/       embedder.py (multilingual-e5), store.py (Qdrant wrapper)
generation/      rag.py (Q&A), drafting.py (template engine + narrative generation),
                 summarize.py, diagram_render.py, html_mockup.py, export.py (PDF),
                 voice.py, llm_client.py (shared Claude client), template_settings.py
  templates/     13 .docx templates (docxtpl Jinja placeholders)
guardrails/      fallback.py, citation.py, audit_log.py
scripts/         build_templates.py, demo_app.py, ingest.py, ask.py, draft.py,
                 verify_setup.py, and test_*.py scripts for each subsystem
data/
  samples/       reference government/business documents (see SOURCES.md)
  generated/     drafted .docx/.pdf output (versioned, gitignored)
  processed/     audit_log.jsonl
config.py        all env-driven settings, one place, not scattered
```

## Templates

**Work Orders:** Services · Goods/Supply · AMC
**MoUs:** Standard · International · Inter-Departmental
**Agreements:** Service · Consultancy · Licensing
**Proposals:** Technical (with diagrams + mockups) · Financial · Combined
**Plus:** a full 17-section Technical Proposal template modelled on real Source Soft
Solutions proposals, with architecture diagrams, data-flow diagrams, and UI mockups.

## Guardrails

**Q&A (`guardrails/`, `generation/rag.py`):**
1. Retrieval-score threshold — below a calibrated similarity score, skip the LLM
   entirely rather than answer on weak context.
2. LLM self-report — the model is required to say when the retrieved context doesn't
   support an answer.
3. Citation validation — every citation number in an answer is checked against the
   actual retrieved chunks, not trusted at face value.

**Drafting (`generation/drafting.py`):**
- Brief validation — rejects placeholder/too-short input before generation runs.
- Known-facts grounding — party/project names are stated explicitly in every prompt
  so the model can't invent plausible-sounding organisation names.
- Entity-leak detection — if a name from a reference document (used for tone only)
  leaks into generated output without being in the user's brief, the system detects
  it and regenerates with no reference grounding.
- Mockup screenshot validation — an AI-generated HTML mockup is rejected (falls back
  to a built-in template) if the resulting screenshot doesn't look like a real page.

Every Q&A interaction is logged to `data/processed/audit_log.jsonl`.

## Known limitations

- Hindi/Hinglish voice transcription was built and tested against real recordings,
  found unreliable (language auto-detection fails on code-switched speech), and
  deliberately dropped — English-only by design, not by oversight.
- No login/RBAC layer — out of scope for this PoC.
- No review/revise feedback loop on drafts yet — each draft is generated once.
- Retrieval-score threshold is calibrated against the current sample corpus and will
  need re-tuning as the real document corpus grows.

See `Memory.md` for the full build log, every bug found and how it was fixed, and the
reasoning behind each architectural decision.
