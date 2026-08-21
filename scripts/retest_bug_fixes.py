"""Targeted retest of the 3 specific bugs found by visual QA + the coverage
checker: Work Order's blank T&C, MoU-Interdept's wrong party names, and
Proposal-Combined's "empanelment" leak. Only re-renders these 3, not all 12,
to keep the retest fast."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.drafting import (
    DraftSession, render_document,
    WORK_ORDER_SPEC, MOU_INTERDEPT_SPEC, PROPOSAL_COMBINED_SPEC,
)
from scripts.test_all_templates import SAMPLE_VALUES


def build_and_render(spec):
    session = DraftSession(fields=spec.fields)
    for name, _q, _d in spec.fields:
        session.answer(name, SAMPLE_VALUES[name])
    return render_document(session, spec)


for spec in [WORK_ORDER_SPEC, MOU_INTERDEPT_SPEC, PROPOSAL_COMBINED_SPEC]:
    print(f"\n--- {spec.key} ---")
    path = build_and_render(spec)
    print(f"Rendered: {path}")

    from docx import Document
    doc = Document(path)
    for p in doc.paragraphs:
        if p.text.strip():
            print(f"  {p.text[:220]}")
