# Project Flow — AI Drafting & Knowledge Hub

## 1. Project Overview

An AI-powered platform that does two things for an organisation's document work:

1. **Conversational Q&A over your own documents** — ask a question in plain English
   and get an answer grounded in your ingested document corpus, with a numbered
   citation pointing back to the exact source chunk. No citation means no claim —
   answers aren't allowed to assert facts the retrieved context doesn't support.
2. **Automated document drafting** — generate formatted, print-ready Work Orders,
   MoUs, Agreements, and Proposals from a short brief. The drafting engine expands
   the brief into full narrative sections, auto-generates architecture and
   data-flow diagrams from the content itself, produces AI-designed UI mockup
   screenshots, and renders everything into a branded `.docx`/PDF.

It began as a proof-of-concept for a real government RFP (Quality Council of India,
tender ref. QCI/0826/550) and was later extended into a general-purpose branded
drafting platform (Source Soft Solutions identity). Both brand identities are
supported; branding is configurable, not hardcoded.

## 2. Technologies Used

| Layer | Technology | Why |
|---|---|---|
| LLM reasoning (drafting, Q&A, summarization, classification) | **Claude** (Anthropic API) | Handles all text generation and reasoning; model is swappable via `.env` (Sonnet for cost, Opus for quality) |
| Embeddings | **multilingual-e5-large** (sentence-transformers, local) | Turns text into vectors for semantic search; multilingual for English/Hindi content |
| Vector database | **Qdrant** | Stores document chunk embeddings; supports metadata filtering (document type/category) |
| OCR | **Tesseract** | Extracts text from scanned/image-only PDF pages |
| Voice transcription | **faster-whisper** | Converts spoken queries to text (English) |
| Document generation | **docxtpl** + **python-docx** | Jinja-templated `.docx` rendering with custom layout (letterhead, signature blocks, footers) |
| Diagram rendering | **matplotlib** | Deterministic rendering of architecture and data-flow diagrams — avoids the garbled text that image-generation models produce |
| AI mockup screenshots | **headless Chrome** | Screenshots LLM-authored HTML mockup pages for embedding into proposals |
| PDF export | **docx2pdf** (Word COM automation) | One-click DOCX → PDF |
| PDF/document parsing | **pdfplumber**, **PyMuPDF**, **python-docx**, **openpyxl**, **python-pptx** | Multi-format ingestion |
| Demo UI | **Streamlit** | Interactive web app for Q&A, drafting, and summarization |
| Backend language | **Python 3.12** | |

## 3. Project Workflow / Architecture

### Knowledge ingestion → retrieval (RAG) pipeline

```
Document (PDF/DOCX/XLSX/PPTX)
        │
        ▼
   Parse text ──── <40 chars native text? ──▶ OCR fallback (Tesseract)
        │
        ▼
   Chunk (1000 chars, 150 overlap)
        │
        ▼
   Classify (Claude: document_type + category)
        │
        ▼
   Embed (multilingual-e5-large)
        │
        ▼
   Store in Qdrant (with metadata: type, category, version)
```

### Conversational Q&A

```
User question
     │
     ▼
Embed question ──▶ Search Qdrant (top-K, cosine similarity)
     │
     ▼
Top-1 score < 0.78 threshold? ──▶ YES ──▶ "No information found" (LLM never called)
     │ NO
     ▼
Send question + retrieved chunks ──▶ Claude
     │
     ▼
Claude answers with citation markers, or self-reports "no info found"
     │
     ▼
Post-hoc citation validation (every citation checked against real retrieved chunks)
     │
     ▼
Answer shown to user + logged to audit_log.jsonl
```

### Document drafting

```
User fills structured fields + a short narrative brief per section
     │
     ▼
For each narrative field:
   Retrieve similar reference documents (tone/structure only)
     │
   Prompt Claude with: brief + known facts (party names, project title, stated
   explicitly so they can't be hallucinated) + reference text
     │
   Generate narrative text
     │
   Entity-leak check: did a name from the reference doc leak in that wasn't
   in the brief? ──▶ YES ──▶ regenerate with reference text stripped out
     │ NO
     ▼
Structured fields left blank (e.g. architecture layers)?
   ──▶ YES ──▶ Claude derives them from the already-generated narrative context
     │
     ▼
Render diagrams (matplotlib) from the structured data — architecture layers,
Gane-Sarson data-flow diagram (entities/processes/data stores)
     │
     ▼
Technical Proposal only: Claude writes self-contained HTML for UI mockups
   ──▶ headless Chrome screenshots it ──▶ validated (size/aspect-ratio/color
   checks) ──▶ embedded, or falls back to a built-in template if invalid
     │
     ▼
docxtpl renders the .docx (letterhead, signature block, footer, page border)
     │
     ▼
User downloads .docx, converts to PDF, or downloads mockups/diagrams as a zip
```

## 4. Key Features

- **Grounded Q&A with enforced citations** — three-layer guardrail (retrieval
  threshold, LLM self-report, post-hoc citation validation) prevents ungrounded
  answers rather than trusting the model's word alone.
- **13 document templates** across 4 types — Work Orders (Services/Goods/AMC),
  MoUs (Standard/International/Inter-Departmental), Agreements
  (Service/Consultancy/Licensing), Proposals (Technical/Financial/Combined), plus
  a full 17-section Technical Proposal template.
- **Content-derived diagrams** — architecture and data-flow diagrams are generated
  from what the proposal actually says, not hand-drawn or templated, and rendered
  deterministically so text never garbles.
- **AI-designed UI mockups** — real HTML written by the LLM, screenshotted, and
  validated before being embedded, with an automatic fallback if the result
  doesn't look like a genuine page.
- **Hallucination-prevention guardrails on drafting** — known-facts grounding
  (party/project names stated explicitly) and entity-leak detection (catches
  names from reference documents bleeding into generated text).
- **Cost estimate before every generation** — since drafting makes real, billed
  LLM calls, the UI shows an estimated cost based on which fields will trigger a
  call, before the user commits.
- **Voice input** — English speech-to-text via faster-whisper, validated at 97%
  character accuracy. (Hindi/Hinglish was built and tested against real
  recordings, found unreliable, and deliberately dropped rather than shipped
  broken — see `Memory.md`.)
- **Document summarization** — map-reduce summarization for large ingested
  documents that don't fit in a single LLM context call.
- **One-click PDF export** and a **downloadable zip of mockups/diagrams**
  alongside every generated document.
- **Full audit trail** — every Q&A interaction (question, retrieved chunks,
  answer, guardrail pass/fail) logged to `data/processed/audit_log.jsonl`.

## 5. How to Run the Project

```powershell
# 1. Set up the environment
python -m venv venv
venv\Scripts\pip install -r requirements.txt
winget install UB-Mannheim.TesseractOCR

# 2. Configure
copy .env.example .env
# edit .env and set ANTHROPIC_API_KEY (everything else has a working default)

# 3. Verify the stack is healthy
venv\Scripts\python.exe scripts\verify_setup.py

# 4. Ingest the reference documents
venv\Scripts\python.exe scripts\ingest.py

# 5. Launch the app
venv\Scripts\python.exe -m streamlit run scripts\demo_app.py
```

Open `http://localhost:8501` — three tabs: **Conversational Search**,
**Draft a Document**, **Summarize a Document**.

> Drafting and Q&A make real, billed calls to the Claude API. The drafting tab
> shows a cost estimate before you click Generate.

Optional — run Qdrant as a real server instead of embedded mode:

```powershell
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

Set `QDRANT_MODE=server` in `.env`, then re-run `scripts\ingest.py`.

For the full build history, every bug found and how it was fixed, and the
reasoning behind each architectural decision, see `Memory.md`.
