"""Renders section 14's UI mockups (public site + admin CMS) as real HTML/
CSS pages, screenshotted with a locally-installed Chrome/Edge in headless
mode, instead of matplotlib-drawn boxes. Real fonts, real flexbox layout,
real box-shadows — a genuinely higher-fidelity mockup than
diagram_render.render_ui_mockup's hand-drawn wireframe, at effectively
zero marginal cost: no new LLM calls (reuses content already generated
for other sections — sitemap pillars, modules, admin capabilities), no
new paid dependency (Chrome/Edge ships with Windows, or is near-universal
on a dev machine already). A real user asked for exactly this after
seeing the matplotlib version: "make screens of HTML and then the
screenshots... fed into the PDF."

Falls back to diagram_render.render_ui_mockup automatically if no local
Chrome/Edge is found (see build_templates.py's _add_ui_mockup_image) —
this keeps the pipeline working on a machine without either browser
installed, at the cost of the lower-fidelity wireframe there instead."""
from __future__ import annotations

import colorsys
import html
import shutil
import subprocess
import tempfile
from pathlib import Path


def _derive_palette(accent_hex: str, n: int = 5) -> list[str]:
    """Coordinated colours derived from `accent_hex` instead of a fixed
    literal palette — same fix, same reasoning, as
    generation/diagram_render.py's `_derive_palette` (duplicated rather
    than imported to keep this module's only external dependency a local
    browser binary, not another project module): a real user reported
    "light mode and dark mode is not working properly", and here it was
    this module's card icon colours staying the old default navy/red no
    matter which preset was active, while the nav bar and buttons (which
    already used `accent_hex` directly) correctly changed.

    Monochromatic by design (lightness-only variation, same hue) rather
    than hue-rotated — an earlier version that rotated hue produced neon,
    off-brand swatches for saturated accents; see diagram_render.py's
    version of this function for the full reasoning."""
    r, g, b = (int(accent_hex.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    base_l = min(max(l, 0.22), 0.40)
    light_shifts = [0.0, -0.08, 0.07, -0.14, 0.13][:n]
    palette = []
    for dl in light_shifts:
        nl = min(max(base_l + dl, 0.16), 0.50)
        nr, ng, nb = colorsys.hls_to_rgb(h, nl, s)
        palette.append("".join(f"{max(0, min(255, round(c * 255))):02X}" for c in (nr, ng, nb)))
    return palette


class BrowserNotFoundError(RuntimeError):
    """No local Chrome/Edge install found to drive headless screenshots."""


def _find_browser() -> Path | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return Path(c)
    for name in ("google-chrome", "chromium", "chromium-browser", "msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _truncate(text: str, max_chars: int) -> str:
    text = str(text)
    return text if len(text) <= max_chars else text[:max_chars - 1].rstrip() + "…"


_BASE_CSS = """
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: '{font}', 'Segoe UI', Calibri, sans-serif; background:#e9edf1; padding:20px; }}
.browser {{ max-width:1160px; margin:0 auto; border-radius:10px; overflow:hidden;
  box-shadow:0 8px 24px rgba(0,0,0,0.16); background:#fff; border:1px solid #d0d5dd; }}
.chrome {{ background:#eceef1; padding:10px 16px; display:flex; align-items:center; gap:14px;
  border-bottom:1px solid #d7dbe0; }}
.dots span {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:6px; }}
.url {{ flex:1; background:#fff; border:1px solid #c7ccd4; border-radius:6px; padding:6px 12px;
  color:#6b7280; font-size:13px; }}
"""


def render_html_mockup(kind: str, heading: str, out_path: str | Path,
                        accent_hex: str = "1F4E78", font_family: str = "Calibri",
                        nav_items: list[str] | None = None, cards: list[str] | None = None,
                        sidebar_items: list[str] | None = None) -> Path:
    browser = _find_browser()
    if browser is None:
        raise BrowserNotFoundError(
            "No local Chrome/Edge install found — can't render HTML mockups. "
            "Falls back to the matplotlib wireframe automatically (see "
            "build_templates.py's _add_ui_mockup_image)."
        )
    out_path = Path(out_path)
    accent = f"#{accent_hex.lstrip('#')}"

    if kind == "admin_dashboard":
        items = [i for i in (sidebar_items or []) if i][:4]
        items = ["Dashboard"] + items if items else ["Dashboard", "Content", "Media", "Users & Roles", "Settings"]
        sidebar_links = "".join(
            f'<a class="{"active" if i == 0 else ""}">{_esc(_truncate(item, 22))}</a>'
            for i, item in enumerate(items)
        )
        stats = [("128", "Enquiries"), ("46", "Content Items"), ("12", "Pending"), ("99.9%", "Uptime")]
        stats_html = "".join(
            f'<div class="stat"><div class="num">{_esc(n)}</div><div class="label">{_esc(l)}</div></div>'
            for n, l in stats
        )
        rows_html = "".join(
            f'<div class="row">{_esc(item)} — updated recently</div>' for item in items[1:4]
        ) or '<div class="row">No recent activity</div>'
        url_slug = _truncate(heading.lower().replace(" ", ""), 24)
        html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_BASE_CSS.format(font=font_family)}
.layout {{ display:flex; }}
.sidebar {{ width:210px; background:{accent}; color:#fff; padding:22px 0; flex-shrink:0; }}
.sidebar .brand {{ font-weight:700; padding:0 20px 18px; font-size:15px; }}
.sidebar a {{ display:block; padding:10px 20px; color:#fff; text-decoration:none; font-size:13.5px; opacity:0.85; cursor:default; }}
.sidebar a.active {{ background:rgba(255,255,255,0.16); opacity:1; font-weight:600; }}
.content {{ flex:1; padding:26px 30px; background:#f8fafc; min-width:0; }}
.content h2 {{ margin:0 0 18px; font-size:19px; color:#1a1a1a; }}
.stats {{ display:flex; gap:14px; margin-bottom:22px; }}
.stat {{ flex:1; background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:16px; text-align:center; }}
.stat .num {{ font-size:20px; font-weight:700; color:{accent}; }}
.stat .label {{ font-size:11.5px; color:#6b7280; margin-top:4px; }}
.table {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; overflow:hidden; }}
.table .head {{ background:{accent}; color:#fff; padding:11px 18px; font-size:12.5px; font-weight:600; }}
.table .row {{ padding:11px 18px; border-top:1px solid #eef0f3; font-size:12.5px; color:#374151; }}
</style></head><body>
<div class="browser">
<div class="chrome"><div class="dots"><span style="background:#e74c3c"></span><span style="background:#f1c40f"></span><span style="background:#2ecc71"></span></div>
<div class="url">{_esc(url_slug)}.example.gov.in/admin</div></div>
<div class="layout">
<div class="sidebar"><div class="brand">Admin CMS</div>{sidebar_links}</div>
<div class="content"><h2>Dashboard</h2>
<div class="stats">{stats_html}</div>
<div class="table"><div class="head">Recent Activity</div>{rows_html}</div>
</div></div></div></body></html>"""
    else:  # public_home
        items = [i for i in (nav_items or []) if i][:5] or ["Home", "About", "Services", "News", "Contact"]
        nav_links = "".join(f'<a>{_esc(_truncate(item, 16))}</a>' for item in items)
        card_labels = [c for c in (cards or []) if c][:3]
        while len(card_labels) < 3:
            card_labels.append(None)
        card_palette = _derive_palette(accent_hex)
        cards_html = "".join(
            f'<div class="card"><div class="icon" style="background:#{card_palette[i % len(card_palette)]}"></div>'
            f'<h3>{_esc(_truncate(label, 40)) if label else "&nbsp;"}</h3>'
            f'<p>{"Key functionality for this section of the site." if label else "&nbsp;<br>&nbsp;"}</p></div>'
            for i, label in enumerate(card_labels)
        )
        url_slug = _truncate(heading.lower().replace(" ", ""), 24)
        html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_BASE_CSS.format(font=font_family)}
.nav {{ background:{accent}; color:#fff; padding:16px 32px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }}
.nav .brand {{ font-weight:700; font-size:17px; }}
.nav .links a {{ color:#fff; text-decoration:none; margin-left:24px; font-size:13.5px; opacity:0.92; }}
.hero {{ padding:44px 40px; background:#f5f7fa; }}
.hero h1 {{ margin:0 0 12px; font-size:27px; color:#1a1a1a; }}
.hero p {{ color:#4b5563; max-width:600px; margin:0 0 22px; font-size:14.5px; }}
.btn {{ display:inline-block; padding:11px 22px; border-radius:8px; font-weight:600; text-decoration:none; font-size:13.5px; margin-right:12px; }}
.btn-primary {{ background:{accent}; color:#fff; }}
.btn-secondary {{ background:#fff; color:{accent}; border:2px solid {accent}; }}
.cards {{ display:flex; gap:18px; padding:30px 40px 44px; }}
.card {{ flex:1; background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:22px;
  box-shadow:0 2px 6px rgba(0,0,0,0.04); min-width:0; }}
.card .icon {{ width:40px; height:40px; border-radius:50%; margin-bottom:12px; }}
.card h3 {{ margin:0 0 6px; font-size:14px; color:#1a1a1a; }}
.card p {{ margin:0; color:#6b7280; font-size:12.5px; line-height:1.5; }}
</style></head><body>
<div class="browser">
<div class="chrome"><div class="dots"><span style="background:#e74c3c"></span><span style="background:#f1c40f"></span><span style="background:#2ecc71"></span></div>
<div class="url">{_esc(url_slug)}.example.gov.in</div></div>
<div class="nav"><div class="brand">{_esc(_truncate(heading, 40))}</div><div class="links">{nav_links}</div></div>
<div class="hero"><h1>Welcome to {_esc(_truncate(heading, 50))}</h1>
<p>A modern, accessible platform built to serve every visitor efficiently and reliably.</p>
<a class="btn btn-primary">Get Started</a><a class="btn btn-secondary">Learn More</a></div>
<div class="cards">{cards_html}</div>
</div></body></html>"""

    return _screenshot_html(html_doc, out_path, browser)


def _screenshot_html(html_doc: str, out_path: Path, browser: Path,
                      bg_rgb: tuple[int, int, int] = (233, 237, 241)) -> Path:
    """Render `html_doc` in headless Chrome/Edge, screenshot it, auto-crop
    the trailing blank area, and save to `out_path`.

    Shared by the built-in template path and the AI-generated-HTML path so
    both get identical capture settings (2x device scale for a crisp
    embed, a deliberately over-tall window since headless Chrome captures
    exactly the viewport and has no "full page, auto height" flag, then a
    difference-against-background crop to remove the unused space)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        html_path = Path(tmp_dir) / "mockup.html"
        html_path.write_text(html_doc, encoding="utf-8")
        raw_shot = Path(tmp_dir) / "raw.png"
        result = subprocess.run(
            [str(browser), "--headless", "--disable-gpu", f"--screenshot={raw_shot}",
             "--window-size=1200,1600", "--force-device-scale-factor=2",
             "--default-background-color=FFFFFFFF", "--hide-scrollbars", str(html_path)],
            capture_output=True, timeout=30,
        )
        if not raw_shot.exists():
            raise RuntimeError(f"Headless screenshot failed: {result.stderr.decode(errors='replace')[:500]}")

        from PIL import Image, ImageChops
        img = Image.open(raw_shot).convert("RGB")
        bg = Image.new("RGB", img.size, bg_rgb)
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox:
            pad = 10
            bbox = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                    min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height))
            img = img.crop(bbox)
        img.save(out_path)

    return out_path


def _looks_like_a_real_page(png_path: Path) -> tuple[bool, str]:
    """Sanity-check a screenshot before it is allowed into a client
    document. Guards specifically against the failure mode that makes
    AI-generated HTML risky: the model emits markup that renders to a
    blank page, a sliver, or a wall of one flat colour, and — without this
    check — that gets embedded into a real proposal as-is.

    Deliberately cheap and structural (size + colour variety) rather than
    trying to judge design quality, which is not something a heuristic can
    do honestly."""
    from PIL import Image
    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    if w < 500 or h < 250:
        return False, f"too small ({w}x{h}) — likely rendered blank or collapsed"
    if h > w * 3:
        return False, f"implausible aspect ratio ({w}x{h}) — layout probably broke"
    # A real mockup has chrome, text and panels: many distinct colours. A
    # blank/failed render is one or two flat fills.
    colours = img.resize((160, 160)).getcolors(maxcolors=160 * 160) or []
    if len(colours) < 12:
        return False, f"only {len(colours)} distinct colours — looks blank"
    dominant = max((c for c, _ in colours), default=0)
    if dominant / float(160 * 160) > 0.97:
        return False, "one colour covers >97% of the page — looks blank"
    return True, "ok"


def render_ai_mockup(html_doc: str, out_path: str | Path) -> Path:
    """Screenshot LLM-authored HTML, but only return successfully if the
    result passes `_looks_like_a_real_page`. Raises otherwise, so callers
    can fall back to the built-in template rather than embedding a broken
    page into a client proposal."""
    browser = _find_browser()
    if browser is None:
        raise BrowserNotFoundError("No local Chrome/Edge install found.")
    out_path = Path(out_path)
    _screenshot_html(html_doc, out_path, browser, bg_rgb=(255, 255, 255))
    ok, why = _looks_like_a_real_page(out_path)
    if not ok:
        raise ValueError(f"AI-generated mockup rejected: {why}")
    return out_path
