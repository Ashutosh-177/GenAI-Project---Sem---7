"""A real user found voice input "very slow" and saw "MoU" transcribed as
"RMEU" with only 0.45 language confidence. This measures: (1) how much of
the slowness is one-time model load vs. actual per-call transcription time
(the demo had JUST been restarted before that test, so the first call paid
a cold-start cost this script separates out), and (2) whether the
initial_prompt domain-vocabulary fix actually helps the acronym problem,
using the same synthetic ground-truth audio as before for a controlled
comparison."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faster_whisper import WhisperModel
from generation.voice import DOMAIN_PROMPT

TEST_WAV = Path(__file__).resolve().parent.parent / "data" / "voice_test" / "synthetic_query_en.wav"
GROUND_TRUTH = "What is the purpose of the National Emergency Response System MoU?"


def test_model_size(size: str):
    print(f"\n{'=' * 60}\nMODEL SIZE: {size}\n{'=' * 60}")
    t0 = time.time()
    model = WhisperModel(size, device="cpu", compute_type="int8")
    print(f"Load time: {time.time() - t0:.2f}s")

    for i in range(1, 3):
        t0 = time.time()
        segments, info = model.transcribe(str(TEST_WAV), beam_size=5, initial_prompt=DOMAIN_PROMPT)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.time() - t0
        correct = "mou" in text.lower()
        print(f"Run {i}: {elapsed:.2f}s | 'MoU' correct: {correct} | Text: {text!r}")


if __name__ == "__main__":
    for size in ["small", "medium"]:
        test_model_size(size)
    print(f"\nGround truth: {GROUND_TRUTH!r}")
