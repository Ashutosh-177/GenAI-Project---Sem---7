"""Same discipline as scripts/test_voice.py, extended to Hindi — the gap
explicitly flagged in Memory.md as "genuinely open, not verified." That
test could only validate English because the only TTS voices installed on
this machine are English (confirmed: Windows SAPI has no Hindi voice, and
neither does the OneCore WinRT voice list). Meta's MMS-TTS (open-weight,
non-Chinese-origin, runs fully local via transformers — same "no external
API call after model download" boundary as Whisper/Ollama elsewhere in
this project) fills that gap: synthesize a known-ground-truth Hindi
sentence, transcribe it with faster-whisper, and measure real accuracy
instead of assuming Hindi works because English did.

Two ground-truth sentences: one pure Hindi (isolates whether Hindi ASR
works at all), one Hinglish code-switched (approximates the real failure
a user hit: "Mereko National Emergency Response System ke baare me
batao" transcribed as unrelated English text at 0.45 language confidence)."""
import difflib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp1252, can't print Devanagari
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scipy.io.wavfile
import torch
from transformers import VitsModel, AutoTokenizer

from generation.voice import transcribe_audio

TEST_DIR = Path(__file__).resolve().parent.parent / "data" / "voice_test"

CASES = [
    ("synthetic_query_hi_pure.wav",
     "राष्ट्रीय आपातकालीन प्रतिक्रिया प्रणाली के बारे में जानकारी दीजिए"),
    ("synthetic_query_hi_hinglish.wav",
     "मेरे को नेशनल इमरजेंसी रिस्पांस सिस्टम के बारे में बताओ"),
]

_model = None
_tokenizer = None


def _get_tts():
    global _model, _tokenizer
    if _model is None:
        print("Loading facebook/mms-tts-hin (first run downloads the model)...")
        _model = VitsModel.from_pretrained("facebook/mms-tts-hin")
        _tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-hin")
    return _model, _tokenizer


def synthesize(text: str, out_path: Path):
    model, tokenizer = _get_tts()
    inputs = tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        output = model(**inputs).waveform
    waveform = output.squeeze().numpy()
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    scipy.io.wavfile.write(out_path, rate=model.config.sampling_rate, data=waveform)


def main():
    for filename, ground_truth in CASES:
        wav_path = TEST_DIR / filename
        synthesize(ground_truth, wav_path)
        print(f"\nBuilt synthetic audio: {wav_path} ({wav_path.stat().st_size} bytes)")

        result = transcribe_audio(wav_path, language="hi")
        print(f"Ground truth: {ground_truth!r}")
        print(f"Transcribed:  {result['text']!r}")

        accuracy = difflib.SequenceMatcher(None, ground_truth, result["text"]).ratio() * 100
        print(f"Character-level similarity: {accuracy:.1f}%")
        print(f"Language reported: {result['language']} (confidence {result['language_probability']:.2f})")


if __name__ == "__main__":
    main()
