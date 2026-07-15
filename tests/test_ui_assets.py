"""Official palette and res/ assets (icons, sprites, fonts).

The resources live in res/ (extracted from the official POD Go Edit app):
res/icons/models, res/icons/category, res/images/main (+ imageinfo.xml with
multi-state sprites) and res/fonts.
"""

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openpodgo import catalog  # noqa: E402
from openpodgo.ui import assets, palette  # noqa: E402

ROOT = Path(__file__).parent.parent

#: Some tests need the official POD Go Edit res/ (not shipped). Skip them when a
#: user has not copied it in; the placeholder-fallback tests cover that case.
needs_res = pytest.mark.skipif(
    assets.res_root() is None, reason="official res/ not present"
)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


def _ok(pm) -> bool:
    return pm is not None and not pm.isNull()


# --- palette ---


def test_palette_covers_all_categories():
    cats = {catalog.display_category(n) for n in catalog.model_names()}
    cats.discard(None)
    cats.add("Other")
    for cat in cats:
        color = palette.category_color(cat)
        assert color.startswith("#") and len(color) == 7, cat


def test_official_palette_colors():
    # Values from the `color` field of PGModelCatalog.json (official resources).
    assert palette.category_color("Dist").lower() == "#f5901e"
    assert palette.category_color("Mod").lower() == "#0094e9"
    assert palette.category_color("Delay").lower() == "#00cc00"
    assert palette.category_color("Reverb").lower() == "#ff5c00"
    assert palette.category_color("Amp").lower() == "#dd1111"
    assert palette.category_color("Cab").lower() == "#dd1111"
    assert palette.category_color("Dyn").lower() == "#ddcc00"
    assert palette.category_color("EQ").lower() == "#ddcc00"
    assert palette.category_color("Pitch").lower() == "#ad46e2"
    assert palette.category_color("Wah").lower() == "#a844db"
    assert palette.category_color("Vol").lower() == "#38a696"


def test_dimmed_drops_color():
    from PySide6.QtGui import QColor

    bright = QColor("#f5901e")
    dimmed = palette.dimmed("#f5901e")
    assert dimmed.valueF() < bright.valueF()
    assert dimmed.saturationF() < bright.saturationF()


def test_tinted_bg_is_dark():
    bg = palette.tinted_bg("#DD1111")
    # Mostly background mix: much darker than the pure color, but
    # retains the tint (in red, the R channel dominates).
    assert bg.valueF() < 0.35
    assert bg.red() > bg.green() and bg.red() > bg.blue()


# --- icon map ---


@needs_res
def test_icon_map_exists_and_points_to_real_files():
    data = json.loads(
        (ROOT / "src/openpodgo/data/icon_map.json").read_text(encoding="utf-8")
    )
    assert len(data) >= 500  # 520 auto-mapped + overrides
    icons_dir = ROOT / "res/icons/models"
    for name, fname in data.items():
        assert (icons_dir / fname).is_file(), f"{name} → {fname} not found"


def test_every_swappable_has_pixmap(app):
    # Via icon_map or fallback to category icon (HD2_PreampVintagePre is
    # the only one without its own icon in official resources).
    missing = []
    for name in catalog.model_names():
        info = catalog.model_info(name)
        if info is None or info.wire_id is None or info.param_order is None:
            continue
        pm = assets.model_icon(name)
        if pm is None or pm.isNull():
            missing.append(name)
    assert missing == []


# --- assets ---


def test_model_icon(app):
    pm = assets.model_icon("HD2_DM4TubeDrive")
    assert pm is not None and not pm.isNull()


def test_model_icon_fallback_category(app):
    # A non-existent model falls back to its category icon (None here) or None.
    assert assets.model_icon("NoExiste") is None


def test_category_icon(app):
    for cat in ("Amp", "Cab", "Dist", "Delay", "Looper"):
        pm = assets.category_icon(cat)
        assert pm is not None and not pm.isNull(), cat


def test_category_icon_eq_kind(app):
    # spec08: Preset EQ uses the sliders icon (EQFixed); Effects EQ uses the
    # knobs icon (EQ, the historical default for the category).
    preset = assets.category_icon("EQ", eq_kind="preset")
    effects = assets.category_icon("EQ", eq_kind="effects")
    assert preset is not None and not preset.isNull()
    assert effects is not None and not effects.isNull()
    assert preset.toImage() != effects.toImage()
    # Effects = default for the EQ category; without eq_kind the rest doesn't change.
    assert effects.toImage() == assets.category_icon("EQ").toImage()


@needs_res
def test_ui_image_slices_sprites(app):
    # btn-preset-save: rows=4 per imageinfo.xml → each frame is 1/4 the height.
    f0 = assets.ui_image("btn-preset-save", frame=0)
    f3 = assets.ui_image("btn-preset-save", frame=3)
    assert f0 is not None and f3 is not None
    assert f0.height() == f3.height()
    full = assets.ui_image("btn-undo")  # rows=1: full image
    assert full is not None and not full.isNull()


def test_ui_image_nonexistent(app):
    assert assets.ui_image("no-existe") is None


@needs_res
def test_load_fonts(app):
    families = assets.load_fonts()
    assert any("Roboto" in f for f in families)


# --- placeholder fallback (no official res/) ---


def test_placeholders_resolve_without_official_res(app, monkeypatch):
    """With res/ absent, icons fall back to the bundled neutral placeholders."""
    monkeypatch.setattr(assets, "res_root", lambda: None)
    for fn in (assets._sprite_grid, assets.chain_icon, assets.ui_image):
        fn.cache_clear()

    # Category tiles resolve for every UI category.
    for cat in ("Amp", "Cab", "Dist", "Delay", "Reverb", "Looper", None):
        assert _ok(assets.category_icon(cat)), cat
    # Chain endpoints resolve (sliced + tinted from the placeholder strip).
    assert _ok(assets.chain_icon("input"))
    assert _ok(assets.chain_icon("output"))
    # A real model with no bundled icon falls back to its category placeholder.
    assert _ok(assets.model_icon("HD2_DM4TubeDrive"))
    # Neutral wordmark used in the librarian header.
    assert _ok(assets.ui_image("PODGoLogo-small"))

    for fn in (assets._sprite_grid, assets.chain_icon, assets.ui_image):
        fn.cache_clear()
