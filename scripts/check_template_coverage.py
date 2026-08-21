"""Systematic check for the bug class just found in Work Order: a {{
placeholder }} in a .docx template that nothing in the corresponding spec
actually populates, silently rendering blank. Extracts every {{ }} tag from
each template file and compares against what render_document() would
actually set (session fields + narrative output_fields + "version"),
flagging any gap — across all 12 specs, not just the one we found by hand."""
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.drafting import ALL_TEMPLATE_SPECS, TEMPLATES_DIR

# render_document() has one runtime special case (Work Order — Services'
# terms_and_conditions, drafted directly from context rather than a spec
# NarrativeField — see its own comment in drafting.py for why). This static
# checker only reads spec.fields/narrative_fields, so it can't see that
# branch — hardcoded here so a real fix doesn't show up as a false gap.
KNOWN_RUNTIME_SPECIAL_CASES = {"work_order_services": {"terms_and_conditions"}}

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def extract_placeholders(docx_path: Path) -> set[str]:
    """docx is a zip; the text (including Jinja tags, sometimes split across
    multiple XML runs) lives in word/document.xml — plus word/footerN.xml
    and word/headerN.xml now that both are real Word header/footer parts
    (doc.sections[0].header/.footer) rather than body paragraphs. Missing
    either here previously caused a false-negative: {{ version }} moved
    into the footer and silently dropped out of this checker's view
    without raising a gap; the running header added later carries its own
    {{ ref }} placeholders too. Runs can split a single {{ tag }} across
    runs, so this also tries a de-XML'd flatten as a fallback."""
    with zipfile.ZipFile(docx_path) as z:
        parts = [n for n in z.namelist()
                 if n == "word/document.xml" or re.match(r"word/(header|footer)\d+\.xml", n)]
        xml = "".join(z.read(n).decode("utf-8") for n in parts)
    # Strip XML tags to reassemble text that may have been split across runs
    flattened = re.sub(r"<[^>]+>", "", xml)
    return set(PLACEHOLDER_PATTERN.findall(flattened))


def main():
    any_gap = False
    for spec in ALL_TEMPLATE_SPECS:
        template_path = TEMPLATES_DIR / spec.template_file
        placeholders = extract_placeholders(template_path)

        provided = {name for name, _q, _d in spec.fields}
        provided -= {nf.brief_field for nf in spec.narrative_fields}  # briefs get popped
        provided |= {nf.output_field for nf in spec.narrative_fields}
        provided |= {"version"}
        provided |= KNOWN_RUNTIME_SPECIAL_CASES.get(spec.key, set())

        missing = placeholders - provided
        extra_unused = provided - placeholders  # informational only, not a bug

        status = "OK" if not missing else "GAP"
        print(f"[{status}] {spec.key}: {len(placeholders)} placeholder(s) in template")
        if missing:
            any_gap = True
            print(f"   MISSING (in template, nothing populates them): {sorted(missing)}")

    print()
    print("Some templates render blank sections right now." if any_gap
          else "All 12 templates: every placeholder is covered.")


if __name__ == "__main__":
    main()
