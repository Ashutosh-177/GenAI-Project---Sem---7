"""PDF export — RFP explicitly wants generated documents available as both
DOCX and PDF; only DOCX existed until now. Reuses docx2pdf (Word COM
automation), already proven working when we visually verified the letterhead
rendering earlier — this just wires the same mechanism into the actual
product flow instead of a one-off testing script.

A real user hit "can't download as PDF" running this from the Streamlit
app. docx2pdf's own Windows code path (docx2pdf/main.py: `windows()`) calls
`win32com.client.Dispatch("Word.Application")` with NO explicit COM
initialization — it relies on the calling thread already being in a COM
apartment, which a bare top-level script gets close to for free but a
long-lived worker thread (Streamlit reruns the app script in a per-session
thread, not the process's main thread) is not guaranteed to have, and this
is the single most commonly reported docx2pdf failure mode outside plain
scripts. Fixed here with explicit `pythoncom.CoInitialize()` /
`CoUninitialize()` around the call, plus a hard timeout so a blocking Word
dialog (an update prompt, an unsaved-recovery dialog from a prior crashed
run) hangs this call instead of the whole app forever."""
import threading
from pathlib import Path

from docx2pdf import convert

_CONVERT_TIMEOUT_S = 60


class PdfConversionError(RuntimeError):
    """Wraps any failure from the underlying docx2pdf/Word COM call with a
    message a user (not just a developer reading a traceback) can act on."""


def docx_to_pdf(docx_path: Path) -> Path:
    """Converts in place next to the source .docx. Requires MS Word
    installed (COM automation) — confirmed present on this machine. If Word
    isn't available in a given deployment environment, this is the one
    export path that would need a different converter (e.g. LibreOffice
    headless) — noted here rather than assumed to always work."""
    docx_path = Path(docx_path)
    pdf_path = docx_path.with_suffix(".pdf")

    result: dict = {}

    def _run():
        import pythoncom
        pythoncom.CoInitialize()
        try:
            convert(str(docx_path), str(pdf_path))
        except Exception as e:  # noqa: BLE001 — re-raised in the caller's thread below
            result["error"] = e
        finally:
            pythoncom.CoUninitialize()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_CONVERT_TIMEOUT_S)

    if thread.is_alive():
        raise PdfConversionError(
            "PDF conversion is taking too long (over "
            f"{_CONVERT_TIMEOUT_S}s) — Microsoft Word is likely stuck behind "
            "a dialog box (an update prompt, or an unsaved-document recovery "
            "prompt from a previous crash). Close any open Word windows — "
            "check the taskbar even if none look open — and try again."
        )
    if "error" in result:
        raise PdfConversionError(
            f"PDF conversion failed: {result['error']}. This usually means "
            "Microsoft Word isn't installed, isn't licensed/activated, or is "
            "stuck showing a dialog box. Close any open Word windows and try "
            "again; if it keeps failing, the .docx file is still available "
            "to download directly."
        ) from result["error"]

    return pdf_path
