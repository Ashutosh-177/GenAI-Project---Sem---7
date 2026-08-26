"""Document drafting engine (Phase 3) — Pillar 3's other core deliverable,
sitting on the exact same building blocks as Phase 2 (retrieval + LLM),
aimed at a different job: fill a template instead of answer a question.

Required fields are a fixed, deterministic schema — not something the LLM
improvises — because a work order's structure is a legal/procedural fact,
not a judgment call. The LLM is only used to expand the two narrative
sections (scope of work, terms & conditions), and even there it's grounded
by retrieving similar previously-ingested documents for tone/structure,
matching the RFP's "context-aware document generation using organisational
repositories" requirement rather than pure free-form generation."""
import re
from dataclasses import dataclass, field as dc_field
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from docxtpl import DocxTemplate

from generation.llm_client import chat as _llm_chat
from generation.template_settings import TemplateSettings
from retrieval.store import search as _raw_search


def search(*args, **kwargs):
    """Retrieval with graceful degradation.

    Reference-document retrieval is a QUALITY enhancement — it grounds the
    model in the tone/structure of real past documents — not a hard
    requirement for producing a draft. But `retrieval.store.search()`
    raises if Qdrant is unreachable, which made a stopped Qdrant/Docker
    container fail EVERY draft outright, at the very first narrative
    field, before any LLM call.

    Found by a fair user challenge ("are you sure the webpage will
    work?") rather than by testing: every zero-cost verification run this
    session stubbed this function out, which is precisely why the real
    failure went unnoticed for so long. Stubbing a dependency to test
    around it is fine; forgetting that the unstubbed path was never
    exercised is not.

    Degrading to an empty result set means drafts still generate with
    Qdrant down — slightly less styled after real reference documents,
    but produced rather than crashed. Callers already handle an empty
    `reference_chunks` (`reference_text` becomes "" and the leak-detection
    guardrail is skipped, since with no reference text there is nothing to
    leak)."""
    try:
        return _raw_search(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 — any retrieval failure is non-fatal by design
        print(f"[drafting] Retrieval unavailable ({type(e).__name__}) — "
              f"drafting without reference-document grounding.")
        return []

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated"

# (field name, question asked to the user, default value or None)
WORK_ORDER_FIELDS = [
    ("work_order_no", "What is the work order number?", None),
    ("work_order_date", "What is the issue date?", str(date.today())),
    ("issuing_organisation", "Issuing organisation?", "Source Soft Solutions"),
    ("contractor_name", "Who is the contractor / service provider (name)?", None),
    ("contractor_address", "Contractor's address?", None),
    ("project_title", "What is the project / work title?", None),
    ("scope_of_work_brief", "Briefly, what is the scope of work? (a sentence or two — this gets expanded)", None),
    ("contract_value", "What is the contract value?", None),
    ("start_date", "What is the work start date?", None),
    ("completion_period", "What is the completion period? (e.g. '3 months from issue')", None),
    ("payment_terms", "What are the payment terms?", None),
    ("authorized_signatory_name", "Who is signing on behalf of the issuing organisation (name)?", None),
    ("authorized_signatory_designation", "Their designation?", None),
]


# MoU — the second template, added to prove the Work Order pattern
# generalizes rather than being a one-off. Same shape: fixed field schema,
# two narrative sections the LLM expands from a brief.
MOU_FIELDS = [
    ("mou_no", "What is the MoU reference number?", None),
    ("mou_date", "What is the date of this MoU?", str(date.today())),
    ("party_a_name", "First party (usually Source Soft Solutions)?", "Source Soft Solutions"),
    ("party_b_name", "Second party (the other organisation)?", None),
    ("party_b_address", "Second party's address?", None),
    ("mou_title", "What is the title / purpose of this MoU?", None),
    ("background_brief", "Briefly, what's the background/context for this MoU? (this gets expanded)", None),
    ("objectives_brief", "Briefly, what are the objectives of this collaboration? (this gets expanded)", None),
    ("duration", "What is the duration of this MoU? (e.g. '3 years from date of signing')", None),
    ("signatory_a_name", "Who signs for the first party (name)?", None),
    ("signatory_a_designation", "Their designation?", None),
    ("signatory_b_name", "Who signs for the second party (name)?", None),
    ("signatory_b_designation", "Their designation?", None),
]

# Fields that get AI-expanded from a brief into a full paragraph — flagged
# here so DraftSession knows which fields need the brief-quality gate,
# regardless of which document type/schema is active.
_AI_EXPANDED_BRIEF_FIELDS = {"scope_of_work_brief", "background_brief", "objectives_brief"}

_PLACEHOLDER_WORDS = {"test", "tbd", "n/a", "na", "xxx", "asdf", "todo", "tba", "sample", "dummy", "xyz"}


def _validate_brief_field(value: str) -> tuple[bool, str]:
    """Caught by a real user hitting it: a near-empty brief ("Test") gives the
    LLM nothing to expand from, so it fills the gap by copying actual facts
    out of the retrieved reference documents instead of just their tone —
    confirmed case: a "Test" project got a real, unrelated scope of work
    about a different building in a different city, lifted from a reference
    tender. Rejecting too-thin input here is cheaper and more reliable than
    trying to catch every possible leak after the fact. Applies to every
    AI-expanded brief field across every document type, not just Work Order's."""
    stripped = value.strip().lower()
    words = stripped.split()
    if len(value.strip()) < 15 or len(words) < 3:
        return False, ("That's too short for the AI to expand safely — a brief description "
                        "under ~3 words risks pulling in unrelated content from reference "
                        "documents instead. Please give at least a short sentence.")
    if stripped in _PLACEHOLDER_WORDS or all(w in _PLACEHOLDER_WORDS for w in words):
        return False, "That looks like placeholder text, not a real description. Please describe it properly."
    return True, ""


@dataclass
class DraftSession:
    answers: dict = dc_field(default_factory=dict)
    fields: list = dc_field(default_factory=lambda: WORK_ORDER_FIELDS)

    def next_question(self):
        """Returns (field_name, question) for the next unanswered field, or
        None once every field has been collected."""
        for name, question, _default in self.fields:
            if name not in self.answers:
                return name, question
        return None

    def answer(self, field_name: str, value: str) -> tuple[bool, str]:
        """Returns (accepted, error_message) — error_message is empty when
        accepted. Two things enforced here that weren't before this was
        first built: a required field (no default) can no longer be silently
        accepted as an empty string (it was — next_question() only checks
        dict membership, not whether the value is meaningful), and every
        AI-expanded brief field is quality-gated per _validate_brief_field."""
        value = (value or "").strip()
        default = next((d for n, q, d in self.fields if n == field_name), None)
        if not value:
            if default is not None:
                value = default
            else:
                return False, "This field is required — please provide a value."
        if field_name in _AI_EXPANDED_BRIEF_FIELDS:
            valid, msg = _validate_brief_field(value)
            if not valid:
                return False, msg
        self.answers[field_name] = value
        return True, ""

    def is_complete(self) -> bool:
        return self.next_question() is None


_PREAMBLE_PATTERNS = [
    r"^here (is|are)[^\n:]*:\s*",
    r"^sure[,!]?\s*here[^\n:]*:\s*",
    r"^(certainly|of course)[,!]?\s*",
]
_TRAILING_NOTE_PATTERN = re.compile(r"\n\s*note:.*$", re.IGNORECASE | re.DOTALL)


def _strip_llm_meta_commentary(text: str) -> str:
    """Prompt instructions alone don't reliably stop a 3B model from wrapping
    its answer in "Here is..." / "Note: you should..." — same lesson as
    Phase 2's guardrails: don't trust instruction-following alone, verify
    and clean the output. Strips known preamble/postamble patterns and any
    surrounding quote marks the model adds around the "quoted" answer."""
    text = text.strip()
    for pattern in _PREAMBLE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = _TRAILING_NOTE_PATTERN.sub("", text)
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()
    return text


# Caught visually: T&C clause headings numbered by the model ("1. Quality
# and Compliance Expectations") collide with and restart under the
# template's own already-numbered section heading ("6. Terms &
# Conditions") — reads as "6. Terms & Conditions / 1. Quality...". First
# fix attempt just told the model not to add digit-numbers — it complied
# by switching to "Section 1." instead, still colliding (verified by
# actually re-reading the rendered output, not assumed fixed from the
# prompt change alone). Broadened to strip digits AND roman numerals,
# optionally preceded by "Section"/"Clause"/"Article".
_LEADING_CLAUSE_NUMBER_PATTERN = re.compile(
    r"^\s*(?:(?:section|clause|article)\s+)?(?:\d+|[ivxlcIVXLC]+)[\.\)\-:]\s+",
    re.MULTILINE | re.IGNORECASE,
)


def _strip_leading_clause_numbers(text: str) -> str:
    return _LEADING_CLAUSE_NUMBER_PATTERN.sub("", text)


_PROPER_NOUN_PATTERN = re.compile(r"\b(?:[A-Z][a-zA-Z0-9\-]*\s+){1,4}[A-Z][a-zA-Z0-9\-]*\b")
# Generic phrases that happen to be title-cased in legal boilerplate — not
# real leaked entities, would otherwise false-positive on every draft.
_LEAKAGE_ALLOWLIST = {"the contractor", "the client", "work order", "terms conditions",
                       "quality council", "quality council of india"}


def _extract_proper_nouns(text: str) -> set[str]:
    """Heuristic: 2+ consecutive capitalized words ('SAMEER Kolkata', 'Sec-V
    office') are almost always specific names or places, not generic
    scope-of-work vocabulary — used to catch reference-document facts that
    leaked into generated output despite being told 'tone/structure only'."""
    return {m.strip().lower() for m in _PROPER_NOUN_PATTERN.findall(text)} - _LEAKAGE_ALLOWLIST


def _generate_narrative_text(brief: str, subject_label: str, doc_label: str,
                               reference_text: str, known_facts: dict) -> str:
    """Generic narrative-expansion call, shared by every AI-expanded brief
    field across every document type (Work Order's scope of work, MoU's
    background/objectives, and whatever templates come after). Only the
    subject/doc labels change per call site — the anti-hallucination and
    anti-leakage instructions are identical everywhere on purpose, since
    they're the actual guardrail, not boilerplate.

    known_facts exists because of a real bug found by visual QA: an MoU
    between "Quality Council of India" and "Ministry of MSME" came back with
    body text calling the parties "Department of Commerce" and "Quality
    Control Institute" — neither of which is right (QCI is Quality COUNCIL
    of India). Root cause: the brief text doesn't always name the parties
    explicitly, so with nothing to anchor to, the model invented
    plausible-sounding government bodies instead of using the real ones that
    were sitting right there in the form data, just never passed into this
    prompt. known_facts fixes that by stating them outright."""
    facts_block = ""
    if known_facts:
        facts_lines = "\n".join(f"- {label}: {value}" for label, value in known_facts.items())
        facts_block = (f"\nKnown facts — use these names EXACTLY as given below, verbatim. "
                        f"Do not paraphrase them, abbreviate them differently, or substitute "
                        f"any other organisation/person name in their place. These labels "
                        f"(like \"{next(iter(known_facts))}\") are for your reference only — "
                        f"never write a label itself in your output, only the value it maps to:\n{facts_lines}\n")

    prompt = f"""Expand this brief {subject_label} description into a formal, \
professional paragraph (3-5 sentences) suitable for a {doc_label}. \
Do not invent contract-specific facts (dates, values, names, percentages, or any \
numbers) that weren't given — only elaborate on what was actually described.
{facts_block}
Output ONLY the paragraph itself. No preamble like "Here is..."; no notes, \
disclaimers, or commentary before or after it. Your entire response is inserted \
directly into a legal document as-is.

Brief description (this is the ONLY source of NEW facts — everything else you \
write must come from this or the known facts above): {brief}
{("Reference examples below are from a COMPLETELY DIFFERENT, UNRELATED document — "
  "shown ONLY so you can match sentence structure and tone. Any place name, "
  "organisation name, or specific detail in them belongs to that other "
  "document and must NEVER appear in your answer:\n" + reference_text) if reference_text else ""}

Expanded {subject_label}:"""

    return _strip_llm_meta_commentary(_llm_chat(prompt))


def _expand_brief(brief: str, subject_label: str, doc_label: str, reference_query: str,
                   known_facts: dict | None = None) -> str:
    """Retrieval-grounded expansion + the leak-detection/retry guardrail,
    generalized so every brief field across every document type gets the
    same protection the Work Order scope-of-work bug fix introduced."""
    known_facts = known_facts or {}
    reference_chunks = search(reference_query, top_k=3)
    reference_text = "\n\n".join(
        f"Reference style ({c['source']}, {c['unit_label']}): {c['text'][:400]}"
        for c in reference_chunks
    )

    result = _generate_narrative_text(brief, subject_label, doc_label, reference_text, known_facts)

    if reference_text:
        # Confirmed failure mode: with a thin brief, the model copies real
        # facts out of the reference chunks instead of just their tone. Check
        # for it, and if any reference-only proper noun leaked into the
        # output, regenerate with zero grounding rather than ship it —
        # correctness beats "context-aware" here.
        reference_entities = _extract_proper_nouns(reference_text)
        # known_facts values are legitimate, deliberately-provided names —
        # never flag them as "leaked" even if they happen to also appear in
        # the reference text (e.g. "Quality Council of India" showing up in
        # both a known fact and a retrieved reference chunk is a coincidence,
        # not contamination).
        allowed_entities = _extract_proper_nouns(brief) | _extract_proper_nouns(" ".join(known_facts.values()))
        leaked = _extract_proper_nouns(result) & reference_entities - allowed_entities
        if leaked:
            result = _generate_narrative_text(brief, subject_label, doc_label, "", known_facts)

    return result


def _draft_terms_and_conditions_text(project_title: str, reference_text: str, known_facts: dict) -> str:
    facts_block = ""
    if known_facts:
        facts_lines = "\n".join(f"- {label}: {value}" for label, value in known_facts.items())
        facts_block = (f"\nKnown facts — use these names EXACTLY as given, verbatim, if you refer "
                        f"to either party. These labels are for your reference only — never write "
                        f"a label itself in your output, only the value it maps to:\n{facts_lines}\n")

    prompt = f"""Draft 3-4 standard terms & conditions clauses for a government work order \
titled "{project_title}". Cover: quality/compliance expectations, timeline adherence, \
and dispute resolution. Keep it generic and professional. Do not invent any specific \
numbers — no penalty percentages, amounts, day-counts, or dates. Where a real contract \
would need such a figure, write "[to be specified]" instead of guessing one.
{facts_block}
Give each clause a short heading on its own line followed by its text — but do NOT label \
or number the heading in ANY way: no "1.", no "Section 1.", no "Clause 1:", no "Article \
I.", no roman numerals, nothing. Just the plain heading text itself, e.g. "Quality and \
Compliance Expectations" on its own, nothing before it. This text is inserted under a \
section that is already numbered elsewhere in the document, so any numbering or labeling \
you add would collide with it and restart confusingly.

Output ONLY the clauses themselves. No preamble like "Here are..."; no closing notes, \
disclaimers, or recommendations to consult a lawyer. Your entire response is inserted \
directly into a legal document as-is.
{"Reference examples for tone/structure only:\n" + reference_text if reference_text else ""}

Terms & conditions:"""

    return _strip_leading_clause_numbers(_strip_llm_meta_commentary(_llm_chat(prompt)))


def _draft_terms_and_conditions(project_title: str, known_facts: dict | None = None) -> str:
    """Same leak-detection/retry guardrail as _expand_brief, applied here too
    — this function predates that generalization and was missed when it was
    built, the same class of gap that let terms_and_conditions go completely
    unpopulated in the generic render path (found by the template coverage
    check). known_facts stops the party-name-hallucination bug found by
    visual QA from recurring here too."""
    known_facts = known_facts or {}
    reference_chunks = search(f"terms and conditions {project_title}", top_k=3)
    reference_text = "\n\n".join(
        f"({c['source']}, {c['unit_label']}): {c['text'][:400]}" for c in reference_chunks
    )

    result = _draft_terms_and_conditions_text(project_title, reference_text, known_facts)

    if reference_text:
        reference_entities = _extract_proper_nouns(reference_text)
        allowed_entities = _extract_proper_nouns(project_title) | _extract_proper_nouns(" ".join(known_facts.values()))
        leaked = _extract_proper_nouns(result) & reference_entities - allowed_entities
        if leaked:
            result = _draft_terms_and_conditions_text(project_title, "", known_facts)

    return result


def _generate_architecture_layers(project_title: str, problem_statement: str,
                                   known_facts: dict) -> str:
    """Derives the Solution & Technology Architecture diagram FROM the
    actual problem statement (executive summary + understanding +
    objectives, gathered by the caller) instead of requiring the user to
    hand-type the diagram structure. Still structured output, not free
    narrative prose — the prompt constrains the model to exactly the
    "Layer Name: Description" line format _parse_architecture_layers
    expects, same reliability reasoning as every other diagram-input
    decision in this module: a diagram needs to know precisely how many
    boxes and what's in each."""
    facts_block = ""
    if known_facts:
        facts_lines = "\n".join(f"- {label}: {value}" for label, value in known_facts.items())
        facts_block = f"\nKnown facts — use these names EXACTLY as given, verbatim:\n{facts_lines}\n"

    prompt = f"""Based on this problem statement for a technical proposal titled \
"{project_title}", propose a realistic layered technical architecture for the solution.
{facts_block}
Problem statement:
{problem_statement}

Output ONLY 4-6 lines, one per architecture layer, each in EXACTLY this format:
Layer Name: One-sentence description of what runs in this layer

Layers should flow top-to-bottom in a sensible order (e.g. Frontend, Security, \
Backend/API, Data). Be specific to what the problem statement actually describes — \
don't invent technology choices the problem statement gives no basis for; where the \
brief doesn't specify a technology, describe the layer's role generically instead \
of guessing a stack. No preamble, no numbering, no bullet points — just the "Layer \
Name: description" lines, nothing else."""

    result = _llm_chat(prompt)
    return _strip_llm_meta_commentary(result)


def _generate_flow_steps(project_title: str, problem_statement: str,
                          known_facts: dict) -> str:
    """Same reasoning as _generate_architecture_layers, for the primary
    process/data flow instead of the architecture stack."""
    facts_block = ""
    if known_facts:
        facts_lines = "\n".join(f"- {label}: {value}" for label, value in known_facts.items())
        facts_block = f"\nKnown facts — use these names EXACTLY as given, verbatim:\n{facts_lines}\n"

    prompt = f"""Based on this problem statement for a technical proposal titled \
"{project_title}", identify the single most important process or data flow the \
solution needs to support.
{facts_block}
Problem statement:
{problem_statement}

Output ONLY 4-6 steps, one per line, in the order they happen. Each step must be \
SHORT — 2-5 words, like a diagram box label, not a sentence: "User submits enquiry", \
"Validate input", "Persist to database", not "The user fills out and submits the \
enquiry form on the public-facing website". These render as boxes in a flow diagram, \
and a long phrase makes an oversized box. Be specific to what the problem statement \
actually describes, just terse about it. No preamble, no numbering (numbers are \
added automatically), no bullet points — just the plain step text, one per line, \
nothing else."""

    result = _llm_chat(prompt)
    return _strip_llm_meta_commentary(result)


def _generate_timeline_phases(project_title: str, problem_statement: str,
                               known_facts: dict) -> str:
    """Same derive-from-the-problem-statement reasoning as
    _generate_architecture_layers/_generate_flow_steps, for the
    implementation timeline instead of the architecture/flow diagrams."""
    facts_block = ""
    if known_facts:
        facts_lines = "\n".join(f"- {label}: {value}" for label, value in known_facts.items())
        facts_block = f"\nKnown facts — use these names EXACTLY as given, verbatim:\n{facts_lines}\n"

    prompt = f"""Based on this problem statement for a technical proposal titled \
"{project_title}", propose a realistic phased implementation timeline for the solution.
{facts_block}
Problem statement:
{problem_statement}

Output ONLY 3-5 lines, one per phase, each in EXACTLY this format (pipe-separated, \
three fields):
Phase Name | Week range | One-sentence description of what happens in this phase

Example: Phase 1 — Discovery & Design | Weeks 1-3 | Kick-off, requirement study and \
design approval before build starts.

Phases should flow in delivery order and cover the whole engagement end-to-end (e.g. \
discovery/design, build, deploy/hardening, testing/audit if relevant, go-live). Week \
ranges should be sequential and non-overlapping-in-spirit (a later phase can start \
before an earlier one fully ends, e.g. "Weeks 8-10" after "Weeks 3-8", but must not \
regress backward). Be specific to what the problem statement actually describes. No \
preamble, no numbering beyond what's already in the phase name, no bullet points — \
just the "Phase Name | Week range | description" lines, nothing else."""

    result = _llm_chat(prompt)
    return _strip_llm_meta_commentary(result)


def _generate_structured_lines(instructions: str, project_title: str, problem_statement: str,
                                known_facts: dict) -> str:
    """Shared driver for every "derive structured content from the problem
    statement" need added after the original two diagrams — table rows for
    the compliance matrix, modules & features, admin capabilities/roles,
    enquiry channels, security areas, SEO items, AMC scope, and the
    sitemap/core-module/security flow step lists. Rather than one
    near-identical _generate_* function per field (the pattern
    _generate_architecture_layers/_generate_flow_steps/
    _generate_timeline_phases established), `instructions` supplies only
    the task-specific framing and exact output format; this wraps it with
    the problem statement and known-facts grounding every one of them
    shares. The three original functions are left as they are (already
    verified working) rather than retrofitted onto this — new fields only."""
    facts_block = ""
    if known_facts:
        facts_lines = "\n".join(f"- {label}: {value}" for label, value in known_facts.items())
        facts_block = f"\nKnown facts — use these names EXACTLY as given, verbatim:\n{facts_lines}\n"

    prompt = f"""Based on this problem statement for a technical proposal titled \
"{project_title}":
{facts_block}
Problem statement:
{problem_statement}

{instructions}"""

    result = _llm_chat(prompt)
    return _strip_llm_meta_commentary(result)


def _generate_mockup_html(kind: str, project_title: str, problem_statement: str,
                           detail_lines: list[str], accent_hex: str,
                           font_family: str = "Calibri") -> str:
    """Ask the model to WRITE the mockup page itself (HTML + inline CSS),
    so section 14's screens are designed for this specific project rather
    than being the same fixed skeleton every proposal gets.

    Constraints in the prompt exist for concrete reasons, not politeness:
    everything must be inline and offline (headless Chrome renders this
    with no network — a CDN stylesheet or remote image would silently
    render as an unstyled or broken page), and the width is pinned so the
    screenshot crops predictably. The caller validates the resulting
    screenshot and falls back to the built-in template if it doesn't look
    like a real page — see `html_mockup.render_ai_mockup`."""
    screen = ("the PUBLIC-FACING HOME PAGE" if kind == "public_home"
              else "the ADMIN CMS DASHBOARD (logged-in back office)")
    detail = "\n".join(f"- {d}" for d in detail_lines if d) or "- (infer from the problem statement)"

    prompt = f"""You are designing a realistic UI mock screen for a technical proposal.

Project: {project_title}

Problem statement:
{problem_statement}

Design {screen} for this project. Real elements it should show:
{detail}

Output a COMPLETE, SELF-CONTAINED HTML document. Hard requirements:
- Inline <style> only. NO external CSS, NO CDN links, NO web fonts, NO <img> tags,
  NO JavaScript. It is rendered offline in a headless browser — anything remote
  renders broken.
- Use ONLY CSS for all visuals (colour blocks, borders, shadows, CSS shapes for
  icons/avatars). Represent images/logos as coloured CSS blocks.
- Primary/accent colour: #{accent_hex.lstrip('#')}. Font stack: '{font_family}',
  'Segoe UI', sans-serif.
- Wrap the page in a realistic browser window frame (title bar with three small
  circular dots and an address bar showing a plausible URL).
- Set body{{margin:0;padding:20px;background:#FFFFFF}} and put the frame in a
  container with width:1160px. Do not exceed that width.
- Total rendered height must stay under 1500px — design one screenful, not a
  long scrolling page.
- Use REAL text from the project above (real nav labels, real module names, real
  metric labels). No lorem ipsum, no placeholder text like "Item 1".

Output ONLY the raw HTML, starting with <!DOCTYPE html>. No markdown code fences,
no explanation before or after."""

    raw = _llm_chat(prompt)
    return _strip_code_fences(raw)


def _strip_code_fences(text: str) -> str:
    """Remove ```html ... ``` wrappers the model adds despite being asked
    not to — cheaper and more reliable than re-prompting, and a stray fence
    would otherwise render as literal text at the top of the page."""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines:
            lines = lines[1:]                      # drop opening fence (+ any language tag)
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _parse_pipe_rows(raw: str, min_fields: int = 2) -> list[list[str]]:
    """Splits "Field 1 | Field 2 | Field 3" lines into trimmed field lists —
    shared parser for every new pipe-delimited table/flow field. Pipe-
    delimited rather than colon-delimited (like the original architecture
    layers) because these descriptions are free prose that legitimately
    contains colons (e.g. "Gate: development starts after design
    approval"). Rows with fewer than `min_fields` fields are dropped
    rather than padded — a malformed row silently missing a column would
    otherwise misalign every column after it in the rendered table."""
    rows = []
    for line in (raw or "").strip().splitlines():
        line = line.strip().lstrip("-•").strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= min_fields:
            rows.append(parts)
    return rows


def _parse_architecture_layers(raw: str) -> list[tuple[str, str]]:
    """Turns user-typed "Layer Name: description" lines into (label, desc)
    pairs for the layered-architecture diagram. Structured input, not AI
    prose — a diagram needs to know exactly how many boxes and what goes
    in each, which free-form narrative text can't guarantee reliably."""
    layers = []
    for line in (raw or "").strip().splitlines():
        line = line.strip().lstrip("-•").strip()
        if not line:
            continue
        if ":" in line:
            label, desc = line.split(":", 1)
            layers.append((label.strip(), desc.strip()))
        else:
            layers.append((line, ""))
    return layers


def _parse_flow_steps(raw: str) -> list[str]:
    """One flow-diagram step per line — same structured-input reasoning
    as _parse_architecture_layers."""
    return [line.strip().lstrip("-•").strip() for line in (raw or "").strip().splitlines()
            if line.strip()]


def _parse_timeline_phases(raw: str) -> list[tuple[str, str, str]]:
    """Turns "Phase Name | Week range | description" lines into
    (phase_name, week_range, description) triples — pipe-separated rather
    than colon-separated like the other two diagram parsers, since a
    timeline description is free prose that legitimately contains colons
    (e.g. "Gate: development starts after design approval")."""
    phases = []
    for line in (raw or "").strip().splitlines():
        line = line.strip().lstrip("-•").strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            phases.append((parts[0], parts[1], parts[2]))
        elif len(parts) == 2:
            phases.append((parts[0], parts[1], ""))
    return phases


def _inject_generated_content(doc, content: dict, settings, assets_dir=None) -> None:
    """Replaces every `[[MARKER]]` placeholder paragraph (see
    build_technical_proposal_template's docstring for why these are
    plain-text markers, not Jinja fields) with real generated content —
    diagrams and UI mockups rendered as images
    (generation/diagram_render.py) embedded directly into the marker
    paragraph, and data tables/feature grids built as real Word tables
    inserted in the marker's place — using scripts/build_templates.py's
    functions against the already-rendered document. docxtpl's
    DocxTemplate wraps a real python-docx Document (`tpl.get_docx()`), and
    `.save()` persists that same object — so editing it here after
    render() is reflected in the saved file, the same mechanism as
    everything else in this module that manipulates the doc post-render.

    Grew from the original _inject_diagrams (architecture/flow/timeline
    only) into this broader function when the template grew from a
    9-section skeleton to the real proposal's full 17 sections — most of
    the new sections are tables, not diagrams, so this now takes one
    `content` dict rather than a positional arg per diagram to avoid an
    unwieldy 10+-parameter signature."""
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    from scripts.build_templates import (
        _add_layered_architecture_diagram, _add_flow_diagram, _add_timeline_diagram,
        _add_sitemap_diagram_image, _add_ui_mockup_image, _add_data_table, _add_feature_grid,
    )
    from scripts.build_templates import _collect_assets_into

    # The AI-written mock screens are real, standalone web pages — worth
    # handing back as source, not only flattened into the .docx. Saved
    # before rendering so the HTML survives even if the screenshot step
    # later fails validation and falls back to the built-in template.
    if assets_dir:
        from pathlib import Path as _P2
        adir = _P2(assets_dir)
        adir.mkdir(parents=True, exist_ok=True)
        for kind, html in (content.get("mockup_html") or {}).items():
            if html:
                (adir / f"mockup_{kind}.html").write_text(html, encoding="utf-8")

    def _find(marker: str):
        return next((p for p in doc.paragraphs if marker in p.text), None)

    def _image_marker(marker: str, build_fn, *args):
        p = _find(marker)
        if p is not None:
            # Scoped per call so each embedded PNG is also copied into the
            # downloadable assets folder, and the collector is always
            # cleared afterwards even if this diagram raises.
            with _collect_assets_into(assets_dir):
                build_fn(doc, p, *args, settings)

    def _table_marker(marker: str, build_fn, *args, **kwargs):
        p = _find(marker)
        if p is None:
            return
        table = build_fn(*args, settings=settings, **kwargs)
        if table is None:
            return
        p._p.addnext(table._tbl)
        p._p.getparent().remove(p._p)

    _image_marker("[[ARCHITECTURE_DIAGRAM]]", _add_layered_architecture_diagram,
                   content.get("layers") or [])
    _image_marker("[[DATA_FLOW_DIAGRAM]]", _add_flow_diagram, content.get("flow_steps") or [])
    _image_marker("[[TIMELINE_DIAGRAM]]", _add_timeline_diagram, content.get("timeline") or [])
    _image_marker("[[SITEMAP_DIAGRAM]]", _add_sitemap_diagram_image,
                   content.get("site_name", ""), content.get("sitemap_pillars") or [])
    _image_marker("[[CORE_MODULE_FLOW]]", _add_flow_diagram, content.get("core_module_flow") or [])
    _image_marker("[[SECURITY_FLOW]]", _add_flow_diagram, content.get("security_flow") or [])
    # Nav items, feature cards and admin sidebar items reflect THIS
    # project's own sitemap/modules/admin-capabilities rather than a
    # generic "Home / About / Services" skeleton every project used to
    # get — a real user asked whether section 14's mockups were the same
    # image every time; before this they effectively were.
    nav_items = [name for name, _subs in (content.get("sitemap_pillars") or [])]
    cards = [row[0] for row in (content.get("modules_features") or []) if row]
    sidebar_items = [row[0] for row in (content.get("admin_capabilities") or []) if row]
    ai_html = content.get("mockup_html") or {}
    _image_marker("[[UI_MOCKUP_HOME]]", _add_ui_mockup_image,
                   "public_home", content.get("project_title", ""), nav_items, cards, None,
                   ai_html.get("public_home"))
    _image_marker("[[UI_MOCKUP_ADMIN]]", _add_ui_mockup_image,
                   "admin_dashboard", content.get("project_title", ""), None, None, sidebar_items,
                   ai_html.get("admin_dashboard"))

    _table_marker("[[COMPLIANCE_MATRIX]]", _add_data_table, doc,
                  headers=["#", "Requirement", "Proposed Solution", "Status"],
                  rows=[[str(i + 1), req, sol, "Complied"]
                        for i, (req, sol) in enumerate(content.get("compliance_items") or [])])
    _table_marker("[[MODULES_TABLE]]", _add_data_table, doc,
                  headers=["Module", "What it does"], rows=content.get("modules_features") or [])
    _table_marker("[[ADMIN_ROLES_TABLE]]", _add_data_table, doc,
                  headers=["Role", "Can do"], rows=content.get("admin_roles") or [])
    _table_marker("[[ENQUIRY_TABLE]]", _add_data_table, doc,
                  headers=["Form", "Captured", "Routed to"], rows=content.get("enquiry_channels") or [])
    _table_marker("[[SECURITY_TABLE]]", _add_data_table, doc,
                  headers=["Area", "What we implement"], rows=content.get("security_areas") or [])
    _table_marker("[[SEO_TABLE]]", _add_data_table, doc,
                  headers=["Item", "Detail"], rows=content.get("seo_performance_items") or [])
    _table_marker("[[AMC_TABLE]]", _add_data_table, doc,
                  headers=["Scope Area", "What's Covered"], rows=content.get("amc_scope") or [])
    _table_marker("[[ADMIN_FEATURE_GRID]]", _add_feature_grid, doc,
                  items=[(row[0], row[1]) for row in content.get("admin_capabilities") or [] if len(row) >= 2])


def _next_version(prefix: str, doc_no: str) -> int:
    """Auto-versioning per the RFP's deliverable spec (v1, v2, v3...) — scans
    what's already on disk for this document number rather than tracking
    version state separately, so it can't drift out of sync with reality.
    `prefix` separates document types (work_order_/mou_) so numbering never
    collides across templates."""
    safe = re.sub(r"[^\w\-]", "_", doc_no)
    existing = list(OUTPUT_DIR.glob(f"{prefix}_{safe}_v*.docx"))
    if not existing:
        return 1
    versions = [int(m.group(1)) for p in existing if (m := re.search(r"_v(\d+)\.docx$", p.name))]
    return max(versions) + 1 if versions else 1


def _escape_context(context: dict) -> dict:
    # docxtpl does NOT XML-escape substituted values by default — a bare "&"
    # (or <, >) produces invalid XML inside the .docx, which then gets
    # silently mangled on read-back (confirmed: "IT & Digital Initiatives"
    # round-tripped as "IT  Digital Initiatives", the & just vanished).
    # Escaping here, once, for every field, is cheaper than hoping no QCI
    # document ever contains an ampersand.
    return {k: (xml_escape(v) if isinstance(v, str) else v) for k, v in context.items()}


@dataclass
class NarrativeField:
    """One AI-expanded section: a short user brief becomes a full paragraph,
    grounded by retrieval, protected by the leak-detection guardrail — the
    exact mechanism proven on Work Order's scope-of-work, now reusable
    across every template instead of rewritten per document type."""
    brief_field: str
    output_field: str
    subject_label: str
    doc_label: str
    reference_query_fields: tuple = ()
    # Fields whose VALUES get stated outright in the generation prompt as
    # "known facts, use verbatim" — this is what stops the model inventing
    # substitute names for parties the brief doesn't happen to mention (see
    # the docstring on _generate_narrative_text for the bug this fixes).
    # Distinct from reference_query_fields, which only shapes the retrieval
    # search — a field can (and usually should) be in both.
    context_fields: tuple = ()


@dataclass
class TemplateSpec:
    """Everything that makes one template different from another — the
    render logic itself (render_document, below) is identical for all of
    them. Adding template #13 later means adding a spec + a .docx layout,
    not new engine code."""
    key: str
    display_name: str
    template_file: str
    filename_prefix: str
    doc_number_field: str
    fields: list
    narrative_fields: tuple


# Mapping from spec keys to the build function + recipe args needed for
# dynamic template rebuilding when custom TemplateSettings are provided.
# Imported lazily (at call time) to avoid circular imports with
# scripts/build_templates.py.
_SPEC_KEY_TO_BUILD_INFO: dict | None = None


def _get_build_info() -> dict:
    """Lazily build a mapping from spec.key to the build function + kwargs
    needed to dynamically rebuild a template with custom settings."""
    global _SPEC_KEY_TO_BUILD_INFO
    if _SPEC_KEY_TO_BUILD_INFO is not None:
        return _SPEC_KEY_TO_BUILD_INFO

    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    from scripts.build_templates import (
        build_work_order_template, build_mou_template,
        build_generic_template, build_technical_proposal_template, REMAINING_TEMPLATES,
    )

    info = {
        "work_order_services": {"fn": build_work_order_template, "kwargs": {}},
        "mou_institutional": {"fn": build_mou_template, "kwargs": {}},
        "technical_proposal": {"fn": build_technical_proposal_template, "kwargs": {}},
    }
    # Map each generic recipe's filename back to the spec key that uses it
    _filename_to_key = {s.template_file: s.key for s in ALL_TEMPLATE_SPECS}
    for recipe in REMAINING_TEMPLATES:
        key = _filename_to_key.get(recipe["filename"])
        if key:
            info[key] = {"fn": build_generic_template, "kwargs": dict(recipe)}

    _SPEC_KEY_TO_BUILD_INFO = info
    return info


def render_document(session: DraftSession, spec: TemplateSpec,
                    settings: TemplateSettings | None = None) -> Path:
    """The one render function every template uses. Replaces per-template
    render_work_order/render_mou-style duplication — those two now exist
    only as thin backward-compatible wrappers around this.

    When `settings` is provided, the template .docx is dynamically rebuilt
    with those settings (cover page, TOC, declarations, custom colours/
    fonts/logos) before being rendered with docxtpl. When settings is None,
    behaviour is unchanged — uses the pre-built static template."""
    if not session.is_complete():
        raise ValueError("Cannot render — clarifying questions are not fully answered yet.")

    context = dict(session.answers)
    for nf in spec.narrative_fields:
        brief = context.pop(nf.brief_field)
        ref_query = " ".join(str(context.get(f, "")) for f in nf.reference_query_fields).strip() or brief
        # Humanized labels, not raw field names — confirmed necessary by
        # testing, not just theoretical: with the raw name as the label
        # ("department_a_name: Quality Council of India"), the model echoed
        # the literal internal field name into the output as a parenthetical
        # ("...Quality Council of India (department_a_name) will conduct...").
        known_facts = {f.replace("_", " ").title(): context[f] for f in nf.context_fields if f in context}
        context[nf.output_field] = _expand_brief(brief, nf.subject_label, nf.doc_label, ref_query, known_facts)

    # Work Order — Services/Consultancy is the one template still needing a
    # Terms & Conditions section drafted directly from context rather than a
    # user brief — a legacy special case from before the generic spec system
    # existed. Found by scripts/check_template_coverage.py: this placeholder
    # was rendering completely blank in every real draft through this path,
    # since narrative_fields never covered it. Kept as a targeted branch
    # rather than forcing a one-off pattern into NarrativeField's shape.
    if spec.key == "work_order_services":
        context["terms_and_conditions"] = _draft_terms_and_conditions(
            context["project_title"],
            known_facts={"Issuing Organisation": context.get("issuing_organisation", ""),
                         "Contractor": context.get("contractor_name", "")},
        )

    # Technical Proposal's two diagrams (Solution & Technology Architecture,
    # Data Flow Diagram) are structured input, not AI narrative text — see
    # NarrativeField's docstring for why free-form prose can't lay out a
    # diagram reliably. Popped from context (not real Jinja fields) so
    # docxtpl doesn't choke on a value it was never meant to substitute;
    # they're injected into the actual document after rendering instead.
    #
    # If the user left the raw field blank, the diagram is derived FROM the
    # problem statement instead of requiring them to hand-author it — the
    # explicit ask that drove this: "it should be able to make architecture,
    # flow diagrams... accurately" from the proposal content, not just
    # render whatever structure the user manually typed. Grounded in the
    # SAME expanded narrative text already produced above (executive
    # summary + understanding + objectives), not a fresh unrelated brief —
    # keeps the diagram consistent with what the rest of the document
    # actually says. Still goes through the same structured-line parser
    # either way, so a manually-typed diagram and an AI-derived one are
    # handled identically downstream.
    generated_content = None
    if spec.key == "technical_proposal":
        problem_statement = "\n\n".join(filter(None, [
            context.get("executive_summary"), context.get("understanding"),
            context.get("objectives"),
        ]))
        known_facts = {"Client": context.get("client_name", ""),
                       "Submitted By": context.get("submitted_by", "")}
        project_title = context.get("project_title", "")

        def _structured(field_name: str, instructions: str) -> str:
            raw = context.pop(field_name, "")
            if not raw.strip():
                raw = _generate_structured_lines(instructions, project_title, problem_statement, known_facts)
            return raw

        raw_layers = context.pop("architecture_layers", "")
        if not raw_layers.strip():
            raw_layers = _generate_architecture_layers(project_title, problem_statement, known_facts)
        diagram_layers = _parse_architecture_layers(raw_layers)

        raw_steps = context.pop("data_flow_steps", "")
        if not raw_steps.strip():
            raw_steps = _generate_flow_steps(project_title, problem_statement, known_facts)
        diagram_steps = _parse_flow_steps(raw_steps)

        raw_timeline = context.pop("implementation_timeline", "")
        if not raw_timeline.strip():
            raw_timeline = _generate_timeline_phases(project_title, problem_statement, known_facts)
        diagram_timeline = _parse_timeline_phases(raw_timeline)

        # Every field below follows the same "leave blank to auto-derive
        # from the problem statement" convention as the three diagrams
        # above — see build_technical_proposal_template's docstring for
        # why these are structured pipe-delimited lines, not free prose.
        raw_sitemap = _structured("sitemap_pillars",
            "Propose an information architecture for this website: 4-6 top-level navigation "
            "pillars, each with 3-5 sub-pages.\n\nOutput ONLY lines in EXACTLY this format "
            "(pipe-separated, two fields, sub-pages comma-separated within the second field):\n"
            "Pillar Name | Sub-page one, Sub-page two, Sub-page three\n\n"
            "Example: Home | Highlights, Latest news, Notices, Quick links\n\n"
            "Be specific to what the problem statement actually describes. No preamble, no "
            "numbering, no bullet points — just the lines, nothing else.")
        sitemap_pillars = [(r[0], [i.strip() for i in r[1].split(",") if i.strip()])
                           for r in _parse_pipe_rows(raw_sitemap, 2)]

        raw_compliance = _structured("compliance_items",
            "List 6-8 rows mapping key requirements implied by the problem statement to how "
            "the proposed solution meets each one.\n\nOutput ONLY lines in EXACTLY this format "
            "(pipe-separated, two fields):\nRequirement | Proposed solution\n\n"
            "Example: Hosting in a MeitY-approved data centre in India | Deployment to an "
            "approved provider with production environment, SSL and hardening\n\n"
            "Be specific to what the problem statement actually describes. No preamble, no "
            "numbering, no bullet points — just the lines, nothing else.")
        compliance_items = [(r[0], r[1]) for r in _parse_pipe_rows(raw_compliance, 2)]

        raw_modules = _structured("modules_features",
            "List 6-10 modules/features of the public-facing website this solution delivers.\n\n"
            "Output ONLY lines in EXACTLY this format (pipe-separated, two fields):\n"
            "Module | What the user gets\n\nExample: News & Updates | Dated, paginated listing "
            "with detail pages and attachments\n\nBe specific to what the problem statement "
            "actually describes. No preamble, no numbering, no bullet points — just the lines, "
            "nothing else.")
        modules_features = _parse_pipe_rows(raw_modules, 2)

        raw_core_flow = _structured("core_module_flow",
            "Identify the single centrepiece module of this solution (the feature the whole "
            "engagement exists to deliver) and describe the user's journey through it as 4-6 "
            "short steps.\n\nOutput ONLY 4-6 steps, one per line, SHORT (2-5 words, like a "
            "diagram box label). No preamble, no numbering (added automatically), no bullet "
            "points — just the plain step text, one per line, nothing else.")
        core_module_flow = _parse_flow_steps(raw_core_flow)

        raw_admin_caps = _structured("admin_capabilities",
            "List 4-6 capability areas of the admin CMS portal for this solution.\n\nOutput "
            "ONLY lines in EXACTLY this format (pipe-separated, two fields):\n"
            "Feature | Description\n\nExample: Content management | News, notices, tenders, "
            "events and downloads, each with publish/expiry control\n\nBe specific to what the "
            "problem statement actually describes. No preamble, no numbering, no bullet points "
            "— just the lines, nothing else.")
        admin_capabilities = _parse_pipe_rows(raw_admin_caps, 2)

        raw_admin_roles = _structured("admin_roles",
            "List 3-4 admin CMS user roles for this solution and what each can do.\n\nOutput "
            "ONLY lines in EXACTLY this format (pipe-separated, two fields):\nRole | Can do\n\n"
            "Example: Content Editor | Create and publish news, notices and events\n\nBe "
            "specific to what the problem statement actually describes. No preamble, no "
            "numbering, no bullet points — just the lines, nothing else.")
        admin_roles = _parse_pipe_rows(raw_admin_roles, 2)

        raw_enquiry = _structured("enquiry_channels",
            "List 2-4 enquiry/contact form types this solution needs.\n\nOutput ONLY lines in "
            "EXACTLY this format (pipe-separated, three fields):\nForm | Captured | Routed to\n\n"
            "Example: General contact enquiry | Name, organisation, email, subject, message | "
            "Admin portal + notification inbox\n\nBe specific to what the problem statement "
            "actually describes. No preamble, no numbering, no bullet points — just the lines, "
            "nothing else.")
        enquiry_channels = _parse_pipe_rows(raw_enquiry, 3)

        raw_security_flow = _structured("security_flow",
            "Describe the security/hardening/certification pipeline this solution goes through "
            "before go-live, as 4-6 short steps.\n\nOutput ONLY 4-6 steps, one per line, SHORT "
            "(2-5 words, like a diagram box label). No preamble, no numbering (added "
            "automatically), no bullet points — just the plain step text, one per line, "
            "nothing else.")
        security_flow = _parse_flow_steps(raw_security_flow)

        raw_security_areas = _structured("security_areas",
            "List 4-6 security/hosting/compliance areas this solution addresses.\n\nOutput ONLY "
            "lines in EXACTLY this format (pipe-separated, two fields):\n"
            "Area | What we implement\n\nExample: Application security | Server-side validation "
            "on every input, CSRF tokens, secure session cookies, security headers\n\nBe "
            "specific to what the problem statement actually describes. No preamble, no "
            "numbering, no bullet points — just the lines, nothing else.")
        security_areas = _parse_pipe_rows(raw_security_areas, 2)

        raw_seo = _structured("seo_performance_items",
            "List 5-8 multilingual/SEO/performance items relevant to this solution.\n\nOutput "
            "ONLY lines in EXACTLY this format (pipe-separated, two fields):\nItem | Detail\n\n"
            "Example: SEO-friendly URLs | Page titles & meta descriptions\n\nBe specific to what "
            "the problem statement actually describes. No preamble, no numbering, no bullet "
            "points — just the lines, nothing else.")
        seo_performance_items = _parse_pipe_rows(raw_seo, 2)

        raw_amc = _structured("amc_scope",
            "List 3-5 annual maintenance & support scope areas for this solution once live.\n\n"
            "Output ONLY lines in EXACTLY this format (pipe-separated, two fields):\n"
            "Scope area | What's covered\n\nExample: Corrective maintenance | Bug fixes and "
            "defect resolution within agreed SLAs\n\nBe specific to what the problem statement "
            "actually describes. No preamble, no numbering, no bullet points — just the lines, "
            "nothing else.")
        amc_scope = _parse_pipe_rows(raw_amc, 2)

        # Section 14's mock screens: ask the model to design each page for
        # THIS project (HTML it writes itself), rather than filling a fixed
        # skeleton. Failures here are non-fatal by design — a rejected or
        # errored mockup falls back to the built-in template downstream, so
        # a bad HTML generation costs a slightly less bespoke picture, never
        # a failed draft.
        accent = getattr(settings, "accent_colour", "1F4E78") if settings else "1F4E78"
        font = getattr(settings, "font_family", "Calibri") if settings else "Calibri"
        mockup_html = {}
        for kind, details in (
            ("public_home", [p for p, _ in sitemap_pillars] + [r[0] for r in modules_features if r]),
            ("admin_dashboard", [r[0] for r in admin_capabilities if r] + [r[0] for r in admin_roles if r]),
        ):
            try:
                mockup_html[kind] = _generate_mockup_html(
                    kind, project_title, problem_statement, details, accent, font)
            except Exception as e:  # noqa: BLE001 — cosmetic feature, never fail a draft
                print(f"[mockup] HTML generation failed for {kind} ({type(e).__name__}); "
                      f"using built-in template.")
                mockup_html[kind] = None

        generated_content = {
            "mockup_html": mockup_html,
            "layers": diagram_layers, "flow_steps": diagram_steps, "timeline": diagram_timeline,
            "project_title": project_title, "site_name": context.get("client_name", project_title),
            "sitemap_pillars": sitemap_pillars, "compliance_items": compliance_items,
            "modules_features": modules_features, "core_module_flow": core_module_flow,
            "admin_capabilities": admin_capabilities, "admin_roles": admin_roles,
            "enquiry_channels": enquiry_channels, "security_flow": security_flow,
            "security_areas": security_areas, "seo_performance_items": seo_performance_items,
            "amc_scope": amc_scope,
        }

    doc_no = session.answers[spec.doc_number_field]
    version = _next_version(spec.filename_prefix, doc_no)
    context["version"] = f"v{version}"
    context = _escape_context(context)

    # ── Template selection: static (default) or dynamically rebuilt ──
    # tmp_dir is cleaned up in the finally below — without that, every render
    # with custom settings leaked a temp directory that was never removed.
    tmp_dir = None
    try:
        if settings is not None:
            # Dynamically rebuild the template with custom settings so cover
            # page, TOC, declarations, colours, fonts, logos etc. all reflect
            # the user's choices. The rebuilt template goes into a temp location
            # to avoid overwriting the stored defaults.
            import tempfile
            build_info = _get_build_info()
            info = build_info.get(spec.key)
            if info:
                # Temporarily redirect the build output into a temp dir
                import scripts.build_templates as _bt
                original_dir = _bt.TEMPLATES_DIR
                tmp_dir = Path(tempfile.mkdtemp(prefix="qci_tpl_"))
                _bt.TEMPLATES_DIR = tmp_dir
                try:
                    info["fn"](settings=settings, **info["kwargs"])
                finally:
                    _bt.TEMPLATES_DIR = original_dir
                template_path = tmp_dir / spec.template_file
            else:
                # Fallback — spec not in the build map, use static template
                template_path = TEMPLATES_DIR / spec.template_file
        else:
            template_path = TEMPLATES_DIR / spec.template_file

        tpl = DocxTemplate(template_path)
        tpl.render(context)

        if spec.key == "technical_proposal":
            # NOT tpl.get_docx() — that calls init_docx(reload=True), which
            # RE-LOADS from the original template file whenever is_rendered
            # is True (confirmed by reading docxtpl's source after this
            # produced a fully unrendered document — every {{ field }}
            # showed up as raw text). tpl.docx already holds the rendered
            # document; use it directly.
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            _safe = re.sub(r"[^\w\-]", "_", doc_no)
            _assets = OUTPUT_DIR / f"{spec.filename_prefix}_{_safe}_v{version}_assets"
            _inject_generated_content(tpl.docx, generated_content, settings,
                                       assets_dir=_assets)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]", "_", doc_no)
        out_path = OUTPUT_DIR / f"{spec.filename_prefix}_{safe}_v{version}.docx"
        tpl.save(out_path)
        return out_path
    finally:
        if tmp_dir is not None:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================================
# Remaining 10 templates — RFP wants 12 total (3 each across Work Order, MoU,
# Agreement, Proposal). The RFP names the count but not what distinguishes
# the 3 variants within each type; these variant splits are a reasonable
# judgment call, not QCI's spec — worth a pre-bid query to confirm before
# this goes into an actual submission. All use render_document() above; no
# new engine code, just field schemas + a .docx layout per template.
# ============================================================================

# ---- Work Order variant 2: Goods/Supply ----
WORK_ORDER_GOODS_FIELDS = [
    ("work_order_no", "What is the work order number?", None),
    ("work_order_date", "What is the issue date?", str(date.today())),
    ("issuing_organisation", "Issuing organisation?", "Source Soft Solutions"),
    ("supplier_name", "Who is the supplier?", None),
    ("supplier_address", "Supplier's address?", None),
    ("item_description_brief", "Briefly, what goods/items are being supplied? (this gets expanded)", None),
    ("quantity_and_value", "Quantity and total order value?", None),
    ("delivery_date", "Required delivery date?", None),
    ("delivery_location", "Delivery location?", None),
    ("warranty_terms", "Warranty terms?", None),
    ("authorized_signatory_name", "Who is signing on behalf of the issuing organisation (name)?", None),
    ("authorized_signatory_designation", "Their designation?", None),
]
WORK_ORDER_GOODS_SPEC = TemplateSpec(
    key="work_order_goods", display_name="Work Order — Goods/Supply",
    template_file="work_order_goods_template.docx", filename_prefix="work_order_goods",
    doc_number_field="work_order_no", fields=WORK_ORDER_GOODS_FIELDS,
    narrative_fields=(NarrativeField("item_description_brief", "item_description", "supplied goods description",
                                      "government supply work order", ("supplier_name",),
                                      context_fields=("issuing_organisation", "supplier_name")),),
)

# ---- Work Order variant 3: AMC/Maintenance ----
WORK_ORDER_AMC_FIELDS = [
    ("amc_no", "What is the AMC reference number?", None),
    ("amc_date", "What is the issue date?", str(date.today())),
    ("issuing_organisation", "Issuing organisation?", "Source Soft Solutions"),
    ("vendor_name", "Who is the maintenance vendor?", None),
    ("vendor_address", "Vendor's address?", None),
    ("equipment_covered_brief", "Briefly, what equipment/systems does this AMC cover? (this gets expanded)", None),
    ("amc_period", "What is the AMC period? (e.g. '1 year from go-live')", None),
    ("service_frequency", "Service visit frequency? (e.g. 'quarterly preventive maintenance')", None),
    ("response_time_sla", "Response time SLA for breakdowns?", None),
    ("amc_value", "AMC value?", None),
    ("authorized_signatory_name", "Who is signing on behalf of the issuing organisation (name)?", None),
    ("authorized_signatory_designation", "Their designation?", None),
]
WORK_ORDER_AMC_SPEC = TemplateSpec(
    key="work_order_amc", display_name="Work Order — AMC/Maintenance",
    template_file="work_order_amc_template.docx", filename_prefix="work_order_amc",
    doc_number_field="amc_no", fields=WORK_ORDER_AMC_FIELDS,
    narrative_fields=(NarrativeField("equipment_covered_brief", "equipment_covered", "equipment/systems coverage",
                                      "annual maintenance contract", ("vendor_name",),
                                      context_fields=("issuing_organisation", "vendor_name")),),
)

# ---- MoU variant 2: International/Bilateral ----
MOU_INTERNATIONAL_FIELDS = [
    ("mou_no", "What is the MoU reference number?", None),
    ("mou_date", "What is the date of this MoU?", str(date.today())),
    ("indian_party_name", "Indian party?", "Source Soft Solutions"),
    ("foreign_party_name", "Foreign party (organisation name)?", None),
    ("foreign_party_country", "Foreign party's country?", None),
    ("purpose_brief", "Briefly, what is the purpose of this bilateral MoU? (this gets expanded)", None),
    ("areas_of_cooperation_brief", "Briefly, what areas of cooperation does this cover? (this gets expanded)", None),
    ("duration", "Duration of this MoU?", None),
    ("signatory_indian_name", "Signatory for the Indian party (name)?", None),
    ("signatory_indian_designation", "Their designation?", None),
    ("signatory_foreign_name", "Signatory for the foreign party (name)?", None),
    ("signatory_foreign_designation", "Their designation?", None),
]
MOU_INTERNATIONAL_SPEC = TemplateSpec(
    key="mou_international", display_name="MoU — International/Bilateral",
    template_file="mou_international_template.docx", filename_prefix="mou_intl",
    doc_number_field="mou_no", fields=MOU_INTERNATIONAL_FIELDS,
    narrative_fields=(
        NarrativeField("purpose_brief", "purpose", "purpose", "bilateral memorandum of understanding", ("foreign_party_name",),
                       context_fields=("indian_party_name", "foreign_party_name")),
        NarrativeField("areas_of_cooperation_brief", "areas_of_cooperation", "areas of cooperation",
                       "bilateral memorandum of understanding", ("foreign_party_name",),
                       context_fields=("indian_party_name", "foreign_party_name")),
    ),
)

# ---- MoU variant 3: Inter-departmental/Government ----
MOU_INTERDEPT_FIELDS = [
    ("mou_no", "What is the MoU reference number?", None),
    ("mou_date", "What is the date of this MoU?", str(date.today())),
    ("department_a_name", "First department/body?", "Source Soft Solutions"),
    ("department_b_name", "Second department/body?", None),
    ("subject_matter_brief", "Briefly, what is this MoU about? (this gets expanded)", None),
    ("responsibilities_brief", "Briefly, what are each party's responsibilities? (this gets expanded)", None),
    ("review_period", "How often will this MoU be reviewed? (e.g. 'annually')", None),
    ("signatory_a_name", "Signatory for the first party (name)?", None),
    ("signatory_a_designation", "Their designation?", None),
    ("signatory_b_name", "Signatory for the second party (name)?", None),
    ("signatory_b_designation", "Their designation?", None),
]
MOU_INTERDEPT_SPEC = TemplateSpec(
    key="mou_interdept", display_name="MoU — Inter-departmental/Government",
    template_file="mou_interdept_template.docx", filename_prefix="mou_interdept",
    doc_number_field="mou_no", fields=MOU_INTERDEPT_FIELDS,
    narrative_fields=(
        NarrativeField("subject_matter_brief", "subject_matter", "subject matter", "inter-departmental memorandum of understanding", ("department_b_name",),
                       context_fields=("department_a_name", "department_b_name")),
        NarrativeField("responsibilities_brief", "responsibilities", "responsibilities", "inter-departmental memorandum of understanding", ("department_b_name",),
                       context_fields=("department_a_name", "department_b_name")),
    ),
)

# ---- Agreement variant 1: Service Agreement ----
AGREEMENT_SERVICE_FIELDS = [
    ("agreement_no", "What is the agreement number?", None),
    ("agreement_date", "What is the agreement date?", str(date.today())),
    ("client_name", "Client?", None),
    ("provider_name", "Service provider?", None),
    ("provider_address", "Provider's address?", None),
    ("service_description_brief", "Briefly, what services are covered? (this gets expanded)", None),
    ("sla_terms_brief", "Briefly, what are the SLA/performance terms? (this gets expanded)", None),
    ("contract_value", "Contract value?", None),
    ("contract_duration", "Contract duration?", None),
    ("termination_notice_period", "Termination notice period?", None),
    ("signatory_provider_name", "Signatory for the provider (name)?", None),
    ("signatory_provider_designation", "Their designation?", None),
    ("signatory_client_name", "Signatory for the client (name)?", None),
    ("signatory_client_designation", "Their designation?", None),
]
AGREEMENT_SERVICE_SPEC = TemplateSpec(
    key="agreement_service", display_name="Agreement — Service",
    template_file="agreement_service_template.docx", filename_prefix="agreement_service",
    doc_number_field="agreement_no", fields=AGREEMENT_SERVICE_FIELDS,
    narrative_fields=(
        NarrativeField("service_description_brief", "service_description", "service description", "service agreement", ("provider_name",),
                       context_fields=("client_name", "provider_name")),
        NarrativeField("sla_terms_brief", "sla_terms", "SLA/performance terms", "service agreement", ("provider_name",),
                       context_fields=("client_name", "provider_name")),
    ),
)

# ---- Agreement variant 2: Consultancy Agreement ----
AGREEMENT_CONSULTANCY_FIELDS = [
    ("agreement_no", "What is the agreement number?", None),
    ("agreement_date", "What is the agreement date?", str(date.today())),
    ("client_name", "Client?", None),
    ("consultant_name", "Consultant?", None),
    ("consultant_address", "Consultant's address?", None),
    ("consultancy_scope_brief", "Briefly, what is the scope of this consultancy? (this gets expanded)", None),
    ("deliverables_brief", "Briefly, what are the key deliverables? (this gets expanded)", None),
    ("fee_structure", "Fee structure?", None),
    ("engagement_period", "Engagement period?", None),
    ("signatory_consultant_name", "Signatory for the consultant (name)?", None),
    ("signatory_consultant_designation", "Their designation?", None),
    ("signatory_client_name", "Signatory for the client (name)?", None),
    ("signatory_client_designation", "Their designation?", None),
]
AGREEMENT_CONSULTANCY_SPEC = TemplateSpec(
    key="agreement_consultancy", display_name="Agreement — Consultancy",
    template_file="agreement_consultancy_template2.docx", filename_prefix="agreement_consultancy",
    doc_number_field="agreement_no", fields=AGREEMENT_CONSULTANCY_FIELDS,
    narrative_fields=(
        NarrativeField("consultancy_scope_brief", "consultancy_scope", "consultancy scope", "consultancy agreement", ("consultant_name",),
                       context_fields=("client_name", "consultant_name")),
        NarrativeField("deliverables_brief", "deliverables", "key deliverables", "consultancy agreement", ("consultant_name",),
                       context_fields=("client_name", "consultant_name")),
    ),
)

# ---- Agreement variant 3: Licensing/IP Agreement ----
AGREEMENT_LICENSING_FIELDS = [
    ("agreement_no", "What is the agreement number?", None),
    ("agreement_date", "What is the agreement date?", str(date.today())),
    ("licensor_name", "Licensor?", "Source Soft Solutions"),
    ("licensee_name", "Licensee?", None),
    ("licensee_address", "Licensee's address?", None),
    ("ip_description_brief", "Briefly, what IP/materials are being licensed? (this gets expanded)", None),
    ("usage_terms_brief", "Briefly, what are the usage terms/restrictions? (this gets expanded)", None),
    ("royalty_terms", "Royalty/fee terms?", None),
    ("license_duration", "License duration?", None),
    ("signatory_licensor_name", "Signatory for the licensor (name)?", None),
    ("signatory_licensor_designation", "Their designation?", None),
    ("signatory_licensee_name", "Signatory for the licensee (name)?", None),
    ("signatory_licensee_designation", "Their designation?", None),
]
AGREEMENT_LICENSING_SPEC = TemplateSpec(
    key="agreement_licensing", display_name="Agreement — Licensing/IP",
    template_file="agreement_licensing_template.docx", filename_prefix="agreement_licensing",
    doc_number_field="agreement_no", fields=AGREEMENT_LICENSING_FIELDS,
    narrative_fields=(
        NarrativeField("ip_description_brief", "ip_description", "licensed IP/materials description", "licensing agreement", ("licensee_name",),
                       context_fields=("licensor_name", "licensee_name")),
        NarrativeField("usage_terms_brief", "usage_terms", "usage terms and restrictions", "licensing agreement", ("licensee_name",),
                       context_fields=("licensor_name", "licensee_name")),
    ),
)

# ---- Proposal variant 1: Technical Proposal ----
PROPOSAL_TECHNICAL_FIELDS = [
    ("proposal_no", "What is the proposal number?", None),
    ("proposal_date", "What is the proposal date?", str(date.today())),
    ("submitted_by", "Who is submitting this proposal (bidder name)?", None),
    ("submitted_to", "Submitted to?", None),
    ("project_title", "What is the project title?", None),
    ("technical_approach_brief", "Briefly, what is the proposed technical approach? (this gets expanded)", None),
    ("team_composition_brief", "Briefly, describe the proposed team. (this gets expanded)", None),
    ("implementation_timeline", "Implementation timeline?", None),
    ("signatory_name", "Authorized signatory (name)?", None),
    ("signatory_designation", "Their designation?", None),
]
PROPOSAL_TECHNICAL_SPEC = TemplateSpec(
    key="proposal_technical", display_name="Proposal — Technical",
    template_file="proposal_technical_template.docx", filename_prefix="proposal_technical",
    doc_number_field="proposal_no", fields=PROPOSAL_TECHNICAL_FIELDS,
    narrative_fields=(
        NarrativeField("technical_approach_brief", "technical_approach", "technical approach", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "submitted_to", "project_title")),
        NarrativeField("team_composition_brief", "team_composition", "team composition", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "submitted_to", "project_title")),
    ),
)

# ---- Proposal variant 2: Financial Proposal ----
PROPOSAL_FINANCIAL_FIELDS = [
    ("proposal_no", "What is the proposal number?", None),
    ("proposal_date", "What is the proposal date?", str(date.today())),
    ("submitted_by", "Who is submitting this proposal (bidder name)?", None),
    ("submitted_to", "Submitted to?", None),
    ("project_title", "What is the project title?", None),
    ("cost_breakdown_brief", "Briefly, summarise the cost breakdown. (this gets expanded)", None),
    ("payment_schedule_brief", "Briefly, describe the proposed payment schedule. (this gets expanded)", None),
    ("total_value", "Total proposal value?", None),
    ("validity_period", "Proposal validity period? (e.g. '120 days')", None),
    ("signatory_name", "Authorized signatory (name)?", None),
    ("signatory_designation", "Their designation?", None),
]
PROPOSAL_FINANCIAL_SPEC = TemplateSpec(
    key="proposal_financial", display_name="Proposal — Financial",
    template_file="proposal_financial_template.docx", filename_prefix="proposal_financial",
    doc_number_field="proposal_no", fields=PROPOSAL_FINANCIAL_FIELDS,
    narrative_fields=(
        NarrativeField("cost_breakdown_brief", "cost_breakdown", "cost breakdown summary", "financial proposal", ("project_title",),
                       context_fields=("submitted_by", "submitted_to", "project_title")),
        NarrativeField("payment_schedule_brief", "payment_schedule", "payment schedule", "financial proposal", ("project_title",),
                       context_fields=("submitted_by", "submitted_to", "project_title")),
    ),
)

# ---- Proposal variant 3: Combined Technical + Financial ----
PROPOSAL_COMBINED_FIELDS = [
    ("proposal_no", "What is the proposal number?", None),
    ("proposal_date", "What is the proposal date?", str(date.today())),
    ("submitted_by", "Who is submitting this proposal (bidder name)?", None),
    ("submitted_to", "Submitted to?", None),
    ("project_title", "What is the project title?", None),
    ("executive_summary_brief", "Briefly, summarise the overall proposal. (this gets expanded)", None),
    ("approach_and_cost_brief", "Briefly, describe the approach and cost basis together. (this gets expanded)", None),
    ("total_value", "Total proposal value?", None),
    ("implementation_timeline", "Implementation timeline?", None),
    ("signatory_name", "Authorized signatory (name)?", None),
    ("signatory_designation", "Their designation?", None),
]
PROPOSAL_COMBINED_SPEC = TemplateSpec(
    key="proposal_combined", display_name="Proposal — Combined Technical & Financial",
    template_file="proposal_combined_template.docx", filename_prefix="proposal_combined",
    doc_number_field="proposal_no", fields=PROPOSAL_COMBINED_FIELDS,
    narrative_fields=(
        NarrativeField("executive_summary_brief", "executive_summary", "executive summary", "combined technical and financial proposal", ("project_title",),
                       context_fields=("submitted_by", "submitted_to", "project_title")),
        NarrativeField("approach_and_cost_brief", "approach_and_cost", "approach and cost basis", "combined technical and financial proposal", ("project_title",),
                       context_fields=("submitted_by", "submitted_to", "project_title")),
    ),
)

# ---- Technical Proposal — modelled on Source Soft Solutions' own real
# proposals (New Index/*.pdf) rather than invented; see
# build_technical_proposal_template's docstring for exactly which real
# section names/order this matches and which client-specific middle
# sections were deliberately left out as inherently one-off per engagement.
TECHNICAL_PROPOSAL_FIELDS = [
    ("proposal_no", "What is the proposal number?", None),
    ("proposal_date", "What is the proposal date?", str(date.today())),
    ("client_name", "Who is this proposal for (client organisation)?", None),
    ("project_title", "What is the project title?", None),
    ("executive_summary_brief", "Briefly, summarise the overall proposal in a sentence or two. (this gets expanded)", None),
    ("understanding_brief", "Briefly, what is your understanding of the client's requirement? (this gets expanded)", None),
    ("objectives_brief", "Briefly, what outcomes will this engagement be measured against? (this gets expanded)", None),
    ("compliance_summary_brief", "Briefly, how does your proposed solution meet the requirement? (this gets expanded)", None),
    ("compliance_items",
     "List requirement-to-solution rows, one per line, as 'Requirement | Proposed solution' "
     "— or leave blank and this will be generated automatically from your problem statement above.", ""),
    ("information_architecture_brief", "Briefly describe the information architecture / sitemap approach. (this gets expanded)", None),
    ("sitemap_pillars",
     "List your site's top-level navigation pillars, one per line, as "
     "'Pillar Name | Sub-page one, Sub-page two, Sub-page three' — or leave blank and this "
     "will be generated automatically from your problem statement above.", ""),
    ("architecture_intro_brief", "Briefly introduce your solution's technical architecture in a sentence. (this gets expanded)", None),
    ("architecture_layers",
     "List your solution's architecture layers, one per line, as 'Layer Name: Description' "
     "(e.g. 'Frontend: React SPA served via CDN') — or leave blank and this will be "
     "generated automatically from your problem statement above.", ""),
    ("data_flow_intro_brief", "Briefly introduce your primary data/process flow in a sentence. (this gets expanded)", None),
    ("data_flow_steps",
     "List the key steps in your primary process flow, one per line, in order "
     "(e.g. 'User submits enquiry form') — or leave blank and this will be generated "
     "automatically from your problem statement above.", ""),
    ("modules_intro_brief", "Briefly introduce the public website's modules and features in a sentence. (this gets expanded)", None),
    ("modules_features",
     "List the public website's modules, one per line, as 'Module | What the user gets' — "
     "or leave blank and this will be generated automatically from your problem statement above.", ""),
    ("core_module_intro_brief", "Briefly introduce your solution's centrepiece module in a sentence. (this gets expanded)", None),
    ("core_module_flow",
     "List the user's journey through your solution's centrepiece module, one step per line "
     "— or leave blank and this will be generated automatically from your problem statement above.", ""),
    ("admin_portal_intro_brief", "Briefly introduce the admin CMS portal in a sentence. (this gets expanded)", None),
    ("admin_capabilities",
     "List the admin CMS portal's capability areas, one per line, as 'Feature | Description' "
     "— or leave blank and this will be generated automatically from your problem statement above.", ""),
    ("admin_roles",
     "List the admin CMS user roles, one per line, as 'Role | Can do' — or leave blank and "
     "this will be generated automatically from your problem statement above.", ""),
    ("enquiry_intro_brief", "Briefly introduce how enquiries/contact forms are handled in a sentence. (this gets expanded)", None),
    ("enquiry_channels",
     "List enquiry/contact form types, one per line, as 'Form | Captured | Routed to' — or "
     "leave blank and this will be generated automatically from your problem statement above.", ""),
    ("security_intro_brief", "Briefly introduce your security, hosting and compliance approach in a sentence. (this gets expanded)", None),
    ("security_flow",
     "List the security/hardening/certification pipeline before go-live, one step per line "
     "— or leave blank and this will be generated automatically from your problem statement above.", ""),
    ("security_areas",
     "List security/hosting/compliance areas, one per line, as 'Area | What we implement' — "
     "or leave blank and this will be generated automatically from your problem statement above.", ""),
    ("seo_intro_brief", "Briefly introduce your multilingual/SEO/performance approach in a sentence. (this gets expanded)", None),
    ("seo_performance_items",
     "List multilingual/SEO/performance items, one per line, as 'Item | Detail' — or leave "
     "blank and this will be generated automatically from your problem statement above.", ""),
    ("methodology_brief", "Briefly describe your implementation methodology and phases. (this gets expanded)", None),
    ("implementation_timeline",
     "List your implementation phases, one per line, as 'Phase Name | Week range | Description' "
     "(e.g. 'Phase 1 — Discovery & Design | Weeks 1-3 | Kick-off and requirement study') — or "
     "leave blank and this will be generated automatically from your problem statement above.", ""),
    ("amc_intro_brief", "Briefly introduce your annual maintenance & support offering in a sentence. (this gets expanded)", None),
    ("amc_scope",
     "List annual maintenance & support scope areas, one per line, as 'Scope area | What's "
     "covered' — or leave blank and this will be generated automatically from your problem "
     "statement above.", ""),
    ("deliverables_brief", "Briefly list key deliverables and any assumptions. (this gets expanded)", None),
    ("submitted_by", "Submitted by (your organisation)?", "Source Soft Solutions"),
    ("signatory_name", "Authorized signatory (name)?", None),
    ("signatory_designation", "Their designation?", None),
    ("about_company", "Company profile for the About the Company page? (leave blank to use Source Soft Solutions' real profile)", ""),
]
TECHNICAL_PROPOSAL_SPEC = TemplateSpec(
    key="technical_proposal", display_name="Technical Proposal",
    template_file="technical_proposal_template.docx", filename_prefix="technical_proposal",
    doc_number_field="proposal_no", fields=TECHNICAL_PROPOSAL_FIELDS,
    narrative_fields=(
        NarrativeField("executive_summary_brief", "executive_summary", "executive summary", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("understanding_brief", "understanding", "understanding of the requirement", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("objectives_brief", "objectives", "project objectives", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("compliance_summary_brief", "compliance_summary", "requirement-to-solution compliance", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("information_architecture_brief", "information_architecture", "information architecture", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("architecture_intro_brief", "architecture_intro", "technology architecture introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("data_flow_intro_brief", "data_flow_intro", "data flow introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("modules_intro_brief", "modules_intro", "public website modules and features introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("core_module_intro_brief", "core_module_intro", "centrepiece module introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("admin_portal_intro_brief", "admin_portal_intro", "admin CMS portal introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("enquiry_intro_brief", "enquiry_intro", "enquiry and notification handling introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("security_intro_brief", "security_intro", "security, hosting and compliance introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("seo_intro_brief", "seo_intro", "multilingual, SEO and performance introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("methodology_brief", "methodology", "implementation methodology", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("amc_intro_brief", "amc_intro", "annual maintenance and support introduction", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
        NarrativeField("deliverables_brief", "deliverables", "deliverables and assumptions", "technical proposal", ("project_title",),
                       context_fields=("submitted_by", "client_name", "project_title")),
    ),
)

WORK_ORDER_SPEC = TemplateSpec(
    key="work_order_services", display_name="Work Order — Services/Consultancy",
    template_file="work_order_template.docx", filename_prefix="work_order",
    doc_number_field="work_order_no", fields=WORK_ORDER_FIELDS,
    narrative_fields=(
        NarrativeField("scope_of_work_brief", "scope_of_work", "scope-of-work", "government work order", ("project_title",),
                       context_fields=("issuing_organisation", "contractor_name", "project_title")),
    ),
)
MOU_SPEC = TemplateSpec(
    key="mou_institutional", display_name="MoU — Institutional Collaboration",
    template_file="mou_template.docx", filename_prefix="mou",
    doc_number_field="mou_no", fields=MOU_FIELDS,
    narrative_fields=(
        NarrativeField("background_brief", "background", "background/context", "memorandum of understanding", ("mou_title",),
                       context_fields=("party_a_name", "party_b_name", "mou_title")),
        NarrativeField("objectives_brief", "objectives", "objectives", "memorandum of understanding", ("mou_title",),
                       context_fields=("party_a_name", "party_b_name", "mou_title")),
    ),
)

# Registry — every template the demo/CLI can offer, keyed for a UI selector.
# render_work_order/render_mou (the two hand-written functions above) predate
# this registry and are kept as-is since demo_app.py already calls them
# directly; every template built after them goes through render_document()
# + this registry instead.
ALL_TEMPLATE_SPECS = [
    TECHNICAL_PROPOSAL_SPEC,
    WORK_ORDER_SPEC, WORK_ORDER_GOODS_SPEC, WORK_ORDER_AMC_SPEC,
    MOU_SPEC, MOU_INTERNATIONAL_SPEC, MOU_INTERDEPT_SPEC,
    AGREEMENT_SERVICE_SPEC, AGREEMENT_CONSULTANCY_SPEC, AGREEMENT_LICENSING_SPEC,
    PROPOSAL_TECHNICAL_SPEC, PROPOSAL_FINANCIAL_SPEC, PROPOSAL_COMBINED_SPEC,
]
