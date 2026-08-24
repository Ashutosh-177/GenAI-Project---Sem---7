"""One-time generator for the .docx template files docxtpl fills in.
Templates are real Word documents with Jinja placeholders ({{ field }}) as
run text — this script builds that starting file programmatically so it's
version-controlled as code, not a binary someone hand-edited in Word once
and can't reproduce.

Updated to support TemplateSettings — all colours, fonts, borders, logos,
and fixed pages (cover, TOC, declarations) are driven by the settings
dataclass instead of hardcoded constants, so the UI can customise them
per-render."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from generation.template_settings import TemplateSettings

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "generation" / "templates"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
SOURCESOFT_LOGO = ASSETS_DIR / "sourcesoft_logo.png"  # real logo, extracted from New Index/*.pdf
# Source Soft Solutions' real logo is a single square mark with no wordmark
# baked in (unlike QCI's, which combined mark + Hindi/English wordmark +
# tagline into one raster lockup) — their real letterhead pairs this same
# icon with a separate bold-navy "Source Soft Solutions" text run, not a
# wider pre-composed image. Both constants point at the same file; sizing
# is handled entirely via the width= parameter at each call site.
LOGO_FULL = SOURCESOFT_LOGO
LOGO_MARK = SOURCESOFT_LOGO


def _hex_to_rgb(hex_str: str) -> RGBColor:
    """Convert a 6-char hex colour string to a python-docx RGBColor."""
    hex_str = hex_str.lstrip("#")
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


def _resolve_logo(settings: TemplateSettings) -> Path | None:
    """Return the logo path to use, or None if explicitly disabled."""
    if settings.logo_path == "__NONE__":
        return None
    if settings.logo_path and Path(settings.logo_path).exists():
        return Path(settings.logo_path)
    if LOGO_FULL.exists():
        return LOGO_FULL
    return None


def _resolve_logo_mark(settings: TemplateSettings) -> Path | None:
    """Return the signature-block mark path, or None if disabled."""
    if settings.logo_mark_path == "__NONE__":
        return None
    if settings.logo_mark_path and Path(settings.logo_mark_path).exists():
        return Path(settings.logo_mark_path)
    if LOGO_MARK.exists():
        return LOGO_MARK
    return None


def _add_bottom_rule(paragraph, settings: TemplateSettings | None = None):
    """A real paragraph border, not literal underscore characters — the
    underscore approach wraps unpredictably at 95 chars and looks broken
    in Word (confirmed visually: it split onto two ragged lines)."""
    colour = settings.accent_colour if settings else "1B6E75"
    p_pr = paragraph._p.get_or_add_pPr()
    p_borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), colour)
    p_borders.append(bottom)
    p_pr.append(p_borders)


def _set_body_font(doc, settings: TemplateSettings | None = None):
    """Set the document's default body font from settings. Calibri by
    default, matching QCI's own RFP. Justified body text — set on the
    style so it applies everywhere automatically; paragraphs that need
    different alignment override it explicitly."""
    s = settings or TemplateSettings()
    style = doc.styles["Normal"]
    style.font.name = s.font_family
    style.font.size = Pt(s.body_font_size)
    style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # A real bug the user caught: the Table of Contents rendered as raw
    # "[Right-click and select 'Update Field'...]" placeholder text in the
    # exported PDF, not an actual table of contents. Word's TOC field only
    # computes its content when told to — either the user manually presses
    # F9, or the document is opened with "update fields on open" set. Our
    # PDF export goes through Word's own COM automation (docx2pdf), so
    # setting this at the document level makes Word compute the TOC (and
    # refresh PAGE/NUMPAGES) automatically the moment it opens the file,
    # before printing to PDF — no manual step needed on either side.
    settings_el = doc.settings.element
    update_fields = OxmlElement("w:updateFields")
    update_fields.set(qn("w:val"), "true")
    settings_el.append(update_fields)


def _add_page_border(doc, settings: TemplateSettings | None = None):
    """A rectangular border around every page, driven by settings for
    colour and style."""
    s = settings or TemplateSettings()
    if not s.show_page_border:
        return
    # Map friendly style names to Word border values
    border_val_map = {
        "single": "single",
        "double": "double",
        "thick": "thick",
        "dotted": "dotted",
    }
    border_val = border_val_map.get(s.page_border_style, "single")
    sectPr = doc.sections[0]._sectPr
    pg_borders = OxmlElement("w:pgBorders")
    pg_borders.set(qn("w:offsetFrom"), "page")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), border_val)
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "24")
        el.set(qn("w:color"), s.page_border_colour)
        pg_borders.append(el)
    sectPr.append(pg_borders)


def _add_running_header(doc, header_text: str, settings: TemplateSettings | None = None):
    """A repeating italic header on every page, matching QCI's own RFP.
    Can be disabled via settings."""
    s = settings or TemplateSettings()
    if not s.show_running_header:
        return
    header = doc.sections[0].header
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(header_text)
    run.italic = True
    run.font.size = Pt(10)
    run.font.name = s.font_family


def _add_shaded_heading(doc, text: str, settings: TemplateSettings | None = None,
                         outline_level: int | None = 0):
    """Section headings as a coloured filled bar with contrasting text —
    colours driven by settings instead of hardcoded constants.

    Sets w:outlineLvl so the Table of Contents field can actually find
    these headings. Without it the TOC populates EMPTY: the TOC field
    instruction (`TOC \\o "1-3"`) collects paragraphs by outline level,
    and a plain shaded paragraph has none. Using w:outlineLvl rather than
    Word's built-in "Heading 1" style keeps the custom bar colour, fill
    and font intact — applying the Heading style would override them."""
    s = settings or TemplateSettings()
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(6)
    p_pr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), s.heading_bar_colour)
    p_pr.append(shd)
    if outline_level is not None:
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), str(outline_level))
        p_pr.append(outline)
    run = p.add_run(text)
    run.bold = True
    run.font.color.rgb = _hex_to_rgb(s.heading_text_colour)
    run.font.name = s.font_family
    return p


def _add_letterhead(doc, settings: TemplateSettings | None = None):
    """Organisation letterhead — logo, name, address and a horizontal rule.

    Logo + name sit side by side in a borderless table, matching Source
    Soft Solutions' real page header (icon mark + bold "Source Soft
    Solutions" text run, not one pre-composed raster lockup — their logo
    file is just the icon, with the org name as live text next to it).
    Uses a custom logo/name if provided in settings, else Source Soft's
    real defaults."""
    s = settings or TemplateSettings()
    logo = _resolve_logo(s)

    if logo and s.organisation_name:
        # Fixed layout with explicit widths on BOTH columns, not autofit —
        # autofit with only the first column's width set let Word re-flow
        # the name column to something close to the full remaining page
        # width when opened in real Word (confirmed from a real generated
        # PDF: the org name rendered noticeably shifted right of/disconnected
        # from the logo, not sitting immediately beside it as a lockup).
        # Also vertically centers both cells so the single-line name sits
        # level with the visual center of the taller logo image instead of
        # pinned to the top of the row.
        row = doc.add_table(rows=1, cols=2)
        row.autofit = False
        logo_cell, name_cell = row.cell(0, 0), row.cell(0, 1)
        logo_cell.width = Cm(s.logo_width_cm + 0.5)
        name_cell.width = Cm(6)
        for cell in (logo_cell, name_cell):
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        logo_p = logo_cell.paragraphs[0]
        logo_p.add_run().add_picture(str(logo), width=Cm(s.logo_width_cm))
        name_p = name_cell.paragraphs[0]
        name_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        name_run = name_p.add_run(s.organisation_name)
        name_run.bold = True
        name_run.font.size = Pt(14)
        name_run.font.name = s.font_family
        name_run.font.color.rgb = _hex_to_rgb(s.accent_colour)
    elif logo:
        logo_para = doc.add_paragraph()
        logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        logo_para.add_run().add_picture(str(logo), width=Cm(s.logo_width_cm))
    elif s.organisation_name:
        name_p = doc.add_paragraph()
        name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        name_run = name_p.add_run(s.organisation_name)
        name_run.bold = True
        name_run.font.size = Pt(14)
        name_run.font.name = s.font_family
        name_run.font.color.rgb = _hex_to_rgb(s.accent_colour)

    # Only show address if provided
    addr_text = s.organisation_address
    if addr_text:
        addr = doc.add_paragraph()
        addr.alignment = WD_ALIGN_PARAGRAPH.CENTER
        addr_run = addr.add_run(addr_text)
        addr_run.font.size = Pt(9)
        addr_run.italic = True
        addr_run.font.name = s.font_family

    rule = doc.add_paragraph()
    _add_bottom_rule(rule, s)
    doc.add_paragraph()


def _signature_lines(name_ph: str, desig_ph: str) -> str:
    """Labeled "Name:"/"Designation:" lines rather than bare placeholder
    text — matches both real samples."""
    return f"Name: {name_ph}\nDesignation: {desig_ph}"


def _set_left(paragraph):
    """Force LEFT alignment on non-prose paragraphs to avoid JUSTIFY
    stretching short label text."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    return paragraph


def _left_cell(cell):
    """Same fix as `_set_left`, applied to a table cell's paragraph(s)."""
    for p in cell.paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    return cell


def _add_field_run(paragraph, field_code: str):
    """A real Word field (PAGE / NUMPAGES), not literal text — Word computes
    and auto-updates these on open/print, unlike a hardcoded number."""
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = field_code
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)
    return run


def _add_footer(doc, ref_field: str, settings: TemplateSettings | None = None):
    """A real Word footer repeating on every page with the document's
    reference number, version, and page X of Y."""
    s = settings or TemplateSettings()
    if not s.show_footer:
        return
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p.add_run(f"Ref: {ref_field}  |  Version {{{{ version }}}}  |  Page ")
    r1.font.size = Pt(8)
    r1.italic = True
    r1.font.name = s.font_family
    page_run = _add_field_run(p, "PAGE")
    page_run.font.size = Pt(8)
    page_run.italic = True
    r2 = p.add_run(" of ")
    r2.font.size = Pt(8)
    r2.italic = True
    r2.font.name = s.font_family
    numpages_run = _add_field_run(p, "NUMPAGES")
    numpages_run.font.size = Pt(8)
    numpages_run.italic = True


_SOURCESOFT_OFFICES = [
    ("New Jersey, USA – Headquarters", "3840 Park Avenue, STE C-205, Edison, NJ 08820", "+1 551 358 2076"),
    ("Dubai, UAE", "Unit 107-0140, OF 107, Dubai Investment Park First", "+971 50 780 4640"),
    ("Noida, India", "B-21 & B-93, Sector 67, Noida 201301, Uttar Pradesh", "+91 98999 41672"),
]


def _add_technical_proposal_footer(doc, client_field: str, settings: TemplateSettings | None = None):
    """Technical Proposal's footer — matches Source Soft Solutions' real
    proposal footer exactly (New Index/*.pdf, every page): a 3-column
    office block (New Jersey HQ / Dubai / Noida, each with address and
    phone) under a rule, then a contact/confidentiality line with the
    live page number. Deliberately NOT the generic Ref/Version/Page
    footer the other 12 templates use — those are signed legal
    instruments where that convention was benchmarked against a real
    signed document; this is a proposal, where Source Soft Solutions'
    own real proposals use this office-block format on every page
    instead, so this matches that real document rather than reusing the
    other convention just because it already existed."""
    s = settings or TemplateSettings()
    if not s.show_footer:
        return
    footer = doc.sections[0].footer
    rule_p = footer.paragraphs[0]
    _add_bottom_rule(rule_p, s)  # this draws the rule ABOVE this paragraph — see below
    # _add_bottom_rule puts the border on the paragraph's own bottom edge,
    # but we want the rule at the TOP of the footer, above the office
    # block — so swap it onto a top border on this same (otherwise empty)
    # paragraph instead.
    p_pr = rule_p._p.get_or_add_pPr()
    p_borders = p_pr.find(qn("w:pBdr"))
    bottom_el = p_borders.find(qn("w:bottom"))
    p_borders.remove(bottom_el)
    top_el = OxmlElement("w:top")
    for attr in ("w:val", "w:sz", "w:space", "w:color"):
        top_el.set(qn(attr), bottom_el.get(qn(attr)))
    p_borders.append(top_el)

    # footer.add_table(), NOT doc.add_table() — doc.add_table() appends to
    # the main document BODY regardless of what section is being built,
    # since python-docx has no notion of "currently working on a footer".
    # Confirmed as a real bug from a generated PDF: the whole 3-office
    # block landed on the LAST page of the document body, right after the
    # signature block, while the footer itself stayed a single bare line.
    # Header/footer containers need an explicit table width — unlike
    # Document.add_table(), they have no page-margin context to derive one
    # from automatically.
    offices = footer.add_table(rows=1, cols=3, width=Cm(17))
    offices.autofit = True
    for col, (title, addr, phone) in enumerate(_SOURCESOFT_OFFICES):
        cell = offices.cell(0, col)
        p = cell.paragraphs[0]
        _tight(p, 1)
        tr = p.add_run(title)
        tr.bold = True
        tr.font.size = Pt(8)
        tr.font.name = s.font_family
        for line in (addr, phone):
            lp = cell.add_paragraph(line)
            _tight(lp, 1)
            for r in lp.runs:
                r.font.size = Pt(8)
                r.font.name = s.font_family
        _left_cell(cell)

    contact_p = footer.add_paragraph()
    contact_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    tab_stops = contact_p.paragraph_format.tab_stops
    tab_stops.add_tab_stop(Cm(17), alignment=WD_ALIGN_PARAGRAPH.RIGHT)
    cr = contact_p.add_run(
        f"info@sourcesoftsolutions.com · www.sourcesoftsolutions.com · "
        f"Confidential — prepared for {client_field}\t")
    cr.font.size = Pt(8)
    cr.font.name = s.font_family
    page_prefix = contact_p.add_run("Page ")
    page_prefix.font.size = Pt(8)
    page_prefix.font.name = s.font_family
    page_run = _add_field_run(contact_p, "PAGE")
    page_run.font.size = Pt(8)
    page_run.font.name = s.font_family


def _add_issuer_acceptance_block(doc, issuer_ph: str, name_ph: str, desig_ph: str,
                                  acceptance_party_ph: str, settings: TemplateSettings | None = None):
    """Work Order issuer + contractor acknowledgment block."""
    table = doc.add_table(rows=3, cols=2)
    table.cell(0, 0).text = f"For {issuer_ph}"
    table.cell(0, 1).text = f"Received & Accepted by\nFor {acceptance_party_ph}"
    table.cell(1, 0).text = " "
    table.cell(1, 1).text = " "
    table.cell(2, 0).text = _signature_lines(name_ph, desig_ph)
    table.cell(2, 1).text = "Signature: ____________________\nName: ____________________\nDate: ____________________"
    for row in range(3):
        _left_cell(table.cell(row, 0))
        _left_cell(table.cell(row, 1))


def _add_witness_block(doc):
    """MoUs specifically get a witness section — blank numbered lines
    for handwritten witness names at signing time."""
    doc.add_paragraph()
    wit_table = doc.add_table(rows=3, cols=2)
    wit_table.cell(0, 0).text = "Witnesses:"
    wit_table.cell(0, 0).paragraphs[0].runs[0].bold = True
    wit_table.cell(0, 1).text = "Witnesses:"
    wit_table.cell(0, 1).paragraphs[0].runs[0].bold = True
    wit_table.cell(1, 0).text = "1. ____________________________"
    wit_table.cell(1, 1).text = "1. ____________________________"
    wit_table.cell(2, 0).text = "2. ____________________________"
    wit_table.cell(2, 1).text = "2. ____________________________"
    for row in range(3):
        _left_cell(wit_table.cell(row, 0))
        _left_cell(wit_table.cell(row, 1))


# ═══════════════════════════════════════════════════════════════════════
# NEW: Fixed pages — Cover Page, Table of Contents, Declarations
# ═══════════════════════════════════════════════════════════════════════

def _add_section_break(doc):
    """Insert a section break (next page) so the next content starts on
    a new page.

    Copies the document's existing body-level sectPr rather than creating
    an empty one. In Word's model a paragraph-level sectPr describes the
    section *ending* at that paragraph — so an empty sectPr silently
    stripped the page border and running header from the cover page and
    every other pre-break page, while the body kept them (confirmed
    visually: page 4 had the border, page 1 did not). Inheriting the real
    section properties keeps borders, headers, margins and page size
    consistent across the whole document — matching QCI's own RFP, whose
    cover page carries the same border and running header as its body."""
    body_sect_pr = doc.element.body.find(qn("w:sectPr"))
    if body_sect_pr is not None:
        sect_pr = copy.deepcopy(body_sect_pr)
    else:
        sect_pr = OxmlElement("w:sectPr")

    # Set (or replace) the break type without disturbing the rest. w:type
    # must sit before w:pgSz in the schema's element order.
    for existing in sect_pr.findall(qn("w:type")):
        sect_pr.remove(existing)
    sect_type = OxmlElement("w:type")
    sect_type.set(qn("w:val"), "nextPage")
    pg_sz = sect_pr.find(qn("w:pgSz"))
    if pg_sz is not None:
        pg_sz.addprevious(sect_type)
    else:
        sect_pr.append(sect_type)

    last_para = doc.paragraphs[-1]
    p_pr = last_para._p.get_or_add_pPr()
    p_pr.append(sect_pr)


def _add_cover_page(doc, settings: TemplateSettings, title: str, metadata_rows: list):
    """A dedicated cover page — page 1 of every document.

    Layout:
    - Organisation logo (large, centered)
    - Organisation name in bold heading font
    - Horizontal accent rule
    - Document title in the accent colour, large
    - Key metadata table (date, parties, reference no.)
    - Optional "CONFIDENTIAL" marking
    - Section break to start body on next page
    """
    if not settings.include_cover_page:
        return

    # Spacer for visual balance — was 2 full blank paragraphs; trimmed to 1
    # after the new 3-office footer (see _add_technical_proposal_footer)
    # started eating enough extra page height on every page that the
    # cover's own content spilled a near-empty line onto page 2, pushing
    # the Table of Contents to start on page 3 instead of page 2
    # (confirmed from a real generated PDF, not assumed).
    doc.add_paragraph()

    # Large logo
    logo = _resolve_logo(settings)
    if logo:
        logo_para = doc.add_paragraph()
        logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        logo_para.add_run().add_picture(str(logo), width=Cm(8))
        _tight(doc.add_paragraph(), 2)

    # Organisation name
    if settings.organisation_name:
        org_para = doc.add_paragraph()
        org_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        org_run = org_para.add_run(settings.organisation_name)
        org_run.bold = True
        org_run.font.size = Pt(20)
        org_run.font.name = settings.font_family
        org_run.font.color.rgb = _hex_to_rgb(settings.heading_bar_colour)

    # Organisation address
    if settings.organisation_address:
        addr_para = doc.add_paragraph()
        addr_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        addr_run = addr_para.add_run(settings.organisation_address)
        addr_run.font.size = Pt(10)
        addr_run.italic = True
        addr_run.font.name = settings.font_family

    # Accent rule
    rule = doc.add_paragraph()
    _add_bottom_rule(rule, settings)
    _tight(doc.add_paragraph(), 2)

    # Document title
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_para.add_run(title)
    title_run.bold = True
    title_run.font.size = Pt(settings.heading_font_size + 4)
    title_run.font.name = settings.font_family
    title_run.font.color.rgb = _hex_to_rgb(settings.accent_colour)

    _tight(doc.add_paragraph(), 2)

    # Key metadata table (subset — just the essentials for a cover page)
    if metadata_rows:
        meta = doc.add_table(rows=len(metadata_rows), cols=2)
        meta.style = "Light Grid Accent 1"
        for i, (label, value) in enumerate(metadata_rows):
            meta.cell(i, 0).text = label
            meta.cell(i, 0).paragraphs[0].runs[0].bold = True
            for p in meta.cell(i, 0).paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for r in p.runs:
                    r.font.name = settings.font_family
            meta.cell(i, 1).text = value
            for p in meta.cell(i, 1).paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for r in p.runs:
                    r.font.name = settings.font_family

    _tight(doc.add_paragraph(), 2)

    # Confidential marking
    if settings.show_confidential_marking:
        conf_para = doc.add_paragraph()
        conf_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        conf_run = conf_para.add_run("CONFIDENTIAL — FOR OFFICIAL USE ONLY")
        conf_run.bold = True
        conf_run.font.size = Pt(12)
        conf_run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
        conf_run.font.name = settings.font_family

    # Section break to start content on next page
    _add_section_break(doc)


def _add_table_of_contents(doc, settings: TemplateSettings):
    """Insert a Table of Contents page using a Word TOC field.
    Word auto-populates the TOC when the user opens the document and
    presses F9 or selects 'Update Table' — the field instruction tells
    Word which heading levels to include."""
    if not settings.include_toc:
        return

    # TOC heading — outline_level=None so the Table of Contents doesn't
    # list itself as one of its own entries.
    _add_shaded_heading(doc, "TABLE OF CONTENTS", settings, outline_level=None)

    doc.add_paragraph()

    # TOC field — instructs Word to build a table of contents from
    # headings 1-3. The \\h flag creates hyperlinks, \\z hides tab
    # leaders in web view, \\u uses outline levels.
    toc_para = doc.add_paragraph()
    run = toc_para.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run._r.append(fld_begin)

    instr_run = toc_para.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    instr_run._r.append(instr)

    fld_separate_run = toc_para.add_run()
    fld_separate = OxmlElement("w:fldChar")
    fld_separate.set(qn("w:fldCharType"), "separate")
    fld_separate_run._r.append(fld_separate)

    # Placeholder text shown before the user updates the TOC in Word
    placeholder_run = toc_para.add_run(
        "[Right-click and select 'Update Field' to populate the Table of Contents]"
    )
    placeholder_run.italic = True
    placeholder_run.font.size = Pt(10)
    placeholder_run.font.name = settings.font_family

    fld_end_run = toc_para.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    fld_end_run._r.append(fld_end)

    doc.add_paragraph()

    # Section break
    _add_section_break(doc)


# Standard Indian Government declarations, varying by document category.
_DECLARATIONS_COMMON = [
    "This document is executed on the basis of mutual understanding between "
    "the parties mentioned herein, and represents the true intent of all "
    "signatories.",
    "The information contained in this document is true, correct, and "
    "complete to the best of our knowledge and belief. No material "
    "information has been concealed, suppressed, or misrepresented.",
    "All parties agree to act in good faith and in accordance with the "
    "terms set forth in this document.",
    "Any dispute arising out of or in connection with this document shall "
    "be subject to the exclusive jurisdiction of the courts in New Delhi, "
    "India, and shall be governed by the laws of India.",
]

_DECLARATIONS_BY_TYPE = {
    "work_order": [
        "The contractor undertakes to comply with all applicable labour "
        "laws, safety regulations, and environmental norms as prescribed "
        "by the Government of India and the respective State Government.",
        "The contractor confirms that they have not been blacklisted or "
        "debarred by any Central/State Government department or Public "
        "Sector Undertaking as on the date of this Work Order.",
        "The contractor agrees to maintain adequate insurance coverage for "
        "all personnel deployed and equipment used during the execution of "
        "this work.",
    ],
    "mou": [
        "This Memorandum of Understanding does not create any legally "
        "binding obligation between the parties, except for the clauses "
        "relating to confidentiality and intellectual property rights.",
        "Either party may terminate this MoU by providing written notice "
        "of not less than 30 days to the other party.",
        "Any intellectual property developed jointly under this MoU shall "
        "be jointly owned by both parties, unless otherwise agreed in "
        "writing.",
    ],
    "agreement": [
        "Both parties confirm that they have the legal authority and "
        "capacity to enter into this Agreement and to perform their "
        "respective obligations hereunder.",
        "Neither party shall assign or transfer any rights or obligations "
        "under this Agreement without the prior written consent of the "
        "other party.",
        "This Agreement, together with all annexures and schedules "
        "attached hereto, constitutes the entire agreement between the "
        "parties and supersedes all prior negotiations, representations, "
        "and agreements.",
    ],
    "proposal": [
        "The bidder hereby declares that the information furnished in this "
        "proposal is true and correct, and no material information has "
        "been concealed or suppressed.",
        "The bidder confirms that they meet all the eligibility criteria "
        "as specified in the Request for Proposal (RFP) and are not "
        "disqualified under any of the exclusion conditions.",
        "The bidder agrees that the prices quoted in this proposal shall "
        "remain valid for the period specified in the RFP and shall not "
        "be subject to any escalation.",
        "The bidder undertakes to execute the work as per the terms and "
        "conditions of the RFP and this proposal, if selected.",
    ],
}


def _get_doc_category(title: str) -> str:
    """Infer the document category from the title for declarations."""
    title_lower = title.lower()
    if "work order" in title_lower or "amc" in title_lower or "maintenance" in title_lower:
        return "work_order"
    if "mou" in title_lower or "memorandum" in title_lower:
        return "mou"
    if "agreement" in title_lower or "licensing" in title_lower or "consultancy" in title_lower or "service agreement" in title_lower:
        return "agreement"
    if "proposal" in title_lower:
        return "proposal"
    return "work_order"  # fallback


def _add_declarations_page(doc, settings: TemplateSettings, title: str):
    """A Declarations & Undertakings page with standard Indian Government
    legal declarations, varying by document type. Each declaration is
    numbered and includes a checkbox placeholder for formal acknowledgment."""
    if not settings.include_declarations:
        return

    _add_shaded_heading(doc, "DECLARATIONS & UNDERTAKINGS", settings)

    doc.add_paragraph()

    # Intro paragraph
    intro = doc.add_paragraph()
    intro_run = intro.add_run(
        "The undersigned hereby declare and undertake the following in "
        "connection with this document:"
    )
    intro_run.font.name = settings.font_family
    intro_run.font.size = Pt(settings.body_font_size)

    doc.add_paragraph()

    # Common declarations
    doc_category = _get_doc_category(title)
    all_declarations = _DECLARATIONS_COMMON + _DECLARATIONS_BY_TYPE.get(doc_category, [])

    for i, declaration in enumerate(all_declarations, 1):
        decl_para = doc.add_paragraph()
        _set_left(decl_para)

        # Numbered checkbox
        checkbox_run = decl_para.add_run(f"{i}. ☐  ")
        checkbox_run.bold = True
        checkbox_run.font.name = settings.font_family
        checkbox_run.font.size = Pt(settings.body_font_size)

        # Declaration text
        text_run = decl_para.add_run(declaration)
        text_run.font.name = settings.font_family
        text_run.font.size = Pt(settings.body_font_size)

    doc.add_paragraph()

    # Acknowledgment line
    ack = doc.add_paragraph()
    _set_left(ack)
    ack_run = ack.add_run(
        "I/We have read and understood all the above declarations and "
        "undertakings and agree to abide by them."
    )
    ack_run.italic = True
    ack_run.font.name = settings.font_family
    ack_run.font.size = Pt(settings.body_font_size)

    doc.add_paragraph()

    # Signature line for declarations
    sig_para = doc.add_paragraph()
    _set_left(sig_para)
    sig_run = sig_para.add_run(
        "Signature: ____________________    "
        "Name: ____________________    "
        "Date: ____________________"
    )
    sig_run.font.name = settings.font_family
    sig_run.font.size = Pt(settings.body_font_size)

    doc.add_paragraph()

    # Section break
    _add_section_break(doc)


# ═══════════════════════════════════════════════════════════════════════
# Template builders — updated to accept TemplateSettings
# ═══════════════════════════════════════════════════════════════════════

def build_work_order_template(settings: TemplateSettings | None = None):
    settings = settings or TemplateSettings()
    doc = Document()
    _set_body_font(doc, settings)
    _add_page_border(doc, settings)
    _add_running_header(doc, "WORK ORDER — {{ work_order_no }}", settings)

    # ── Fixed pages ──
    cover_meta = [
        ("Work Order No.", "{{ work_order_no }}"),
        ("Date", "{{ work_order_date }}"),
        ("Issued To", "{{ contractor_name }}"),
        ("Project", "{{ project_title }}"),
    ]
    _add_cover_page(doc, settings, "WORK ORDER", cover_meta)
    _add_table_of_contents(doc, settings)
    _add_declarations_page(doc, settings, "WORK ORDER")

    # ── Body content ──
    _add_letterhead(doc, settings)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("WORK ORDER")
    run.bold = True
    run.font.size = Pt(settings.heading_font_size)
    run.font.name = settings.font_family

    doc.add_paragraph()

    # metadata table
    meta = doc.add_table(rows=4, cols=2)
    meta.style = "Light Grid Accent 1"
    rows = [
        ("Work Order No.", "{{ work_order_no }}"),
        ("Date", "{{ work_order_date }}"),
        ("Issued To (Contractor)", "{{ contractor_name }}"),
        ("Contractor Address", "{{ contractor_address }}"),
    ]
    for i, (label, value) in enumerate(rows):
        meta.cell(i, 0).text = label
        meta.cell(i, 0).paragraphs[0].runs[0].bold = True
        meta.cell(i, 1).text = value
        _left_cell(meta.cell(i, 0))
        _left_cell(meta.cell(i, 1))

    doc.add_paragraph()
    _add_shaded_heading(doc, "1. Project / Work Title", settings)
    doc.add_paragraph("{{ project_title }}")

    _add_shaded_heading(doc, "2. Scope of Work", settings)
    doc.add_paragraph("{{ scope_of_work }}")

    _add_shaded_heading(doc, "3. Contract Value", settings)
    doc.add_paragraph("{{ contract_value }}")

    _add_shaded_heading(doc, "4. Schedule", settings)
    doc.add_paragraph("Start date: {{ start_date }}")
    doc.add_paragraph("Completion period: {{ completion_period }}")

    _add_shaded_heading(doc, "5. Payment Terms", settings)
    doc.add_paragraph("{{ payment_terms }}")

    _add_shaded_heading(doc, "6. Terms & Conditions", settings)
    _set_left(doc.add_paragraph("{{ terms_and_conditions }}"))

    doc.add_paragraph()
    doc.add_paragraph()
    logo_mark = _resolve_logo_mark(settings)
    if logo_mark:
        mark_para = doc.add_paragraph()
        mark_para.add_run().add_picture(str(logo_mark), width=Cm(settings.logo_mark_width_cm))
    _add_issuer_acceptance_block(doc, "{{ issuing_organisation }}", "{{ authorized_signatory_name }}",
                                  "{{ authorized_signatory_designation }}", "{{ contractor_name }}", settings)

    _add_footer(doc, "{{ work_order_no }}", settings)

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / "work_order_template.docx"
    doc.save(out_path)
    print(f"Built {out_path}")


def build_mou_template(settings: TemplateSettings | None = None):
    """MoU — Institutional Collaboration template."""
    settings = settings or TemplateSettings()
    doc = Document()
    _set_body_font(doc, settings)
    _add_page_border(doc, settings)
    _add_running_header(doc, "MEMORANDUM OF UNDERSTANDING — {{ mou_no }}", settings)

    # ── Fixed pages ──
    cover_meta = [
        ("MoU No.", "{{ mou_no }}"),
        ("Date", "{{ mou_date }}"),
        ("Between", "{{ party_a_name }} and {{ party_b_name }}"),
    ]
    _add_cover_page(doc, settings, "MEMORANDUM OF UNDERSTANDING", cover_meta)
    _add_table_of_contents(doc, settings)
    _add_declarations_page(doc, settings, "MEMORANDUM OF UNDERSTANDING")

    # ── Body content ──
    _add_letterhead(doc, settings)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("MEMORANDUM OF UNDERSTANDING")
    run.bold = True
    run.font.size = Pt(settings.heading_font_size)
    run.font.name = settings.font_family

    doc.add_paragraph()

    meta = doc.add_table(rows=3, cols=2)
    meta.style = "Light Grid Accent 1"
    rows = [
        ("MoU No.", "{{ mou_no }}"),
        ("Date", "{{ mou_date }}"),
        ("Between", "{{ party_a_name }} and {{ party_b_name }}"),
    ]
    for i, (label, value) in enumerate(rows):
        meta.cell(i, 0).text = label
        meta.cell(i, 0).paragraphs[0].runs[0].bold = True
        meta.cell(i, 1).text = value
        _left_cell(meta.cell(i, 0))
        _left_cell(meta.cell(i, 1))

    doc.add_paragraph()
    _add_shaded_heading(doc, "1. Title / Purpose", settings)
    doc.add_paragraph("{{ mou_title }}")

    _add_shaded_heading(doc, "2. Background", settings)
    doc.add_paragraph("{{ background }}")

    _add_shaded_heading(doc, "3. Objectives", settings)
    doc.add_paragraph("{{ objectives }}")

    _add_shaded_heading(doc, "4. Second Party Address", settings)
    doc.add_paragraph("{{ party_b_address }}")

    _add_shaded_heading(doc, "5. Duration", settings)
    doc.add_paragraph("{{ duration }}")

    doc.add_paragraph()
    doc.add_paragraph()
    logo_mark = _resolve_logo_mark(settings)
    if logo_mark:
        mark_para = doc.add_paragraph()
        mark_para.add_run().add_picture(str(logo_mark), width=Cm(settings.logo_mark_width_cm))

    sig_table = doc.add_table(rows=3, cols=2)
    sig_table.cell(0, 0).text = "FOR AND ON BEHALF OF {{ party_a_name }}"
    sig_table.cell(0, 1).text = "FOR AND ON BEHALF OF {{ party_b_name }}"
    sig_table.cell(1, 0).text = " "
    sig_table.cell(1, 1).text = " "
    sig_table.cell(2, 0).text = _signature_lines("{{ signatory_a_name }}", "{{ signatory_a_designation }}")
    sig_table.cell(2, 1).text = _signature_lines("{{ signatory_b_name }}", "{{ signatory_b_designation }}")
    for row in range(3):
        _left_cell(sig_table.cell(row, 0))
        _left_cell(sig_table.cell(row, 1))
    _add_witness_block(doc)

    _add_footer(doc, "{{ mou_no }}", settings)

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / "mou_template.docx"
    doc.save(out_path)
    print(f"Built {out_path}")


def build_generic_template(filename: str, title: str, metadata_rows: list,
                            sections: list, signatories: list, include_witnesses: bool = False,
                            acceptance_party_field: str = None,
                            settings: TemplateSettings | None = None):
    """Generic builder for the remaining 10 templates — same structure as
    Work Order and MoU, parameterized. Now also supports TemplateSettings
    for all customisable properties and inserts fixed pages."""
    settings = settings or TemplateSettings()
    doc = Document()
    _set_body_font(doc, settings)
    _add_page_border(doc, settings)
    _add_running_header(doc, f"{title} — {metadata_rows[0][1]}", settings)

    # ── Fixed pages ──
    _add_cover_page(doc, settings, title, metadata_rows)
    _add_table_of_contents(doc, settings)
    _add_declarations_page(doc, settings, title)

    # ── Body content ──
    _add_letterhead(doc, settings)

    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run(title)
    run.bold = True
    run.font.size = Pt(settings.heading_font_size)
    run.font.name = settings.font_family
    doc.add_paragraph()

    meta = doc.add_table(rows=len(metadata_rows), cols=2)
    meta.style = "Light Grid Accent 1"
    for i, (label, value) in enumerate(metadata_rows):
        meta.cell(i, 0).text = label
        meta.cell(i, 0).paragraphs[0].runs[0].bold = True
        meta.cell(i, 1).text = value
        _left_cell(meta.cell(i, 0))
        _left_cell(meta.cell(i, 1))

    doc.add_paragraph()
    for i, (heading, value) in enumerate(sections, 1):
        _add_shaded_heading(doc, f"{i}. {heading}", settings)
        body = doc.add_paragraph(value)
        if "\n" in value:
            _set_left(body)

    doc.add_paragraph()
    doc.add_paragraph()
    logo_mark = _resolve_logo_mark(settings)
    if logo_mark:
        mark_para = doc.add_paragraph()
        mark_para.add_run().add_picture(str(logo_mark), width=Cm(settings.logo_mark_width_cm))

    if len(signatories) == 1 and acceptance_party_field:
        label, name_ph, desig_ph = signatories[0]
        _add_issuer_acceptance_block(doc, label, name_ph, desig_ph, acceptance_party_field, settings)
    elif len(signatories) == 1:
        label, name_ph, desig_ph = signatories[0]
        _set_left(doc.add_paragraph(f"For {label}"))
        doc.add_paragraph()
        _set_left(doc.add_paragraph(_signature_lines(name_ph, desig_ph)))
    else:
        sig_table = doc.add_table(rows=3, cols=2)
        for col, (label, name_ph, desig_ph) in enumerate(signatories):
            sig_table.cell(0, col).text = f"FOR AND ON BEHALF OF {label}"
            sig_table.cell(1, col).text = " "
            sig_table.cell(2, col).text = _signature_lines(name_ph, desig_ph)
            _left_cell(sig_table.cell(0, col))
            _left_cell(sig_table.cell(1, col))
            _left_cell(sig_table.cell(2, col))
        if include_witnesses:
            _add_witness_block(doc)

    _add_footer(doc, metadata_rows[0][1], settings)

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / filename
    doc.save(out_path)
    print(f"Built {out_path}")


# ═══════════════════════════════════════════════════════════════════════
# Architecture / flow diagrams — Technical Proposal template
# ═══════════════════════════════════════════════════════════════════════
# Real pattern, not invented: Source Soft Solutions' own proposals
# (New Index/*.pdf) carry two structured diagrams in every one of them —
# a layered architecture stack ("Solution & Technology Architecture") and
# a numbered process flow ("Data Flow Diagrams"). Colours below are read
# directly off the real diagram's fill colours (pymupdf get_drawings() on
# NIGST_Technical_Proposal_v2.pdf p.7), not chosen freehand.
_DIAGRAM_LAYER_COLOURS = ["1F4E78", "2E6BA3", "BF382A", "2E7D45", "2E86AB"]


def _disable_row_split(row):
    """Stops a table row from breaking across a page boundary — Word's
    default lets a row split mid-cell, which fractured diagram box text
    across the page edge (confirmed visually: "1.0 Citizen submits form"
    literally split, with "form" landing on the next page while "1.0
    Citizen submits" stayed on the page before). Sets w:cantSplit, which
    python-docx doesn't expose as a high-level property. A whole row now
    either fits entirely on the current page or moves entirely to the
    next one."""
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def _keep_row_with_next(row):
    """w:keepNext on every paragraph in a row's cells — tells Word "don't
    leave this row on a different page than the row after it." Applied to
    every row except the table's last, this keeps the WHOLE diagram table
    together as one visual unit (moving entirely to the next page if it
    doesn't fit, rather than splitting between rows) — cantSplit alone
    only stops a single row from breaking mid-cell, it doesn't stop the
    table breaking BETWEEN rows. Confirmed needed from a real generated
    PDF: the architecture diagram's last two rows spilled onto the
    following page, ahead of "7. Data Flow Diagram", leaving an ugly gap."""
    for cell in row.cells:
        for p in cell.paragraphs:
            p._p.get_or_add_pPr().append(OxmlElement("w:keepNext"))


def _add_data_table(doc, headers: list[str], rows: list[list[str]],
                     settings: TemplateSettings | None = None,
                     col_widths_cm: list[float] | None = None):
    """A real Word table matching the reference proposals' matrix style
    (Requirement to Solution Compliance Matrix, Public Website Modules &
    Features, etc.): navy header row with white bold text, striped body
    rows, borders. Used for every new tabular section added to close the
    "most of this is still text, not tabular" gap — a table users can
    scan, sort mentally by column, not another paragraph of prose."""
    s = settings or TemplateSettings()
    if not rows:
        return None
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.autofit = True
    for c, h in enumerate(headers):
        cell = table.cell(0, c)
        p = cell.paragraphs[0]
        p_pr = p._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), s.heading_bar_colour)
        p_pr.append(shd)
        r = p.add_run(h)
        r.bold = True
        r.font.color.rgb = _hex_to_rgb(s.heading_text_colour)
        r.font.name = s.font_family
        r.font.size = Pt(s.body_font_size)
        _left_cell(cell)
    for ri, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = table.cell(ri + 1, c)
            p = cell.paragraphs[0]
            if ri % 2 == 1:
                p_pr = p._p.get_or_add_pPr()
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), "F5F7FA")
                p_pr.append(shd)
            r = p.add_run(str(val))
            r.font.name = s.font_family
            r.font.size = Pt(s.body_font_size)
            _left_cell(cell)
    if col_widths_cm:
        table.autofit = False
        for row_cells in table.rows:
            for c, w in enumerate(col_widths_cm):
                row_cells.cells[c].width = Cm(w)
    for row in table.rows:
        _disable_row_split(row)
    return table


def _add_feature_grid(doc, items: list[tuple[str, str]],
                       settings: TemplateSettings | None = None, cols: int = 2):
    """A grid of bordered tiles (bold label + description), one item per
    cell — matches the reference proposal's "Admin CMS Portal" 2x3
    capability grid (Access & overview / Content management / Labs &
    enquiries / ...). Same underlying table-as-grid technique as the About
    page's "What we deliver" grid, factored out here so every new tile
    section (admin capabilities, etc.) doesn't hand-roll its own copy."""
    s = settings or TemplateSettings()
    if not items:
        return None
    nrows = (len(items) + cols - 1) // cols
    grid = doc.add_table(rows=nrows, cols=cols)
    grid.autofit = True
    for i, (label, desc) in enumerate(items):
        row, col = divmod(i, cols)
        cell = grid.cell(row, col)
        p = cell.paragraphs[0]
        _tight(p, 2)
        lr = p.add_run(label)
        lr.bold = True
        lr.font.name = s.font_family
        lr.font.color.rgb = _hex_to_rgb(s.accent_colour)
        dp = cell.add_paragraph(desc)
        _tight(dp, 6)
        for run in dp.runs:
            run.font.name = s.font_family
            run.font.size = Pt(s.body_font_size - 1)
        _left_cell(cell)
    for row in grid.rows:
        _disable_row_split(row)
    return grid


def _add_sitemap_diagram_image(doc, paragraph, site_name: str,
                                pillars: list[tuple[str, list[str]]],
                                settings: TemplateSettings | None = None):
    """Renders the Information Architecture sitemap (title bar, down
    arrow, one column per top-level nav pillar with its sub-pages) and
    embeds it in place of the `[[SITEMAP_DIAGRAM]]` marker paragraph."""
    s = settings or TemplateSettings()
    if not pillars:
        return
    from generation.diagram_render import render_sitemap_diagram
    _embed_diagram_image(
        paragraph, render_sitemap_diagram, site_name, pillars,
        tmp_name="sitemap_diagram.png",
        accent_hex=s.accent_colour, font_family=s.font_family,
    )


def _add_ui_mockup_image(doc, paragraph, kind: str, heading: str,
                          nav_items: list[str] | None = None, cards: list[str] | None = None,
                          sidebar_items: list[str] | None = None,
                          settings: TemplateSettings | None = None):
    """Renders a low-fidelity UI wireframe (browser frame + nav/hero/cards
    for `kind="public_home"`, or sidebar/stat-cards/table for
    `kind="admin_dashboard"`) and embeds it in place of its marker
    paragraph — the actual "wireframes/mock screens" the reference
    proposal's section 14 shows and this template didn't have at all
    before. `nav_items`/`cards`/`sidebar_items` (from this project's own
    sitemap/modules/admin-capabilities, passed by _inject_generated_content)
    make the mockup reflect THIS project instead of a generic skeleton
    every project used to get — a real user asked "will the image be the
    same [every time]?" and the honest answer had been yes."""
    from generation.diagram_render import render_ui_mockup
    s = settings or TemplateSettings()
    _embed_diagram_image(
        paragraph, render_ui_mockup, kind, heading,
        tmp_name=f"ui_mockup_{kind}.png", width_cm=13.0,
        accent_hex=s.accent_colour, font_family=s.font_family,
        nav_items=nav_items, cards=cards, sidebar_items=sidebar_items,
    )


def _embed_diagram_image(paragraph, render_fn, *args, width_cm: float = 16.0, tmp_name: str, **kwargs):
    """Renders a diagram via `render_fn` (from generation.diagram_render)
    to a temp PNG and embeds it into `paragraph`, replacing whatever text
    the paragraph held (the literal `[[MARKER]]` placeholder text).

    Superseded the original Word-table diagrams (shaded table cells, ▶
    glyph arrows) — tables can't produce real borders-and-arrowheads
    diagrams, which is why the first version looked flat/basic next to
    Source Soft Solutions' own reference proposals. Rendering to a raster
    image and embedding it as a picture (same `add_picture` pattern the
    logo/letterhead already use) gives pixel-level control over box
    borders, arrowheads and colour that a table cannot."""
    import tempfile
    from pathlib import Path as _P

    tmp_path = _P(tempfile.gettempdir()) / tmp_name
    render_fn(*args, tmp_path, **kwargs)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in list(paragraph.runs):
        run.text = ""
    run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
    run.add_picture(str(tmp_path), width=Cm(width_cm))
    tmp_path.unlink(missing_ok=True)


def _add_layered_architecture_diagram(doc, paragraph, layers: list[tuple[str, str]],
                                       settings: TemplateSettings | None = None):
    """Renders the layered-architecture stack as an image (vertical cards
    with a coloured accent bar, connected by arrows) and embeds it in
    place of the `[[ARCHITECTURE_DIAGRAM]]` marker paragraph."""
    s = settings or TemplateSettings()
    if not layers:
        return
    from generation.diagram_render import render_architecture_diagram
    _embed_diagram_image(
        paragraph, render_architecture_diagram, layers,
        tmp_name="arch_diagram.png",
        accent_hex=s.accent_colour, font_family=s.font_family,
    )


def _add_flow_diagram(doc, paragraph, steps: list[str], settings: TemplateSettings | None = None):
    """Renders the process/data-flow chain as an image (numbered boxes
    connected by arrows, wrapping onto further rows) and embeds it in
    place of the `[[DATA_FLOW_DIAGRAM]]` marker paragraph."""
    s = settings or TemplateSettings()
    if not steps:
        return
    from generation.diagram_render import render_flow_diagram
    _embed_diagram_image(
        paragraph, render_flow_diagram, steps,
        tmp_name="flow_diagram.png",
        accent_hex=s.accent_colour, font_family=s.font_family,
    )


def _add_timeline_diagram(doc, paragraph, phases: list[tuple[str, str, str]],
                           settings: TemplateSettings | None = None):
    """Renders the implementation timeline as an image (stacked phase
    cards with a week-range header) and embeds it in place of the
    `[[TIMELINE_DIAGRAM]]` marker paragraph. `phases` is a list of
    (phase_name, week_range, description)."""
    s = settings or TemplateSettings()
    if not phases:
        return
    from generation.diagram_render import render_timeline_diagram
    _embed_diagram_image(
        paragraph, render_timeline_diagram, phases,
        tmp_name="timeline_diagram.png",
        accent_hex=s.accent_colour, font_family=s.font_family,
    )


def _tight(paragraph, space_after: int = 4):
    """Trims a paragraph's space-after to `space_after` pt — the default
    Normal-style spacing (plus a run of separate one-line paragraphs for
    the deliverables list and leadership bios) was consuming enough extra
    vertical space that "About the Company" spilled onto a second page,
    orphaning "Vikram Sharma — Solutions Lead" as a heading alone at the
    bottom of page 3 with his bio isolated alone on page 4 (confirmed
    visually from a real generated PDF, not assumed). Keeps the content,
    just stops padding it with whitespace it doesn't need."""
    paragraph.paragraph_format.space_after = Pt(space_after)
    return paragraph


def _resolve_leadership_photo(name_title: str, settings: TemplateSettings) -> Path:
    """A real photo if one exists at assets/leadership/<slug>.(jpg|jpeg|png)
    (drop a file there named after the person, e.g. "alok_dharayan.jpg", to
    have it used automatically), else a generated navy-circle initials
    placeholder — no real leadership photos ship with this repo, so a
    placeholder is what renders until real ones are supplied."""
    name = name_title.split("—")[0].strip()
    slug = name.lower().replace(" ", "_").replace(".", "")
    photo_dir = ASSETS_DIR / "leadership"
    for ext in (".jpg", ".jpeg", ".png"):
        candidate = photo_dir / f"{slug}{ext}"
        if candidate.exists():
            return candidate
    import tempfile
    from generation.diagram_render import render_initials_avatar
    tmp_path = Path(tempfile.gettempdir()) / f"avatar_{slug}.png"
    render_initials_avatar(name, tmp_path, bg_hex=settings.accent_colour,
                            font_family=settings.font_family)
    return tmp_path


def _add_about_company_page(doc, settings: TemplateSettings | None = None):
    """A dedicated "About the Company" page — profile, what-we-deliver
    grid, and leadership team. Content matches Source Soft Solutions' own
    real proposals verbatim (New Index/*.pdf, p.2) since this is their
    actual company profile, not placeholder text; falls back to a generic
    structure if `settings.organisation_name` has been changed away from
    Source Soft Solutions, since the real bios wouldn't apply to a
    different organisation."""
    s = settings or TemplateSettings()
    _add_shaded_heading(doc, "About the Company", s)
    is_sourcesoft = s.organisation_name.strip().lower() == "source soft solutions"

    if is_sourcesoft:
        _tight(doc.add_paragraph(
            "We at Source Soft Solutions provide AI, cloud, and data solutions to drive "
            "innovation and growth across industries. Our services focus on data "
            "modernization, analytics, and cloud infrastructure management, helping "
            "businesses unlock new possibilities with AI/ML, data insights, and scalable "
            "cloud technologies."
        ))
        tagline = doc.add_paragraph()
        _tight(tagline)
        tr = tagline.add_run("Empowering organizations to thrive in the digital landscape.")
        tr.bold = True
        tr.font.color.rgb = _hex_to_rgb(s.accent_colour)
        tr.font.name = s.font_family
        _tight(doc.add_paragraph(
            "Headquartered in Edison, New Jersey, with an office in Dubai and our primary "
            "engineering centre in Noida, India, we run long-term maintenance and support "
            "contracts on the same platforms we engineer."
        ))

        h2 = doc.add_paragraph()
        _tight(h2, 3)
        h2r = h2.add_run("What we deliver")
        h2r.bold = True
        h2r.font.size = Pt(s.body_font_size + 1)
        h2r.font.name = s.font_family
        # A 2-column grid, not one item per line — matches the real "What we
        # deliver" layout (New Index/*.pdf p.2) AND roughly halves the
        # vertical space 8 single-column bullet paragraphs used to take,
        # which is most of what was pushing the page to overflow.
        deliverables = ["Transformative Data Solutions", "Robust Cloud Services",
                         "Advanced AI Capabilities", "Insightful Analytics",
                         "Seamless Integration", "Custom Software Development",
                         "Data Security & Compliance", "Training & Support"]
        grid = doc.add_table(rows=len(deliverables) // 2, cols=2)
        grid.autofit = True
        for i in range(0, len(deliverables), 2):
            row = i // 2
            for col, item in enumerate(deliverables[i:i + 2]):
                cell = grid.cell(row, col)
                p = cell.paragraphs[0]
                _tight(p, 2)
                p.add_run(f"•  {item}").font.name = s.font_family
                _left_cell(cell)
        doc.add_paragraph()

        h3 = doc.add_paragraph()
        _tight(h3, 3)
        h3r = h3.add_run("Leadership team")
        h3r.bold = True
        h3r.font.size = Pt(s.body_font_size + 1)
        h3r.font.name = s.font_family
        leadership = [
            ("Alok Dharayan — President",
             "25+ years delivering engineering solutions to complex global problems. "
             "Masters, New Jersey Institute of Technology. Sets delivery governance and "
             "client accountability across Source Soft Solutions' enterprise and "
             "government engagements."),
            ("Vijay Konar — Chief Technology Officer",
             "Leads all product and platform engineering at Source Soft Solutions. Deep "
             "expertise in full-stack development, AWS cloud architecture and data "
             "engineering; owns technical standards, release controls and architecture "
             "reviews."),
            ("Vikram Sharma — Solutions Lead",
             "Architects client engagements end-to-end — from requirement study and "
             "solution design to transition-in and steady-state operations. Background "
             "in enterprise consulting and large-scale application maintenance "
             "programmes."),
        ]
        for name_title, bio in leadership:
            photo = _resolve_leadership_photo(name_title, s)
            # Photo + name/bio side by side in a borderless 2-column table —
            # same pattern as _add_letterhead's logo/name row. w:cantSplit +
            # w:keepNext on the row's paragraphs keep the whole card intact
            # across a page boundary (the plain-paragraph version before
            # this stranded "Vikram Sharma" as a heading alone at the
            # bottom of a page, with his bio isolated on the next).
            card = doc.add_table(rows=1, cols=2)
            card.autofit = False
            photo_cell, text_cell = card.cell(0, 0), card.cell(0, 1)
            photo_cell.width = Cm(2.0)
            text_cell.width = Cm(14.3)
            for cell in (photo_cell, text_cell):
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            pp = photo_cell.paragraphs[0]
            pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pp.add_run().add_picture(str(photo), width=Cm(1.7))
            np = text_cell.paragraphs[0]
            _set_left(np)
            _tight(np, 1)
            nr = np.add_run(name_title)
            nr.bold = True
            nr.font.name = s.font_family
            _tight(_set_left(text_cell.add_paragraph(bio)))
            _disable_row_split(card.rows[0])
            _keep_row_with_next(card.rows[0])
            doc.add_paragraph()
    else:
        # A different organisation's letterhead is in use — don't attribute
        # Source Soft Solutions' real leadership bios to someone else.
        doc.add_paragraph(f"{{{{ about_company }}}}")


def build_technical_proposal_template(settings: TemplateSettings | None = None):
    """Technical Proposal — modelled directly on Source Soft Solutions'
    own real proposals (New Index/*.pdf: CSIR Innovation Complex, v2,
    ICAR-NRCC and NIGST). Matches the real document's full 17-section
    skeleton (Executive Summary through Deliverables, Assumptions &
    Clarifications) — not just the front section — with client-specific
    real content (the "24 Incubation Labs Module", CICM's specific admin
    roles, etc.) generalised into an equivalent generic section every
    engagement needs (a core platform module, an admin CMS portal,
    security/hosting/compliance, and so on), rather than hardcoding
    CICM's specifics into a template every client will reuse.

    Most sections that were plain narrative paragraphs in the very first
    version of this template are now real tables or diagrams — matches an
    explicit user correction: "most of the things till now are in text
    not in tabular format... no wireframes" after comparing a generated
    draft against this exact reference PDF. Structured content (diagram
    layers/steps/phases, table rows, mockup image kind) is still driven by
    "Label: description" / "Field | Field | Field" lines the user provides
    or the model derives from the problem statement — never free
    narrative prose — for the same reliability reason as the original two
    diagrams: a table or diagram needs to know exactly how many
    rows/boxes there are and what goes in each, which prose can't
    guarantee."""
    s = settings or TemplateSettings()
    doc = Document()
    _set_body_font(doc, s)
    _add_page_border(doc, s)
    _add_running_header(doc, "TECHNICAL PROPOSAL — {{ proposal_no }}", s)

    cover_meta = [
        ("Proposal No.", "{{ proposal_no }}"),
        ("Date", "{{ proposal_date }}"),
        ("Client", "{{ client_name }}"),
        ("Project", "{{ project_title }}"),
    ]
    _add_cover_page(doc, s, "TECHNICAL PROPOSAL", cover_meta)
    _add_table_of_contents(doc, s)
    _add_about_company_page(doc, s)
    _add_section_break(doc)

    _add_letterhead(doc, s)
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run("TECHNICAL PROPOSAL")
    run.bold = True
    run.font.size = Pt(s.heading_font_size)
    run.font.name = s.font_family
    doc.add_paragraph()

    meta = doc.add_table(rows=len(cover_meta), cols=2)
    meta.style = "Light Grid Accent 1"
    for i, (label, value) in enumerate(cover_meta):
        meta.cell(i, 0).text = label
        meta.cell(i, 0).paragraphs[0].runs[0].bold = True
        meta.cell(i, 1).text = value
        _left_cell(meta.cell(i, 0))
        _left_cell(meta.cell(i, 1))
    doc.add_paragraph()

    sections = [
        ("1. Executive Summary", "{{ executive_summary }}"),
        ("2. Our Understanding of the Requirement", "{{ understanding }}"),
        ("3. Project Objectives", "{{ objectives }}"),
    ]
    for heading, value in sections:
        _add_shaded_heading(doc, heading, s)
        doc.add_paragraph(value)

    # [[ ]] not {{ }} deliberately, on every marker below — a literal
    # {{...}} here would be parsed by docxtpl's Jinja engine as a
    # (malformed) template tag and crash render(). render_document() finds
    # each marker by plain text search and swaps it for a real table/
    # diagram/image after rendering, so none of them may look like Jinja
    # syntax.
    _add_shaded_heading(doc, "4. Requirement to Solution Compliance Matrix", s)
    doc.add_paragraph("{{ compliance_summary }}")
    doc.add_paragraph("[[COMPLIANCE_MATRIX]]")  # replaced by render_document()

    _add_shaded_heading(doc, "5. Information Architecture", s)
    doc.add_paragraph("{{ information_architecture }}")
    doc.add_paragraph("[[SITEMAP_DIAGRAM]]")  # replaced by render_document()

    _add_shaded_heading(doc, "6. Solution & Technology Architecture", s)
    doc.add_paragraph("{{ architecture_intro }}")
    doc.add_paragraph("[[ARCHITECTURE_DIAGRAM]]")  # replaced by render_document()

    _add_shaded_heading(doc, "7. Data Flow Diagram", s)
    doc.add_paragraph("{{ data_flow_intro }}")
    doc.add_paragraph("[[DATA_FLOW_DIAGRAM]]")  # replaced by render_document()

    _add_shaded_heading(doc, "8. Public Website — Modules & Features", s)
    doc.add_paragraph("{{ modules_intro }}")
    doc.add_paragraph("[[MODULES_TABLE]]")  # replaced by render_document()

    _add_shaded_heading(doc, "9. Core Platform Module", s)
    doc.add_paragraph("{{ core_module_intro }}")
    doc.add_paragraph("[[CORE_MODULE_FLOW]]")  # replaced by render_document()

    _add_shaded_heading(doc, "10. Admin CMS Portal", s)
    doc.add_paragraph("{{ admin_portal_intro }}")
    doc.add_paragraph("[[ADMIN_FEATURE_GRID]]")  # replaced by render_document()
    admin_roles_heading = doc.add_paragraph()
    _tight(admin_roles_heading, 3)
    arh = admin_roles_heading.add_run("Roles")
    arh.bold = True
    arh.font.size = Pt(s.body_font_size + 1)
    arh.font.name = s.font_family
    doc.add_paragraph("[[ADMIN_ROLES_TABLE]]")  # replaced by render_document()

    _add_shaded_heading(doc, "11. Enquiry & Notification Handling", s)
    doc.add_paragraph("{{ enquiry_intro }}")
    doc.add_paragraph("[[ENQUIRY_TABLE]]")  # replaced by render_document()

    _add_shaded_heading(doc, "12. Security, Hosting & Compliance", s)
    doc.add_paragraph("{{ security_intro }}")
    doc.add_paragraph("[[SECURITY_FLOW]]")  # replaced by render_document()
    doc.add_paragraph("[[SECURITY_TABLE]]")  # replaced by render_document()

    _add_shaded_heading(doc, "13. Multilingual, SEO & Performance", s)
    doc.add_paragraph("{{ seo_intro }}")
    doc.add_paragraph("[[SEO_TABLE]]")  # replaced by render_document()

    _add_shaded_heading(doc, "14. UI Design Concepts & Mock Screens", s)
    doc.add_paragraph(
        "The concepts below illustrate the shape and structure of the public "
        "site and the admin CMS — page layout, navigation and information "
        "density — not final visual design. Final screens are confirmed with "
        "{{ client_name }} in the discovery and design phase."
    )
    doc.add_paragraph("[[UI_MOCKUP_HOME]]")  # replaced by render_document()
    doc.add_paragraph()
    doc.add_paragraph("[[UI_MOCKUP_ADMIN]]")  # replaced by render_document()

    _add_shaded_heading(doc, "15. Implementation Methodology & Timeline", s)
    doc.add_paragraph("{{ methodology }}")
    doc.add_paragraph("[[TIMELINE_DIAGRAM]]")  # replaced by render_document()

    _add_shaded_heading(doc, "16. Annual Maintenance & Support", s)
    doc.add_paragraph("{{ amc_intro }}")
    doc.add_paragraph("[[AMC_TABLE]]")  # replaced by render_document()

    _add_shaded_heading(doc, "17. Deliverables, Assumptions & Clarifications", s)
    doc.add_paragraph("{{ deliverables }}")

    doc.add_paragraph()
    doc.add_paragraph()
    mark = _resolve_logo_mark(s)
    if mark:
        mark_para = doc.add_paragraph()
        mark_para.add_run().add_picture(str(mark), width=Cm(s.logo_mark_width_cm))
    _set_left(doc.add_paragraph(f"For {{{{ submitted_by }}}}"))
    doc.add_paragraph()
    _set_left(doc.add_paragraph(_signature_lines("{{ signatory_name }}", "{{ signatory_designation }}")))

    _add_technical_proposal_footer(doc, "{{ client_name }}", s)

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / "technical_proposal_template.docx"
    doc.save(out_path)
    print(f"Built {out_path}")


# Data-driven recipes for the remaining 10 templates — field placeholders
# here MUST match the context keys generation/drafting.py's specs produce
# (either passed straight through from DraftSession.answers, or the
# `output_field` name of a NarrativeField for AI-expanded sections).
REMAINING_TEMPLATES = [
    dict(
        filename="work_order_goods_template.docx", title="WORK ORDER — GOODS / SUPPLY",
        metadata_rows=[("Work Order No.", "{{ work_order_no }}"), ("Date", "{{ work_order_date }}"),
                        ("Supplier", "{{ supplier_name }}"), ("Supplier Address", "{{ supplier_address }}")],
        sections=[("Item Description", "{{ item_description }}"),
                  ("Quantity & Value", "{{ quantity_and_value }}"),
                  ("Delivery", "Delivery date: {{ delivery_date }}\nDelivery location: {{ delivery_location }}"),
                  ("Warranty Terms", "{{ warranty_terms }}")],
        signatories=[("{{ issuing_organisation }}", "{{ authorized_signatory_name }}", "{{ authorized_signatory_designation }}")],
        acceptance_party_field="{{ supplier_name }}",
    ),
    dict(
        filename="work_order_amc_template.docx", title="ANNUAL MAINTENANCE CONTRACT (AMC)",
        metadata_rows=[("AMC No.", "{{ amc_no }}"), ("Date", "{{ amc_date }}"),
                        ("Vendor", "{{ vendor_name }}"), ("Vendor Address", "{{ vendor_address }}")],
        sections=[("Equipment Covered", "{{ equipment_covered }}"),
                  ("AMC Period & Service Frequency", "AMC period: {{ amc_period }}\nService frequency: {{ service_frequency }}"),
                  ("Response Time SLA", "{{ response_time_sla }}"),
                  ("AMC Value", "{{ amc_value }}")],
        signatories=[("{{ issuing_organisation }}", "{{ authorized_signatory_name }}", "{{ authorized_signatory_designation }}")],
        acceptance_party_field="{{ vendor_name }}",
    ),
    dict(
        filename="mou_international_template.docx", title="MEMORANDUM OF UNDERSTANDING (INTERNATIONAL)",
        metadata_rows=[("MoU No.", "{{ mou_no }}"), ("Date", "{{ mou_date }}"),
                        ("Between", "{{ indian_party_name }} and {{ foreign_party_name }}"),
                        ("Foreign Party Country", "{{ foreign_party_country }}")],
        sections=[("Purpose", "{{ purpose }}"), ("Areas of Cooperation", "{{ areas_of_cooperation }}"),
                  ("Duration", "{{ duration }}")],
        signatories=[("{{ indian_party_name }}", "{{ signatory_indian_name }}", "{{ signatory_indian_designation }}"),
                     ("{{ foreign_party_name }}", "{{ signatory_foreign_name }}", "{{ signatory_foreign_designation }}")],
        include_witnesses=True,
    ),
    dict(
        filename="mou_interdept_template.docx", title="MEMORANDUM OF UNDERSTANDING (INTER-DEPARTMENTAL)",
        metadata_rows=[("MoU No.", "{{ mou_no }}"), ("Date", "{{ mou_date }}"),
                        ("Between", "{{ department_a_name }} and {{ department_b_name }}")],
        sections=[("Subject Matter", "{{ subject_matter }}"), ("Responsibilities", "{{ responsibilities }}"),
                  ("Review Period", "{{ review_period }}")],
        signatories=[("{{ department_a_name }}", "{{ signatory_a_name }}", "{{ signatory_a_designation }}"),
                     ("{{ department_b_name }}", "{{ signatory_b_name }}", "{{ signatory_b_designation }}")],
        include_witnesses=True,
    ),
    dict(
        filename="agreement_service_template.docx", title="SERVICE AGREEMENT",
        metadata_rows=[("Agreement No.", "{{ agreement_no }}"), ("Date", "{{ agreement_date }}"),
                        ("Client", "{{ client_name }}"), ("Provider", "{{ provider_name }}, {{ provider_address }}")],
        sections=[("Service Description", "{{ service_description }}"), ("SLA / Performance Terms", "{{ sla_terms }}"),
                  ("Contract Value & Duration", "Value: {{ contract_value }}\nDuration: {{ contract_duration }}"),
                  ("Termination Notice Period", "{{ termination_notice_period }}")],
        signatories=[("{{ provider_name }}", "{{ signatory_provider_name }}", "{{ signatory_provider_designation }}"),
                     ("{{ client_name }}", "{{ signatory_client_name }}", "{{ signatory_client_designation }}")],
    ),
    dict(
        filename="agreement_consultancy_template2.docx", title="CONSULTANCY AGREEMENT",
        metadata_rows=[("Agreement No.", "{{ agreement_no }}"), ("Date", "{{ agreement_date }}"),
                        ("Client", "{{ client_name }}"), ("Consultant", "{{ consultant_name }}, {{ consultant_address }}")],
        sections=[("Consultancy Scope", "{{ consultancy_scope }}"), ("Deliverables", "{{ deliverables }}"),
                  ("Fee Structure & Engagement Period", "Fee: {{ fee_structure }}\nPeriod: {{ engagement_period }}")],
        signatories=[("{{ consultant_name }}", "{{ signatory_consultant_name }}", "{{ signatory_consultant_designation }}"),
                     ("{{ client_name }}", "{{ signatory_client_name }}", "{{ signatory_client_designation }}")],
    ),
    dict(
        filename="agreement_licensing_template.docx", title="LICENSING AGREEMENT",
        metadata_rows=[("Agreement No.", "{{ agreement_no }}"), ("Date", "{{ agreement_date }}"),
                        ("Licensor", "{{ licensor_name }}"), ("Licensee", "{{ licensee_name }}, {{ licensee_address }}")],
        sections=[("Licensed IP / Materials", "{{ ip_description }}"),
                  ("Usage Terms & Restrictions", "{{ usage_terms }}"),
                  ("Royalty Terms & Duration", "Royalty: {{ royalty_terms }}\nDuration: {{ license_duration }}")],
        signatories=[("{{ licensor_name }}", "{{ signatory_licensor_name }}", "{{ signatory_licensor_designation }}"),
                     ("{{ licensee_name }}", "{{ signatory_licensee_name }}", "{{ signatory_licensee_designation }}")],
    ),
    dict(
        filename="proposal_technical_template.docx", title="TECHNICAL PROPOSAL",
        metadata_rows=[("Proposal No.", "{{ proposal_no }}"), ("Date", "{{ proposal_date }}"),
                        ("Submitted By", "{{ submitted_by }}"), ("Submitted To", "{{ submitted_to }}")],
        sections=[("Project Title", "{{ project_title }}"), ("Technical Approach", "{{ technical_approach }}"),
                  ("Team Composition", "{{ team_composition }}"),
                  ("Implementation Timeline", "{{ implementation_timeline }}")],
        signatories=[("{{ submitted_by }}", "{{ signatory_name }}", "{{ signatory_designation }}")],
    ),
    dict(
        filename="proposal_financial_template.docx", title="FINANCIAL PROPOSAL",
        metadata_rows=[("Proposal No.", "{{ proposal_no }}"), ("Date", "{{ proposal_date }}"),
                        ("Submitted By", "{{ submitted_by }}"), ("Submitted To", "{{ submitted_to }}")],
        sections=[("Project Title", "{{ project_title }}"), ("Cost Breakdown", "{{ cost_breakdown }}"),
                  ("Payment Schedule", "{{ payment_schedule }}"),
                  ("Total Value & Validity", "Total: {{ total_value }}\nValidity: {{ validity_period }}")],
        signatories=[("{{ submitted_by }}", "{{ signatory_name }}", "{{ signatory_designation }}")],
    ),
    dict(
        filename="proposal_combined_template.docx", title="TECHNICAL & FINANCIAL PROPOSAL",
        metadata_rows=[("Proposal No.", "{{ proposal_no }}"), ("Date", "{{ proposal_date }}"),
                        ("Submitted By", "{{ submitted_by }}"), ("Submitted To", "{{ submitted_to }}")],
        sections=[("Project Title", "{{ project_title }}"), ("Executive Summary", "{{ executive_summary }}"),
                  ("Approach & Cost Basis", "{{ approach_and_cost }}"),
                  ("Total Value & Timeline", "Total: {{ total_value }}\nTimeline: {{ implementation_timeline }}")],
        signatories=[("{{ submitted_by }}", "{{ signatory_name }}", "{{ signatory_designation }}")],
    ),
]


if __name__ == "__main__":
    build_work_order_template()
    build_mou_template()
    build_technical_proposal_template()
    for recipe in REMAINING_TEMPLATES:
        build_generic_template(**recipe)
