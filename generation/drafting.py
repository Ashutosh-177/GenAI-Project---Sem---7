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
from retrieval.store import search

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated"

# (field name, question asked to the user, default value or None)
WORK_ORDER_FIELDS = [
    ("work_order_no", "What is the work order number?", None),
    ("work_order_date", "What is the issue date?", str(date.today())),
    ("issuing_organisation", "Issuing organisation?", "Quality Council of India"),
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
    ("party_a_name", "First party (usually QCI)?", "Quality Council of India"),
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


def render_document(session: DraftSession, spec: TemplateSpec) -> Path:
    """The one render function every template uses. Replaces per-template
    render_work_order/render_mou-style duplication — those two now exist
    only as thin backward-compatible wrappers around this."""
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

    doc_no = session.answers[spec.doc_number_field]
    version = _next_version(spec.filename_prefix, doc_no)
    context["version"] = f"v{version}"
    context = _escape_context(context)

    tpl = DocxTemplate(TEMPLATES_DIR / spec.template_file)
    tpl.render(context)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", doc_no)
    out_path = OUTPUT_DIR / f"{spec.filename_prefix}_{safe}_v{version}.docx"
    tpl.save(out_path)
    return out_path


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
    ("issuing_organisation", "Issuing organisation?", "Quality Council of India"),
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
    ("issuing_organisation", "Issuing organisation?", "Quality Council of India"),
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
    ("indian_party_name", "Indian party?", "Quality Council of India"),
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
    ("department_a_name", "First department/body?", "Quality Council of India"),
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
    ("client_name", "Client?", "Quality Council of India"),
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
    ("client_name", "Client?", "Quality Council of India"),
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
    ("licensor_name", "Licensor?", "Quality Council of India"),
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
    ("submitted_to", "Submitted to?", "Quality Council of India"),
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
    ("submitted_to", "Submitted to?", "Quality Council of India"),
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
    ("submitted_to", "Submitted to?", "Quality Council of India"),
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
    WORK_ORDER_SPEC, WORK_ORDER_GOODS_SPEC, WORK_ORDER_AMC_SPEC,
    MOU_SPEC, MOU_INTERNATIONAL_SPEC, MOU_INTERDEPT_SPEC,
    AGREEMENT_SERVICE_SPEC, AGREEMENT_CONSULTANCY_SPEC, AGREEMENT_LICENSING_SPEC,
    PROPOSAL_TECHNICAL_SPEC, PROPOSAL_FINANCIAL_SPEC, PROPOSAL_COMBINED_SPEC,
]
