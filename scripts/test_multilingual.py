"""First-ever test of Hindi/Hinglish query handling — RFP explicitly requires
it ("Voice languages supported (input): English, Hindi, Hinglish") and it has
never been exercised once in this build. Surfaces real gaps rather than
assuming the pipeline just handles it because Llama is "multilingual"."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.rag import ask

QUERIES = [
    ("Hindi", "ZED प्रमाणन योजना क्या है?"),  # "What is the ZED certification scheme?"
    ("Hinglish", "MoU ka scope kya hai?"),  # "What is the MoU's scope?"
    ("Hinglish", "Work order mein contractor ka naam kaun sa hai?"),
]

for lang, q in QUERIES:
    print(f"\n{'=' * 70}\n[{lang}] {q}\n{'=' * 70}")
    result = ask(q)
    print(f"Fallback: {result.is_fallback}")
    print(f"Answer: {result.answer}")
    if not result.is_fallback:
        print(f"Citations: {len(result.citations)}")
        print(f"Guardrail issues: {result.guardrail_issues}")
        print(f"Top retrieval score: {result.retrieved_chunks[0]['score']:.3f}" if result.retrieved_chunks else "N/A")
