"""Validates the voice-input pipeline end-to-end, same discipline as
scripts/test_ocr.py: synthesize known ground-truth speech (Windows SAPI,
since no microphone is available in this environment), transcribe it with
faster-whisper, and measure real character-level accuracy instead of just
checking the pipeline "ran".

Honest scope limit: only an en-US TTS voice is installed on this machine, so
this validates the ENGLISH path rigorously. Hindi/Hinglish are built for
(Whisper supports both) but not locally verified the same way — flagged in
Memory.md rather than silently assumed to work."""
import difflib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.voice import transcribe_audio

TEST_DIR = Path(__file__).resolve().parent.parent / "data" / "voice_test"
TEST_WAV = TEST_DIR / "synthetic_query_en.wav"

GROUND_TRUTH = "What is the purpose of the National Emergency Response System MoU?"

SAPI_SCRIPT = f'''
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Zira Desktop")
$synth.SetOutputToWaveFile("{TEST_WAV}")
$synth.Speak("{GROUND_TRUTH}")
$synth.Dispose()
'''


def build_synthetic_audio():
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-Command", SAPI_SCRIPT], check=True)
    print(f"Built synthetic audio: {TEST_WAV} ({TEST_WAV.stat().st_size} bytes)")


def main():
    build_synthetic_audio()

    result = transcribe_audio(TEST_WAV)
    print(f"\nDetected language: {result['language']} (confidence {result['language_probability']:.2f})")
    print(f"Ground truth: {GROUND_TRUTH!r}")
    print(f"Transcribed:  {result['text']!r}")

    accuracy = difflib.SequenceMatcher(None, GROUND_TRUTH.lower(), result["text"].lower()).ratio() * 100
    print(f"\nCharacter-level similarity: {accuracy:.1f}%")
    print(f"Language correctly detected as English: {result['language'] == 'en'}")


if __name__ == "__main__":
    main()
