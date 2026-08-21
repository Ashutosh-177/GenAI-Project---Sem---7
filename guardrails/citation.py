"""Post-hoc citation validation. The prompt asks the LLM to cite [n] after
every factual claim, but instruction-following isn't guaranteed — especially
from a 3B model — so this checks the output actually did it rather than
trusting it did. Feeds the "100% of factual claims must carry a citation"
requirement: we can't enforce the LLM's internals, but we CAN refuse to
silently pass through an answer that skipped citations entirely, and we CAN
catch a fabricated citation number that doesn't correspond to any retrieved
chunk."""
import re

# Matches both [1] and [1, 2, 3] — the model (observed in both English and
# Hindi output) sometimes clusters multiple citations in one bracket instead
# of writing [1][2] separately. The original pattern only matched a single
# bare digit, so "[1, 2]" silently counted as zero citations and triggered a
# false "no citations found" guardrail flag despite the model citing correctly.
CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def extract_citation_indices(answer_text: str) -> set[int]:
    indices = set()
    for group in CITATION_PATTERN.findall(answer_text):
        indices.update(int(n) for n in group.split(","))
    return indices


def validate_citations(answer_text: str, num_chunks: int) -> tuple[bool, list[str]]:
    """Returns (passed, issues). `passed=False` doesn't mean discard the
    answer — it means log it for admin review, per the RFP's guardrail
    behavior spec, while still surfacing the answer to the user."""
    issues = []
    cited = extract_citation_indices(answer_text)

    if not cited:
        issues.append("No citations found in a non-fallback answer.")

    out_of_range = {i for i in cited if i < 1 or i > num_chunks}
    if out_of_range:
        issues.append(f"Answer cites source index/indices not in the retrieved set: {sorted(out_of_range)}")

    return (len(issues) == 0), issues
