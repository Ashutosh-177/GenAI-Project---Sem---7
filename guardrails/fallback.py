"""The RFP scores "No information found" as a required, explicit,
logged-for-admin-review behavior — this is the cheap first line of defense:
if retrieval itself came back weak, don't even bother asking the LLM, since
a low-signal context is exactly what produces confident-sounding
hallucination."""
from config import RETRIEVAL_SCORE_THRESHOLD


def retrieval_is_too_weak(chunks: list[dict]) -> bool:
    if not chunks:
        return True
    top_score = chunks[0]["score"]
    return top_score < RETRIEVAL_SCORE_THRESHOLD


LLM_NO_INFO_TOKEN = "NO_INFO_FOUND"


def is_llm_no_info_response(raw_answer: str) -> bool:
    """The LLM is also instructed to self-report when the provided context
    doesn't actually answer the question — this catches the case where
    retrieval scored decently but the chunks are still off-topic.

    Deliberately checks for the token ANYWHERE in the response, not just at
    the start: testing against llama3.2:3b showed it will sometimes hedge
    with a *partial* answer that embeds NO_INFO_FOUND mid-response instead of
    replying with only that token (e.g. answering a multi-part question where
    it can't support one part — and then fabricating a citation for that part
    anyway). Any presence of the token means the model itself flagged
    something as unsupported, so the safer move is to discard the whole
    answer rather than trust the parts around the token."""
    return LLM_NO_INFO_TOKEN in raw_answer
