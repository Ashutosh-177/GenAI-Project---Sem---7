# Project Memory — Source Soft Solutions Drafting Platform

Single source of truth for this project. If context is ever lost, read this file
first — it should be enough to reconstruct everything: what this is, why
decisions were made, what's built, what's broken, what's left.

**Pivot, 24 Aug 2026 — full retarget from QCI to Source Soft Solutions,
an explicit user decision.** This project began as a PoC built specifically
for a real QCI government tender (still documented in full below, since the
architecture and every guardrail were proven against that RFP's real
requirements — none of that reasoning stopped being valid). It is now
Source Soft Solutions' own drafting platform. Concretely: default branding
(logo, navy #1F4E78, org name/address) across all 12 original templates
changed from QCI to Source Soft Solutions' real identity; a 13th template
(Technical Proposal) was added, modelled directly on 3 of Source Soft
Solutions' own real proposals rather than invented — see the dedicated
build-log entry below for what was benchmarked and how. QCI's own
requirements (the 4 Pillars, the RFP text, the non-Chinese-origin
reasoning) stay documented as-is below for historical/architectural
context, not because they still define the product's purpose.

Last updated: 24 August 2026 (Source Soft Solutions pivot — rebrand + Technical Proposal template with architecture/flow diagrams).

---

## 1. What this project is

Building a prototype/PoC for a real government tender:

- **Client:** Quality Council of India (QCI) — autonomous body under DPIIT,
  Ministry of Commerce and Industry, Govt. of India
- **Tender ref:** QCI/0826/550, dated 06.08.2026
- **RFP title:** "Engagement of an agency for design, development, deployment,
  implementation, and support of an AI-powered Knowledge Hub and Workflow
  Automation Platform for QCI"
- **Source doc:** `QCI.pdf` in the project root (31 pages, full RFP text)
- **Contract shape:** 1 year 9 months total (3mo deployment + 6mo warranty +
  1yr AMC). QCBS selection (70% technical / 30% financial). EMD ₹1.6L, PBG 5%
  of contract value. Min. 70/100 technical score to qualify.
- **Why we're building this:** to have a working PoC/demo ready for the
  technical presentation, which explicitly scores "Demonstration / PoC of
  solution proposed" (10 marks) under the Approach & Methodology criterion.

### The RFP's 4 Pillars (official scope structure)
1. **User Interface with Access Control** — login, RBAC, SSO, dashboards
2. **Knowledge Repository** — ingest, OCR, index, store, retrieve documents
3. **AI-Enabled Outputs** — conversational search+citations, summarization,
   document drafting (Proposals/MoUs/Agreements/Work Orders), iterative refinement
4. **Deployment, Operations & Support** — SIT/UAT, SLAs, monitoring, handover

### Our scope decision
**Deliberately skipping Pillar 1 (login/RBAC) for now.** Focus is Pillars 2–4 —
that's where the real technical risk and differentiation is. Pillar 1 is UI
plumbing that can be built later; it's not what proves the concept works.

Key RFP scale numbers to remember:
- Ingest up to **10,000 documents or 2TB**, whichever is higher (Milestone M4,
  not day one — comes after SIT/UAT)
- OCR accuracy benchmark: **≥90% character accuracy** on printed text
- Citations: **mandatory, minimum 1 per factual claim**
- 12 templates total: 3 each for Proposals, MoUs, Agreements, Work Orders
- Voice/text query in **English, Hindi, Hinglish**
- Data must **never leave QCI's AWS environment** (their own AWS account counts
  as "on-prem" per their own definition — the boundary is "not a 3rd-party API",
  not "not cloud")

---

## 2. Key architectural decisions (and why)

- **Local LLM, not an API** — Llama 3.2 3B via Ollama for dev. Explicitly
  **non-Chinese-origin** (ruled out Qwen/DeepSeek/Yi/GLM/InternLM) given the
  govt-tender data-sovereignty angle. Production target: Llama 3.3 70B /
  Mistral Large, self-hosted on AWS (EC2 GPU or Bedrock) inside QCI's account.
  **SUPERSEDED, 21 Aug 2026 — Ollama/llama3.2 removed entirely.** Done in
  two steps the same day: first drafting only, then (explicit follow-up:
  "whatever ollama was doing we will do using claude API") **all four**
  LLM-reasoning call sites moved to Claude via the Anthropic API —
  drafting (`generation/drafting.py`), conversational Q&A
  (`generation/rag.py`), summarization (`generation/summarize.py`), and
  ingest-time classification (`ingestion/classifier.py`). Shared client
  lives in `generation/llm_client.py` (one place for the client setup +
  the ThinkingBlock response-parsing fix, instead of four copies); it
  exposes `chat(prompt, max_tokens, system)`, where `system` maps to
  Anthropic's dedicated system-prompt parameter so rag.py's citation
  guardrails keep their instruction-following weight. `scripts/verify_setup.py`'s
  health check and the demo's sidebar model line were updated to match.
  **Still local and self-hosted (unchanged):** embeddings
  (multilingual-e5-large), vector search (Qdrant), voice transcription
  (faster-whisper) — the user explicitly asked to keep Whisper.
  Side benefit found while migrating: `summarize.py`'s `BATCH_CHAR_BUDGET`
  was 6000 chars, sized for a 3B model's small context window — raised to
  40000 for Claude, which collapsed a 17-chunk document from multiple
  map-reduce round trips down to a single call.
  All four verified working end-to-end after migration, not just imported:
  Q&A returned a correctly-cited answer, summarization produced a coherent
  1-batch summary, classification correctly tagged both an MoU and a
  Circular/NABH, and all 12 drafting templates rendered. **Flagged directly, not glossed over: this
  is a real conflict with the RFP text quoted in section 1 above** — "Data
  must never leave QCI's AWS environment... the boundary is 'not a 3rd-party
  API'." The Anthropic API is exactly a 3rd-party API; draft content (party
  names, contract values, project details) now leaves the machine. Fine for
  a demo/PoC to show drafting quality, but this line needs to be swapped
  back to a self-hosted model (or an in-VPC Bedrock/Claude deployment,
  which the RFP's own "AWS account counts as on-prem" carve-out might
  actually permit) before anything resembling a compliant submission.
  **Key-hygiene note**: the user pasted a live API key directly into chat
  twice, then put that same unrotated key into `.env` after being asked to
  rotate it, and explicitly confirmed proceeding with it anyway once the
  risk was flagged clearly — their informed call, not an oversight on
  either side. The key was never written into any git-tracked file or
  echoed back in full.
  **Real bug caught during first live integration test**: `response.content[0].text`
  crashed with `AttributeError: 'ThinkingBlock' object has no attribute
  'text'` — claude-sonnet-5 can return a thinking block before the text
  block, so content[0] isn't reliably the answer. Fixed with `_response_text()`,
  which finds the block by `type == "text"` instead of assuming position 0.
  Verified after the fix: all 12 templates render successfully through
  Claude (`scripts/test_all_templates.py`), and the known-facts party-name
  grounding guardrail (the original MoU hallucination bug fix) still holds
  — spot-checked real output, correct organisation names throughout, no
  regression from the model swap.
- **Pure inference, no fine-tuning.** RAG (retrieval-augmented generation) +
  prompting only. Reasoning: the knowledge changes too often for fine-tuning to
  make sense (documents added, HR data refreshed monthly); RAG is what actually
  satisfies the "100% citation" and "no hallucination" requirements (fine-tuning
  doesn't remove the need for grounding); and RAG keeps QCI's data cleanly
  separable from the model, which matters for the RFP's anti-vendor-lock-in
  clause (data/knowledge must be portable if QCI switches vendors).
- **Two separate models, not one:** the **embedding model**
  (multilingual-e5-large) turns text into vectors for search — no reasoning,
  just math. The **LLM** (Llama) does all actual generation/reasoning: Q&A
  answering, guardrail self-assessment, and (Phase 3+) drafting, clarifying
  questions, and eventually summarization/classification. Same LLM, different
  prompts per job — not different models per feature.
- **Qdrant** for vector storage — avoided Milvus (Zilliz, Chinese-origin) and
  BGE embeddings (Beijing Academy of AI) for the same non-Chinese-component
  reasoning as the LLM choice.
- **Tesseract** for OCR — avoided PaddleOCR (Baidu) and, when specifically
  evaluated, `baidu/Unlimited-OCR` (Baidu, built on DeepSeek-OCR — technically
  impressive, 24K+ stars, but Chinese-origin) for the same reason. If Tesseract
  accuracy ever becomes a real bottleneck at scale, the non-Chinese fallback is
  **docTR** (Mindee, France), not a Chinese alternative.
- **Deterministic guardrails over trusting the LLM's instruction-following.**
  Repeated lesson across both Phase 2 and Phase 3: a 3B model does NOT reliably
  follow "always do X" instructions — every guardrail needed a prompt fix AND a
  code-level post-processing check as a second line of defense. Don't trust
  prompt engineering alone anywhere citations, hallucination-prevention, or
  document correctness matters.

---

## 3. Machine / environment

- Windows 11, no prior git repo (project isn't under version control as of
  this writing)
- **Specs:** AMD Ryzen 7 7435HS (8c/16t), **RTX 2050 4GB VRAM**, ~16GB RAM —
  this is why Llama 3.2 3B was chosen for dev over 8B+ (8B needs ~7-8GB RAM,
  tight on this machine; 70B+ is AWS-GPU-only, never attempted locally)
- Project root: `D:\Grey Matterz\Govt RFP`
- Python 3.12.10, venv at `.\venv`
- **Windows "Fast Startup" gotcha (cost real time to diagnose):** `HiberbootEnabled=1`
  meant clicking "Shut down" hibernates the kernel instead of truly restarting
  it, so a pending WSL/Docker feature install sat unapplied for days despite
  multiple "restarts." Fix: use the actual **Restart** button (not Shut down +
  power on), or disable Fast Startup in Power Options. Confirmed working after
  a genuine restart — `wsl --status` and `docker ps` both clean now.

---

## 4. What's installed / running

| Tool | Version/detail | Status |
|---|---|---|
| Ollama | — | ✅ running, model `llama3.2:3b` pulled |
| Tesseract OCR | 5.4.0.20240606 | ✅ at `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| Docker Desktop | 4.86.0 | ✅ running (fixed after Fast Startup issue) |
| Docker CLI | 29.7.2 | ✅ |
| WSL2 | Default Version: 2 | ✅ working |
| Qdrant | via Docker container `qdrant` | ✅ real server, port 6333 (not embedded local mode anymore) |
| Streamlit | — | ✅ demo app at `http://localhost:8501` |

`.env` has `QDRANT_MODE=server` (switched from `local` once Docker was fixed).
The old embedded-mode data folder `./qdrant_storage/` (not the Docker volume of
the same name) is stale/redundant now — safe to delete.

---

## 5. Project structure

```
ingestion/       parser.py (PDF/DOCX/XLSX/PPTX + OCR fallback), chunker.py
retrieval/       embedder.py (e5, query:/passage: prefixes), store.py (Qdrant wrapper)
generation/      rag.py (Q&A), drafting.py (Work Order template engine)
  templates/     work_order_template.docx (docxtpl Jinja placeholders)
guardrails/      fallback.py, citation.py, audit_log.py
scripts/         ingest.py, query.py, ask.py, draft.py, test_draft.py, test_ocr.py,
                 demo_app.py, calibrate_threshold.py, build_templates.py, verify_setup.py
data/
  samples/       5 real downloaded govt/QCI PDFs (see SOURCES.md)
  generated/     drafted .docx output (versioned)
  ocr_test/      synthetic scan test PDF
  processed/     audit_log.jsonl
config.py        all env-driven settings, one place, not scattered
```

---

## 6. Build log by phase

### Phase 0 — Environment (done)
venv + full dependency set (torch, llama-index, qdrant-client, fastapi, docxtpl,
doc/OCR toolchain) installed clean. Ollama + Llama 3.2 3B, Tesseract via winget.
`scripts/verify_setup.py` confirms every component is wired up.

### Sample documents (done)
5 **real** (not synthetic) government/QCI PDFs downloaded — see
`data/samples/SOURCES.md` for exact provenance:
- `qci_eoi_consultant_zed.pdf` — real QCI procurement doc
- `mha_sample_mou.pdf` — real Govt of India MoU
- `crpf_tender.pdf`, `sameer_tender.pdf` — govt tender/work-order-style docs
- `dopt_scanned_circular_2001.pdf` — older circular (turned out to have native
  text despite looking scan-like — see OCR section below)

Some qcin.org links were dead (404 despite showing in search index) and
daman.nic.in refused connections — noted, not silently dropped.

### Phase 1 — Ingestion → Retrieval (done)
- **Bug fixed:** point IDs used Python's randomized `hash()` — would've
  created duplicate Qdrant points on every re-run instead of updating
  cleanly. Fixed to deterministic SHA-256-based IDs.
- OCR fallback threshold: <40 chars of native-extracted text on a PDF page
  triggers Tesseract instead.
- Result: 5 docs → 304 chunks. Retrieval scores 0.82–0.88 top-1, correct
  cross-document discrimination confirmed.

### Phase 2 — RAG Q&A with guardrails (done)
Three-layer defense: (1) retrieval-score threshold before even calling the LLM,
(2) LLM self-report (`NO_INFO_FOUND` token), (3) post-hoc citation validation.
Every interaction logged to `data/processed/audit_log.jsonl`.

**Two bugs caught by adversarial testing, not just happy-path testing:**
1. Threshold started at 0.45 — useless, since on this corpus relevant queries
   scored 0.80–0.87 and *irrelevant* ones still scored 0.74–0.77 (e5 cosine
   similarity isn't a calibrated relevance scale). Recalibrated to **0.78**
   based on actual measured data (`scripts/calibrate_threshold.py`) — flagged
   as corpus-specific, will need re-tuning at real scale.
2. The model buried `NO_INFO_FOUND` mid-response while still fabricating a
   citation (claimed a garbled OCR fragment named France's capital) — the
   original check only looked at the start of the string. Fixed: substring
   check instead of prefix check, plus a stricter prompt forcing all-or-nothing
   behavior on multi-part questions.

### Real bug found by an actual user, not testing (done, fixed)
A real user typed "Test" as the scope-of-work brief in the demo. The drafting
engine generated a full, specific, **wrong** scope of work — "renovate the
Sec-V office building at SAMEER Kolkata" — lifted directly from an unrelated
reference document (`sameer_tender.pdf`). Root cause: the scope-expansion
prompt says "use references for tone only, don't copy facts," but with a
near-empty brief the model has nothing else to write from, so it copies real
facts anyway. Same instruction-following gap as every guardrail bug before it,
except this one put **wrong content into a legal-shaped document**, not just a
formatting issue.

Fixed in three layers (`generation/drafting.py`):
1. `_validate_scope_brief()` — rejects too-short/placeholder briefs outright
   (< 3 words, or literal "test"/"tbd"/etc.) before generation even runs.
   Also fixed a latent bug this exposed: required fields with no default could
   previously be silently accepted as empty strings.
2. Much more forceful prompt language telling the model the reference examples
   are from "a COMPLETELY DIFFERENT, UNRELATED contract."
3. **Post-hoc entity-leakage detection** — extracts proper-noun-like phrases
   (2+ consecutive capitalized words) from the reference chunks, checks if any
   leaked into the output that weren't in the brief, and if so, silently
   regenerates with zero reference grounding rather than shipping contaminated
   content. Verified against the exact reported case (`scripts/test_scope_leak_fix.py`).

Demo UI (`scripts/demo_app.py`) also fixed to: show the validation error
instead of silently advancing, and show a proper identifying summary (work
order no. + project + contractor) after each generation plus a session history
list — previously only a bare filename was shown, making multiple drafts hard
to tell apart (also user-reported).

### Corpus expanded + real throughput measured (done)
Added 16 more real government PDFs (20 attempted, 4 honest failures/dead links)
spread across all 4 RFP document types (MoU, EoI/Proposal, Tender, Agreement)
plus more circulars — corpus now **21 documents, ~20MB, 2,273 chunks**
(`data/samples/SOURCES.md` has full provenance). Purpose: get **measured**
ingestion throughput instead of the earlier extrapolation from a 5-doc sample.

Result: 2,273 chunks in 1,378.5s wall time (~23 min) — **0.61 sec/chunk**,
~108 chunks/doc average (real docs are denser than the original 5-doc sample
suggested — one single "Model Tender Document" alone produced 555 chunks).
Extrapolated to 10,000 docs: **~7.6 days single-threaded on this laptop's
CPU** — slightly worse than the earlier ~6-day guess, a more honest number
now that it's grounded in real data rather than a small sample. Conclusion
unchanged, now evidenced: ingestion throughput (CPU-bound embedding) is the
real bottleneck at scale, not the vector database (2,273 chunks ≈ 9MB;
extrapolated 10K-doc scale ≈ 4.3GB — trivial for Qdrant).

Bonus: 3 of the new documents turned out to be genuinely scanned and
triggered real OCR (not just the synthetic test from before) — stronger
validation than the manufactured test alone.

Docker/Qdrant died again mid-task during this — 4th occurrence now. Same fix
each time (relaunch Docker Desktop, wait for daemon, `docker start qdrant`),
data always survives (named volume persists). Root cause still not fully
pinned down — registry autostart entry exists but doesn't reliably keep it
running through a session.

### Pillar 2 gaps closed: classification, versioning, file-size limit (done)
Explicit response to "let's complete Pillar 2 and Pillar 3":

- **`ingestion/classifier.py`** — LLM classifies every document once at ingest
  time into a `document_type` (Proposal/MoU/Agreement/Work Order/Tender/
  Circular/EoI/Other) and a `category` using **QCI's real board/division
  names** (NABL, NABH, NABET, NABCB, NBQP, PPID, NDIE, PADD, SPD — read
  directly from QCI.pdf, not a generic placeholder), matching the RFP's own
  "NABH vs. NABL" example of department-scoped access.
  **Real bug caught before it shipped at scale**: the model reliably dropped
  the `TYPE:` line entirely when asked for both fields in one combined-line
  format, so every one of the first 5 documents classified as "Other/
  Unclassified" — 100% failure, not genuine ambiguity. Confirmed via
  `scripts/debug_classifier.py`, fixed by parsing TYPE and CATEGORY as two
  independent regexes instead of one combined pattern. Re-verified across 5
  varied document types (5/5 correct) before re-running the full ingestion.
- **`ingestion/versioning.py`** + `delete_stale_chunks()` — re-ingesting a
  changed document bumps a version number (RFP: "last 3 versions retained")
  AND removes chunks that existed under the old version but not the new one,
  so a shrunk/restructured document doesn't leave stale, still-retrievable
  ghost chunks behind. Scoped deliberately: tracks version numbers + compact
  history, not full-content archival of every old version (would need a real
  blob store design).
- **`MAX_FILE_SIZE_BYTES`** (200MB, RFP spec) enforced in `scripts/ingest.py`
  — oversized files are skipped with a clear message, not silently attempted.
- Corpus expanded to 21 real documents (see "Corpus expanded" entry below),
  fully re-ingested with all of the above — 2,273 chunks, all now carrying
  document_type/category metadata. `retrieval/store.py` also gained
  `search(..., category=...)` filtering, `get_document_chunks()`, and
  `list_sources()` to support this and summarization.

### Pillar 3 additions: summarization, PDF export, 10 more templates (done)
- **`generation/summarize.py`** — map-reduce summarization (batch summaries
  -> combined summary) since large documents (the 555-chunk tender doc)
  don't fit a 3B model's context in one call. New "Summarize a Document" tab.
- **`generation/export.py`** — PDF export via `docx2pdf` (Word COM
  automation, same mechanism already proven for visual verification
  earlier), wired as a real product feature (download button) not just a
  testing tool.
- **All 12 templates built** (RFP: 3 each across Work Order/MoU/Agreement/
  Proposal — was 2/12, now 12/12). Required generalizing the drafting engine:
  `TemplateSpec`/`NarrativeField` dataclasses + one `render_document()`
  function replace what would otherwise be 12 near-duplicate render
  functions; `DraftSession` now takes a `fields` parameter instead of being
  hardcoded to Work Order. `scripts/build_templates.py` similarly gained a
  `build_generic_template()` + a data-driven recipe list instead of 10
  hand-written layout functions. Demo UI consolidated from 2 hardcoded tabs
  into 1 "Draft a Document" tab with a 12-way type selector.
  **Honest scope caveat**: the first 2 templates (Work Order, MoU) got deep
  adversarial testing — the scope-leak bug, the XML-escape bug, multiple
  rounds of visual PDF verification. The other 10 get the same *automatic*
  guardrails (leak detection, XML-escaping, meta-commentary stripping, brief
  validation — all generic now) plus a smoke test (`scripts/test_all_templates.py`,
  renders all 12 with realistic sample data, reports pass/fail per template),
  but not the same bespoke bug-hunting depth. Worth another pass before an
  actual submission, not before a demo.
  **Also flagged, not guessed past**: the RFP names "3 templates per type"
  but never specifies what distinguishes the 3 variants — the specific
  variants chosen (e.g. Work Order: Services/Goods/AMC) are a reasonable
  judgment call, not QCI's spec. Worth a pre-bid query (RFP has a built-in
  form for exactly this, Annexure-A) before an actual submission.

### Voice input (done)
RFP requires voice queries (English/Hindi/Hinglish) transcribed before
processing — previously untouched. Built `generation/voice.py` using
**faster-whisper** (OpenAI Whisper, MIT license, non-Chinese-origin — same
reasoning as every other component choice). Runs on CPU with int8 compute by
default since the GPU's already carrying Ollama on this machine's 4GB VRAM.
Wired into the Conversational Search tab via Streamlit's native
`st.audio_input` (in-browser mic recording, no extra JS) — transcribed text
joins the exact same `ask()` pipeline as typed input, not a separate path.

**Validated the same way as OCR** (`scripts/test_voice.py`): synthesized known
ground-truth speech via Windows SAPI TTS (only en-US voice installed on this
machine — no microphone available in this environment either), transcribed
it, measured real accuracy. Result: 97.0% character-level similarity —
**but the one actual error was "MoU" transcribed as "now"**, a domain-acronym
misread, not a trivial artifact. Worth watching in production since this
document domain is full of acronyms (MoU, NABL, SLA, AMC...) that a smaller
Whisper tier may mishear; a bigger model (`small`/`medium`) trades speed for
accuracy on exactly this kind of term. **Honest scope limit**: Hindi/Hinglish
transcription is built for (Whisper supports both) but NOT locally verified
the same rigorous way — no Hindi TTS voice available on this machine to
synthesize a test case. Flagged as untested, not assumed working.

**Follow-up, from a real user test, not synthetic:** recording a real question
live in the demo produced "What is the purpose of national emergency response
system of RMEU?" — "MoU" misheard as "RMEU" this time, with only 0.45 language
confidence, and it felt "very slow." Investigated both properly instead of
guessing:
- **Speed**: measured directly — model load is 1.6s (one-time), each
  transcription only 1.5-1.7s on the "base" tier. The "very slow" feeling was
  the demo having just been restarted (cold start) plus every other service
  competing for the same CPU, not a real per-call performance problem.
- **Accuracy fix attempt #1 (prompt bias) — failed, reported honestly**: added
  a `initial_prompt` with domain vocabulary (MoU, NABL, QCI, etc.) to bias
  Whisper's decoding. Re-tested against the same synthetic audio — zero
  improvement, "MoU" still misheard as "now" every time. Didn't claim this
  fixed it since it demonstrably didn't.
- **Accuracy fix attempt #2 (bigger model tier) — worked, verified with data**:
  tested `small` and `medium` tiers head-to-head. Both correctly transcribed
  "MoU" every run; `small` does it at 3.3s/query (vs. base's 1.6s — a small
  cost) while `medium` needed 214s just to load and 12.3s/query for no extra
  accuracy benefit over `small`. **Switched `WHISPER_MODEL_SIZE` default to
  `small`** (`config.py`) — real fix, backed by a controlled before/after
  comparison, not assumed to have worked.

**Second follow-up — a more serious gap, still open**: a real Hindi/Hinglish
question ("Mereko National Emergency Response System ke baare me batao") came
back as "Make one national agreement with this one system to run on the
public" — language auto-detected as English at 0.45 confidence (near
coin-flip) on audio that wasn't English at all, and the transcription bears
almost no relation to what was said. This is categorically worse than the
acronym-mishearing bug: not a wrong word, a wrong language entirely, likely
because Whisper's auto-detect struggles with code-switched speech (Hindi
grammar + an embedded English technical phrase) especially on a short (4s)
clip. **Not fixed yet** — couldn't be, since the demo transcribed-and-deleted
the audio, leaving nothing to debug against. Two things built in response:
1. `transcribe_audio()` now accepts an optional `language` hint ("en"/"hi")
   that skips auto-detect entirely when passed — wired into a new language
   selector (Auto-detect / English / Hindi) in the demo's voice expander.
2. Recorded audio is now **persisted** to `data/voice_test/user_recordings/`
   (gitignored — real voice data) instead of transcribed-and-deleted. Without
   this there was no way to build a real Hindi/Hinglish test corpus, only
   synthetic English TTS (which can't even be attempted for Hindi — no Hindi
   TTS voice on this machine, same limitation noted earlier). Real failing
   recordings can now accumulate for actual debugging instead of guessing.

Next step when there's a real recording to test against: try explicit
`language="hi"` forcing (skip the bad auto-detect guess), and/or test whether
a bigger tier helps with code-switched speech the way it did for the English
acronym case — neither attempted yet, both need real audio first.

### Full visual QA pass on all 12 templates — found and fixed 2 serious bugs (done)
Explicit response to "should it look perfect, and take more sample documents
for testing" — closed the gap where only 4 of 12 templates had ever been
visually inspected (the rest only passed a smoke test: rendered without
crashing, never actually looked at). Also expanded Agreement-type reference
coverage from 2 to 4 real documents (thinnest-covered type), and added a
skip-unchanged optimization to `scripts/ingest.py` (`ingestion/versioning.is_unchanged`)
so re-ingesting a mostly-same corpus takes ~6 min instead of ~20+.

Rendered and read all 8 previously-unchecked templates. Two real, serious bugs found:

1. **Work Order's Terms & Conditions section was rendering completely
   blank** in every draft the demo actually produces. Root cause: when the
   drafting engine was generalized into the `TemplateSpec`/`render_document()`
   system, only `scope_of_work_brief` got ported over as a `NarrativeField`
   — the original `_draft_terms_and_conditions()` function (which predates
   the generic system) never got wired back in. Found systematically, not
   just by luck: wrote `scripts/check_template_coverage.py`, which extracts
   every `{{ placeholder }}` from each `.docx` and checks whether anything in
   the spec actually populates it — confirmed this was isolated to
   `work_order_services` alone (the one template built before the generic
   system existed), all other 11 were fully covered.

2. **A document's own AI-generated body text used the WRONG party names** —
   an MoU correctly labeled "Quality Council of India" and "Ministry of
   MSME" in its metadata table came back with body text calling them
   "Department of Commerce" and "Quality Control Institute" (QCI actually
   stands for Quality COUNCIL, not "Control Institute" — a wrong acronym
   expansion, not a paraphrase). Root cause: the narrative-generation prompt
   only ever received the short user brief, never the actual party names —
   when a brief doesn't happen to name the parties, the model invented
   plausible-sounding Indian government bodies instead of using the real
   ones already sitting in the form data. A softer version of the same bug
   also showed up as an out-of-place "empanelment" reference in a completely
   unrelated IT-upgrade proposal (leaked from the EoI reference corpus) —
   the existing leak-detector didn't catch it because it only flags
   multi-word proper-noun phrases, not single domain words.

   Fixed with a `known_facts` mechanism threaded through
   `_generate_narrative_text`/`_expand_brief`/`_draft_terms_and_conditions`:
   every `NarrativeField` now declares `context_fields` (the party/subject
   names relevant to that section), and `render_document()` states them
   outright in the prompt as "use these names EXACTLY, verbatim." Applied
   to all 12 templates' narrative fields, not just the one that broke.
   **Caught and fixed a second-order bug from the fix itself**: the first
   version used raw field names as prompt labels (`department_a_name:
   Quality Council of India`), and the model literally echoed
   `(department_a_name)` into the output text. Fixed by humanizing the
   labels (`Department A Name`) and explicitly telling the model never to
   write a label itself — re-verified this specific fix before trusting it.

   Also retired `render_work_order()`/`render_mou()`/`_expand_scope_of_work()`
   entirely — they were a second, parallel implementation of the same logic
   the generic spec system provides, already drifted out of sync once (bug
   #1 above), which is exactly how that class of bug happens. Redirected
   their only remaining callers (`scripts/draft.py`, `test_draft.py`,
   `test_mou_draft.py`) to the unified `render_document()` path instead —
   one implementation now, not two that can silently diverge again.

   All three fixes re-verified empirically against the exact failure cases
   (`scripts/retest_bug_fixes.py`) before being called done, not assumed
   from the code change alone.

### Letterhead / branding (done)
Templates now carry QCI's real letterhead — logo extracted directly from
`QCI.pdf` page 1 (`assets/qci_logo_0.jpeg` full lockup, `assets/qci_logo_1.jpeg`
compact mark), not sourced elsewhere. Full lockup + address at the top, compact
mark above the signature block. `scripts/build_templates.py` has a shared
`_add_letterhead()` helper so every future template (MoU, Agreement, Proposal)
gets the same branding for free.

**Caught by actually rendering the document to an image, not just checking the
file saved:** the horizontal rule under the header, built from 95 literal
underscore characters, wrapped ugly onto two ragged lines in Word. Fixed with a
real paragraph bottom-border (`_add_bottom_rule()`, XML-level via `docx.oxml`)
instead of character art. Verified by converting the actual generated .docx to
PDF (via Word/`docx2pdf`) and rendering to PNG (`pymupdf`) to visually inspect
— confirmed clean before and after.

### Phase 3 — Document drafting engine (done, 1 of 12 templates)
Built the Work Order template only (of 12 total: 3 each for Proposals, MoUs,
Agreements, Work Orders) — proves the pattern, replicating to the other 11 is
mostly copy-paste of this same structure now.

Deterministic field schema drives clarifying questions (not LLM-improvised —
required fields are procedural fact). LLM only expands two narrative sections
(scope of work, terms & conditions), grounded by retrieving similar ingested
documents for tone/structure. Auto-versions (v1, v2...) per work order number.

**Two bugs caught by actually reading the generated .docx, not just checking
it existed:**
1. `docxtpl` doesn't XML-escape substituted values — a bare `&` (e.g. "IT &
   Digital Initiatives") produced invalid XML that silently corrupted on
   read-back into "IT  Digital Initiatives". Fixed: escape every string field
   (`xml.sax.saxutils.escape`) before rendering.
2. Same instruction-following gap as Phase 2: the model wrapped output in
   meta-commentary ("Here is a formal paragraph...", trailing "Note: consult a
   lawyer...") and fabricated a specific "10% penalty" figure despite being
   told not to invent numbers. Fixed with a stricter prompt (explicit
   "[to be specified]" instruction) **plus** a regex-based post-processing
   strip of known preamble/postamble patterns — prompt wording alone wasn't
   trusted, same lesson as Phase 2.

### OCR fallback validation (done)
None of the 5 real sample docs ever triggered OCR — even the "scanned" 2001
circular had native text. Closed the gap with `scripts/test_ocr.py`: manufactured
a genuinely image-only PDF (rendered text baked into a raster image, saved as
PDF, zero text layer) with known ground-truth content.

Result: fallback correctly triggered. Raw accuracy score 90.6% — but that was a
**comparison artifact** (OCR preserves line-wrap newlines, ground truth string
didn't have them; `difflib` counted those as edits). After normalizing
whitespace: **real accuracy is 99.5%**, comfortably clearing the RFP's ≥90%
benchmark. The only genuine misread in the whole paragraph: capital **"I" read
as "l"**, twice, both times in "AI-powered"/"AI-enabled" — the classic I/l/1
sans-serif OCR ambiguity, worth watching since this corpus's subject matter
means "AI" appears constantly.

### Template visual redesign (done) — font, logo size, signature blocks

User flagged the 12 generated `.docx` templates as unpolished: logo too big,
font not matching real documents, signature area not "managed properly."
Rather than guess, benchmarked against real evidence pulled from the sample
corpus and QCI's own RFP PDF (`QCI.pdf`) before changing anything:

- **Font: Calibri → Times New Roman, 11pt → 12pt.** Extracted embedded font
  names directly from PDFs (`page.get_fonts()` in pymupdf) rather than
  guessing from a rendered image. QCI's own RFP is Calibri throughout — but
  that's their house style for a 31-page narrative tender document with a
  dedicated cover page, not a signed instrument. The one real downloadable
  *legal template* in the sample corpus (`agreement_consultancy_template.pdf`,
  a LetsVenture Consultancy Agreement) is set in Garamond, a classic serif.
  Times New Roman is the same serif family and the universal Indian
  government/legal-document default, so it reads as "signed instrument"
  rather than "brand report" — the right register for Work
  Orders/MoUs/Agreements/Proposals specifically. Bumped to 12pt because Times
  New Roman's x-height is visibly smaller than Calibri's at the same size.
- **Logo: Cm(12) → Cm(5) in the letterhead.** Measured the actual logo bbox on
  QCI.pdf page 1 (`page.get_image_info()`): QCI's own full-width lockup is
  reserved for a dedicated, mostly-blank cover page. A real system-generated
  government portal document in the samples (`agreement_sla_manpower_gem.pdf`,
  a GeM SLA) uses a small top-of-page icon with a rule below, not a banner —
  and our templates are dense 1-2 page instruments with content starting
  right under the header, so a full-width lockup crowded everything below it.
  The compact signature-block mark (`LOGO_MARK`, Cm(1.6)) was already
  correctly sized and untouched.
- **Signature blocks redesigned against two real signed documents.** The
  LetsVenture Agreement signs off with **two stacked, unlabeled blocks**
  (Name:/Title:/Date:) and no witnesses. The NPC/KPMG MoU (a real signed
  government MoU) signs off with **two side-by-side "FOR AND ON BEHALF OF X"
  blocks**, each with a labeled Name/Designation line, **plus two numbered
  witness lines under each party**. Applied both patterns by document type:
  single-signatory docs (Work Order/AMC/Goods/Proposals) now use labeled
  "Name: ___ / Designation: ___" lines instead of bare placeholder text;
  dual-signatory docs (MoU/Agreement) use "FOR AND ON BEHALF OF" headers over
  labeled Name/Designation; and specifically the **3 MoU templates** (not
  Agreements — the real Agreement sample had none) got a new
  `_add_witness_block()` — two blank numbered witness lines per party,
  matching the real MoU exactly. Signatory *counts* per doc type (1 for
  unilateral Work Orders/Proposals, 2 for bilateral MoUs/Agreements) were
  already correct and didn't need to change.

Implementation lives entirely in `scripts/build_templates.py`
(`_set_body_font`, `_add_letterhead`, `_signature_lines`,
`_add_witness_block`) — no changes needed in `generation/drafting.py`, since
this was purely a `.docx` layout/typography concern. Rebuilt all 12 templates,
re-ran `scripts/check_template_coverage.py` (clean, all placeholders covered),
regenerated all 12 drafts via `scripts/test_all_templates.py`, and visually
verified two representative outputs (Work Order — single signatory; MoU
Inter-Departmental — dual signatory + witnesses) via docx2pdf + pymupdf
rendering. Both matched the intended design.

**Follow-up from user testing:** after generating a real Work Order in the
demo, the user asked why only one person signs it. Checked our own sample
corpus for the actual rule rather than guessing: `tender_model_document_goods.pdf`
(a GFR-based procurement manual, p.65) explicitly defines a Work Order as a
unilateral instrument, binding once "accepted/acted upon by the contractor"
— not a co-signed bilateral agreement, which is why only the issuing
authority's signature was collected. Real practice still records the
contractor's acknowledgment as a paper trail though, so added
`_add_issuer_acceptance_block()`: a two-column block with the issuer's real,
collected signatory on the left and a blank "Received & Accepted by / For
{{ contractor/supplier/vendor_name }}" acknowledgment slot (Signature/Name/Date,
left blank since that specific person isn't collected at drafting time) on
the right. Applied to all 3 Work Order-family templates (Services, Goods,
AMC) — **not** Proposals, which stay single-signatory since a proposal is
submitted unilaterally with no counterparty yet to acknowledge receipt.

**Footer added as a real Word footer, not a body paragraph.** User pointed
out the old "footer" (a body paragraph after the last section, reading
"Document version: vX | Generated by QCI AI Knowledge Hub (PoC)") only ever
showed up once, on the last page — not a real repeating page footer. Fixed
with `_add_footer()` writing to `doc.sections[0].footer`, plus a
`_add_field_run()` helper inserting live Word PAGE/NUMPAGES fields (not a
hardcoded page number), matching QCI's own RFP convention of "Page X of Y"
on every page. User then also questioned whether "Generated by QCI AI
Knowledge Hub (PoC)" was the most valuable use of that space — swapped it
for the document's own reference number instead (`Ref: {{ work_order_no }}`
etc.), since these are legal instruments that get printed/handled and a
real formal document repeats its reference number on every page for
traceability if pages get separated. For the 10 generic-builder templates,
the ref number is derived automatically from `metadata_rows[0][1]` (always
that document's own reference field) rather than threading a new parameter
through every recipe. Final footer: "Ref: {{ ref }} | Version {{ version }}
| Page X of Y". **Also fixed a real blind spot this surfaced**:
`check_template_coverage.py` only ever scanned `word/document.xml`, so
moving `{{ version }}` into the footer silently dropped it from the
checker's view without flagging a gap — fixed to also scan
`word/footerN.xml` parts.

**Justified body text — and a real bug the user caught in it.** Set
`Normal` style's default paragraph alignment to JUSTIFY (matches every real
sample: LetsVenture Agreement, QCI's RFP). First pass applied it globally
via the style default, which broke every signature block and metadata
table: Word only skips justifying a paragraph's *last* line, so any short
label text with an embedded line break (`_signature_lines()` — "Name:
X\nDesignation: Y") or any table cell narrow enough to wrap (e.g. "FOR AND
ON BEHALF OF Quality Council of India") got its non-final line's
word-spacing stretched across the full width — "Name:      Anjali
Verma"-style ugly gaps. User caught it from a live screenshot. Fixed with
two explicit-override helpers, `_set_left()` (paragraphs) and `_left_cell()`
(table cells), applied to every metadata table, signature block (single-,
dual-, and issuer/acceptance-style), witness block, and any `sections`
value containing an embedded `\n` (the short combo field-pairs like
"Delivery date: X\nDelivery location: Y") — leaving JUSTIFY to apply only
where genuinely intended: real long-form narrative paragraphs (scope of
work, terms & conditions, background, etc.) that wrap because they're
actually long. Re-verified visually on both the MoU-Interdept signature
page (previously broken) and a Work Order's Scope of Work paragraph
(genuinely justified, no stretching) after the fix.

**Same justify bug recurred on Terms & Conditions — user caught it in a
second live screenshot after the first fix.** `{{ terms_and_conditions }}`
renders as one single Word paragraph (soft line breaks separating the
LLM's own numbered headers from clause bodies, since
`_draft_terms_and_conditions_text()` explicitly prompts for "3-4 clauses"
and the model formats them with headers), so short header lines like "1.
Quality and Compliance Expectations" weren't the paragraph's last line and
got JUSTIFY-stretched — same root cause as the signature-block bug, just in
a runtime AI-generated field the earlier static-content fix couldn't see
(build_templates.py only knows the field is `{{ terms_and_conditions }}` at
build time, not that its rendered value will contain internal structure).
Fixed by explicitly left-aligning that one paragraph via `_set_left()`,
appropriate for a numbered-clause list rather than flowing prose. Other
narrative fields (scope_of_work, background, etc.) are prompted for plain
paragraphs, not clauses, and were re-confirmed still justified correctly —
left as-is, but if the same stretching recurs there, the same fix applies.

**Second full redesign pass — QCI's own house style, superseding the
"generic signed instrument" convention from the first pass.** User pointed
to a reference file ("QCI Sample.pdf", the RFP itself) and said the
drafted output should look like *that*, not what the templates currently
produced. Extracted the exact visual spec programmatically rather than
eyeballing it (`pymupdf`'s `get_drawings()` on the reference PDF): a full
black rectangular page border, an italic running header repeating the
document title on every page, and section headings as filled colour bars
— dark navy `#1F3864` with white bold text, read directly off the PDF's
fill-color drawing data (RGB 0.122/0.220/0.392), not guessed from the
screenshot. Implemented in `scripts/build_templates.py`:
`_add_page_border()` (section-level `w:pgBorders`), `_add_running_header()`
(a real `doc.sections[0].header`, using "[DOC TYPE] — [REFERENCE NO.]"
since our short instruments don't have a long fixed title like the RFP
does), and `_add_shaded_heading()` (paragraph shading via `w:shd`,
replacing every plain bold-black section heading across all 12 templates).
Font switched back from Times New Roman to Calibri, explicitly reversing
the earlier pass's reasoning — that choice was benchmarked against
signed-instrument samples (LetsVenture Agreement, NPC/KPMG MoU); this
directive is to match QCI's own document identity instead, which
supersedes it. Also fixed the same coverage-checker blind spot as before,
now for headers: `check_template_coverage.py` only scanned
`document.xml` + `footerN.xml`, so it couldn't see placeholders newly
added to the running header — extended to also scan `headerN.xml`.
Rebuilt all 12, coverage re-verified clean, regenerated, and visually
confirmed on both a 3-page Work Order (border/header/footer all repeat
correctly across pages, signature block intact) and an MoU (colour bars
correct) — closely matches the reference document's visual identity.

**Known pre-existing issue spotted during this visual pass, not yet fixed:**
the AI-drafted Terms & Conditions section renders its own sub-numbering
(e.g. "5. Quality and Compliance Expectations", "6. Timeline Adherence") that
doesn't restart at 1 under the parent "6. Terms & Conditions" heading — the
LLM brings its own numbering as part of the generated text in
`_draft_terms_and_conditions()`, unrelated to the template's own section
numbers. Cosmetic, not a data-correctness bug; flagged for a future fix.

---

## 7. How to run everything

```powershell
# activate venv first
.\venv\Scripts\python.exe scripts\verify_setup.py       # confirm stack is healthy
.\venv\Scripts\python.exe scripts\ingest.py              # parse+chunk+embed+index data/samples/
.\venv\Scripts\python.exe scripts\query.py "question" 5  # raw retrieval only, no LLM
.\venv\Scripts\python.exe scripts\ask.py "question"       # full RAG Q&A with guardrails
.\venv\Scripts\python.exe scripts\draft.py                # interactive Work Order drafting CLI
.\venv\Scripts\python.exe scripts\test_draft.py            # non-interactive drafting smoke test
.\venv\Scripts\python.exe scripts\test_ocr.py               # OCR fallback validation
.\venv\Scripts\python.exe -m streamlit run scripts\demo_app.py --server.headless true
# demo UI: http://localhost:8501 — two tabs, Conversational Search + Draft a Work Order

docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

---

## 8. Current status — what's done vs open

**Done:**
- Pillar 2 (Knowledge Repository): ingestion, OCR (validated), chunking,
  embedding, vector storage, **document classification (real QCI board
  taxonomy), source-document versioning + stale-chunk cleanup, 200MB file
  size limit** — essentially complete now
- Pillar 3 (AI-Enabled Outputs), half A: conversational search + citations +
  guardrails — complete
- Pillar 3, half B: document drafting — **all 12 templates built** (4 document
  types × 3 variants), though the last 10 got lighter testing than the first 2
  (see the Pillar 3 additions entry above for the honest caveat)
- **Summarization** (map-reduce for large docs) — built
- **PDF export** — built
- **Voice input** (English only, validated at 97% accuracy; Hindi/Hinglish was
  built, tested against a real recording, found unusable, and deliberately
  dropped rather than shipped broken — see the Build Log entry below) — built
- Demo UI: 3 tabs (Conversational Search with voice input, Draft a Document
  with a 12-way selector, Summarize a Document)

**Open gaps, not forgotten, just deferred by explicit choice:**
- **Pillar 1** (login/RBAC/SSO) — deliberately out of scope for the PoC
- **Pillar 4** (deployment/ops/SLA monitoring/dashboards) — untouched entirely
- **Phase 4** (HR batch ingestion, resource matching) — not started
- **Iterative refinement / review-approval workflow** for drafts — not built;
  each draft is generated once, no "revise based on feedback" loop yet
- **Citation-correctness verification** — guardrails check citation
  *presence*, not whether the citation actually supports the claim (found via
  the "SAMEER" mixup in multilingual testing)
- ~~Reliable Hindi/Hinglish generation~~ — **resolved by descoping, closed
  out with real evidence, not left an open question.** Sequence: (1)
  synthetic-TTS testing (`scripts/test_voice_hindi.py`, using Meta's
  open-weight non-Chinese-origin MMS-TTS since no Hindi voice exists on
  this machine — checked both legacy SAPI and OneCore) looked promising, a
  Hinglish sentence close to the real failure case scored 90.7% accuracy;
  (2) the user then recorded a REAL Hindi/Hinglish question through the
  demo and it transcribed as pure nonsense — proof synthetic TTS wasn't a
  reliable proxy for real speech here, despite looking fine in (1); (3)
  `scripts/debug_real_hindi.py` isolated the cause against that exact real
  recording by varying model tier (small/medium), the forced language
  hint, and the DOMAIN_PROMPT one at a time — every single combination
  produced nonsense, ruling out a tunable-parameter fix; (4) user made the
  explicit call to drop Hindi/Hinglish entirely rather than keep chasing
  it — `scripts/demo_app.py`'s voice tab now only offers English, with
  `language="en"` hardcoded rather than exposing a language picker.
  English alone stays genuinely validated at 97% (`scripts/test_voice.py`).
  This is the right kind of scope cut: reached only after building the
  feature, testing it for real, and confirming with a real recording that
  it doesn't work — not skipped from the start.
- **Backup/recovery** and **file server integration** (Pillar 2) — can't be
  meaningfully built without real AWS/QCI infrastructure; documented as a
  known limitation rather than mocked
- Scale-up plan for 10,000 docs/2TB is designed with **real measured data**
  now (21-doc corpus: 0.61 sec/chunk, ~7.6 days extrapolated single-threaded)
  but not implemented — current setup is single-machine, single-process

---

## 8b. The Source Soft Solutions pivot (24 Aug 2026) — full detail

**Trigger.** User said "forget QCI" and pointed at `New Index/` — 3 real
Source Soft Solutions technical proposals (CSIR Innovation Complex, ICAR-NRCC,
NIGST), asking for the company's own identity throughout and for the agent
to be able to produce architecture/flow diagrams. Confirmed scope with two
questions before touching anything, given the size of the pivot: (1) full
replacement of QCI identity, not an added brand option — confirmed; (2) which
of the two real TOC structures found in the PDFs to standardise on
(new-build vs. AMC/maintenance) — confirmed new-build (CSIR/ICAR-NRCC).

**What was extracted from the real PDFs, not guessed** (same "benchmark
against the real document" discipline as every other visual decision this
project has made): the real logo (`assets/sourcesoft_logo.png`, extracted
via `pymupdf` `get_images()`, 900×900 the highest-res copy found), the exact
navy brand colour `#1F4E78` (via `get_text('dict')` span colour on
"TECHNICAL PROPOSAL" and `get_drawings()` fill colour on the header rule —
both independently confirmed the same hex), the 5-colour architecture-diagram
palette (`get_drawings()` on NIGST p.7's layered-stack diagram), the real
"About the Company" profile/leadership text (page 2 of all three, word for
word), and the stable 8-section front-matter skeleton shared identically by
CSIR and ICAR-NRCC (About the Company → Executive Summary → Understanding →
Objectives → Compliance Matrix → Information Architecture → Solution &
Technology Architecture → Data Flow Diagrams) — the client-specific middle
sections (bespoke module lists, bilingual content models, etc.) were
deliberately NOT hardcoded into the generic template, since they're
inherently one-off per real engagement, not a reusable pattern.

**Rebrand** (`generation/template_settings.py`, `scripts/build_templates.py`):
`TemplateSettings` defaults and the renamed "Source Soft Solutions" built-in
preset (was "QCI Branded" — the stale `qci_branded.json` preset file was
deleted so it couldn't shadow the new default) now carry the real logo,
navy, org name, and 3-office address. `_add_letterhead()` was restructured
from one big pre-composed logo image (QCI's convention) to a side-by-side
icon + live bold-navy org-name text (matches Source Soft Solutions' real
header — their logo file is just the icon, with the name as a separate text
run next to it, not baked into the raster). `scripts/demo_app.py` had 15
literal "QCI"/"QCI Branded" UI strings — fixed all of them, including 5 that
referenced the old preset name and would have thrown `FileNotFoundError` on
click after the rename (real bug caught by grepping, not assumed fixed).

**New capability: Technical Proposal template with real diagrams**
(`build_technical_proposal_template()` + `TECHNICAL_PROPOSAL_SPEC`). Two
diagram types, both structured input rather than AI narrative text — a
diagram needs to know exactly how many boxes and what's in each, which
free-form prose can't guarantee:
- `_add_layered_architecture_diagram()` — stacked coloured-label / light-description
  rows, matching NIGST's real "Solution & Technology Architecture" diagram
  exactly. Driven by `architecture_layers`, a user-typed "Layer Name:
  Description" per line.
- `_add_flow_diagram()` — numbered process boxes joined by arrow glyphs,
  matching the real "DFD Level 1" rows. Driven by `data_flow_steps`, one
  step per line.

**Three real bugs found building this, all confirmed by actually rendering
and looking, not assumed fixed from the code:**
1. **TOC rendered empty.** `_add_shaded_heading()`'s paragraphs had no
   `w:outlineLvl`, and Word's `TOC \o "1-3"` field collects entries by
   outline level, not by "looks like a heading." Fixed by adding
   `w:outlineLvl` directly (not Word's built-in Heading style, which would
   have overridden the custom bar colour/font) — `outline_level=None` on
   the TOC's own heading so it doesn't list itself.
2. **Cover page silently lost its page border and running header.**
   `_add_section_break()` built a brand-new *empty* `w:sectPr` for the
   section boundary — in Word's model a paragraph-level `sectPr` describes
   the section *ending* there, so an empty one strips every section
   property (border, header, margins) from every page before it. Confirmed
   visually: page 4 had the border, page 1 didn't. Fixed by deep-copying
   the real body `sectPr` instead of building an empty one.
3. **`tpl.get_docx()` silently discarded the entire render.** Diagram
   injection needs to edit the document after `tpl.render()`; calling
   `tpl.get_docx()` for that access triggers docxtpl's `init_docx(reload=True)`,
   which — confirmed by reading docxtpl's own source after this produced a
   fully unrendered document, every `{{ field }}` back to raw text —
   reloads fresh from the original template file whenever `is_rendered` is
   True. Fixed by using `tpl.docx` directly (the already-rendered object;
   `save()` persists that same object) instead of calling `get_docx()`.
4. **Diagram table rows split mid-page**, fracturing box text across the
   page boundary (confirmed visually: "1.0 Citizen submits form" literally
   split, "form" landing on the next page). Word's default lets a table row
   break across pages; fixed with `_disable_row_split()` (`w:cantSplit`,
   not exposed as a high-level python-docx property) on every diagram row —
   a row now either fits entirely on the current page or moves entirely to
   the next.

**Marker mechanism, worth remembering if this needs extending**: the two
diagram placeholders in the template are literal text markers
(`[[ARCHITECTURE_DIAGRAM]]`, `[[DATA_FLOW_DIAGRAM]]`), deliberately NOT
`{{ }}` Jinja syntax — a `{{{{...}}}}`-style literal would be parsed by
docxtpl's Jinja engine as a malformed tag and crash `render()`. Caught by
reasoning through what Jinja would actually see in that string before ever
running a real render, and switched to `[[ ]]` — not found by trial and
error.

**Verified end-to-end**, not just unit-level: full render with real
multi-line architecture/flow-diagram input, converted to PDF, every page
visually inspected — cover page, About the Company (real leadership bios),
narrative sections, both diagrams intact on their own pages, signature
block. Then a full regression pass confirmed the other 12 original
templates (whose shared helpers — letterhead, section break, headings — all
changed) still build and render correctly.

**Follow-up, same day — diagrams now derived FROM the problem statement,
not hand-typed.** User's explicit ask: "it should be able to make
architecture, flow diagrams... accurately" from the proposal content, not
require the user to manually author the diagram structure. `architecture_layers`
/ `data_flow_steps` changed from required fields to optional (default `""`)
— when left blank, `_generate_architecture_layers()` / `_generate_flow_steps()`
derive the diagram FROM the already-expanded narrative context (executive
summary + understanding + objectives, the same text the rest of the
document uses), grounded with known_facts (client/submitted-by names),
constrained to the exact structured line format the existing parser
expects. Manual input still works if the user provides it — AI-generation
is the fallback, not a replacement.

Blocked mid-verification by a real, external condition: the Anthropic
account hit `credit balance too low` (confirmed via a bare 10-token test
call returning the identical error, not a code bug) — reported plainly
rather than worked around, since silently downgrading models to dodge a
billing block would hide the real signal from the user. Resumed once the
user topped up and rotated the key (now `claude-sonnet-5`, their own model
choice — the account switched from Opus to Sonnet, and the shared
`llm_client.py` fallback-degradation logic built earlier already handles a
model that doesn't support `fallbacks`, no code change needed).

Verified for real with the topped-up key: rendered CICM's actual real
engagement (client name + problem statement lifted from the real proposal
this template was benchmarked against) with both diagram fields left
blank. Confirmed visually — the AI-derived architecture correctly named
layers like "Application/API Layer" and "Admin/CMS Layer" with descriptions
specifically referencing "24 incubation labs" and "CICM staff," not
generic filler, and the flow diagram correctly sequenced the real enquiry-
handling process. One real polish issue caught from that same visual
check: the model's first attempt wrote flow-diagram steps as full
sentences ("The user fills out and submits the enquiry form on the
public-facing website"), making oversized diagram boxes — tightened the
prompt to explicitly require 2-5 word phrases ("these render as boxes in a
flow diagram, and a long phrase makes an oversized box"); re-verified the
retry produced consistent 3-word steps, still scenario-specific.

**Second follow-up, same day — 5 real layout bugs from a real generated PDF
the user downloaded and inspected (not from my own testing).** User gave a
real file path (`C:\Users\...\Downloads\technical_proposal_SSS_PROP_2026_003_v1.pdf`)
plus a reference screenshot of Source Soft Solutions' real footer — read
both directly rather than guessing at the complaints. All 5 confirmed and
fixed:

1. **TOC rendered as raw placeholder text**, not an actual table of
   contents. Word's TOC field only computes when told to (F9, or "update
   fields on open"). Fixed with `w:updateFields` in `word/settings.xml`
   (added in `_set_body_font`, so it applies to all 13 templates) — makes
   Word auto-refresh TOC/PAGE/NUMPAGES the moment it opens the file, which
   also fixes it for docx2pdf's PDF export since that goes through real
   Word via COM automation.
2. **"About the Company" overflowed onto an orphan page** — "Vikram Sharma
   — Solutions Lead" stranded as a bare heading at the bottom of one page,
   his bio alone on the next. Root cause was accumulated default paragraph
   spacing across ~15 separate one-line paragraphs (profile text, 8
   bullet deliverables, 3 leadership entries). Fixed two ways: the
   deliverables list is now a 2-column grid (also matches the real
   reference layout exactly, not just a spacing fix), and every paragraph
   on the page uses a new `_tight()` helper (trims `space_after`) — plus
   `w:keepNext` on each leadership name+bio pair as defense in depth.
3. **Both diagrams looked bad**: the architecture diagram split
   mid-diagram across a page boundary (last 2 of 6 layers stranded on the
   next page before "7. Data Flow Diagram", an ugly gap), and the flow
   diagram's boxes wrapped awkwardly (`cols_per_row=4` gave each box only
   ~2.8cm — even 3-word phrases wrapped 2-3 lines). Fixed: a new
   `_keep_row_with_next()` helper (`w:keepNext` on every paragraph in a
   row's cells) applied to all-but-the-last row of both diagram tables —
   `cantSplit` alone only stops a row breaking *within* itself, not the
   table breaking *between* rows. Flow diagram also dropped to 3 boxes per
   row (from 4) with explicit `Cm(4.2)` box / `Cm(0.9)` arrow column
   widths and `table.autofit = False` (fixed layout, not content-based
   autofit) — autofit was producing inconsistent column widths across
   otherwise-identical columns.
4. **Letterhead logo/name misaligned** on every body page — the org name
   rendered shifted away from the logo rather than sitting beside it as a
   lockup. Root cause: the 2-column table had `autofit = True` with only
   the first column's width set; Word's real autofit re-flowed the second
   column to something close to the full remaining page width when opened
   in actual Word (python-docx's own rendering doesn't show this — only
   caught because the user opened the real exported PDF). Fixed with
   explicit widths on BOTH columns, `autofit = False`, and
   `WD_ALIGN_VERTICAL.CENTER` on both cells so the single-line name sits
   level with the taller logo image instead of pinned to the top.
5. **Footer didn't match Source Soft Solutions' real proposal footer** —
   was reusing the other 12 templates' generic "Ref: X | Version | Page
   N of M" line. User's reference screenshot showed their real footer: a
   3-column office block (New Jersey HQ / Dubai / Noida, each with
   address + phone) under a rule, then a contact/confidentiality line with
   the page number. Built a new `_add_technical_proposal_footer()`
   specific to this template (the other 12 keep the Ref/Version/Page
   convention — that's still correct for signed legal instruments, this is
   a proposal, where the real document uses this format instead) — hit a
   real bug building it: used `doc.add_table()` instead of
   `footer.add_table()`, which appends to the main document BODY
   regardless of what section is conceptually being built (python-docx has
   no notion of "currently in a footer") — confirmed from a real render,
   where the entire 3-office block landed on the LAST page of the
   document, after the signature block, while the footer stayed a single
   bare line. `footer.add_table()` also needs an explicit `width=` argument
   unlike `Document.add_table()`, which derives one from page margins
   automatically.

**One regression caught and fixed within this same round**: the new
footer's extra height (3-office block + contact line, ~6 lines vs. the
old single line) shrank every page's usable body height enough that the
cover page's own content spilled a near-empty line onto page 2, pushing
TOC to start on page 3 instead of page 2 — a genuinely new blank page that
wasn't there before. Caught by re-inspecting the fixed render rather than
assuming the fix was complete once each individual issue looked right in
isolation. Fixed by trimming the cover page's blank spacer paragraphs
(`_tight()` again, plus removing one redundant top spacer).

All 5 fixes plus the regression re-verified visually against a real
generated PDF (not just python-docx's report that it saved successfully):
TOC now shows real section names and page numbers, About the Company
fits entirely on one page with all 3 leadership entries intact, both
diagrams render as complete single-page units with no wrapping, the
letterhead logo and org name sit correctly aligned, and the footer matches
the real reference on every page. Per an explicit user instruction this
round, only the Technical Proposal was regenerated as a real document —
the other 12 templates were rebuilt as scaffolding (`build_templates.py` +
`check_template_coverage.py`, both clean) but not rendered/filled, so
their real-world rendering after the shared `_add_letterhead`/`_set_body_font`
changes remains to be visually re-confirmed.

### Third follow-up (24 Aug 2026) — image-based diagrams, leadership photos, Opus

User showed 5 reference images (sitemap, layered-architecture, DFD L0/L1,
a module-feature table, a phase timeline) as the visual bar to hit, and
asked for: (1) leadership photos on the About page, (2) genuinely
accurate/good-looking diagrams, (3) Claude Opus for content generation,
(4) a cost estimate, (5) more pictorial content generally (tables,
diagrams, wireframes) throughout the draft.

**Root cause of "diagrams are bad as hell" even after the prior fix
round**: they were Word tables with shaded cells — no real borders per
box, no arrowheads, unreliable wrapping. A table can only ever look like
a flat colored grid, not a real boxes-and-arrows diagram. Fixed by adding
`generation/diagram_render.py`, a new standalone module that renders
diagrams via matplotlib to PNG (rounded "card" boxes with a colored left
accent bar, wrapped description text, `FancyArrowPatch` arrows with real
arrowheads) and embeds them as pictures using the same `add_picture`
pattern the logo already used — `matplotlib` added to `requirements.txt`
(wasn't a dependency before). All layout math is done in "inches as data
units" (`ax.set_xlim(0, fig_w)` with `fig.add_axes([0,0,1,1])`) so the
saved PNG's aspect ratio is exact and callers only need to set width in
the docx; height follows automatically.

Three diagrams: `render_architecture_diagram` (vertical stack of layer
cards, arrows between), `render_flow_diagram` (numbered process boxes,
wraps to further rows), `render_timeline_diagram` (phase cards with a
week-range header — brand new, no prior equivalent existed). Also
`render_initials_avatar` for leadership photo placeholders.

**Bug found and fixed while building the flow-diagram row-wrap
connector**: first attempt used `FancyArrowPatch(connectionstyle="angle,
angleA=0,angleB=90,rad=6")` for the elbow between the last box of one row
and the first box of the next. `rad=6` is enormous relative to the
diagram's inch-scale coordinates (whole diagram is ~7×3 inches) — the
corner-rounding radius swallowed the entire path and the arrow rendered
in the wrong place (appeared as a vertical line under column 0 instead of
connecting the actual two boxes). Caught by rendering a standalone test
image and visually inspecting it before wiring into the real pipeline —
same "verify before integrating" discipline as everything else in this
project. Fixed by dropping the "angle" connection style entirely in favor
of a plain straight-line arrow between the two box centers
(`_diagonal_arrow`) — simpler, no `rad` tuning needed, and unambiguous.

**Wiring changes**: `build_templates.py`'s `_add_layered_architecture_diagram`/
`_add_flow_diagram` now take the marker *paragraph* directly (not `doc`)
and embed the rendered PNG straight into it, replacing the old
"grab `doc.tables[-1]` and reposition the XML node" trick that only
worked for tables. New `_add_timeline_diagram` follows the same pattern.
`drafting.py`'s `_inject_diagrams` signature grew a `timeline_phases`
param; new `_generate_timeline_phases`/`_parse_timeline_phases` pair
mirrors the existing architecture/flow generate+parse functions exactly
(same "derive from problem statement, structured pipe-delimited output"
approach), except pipe-delimited (`Phase Name | Week range | description`)
rather than colon-delimited, since a timeline description is free prose
that legitimately contains colons. New `[[TIMELINE_DIAGRAM]]` marker
added after the `{{ methodology }}` paragraph in section 8. New optional
`implementation_timeline` field in `TECHNICAL_PROPOSAL_FIELDS` (blank →
auto-generated, same convention as the other two).

**Leadership photos**: `_resolve_leadership_photo()` in
`build_templates.py` looks for a real file at
`assets/leadership/<slug>.(jpg|jpeg|png)` (slug = lowercased name with
spaces→underscores, e.g. `alok_dharayan.jpg`) and uses it if present;
otherwise generates a navy-circle initials placeholder via
`render_initials_avatar`. No real photos of Source Soft Solutions'
leadership exist anywhere in this repo — what renders today is the
placeholder. Each leadership entry changed from plain paragraphs to a
borderless 2-column table (photo | name+bio), same construction pattern
as `_add_letterhead`'s logo/name row, with `_disable_row_split` +
`_keep_row_with_next` so a card can't be split or stranded across a page
boundary. Verified visually: About the Company page still fits on one
page with all 3 photo cards intact.

**Claude Opus**: `config.py` already defaulted `ANTHROPIC_MODEL` to
`claude-opus-5`, but `.env` was pinned to `claude-sonnet-5` (from the
earlier context-window/credit-conservation period) — that's the actual
override in effect. Changed `.env` to `claude-opus-5`. This is a single
global switch (`llm_client.chat()` has no per-call model override) — it
affects every LLM call in the app, not just proposal drafting.

**Cost estimate given to the user** (from a live pricing search, not
memorized numbers — Opus 5: $5/M input, $25/M output tokens; Sonnet 5:
$2/M input, $10/M output): a full Technical Proposal draft makes ~12-15
LLM calls (one per narrative section + diagram-content generation), at
roughly ~2K input / ~600 output tokens per call → about $0.15/proposal on
Sonnet vs ~$0.35-0.40/proposal on Opus. The user's existing account
recharge covers hundreds of drafts either way.

**Explicitly scoped OUT of this round** (flagged to the user, not
silently dropped): a real sitemap/information-architecture tree diagram
for section 5 (currently still plain `{{ information_architecture }}`
text), proper DFD notation with distinct external-entity/process/data-store
shapes (the flow diagram is still a linear numbered chain, not true DFD
Level 0/Level 1 structure), and a "Modules & Features" table section
(seen in the reference images but not part of the current template's
section skeleton at all). These are new content/structure, not fixes to
what exists, and were judged too large to fold into this same pass.

Verified end-to-end: rendered the same NIGST scenario used in prior
rounds with hand-typed structured diagram input (fast/free), confirmed
visually via PDF — About page (photos + one-page fit), architecture
diagram, flow diagram (including the fixed row-wrap connector), timeline
diagram, TOC, and footer all correct across 10 pages. Separately
confirmed the AI-derivation path works end-to-end on Opus: a live
`_generate_timeline_phases()` call produced correctly-parseable
pipe-delimited output.

### Fourth follow-up (24 Aug 2026) — real leadership photos + full 17-section
### template rebuild against the real reference PDF

User provided 3 real headshot photos (pasted into chat, found via a
Windows temp-file/screenshot search since there's no direct
"save pasted image" tool — `C:\Users\ashut\Pictures\Screenshots\Screenshot
2026-08-24 17011*.png`, matched to Alok Dharayan/Vijay Konar/Vikram Sharma
by timestamp order) and copied them to `assets/leadership/<slug>.png`
(`alok_dharayan.png`, `vijay_konar.png`, `vikram_sharma.png` — slug =
lowercased name, spaces→underscores, matching `_resolve_leadership_photo`'s
lookup exactly). These are picked up automatically on the next render —
no code change needed, `_resolve_leadership_photo()` already checked for
real files before falling back to the initials placeholder.

**The bigger ask**: user said most of the document is still prose, not
tabular/pictorial, and pointed at `New Index/CSIR_Innovation_Complex_
Technical_Proposal.pdf` — "all the fields mentioned here should come in
drafts... everything... tabular, mocks, diagrams". Extracted the real
document's full structure (`pymupdf`, regex for numbered headings): **17
sections**, not the 9 this template had. Missing entirely: section 4's
Compliance Matrix was prose (should be a real table), section 5's
Information Architecture had no sitemap diagram, and sections 8-14 and 16
(Modules & Features, a core-module walkthrough, Admin CMS Portal,
Enquiry & Notification, Security/Hosting/Compliance, Multilingual/SEO,
**UI Design Concepts & Mock Screens**, Annual Maintenance) didn't exist
in the template at all. Section 14 is literally wireframes/mockups —
directly what "no wireframes" was pointing at.

**Generalizing client-specific real content**: the real doc's section 9
is "The 24 Incubation Labs Module" (CICM-specific); this template can't
hardcode that for every client, so it became a generic "9. Core Platform
Module" — the same *shape* (a centrepiece-module user-journey flow
diagram) with content derived per-engagement instead of copied from CICM.
Same treatment for Admin CMS roles, security certifications, etc. — the
structure is real, the specific content is generated per problem
statement.

**New rendering infrastructure** (`generation/diagram_render.py`):
- `render_sitemap_diagram(site_name, pillars, ...)` — title bar, down
  arrow, N pillar columns each with a bulleted sub-page list. Matches the
  reference's Information Architecture diagram almost exactly.
- `render_ui_mockup(kind, heading, ...)` — a low-fidelity browser-frame
  wireframe. `kind="public_home"`: chrome bar, nav, hero with 2 CTA
  buttons, 3-card row (icon-circle + placeholder text-line bars).
  `kind="admin_dashboard"`: sidebar nav, 4 stat cards, a table skeleton.
  This is genuinely new ground — nothing like it existed before; it's
  what section 14 (UI Design Concepts & Mock Screens) embeds.
- `build_templates.py` gained 4 new generic helpers used across most of
  the new sections rather than one bespoke function per section:
  `_add_data_table` (navy-header striped Word table — compliance matrix,
  modules table, roles table, enquiry table, security table, SEO table,
  AMC table all reuse this one function), `_add_feature_grid` (bordered
  tile grid — admin capabilities), `_add_sitemap_diagram_image`,
  `_add_ui_mockup_image` (both wrap `_embed_diagram_image`, same pattern
  as the existing architecture/flow/timeline diagrams).

**Two real bugs found and fixed while building this, both caught by
rendering standalone test images before wiring into the real pipeline —
same discipline as every fix this project has made**:
1. **matplotlib/freetype silently drops text below ~8pt at 200dpi with
   this font** — the admin-dashboard mockup's stat-card labels
   ("Enquiries", "Content Items", "Pending") rendered as nothing at all,
   and "Uptime" rendered as a stray "ti" fragment (the middle of the
   word — an edge-of-failure case, not fully dropped). Root cause
   isolated with a minimal reproduction (varying only fontsize) — sizes
   8/9.5/12 rendered fine, 6.8 silently vanished. No matplotlib
   warning/error is raised; it just doesn't draw. Fixed by auditing every
   `fontsize=` in `diagram_render.py` and raising anything under 8.0pt.
   Take-away for any future diagram work in this module: **never go below
   8pt**, regardless of how cramped a label seems — it won't just look
   small, it will disappear.
2. **UI mockup nav bar / hero heading overlapped with long project
   titles** — a real title like "CSIR Innovation Complex Website
   Redevelopment & Incubation Portal" (67 chars) ran straight into the
   nav's "Home" item, and the hero "Welcome to {heading}" line extended
   past its box on one unwrapped line. Fixed with a `_truncate()` helper
   for the nav-bar brand text and chrome-bar URL slug (hard character
   limits — there's no room to wrap in a single nav bar row), and
   `_wrap()` (existing helper) for the hero heading, which has room to
   become 2 lines — with the placeholder body-text and CTA buttons
   below it repositioned to key off the actual wrapped-heading height
   instead of a fixed offset, so they don't collide when the heading
   wraps.

**Field/content wiring** (`generation/drafting.py`): added
`_generate_structured_lines()` — one shared driver for every new
"derive structured content from the problem statement" field, taking
task-specific instructions text as a parameter, rather than 11 near-
duplicate `_generate_*` functions (the pattern the original three
diagrams established). Paired with `_parse_pipe_rows()`, a shared
pipe-delimited parser (pipe, not colon, since these descriptions
legitimately contain colons — same reasoning as the timeline phases
parser). 11 new structured fields (`compliance_items`,
`sitemap_pillars`, `modules_features`, `core_module_flow`,
`admin_capabilities`, `admin_roles`, `enquiry_channels`,
`security_flow`, `security_areas`, `seo_performance_items`,
`amc_scope`) and 7 new narrative `_brief` fields (one prose intro per
new section) added to `TECHNICAL_PROPOSAL_FIELDS`, all following the
established "leave blank to auto-generate" convention. `_inject_diagrams`
renamed to `_inject_generated_content` and rewritten to take one
`content` dict instead of a positional arg per diagram — the old
per-diagram-argument signature doesn't scale to 16 markers ((3 original
diagrams + sitemap + 2 mockups + 2 flow diagrams) as images, (7 tables +
1 feature grid) as native Word tables inserted the same way the original
table-based diagrams used to be, before they were switched to images).

**Cost impact**: roughly doubled the number of LLM calls per Technical
Proposal draft (~12-15 → ~25-30, one per brief + one per structured
field that's left blank), so the per-document Opus cost estimate from
the previous round (~$0.35-0.40) roughly doubles too (~$0.70-0.80) — see
[[cost estimate note above]] for the underlying per-token pricing. Still
cents per document.

Verified end-to-end: rendered a full CSIR Innovation Complex example
(the same scenario as the reference PDF) with hand-typed structured
content for every new field (fast/free — avoids re-paying for LLM calls
on every verification pass) but real Opus-generated prose for all 23
narrative brief fields. Confirmed visually via an 18-page PDF: all 17
TOC entries with correct real page numbers, compliance matrix (5 rows,
correct columns/shading), sitemap diagram (5 pillars, bulleted
sub-items), modules table, core-module flow diagram, admin CMS feature
grid + roles table, enquiry table, security flow diagram + table, SEO
table, both UI mockups (post-fix, no overlap), timeline diagram, AMC
table, and the final deliverables page — every new section renders
correctly and matches the reference document's structure. Output:
`data/generated/technical_proposal_SSS-PROP-2026-011_v2.docx`.

**Not done this round** (true DFD notation with distinct entity/process/
data-store shapes, rather than the current linear numbered-box chain
reused for both the original Data Flow Diagram and the new core-module/
security flows) — the reference document's actual DFD Level 0/Level 1
notation (external entities as separate boxes, numbered processes,
labelled data stores, directional flow) is a different diagram grammar
than the "numbered chain" this template uses everywhere; flagged, not
attempted, given how much else this round already covered.

### Real production failure (24 Aug 2026) — 529 Overloaded crashed the app mid-draft

User ran the app themselves (`streamlit run scripts/demo_app.py`, filling
in a Technical Proposal by hand from the walkthrough example given
above) and hit `anthropic.OverloadedError: 529 Overloaded` on one of the
~25-30 sequential LLM calls a full draft now makes (grew from ~12-15
after the 17-section rebuild — more calls means more surface area for
hitting a transient overload mid-run). This crashed the whole Streamlit
app to a raw Python traceback — bad on its own, worse because it happens
after 20+ already-succeeded, already-paid-for LLM calls get thrown away
with no way to resume mid-draft.

Two-part fix:
1. **`generation/llm_client.py`**: added `_call_with_retry()` — wraps
   both `client.beta.messages.create` and the plain-fallback
   `client.messages.create` calls with exponential backoff + jitter (5
   attempts, base delay 2s) on `anthropic.APIStatusError` where
   `status_code` is in `{429, 500, 502, 503, 529}`, and on
   `anthropic.APIConnectionError` unconditionally. Anything else (400
   bad request, refusal, auth) raises immediately on the first attempt —
   retrying a permanent failure just wastes time reproducing it. Verified
   against the real anthropic SDK's exception hierarchy
   (`venv/Lib/site-packages/anthropic/_exceptions.py`): `OverloadedError`
   is a real `APIStatusError` subclass with `status_code=529` (confirmed
   by reading the source, not assumed), so `except APIStatusError as e:
   e.status_code` reliably catches it. Tested with a mocked flaky client
   (real `httpx2.Response` objects, not hand-faked): retry-then-succeed,
   non-retryable-raises-immediately, and exhausts-then-raises all
   verified correct before touching the real pipeline.
2. **`scripts/demo_app.py`**: wrapped the `render_fn(session)` call (the
   one that had crashed) in try/except — on failure, shows `st.error(...)`
   with a readable message and `st.stop()`, instead of Streamlit's raw
   traceback page. Collected answers survive a failed render (they live
   in `st.session_state`, untouched by the exception), so the user can
   just click Generate again — the retry wrapper above should make that
   rarely even necessary now, but this is the backstop for when retries
   are exhausted or a genuinely different error occurs.

### Real production bug (24 Aug 2026) — stale preset JSON files still had QCI branding

User rendered a real Technical Proposal via the Streamlit app and got
"Quality Council of India" in the letterhead and a completely missing
About the Company section (`technical_proposal_SSS_PROP_2026_003_v1.pdf`
— note underscores in the proposal number, meaning the user typed this
directly into the webpage, not one of my hyphenated example scenarios).

**Root cause**: `data/template_presets/dark_mode.json`,
`executive_crimson.json` and `light_mode.json` had been materialised to
disk back when their in-code factory functions (`_dark_mode()` etc. in
`generation/template_settings.py`) still set
`organisation_name="Quality Council of India"` — before the Source Soft
Solutions rebrand. The dataclass default and every factory's definition
were fixed correctly months ago (`organisation_name: str = "Source Soft
Solutions"`), but `load_preset()` checked for an existing JSON file
FIRST and returned it verbatim if found, never re-deriving from the
current (correct) in-code factory. So the code fix silently stopped
applying to these 3 built-in presets the moment each was first loaded
once, pre-rebrand — with no error, no warning, just quietly wrong output
forever after. `_add_about_company_page()` only renders real About-page
content when `settings.organisation_name.strip().lower() ==
"source soft solutions"` (falls back to an empty/near-empty page
otherwise, by design — see the Source Soft Solutions pivot notes — since
Source Soft's real bios shouldn't be attributed to a different org) — so
one stale field explains both symptoms the user saw in a single root
cause.

The user must have visited the Template Settings tab and loaded one of
Dark Mode/Light Mode/Executive Crimson (or it stayed selected in
`st.session_state["template_settings"]` from earlier in their session)
before drafting — a render with `settings=None` (never touched Template
Settings at all) was NOT affected, since that path uses
`TemplateSettings()`'s own (correct) dataclass default directly, with no
JSON file in the loop at all.

**Fix**: `load_preset()` now checks `if name in _BUILTIN_FACTORIES`
FIRST and always returns a fresh call to the in-code factory for any
built-in preset name — a stale (or absent) JSON file is irrelevant for
built-ins, closing the whole bug class rather than just this one
instance (the on-disk cache is still refreshed via `save_preset()` after,
harmless, just keeps it in sync for inspection). User-created custom
presets (any name not in `_BUILTIN_FACTORIES`) are unaffected — those
still load from their JSON file, since a user's saved customisation has
no in-code fallback and should persist exactly as they left it. Confirmed
via `demo_app.py`'s actual preset-loading UI flow (`ensure_builtin_presets()`,
the quick-preset buttons, "Save Preset" always prompts for a new name) that
this change can't silently discard a real user customisation — built-ins
were never meant to be edited-and-saved-in-place through the UI.

**Verified with zero API cost**, given the user's explicit "$5 total,
testing costs money" constraint: monkey-patched `drafting._llm_chat` to
return canned text (no real Anthropic calls), rendered a full Technical
Proposal under the previously-buggy "Dark Mode" preset, converted to PDF,
and confirmed visually — letterhead and cover page now say "Source Soft
Solutions" (not QCI), the About the Company page is fully present
including the real leadership photos (added earlier this session), and
Dark Mode's actual custom styling (navy/black heading bars, blue accent)
still renders correctly — the fix corrected only the stale field, nothing
else about the preset's intended look changed. This "stub the LLM,
verify structure for free" pattern is worth reusing for any future
structural-only fix — full narrative-quality checks still need a real
Opus call, but layout/branding/data-wiring bugs like this one don't.

### UI mockups were generic, not project-specific (24 Aug 2026)

User asked directly: "in section 14... will the image generated will be
same?" Honest answer at the time was yes — `render_ui_mockup()`'s nav
items ("Home/About/Services/News/Contact"), admin sidebar menu
("Dashboard/Content/Media/Users & Roles/Settings") and stat-card layout
were all hardcoded, identical on every render regardless of project; only
the title text and accent colour varied. Fixed by adding optional
`nav_items`/`cards` (public_home) and `sidebar_items` (admin_dashboard)
parameters to `render_ui_mockup()`, wired through
`_add_ui_mockup_image()` (build_templates.py) and
`_inject_generated_content()` (drafting.py) from data ALREADY being
generated for other sections — `sitemap_pillars` → nav items,
`modules_features` → the 3 feature-card labels, `admin_capabilities` →
sidebar items — no new fields needed, just reusing what section 8/10 and
the sitemap diagram already produce. Falls back to the original generic
content when nothing is passed (keeps standalone/manual calls to
`render_ui_mockup` working). Verified free (stubbed `_llm_chat` again):
a test project with "Certificate Verification / Notices Board / Training
Partners" as its modules now shows exactly those as the mockup's feature
cards, and its admin capabilities as the sidebar items — confirmed via
rendered PDF.

---

## 9. Where to look for more detail

- `README.md` — developer-facing setup/run instructions, kept in sync with
  each phase as it's built
- `data/samples/SOURCES.md` — exact provenance of every sample document
- `data/processed/audit_log.jsonl` — every Q&A interaction ever logged
- Published artifact: "Knowledge Hub Blueprint" — visual architecture diagrams
  of the ingestion and query/guardrail pipelines (published earlier this
  session; ask the user for the link if needed, or check Artifact list)
