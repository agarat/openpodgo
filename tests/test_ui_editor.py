"""Offscreen smoke tests of the editor view (no pedal).

Exercises the public API of the widgets (the same ones triggered by signals)
over the BassPreset fixture.
"""

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openpodgo import editor, l6helix  # noqa: E402
from openpodgo.ui.editor import EditorView, short_name  # noqa: E402

CAPS = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _view(app) -> EditorView:
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    view = EditorView()
    view.set_preset(editor.PresetEditor(l6helix.parse_blob(blob)), "BassPreset")
    return view


def _slot_of(view: EditorView, model_id: int) -> int:
    for i, blk in enumerate(view.editor.preset.chain):
        if blk is not None and blk.model_id == model_id:
            return i
    raise AssertionError(f"model {model_id} is not in the chain")


def test_chain_rendered(app):
    view = _view(app)
    # input + 10 slots + output
    assert len(view.chain.slot_widgets) == 10
    labels = [w.model_text() for w in view.chain.slot_widgets]
    assert any("Tube Drive" in t for t in labels)
    # BassPreset has one empty slot
    assert sum(1 for w in view.chain.slot_widgets if w.is_empty) == 1


def test_toggle_bypass_control_panel(app):
    view = _view(app)
    slot = _slot_of(view, 366)  # Tube Drive
    view.select_slot(slot)
    assert view.bypass_panel.isHidden()
    # The header button toggles the panel and populates it with the active slot.
    view.inspector.header.bypass_btn.setChecked(True)
    assert not view.bypass_panel.isHidden()
    assert view.bypass_panel.slot == slot
    # An assignment from the panel marks the preset as edited.
    view.modified = False
    view.bypass_panel._select("FS3")
    assert view.editor.bypass_target(slot) == "FS3"
    assert view.modified is True
    # Close by unchecking the button.
    view.bypass_panel.close_requested.emit()
    assert view.bypass_panel.isHidden()
    assert not view.inspector.header.bypass_btn.isChecked()


def test_assign_bypass_desde_signal_flow(app):
    view = _view(app)
    slot = _slot_of(view, 366)  # Tube Drive (FS4)
    view.modified = False
    view.assign_bypass(slot, "FS3")
    assert view.editor.bypass_target(slot) == "FS3"
    assert view.modified is True
    view.assign_bypass(slot, None)
    assert view.editor.bypass_target(slot) is None


def test_clear_slot_syncs_to_pedal(app):
    # Emptying a slot triggers a full blob dump (op 21).
    view = _view(app)
    emitted = []
    view.chain_write_requested.connect(lambda: emitted.append(True))
    slot = _slot_of(view, 366)
    view.clear_slot(slot)
    assert view.editor.preset.chain[slot] is None
    assert emitted


def test_assign_bypass_syncs_to_pedal(app):
    # Changing the bypass assignment also dumps the blob (body[3]).
    view = _view(app)
    emitted = []
    view.chain_write_requested.connect(lambda: emitted.append(True))
    slot = _slot_of(view, 366)
    view.assign_bypass(slot, "FS3")
    assert emitted


def test_panel_assignment_syncs_to_pedal(app):
    # An assignment made from the Bypass/Control panel dumps the blob.
    view = _view(app)
    emitted = []
    view.chain_write_requested.connect(lambda: emitted.append(True))
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    view.inspector.header.bypass_btn.setChecked(True)
    view.bypass_panel._select("FS5")
    assert view.editor.bypass_target(slot) == "FS5"
    assert emitted


def test_short_name():
    assert short_name("HD2_DM4TubeDrive") == "DM4 Tube Drive"
    assert short_name("HD2_AmpGCougar800") == "G Cougar 800"
    assert short_name("VIC_ReverbDynRoomStereo") == "Dyn Room"


def test_selection_shows_params(app):
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    names = [row.label for row in view.inspector.rows]
    assert names == ["Drive", "Bass", "Mid", "Treble", "Output"]


def test_edit_param_updates_model(app):
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    row = view.inspector.rows[0]
    row.set_value(0.55)
    assert view.editor.preset.chain[slot].params[0] == pytest.approx(0.55, abs=1e-3)
    assert view.modified


def test_mark_saved_clears_indicator(app):
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    view.inspector.rows[0].set_value(0.55)
    assert view.modified
    view.mark_saved()
    assert not view.modified


def test_select_io_shows_params(app):
    # #2: clicking the Input/Output node shows its params in the inspector.
    view = _view(app)
    view.select_io("input")
    assert [r.label for r in view.inspector.rows] == [
        "Input Gate", "Threshold", "Decay"
    ]
    view.inspector.rows[1].set_value(-30.0)
    assert view.editor.io_values("input")[1] == pytest.approx(-30.0, abs=0.1)
    assert view.modified
    view.select_io("output")
    assert [r.label for r in view.inspector.rows] == ["Pan", "Level"]
    # The Output node is marked as selected in the chain.
    assert view.chain.io_output.selected
    assert not view.chain.io_input.selected


def test_toggle_bypass(app):
    view = _view(app)
    slot = _slot_of(view, 366)
    was = view.editor.preset.chain[slot].enabled
    view.toggle_bypass(slot)
    assert view.editor.preset.chain[slot].enabled is not was


def test_swap_model_refreshes_chain(app):
    view = _view(app)
    slot = _slot_of(view, 366)
    view.apply_model(slot, "HD2_DistTriangleFuzzMono")
    assert view.editor.preset.chain[slot].model_id == 95
    assert any(
        "Triangle Fuzz" in w.model_text() for w in view.chain.slot_widgets
    )
    assert view.modified


def test_export_pgp(app, tmp_path):
    view = _view(app)
    out = tmp_path / "export.pgp"
    view.export_pgp(out)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "L6Preset"
    assert doc["data"]["meta"]["name"] == "BassPreset"


def test_choose_model_from_inspector_applies_swap(app):
    # The embedded Model Select replaces the old ModelPickerDialog (its
    # swappable universe is tested in test_ui_inspector).
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    view.inspector.set_mode("models")
    view.inspector.models.set_filter("triangle")
    view.inspector.models.choose_first()
    assert view.editor.preset.chain[slot].model_id == 95
    assert view.inspector.mode() == "edit"  # back to Edit panel
    assert view.modified


def test_set_preset_keep_state_preserves_modified_and_selection(app):
    # #2 + #4: a re-read from pedal-reorder must NOT lose the ● or jump
    # the selection to the first block.
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    view.inspector.rows[0].set_value(0.55)  # marca modified=True
    assert view.modified and view._selected == slot

    # new editor (like the one built by re-read), preserving state
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    view.set_preset(
        editor.PresetEditor(l6helix.parse_blob(blob)),
        "BassPreset",
        keep_state=True,
    )
    assert view.modified is True
    assert view._selected == slot


def test_set_preset_without_keep_state_resets(app):
    # Normal path (real preset change): resets ● and selects the 1st block.
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    view.inspector.rows[0].set_value(0.55)
    assert view.modified

    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    view.set_preset(
        editor.PresetEditor(l6helix.parse_blob(blob)), "BassPreset"
    )
    assert view.modified is False
    first = next(
        (i for i, b in enumerate(view.editor.preset.chain) if b is not None),
        None,
    )
    assert view._selected == first


def test_set_preset_modified_true_starts_with_indicator(app):
    # spec 06: the pedal reports the active preset as edited → starts with ●.
    view = _view(app)
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    view.set_preset(
        editor.PresetEditor(l6helix.parse_blob(blob)),
        "BassPreset",
        modified=True,
    )
    assert view.modified is True
    assert "●" in view.toolbar.title_label.text()


def test_set_preset_modified_false_starts_clean(app):
    # By default (un-edited preset) starts clean: ○, no ●.
    view = _view(app)
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    view.set_preset(
        editor.PresetEditor(l6helix.parse_blob(blob)),
        "BassPreset",
        modified=False,
    )
    assert view.modified is False
    assert "●" not in view.toolbar.title_label.text()


def test_set_preset_keep_state_ignores_modified(app):
    # Regression guard spec 05: with keep_state=True the reorder path
    # preserves the previous modified and does NOT overwrite it with the
    # new `modified` arg.
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    view.inspector.rows[0].set_value(0.55)  # marca modified=True
    assert view.modified

    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    view.set_preset(
        editor.PresetEditor(l6helix.parse_blob(blob)),
        "BassPreset",
        keep_state=True,
        modified=False,
    )
    assert view.modified is True


def test_import_pgp(app, tmp_path, monkeypatch, preset_a):
    """Importing a .pgp loads the preset into the editor via context menu."""
    import shutil
    from PySide6.QtWidgets import QFileDialog
    from openpodgo.ui.main_window import MainWindow

    win = MainWindow(autoconnect=False)
    win.librarian._loaded = 0  # slot destino

    pgp_path = tmp_path / "test.pgp"
    shutil.copy2(preset_a, pgp_path)

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **kw: (str(pgp_path), "POD Go Preset (*.pgp)"))

    win._import_preset_to(0)

    ed = win.editor_view.editor
    assert ed is not None, "Editor should have content after import"
    assert len(ed.preset.chain) > 0, "Chain should have entries"


def test_import_pgp_unknown_model_warning(app, tmp_path, monkeypatch):
    """Importing a .pgp with an unknown model → empty slot + QMessageBox."""
    import json
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from openpodgo.ui.main_window import MainWindow

    # No modal in offscreen: silence QMessageBox.information
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)

    win = MainWindow(autoconnect=False)

    pgp_path = tmp_path / "unknown.pgp"
    dsp0 = {
        "input": {"@input": 0, "@model": "P34_AppDSPFlowInput",
                  "noiseGate": True, "threshold": -60.0, "decay": 0.05},
        "output": {"@model": "P34_AppDSPFlowOutput", "@output": 0,
                   "pan": 0.5, "gain": 0.0},
    }
    dsp0["block0"] = {"@position": 0, "@model": "FAKE_Unknown", "@enabled": True}
    for i in range(1, 10):
        dsp0[f"block{i}"] = {"@position": i, "@model": "FAKE_Unknown",
                             "@enabled": False}
    pgp_path.write_text(json.dumps({
        "schema": "L6Preset",
        "version": 6,
        "meta": {"original": 0, "pbn": 0, "premium": 0},
        "data": {
            "device": 2162695,
            "device_version": 33619968,
            "meta": {"application": "POD Go Edit", "appversion": 33554432,
                     "name": "Test", "modifieddate": 0},
            "tone": {
                "controller": {"dsp0": {}},
                "dsp0": dsp0,
                "dsp1": {},
                "footswitch": {"dsp0": {}},
                "global": {"@current_snapshot": 0, "@tempo": 120.0,
                           "@pedalstate": 0},
            },
        },
    }, indent=2))

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **kw: (str(pgp_path), "POD Go Preset (*.pgp)"))

    win._import_preset_to(0)

    ed = win.editor_view.editor
    assert ed is not None
    assert ed.preset.chain[0] is None, "Unknown model should become empty slot"
