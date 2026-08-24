"""Template customisation settings — a single dataclass holding every
visual/layout property that can vary between document renders, plus a
preset system to save/load named configurations as JSON files.

Defaults match Source Soft Solutions' real branding (navy #1F4E78 heading
bars, their actual logo, real office addresses) — extracted directly from
three of their own real technical proposals (see `New Index/`), the same
"benchmark against the real document, don't guess" discipline used for
every other visual decision in this project. This superseded an earlier
QCI-branded default: this project pivoted from a QCI-specific PoC to being
Source Soft Solutions' own drafting tool, an explicit user decision — see
Memory.md."""
import json
from dataclasses import dataclass, field as dc_field, asdict
from pathlib import Path

PRESETS_DIR = Path(__file__).resolve().parent.parent / "data" / "template_presets"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# Names that ship with the system and cannot be deleted by users. A list,
# not a set: this drives the order of the preset dropdown in the UI, and a
# set's iteration order is not stable between runs — the dropdown would
# silently reshuffle itself every restart.
_BUILTIN_PRESET_NAMES = ["Source Soft Solutions", "Dark Mode", "Light Mode", "Minimal Clean", "Executive Crimson"]


@dataclass
class TemplateSettings:
    """Every customisable property of a generated document.  All fields
    have sensible defaults matching the current QCI-branded style, so
    existing code that doesn't pass settings gets the same output as
    before this feature existed."""

    # ── Colours ──────────────────────────────────────────────────────
    # Extracted directly from Source Soft Solutions' own proposal PDFs
    # (pymupdf get_drawings()/get_text() on New Index/*.pdf), not guessed:
    # the header rule, "TECHNICAL PROPOSAL" title, and section headings all
    # use this exact navy (confirmed: text span colour 0x1f4e78).
    heading_bar_colour: str = "1F4E78"        # navy fill on section headings
    heading_text_colour: str = "FFFFFF"       # white text inside heading bars
    page_border_colour: str = "000000"        # black page border
    accent_colour: str = "1F4E78"             # navy accent (header rule, etc.)

    # ── Typography ───────────────────────────────────────────────────
    font_family: str = "Calibri"
    body_font_size: int = 11                  # pt
    heading_font_size: int = 16               # pt

    # ── Logo ─────────────────────────────────────────────────────────
    # None → use Source Soft Solutions' real logo (assets/sourcesoft_logo.png,
    # extracted from their own proposal PDFs). A non-None value is an
    # absolute path to a user-uploaded image.
    logo_path: str | None = None
    logo_width_cm: float = 5.0
    logo_mark_path: str | None = None         # compact mark for signature block
    logo_mark_width_cm: float = 1.6

    # ── Page border ──────────────────────────────────────────────────
    show_page_border: bool = True
    page_border_style: str = "single"         # single | double | thick | dotted

    # ── Header / Footer ──────────────────────────────────────────────
    show_running_header: bool = True
    show_footer: bool = True

    # ── Signature block ──────────────────────────────────────────────
    signature_style: str = "labeled"          # labeled | blank-line

    # ── Fixed pages ──────────────────────────────────────────────────
    include_cover_page: bool = True
    include_toc: bool = True
    include_declarations: bool = True
    show_confidential_marking: bool = False

    # ── Organisation info (cover page) ───────────────────────────────
    organisation_name: str = "Source Soft Solutions"
    organisation_address: str = (
        "New Jersey, USA (HQ) · Dubai, UAE · Noida, India"
    )


# ═══════════════════════════════════════════════════════════════════════
# Built-in presets
# ═══════════════════════════════════════════════════════════════════════

def _sourcesoft_branded() -> TemplateSettings:
    """The exact current look — Source Soft Solutions' real navy heading
    bars, Calibri, and logo."""
    return TemplateSettings()


def _dark_mode() -> TemplateSettings:
    """Sleek modern dark styling — deep midnight heading bars, cyan/indigo accent, dark border."""
    return TemplateSettings(
        heading_bar_colour="0F172A",
        heading_text_colour="F8FAFC",
        page_border_colour="334155",
        accent_colour="3B82F6",
        font_family="Calibri",
        body_font_size=11,
        heading_font_size=16,
        show_page_border=True,
        page_border_style="single",
        show_confidential_marking=False,
    )


def _light_mode() -> TemplateSettings:
    """Refined clean light styling — crisp slate heading bars with dark text, vibrant azure accent."""
    return TemplateSettings(
        heading_bar_colour="E2E8F0",
        heading_text_colour="0F172A",
        page_border_colour="CBD5E1",
        accent_colour="0284C7",
        font_family="Calibri",
        body_font_size=11,
        heading_font_size=16,
        show_page_border=True,
        page_border_style="single",
        show_confidential_marking=False,
    )


def _minimal_clean() -> TemplateSettings:
    """Lighter, logo-free variant for internal / non-branded drafts."""
    return TemplateSettings(
        heading_bar_colour="4472C4",
        heading_text_colour="FFFFFF",
        page_border_colour="AAAAAA",
        accent_colour="5B9BD5",
        font_family="Arial",
        body_font_size=11,
        heading_font_size=15,
        logo_path="__NONE__",             # sentinel: explicitly no logo
        logo_mark_path="__NONE__",
        show_page_border=False,
        show_confidential_marking=False,
        organisation_name="",
        organisation_address="",
    )


def _executive_crimson() -> TemplateSettings:
    """Formal executive style with rich maroon/crimson accents and Garamond typography."""
    return TemplateSettings(
        heading_bar_colour="581845",
        heading_text_colour="FFFFFF",
        page_border_colour="900C3F",
        accent_colour="C70039",
        font_family="Garamond",
        body_font_size=12,
        heading_font_size=17,
        show_page_border=True,
        page_border_style="double",
        show_confidential_marking=True,
    )


_BUILTIN_FACTORIES = {
    "Source Soft Solutions": _sourcesoft_branded,
    "Dark Mode": _dark_mode,
    "Light Mode": _light_mode,
    "Minimal Clean": _minimal_clean,
    "Executive Crimson": _executive_crimson,
}


# ═══════════════════════════════════════════════════════════════════════
# Preset persistence (JSON files under data/template_presets/)
# ═══════════════════════════════════════════════════════════════════════

def _ensure_presets_dir():
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def _preset_path(name: str) -> Path:
    safe = name.strip().replace(" ", "_").lower()
    return PRESETS_DIR / f"{safe}.json"


def save_preset(name: str, settings: TemplateSettings) -> Path:
    """Save settings to a named JSON file.  Returns the file path."""
    _ensure_presets_dir()
    path = _preset_path(name)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    return path


def load_preset(name: str) -> TemplateSettings:
    """Load a preset by name.

    Built-in presets ALWAYS come from their in-code factory, never from a
    cached JSON file on disk — even if one already exists. A real bug hit
    a real user because of the opposite behaviour: Dark Mode/Light Mode/
    Executive Crimson had been materialised to disk (data/template_presets/
    *.json) back when their factories still set organisation_name="Quality
    Council of India" (pre-rebrand). The dataclass default was fixed to
    "Source Soft Solutions" months ago and every factory function is
    correct today, but `load_preset` was checking the stale JSON file
    FIRST and returning it verbatim — so every fix to a built-in preset's
    definition silently stopped applying the moment that preset was first
    loaded once, with no error or warning. A user rendered a real Technical
    Proposal, got "Quality Council of India" in the letterhead and a blank
    About the Company page (which only renders real content when
    organisation_name is exactly "Source Soft Solutions" — see
    _add_about_company_page in build_templates.py), and had no way to know
    a stale cache file was the cause.

    User-created custom presets (any name not in _BUILTIN_FACTORIES) still
    load from their JSON file as before — those have no in-code factory to
    fall back to, and a user's saved customisation should persist exactly
    as they left it."""
    if name in _BUILTIN_FACTORIES:
        settings = _BUILTIN_FACTORIES[name]()
        save_preset(name, settings)  # keep the on-disk cache in sync, harmless
        return settings
    path = _preset_path(name)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return TemplateSettings(**{k: v for k, v in data.items()
                                    if k in TemplateSettings.__dataclass_fields__})
    raise FileNotFoundError(f"No preset named '{name}' found at {path}")


def list_presets() -> list[str]:
    """All available preset names — built-ins first, then user-created."""
    _ensure_presets_dir()
    # Reverse map: filename stem -> canonical display name for built-ins
    # (avoids .title() mangling acronyms like QCI -> Qci)
    builtin_stems = {_preset_path(name).stem: name for name in _BUILTIN_PRESET_NAMES}
    user_presets = []
    for p in PRESETS_DIR.glob("*.json"):
        if p.stem not in builtin_stems:
            user_presets.append(p.stem.replace("_", " ").title())
    all_names = list(_BUILTIN_PRESET_NAMES) + sorted(user_presets)
    return all_names


def delete_preset(name: str) -> bool:
    """Delete a user-created preset.  Returns False for built-in presets."""
    if name in _BUILTIN_PRESET_NAMES:
        return False
    path = _preset_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def ensure_builtin_presets():
    """Materialise built-in preset JSON files if they don't exist yet."""
    for name, factory in _BUILTIN_FACTORIES.items():
        path = _preset_path(name)
        if not path.exists():
            save_preset(name, factory())
