"""Live demo UI for the technical presentation / PoC scoring criterion.
Two tabs: conversational search (Phase 2) and document drafting (Phase 3).
Nothing here duplicates pipeline logic — it's a thin presentation layer over
what's already built. Run with: streamlit run scripts/demo_app.py"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from generation.rag import ask
from generation.drafting import DraftSession, render_document, ALL_TEMPLATE_SPECS
from generation.summarize import summarize_document
from generation.export import docx_to_pdf
from generation.voice import transcribe_audio
from retrieval.store import get_client, list_sources
from config import QDRANT_COLLECTION, ANTHROPIC_MODEL, RETRIEVAL_SCORE_THRESHOLD, QDRANT_MODE


def render_drafting_tab(state_key: str, fields: list, render_fn, id_field_names: tuple,
                         generate_label: str, brief_field_names: set):
    """One drafting flow, parameterized so Work Order and MoU (and any future
    template) share this instead of duplicating ~90 lines of near-identical
    Streamlit code each. `id_field_names` are the 3 fields shown in the
    post-generation summary/history so drafts stay distinguishable; the
    backend (generation/drafting.py) was already generalized the same way."""
    answers_key, history_key = f"{state_key}_answers", f"{state_key}_history"
    if answers_key not in st.session_state:
        st.session_state[answers_key] = {}
    if history_key not in st.session_state:
        st.session_state[history_key] = []

    session = DraftSession(answers=dict(st.session_state[answers_key]), fields=fields)

    if not session.is_complete():
        field_name, question = session.next_question()
        default = next((d for n, q, d in fields if n == field_name), None)
        done = len(st.session_state[answers_key])
        total = len(fields)
        st.progress(done / total, text=f"Question {done + 1} of {total}")

        answer = st.text_input(question, value=default or "", key=f"{state_key}_input_{field_name}")
        if field_name in brief_field_names:
            st.caption("Be specific — a thin description (e.g. \"Test\") can cause the AI to pull in "
                       "unrelated content from reference documents instead of making something up from nothing.")
        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            if st.button("← Back", key=f"{state_key}_back", disabled=(len(st.session_state[answers_key]) == 0)):
                last_field = list(st.session_state[answers_key].keys())[-1]
                del st.session_state[answers_key][last_field]
                st.rerun()
        with col2:
            if st.button("Next →", key=f"{state_key}_next"):
                accepted, error = session.answer(field_name, answer)
                if accepted:
                    st.session_state[answers_key] = session.answers
                    st.rerun()
                else:
                    st.error(error)
        return

    st.success("All fields collected.")
    with st.expander("Show collected answers"):
        st.json(st.session_state[answers_key])

    if st.button(generate_label, type="primary", key=f"{state_key}_generate"):
        with st.spinner("Retrieving similar reference documents and drafting..."):
            path = render_fn(session)
        record = {"path": str(path)}
        for f in id_field_names:
            record[f] = st.session_state[answers_key].get(f, "?")
        st.session_state[history_key].insert(0, record)
        st.rerun()

    if st.session_state[history_key]:
        latest = st.session_state[history_key][0]
        out_path = Path(latest["path"])
        summary_line = " — ".join(f"{latest[f]}" for f in id_field_names)
        st.success(f"Generated: **{summary_line}** (`{out_path.name}`)")
        dl_col1, dl_col2 = st.columns(2)
        with open(out_path, "rb") as f:
            dl_col1.download_button(
                "Download .docx", data=f.read(), file_name=out_path.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"{state_key}_dl_latest_{out_path.name}",
            )
        if dl_col2.button("Convert & download as PDF", key=f"{state_key}_pdf_btn_{out_path.name}"):
            with st.spinner("Converting to PDF..."):
                pdf_path = docx_to_pdf(out_path)
            with open(pdf_path, "rb") as f:
                st.download_button("Download .pdf", data=f.read(), file_name=pdf_path.name,
                                    mime="application/pdf", key=f"{state_key}_dl_pdf_{pdf_path.name}")

    if len(st.session_state[history_key]) > 1:
        with st.expander(f"Previous drafts this session ({len(st.session_state[history_key]) - 1})"):
            for d in st.session_state[history_key][1:]:
                p = Path(d["path"])
                summary_line = " — ".join(f"{d[f]}" for f in id_field_names)
                st.write(f"**{summary_line}**")
                if p.exists():
                    with open(p, "rb") as f:
                        st.download_button("Download", data=f.read(), file_name=p.name,
                                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                            key=f"{state_key}_dl_hist_{p.name}")
                st.divider()

    if st.button("Start a new draft", key=f"{state_key}_restart"):
        st.session_state[answers_key] = {}
        st.rerun()

st.set_page_config(page_title="QCI Knowledge Hub — Demo", layout="wide")

EXAMPLE_QUESTIONS = [
    "What is the purpose of the National Emergency Response System MoU?",
    "What is the ZED certification scheme about?",
    "What is the capital of France?",  # deliberately off-topic — demonstrates the fallback guardrail live
]

# ---------------- sidebar: what's actually running ----------------
with st.sidebar:
    st.header("System status")
    try:
        info = get_client().get_collection(QDRANT_COLLECTION)
        st.metric("Chunks indexed", info.points_count)
    except Exception:
        st.warning("No collection found yet — run `scripts/ingest.py` first.")

    st.divider()
    st.caption("Configuration")
    st.write(f"**Model:** `{ANTHROPIC_MODEL}` (Claude API — Q&A, drafting, summarization, "
             f"classification; embeddings/retrieval/voice stay local)")
    st.write(f"**Vector store:** Qdrant — `{QDRANT_MODE}` mode")
    st.write(f"**Retrieval fallback threshold:** `{RETRIEVAL_SCORE_THRESHOLD}`")

    st.divider()
    st.caption("Guardrails active")
    st.markdown(
        "1. Retrieval-score filter (pre-LLM)\n"
        "2. LLM self-report (`NO_INFO_FOUND`)\n"
        "3. Citation validation (post-hoc)\n"
        "4. XML-escaping + meta-commentary stripping (drafting)\n\n"
        "Every Q&A interaction is written to `data/processed/audit_log.jsonl`."
    )

tab_search, tab_draft, tab_summarize = st.tabs(
    ["Conversational Search", "Draft a Document", "Summarize a Document"]
)

# ==================== TAB 1: Conversational Search (Phase 2) ====================
with tab_search:
    st.title("QCI Knowledge Hub — Conversational Search")
    st.caption("Pillar 3 PoC: citation-backed Q&A, grounded only in ingested documents.")

    st.write("**Try an example** (the third one is deliberately off-topic — watch the fallback guardrail catch it):")
    cols = st.columns(len(EXAMPLE_QUESTIONS))
    example_clicked = None
    for col, q in zip(cols, EXAMPLE_QUESTIONS):
        if col.button(q, use_container_width=True):
            example_clicked = q

    if "history" not in st.session_state:
        st.session_state.history = []

    for turn in st.session_state.history:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            st.write(turn["answer"])
            if turn["is_fallback"]:
                st.info("Fallback triggered — no ungrounded answer was generated.")
            else:
                if turn["citations"]:
                    st.markdown("**Sources cited:**")
                    for c in turn["citations"]:
                        st.caption(f"[{c['index']}] {c['source']} — {c['unit_label']} "
                                   f"`{c.get('document_type', 'Other')}` / `{c.get('category', 'General/Unclassified')}`")
                if turn["guardrail_issues"]:
                    st.warning("Guardrail flagged (logged for admin review): " + "; ".join(turn["guardrail_issues"]))
                with st.expander("Show retrieved chunks (raw retrieval, before generation)"):
                    for i, chunk in enumerate(turn["retrieved_chunks"], 1):
                        st.markdown(f"**[{i}]** `{chunk['source']}` ({chunk['unit_label']}) — score `{chunk['score']:.3f}`")
                        st.text(chunk["text"][:400] + ("..." if len(chunk["text"]) > 400 else ""))

    with st.expander("🎙️ Or ask by voice (English)"):
        # Hindi/Hinglish was tried and dropped, not just left unbuilt: a real
        # user recording ("Mereko National Emergency Response System ke
        # baare me batao") transcribed as nonsense regardless of model tier
        # (small/medium), language hint, or domain prompt — see
        # scripts/debug_real_hindi.py's output and Memory.md for the full
        # comparison. English alone is what's actually validated (97%
        # accuracy), so that's what's offered here now.
        audio_value = st.audio_input("Record your question")
        voice_question = None
        if audio_value is not None:
            # audio_input returns the same object across reruns until a new
            # recording is made — track what's already been transcribed so
            # an unrelated rerun (e.g. clicking something else on the page)
            # doesn't silently re-ask the same question a second time.
            audio_key = getattr(audio_value, "file_id", None) or hash(audio_value.getvalue())
            if st.session_state.get("last_audio_key") != audio_key:
                with st.spinner("Transcribing..."):
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp.write(audio_value.getvalue())
                        tmp_path = tmp.name
                    result = transcribe_audio(tmp_path, language="en")

                    # Persist a copy instead of deleting it — cheap to keep a
                    # real usage sample set even now that only English is
                    # offered.
                    recordings_dir = Path("data/voice_test/user_recordings")
                    recordings_dir.mkdir(parents=True, exist_ok=True)
                    saved_path = recordings_dir / f"{audio_key}.wav"
                    # Path.replace() (os.replace) requires the same volume for
                    # its atomic rename — fails with WinError 17 when the OS
                    # temp dir and the project directory are on different
                    # drives (confirmed: a real user hit this on C:\...Temp
                    # vs. D:\...project). shutil.move() falls back to a
                    # copy+delete across volumes, same as `mv` on Linux.
                    shutil.move(tmp_path, saved_path)

                st.session_state.last_audio_key = audio_key
                st.session_state.last_voice_transcript = result["text"]
                st.caption(f"Saved as `{saved_path.name}` for testing")
                st.write(f"Transcribed: *{result['text']}*")
                voice_question = result["text"]

    question = st.chat_input("Ask a question about the ingested documents...") or example_clicked or voice_question

    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Retrieving and generating..."):
                result = ask(question)
            st.write(result.answer)
            if result.is_fallback:
                st.info("Fallback triggered — no ungrounded answer was generated.")
            else:
                if result.citations:
                    st.markdown("**Sources cited:**")
                    for c in result.citations:
                        st.caption(f"[{c['index']}] {c['source']} — {c['unit_label']} "
                                   f"`{c.get('document_type', 'Other')}` / `{c.get('category', 'General/Unclassified')}`")
                if result.guardrail_issues:
                    st.warning("Guardrail flagged (logged for admin review): " + "; ".join(result.guardrail_issues))
                with st.expander("Show retrieved chunks (raw retrieval, before generation)"):
                    for i, chunk in enumerate(result.retrieved_chunks, 1):
                        st.markdown(f"**[{i}]** `{chunk['source']}` ({chunk['unit_label']}) — score `{chunk['score']:.3f}`")
                        st.text(chunk["text"][:400] + ("..." if len(chunk["text"]) > 400 else ""))

        st.session_state.history.append({
            "question": question,
            "answer": result.answer,
            "is_fallback": result.is_fallback,
            "citations": result.citations,
            "guardrail_issues": result.guardrail_issues,
            "retrieved_chunks": result.retrieved_chunks,
        })

# ==================== TAB 2: Document Drafting — all 12 templates (Phase 3) ====================
with tab_draft:
    st.title("QCI Knowledge Hub — Document Drafting")
    st.caption(
        "Pillar 3 PoC: guided clarifying-questions flow, then AI expands the narrative "
        "sections — grounded by retrieving similar ingested documents for tone/structure. "
        "12 templates across the RFP's 4 document types (Work Order, MoU, Agreement, Proposal)."
    )

    spec_by_name = {s.display_name: s for s in ALL_TEMPLATE_SPECS}
    selected_name = st.selectbox("Document type", list(spec_by_name.keys()), key="template_selector")
    spec = spec_by_name[selected_name]

    # Identifying fields for the post-generation summary: prefer a
    # (doc_number, title-ish, party-ish) triple where those concepts exist
    # in this spec's schema, falling back to the first 3 fields otherwise —
    # every spec's field names differ, so this can't be hardcoded per-template
    # the way the original Work Order/MoU-only version did.
    field_names = [f[0] for f in spec.fields]
    title_like = next((f for f in field_names if "title" in f or "subject_matter" in f), None)
    party_like = next((f for f in field_names
                        if f not in (spec.doc_number_field, title_like)
                        and ("name" in f and "signatory" not in f)), None)
    id_fields = tuple(f for f in (spec.doc_number_field, title_like, party_like) if f) or tuple(field_names[:3])

    brief_fields = {nf.brief_field for nf in spec.narrative_fields}
    sections_label = " + ".join(nf.subject_label for nf in spec.narrative_fields)

    render_drafting_tab(
        state_key=spec.key, fields=spec.fields,
        render_fn=lambda s, _spec=spec: render_document(s, _spec),
        id_field_names=id_fields,
        generate_label=f"Generate draft (AI expands {sections_label})",
        brief_field_names=brief_fields,
    )

# ==================== TAB 4: Summarize a Document (Pillar 3) ====================
with tab_summarize:
    st.title("QCI Knowledge Hub — Document Summarization")
    st.caption(
        "Pillar 3 PoC: intelligent summarisation. Large documents are summarised via "
        "map-reduce (batch summaries -> combined summary) since they don't fit in one "
        "prompt to a small local model."
    )

    try:
        sources = list_sources()
    except Exception:
        sources = []

    if not sources:
        st.warning("No documents indexed yet — run `scripts/ingest.py` first.")
    else:
        selected = st.selectbox("Choose a document to summarize", sources)
        if st.button("Summarize", type="primary"):
            with st.spinner("Fetching document and summarising (this may take a while for large documents)..."):
                result = summarize_document(selected)
            st.markdown("**Summary:**")
            st.write(result["summary"])
            st.caption(f"{result['chunk_count']} chunk(s) · summarised in {result['batches_used']} batch(es)")
