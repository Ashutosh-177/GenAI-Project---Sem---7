"""Non-interactive smoke test for MoU drafting — same pattern as
test_draft.py, verifying the generalized DraftSession/render machinery
actually works for a second document type, not just Work Order."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.drafting import DraftSession, MOU_FIELDS, MOU_SPEC, render_document

SAMPLE_ANSWERS = {
    "mou_no": "QCI/MOU/2026/007",
    "mou_date": "19 August 2026",
    "party_a_name": "Quality Council of India",
    "party_b_name": "National Skill Development Corporation",
    "party_b_address": "301, World Mark 1, Aerocity, New Delhi - 110037",
    "mou_title": "Collaboration on Quality Standards for Skill Certification Programs",
    "background_brief": "both organisations have a shared interest in improving quality benchmarks for vocational training and skill certification across India",
    "objectives_brief": "jointly develop quality assessment frameworks, conduct periodic audits of certified training centres, and share best practices",
    "duration": "3 years from the date of signing, renewable by mutual consent",
    "signatory_a_name": "Anjali Verma",
    "signatory_a_designation": "CEO, Quality Council of India",
    "signatory_b_name": "Rajesh Kumar",
    "signatory_b_designation": "Managing Director, NSDC",
}


def main():
    session = DraftSession(fields=MOU_FIELDS)
    for field, value in SAMPLE_ANSWERS.items():
        accepted, error = session.answer(field, value)
        assert accepted, f"Sample answer for {field!r} was rejected: {error}"

    assert session.is_complete(), "Sample answers don't cover the full MOU_FIELDS schema"
    print("[test_mou_draft] All fields collected, rendering (AI expanding background + objectives)...")

    path = render_document(session, MOU_SPEC)
    print(f"[test_mou_draft] Draft saved to: {path}")


if __name__ == "__main__":
    main()
