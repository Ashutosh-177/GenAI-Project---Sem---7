"""Core RAG loop: retrieve -> build a numbered, citable context -> generate
-> validate the model actually cited its sources -> log everything. This is
the piece the RFP scores directly (citation-backed, source-grounded Q&A),
so every guardrail here maps to a specific scored requirement, not a nice-
to-have."""
from dataclasses import dataclass, field

from config import RETRIEVAL_TOP_K, NO_INFO_MESSAGE
from generation.llm_client import chat as _llm_chat
from retrieval.store import search
from guardrails.fallback import retrieval_is_too_weak, is_llm_no_info_response, LLM_NO_INFO_TOKEN
from guardrails.citation import validate_citations, extract_citation_indices
from guardrails.audit_log import log_interaction

SYSTEM_PROMPT = f"""You are an assistant answering questions using ONLY the numbered \
source excerpts provided below. Do not use any outside knowledge, even if you know the answer.

Rules:
1. Every factual claim in your answer must end with a citation like [1] or [2] \
referring to the excerpt number it came from.
2. If the excerpts do not contain enough information to answer the question \
- including if they only answer PART of a multi-part question - respond with \
ONLY this exact text and nothing else: {LLM_NO_INFO_TOKEN}
3. Do not partially answer and then note what's missing. Either the excerpts \
fully support an answer, or you output only {LLM_NO_INFO_TOKEN}.
4. Never invent a citation number that isn't listed in the excerpts below.
5. Be concise and answer only what was asked."""


@dataclass
class RagAnswer:
    question: str
    answer: str
    is_fallback: bool
    citations: list[dict] = field(default_factory=list)
    guardrail_issues: list[str] = field(default_factory=list)
    retrieved_chunks: list[dict] = field(default_factory=list)


def _build_context_block(chunks: list[dict]) -> str:
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(f"[{i}] ({c['source']}, {c['unit_label']}):\n{c['text']}")
    return "\n\n".join(lines)


def ask(question: str, top_k: int = RETRIEVAL_TOP_K) -> RagAnswer:
    chunks = search(question, top_k=top_k)

    # Guardrail 1: retrieval itself too weak -> don't even call the LLM.
    if retrieval_is_too_weak(chunks):
        result = RagAnswer(question, NO_INFO_MESSAGE, is_fallback=True, retrieved_chunks=chunks)
        log_interaction({
            "question": question, "answer": NO_INFO_MESSAGE, "is_fallback": True,
            "fallback_reason": "retrieval_below_threshold",
            "top_score": chunks[0]["score"] if chunks else None,
            "retrieved_chunks": [c["chunk_id"] for c in chunks],
        })
        return result

    context_block = _build_context_block(chunks)
    prompt = f"Source excerpts:\n\n{context_block}\n\nQuestion: {question}\n\nAnswer (with citations):"

    raw_answer = _llm_chat(prompt, system=SYSTEM_PROMPT).strip()

    # Guardrail 2: the LLM itself says the context doesn't answer the question.
    if is_llm_no_info_response(raw_answer):
        result = RagAnswer(question, NO_INFO_MESSAGE, is_fallback=True, retrieved_chunks=chunks)
        log_interaction({
            "question": question, "answer": NO_INFO_MESSAGE, "is_fallback": True,
            "fallback_reason": "llm_reported_no_info", "raw_llm_output": raw_answer,
            "retrieved_chunks": [c["chunk_id"] for c in chunks],
            "top_score": chunks[0]["score"] if chunks else None,
        })
        return result

    # Guardrail 3: citation validation — didn't cite, or cited something that
    # doesn't exist. Answer still goes back to the user (refusing outright on
    # a formatting slip is worse UX than the citation gap itself), but it's
    # flagged and logged for admin review per the RFP's guardrail spec.
    passed, issues = validate_citations(raw_answer, num_chunks=len(chunks))
    cited_indices = extract_citation_indices(raw_answer)
    citations = [
        {"index": i, "source": chunks[i - 1]["source"], "unit_label": chunks[i - 1]["unit_label"],
         "document_type": chunks[i - 1].get("document_type", "Other"),
         "category": chunks[i - 1].get("category", "General/Unclassified")}
        for i in sorted(cited_indices) if 1 <= i <= len(chunks)
    ]

    result = RagAnswer(
        question=question, answer=raw_answer, is_fallback=False,
        citations=citations, guardrail_issues=issues, retrieved_chunks=chunks,
    )
    log_interaction({
        "question": question, "answer": raw_answer, "is_fallback": False,
        "citations": citations, "guardrail_passed": passed, "guardrail_issues": issues,
        "retrieved_chunks": [c["chunk_id"] for c in chunks],
        "top_score": chunks[0]["score"],
    })
    return result
