"""Loading of official POD Go Edit assets (res/ at the repo root).

- Model icons (res/icons/models) via data/icon_map.json, with fallback to the
  category icon (res/icons/category) — HD2_PreampVintagePre is the only model
  without its own icon in the assets.
- UI images (res/images/main): many are multi-state sprites; frames
  (normal/hover/pressed/disabled) are sliced according to imageinfo.xml.
- Fonts (res/fonts): Roboto is the official app's font.

Everything is tolerant of a missing res/ (returns None): the UI degrades to text.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from .. import catalog

_DATA = Path(__file__).parent.parent / "data"

#: Bundled neutral placeholder assets, used when the official res/ (or a
#: specific file within it) is absent. Shipped with the project; no Line 6 art.
_PLACEHOLDERS = Path(__file__).parent / "placeholder_assets"

#: UI category → PG_Category_*.png icon.
_CATEGORY_FILES = {
    "Amp": "PG_Category_Amp.png",
    "Cab": "PG_Category_Cab.png",
    "Dist": "PG_Category_Distortion.png",
    "Dyn": "PG_Category_Dynamics.png",
    "EQ": "PG_Category_EQ.png",
    "Mod": "PG_Category_Modulation.png",
    "Delay": "PG_Category_Delay.png",
    "Reverb": "PG_Category_Reverb.png",
    "Pitch": "PG_Category_Pitch.png",
    "Filter": "PG_Category_Filter.png",
    "Wah": "PG_Category_Wah.png",
    "Vol": "PG_Category_Volume.png",
    "Send/Return": "PG_Category_FXLoop.png",
    "Looper": "PG_Category_Looper.png",
    "Otros": "PG_Category_None.png",
    None: "PG_Category_None.png",
}
#: Dedicated Preset EQ icon (spec08): the sliders, vs PG_Category_EQ.png
#: (the box with knobs) used for the Effects EQ.
_EQ_PRESET_FILE = "PG_Category_EQFixed.png"
#: Chain endpoint icons (yes, the % is part of the filename).
INPUT_ICON = "PG_Category_Input_%5.png"
OUTPUT_ICON = "PG_Category_Output_%2.png"
#: Color used to tint the monochrome endpoint glyphs (the official sprite is
#: nearly black/transparent: without tinting it is invisible on the background).
CHAIN_ICON_TINT = "#c9cdd3"


def _tinted(pm: QPixmap, color: str) -> QPixmap:
    """Recolors a monochrome glyph preserving its alpha channel (SourceIn)."""
    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, pm)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


#: Tint for the drawn (vector) toolbar glyphs used when the official res/ art
#: is absent. Matches the light-on-dark look of the rest of the UI.
TOOLBAR_GLYPH_TINT = "#c9cdd3"


def _stroke_painter(pm: QPixmap, color: str, width: float) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), width)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    return p


def _draw_save(p: QPainter, r: QRectF) -> None:
    """Floppy-disk glyph (the universal 'save' icon)."""
    fold = r.width() * 0.26
    body = QPainterPath()
    body.moveTo(r.left(), r.top())
    body.lineTo(r.right() - fold, r.top())
    body.lineTo(r.right(), r.top() + fold)
    body.lineTo(r.right(), r.bottom())
    body.lineTo(r.left(), r.bottom())
    body.closeSubpath()
    p.drawPath(body)
    # Top shutter (small solid tab).
    sh = QRectF(
        r.left() + r.width() * 0.30, r.top(),
        r.width() * 0.30, r.height() * 0.26,
    )
    p.fillRect(sh, p.pen().color())
    # Bottom label area.
    lab = QRectF(
        r.left() + r.width() * 0.20, r.top() + r.height() * 0.52,
        r.width() * 0.60, r.height() * 0.36,
    )
    p.drawRect(lab)


def _draw_camera(p: QPainter, r: QRectF) -> None:
    """Camera glyph (snapshots)."""
    top = r.top() + r.height() * 0.18
    body = QRectF(r.left(), top, r.width(), r.bottom() - top)
    p.drawRoundedRect(body, r.width() * 0.14, r.width() * 0.14)
    # Viewfinder bump.
    bump = QPainterPath()
    bx0 = r.left() + r.width() * 0.28
    bump.moveTo(bx0, top)
    bump.lineTo(bx0 + r.width() * 0.10, r.top())
    bump.lineTo(bx0 + r.width() * 0.34, r.top())
    bump.lineTo(bx0 + r.width() * 0.44, top)
    p.drawPath(bump)
    # Lens.
    cy = (top + r.bottom()) / 2
    lens = r.width() * 0.20
    p.drawEllipse(QPointF(r.center().x(), cy), lens, lens)


def _draw_undo(p: QPainter, r: QRectF, mirror: bool = False) -> None:
    """Curved 'undo' arrow — a top semicircle with a down-pointing head on the
    left end (mirror=True flips it horizontally for 'redo')."""
    if mirror:
        p.save()
        p.translate(r.center().x() * 2, 0)
        p.scale(-1, 1)
    # Top-half arc (right end → over the top → left end).
    arc = QRectF(
        r.left(), r.top() + r.height() * 0.20,
        r.width(), r.height() * 0.95,
    )
    path = QPainterPath()
    path.arcMoveTo(arc, 0)
    path.arcTo(arc, 0, 180)
    p.drawPath(path)
    # Arrowhead at the left end, pointing down.
    tip = path.currentPosition()
    head = r.width() * 0.24
    p.drawLine(tip, QPointF(tip.x() - head * 0.55, tip.y() - head * 0.55))
    p.drawLine(tip, QPointF(tip.x() + head * 0.75, tip.y() - head * 0.30))
    if mirror:
        p.restore()


_GLYPHS = {
    "save": _draw_save,
    "camera": _draw_camera,
    "undo": _draw_undo,
    "redo": lambda p, r: _draw_undo(p, r, mirror=True),
}


@lru_cache(maxsize=None)
def glyph_icon(
    name: str, size: int = 18, color: str = TOOLBAR_GLYPH_TINT
) -> QPixmap | None:
    """Crisp vector fallback icon drawn with QPainter (no res/ needed).

    `name` is one of _GLYPHS. Rendered at 3x and tagged with the device pixel
    ratio so it stays sharp on hi-dpi displays while laying out at `size`.
    """
    draw = _GLYPHS.get(name)
    if draw is None:
        return None
    scale = 3
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = _stroke_painter(pm, color, max(1.4 * scale, size * scale * 0.09))
    pad = size * scale * 0.16
    draw(p, QRectF(pad, pad, size * scale - 2 * pad, size * scale - 2 * pad))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


@lru_cache(maxsize=1)
def res_root() -> Path | None:
    """Root of res/ (searching upward from the package), or None if absent."""
    for parent in Path(__file__).resolve().parents:
        cand = parent / "res"
        if (cand / "icons" / "models").is_dir():
            return cand
    return None


@lru_cache(maxsize=1)
def _icon_map() -> dict[str, str]:
    path = _DATA / "icon_map.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _pixmap(path: str) -> QPixmap | None:
    pm = QPixmap(path)
    return None if pm.isNull() else pm


def _asset_path(rel: str) -> str | None:
    """Resolve an asset path, preferring the official res/, then placeholders.

    Returns the official res/<rel> if it exists, otherwise the bundled
    placeholder, otherwise None (so callers can degrade to text).
    """
    root = res_root()
    if root is not None and (root / rel).is_file():
        return str(root / rel)
    cand = _PLACEHOLDERS / rel
    return str(cand) if cand.is_file() else None


def model_icon(model_name: str) -> QPixmap | None:
    """Official model icon (or its category icon as fallback)."""
    fname = _icon_map().get(model_name)
    if fname is not None:
        path = _asset_path(f"icons/models/{fname}")
        if path is not None:
            pm = _pixmap(path)
            if pm is not None:
                return pm
    if catalog.model_info(model_name) is None:
        return None
    return category_icon(catalog.display_category(model_name))


def category_icon(
    category: str | None, eq_kind: str | None = None
) -> QPixmap | None:
    """PG_Category_* icon for a UI category (None = empty slot).

    For EQ (spec08), `eq_kind="preset"` returns the dedicated Preset EQ
    sliders icon; any other case uses PG_Category_EQ.png (Effects EQ),
    which is the historical default for the category.
    """
    if category == "EQ" and eq_kind == "preset":
        fname = _EQ_PRESET_FILE
    else:
        fname = _CATEGORY_FILES.get(category, _CATEGORY_FILES["Otros"])
    path = _asset_path(f"icons/category/{fname}")
    return _pixmap(path) if path is not None else None


@lru_cache(maxsize=None)
def chain_icon(kind: str) -> QPixmap | None:
    """Chain endpoint icon ("input" / "output").

    Files carry the frame count in the name (Line 6's %N convention):
    Input_%5 = [empty, guitar, wireless, guitar+wireless, USB],
    Output_%2 = [✕, arrow]. Input's frame 0 is EMPTY (hence the "missing"
    icon): the guitar is frame 1. Output uses the arrow (frame 1).
    """
    fname, frame = (INPUT_ICON, 1) if kind == "input" else (OUTPUT_ICON, 1)
    path = _asset_path(f"icons/category/{fname}")
    if path is None:
        return None
    pm = _pixmap(path)
    if pm is None:
        return None
    m = re.search(r"_%(\d+)\.png$", fname)
    frames = int(m.group(1)) if m else 1
    h = pm.height() // frames
    glyph = pm.copy(0, frame * h, pm.width(), h)
    # The sprite is dark monochrome: tint it light so it is visible (the
    # Input guitar frame is nearly invisible without this).
    return _tinted(glyph, CHAIN_ICON_TINT)


@lru_cache(maxsize=1)
def _sprite_grid() -> dict[str, tuple[int, int]]:
    """name → (rows, columns) according to imageinfo.xml."""
    root = res_root()
    if root is None:
        return {}
    path = root / "images" / "main" / "imageinfo.xml"
    if not path.is_file():
        return {}
    out: dict[str, tuple[int, int]] = {}
    for el in ET.parse(path).getroot().iter("image"):
        out[(el.text or "").strip()] = (
            int(el.get("rows", 1)),
            int(el.get("columns", 1)),
        )
    return out


@lru_cache(maxsize=None)
def ui_image(name: str, frame: int = 0) -> QPixmap | None:
    """Frame of a res/images/main image (sprites per imageinfo.xml).

    Frames are in row-major order: for buttons (columns=1), 0 is the normal
    state, 1 is hover/on, etc.
    """
    path = _asset_path(f"images/main/{name}.png")
    if path is None:
        return None
    pm = _pixmap(path)
    if pm is None:
        return None
    rows, cols = _sprite_grid().get(name, (1, 1))
    if (rows, cols) == (1, 1):
        return pm
    w, h = pm.width() // cols, pm.height() // rows
    row, col = divmod(frame, cols)
    if row >= rows:
        return None
    return pm.copy(col * w, row * h, w, h)


@lru_cache(maxsize=1)
def load_fonts() -> tuple[str, ...]:
    """Registers fonts from res/fonts; returns the loaded families."""
    root = res_root()
    if root is None:
        return ()
    families: list[str] = []
    for path in sorted((root / "fonts").glob("*")):
        if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return tuple(dict.fromkeys(families))
