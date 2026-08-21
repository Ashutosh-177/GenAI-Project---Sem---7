import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrieval.store import search

queries = [
    ("relevant", "What are the terms of the MoU?"),
    ("relevant", "What is the ZED certification scheme?"),
    ("relevant", "Who are the parties to the work order?"),
    ("irrelevant", "What is the best programming language for game development?"),
    ("irrelevant", "How do I bake a chocolate cake?"),
    ("irrelevant", "What is the population of Japan?"),
    ("irrelevant", "What is the capital of France?"),
]
for label, q in queries:
    r = search(q, top_k=1)
    score = r[0]["score"] if r else None
    print(f"{label:12s} top_score={score:.3f}  q={q!r}")
