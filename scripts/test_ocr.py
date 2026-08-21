"""Validates the OCR fallback path end-to-end — the one thing Phase 1 built
but never actually proved, since none of the 5 sample docs triggered it
(even the "scanned" 2001 circular turned out to have native text).

Manufactures a genuinely image-only PDF (no text layer at all — rendered
text baked into a raster image, then saved as PDF) with known ground-truth
content, runs it through the real parser, and checks two things:
1. The <40-char native-text threshold actually detects it as scan-like and
   routes to Tesseract instead of returning near-empty text.
2. Tesseract's output is close enough to the ground truth to sanity-check
   the RFP's "\u226590% character accuracy" requirement — not a rigorous
   benchmark (one page, one font), but real signal instead of guessing.
"""
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont

from ingestion.parser import parse_document

TEST_DIR = Path(__file__).resolve().parent.parent / "data" / "ocr_test"
TEST_PDF = TEST_DIR / "synthetic_scan_no_text_layer.pdf"

GROUND_TRUTH = (
    "Quality Council of India intends to onboard a technically qualified and "
    "experienced agency for the design, development, deployment, implementation, "
    "and support of an AI-powered Knowledge Hub and Workflow Automation Platform. "
    "The objective of this engagement is to establish a secure, scalable, and "
    "AI-enabled enterprise platform for intelligent knowledge management, "
    "information retrieval, and workflow automation across the organisation."
)


def build_synthetic_scan():
    """Renders GROUND_TRUTH as a rasterized page image, then saves it as a
    PDF via a straight image-to-PDF save — this embeds only a raster image
    in the PDF, no extractable text layer, i.e. a genuine scan, not a
    digital document that merely looks old."""
    width, height = 1654, 2339  # ~A4 at 200 DPI
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 34)

    # simple word-wrap to fit the page width
    words = GROUND_TRUTH.split()
    lines, current = [], []
    max_width = width - 200
    for word in words:
        trial = " ".join(current + [word])
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    y = 150
    for line in lines:
        draw.text((100, y), line, fill="black", font=font)
        y += 50

    TEST_DIR.mkdir(parents=True, exist_ok=True)
    img.save(TEST_PDF, "PDF", resolution=200.0)
    print(f"Built synthetic scan: {TEST_PDF}")


def char_accuracy(expected: str, actual: str) -> float:
    matcher = difflib.SequenceMatcher(None, expected.lower(), actual.lower())
    return matcher.ratio() * 100


def main():
    build_synthetic_scan()

    units = parse_document(TEST_PDF)
    assert len(units) == 1, f"Expected 1 page unit, got {len(units)}"
    unit = units[0]

    print(f"\nExtraction method used: {unit.extraction_method}")
    if unit.extraction_method != "ocr":
        print("FAIL — parser did not route this through OCR. The <40-char "
              "native-text threshold did not detect this as scan-like.")
        sys.exit(1)

    accuracy = char_accuracy(GROUND_TRUTH, unit.text)
    print(f"\n--- Ground truth ---\n{GROUND_TRUTH}")
    print(f"\n--- OCR output ---\n{unit.text}")
    print(f"\nCharacter-level similarity: {accuracy:.1f}%")
    print(f"RFP benchmark (>=90%): {'PASS' if accuracy >= 90 else 'FAIL'}")


if __name__ == "__main__":
    main()
