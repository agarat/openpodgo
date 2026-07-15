"""Official POD Go Edit palette by UI category.

The hex values come from the `color` field of PGModelCatalog.json (official
app assets). Keys are the categories returned by `catalog.display_category()`
plus "Otros" (fallback) and None (empty slot).
"""

from __future__ import annotations

from PySide6.QtGui import QColor

#: Text/accent color per category (official `color` field).
CATEGORY_COLORS: dict[str | None, str] = {
    "Amp": "#DD1111",
    "Cab": "#DD1111",
    "Dist": "#f5901e",
    "Dyn": "#DDCC00",
    "EQ": "#DDCC00",
    "Mod": "#0094E9",
    "Delay": "#00CC00",
    "Reverb": "#FF5C00",
    "Pitch": "#AD46E2",
    "Filter": "#AD46E2",
    "Wah": "#A844DB",
    "Vol": "#38A696",
    "Send/Return": "#9C9C9C",
    "Looper": "#9C9C9C",
    "Otros": "#9C9C9C",
    None: "#606060",
}

#: General app background (POD Go Edit main window).
BACKGROUND = "#18191b"
#: Loaded preset in the Librarian (amber text).
LOADED_AMBER = "#f5a623"


def category_color(category: str | None) -> str:
    """Official hex for the category ("#606060" for empty/unknown slot)."""
    return CATEGORY_COLORS.get(category, CATEGORY_COLORS["Otros"])


def dimmed(color: str | QColor) -> QColor:
    """Dimmed version of the color (bypassed block): less saturation and value."""
    c = QColor(color)
    h, s, v, a = c.getHsvF()
    return QColor.fromHsvF(max(h, 0.0), s * 0.4, v * 0.5, a)


def tinted_bg(color: str | QColor) -> QColor:
    """Near-black background tinted with the color (official inspector header)."""
    c = QColor(color)
    bg = QColor(BACKGROUND)
    mix = 0.15
    return QColor(
        round(bg.red() * (1 - mix) + c.red() * mix),
        round(bg.green() * (1 - mix) + c.green() * mix),
        round(bg.blue() * (1 - mix) + c.blue() * mix),
    )
