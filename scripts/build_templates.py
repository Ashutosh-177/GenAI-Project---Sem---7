"""One-time generator for the .docx template files docxtpl fills in.
Templates are real Word documents with Jinja placeholders ({{ field }}) as
run text — this script builds that starting file programmatically so it's
version-controlled as code, not a binary someone hand-edited in Word once
and can't reproduce."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "generation" / "templates"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_FULL = ASSETS_DIR / "qci_logo_0.jpeg"   # full lockup: mark + Hindi/English wordmark + tagline
LOGO_MARK = ASSETS_DIR / "qci_logo_1.jpeg"   # compact mark, for the signature block


def _add_bottom_rule(paragraph):
    """A real paragraph border, not literal underscore characters — the
    underscore approach wraps unpredictably at 95 chars and looks broken
    in Word (confirmed visually: it split onto two ragged lines)."""
    p_pr = paragraph._p.get_or_add_pPr()
    p_borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), "1B6E75")
    p_borders.append(bottom)
    p_pr.append(p_borders)


def _set_body_font(doc):
    """Calibri, matching QCI's own RFP (QCI.pdf / "QCI Sample.pdf") exactly
    — a direct, explicit user instruction after seeing that reference
    document: match QCI's own house visual identity (Calibri, page border,
    running header, coloured section bars — see _add_page_border,
    _add_running_header, _add_shaded_heading below), not the generic
    "signed legal instrument" convention (Times New Roman, plain black
    headings) an earlier pass derived from other samples. Superseded, not
    layered on top of, that earlier choice. Justified, matching the RFP's
    own body text — set on the style rather than per-paragraph so it
    applies everywhere automatically; paragraphs that need centering
    (titles, the letterhead, the footer) already set their own alignment
    explicitly, which overrides this default."""
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def _add_page_border(doc):
    """A single black rectangular border around every page — extracted
    directly from QCI's own RFP PDF (pymupdf's get_drawings() on "QCI
    Sample.pdf": four black-fill rectangles forming a frame at the page
    margins). Word represents this as a section-level w:pgBorders element,
    not a drawn shape."""
    sectPr = doc.sections[0]._sectPr
    pg_borders = OxmlElement("w:pgBorders")
    pg_borders.set(qn("w:offsetFrom"), "page")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "24")
        el.set(qn("w:color"), "000000")
        pg_borders.append(el)
    sectPr.append(pg_borders)


def _add_running_header(doc, header_text: str):
    """A repeating italic header on every page, matching QCI's own RFP —
    which repeats its full tender title on every single page, not just
    page 1. Our documents don't have a long fixed title to repeat, so this
    uses "[DOC TYPE] — [REFERENCE NO.]" instead, the equivalent
    page-identifying information for a short instrument. Previously the
    QCI letterhead/logo only ever appeared once, in the body flow at the
    top of page 1 — pages 2+ had nothing above the body text at all."""
    header = doc.sections[0].header
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(header_text)
    run.italic = True
    run.font.size = Pt(10)


# Exact colours read off QCI's own RFP via pymupdf's get_drawings() (page
# 5's section/subsection heading bars) rather than eyeballed from the
# screenshot — RGB(0.122, 0.220, 0.392) and RGB(0.851, 0.851, 0.851).
_HEADING_BAR_FILL = "1F3864"
_HEADING_BAR_TEXT = "FFFFFF"


def _add_shaded_heading(doc, text: str):
    """Section headings as a dark-navy filled bar with white bold text —
    replaces the earlier plain "bold black text" heading style, which read
    as a generic Word document rather than QCI's own report convention.
    Paragraph shading (w:shd), not a table cell, since it's simpler and
    resizes with the text automatically."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(6)
    p_pr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), _HEADING_BAR_FILL)
    p_pr.append(shd)
    run = p.add_run(text)
    run.bold = True
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return p


def _add_letterhead(doc):
    """Real QCI letterhead, extracted directly from their own tender PDF
    (QCI.pdf, page 1). Logo width was Cm(12) — measured against QCI's own
    PDF, that size is what QCI reserves for a dedicated, mostly-blank cover
    page; our documents are dense 1-2 page instruments with content
    starting right below the header (like the GeM SLA sample, which uses a
    compact top-left icon, not a full-width banner), so a full-width lockup
    at that size crowds everything under it. Shrunk to Cm(5), which keeps
    the wordmark legible while leaving the header proportionate to a short
    working document rather than a cover sheet."""
    if LOGO_FULL.exists():
        logo_para = doc.add_paragraph()
        logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        logo_para.add_run().add_picture(str(LOGO_FULL), width=Cm(5))

    addr = doc.add_paragraph()
    addr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    addr_run = addr.add_run("Tower J-200, World Trade Center, Nauroji Nagar, New Delhi – 110029")
    addr_run.font.size = Pt(9)
    addr_run.italic = True

    rule = doc.add_paragraph()
    _add_bottom_rule(rule)
    doc.add_paragraph()


def _signature_lines(name_ph: str, desig_ph: str) -> str:
    """Labeled "Name:"/"Designation:" lines rather than bare placeholder
    text — matches both real samples (LetsVenture Agreement uses "Name:"/
    "Title:"/"Date:"; NPC-KPMG MoU labels the role under the signature)."""
    return f"Name: {name_ph}\nDesignation: {desig_ph}"


def _set_left(paragraph):
    """Word only skips justifying a paragraph's *last* line — a short
    two-line label (e.g. "Name: X\\nDesignation: Y") or a table cell narrow
    enough to wrap still gets its non-final line's word-spacing stretched
    to fill the width, which is exactly what the global JUSTIFY default
    (`_set_body_font`) does to every signature/metadata/witness cell: short
    label text stretched into "Name:      Anjali      Verma" across a
    table column. Explicitly forcing LEFT on every non-prose paragraph
    (table cells, signature-block lines) opts them out, leaving JUSTIFY to
    apply only where it was intended — genuine long-form narrative
    paragraphs (scope of work, terms & conditions, background, etc.) that
    wrap because they're actually long, not because of an embedded line
    break in short label text."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    return paragraph


def _left_cell(cell):
    """Same fix as `_set_left`, applied to a table cell's paragraph(s) —
    table columns are narrow, so even ordinary short cell text (e.g. "FOR
    AND ON BEHALF OF Quality Council of India") wraps and gets stretched
    under the JUSTIFY default unless explicitly opted out."""
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


def _add_footer(doc, ref_field: str):
    """A real Word footer (doc.sections[0].footer), repeating on every page
    — what was here before was a body paragraph placed after the last
    section, which only ever showed up once, at the bottom of the last
    page. QCI's own RFP (QCI.pdf) has "Page X of Y" in the footer of every
    single page; matched that exactly, using live PAGE/NUMPAGES fields
    rather than a hardcoded "Page 1" that would be wrong on page 2.

    Leads with the document's own reference number (`ref_field` — e.g.
    "{{ work_order_no }}"), not generic "Generated by..." branding: these
    are legal instruments that get printed and physically handled, and a
    real formal document repeats its own reference number on every page so
    a loose page can be traced back to the right file. Keeps the version
    stamp (useful across v1/v2/v3 redrafts) but drops the AI-tool branding
    line, which said nothing about *this* document."""
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p.add_run(f"Ref: {ref_field}  |  Version {{{{ version }}}}  |  Page ")
    r1.font.size = Pt(8)
    r1.italic = True
    page_run = _add_field_run(p, "PAGE")
    page_run.font.size = Pt(8)
    page_run.italic = True
    r2 = p.add_run(" of ")
    r2.font.size = Pt(8)
    r2.italic = True
    numpages_run = _add_field_run(p, "NUMPAGES")
    numpages_run.font.size = Pt(8)
    numpages_run.italic = True


def _add_issuer_acceptance_block(doc, issuer_ph: str, name_ph: str, desig_ph: str, acceptance_party_ph: str):
    """Work Orders are legally unilateral instruments — per the GFR-based
    procurement manual in our own sample corpus
    (tender_model_document_goods.pdf, p.65), a Work Order is binding once
    "accepted/acted upon by the contractor," not by a co-signed bilateral
    agreement. That's why only the issuing authority signs. But real
    practice still records the contractor's acknowledgment as a paper
    trail, so this adds a second, clearly-secondary block: the issuer's
    real signatory (collected from the user) on the left, and a blank
    "Received & Accepted by" acknowledgment line for the contractor's own
    representative on the right — the contractor's specific signer isn't
    collected at drafting time (only their organisation name is), so that
    side is left blank for them to fill by hand, same as a real acceptance
    slip."""
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
    """MoUs specifically get a witness section — confirmed against a real
    signed government MoU (NPC/KPMG sample), which has two numbered witness
    lines under EACH party's signature block. Names are handwritten at
    signing, not system-filled, so these are blank numbered lines, not
    Jinja placeholders. Work Orders/Agreements/Proposals don't carry this:
    the one real non-MoU legal template in the samples (LetsVenture
    Consultancy Agreement) signs off with no witnesses at all."""
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


def build_work_order_template():
    doc = Document()
    _set_body_font(doc)
    _add_page_border(doc)
    _add_running_header(doc, "WORK ORDER — {{ work_order_no }}")
    _add_letterhead(doc)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("WORK ORDER")
    run.bold = True
    run.font.size = Pt(16)

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
    _add_shaded_heading(doc, "1. Project / Work Title")
    doc.add_paragraph("{{ project_title }}")

    _add_shaded_heading(doc, "2. Scope of Work")
    doc.add_paragraph("{{ scope_of_work }}")

    _add_shaded_heading(doc, "3. Contract Value")
    doc.add_paragraph("{{ contract_value }}")

    _add_shaded_heading(doc, "4. Schedule")
    doc.add_paragraph("Start date: {{ start_date }}")
    doc.add_paragraph("Completion period: {{ completion_period }}")

    _add_shaded_heading(doc, "5. Payment Terms")
    doc.add_paragraph("{{ payment_terms }}")

    _add_shaded_heading(doc, "6. Terms & Conditions")
    # Unlike scope_of_work (a flowing paragraph), this field is explicitly
    # prompted for numbered clauses (_draft_terms_and_conditions_text) —
    # its rendered value is one Word paragraph with the clause headers and
    # bodies separated by soft line breaks, not real paragraph breaks. That
    # makes short header lines ("1. Quality and Compliance Expectations")
    # non-final within the paragraph, so the JUSTIFY default stretched
    # their word-spacing across the full width (caught by the user from a
    # live render). Left-aligned instead, appropriately for a clause list.
    _set_left(doc.add_paragraph("{{ terms_and_conditions }}"))

    doc.add_paragraph()
    doc.add_paragraph()
    if LOGO_MARK.exists():
        mark_para = doc.add_paragraph()
        mark_para.add_run().add_picture(str(LOGO_MARK), width=Cm(1.6))
    _add_issuer_acceptance_block(doc, "{{ issuing_organisation }}", "{{ authorized_signatory_name }}",
                                  "{{ authorized_signatory_designation }}", "{{ contractor_name }}")

    _add_footer(doc, "{{ work_order_no }}")

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / "work_order_template.docx"
    doc.save(out_path)
    print(f"Built {out_path}")


def build_mou_template():
    """Second template — proves the Work Order pattern generalizes rather
    than being a one-off build. Same letterhead helper, same structural
    shape (metadata table, numbered sections, AI-expanded narrative
    sections, signature block with the compact mark), different fields."""
    doc = Document()
    _set_body_font(doc)
    _add_page_border(doc)
    _add_running_header(doc, "MEMORANDUM OF UNDERSTANDING — {{ mou_no }}")
    _add_letterhead(doc)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("MEMORANDUM OF UNDERSTANDING")
    run.bold = True
    run.font.size = Pt(16)

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
    _add_shaded_heading(doc, "1. Title / Purpose")
    doc.add_paragraph("{{ mou_title }}")

    _add_shaded_heading(doc, "2. Background")
    doc.add_paragraph("{{ background }}")

    _add_shaded_heading(doc, "3. Objectives")
    doc.add_paragraph("{{ objectives }}")

    _add_shaded_heading(doc, "4. Second Party Address")
    doc.add_paragraph("{{ party_b_address }}")

    _add_shaded_heading(doc, "5. Duration")
    doc.add_paragraph("{{ duration }}")

    doc.add_paragraph()
    doc.add_paragraph()
    if LOGO_MARK.exists():
        mark_para = doc.add_paragraph()
        mark_para.add_run().add_picture(str(LOGO_MARK), width=Cm(1.6))

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

    _add_footer(doc, "{{ mou_no }}")

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / "mou_template.docx"
    doc.save(out_path)
    print(f"Built {out_path}")


def build_generic_template(filename: str, title: str, metadata_rows: list,
                            sections: list, signatories: list, include_witnesses: bool = False,
                            acceptance_party_field: str = None):
    """Generic builder for the remaining 10 templates — same letterhead,
    same metadata-table/numbered-sections/signature-block shape as Work
    Order and MoU, just parameterized instead of hand-written per document
    type. `signatories` is a list of (label, name_placeholder,
    designation_placeholder) — one entry for a single-party sign-off, two
    for a dual-party one (MoU/Agreement-style). `include_witnesses` is only
    set for the MoU recipes — see `_add_witness_block`. `acceptance_party_field`
    is only set for the Goods/AMC Work Order recipes — see
    `_add_issuer_acceptance_block`; Proposals stay single-signatory since a
    proposal is submitted unilaterally, with no counterparty to acknowledge
    receipt at drafting time."""
    doc = Document()
    _set_body_font(doc)
    _add_page_border(doc)
    # Every recipe's first metadata row is that document's own reference
    # number — reused for the running header too, same as the footer below.
    _add_running_header(doc, f"{title} — {metadata_rows[0][1]}")
    _add_letterhead(doc)

    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
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
        _add_shaded_heading(doc, f"{i}. {heading}")
        body = doc.add_paragraph(value)
        if "\n" in value:
            # Short combo field-pairs (e.g. "Delivery date: X\nDelivery
            # location: Y"), not real flowing prose — the embedded break
            # makes the first line non-final, so it'd get JUSTIFY-stretched
            # otherwise. Genuine narrative fields (scope/T&C/background
            # etc.) have no embedded break and are left on the JUSTIFY
            # default, which is what we actually want for those.
            _set_left(body)

    doc.add_paragraph()
    doc.add_paragraph()
    if LOGO_MARK.exists():
        mark_para = doc.add_paragraph()
        mark_para.add_run().add_picture(str(LOGO_MARK), width=Cm(1.6))

    if len(signatories) == 1 and acceptance_party_field:
        label, name_ph, desig_ph = signatories[0]
        _add_issuer_acceptance_block(doc, label, name_ph, desig_ph, acceptance_party_field)
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

    # Every recipe's first metadata row is that document's own reference
    # number (Work Order No. / MoU No. / Agreement No. / Proposal No.) —
    # reused here rather than adding a separate ref_field parameter per
    # recipe, since it'd otherwise just duplicate metadata_rows[0].
    _add_footer(doc, metadata_rows[0][1])

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / filename
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
    for recipe in REMAINING_TEMPLATES:
        build_generic_template(**recipe)
