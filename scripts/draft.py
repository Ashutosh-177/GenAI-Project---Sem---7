"""Interactive CLI for the Phase 3 drafting engine — the clarifying-questions
flow in action. Run: python scripts/draft.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.drafting import DraftSession, WORK_ORDER_SPEC, render_document


def main():
    print("QCI Knowledge Hub — Work Order drafting (Phase 3 PoC)\n")
    session = DraftSession(fields=WORK_ORDER_SPEC.fields)

    while not session.is_complete():
        field_name, question = session.next_question()
        default = next((d for n, q, d in WORK_ORDER_SPEC.fields if n == field_name), None)
        prompt = f"{question}" + (f" [{default}]" if default else "") + " "
        answer = input(prompt)
        accepted, error = session.answer(field_name, answer)
        if not accepted:
            print(f"  ! {error}")

    print("\nAll fields collected. Generating draft (AI is expanding scope of work and terms & conditions)...")
    path = render_document(session, WORK_ORDER_SPEC)
    print(f"\nDraft saved to: {path}")


if __name__ == "__main__":
    main()
