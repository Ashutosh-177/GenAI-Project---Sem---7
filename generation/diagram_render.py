"""Renders architecture / data-flow / timeline diagrams and leadership
avatars as PNG images via matplotlib, for embedding into generated .docx
files as pictures (`paragraph.add_run().add_picture(...)`).

Word tables (the original approach — see build_templates.py history in
Memory.md) can't produce real boxes-and-arrows diagrams: no true borders
per box, no arrowheads, no reliable multi-line wrapping. Rendering to a
raster image gives pixel-level control to match the polish of Source Soft
Solutions' own reference proposals (New Index/*.pdf).

All layout is done in "inches as data units" — each render function builds
a matplotlib Axes sized exactly to its figure (`fig.add_axes([0,0,1,1])`,
`xlim=(0, fig_w)`, `ylim=(0, fig_h)`) so 1 data unit = 1 inch and box
placement math is directly in the units the figure is saved at. That
keeps the saved PNG's aspect ratio exact, since callers embed by width
only (`add_picture(path, width=Cm(...))`) and let python-docx derive
height from the image's own aspect ratio.
"""
from __future__ import annotations

import colorsys
import textwrap
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Circle, Rectangle
from matplotlib.font_manager import FontProperties

_BODY_FILL = "F5F7FA"
_BORDER = "D0D5DD"
_TEXT_DARK = "1A1A1A"


def _hex(h: str) -> str:
    h = h.lstrip("#")
    return f"#{h}"


def _derive_palette(accent_hex: str, n: int = 5) -> list[str]:
    """A small set of coordinated colours derived from `accent_hex` instead
    of the fixed literal palette this used to be — a real user reported
    "light mode and dark mode is not working properly", and the actual bug
    was every diagram/mockup card colour being hardcoded to the same navy/
    red/green regardless of which preset was active. A Dark Mode render's
    section headings correctly turned near-black with a bright-blue
    accent, but the sitemap's pillar headers and the flow diagram's boxes
    stayed the old default navy — visually unrelated to the rest of the
    page.

    Monochromatic by design — same hue as `accent_hex`, only lightness
    varied — rather than rotating hue: a first version that also shifted
    hue produced neon, off-brand-looking swatches (bright cyan, magenta)
    for saturated accents like Dark Mode's blue, since a wide hue rotation
    at high saturation has no guarantee of landing somewhere that still
    reads as "part of the same colour family." Varying only lightness
    guarantees every swatch is visibly a shade of the SAME colour as the
    rest of the theme, which is what "belongs to this preset" actually
    means visually."""
    r, g, b = (int(accent_hex.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    base_l = min(max(l, 0.22), 0.40)  # anchor away from extremes so every shift stays legible
    light_shifts = [0.0, -0.08, 0.07, -0.14, 0.13][:n]
    palette = []
    for dl in light_shifts:
        nl = min(max(base_l + dl, 0.16), 0.50)  # keep dark enough for reliable white text contrast
        nr, ng, nb = colorsys.hls_to_rgb(h, nl, s)
        palette.append("".join(f"{max(0, min(255, round(c * 255))):02X}" for c in (nr, ng, nb)))
    return palette


def _wrap(text: str, box_w_in: float, fontsize: float) -> list[str]:
    """Wrap to fit `box_w_in`, but NEVER split a word mid-word.

    `break_long_words=False` matters: with the default True, a narrow
    column shreds real words across lines — a real 6-pillar sitemap
    rendered "Highlights" as "Highlight/s", "Administration" as
    "About & Ad/ministrati/on" and "Resolution" as "Resolutio/n". A word
    that overflows its column slightly looks fine; a word chopped in half
    looks broken. `break_on_hyphens=False` likewise keeps hyphenated terms
    ("Ward-wise", "role-based") intact."""
    chars_per_in = 15.5 * (9.0 / fontsize)
    width = max(int(box_w_in * chars_per_in), 8)
    return textwrap.wrap(text, width=width,
                          break_long_words=False, break_on_hyphens=False) or [""]


def _fig(width_in: float, height_in: float, dpi: int = 200):
    fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, width_in)
    ax.set_ylim(0, height_in)
    ax.axis("off")
    ax.invert_yaxis()  # (0,0) at top-left, y grows downward — matches reading order
    return fig, ax


def _rounded_box(ax, x, y, w, h, *, fill=_BODY_FILL, edge=_BORDER, lw=1.0):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.06",
        linewidth=lw, edgecolor=_hex(edge), facecolor=_hex(fill),
        mutation_aspect=1,
    )
    ax.add_patch(box)
    return box


def _left_bar(ax, x, y, h, colour, bar_w=0.09):
    ax.add_patch(FancyBboxPatch(
        (x, y), bar_w, h,
        boxstyle="round,pad=0,rounding_size=0.04",
        linewidth=0, facecolor=_hex(colour),
    ))


def _down_arrow(ax, x, y1, y2, colour=_BORDER):
    ax.add_patch(FancyArrowPatch(
        (x, y1), (x, y2),
        arrowstyle="-|>", mutation_scale=14,
        linewidth=1.4, color=_hex(colour), shrinkA=0, shrinkB=0,
    ))


def _right_arrow(ax, x1, x2, y, colour=_BORDER):
    ax.add_patch(FancyArrowPatch(
        (x1, y), (x2, y),
        arrowstyle="-|>", mutation_scale=14,
        linewidth=1.4, color=_hex(colour), shrinkA=0, shrinkB=0,
    ))


def _diagonal_arrow(ax, x1, y1, x2, y2, colour=_BORDER):
    """Straight connector between two arbitrary points (e.g. bottom of the
    last box in a row to the top of the first box in the next row) — used
    instead of a right-angle elbow, since matplotlib's "angle" connection
    style needs a `rad` tuned to the same units as the coordinates and is
    easy to get wrong at inch-scale (a mis-set rad silently produces a
    degenerate path that renders in the wrong place)."""
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=12,
        linewidth=1.2, color=_hex(colour), shrinkA=0, shrinkB=0,
    ))


# ═══════════════════════════════════════════════════════════════════════
# Layered architecture diagram — vertical stack of "left-accent" cards
# ═══════════════════════════════════════════════════════════════════════

def render_architecture_diagram(layers: list[tuple[str, str]], out_path: str | Path,
                                 accent_hex: str = "1F4E78",
                                 font_family: str = "Calibri") -> Path:
    """layers: list of (layer_name, description). Renders a vertical stack
    of cards, each with a coloured accent bar, bold label and wrapped
    description, connected by downward arrows."""
    out_path = Path(out_path)
    if not layers:
        raise ValueError("render_architecture_diagram: no layers given")

    fig_w = 7.4
    label_fs, desc_fs = 11.5, 9.5
    pad_x, pad_top = 0.22, 0.12
    line_h = 0.185
    box_w = fig_w - 0.5

    wrapped = []
    for label, desc in layers:
        lines = _wrap(desc, box_w - 2 * pad_x, desc_fs)
        body_h = pad_top + 0.24 + len(lines) * line_h + 0.14
        wrapped.append((label, lines, body_h))

    gap = 0.30
    margin = 0.25
    fig_h = margin * 2 + sum(h for _, _, h in wrapped) + gap * (len(wrapped) - 1)

    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    fp_label = FontProperties(family=font_family, weight="bold")
    fp_desc = FontProperties(family=font_family)

    fig, ax = _fig(fig_w, fig_h)
    palette = _derive_palette(accent_hex)
    y = margin
    x = 0.25
    for i, (label, lines, body_h) in enumerate(wrapped):
        colour = palette[i % len(palette)]
        _rounded_box(ax, x, y, box_w, body_h)
        _left_bar(ax, x, y, body_h, colour)
        ax.text(x + pad_x + 0.06, y + pad_top + 0.12, label,
                 fontsize=label_fs, color=_hex(colour), fontproperties=fp_label,
                 ha="left", va="top")
        ty = y + pad_top + 0.24 + 0.10
        for line in lines:
            ax.text(x + pad_x + 0.06, ty, line, fontsize=desc_fs,
                     color=_hex(_TEXT_DARK), fontproperties=fp_desc, ha="left", va="top")
            ty += line_h
        if i < len(wrapped) - 1:
            cx = x + box_w / 2
            _down_arrow(ax, cx, y + body_h, y + body_h + gap, colour=accent_hex)
        y += body_h + gap

    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# Flow / process diagram — horizontal chain of numbered cards, wraps rows
# ═══════════════════════════════════════════════════════════════════════

def render_flow_diagram(steps: list[str], out_path: str | Path,
                         accent_hex: str = "1F4E78",
                         font_family: str = "Calibri", cols_per_row: int = 3) -> Path:
    out_path = Path(out_path)
    if not steps:
        raise ValueError("render_flow_diagram: no steps given")

    fig_w = 7.4
    n = len(steps)
    nrows = (n + cols_per_row - 1) // cols_per_row
    box_w = 1.95
    box_h = 1.05
    gap_x = 0.55
    row_gap = 0.55
    margin = 0.25

    total_row_w = cols_per_row * box_w + (cols_per_row - 1) * gap_x
    x_start = (fig_w - total_row_w) / 2
    fig_h = margin * 2 + nrows * box_h + (nrows - 1) * row_gap

    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    fp_label = FontProperties(family=font_family, weight="bold")

    fig, ax = _fig(fig_w, fig_h)

    centers = []
    for i, step in enumerate(steps):
        row, col = divmod(i, cols_per_row)
        colour = accent_hex
        x = x_start + col * (box_w + gap_x)
        y = margin + row * (box_h + row_gap)
        _rounded_box(ax, x, y, box_w, box_h, fill=colour, edge=colour)
        lines = _wrap(step, box_w - 0.3, 9.5)
        ty = y + box_h / 2 - (len(lines) - 1) * 0.11
        ax.text(x + box_w / 2, y + 0.18, f"{i + 1}.0", fontsize=8.5,
                 color="#FFFFFF", fontproperties=FontProperties(family=font_family),
                 ha="center", va="top", alpha=0.85)
        for line in lines:
            ax.text(x + box_w / 2, ty, line, fontsize=9.5, color="#FFFFFF",
                     fontproperties=fp_label, ha="center", va="center")
            ty += 0.22
        centers.append((x, y, box_w, box_h, row, col))

    for i in range(n - 1):
        x1, y1, w1, h1, r1, c1 = centers[i]
        x2, y2, w2, h2, r2, c2 = centers[i + 1]
        if r1 == r2:
            _right_arrow(ax, x1 + w1, x2, y1 + h1 / 2, colour=accent_hex)
        else:
            _diagonal_arrow(ax, x1 + w1 / 2, y1 + h1, x2 + w2 / 2, y2, colour=accent_hex)

    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path


def _open_store_box(ax, x, y, w, h, edge_hex, fill_hex="FFFFFF"):
    """Gane-Sarson data-store symbol: a box with the right edge left open
    (top, left and bottom drawn; no right border) — the standard DFD
    convention for "data at rest", visually distinct from both the closed
    rounded process boxes and the closed sharp entity rectangles."""
    c = _hex(edge_hex)
    ax.add_patch(Rectangle((x, y), w, h, linewidth=0, facecolor=_hex(fill_hex)))
    ax.plot([x, x + w], [y, y], color=c, linewidth=1.3)
    ax.plot([x, x + w], [y + h, y + h], color=c, linewidth=1.3)
    ax.plot([x, x], [y, y + h], color=c, linewidth=1.3)


def render_dfd_diagram(entities: list[str], processes: list[tuple[str, str, str, str]],
                        stores: dict[str, str], out_path: str | Path,
                        accent_hex: str = "1F4E78", font_family: str = "Calibri",
                        cols_per_row: int = 3) -> Path:
    """A real Data Flow Diagram with three visually distinct shapes, not
    the uniform numbered-box chain `render_flow_diagram` draws — flagged
    as a known gap in Memory.md ("true DFD notation... is a different
    diagram grammar than the numbered chain this template uses
    everywhere") and requested directly by the user afterward.

    - PROCESSES: rounded boxes (same visual language as the rest of this
      module), numbered n.0, in a left-to-right chain that wraps onto
      further rows — reuses render_flow_diagram's exact grid/arrow layout.
    - ENTITIES (external actors — "Citizen", "Ward Officer"): sharp-cornered
      grey rectangles. Only the process chain's start and end are checked
      for an entity reference, matching the common DFD Level-1 shape of
      "actor triggers the process, actor receives the outcome" — a process
      in the MIDDLE of the chain isn't given its own entity box, since
      that would need real graph layout rather than this linear chain.
    - DATA STORES ("D1 Grievance Database"): open-ended boxes (Gane-Sarson
      convention — see `_open_store_box`). Each unique store is drawn once,
      attached below the FIRST process that references it; later
      references to the same store don't redraw it, to avoid cluttering a
      proposal diagram with every read/write edge a rigorous systems-
      analysis DFD would show.

    `processes`: list of (number, label, in_ref, out_ref) — `in_ref`/
    `out_ref` are either blank, an entity name, or a store id ("D1")
    matching a key in `stores`."""
    out_path = Path(out_path)
    if not processes:
        raise ValueError("render_dfd_diagram: no processes given")

    entity_set = {e.strip().lower() for e in entities}

    def _is_entity(ref: str) -> bool:
        return bool(ref) and ref.strip().lower() in entity_set

    def _matching_store(ref: str) -> str | None:
        if not ref:
            return None
        ref_norm = ref.strip().lower()
        for sid in stores:
            if sid.strip().lower() == ref_norm:
                return sid
        return None

    # Build the chain: N processes, plus one trailing "entity" pseudo-box
    # if the last process outputs to a declared entity — reuses the exact
    # same grid/wrap/arrow logic as render_flow_diagram by treating that
    # trailing entity as just another box in the sequence, styled
    # differently at draw time.
    chain = [("process", num, label) for num, label, _in, _out in processes]
    out_ref = processes[-1][3]
    if _is_entity(out_ref):
        chain.append(("entity", "", out_ref))

    fig_w = 7.4
    n = len(chain)
    nrows = (n + cols_per_row - 1) // cols_per_row
    box_w, box_h = 1.95, 1.05
    gap_x = 0.55
    row_gap = 0.95  # taller than render_flow_diagram's — leaves room for a store band between rows
    margin = 0.25

    in_ref0 = processes[0][2]
    has_input_entity = _is_entity(in_ref0)
    entity_band_h = 0.85 if has_input_entity else 0.0

    total_row_w = cols_per_row * box_w + (cols_per_row - 1) * gap_x
    x_start = (fig_w - total_row_w) / 2
    fig_h = margin * 2 + entity_band_h + nrows * box_h + (nrows - 1) * row_gap

    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    fp_bold = FontProperties(family=font_family, weight="bold")
    fp_reg = FontProperties(family=font_family)
    palette = _derive_palette(accent_hex)

    fig, ax = _fig(fig_w, fig_h)
    top = margin + entity_band_h

    centers = []
    for i, (kind, num, label) in enumerate(chain):
        row, col = divmod(i, cols_per_row)
        x = x_start + col * (box_w + gap_x)
        y = top + row * (box_h + row_gap)
        if kind == "entity":
            ax.add_patch(Rectangle((x, y), box_w, box_h, linewidth=1.3,
                                    edgecolor=_hex("6B7280"), facecolor=_hex("F3F4F6")))
            lines = _wrap(label, box_w - 0.3, 9.5)
            ty = y + box_h / 2 - (len(lines) - 1) * 0.11
            for line in lines:
                ax.text(x + box_w / 2, ty, line, fontsize=9.5, color=_hex(_TEXT_DARK),
                         fontproperties=fp_bold, ha="center", va="center")
                ty += 0.22
        else:
            _rounded_box(ax, x, y, box_w, box_h, fill=accent_hex, edge=accent_hex)
            lines = _wrap(label, box_w - 0.3, 9.5)
            ty = y + box_h / 2 - (len(lines) - 1) * 0.11
            ax.text(x + box_w / 2, y + 0.18, num, fontsize=8.5, color="#FFFFFF",
                     fontproperties=fp_reg, ha="center", va="top", alpha=0.85)
            for line in lines:
                ax.text(x + box_w / 2, ty, line, fontsize=9.5, color="#FFFFFF",
                         fontproperties=fp_bold, ha="center", va="center")
                ty += 0.22
        centers.append((x, y, box_w, box_h, row, col))

    for i in range(n - 1):
        x1, y1, w1, h1, r1, c1 = centers[i]
        x2, y2, w2, h2, r2, c2 = centers[i + 1]
        if r1 == r2:
            _right_arrow(ax, x1 + w1, x2, y1 + h1 / 2, colour=accent_hex)
        else:
            _diagonal_arrow(ax, x1 + w1 / 2, y1 + h1, x2 + w2 / 2, y2, colour=accent_hex)

    # Input entity, above the first process
    if has_input_entity:
        x0, y0, w0, h0, _, _ = centers[0]
        ent_w, ent_h = 1.6, 0.55
        ex = x0 + w0 / 2 - ent_w / 2
        ey = margin
        ax.add_patch(Rectangle((ex, ey), ent_w, ent_h, linewidth=1.3,
                                edgecolor=_hex("6B7280"), facecolor=_hex("F3F4F6")))
        for line in _wrap(in_ref0, ent_w - 0.2, 9.0):
            ax.text(ex + ent_w / 2, ey + ent_h / 2, line, fontsize=9.0, color=_hex(_TEXT_DARK),
                     fontproperties=fp_bold, ha="center", va="center")
        _down_arrow(ax, x0 + w0 / 2, ey + ent_h, y0, colour="6B7280")

    # One box per unique data store, attached below the first process (by
    # chain order) that references it — either as input (arrow store ->
    # process) or output (arrow process -> store).
    drawn_stores = set()
    store_w, store_h = 1.5, 0.4
    for idx, (num, label, in_ref, out_ref) in enumerate(processes):
        for ref, is_input in ((in_ref, True), (out_ref, False)):
            sid = _matching_store(ref)
            if sid is None or sid in drawn_stores:
                continue
            drawn_stores.add(sid)
            x, y, w, h, row, col = centers[idx]
            sx = x + w / 2 - store_w / 2
            sy = y + h + 0.2
            colour = palette[len(drawn_stores) % len(palette)]
            _open_store_box(ax, sx, sy, store_w, store_h, edge_hex=colour)
            store_label = f"{sid}  {stores[sid]}"
            for line in _wrap(store_label, store_w - 0.1, 7.5):
                ax.text(sx + store_w / 2, sy + store_h / 2, line, fontsize=7.5,
                         color=_hex(colour), fontproperties=fp_bold, ha="center", va="center")
            if is_input:
                # Arrow points UP into the process (store -> process: the
                # process reads this store) — from=sy (store), to=y+h
                # (process's bottom edge), so the arrowhead lands at the
                # process despite the helper's "down" name (it just draws
                # from its first y to its second; which end gets the
                # arrowhead is what makes this read as "into the process").
                _down_arrow(ax, sx + store_w * 0.3, sy, y + h, colour=colour)
            else:
                # Arrow points DOWN into the store (process -> store: the
                # process writes this store).
                _down_arrow(ax, sx + store_w * 0.7, y + h, sy, colour=colour)

    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# Timeline — stacked phase cards with a week-range header, matching the
# "Implementation Methodology & Timeline" reference layout
# ═══════════════════════════════════════════════════════════════════════

def render_timeline_diagram(phases: list[tuple[str, str, str]], out_path: str | Path,
                             accent_hex: str = "1F4E78",
                             font_family: str = "Calibri") -> Path:
    """phases: list of (phase_name, week_range, description)."""
    out_path = Path(out_path)
    if not phases:
        raise ValueError("render_timeline_diagram: no phases given")

    fig_w = 7.4
    label_fs, range_fs, desc_fs = 11.5, 10.5, 9.3
    pad_x, pad_top = 0.22, 0.12
    line_h = 0.18
    box_w = fig_w - 0.5

    wrapped = []
    for name, weeks, desc in phases:
        lines = _wrap(desc, box_w - 2 * pad_x, desc_fs)
        body_h = pad_top + 0.26 + len(lines) * line_h + 0.16
        wrapped.append((name, weeks, lines, body_h))

    gap = 0.16
    margin = 0.25
    fig_h = margin * 2 + sum(h for *_, h in wrapped) + gap * (len(wrapped) - 1)

    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    fp_label = FontProperties(family=font_family, weight="bold")
    fp_range = FontProperties(family=font_family, weight="bold")
    fp_desc = FontProperties(family=font_family)

    fig, ax = _fig(fig_w, fig_h)
    palette = _derive_palette(accent_hex)
    y = margin
    x = 0.25
    for i, (name, weeks, lines, body_h) in enumerate(wrapped):
        colour = palette[i % len(palette)]
        _rounded_box(ax, x, y, box_w, body_h)
        _left_bar(ax, x, y, body_h, colour)
        ax.text(x + pad_x + 0.06, y + pad_top + 0.10, name, fontsize=label_fs,
                 color=_hex(colour), fontproperties=fp_label, ha="left", va="top")
        ax.text(x + box_w - pad_x, y + pad_top + 0.10, weeks, fontsize=range_fs,
                 color=_hex(_TEXT_DARK), fontproperties=fp_range, ha="right", va="top")
        ty = y + pad_top + 0.26 + 0.12
        for line in lines:
            ax.text(x + pad_x + 0.06, ty, line, fontsize=desc_fs,
                     color=_hex(_TEXT_DARK), fontproperties=fp_desc, ha="left", va="top")
            ty += line_h
        y += body_h + gap

    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# Sitemap — a title bar, a down arrow, then N column "pillar" cards each
# with a bulleted list of sub-pages, matching the reference proposal's
# "Information Architecture" diagram (a coloured header strip, one column
# per top-level nav item, bullet sub-items underneath).
# ═══════════════════════════════════════════════════════════════════════

def render_sitemap_diagram(site_name: str, pillars: list[tuple[str, list[str]]],
                            out_path: str | Path, accent_hex: str = "1F4E78",
                            font_family: str = "Calibri") -> Path:
    """pillars: list of (pillar_title, [sub_page, ...])."""
    out_path = Path(out_path)
    if not pillars:
        raise ValueError("render_sitemap_diagram: no pillars given")

    n = len(pillars)
    # Widen the canvas as pillars are added rather than shrinking the type.
    # Font size is NOT the lever here: matplotlib/freetype silently fails to
    # rasterise below ~8pt at this DPI (text vanishes entirely — see the
    # fontsize floor documented in Memory.md), so anything narrower has to
    # come from more canvas, not smaller text. A wider figure embeds at the
    # same width in the document, so the practical effect is slightly finer
    # text with every word intact.
    fig_w = 7.4 if n <= 5 else 7.4 + 0.75 * (n - 5)
    gap_x = 0.18
    margin = 0.25
    col_w = (fig_w - 2 * margin - (n - 1) * gap_x) / n
    header_h = 0.55
    item_fs, header_fs, title_fs = 8.6, 10.5, 11.5
    item_line_h = 0.20

    wrapped_cols = []
    max_lines = 0
    for title, items in pillars:
        lines = []
        for item in items:
            # Wrap the item text alone (not "• {item}") and prefix the
            # bullet onto the first line only — wrapping the bullet as part
            # of the text let textwrap treat "•" as its own word and strand
            # it alone on a line when "• {item}" didn't fit, e.g.
            # "•" / "Slider/banners" instead of "• Slider/banners".
            item_lines = _wrap(item, col_w - 0.4, item_fs) or [""]
            item_lines[0] = f"• {item_lines[0]}"
            lines.extend(item_lines)
        wrapped_cols.append(lines)
        max_lines = max(max_lines, len(lines))

    title_bar_h = 0.5
    arrow_h = 0.28
    body_h = header_h + 0.18 + max_lines * item_line_h + 0.2
    fig_h = margin + title_bar_h + arrow_h + body_h + margin

    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    fp_title = FontProperties(family=font_family, weight="bold")
    fp_header = FontProperties(family=font_family, weight="bold")
    fp_item = FontProperties(family=font_family)

    fig, ax = _fig(fig_w, fig_h)

    y = margin
    _rounded_box(ax, margin, y, fig_w - 2 * margin, title_bar_h, fill=accent_hex, edge=accent_hex)
    ax.text(fig_w / 2, y + title_bar_h / 2, site_name, fontsize=title_fs,
             color="#FFFFFF", fontproperties=fp_title, ha="center", va="center")
    y += title_bar_h
    _down_arrow(ax, fig_w / 2, y + 0.03, y + arrow_h - 0.03, colour=accent_hex)
    y += arrow_h

    palette = _derive_palette(accent_hex)
    x = margin
    for i, (title, _items) in enumerate(pillars):
        colour = palette[i % len(palette)]
        _rounded_box(ax, x, y, col_w, body_h)
        header_box_h = header_h
        ax.add_patch(FancyBboxPatch(
            (x, y), col_w, header_box_h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=0, facecolor=_hex(colour),
        ))
        # square off the bottom corners of the header so it reads as one
        # continuous card with the body below, not two separate pills
        ax.add_patch(Rectangle((x, y + header_box_h / 2), col_w, header_box_h / 2,
                                linewidth=0, facecolor=_hex(colour)))
        title_lines = _wrap(title, col_w - 0.2, header_fs)
        ty = y + header_box_h / 2 - (len(title_lines) - 1) * 0.09
        for line in title_lines:
            ax.text(x + col_w / 2, ty, line, fontsize=header_fs, color="#FFFFFF",
                     fontproperties=fp_header, ha="center", va="center")
            ty += 0.19
        iy = y + header_box_h + 0.14
        for line in wrapped_cols[i]:
            ax.text(x + 0.1, iy, line, fontsize=item_fs, color=_hex(_TEXT_DARK),
                     fontproperties=fp_item, ha="left", va="top")
            iy += item_line_h
        x += col_w + gap_x

    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# UI mock screen — a low-fidelity browser-frame wireframe (chrome bar, nav,
# hero/content blocks made of placeholder text-line bars) matching the
# reference proposal's "UI Design Concepts & Mock Screens" section. Two
# kinds: "public_home" (marketing/content site) and "admin_dashboard"
# (CMS/admin backend) — generic layouts, not a pixel-accurate design tool,
# intended to show shape/structure the way a real wireframe does.
# ═══════════════════════════════════════════════════════════════════════

def _placeholder_lines(ax, x, y, w, n, colour="#D0D5DD", line_h=0.11, gap=0.05):
    for i in range(n):
        ax.add_patch(Rectangle((x, y + i * (line_h + gap)), w * (0.9 if i == n - 1 else 1.0),
                                line_h, linewidth=0, facecolor=colour))


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars - 1].rstrip() + "…"


def render_ui_mockup(kind: str, heading: str, out_path: str | Path,
                      accent_hex: str = "1F4E78", font_family: str = "Calibri",
                      nav_items: list[str] | None = None, cards: list[str] | None = None,
                      sidebar_items: list[str] | None = None) -> Path:
    """`nav_items`/`cards` (public_home) and `sidebar_items`
    (admin_dashboard) let the mockup reflect THIS project's actual
    sitemap/modules/admin-capabilities instead of a generic "Home / About
    / Services / News / Contact" skeleton every project got before this —
    a real user asked "will the image generated be the same [every time]?"
    and the honest answer had been yes, only the title and colour varied.
    All three are optional and fall back to the original generic content
    when omitted, so a standalone call (testing, docs) still works."""
    out_path = Path(out_path)
    nav_items = [i for i in (nav_items or []) if i][:5] or ["Home", "About", "Services", "News", "Contact"]
    sidebar_items = [i for i in (sidebar_items or []) if i][:4]
    sidebar_items = ["Dashboard"] + sidebar_items if sidebar_items else \
        ["Dashboard", "Content", "Media", "Users & Roles", "Settings"]
    fig_w, fig_h = 6.6, 4.6
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    fp_bold = FontProperties(family=font_family, weight="bold")
    fp_reg = FontProperties(family=font_family)

    fig, ax = _fig(fig_w, fig_h)

    # Outer browser frame
    _rounded_box(ax, 0.15, 0.15, fig_w - 0.3, fig_h - 0.3, fill="FFFFFF", edge="AAB2BD", lw=1.2)
    # Chrome bar
    chrome_h = 0.32
    ax.add_patch(Rectangle((0.15, 0.15), fig_w - 0.3, chrome_h, linewidth=0, facecolor=_hex("EDEFF2")))
    for i, dx in enumerate((0.32, 0.48, 0.64)):
        ax.add_patch(Circle((0.15 + dx, 0.15 + chrome_h / 2), 0.045,
                             facecolor=_hex(["E74C3C", "F1C40F", "2ECC71"][i]), linewidth=0))
    ax.add_patch(FancyBboxPatch((1.0, 0.15 + 0.06), fig_w - 1.5, chrome_h - 0.12,
                                 boxstyle="round,pad=0.01,rounding_size=0.05",
                                 linewidth=0.6, edgecolor=_hex("C7CCD4"), facecolor=_hex("FFFFFF")))
    url_slug = _truncate(heading.lower().replace(" ", ""), 24)
    ax.text(1.15, 0.15 + chrome_h / 2, url_slug + ".example.gov.in",
             fontsize=8.0, color=_hex("6B7280"), fontproperties=fp_reg, ha="left", va="center")

    content_top = 0.15 + chrome_h
    content_h = fig_h - 0.3 - chrome_h

    if kind == "admin_dashboard":
        sidebar_w = 1.5
        ax.add_patch(Rectangle((0.15, content_top), sidebar_w, content_h, linewidth=0, facecolor=_hex(accent_hex)))
        ax.text(0.15 + sidebar_w / 2, content_top + 0.28, "Admin CMS", fontsize=8.5,
                 color="#FFFFFF", fontproperties=fp_bold, ha="center", va="center")
        my = content_top + 0.6
        for i, item in enumerate(sidebar_items):
            if i == 0:
                ax.add_patch(Rectangle((0.15, my - 0.02), sidebar_w, 0.24, linewidth=0,
                                        facecolor=_hex("FFFFFF"), alpha=0.15))
            item_lines = _wrap(item, sidebar_w - 0.3, 8.5)[:1]
            ax.text(0.3, my + 0.1, item_lines[0] if item_lines else item, fontsize=8.5, color="#FFFFFF",
                     fontproperties=fp_reg, ha="left", va="center")
            my += 0.32

        body_x = 0.15 + sidebar_w + 0.15
        body_w = fig_w - 0.3 - sidebar_w - 0.3
        ax.text(body_x, content_top + 0.28, "Dashboard", fontsize=11, color=_hex(_TEXT_DARK),
                 fontproperties=fp_bold, ha="left", va="center")
        # 4 stat cards
        card_w = (body_w - 3 * 0.14) / 4
        card_h = 0.65
        stats = [("128", "Enquiries"), ("46", "Content Items"), ("12", "Pending"), ("99.9%", "Uptime")]
        for i, (num, label) in enumerate(stats):
            cx = body_x + i * (card_w + 0.14)
            cy = content_top + 0.5
            _rounded_box(ax, cx, cy, card_w, card_h)
            ax.text(cx + card_w / 2, cy + 0.24, num, fontsize=11, color=_hex(accent_hex),
                     fontproperties=fp_bold, ha="center", va="center")
            ax.text(cx + card_w / 2, cy + 0.48, label, fontsize=8.0, color=_hex("6B7280"),
                     fontproperties=fp_reg, ha="center", va="center")
        # table area
        table_y = content_top + 0.5 + card_h + 0.2
        table_h = content_h - (table_y - content_top) - 0.15
        _rounded_box(ax, body_x, table_y, body_w, table_h)
        ax.add_patch(Rectangle((body_x, table_y), body_w, 0.26, linewidth=0, facecolor=_hex(accent_hex)))
        for i in range(3):
            ry = table_y + 0.26 + 0.12 + i * 0.22
            if ry < table_y + table_h - 0.1:
                _placeholder_lines(ax, body_x + 0.15, ry, body_w - 0.3, 1, line_h=0.09)

    else:  # public_home
        nav_h = 0.42
        ax.add_patch(Rectangle((0.15, content_top), fig_w - 0.3, nav_h, linewidth=0, facecolor=_hex(accent_hex)))
        ax.text(0.35, content_top + nav_h / 2, _truncate(heading, 20), fontsize=9.5, color="#FFFFFF",
                 fontproperties=fp_bold, ha="left", va="center")
        nav_step = min(0.9, (fig_w - 0.9 - 2.7) / max(len(nav_items) - 1, 1)) if len(nav_items) > 1 else 0
        for i, item in enumerate(nav_items):
            x = fig_w - 0.75 - (len(nav_items) - 1 - i) * nav_step
            ax.text(x, content_top + nav_h / 2, _truncate(item, 12), fontsize=8.0,
                     color="#FFFFFF", fontproperties=fp_reg, ha="left", va="center")

        hero_y = content_top + nav_h + 0.15
        hero_h = 1.35
        _rounded_box(ax, 0.35, hero_y, fig_w - 0.7, hero_h, fill="F5F7FA")
        hero_lines = _wrap(f"Welcome to {heading}", fig_w - 0.7 - 0.4, 12.5)[:2]
        hty = hero_y + 0.24
        for line in hero_lines:
            ax.text(0.55, hty, line, fontsize=12.5,
                     color=_hex(_TEXT_DARK), fontproperties=fp_bold, ha="left", va="center")
            hty += 0.22
        _placeholder_lines(ax, 0.55, hty + 0.06, 3.2, 1, line_h=0.09)
        for i, label in enumerate(["Get Started", "Learn More"]):
            bx = 0.55 + i * 1.5
            by = hero_y + hero_h - 0.35
            fill = accent_hex if i == 0 else "FFFFFF"
            edge = accent_hex
            _rounded_box(ax, bx, by, 1.3, 0.28, fill=fill, edge=edge)
            ax.text(bx + 0.65, by + 0.14, label, fontsize=8.5,
                     color="#FFFFFF" if i == 0 else _hex(accent_hex),
                     fontproperties=fp_bold, ha="center", va="center")

        cards_y = hero_y + hero_h + 0.2
        card_gap = 0.18
        card_w = (fig_w - 0.7 - 2 * card_gap) / 3
        card_h = content_top + content_h - cards_y - 0.15
        card_labels = [c for c in (cards or []) if c][:3]
        card_palette = _derive_palette(accent_hex)
        for i in range(3):
            cx = 0.35 + i * (card_w + card_gap)
            _rounded_box(ax, cx, cards_y, card_w, card_h)
            ax.add_patch(Circle((cx + 0.35, cards_y + 0.35), 0.16, facecolor=_hex(card_palette[i]), linewidth=0))
            if i < len(card_labels):
                label_lines = _wrap(card_labels[i], card_w - 0.36, 9.0)[:2]
                ty = cards_y + 0.66
                for line in label_lines:
                    ax.text(cx + 0.18, ty, line, fontsize=9.0, color=_hex(_TEXT_DARK),
                             fontproperties=fp_bold, ha="left", va="top")
                    ty += 0.16
            else:
                _placeholder_lines(ax, cx + 0.18, cards_y + 0.65, card_w - 0.36, 2, line_h=0.09)

    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════════
# Leadership avatar placeholder — initials on a coloured circle. Used only
# when no real photo file is supplied for a leadership entry.
# ═══════════════════════════════════════════════════════════════════════

def render_initials_avatar(name: str, out_path: str | Path,
                            bg_hex: str = "1F4E78", font_family: str = "Calibri") -> Path:
    out_path = Path(out_path)
    initials = "".join(w[0].upper() for w in name.split()[:2] if w)

    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
    fig, ax = _fig(1.4, 1.4)
    ax.add_patch(Circle((0.7, 0.7), 0.66, facecolor=_hex(bg_hex), linewidth=0))
    ax.text(0.7, 0.72, initials, fontsize=34, color="#FFFFFF",
             fontproperties=FontProperties(family=font_family, weight="bold"),
             ha="center", va="center")
    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path
