"""Speech-to-text — RFP asks for voice queries in English/Hindi/Hinglish,
transcribed before processing. Whisper (OpenAI, open-weight, MIT license)
via faster-whisper: runs fully local, same "no external API call" boundary
as everything else in this project, and — same reasoning as the LLM/OCR/
vector-DB choices — explicitly non-Chinese-origin.

Hindi/Hinglish was built, tested against a real user recording, and
dropped: "Mereko National Emergency Response System ke baare me batao"
transcribed as unrelated nonsense regardless of model tier (small/medium),
forced language hint, or DOMAIN_PROMPT — see scripts/debug_real_hindi.py
and Memory.md for the full comparison. English alone is what's offered
now, validated at 97% accuracy against a real synthesized test
(scripts/test_voice.py) rather than assumed to work.

Once transcribed, voice input joins the EXACT SAME text pipeline as typed
input (generation/rag.py's ask()) — this module's only job is turning audio
into a string, not a separate query path."""
from pathlib import Path

from faster_whisper import WhisperModel

from config import WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    return _model


# Real user test caught this: "MoU" was transcribed as "RMEU" with only 0.45
# language-detection confidence. Whisper's initial_prompt biases decoding
# toward vocabulary that's likely to appear — this document domain's
# acronyms otherwise look like noise to a general-purpose "base" model that's
# never specifically seen "MoU"/"NABL"/etc. as a real word.
DOMAIN_PROMPT = ("This is a query about Indian government documents: MoU, Work Order, "
                  "Agreement, Proposal, Quality Council of India, QCI, NABL, NABH, NABET, "
                  "NABCB, tender, accreditation, certification.")


def transcribe_audio(audio_path: str | Path, language: str | None = None) -> dict:
    """Returns {text, language, language_probability}. `language` is an
    optional hint (the demo always passes "en" now — see this module's
    docstring for why Hindi was dropped); left as None to auto-detect when
    the caller doesn't know the speaker's language ahead of time."""
    model = _get_model()
    segments, info = model.transcribe(str(audio_path), beam_size=5, initial_prompt=DOMAIN_PROMPT,
                                       language=language)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": info.language_probability,
    }
