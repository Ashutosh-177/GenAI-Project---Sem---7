"""PDF export — RFP explicitly wants generated documents available as both
DOCX and PDF; only DOCX existed until now. Reuses docx2pdf (Word COM
automation), already proven working when we visually verified the letterhead
rendering earlier — this just wires the same mechanism into the actual
product flow instead of a one-off testing script."""
from pathlib import Path

from docx2pdf import convert


def docx_to_pdf(docx_path: Path) -> Path:
    """Converts in place next to the source .docx. Requires MS Word
    installed (COM automation) — confirmed present on this machine. If Word
    isn't available in a given deployment environment, this is the one
    export path that would need a different converter (e.g. LibreOffice
    headless) — noted here rather than assumed to always work."""
    docx_path = Path(docx_path)
    pdf_path = docx_path.with_suffix(".pdf")
    convert(str(docx_path), str(pdf_path))
    return pdf_path
