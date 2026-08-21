"""Does a Hindi-specialized model actually fix the inconsistency we found in
llama3.2:3b, or was that a fluke worth re-testing? Runs the SAME Hindi query
3 times against each model, using the exact same retrieval context and
system prompt our real RAG pipeline uses (generation/rag.py) — not a
simplified toy prompt — so this is a fair comparison, not a favorable one."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ollama

from config import OLLAMA_HOST
from retrieval.store import search
from generation.rag import SYSTEM_PROMPT, _build_context_block

QUESTION = "ZED प्रमाणन योजना क्या है?"  # "What is the ZED certification scheme?"
MODELS = ["llama3.2:3b", "hf.co/sam749/Airavata-GGUF:Q4_K_M"]
RUNS_PER_MODEL = 3


def main():
    chunks = search(QUESTION, top_k=5)
    context_block = _build_context_block(chunks)
    prompt = f"Source excerpts:\n\n{context_block}\n\nQuestion: {QUESTION}\n\nAnswer (with citations):"

    client = ollama.Client(host=OLLAMA_HOST)

    for model in MODELS:
        print(f"\n{'=' * 70}\nMODEL: {model}\n{'=' * 70}")
        for i in range(1, RUNS_PER_MODEL + 1):
            response = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            answer = response["message"]["content"].strip()
            print(f"\n--- Run {i} ---\n{answer}")


if __name__ == "__main__":
    main()
