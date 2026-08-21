"""Manual retrieval sanity-check — no LLM involved yet. Ask a question, see
which chunks come back and their scores. This is the "stop and verify
retrieval quality before writing generation code" step from the plan."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.store import search


def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/query.py "your question here" [top_k]')
        sys.exit(1)

    question = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    results = search(question, top_k=top_k)
    if not results:
        print("No results — has scripts/ingest.py been run yet?")
        return

    print(f'Query: "{question}"\n')
    for i, r in enumerate(results, 1):
        print(f"[{i}] score={r['score']:.3f}  {r['source']} ({r['unit_label']}, {r['extraction_method']})")
        preview = r["text"][:300].replace("\n", " ")
        print(f"    {preview}{'...' if len(r['text']) > 300 else ''}\n")


if __name__ == "__main__":
    main()
