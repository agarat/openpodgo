"""Panel Bypass/Control (spec 09): grilla de selectores + Min/Max + lista."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openpodgo import editor, l6helix  # noqa: E402
from openpodgo.ui.bypass_control import (  # noqa: E402
    AssignmentsListDialog,
    BypassControlPanel,
)

CAPS = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _editor(bin_name: str = "spec02_knob.bin") -> editor.PresetEditor:
    blob = l6helix.extract_blob((CAPS / bin_name).read_bytes())
    return editor.PresetEditor(l6helix.parse_blob(blob))


# Slots: 0=VolPan, 1=Wah, 2=TubeDrive, 5=Amp.


def test_param_menu_y_seleccion_bypass(app):
    ed = _editor()
    p = BypassControlPanel()
    p.show_block(ed, 2)  # Tube Drive, bypass on FS4
    # First item = Bypass, with its indicator.
    assert "Bypass" in p.param_menu.itemText(0)
    assert "FS4" in p.param_menu.itemText(0)
    # The FS4 selector is checked.
    assert p._buttons["FS4"].isChecked()
    assert not p._buttons["None"].isChecked()


def test_set_bypass_desde_panel(app):
    ed = _editor()
    p = BypassControlPanel()
    seen = []
    p.changed.connect(lambda: seen.append(True))
    p.show_block(ed, 2)
    p._select("FS3")
    assert ed.bypass_target(2) == "FS3"
    assert seen  # emitted changed
    assert p._buttons["FS3"].isChecked()


def test_clear_bypass_desde_panel(app):
    ed = _editor()
    p = BypassControlPanel()
    p.show_block(ed, 2)
    p._select("None")
    assert ed.bypass_target(2) is None
    assert p._buttons["None"].isChecked()


def test_bypass_no_permite_exp_pedal(app):
    ed = _editor()
    p = BypassControlPanel()
    p.show_block(ed, 2)  # parameter = Bypass
    assert not p._buttons["EXP 1"].isEnabled()
    assert not p._buttons["Snapshots"].isEnabled()
    # Mode/Tap always disabled.
    assert not p._buttons["Mode"].isEnabled()


def test_controller_existente_muestra_minmax(app):
    ed = _editor()
    p = BypassControlPanel()
    p.show_block(ed, 1)  # Wah
    # Select the Pedal parameter (index 0 → menu item 1).
    p.param_menu.setCurrentIndex(1)
    assert not p._minmax.isHidden()
    assert p._buttons["EXP 1"].isChecked()
    p.min_spin.setValue(0.25)
    p.max_spin.setValue(0.75)
    p._commit_minmax()
    a = ed.controller_assignment(1, 0)
    assert a["min"] == pytest.approx(0.25)
    assert a["max"] == pytest.approx(0.75)


def test_crear_controller_informa_re_bloqueado(app):
    ed = _editor()
    p = BypassControlPanel()
    p.show_block(ed, 2)  # Tube Drive
    p.param_menu.setCurrentIndex(1)  # Drive (sin controller)
    assert p._minmax.isHidden()
    p._select("EXP 1")  # create → RE-blocked
    assert "RE" in p.status.text() or "spec 09" in p.status.text()
    assert ed.controller_assignment(2, 0) is None  # nothing was written


def test_assignments_list_dialog(app):
    ed = _editor()
    p = BypassControlPanel()
    p.show_block(ed, 0)
    dlg = AssignmentsListDialog(p, "EXP Toe")
    # Remove all assignments from the toe switch.
    dlg._clear_all()
    assert ed.bypass_blocks_on("EXP Toe") == []


def test_fs_color_index_via_editor(app):
    # Color is a palette index (key 16), not arbitrary RGB.
    ed = _editor()
    assert ed.footswitch_color_index(2) == 0  # Auto
    ed.set_fs_color_index(2, 2)  # Red
    assert ed.footswitch_color_index(2) == 2


def test_empty_slot_does_not_crash(app):
    ed = _editor()
    p = BypassControlPanel()
    p.show_block(ed, 9)  # empty
    p._select("FS3")  # must not write or crash
    assert p._current_param() == -1
