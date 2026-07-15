"""POD Go Edit-style inspector: tinted header, Edit panel with category-colored
sliders and embedded Model Select (replaces the modal dialog)."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openpodgo import catalog, editor, l6helix  # noqa: E402
from openpodgo.ui.inspector import (  # noqa: E402
    InspectorPanel,
    ModelSelectPanel,
    ParamRow,
    available_models,
)

CAPS = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _editor(bin_name: str = "spec02_knob.bin") -> editor.PresetEditor:
    blob = l6helix.extract_blob((CAPS / bin_name).read_bytes())
    return editor.PresetEditor(l6helix.parse_blob(blob))


def _slot_of(ed, model_id: int) -> int:
    for i, blk in enumerate(ed.preset.chain):
        if blk is not None and blk.model_id == model_id:
            return i
    raise AssertionError(f"model {model_id} is not in the chain")


def _inspector(app, ed=None, slot=None):
    ed = ed or _editor()
    slot = slot if slot is not None else _slot_of(ed, 366)
    panel = InspectorPanel()
    panel.show_block(ed, slot, lambda: None)
    return panel, ed, slot


# --- header ---


def test_header_categoria_y_modelo(app):
    panel, _ed, _slot = _inspector(app)
    assert panel.header.category_label.text() == "Dist"
    assert "Tube Drive" in panel.header.model_label.text()


def test_power_button_emite_bypass(app):
    panel, _ed, slot = _inspector(app)
    got = []
    panel.bypass_toggled.connect(got.append)
    panel.header.power_btn.click()
    assert got == [slot]


def test_toggle_cambia_a_model_select(app):
    panel, _ed, _slot = _inspector(app)
    assert panel.mode() == "edit"
    panel.header.toggle_btn.click()
    assert panel.mode() == "models"
    panel.header.toggle_btn.click()
    assert panel.mode() == "edit"


# --- edit panel ---


def test_rows_use_catalog_names(app):
    panel, _ed, _slot = _inspector(app)
    assert [r.label for r in panel.rows] == [
        "Drive", "Bass", "Mid", "Treble", "Output",
    ]


def test_editing_row_mutates_editor(app):
    ed = _editor()
    slot = _slot_of(ed, 366)
    panel = InspectorPanel()
    changes = []
    panel.show_block(ed, slot, lambda: changes.append(1))
    panel.rows[0].set_value(0.55)
    assert ed.preset.chain[slot].params[0] == pytest.approx(0.55, abs=1e-3)
    assert changes


def test_spinbox_knob_muestra_x100(app):
    panel, _ed, _slot = _inspector(app)
    row = panel.rows[0]
    assert row.spin.textFromValue(0.47) == "47.0"
    assert row.spin.valueFromText("47.0") == pytest.approx(0.47)


def test_param_bool_usa_combo(app):
    from PySide6.QtWidgets import QComboBox

    ed = _editor()
    slot = _slot_of(ed, 224)  # VolPan: [Pedal, VolumeTaper(bool)]
    panel = InspectorPanel()
    panel.show_block(ed, slot, lambda: None)
    row = panel.rows[1]
    assert isinstance(row.widget, QComboBox)
    assert row.combo is not None
    labels = [row.combo.itemText(i) for i in range(row.combo.count())]
    assert labels == ["Linear", "Logarithmic"]  # catalog labels
    assert row.combo.currentIndex() == 0  # initial value False → index 0
    # select "Logarithmic" (index 1) writes True (bool) to the editor.
    row.combo.setCurrentIndex(1)
    assert ed.preset.chain[slot].params[1] is True


def test_param_bool_sin_labels_sintetiza_off_on(app):
    from PySide6.QtWidgets import QComboBox

    got = []
    # spec=None and boolean value: no labels → synthesize Off/On.
    row = ParamRow("Switch", False, None, got.append)
    assert isinstance(row.widget, QComboBox)
    labels = [row.combo.itemText(i) for i in range(row.combo.count())]
    assert labels == ["Off", "On"]
    row.combo.setCurrentIndex(1)
    assert got == [True]  # emits bool, not int
    assert got[0] is True


def test_param_enum_2_valores_emite_int(app):
    from PySide6.QtWidgets import QComboBox
    from openpodgo import catalog

    # Discrete with 2 values, non-boolean (value_type=0 + control labels).
    spec = catalog.ParamSpec(
        vmin=0.0, vmax=1.0, is_bool=False,
        value_type=0, display_type="volume_curve",
    )
    got = []
    row = ParamRow("Curve", 0.0, spec, got.append)
    assert isinstance(row.widget, QComboBox)
    assert row.combo.count() == 2
    row.combo.setCurrentIndex(1)
    # enum → vmin + index = 1 (int), not bool.
    assert got == [1]
    assert isinstance(got[0], int) and not isinstance(got[0], bool)


def test_param_bool_valor_inicial_selecciona_item(app):
    # Initial value True → combo starts at index 1.
    row = ParamRow("Switch", True, None, lambda _v: None)
    assert row.combo.currentIndex() == 1


def test_param_enum_usa_combo(app):
    from PySide6.QtWidgets import QComboBox

    ed = _editor()
    slot = _slot_of(ed, 255)  # Auto Filter: param 0 = Mode (mode_pass, enum)
    panel = InspectorPanel()
    panel.show_block(ed, slot, lambda: None)
    mode = panel.rows[0]
    assert mode.label == "Mode"
    assert isinstance(mode.widget, QComboBox)
    assert mode.combo is not None
    labels = [mode.combo.itemText(i) for i in range(mode.combo.count())]
    assert labels == ["Low Pass", "Band Pass", "High Pass"]
    # select "High Pass" (index 2) writes integer value 2 to the editor.
    mode.combo.setCurrentIndex(2)
    assert ed.preset.chain[slot].params[0] == 2


def test_continuous_still_uses_slider(app):
    from PySide6.QtWidgets import QSlider

    panel, _ed, _slot = _inspector(app)  # DM4 Tube Drive: continuous params
    assert isinstance(panel.rows[0].widget, QSlider)
    assert panel.rows[0].combo is None


def test_same_block_does_not_rebuild_rows(app):
    panel, ed, slot = _inspector(app)
    rows_before = panel.rows
    ed.set_param(slot, 0, 0.61)
    panel.show_block(ed, slot, lambda: None)
    assert panel.rows is rows_before  # only update_values, no rebuild
    assert panel.rows[0].spin.value() == pytest.approx(0.61, abs=1e-3)


def test_empty_slot_opens_model_select(app):
    ed = _editor()
    panel = InspectorPanel()
    panel.show_block(ed, 9, lambda: None)  # empty slot from fixture
    assert panel.mode() == "models"
    assert "empty" in panel.header.model_label.text().lower()


# --- model select ---


def test_inspector_restricts_categories_amp(app):
    # #5: in an Amp slot only the Amp category is visible and it can't be cleared.
    ed = _editor()
    slot = _slot_of(ed, 3)  # HD2_AmpGCougar800
    panel = InspectorPanel()
    panel.show_block(ed, slot, lambda: None)
    cats = panel.models._cat_buttons
    assert not cats["Amp"].isHidden()
    assert cats["Delay"].isHidden()
    assert panel.models.none_btn.isHidden()  # Preset block: can't be cleared


def test_inspector_effects_block_allows_effects(app):
    # #5: an Effects block sees the effects categories and can be cleared.
    ed = _editor()
    slot = _slot_of(ed, 366)  # HD2_DM4TubeDrive (Dist)
    panel = InspectorPanel()
    panel.show_block(ed, slot, lambda: None)
    cats = panel.models._cat_buttons
    assert not cats["Delay"].isHidden()
    assert cats["Amp"].isHidden()
    assert cats["Cab"].isHidden()
    assert not panel.models.none_btn.isHidden()


def test_picker_preset_eq_shows_only_static(app):
    # spec08: in a Preset EQ slot the picker shows the 7 STATIC EQs, without
    # Acoustic Sim (which only exists as an Effects EQ).
    ed = _editor("eq_acoustic_sim_obj22.bin")
    slot = _slot_of(ed, 472)  # HD2_EQ_STATIC_ParametricStereo
    panel = InspectorPanel()
    panel.show_block(ed, slot, lambda: None)
    panel.models.select_category("EQ")
    vis = panel.models.visible_models()
    assert vis
    assert all(catalog.eq_kind(n) == "preset" for n in vis), vis
    assert len(vis) == 7
    assert "L6SPB_AcousGtrSimStereo" not in vis


def test_picker_effects_block_shows_eq_no_static(app):
    # spec08: in an Effects block the picker shows the 8 non-STATIC EQs, with
    # Acoustic Sim included.
    ed = _editor("eq_acoustic_sim_obj22.bin")
    slot = _slot_of(ed, 287)  # HD2_DistStuporODMono (Effects block)
    panel = InspectorPanel()
    panel.show_block(ed, slot, lambda: None)
    panel.models.select_category("EQ")
    vis = panel.models.visible_models()
    assert vis
    assert all(catalog.eq_kind(n) == "effects" for n in vis), vis
    assert len(vis) == 8
    assert "L6SPB_AcousGtrSimStereo" in vis


def test_model_select_solo_intercambiables(app):
    panel = ModelSelectPanel()
    names = panel.visible_models()
    assert len(names) > 400  # official resources: amps, legacy cabs, FX…
    assert "HD2_DM4TubeDrive" in names
    assert "HD2_DistMinotaurMono" in names      # already swappable
    assert "HD2_Compressor3BandCompMono" in names  # harvested on-wire category
    assert "HD2_LooperMono" in names  # looper: class-7 insertion supported
    assert "P34_AppDSPFlowInput" not in names
    panel.set_filter("triangle")
    assert panel.visible_models() == ["HD2_DistTriangleFuzzMono"]


def test_model_select_filter_by_category(app):
    panel = ModelSelectPanel()
    panel.select_category("Delay")
    names = panel.visible_models()
    assert names
    from openpodgo import catalog

    assert all(catalog.display_category(n) == "Delay" for n in names)


def test_model_select_click_emits_and_returns_to_edit(app):
    panel, _ed, slot = _inspector(app)
    panel.header.toggle_btn.click()
    chosen = []
    panel.model_chosen.connect(lambda s, n: chosen.append((s, n)))
    panel.models.set_filter("triangle")
    panel.models.choose_first()
    assert chosen == [(slot, "HD2_DistTriangleFuzzMono")]


def test_model_select_none_emits_clear(app):
    panel, _ed, slot = _inspector(app)
    cleared = []
    panel.clear_requested.connect(cleared.append)
    panel.header.toggle_btn.click()
    panel.models.none_btn.click()
    assert cleared == [slot]


def test_model_select_subtabs_amp_preamp(app):
    # Swapping an Amp offers preamps: the "Preamp" sub-tab filters to preamps.
    from openpodgo import catalog
    panel = ModelSelectPanel()
    panel.set_allowed_categories(catalog.swap_group("Amp"), can_clear=False)
    panel.set_current_model("HD2_AmpGCougar800")
    assert not panel._subcat_bar.isHidden()
    assert [b.text() for b in panel._subcat_buttons] == ["All", "Amp", "Preamp"]
    # "All" includes both amps AND preamps.
    vis_all = panel.visible_models()
    assert any("preamp" in n.lower() for n in vis_all)
    assert any("amp" in n.lower() and "preamp" not in n.lower() for n in vis_all)
    # Sub-tab Preamp shows only preamps.
    panel._set_subcategory("Preamp")
    vis = panel.visible_models()
    assert vis and all(
        catalog.model_info(n).subcategory == "Preamp" for n in vis
    )


def test_model_select_subtabs_cab_legacy_ir(app):
    from openpodgo import catalog
    panel = ModelSelectPanel()
    panel.set_allowed_categories(catalog.swap_group("Cab"), can_clear=False)
    panel.set_current_model("HD2_Cab4x10Rhino")
    labels = [b.text() for b in panel._subcat_buttons]
    assert labels == ["All", "Cab", "Legacy Cab", "Impulse Response"]


def test_model_select_effects_no_subtabs(app):
    # A pure effect (Dist) has no subcategories → no sub-tab row.
    from openpodgo import catalog
    panel = ModelSelectPanel()
    panel.set_allowed_categories(catalog.swap_group("Dist"), can_clear=True)
    panel.set_current_model("HD2_DistTriangleFuzzMono")
    assert panel._subcat_bar.isHidden()


def test_available_models_is_the_old_picker_universe(app):
    names = [n for n, _short, _cat in available_models()]
    assert len(names) == len(set(names))
    assert "HD2_DM4TubeDrive" in names
