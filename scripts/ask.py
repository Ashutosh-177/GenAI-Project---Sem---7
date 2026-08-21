"""End-to-end RAG Q&A test — retrieval + generation + guardrails, exactly
what Pillar 3's "conversational search" scope item is. Compare against
scripts/query.py's raw retrieval output to see what the LLM/guardrail layer
adds (or, if something looks wrong, which layer it broke in)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.rag import ask


def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/ask.py "your question here"')
        sys.exit(1)

    question = sys.argv[1]
    result = ask(question)

    print(f'Q: {question}\n')
    print(f"A: {result.answer}\n")

    if result.is_fallback:
        print("[fallback triggered — no LLM call needed / LLM self-reported no info]")
        return

    print(f"Citations: {len(result.citations)}")
    for c in result.citations:
        print(f"  [{c['index']}] {c['source']} ({c['unit_label']})")

    if result.guardrail_issues:
        print(f"\n⚠ Guardrail issues (logged for admin review):")
        for issue in result.guardrail_issues:
            print(f"  - {issue}")


if __name__ == "__main__":
    main()
