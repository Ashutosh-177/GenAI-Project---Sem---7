"""One-off diagnostic for the real user recording that transcribed as
garbage: 'बबीः की ले_ases आठा थन की आठाई बारतेे हैने' instead of
'मेरे को नेशनल इमरजेंसी रिस्पांस सिस्टम के बारे में बताओ'. Isolates which
factor is actually responsible by varying one thing at a time against the
exact same real audio file: the DOMAIN_PROMPT initial_prompt (biased
toward QCI/MoU/NABL vocabulary, irrelevant to this sentence and possibly
actively pulling decoding in the wrong direction), the forced language
hint, and the model tier."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faster_whisper import WhisperModel

AUDIO = "data/voice_test/user_recordings/6e46a8c0-079b-4393-9495-1bc60e583540.wav"
GROUND_TRUTH = "मेरे को नेशनल इमरजेंसी रिस्पांस सिस्टम के बारे में बताओ"
DOMAIN_PROMPT = ("This is a query about Indian government documents: MoU, Work Order, "
                  "Agreement, Proposal, Quality Council of India, QCI, NABL, NABH, NABET, "
                  "NABCB, tender, accreditation, certification.")

print(f"Ground truth: {GROUND_TRUTH!r}\n")


def run(label, model_size, language, initial_prompt):
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(AUDIO, beam_size=5, initial_prompt=initial_prompt, language=language)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    print(f"[{label}]")
    print(f"  language={info.language} (p={info.language_probability:.2f})")
    print(f"  text={text!r}\n")


run("current config (small, hi hint, DOMAIN_PROMPT)", "small", "hi", DOMAIN_PROMPT)
run("small, hi hint, NO prompt", "small", "hi", None)
run("small, auto-detect, NO prompt", "small", None, None)
run("medium, hi hint, NO prompt", "medium", "hi", None)
