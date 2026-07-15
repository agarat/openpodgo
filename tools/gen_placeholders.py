"""Generate the bundled placeholder assets used when the official res/ is absent.

openpodgo ships no proprietary Line 6 / POD Go Edit artwork. When a user has not
copied their POD Go Edit ``res/`` folder into the repo, the UI falls back to the
neutral, self-drawn placeholders produced by this script (see
``openpodgo.ui.assets``). They are plain colored tiles with a short category
label plus a couple of monochrome chain-endpoint glyphs and a text wordmark — no
Line 6 marks of any kind.

Run headlessly (no display needed)::

    python tools/gen_placeholders.py

Regenerate whenever the category set or palette changes.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPixmap,
)

from openpodgo.ui import palette  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "src/openpodgo/ui/placeholder_assets"

TILE = 128
LIGHT = "#e8eaed"  # label / glyph color on a colored tile

#: Placeholder category tiles: PG_Category_<name>.png → (short label, palette key).
#: The palette key drives the tile color so placeholders match the app's theme.
CATEGORY_TILES: dict[str, tuple[str, str | None]] = {
    "PG_Category_Amp": ("AMP", "Amp"),
    "PG_Category_Preamp": ("PRE", "Amp"),
    "PG_Category_Cab": ("CAB", "Cab"),
    "PG_Category_Cab_Legacy": ("CAB", "Cab"),
    "PG_Category_IR": ("IR", "Cab"),
    "PG_Category_Distortion": ("DRV", "Dist"),
    "PG_Category_Dynamics": ("DYN", "Dyn"),
    "PG_Category_EQ": ("EQ", "EQ"),
    "PG_Category_EQFixed": ("EQ≡", "EQ"),
    "PG_Category_Modulation": ("MOD", "Mod"),
    "PG_Category_Delay": ("DLY", "Delay"),
    "PG_Category_Reverb": ("REV", "Reverb"),
    "PG_Category_Pitch": ("PCH", "Pitch"),
    "PG_Category_Filter": ("FLT", "Filter"),
    "PG_Category_Wah": ("WAH", "Wah"),
    "PG_Category_Volume": ("VOL", "Vol"),
    "PG_Category_FXLoop": ("FX", "Send/Return"),
    "PG_Category_Looper": ("LOOP", "Looper"),
    "PG_Category_None": ("", None),
}


def _fresh(w: int, h: int) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    return pm


def _label_font(text: str, box: int) -> QFont:
    f = QFont()
    f.setBold(True)
    # Shrink for longer labels so they fit the tile.
    size = {0: 40, 1: 52, 2: 46, 3: 40}.get(len(text), 30)
    f.setPixelSize(size)
    return f


def _tile(label: str, palette_key: str | None) -> QPixmap:
    pm = _fresh(TILE, TILE)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    color = QColor(palette.category_color(palette_key))
    p.setBrush(color)
    p.setPen(Qt.NoPen)
    m = 10
    p.drawRoundedRect(QRectF(m, m, TILE - 2 * m, TILE - 2 * m), 22, 22)
    if label:
        p.setPen(QColor(LIGHT))
        p.setFont(_label_font(label, TILE))
        p.drawText(pm.rect(), Qt.AlignCenter, label)
    else:
        # Empty-slot tile: a faint "+".
        p.setPen(QColor(LIGHT))
        f = QFont()
        f.setPixelSize(44)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, "+")
    p.end()
    return pm


def _chain_strip(frames: int, glyph_frame: int, kind: str) -> QPixmap:
    """Vertical frame strip; assets.chain_icon slices frame 1 and tints it.

    Drawn monochrome white on transparent so the tint in assets.py takes.
    """
    pm = _fresh(TILE, TILE * frames)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    top = glyph_frame * TILE
    if kind == "input":
        # A simple plug: a bar with a round head.
        p.drawRoundedRect(QRectF(30, top + 40, 68, 20), 8, 8)
        p.drawEllipse(QRectF(20, top + 34, 32, 32))
    else:
        # Output arrow "→".
        p.drawRoundedRect(QRectF(24, top + 54, 60, 18), 6, 6)
        pts = [
            (72, top + 40),
            (104, top + 63),
            (72, top + 86),
        ]
        from PySide6.QtGui import QPolygonF
        from PySide6.QtCore import QPointF

        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    p.end()
    return pm


def _logo() -> QPixmap:
    pm = _fresh(360, 96)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(LIGHT))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(52)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "openpodgo")
    p.end()
    return pm


def main() -> None:
    QGuiApplication.instance() or QGuiApplication([])
    cat_dir = OUT / "icons" / "category"
    models_dir = OUT / "icons" / "models"
    main_dir = OUT / "images" / "main"
    for d in (cat_dir, models_dir, main_dir):
        d.mkdir(parents=True, exist_ok=True)

    for stem, (label, key) in CATEGORY_TILES.items():
        _tile(label, key).save(str(cat_dir / f"{stem}.png"))

    # Chain endpoints (the "%N" in the name is the frame count).
    _chain_strip(5, 1, "input").save(str(cat_dir / "PG_Category_Input_%5.png"))
    _chain_strip(2, 1, "output").save(str(cat_dir / "PG_Category_Output_%2.png"))

    # Generic model fallback (used only if a category has no tile).
    _tile("", None).save(str(models_dir / "placeholder.png"))

    # Neutral wordmark shown in the librarian header.
    _logo().save(str(main_dir / "PODGoLogo-small.png"))

    print(f"placeholders written under {OUT}")


if __name__ == "__main__":
    main()
