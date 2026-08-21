"""Non-interactive smoke test for the drafting engine — feeds a complete set
of sample answers straight through instead of prompting, so the pipeline
(clarifying-question completeness check -> AI expansion -> versioned .docx
render) can be verified without a live terminal session."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.drafting import DraftSession

SAMPLE_ANSWERS = {
    "work_order_no": "QCI/WO/2026/014",
    "work_order_date": "17 August 2026",
    "issuing_organisation": "Quality Council of India",
    "contractor_name": "Bharat Digital Systems Pvt. Ltd.",
    "contractor_address": "Plot 12, Sector 62, Noida, UP - 201301",
    "project_title": "Annual Server Maintenance and Support",
    "scope_of_work_brief": "routine maintenance, patching, and 24x7 monitoring of QCI's server infrastructure",
    "contract_value": "Rs. 18,50,000 (Rupees Eighteen Lakh Fifty Thousand only)",
    "start_date": "1 September 2026",
    "completion_period": "12 months from start date",
    "payment_terms": "Quarterly in advance, within 15 days of invoice",
    "authorized_signatory_name": "R. Sharma",
    "authorized_signatory_designation": "Director, IT & Digital Initiatives",
}


def main():
    session = DraftSession()
    for field, value in SAMPLE_ANSWERS.items():
        accepted, error = session.answer(field, value)
        assert accepted, f"Sample answer for {field!r} was rejected: {error}"

    assert session.is_complete(), "Sample answers don't cover the full field schema"
    print("[test_draft] All fields collected, rendering (AI expanding scope + T&C)...")

    from generation.drafting import render_document, WORK_ORDER_SPEC
    path = render_document(session, WORK_ORDER_SPEC)
    print(f"[test_draft] Draft saved to: {path}")

    # render again to prove auto-versioning increments correctly
    path2 = render_document(session, WORK_ORDER_SPEC)
    print(f"[test_draft] Second draft (should be v2): {path2}")


if __name__ == "__main__":
    main()
