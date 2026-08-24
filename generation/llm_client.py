"""Shared Anthropic API client for every LLM-reasoning call in this
project — document drafting (drafting.py), conversational Q&A (rag.py),
summarization (summarize.py), and document classification
(ingestion/classifier.py). Centralized here so the client setup and the
response-parsing fix below live in exactly one place instead of four
separately-duplicated copies.

This does NOT cover the local/self-hosted pieces of the stack — those are
untouched: embeddings (multilingual-e5-large), vector search (Qdrant), and
voice transcription (faster-whisper) all stay local. Only the
reasoning/generation calls that used to go through local Ollama now go
through Claude — see Memory.md for the full history of this decision and
its RFP-compliance tradeoff (draft/query content now leaves the machine)."""
import random
import time

import anthropic

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

# Status codes worth retrying — transient server-side conditions, not a
# problem with the request itself. 529 specifically: a real user hit this
# mid-draft (a 25-30-call Technical Proposal render, each call retryable
# individually) and the whole Streamlit app crashed to a raw traceback on
# the very last narrative field — losing nothing already typed (answers
# live in session_state), but wasting every prior LLM call in that render.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
_MAX_ATTEMPTS = 5
_BASE_DELAY_S = 2.0

# Server-side fallback: on a policy refusal the API silently re-runs the same
# request on a fallback model within the same call, instead of returning
# nothing. Worth having here specifically because this pipeline feeds the
# model OCR output — a badly-scanned page produces scrambled character soup,
# and a real case in this corpus (agreement_dgshipping_contract_mgmt.pdf,
# last batch) had a safety classifier false-positive on that gibberish with
# category "bio". "default" routes by refusal category automatically rather
# than us maintaining a model list.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMRefusalError(RuntimeError):
    """The model (and any fallback) declined to answer. Distinct from a
    transport/API failure — the request succeeded (HTTP 200), the model
    just refused, so callers can skip this one input and carry on rather
    than treating it as a broken pipeline."""


_client = None

# Not every model accepts `fallbacks` (claude-sonnet-5 rejects it with a 400,
# confirmed). ANTHROPIC_MODEL is .env-configurable, so rather than hardcode an
# assumption about which model is in use, try once with fallbacks and remember
# if this model doesn't take them.
_fallbacks_supported = True


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _response_text(response) -> str:
    """Check stop_reason BEFORE reading content — a refusal returns HTTP 200
    with an EMPTY content list, so parsing content first raises a confusing
    "no text block" error that hides the real cause (this bug hit a real
    summarization run). Also: content[0] is not reliably the text block —
    caught live, the model returned a ThinkingBlock first and content[0].text
    raised AttributeError — so find the text block by type, not position."""
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        raise LLMRefusalError(f"Model declined this input (category: {category})")

    for block in response.content:
        if block.type == "text":
            return block.text

    # max_tokens with no text can happen if thinking consumes the whole budget.
    raise ValueError(
        f"No text block in Anthropic response (stop_reason={response.stop_reason!r}, "
        f"content={response.content!r})"
    )


def _call_with_retry(fn):
    """Retries `fn()` on transient errors (overload, rate limit, connection
    issues) with exponential backoff + jitter, up to _MAX_ATTEMPTS. Anything
    else (bad request, refusal, auth) is not retryable and raises straight
    through on the first attempt — retrying those would just waste time
    reproducing the same permanent failure."""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return fn()
        except anthropic.APIStatusError as e:
            if e.status_code not in _RETRYABLE_STATUS_CODES or attempt == _MAX_ATTEMPTS - 1:
                raise
        except anthropic.APIConnectionError:
            if attempt == _MAX_ATTEMPTS - 1:
                raise
        delay = _BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
        time.sleep(delay)
    raise AssertionError("unreachable")  # loop always returns or raises


def chat(prompt: str, max_tokens: int = 16000, system: str | None = None) -> str:
    """One user-turn call to Claude, returning just the text. Every call
    site that used to do `ollama.Client(host=...).chat(model=..., messages=
    [...])` and then pull `response["message"]["content"]` now does
    `chat(prompt)` instead. `system` is Anthropic's dedicated system-prompt
    parameter, not folded into the user message — rag.py's guardrail rules
    (citation format, the exact no-info token) need to carry the extra
    instruction-following weight a real system prompt gets, not just be
    prepended text.

    max_tokens defaults to 16000, not the 1024 this started with: a low cap
    truncates output mid-sentence, and with thinking enabled it can consume
    the entire budget and leave no text at all. Raises LLMRefusalError if
    the model declines — callers processing a batch of inputs should catch
    it and skip that one rather than failing the whole job."""
    global _fallbacks_supported
    client = _get_client()
    kwargs = dict(model=ANTHROPIC_MODEL, max_tokens=max_tokens,
                  messages=[{"role": "user", "content": prompt}])
    if system:
        kwargs["system"] = system

    if _fallbacks_supported:
        try:
            response = _call_with_retry(lambda: client.beta.messages.create(
                betas=[_FALLBACK_BETA], fallbacks="default", **kwargs))
            return _response_text(response)
        except anthropic.BadRequestError as e:
            if "fallbacks" not in str(e):
                raise
            _fallbacks_supported = False  # this model doesn't take them; stop trying

    return _response_text(_call_with_retry(lambda: client.messages.create(**kwargs)))
