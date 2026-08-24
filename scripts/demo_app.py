"""Live demo UI for the technical presentation / PoC scoring criterion.
Four tabs: Template Settings, Conversational Search (Phase 2),
Document Drafting (Phase 3), and Document Summarization (Pillar 3).
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
from generation.template_settings import (
    TemplateSettings, save_preset, load_preset, list_presets,
    delete_preset, ensure_builtin_presets, _BUILTIN_PRESET_NAMES,
)
from retrieval.store import get_client, list_sources
from config import QDRANT_COLLECTION, ANTHROPIC_MODEL, RETRIEVAL_SCORE_THRESHOLD, QDRANT_MODE


def _get_template_settings() -> TemplateSettings | None:
    """Return the current template settings from session state, or None
    if the user hasn't configured any (use defaults)."""
    return st.session_state.get("template_settings", None)


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
            try:
                path = render_fn(session)
            except Exception as e:
                # A long draft makes 25-30 sequential LLM calls — an
                # unhandled exception on the last one used to crash the
                # whole app to a raw traceback (hit for real: a transient
                # anthropic.OverloadedError). Nothing already typed is
                # lost (answers live in st.session_state), so surface a
                # readable error and let the user just click Generate
                # again rather than losing the page.
                st.error(f"Drafting failed: {e}\n\nYour answers are still saved — click "
                         f"**{generate_label}** again to retry.")
                st.stop()
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

st.set_page_config(page_title="Source Soft Solutions — Demo", layout="wide")

# Ensure built-in presets exist on disk
ensure_builtin_presets()

EXAMPLE_QUESTIONS = [
    "What is the purpose of the National Emergency Response System MoU?",
    "What is the ZED certification scheme about?",
    "What is the capital of France?",  # deliberately off-topic — demonstrates the fallback guardrail live
]

# ---------------- sidebar: what's actually running ----------------
with st.sidebar:
    st.header("⚡ Source Soft Solutions")
    
    st.divider()
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

    st.divider()
    st.caption("Template Settings")
    current_preset = st.session_state.get("current_preset_name", "Source Soft Solutions")
    st.write(f"**Active preset:** `{current_preset}`")
    settings = _get_template_settings()
    if settings:
        st.write(f"**Font:** {settings.font_family} {settings.body_font_size}pt")
        st.write(f"**Cover page:** {'✅' if settings.include_cover_page else '❌'}")
        st.write(f"**TOC:** {'✅' if settings.include_toc else '❌'}")
        st.write(f"**Declarations:** {'✅' if settings.include_declarations else '❌'}")


tab_settings, tab_search, tab_draft, tab_summarize = st.tabs(
    ["⚙️ Template Settings", "🔍 Conversational Search", "📄 Draft a Document", "📋 Summarize a Document"]
)

# ==================== TAB 0: Template Settings ====================
with tab_settings:
    st.title("⚙️ Template Settings")
    st.caption(
        "Customise the look and feel of all drafted documents. Changes apply to all documents "
        "you generate in this session. Save your settings as a preset to reuse them later."
    )

    # ── Quick Theme Presets ──
    st.subheader("⚡ Quick Theme Presets")
    st.caption("One-click style presets for your generated documents:")
    qp_col1, qp_col2, qp_col3, qp_col4, qp_col5 = st.columns(5)
    
    with qp_col1:
        if st.button("🌙 Dark Mode", key="qp_dark", use_container_width=True):
            loaded = load_preset("Dark Mode")
            st.session_state["template_settings"] = loaded
            st.session_state["current_preset_name"] = "Dark Mode"
            st.rerun()
            
    with qp_col2:
        if st.button("☀️ Light Mode", key="qp_light", use_container_width=True):
            loaded = load_preset("Light Mode")
            st.session_state["template_settings"] = loaded
            st.session_state["current_preset_name"] = "Light Mode"
            st.rerun()

    with qp_col3:
        if st.button("🏛️ Source Soft Solutions", key="qp_qci", use_container_width=True):
            loaded = load_preset("Source Soft Solutions")
            st.session_state["template_settings"] = loaded
            st.session_state["current_preset_name"] = "Source Soft Solutions"
            st.rerun()

    with qp_col4:
        if st.button("📄 Minimal Clean", key="qp_minimal", use_container_width=True):
            loaded = load_preset("Minimal Clean")
            st.session_state["template_settings"] = loaded
            st.session_state["current_preset_name"] = "Minimal Clean"
            st.rerun()

    with qp_col5:
        if st.button("📜 Executive", key="qp_exec", use_container_width=True):
            loaded = load_preset("Executive Crimson")
            st.session_state["template_settings"] = loaded
            st.session_state["current_preset_name"] = "Executive Crimson"
            st.rerun()

    st.divider()

    # ── Preset Management ──
    st.subheader("📁 Custom Preset Management")
    preset_col1, preset_col2 = st.columns([3, 1])

    available_presets = list_presets()
    with preset_col1:
        selected_preset = st.selectbox(
            "Select a preset",
            available_presets,
            index=available_presets.index(st.session_state.get("current_preset_name", "Source Soft Solutions"))
            if st.session_state.get("current_preset_name", "Source Soft Solutions") in available_presets else 0,
            key="preset_selector"
        )

    with preset_col2:
        st.write("")  # spacing
        if st.button("📥 Load Preset", key="load_preset_btn", use_container_width=True):
            try:
                loaded = load_preset(selected_preset)
                st.session_state["template_settings"] = loaded
                st.session_state["current_preset_name"] = selected_preset
                st.success(f"Loaded preset: **{selected_preset}**")
                st.rerun()
            except FileNotFoundError:
                st.error(f"Preset '{selected_preset}' not found.")

    save_col1, save_col2, save_col3 = st.columns([2, 1, 1])
    with save_col1:
        new_preset_name = st.text_input("Save current settings as:", placeholder="e.g. My Custom Style",
                                         key="new_preset_name")
    with save_col2:
        st.write("")
        if st.button("💾 Save Preset", key="save_preset_btn", use_container_width=True):
            if new_preset_name.strip():
                current_settings = _get_template_settings() or TemplateSettings()
                save_preset(new_preset_name.strip(), current_settings)
                st.session_state["current_preset_name"] = new_preset_name.strip()
                st.success(f"Saved preset: **{new_preset_name.strip()}**")
                st.rerun()
            else:
                st.warning("Please enter a name for the preset.")
    with save_col3:
        st.write("")
        can_delete = selected_preset not in _BUILTIN_PRESET_NAMES
        if st.button("🗑️ Delete", key="delete_preset_btn", disabled=not can_delete,
                     use_container_width=True):
            if delete_preset(selected_preset):
                st.success(f"Deleted preset: **{selected_preset}**")
                st.rerun()

    st.divider()

    # Initialize settings from session state or defaults
    if "template_settings" not in st.session_state:
        st.session_state["template_settings"] = TemplateSettings()
        st.session_state["current_preset_name"] = "Source Soft Solutions"

    s = st.session_state["template_settings"]

    # ── Colours ──
    st.subheader("🎨 Colours")
    colour_col1, colour_col2, colour_col3, colour_col4 = st.columns(4)
    with colour_col1:
        heading_bar = st.color_picker(
            "Heading bar fill", value=f"#{s.heading_bar_colour}",
            key="cp_heading_bar"
        )
    with colour_col2:
        heading_text = st.color_picker(
            "Heading text", value=f"#{s.heading_text_colour}",
            key="cp_heading_text"
        )
    with colour_col3:
        page_border_col = st.color_picker(
            "Page border", value=f"#{s.page_border_colour}",
            key="cp_page_border"
        )
    with colour_col4:
        accent = st.color_picker(
            "Accent colour", value=f"#{s.accent_colour}",
            key="cp_accent"
        )

    # Live colour preview
    st.markdown(
        f'<div style="display:flex;gap:8px;margin:8px 0;">'
        f'<div style="background-color:{heading_bar};color:{heading_text};padding:8px 16px;'
        f'border-radius:4px;font-weight:bold;font-family:{s.font_family};">Section Heading Preview</div>'
        f'<div style="border:2px solid {page_border_col};padding:8px 16px;border-radius:4px;">'
        f'Page Border</div>'
        f'<div style="border-bottom:3px solid {accent};padding:8px 16px;">Accent Rule</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.divider()

    # ── Typography ──
    st.subheader("✏️ Typography")
    typo_col1, typo_col2, typo_col3 = st.columns(3)
    with typo_col1:
        font_family = st.selectbox(
            "Font family",
            ["Calibri", "Times New Roman", "Arial", "Georgia", "Verdana", "Garamond", "Cambria"],
            index=["Calibri", "Times New Roman", "Arial", "Georgia", "Verdana", "Garamond", "Cambria"]
            .index(s.font_family) if s.font_family in ["Calibri", "Times New Roman", "Arial", "Georgia", "Verdana", "Garamond", "Cambria"] else 0,
            key="font_family_select"
        )
    with typo_col2:
        body_size = st.slider("Body font size (pt)", 9, 14, s.body_font_size, key="body_size_slider")
    with typo_col3:
        heading_size = st.slider("Heading font size (pt)", 14, 22, s.heading_font_size, key="heading_size_slider")

    # Font preview
    st.markdown(
        f'<div style="font-family:{font_family};margin:8px 0;">'
        f'<p style="font-size:{heading_size}px;font-weight:bold;margin:0;">Heading Preview — {font_family}</p>'
        f'<p style="font-size:{body_size}px;margin:4px 0;">Body text preview in {font_family} at {body_size}pt. '
        f'This shows how your document body text will look.</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.divider()

    # ── Logo ──
    st.subheader("🏢 Logo")
    logo_col1, logo_col2 = st.columns(2)
    with logo_col1:
        uploaded_logo = st.file_uploader(
            "Upload custom logo (PNG/JPEG)", type=["png", "jpg", "jpeg"],
            key="logo_uploader",
            help="Leave empty to use the default Source Soft Solutions logo"
        )
        logo_width = st.slider("Logo width (cm)", 2.0, 12.0, s.logo_width_cm, 0.5, key="logo_width_slider")
    with logo_col2:
        uploaded_mark = st.file_uploader(
            "Upload signature mark (PNG/JPEG)", type=["png", "jpg", "jpeg"],
            key="mark_uploader",
            help="Small logo for the signature block"
        )
        mark_width = st.slider("Signature mark width (cm)", 0.5, 4.0, s.logo_mark_width_cm, 0.1,
                                key="mark_width_slider")

    use_default_logo = st.checkbox("Use default Source Soft Solutions logo", value=(s.logo_path is None), key="use_default_logo")

    # Handle uploaded logos — save to a persistent location
    custom_logo_path = s.logo_path
    custom_mark_path = s.logo_mark_path
    if uploaded_logo is not None:
        logo_dir = Path("data/template_presets/logos")
        logo_dir.mkdir(parents=True, exist_ok=True)
        logo_save = logo_dir / f"custom_logo.{uploaded_logo.name.split('.')[-1]}"
        logo_save.write_bytes(uploaded_logo.getvalue())
        custom_logo_path = str(logo_save.resolve())
    elif not use_default_logo:
        custom_logo_path = "__NONE__"
    else:
        custom_logo_path = None

    if uploaded_mark is not None:
        logo_dir = Path("data/template_presets/logos")
        logo_dir.mkdir(parents=True, exist_ok=True)
        mark_save = logo_dir / f"custom_mark.{uploaded_mark.name.split('.')[-1]}"
        mark_save.write_bytes(uploaded_mark.getvalue())
        custom_mark_path = str(mark_save.resolve())

    st.divider()

    # ── Page Border ──
    st.subheader("📐 Page Border")
    border_col1, border_col2 = st.columns(2)
    with border_col1:
        show_border = st.checkbox("Show page border", value=s.show_page_border, key="show_border_cb")
    with border_col2:
        border_style = st.selectbox(
            "Border style",
            ["single", "double", "thick", "dotted"],
            index=["single", "double", "thick", "dotted"].index(s.page_border_style)
            if s.page_border_style in ["single", "double", "thick", "dotted"] else 0,
            key="border_style_select",
            disabled=not show_border,
        )

    st.divider()

    # ── Header / Footer ──
    st.subheader("📝 Header & Footer")
    hf_col1, hf_col2 = st.columns(2)
    with hf_col1:
        show_header = st.checkbox("Show running header on every page", value=s.show_running_header,
                                   key="show_header_cb")
    with hf_col2:
        show_footer = st.checkbox("Show footer (ref, version, page no.)", value=s.show_footer,
                                   key="show_footer_cb")

    st.divider()

    # ── Fixed Pages ──
    st.subheader("📄 Fixed Pages")
    st.caption("These pages are automatically added to the beginning of every drafted document.")
    fp_col1, fp_col2, fp_col3 = st.columns(3)
    with fp_col1:
        include_cover = st.checkbox("📋 Cover Page", value=s.include_cover_page, key="include_cover_cb",
                                     help="A branded cover page with logo, title, and key details")
    with fp_col2:
        include_toc = st.checkbox("📑 Table of Contents", value=s.include_toc, key="include_toc_cb",
                                   help="Auto-generated table of contents (updates in Word)")
    with fp_col3:
        include_decl = st.checkbox("⚖️ Declarations & Undertakings", value=s.include_declarations,
                                    key="include_decl_cb",
                                    help="Standard Indian Government legal declarations")

    show_confidential = st.checkbox("🔒 Show 'CONFIDENTIAL' marking on cover page",
                                     value=s.show_confidential_marking, key="show_conf_cb",
                                     disabled=not include_cover)

    st.divider()

    # ── Organisation Info ──
    st.subheader("🏛️ Organisation Information")
    st.caption("Used on the cover page and letterhead.")
    org_name = st.text_input("Organisation name", value=s.organisation_name, key="org_name_input")
    org_address = st.text_input("Organisation address", value=s.organisation_address, key="org_address_input")

    st.divider()

    # ── Apply Settings ──
    if st.button("✅ Apply Settings", type="primary", key="apply_settings_btn", use_container_width=True):
        new_settings = TemplateSettings(
            heading_bar_colour=heading_bar.lstrip("#").upper(),
            heading_text_colour=heading_text.lstrip("#").upper(),
            page_border_colour=page_border_col.lstrip("#").upper(),
            accent_colour=accent.lstrip("#").upper(),
            font_family=font_family,
            body_font_size=body_size,
            heading_font_size=heading_size,
            logo_path=custom_logo_path,
            logo_width_cm=logo_width,
            logo_mark_path=custom_mark_path,
            logo_mark_width_cm=mark_width,
            show_page_border=show_border,
            page_border_style=border_style,
            show_running_header=show_header,
            show_footer=show_footer,
            signature_style=s.signature_style,
            include_cover_page=include_cover,
            include_toc=include_toc,
            include_declarations=include_decl,
            show_confidential_marking=show_confidential,
            organisation_name=org_name,
            organisation_address=org_address,
        )
        st.session_state["template_settings"] = new_settings
        st.success("✅ Settings applied! All documents generated in the **Draft a Document** tab will use these settings.")
        st.rerun()

    # Reset button
    if st.button("🔄 Reset to Source Soft Defaults", key="reset_defaults_btn"):
        st.session_state["template_settings"] = TemplateSettings()
        st.session_state["current_preset_name"] = "Source Soft Solutions"
        st.success("Reset to Source Soft Solutions defaults.")
        st.rerun()

# ==================== TAB 1: Conversational Search (Phase 2) ====================
with tab_search:
    st.title("Source Soft Solutions — Conversational Search")
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
    st.title("Source Soft Solutions — Document Drafting")
    st.caption(
        "Pillar 3 PoC: guided clarifying-questions flow, then AI expands the narrative "
        "sections — grounded by retrieving similar ingested documents for tone/structure. "
        "12 templates across the RFP's 4 document types (Work Order, MoU, Agreement, Proposal)."
    )

    # Show active template settings summary
    active_settings = _get_template_settings()
    if active_settings:
        with st.expander("📋 Active Template Settings", expanded=False):
            settings_col1, settings_col2, settings_col3 = st.columns(3)
            with settings_col1:
                st.write(f"**Font:** {active_settings.font_family} {active_settings.body_font_size}pt")
                st.write(f"**Heading colour:** #{active_settings.heading_bar_colour}")
            with settings_col2:
                st.write(f"**Cover page:** {'✅' if active_settings.include_cover_page else '❌'}")
                st.write(f"**TOC:** {'✅' if active_settings.include_toc else '❌'}")
            with settings_col3:
                st.write(f"**Declarations:** {'✅' if active_settings.include_declarations else '❌'}")
                st.write(f"**Page border:** {'✅' if active_settings.show_page_border else '❌'}")
            st.caption("Configure these in the **⚙️ Template Settings** tab.")

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
        render_fn=lambda s, _spec=spec: render_document(s, _spec, settings=_get_template_settings()),
        id_field_names=id_fields,
        generate_label=f"Generate draft (AI expands {sections_label})",
        brief_field_names=brief_fields,
    )

# ==================== TAB 3: Summarize a Document (Pillar 3) ====================
with tab_summarize:
    st.title("Source Soft Solutions — Document Summarization")
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
