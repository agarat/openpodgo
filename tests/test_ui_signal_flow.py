"""Signal Flow POD Go Edit style: official icons, bypass dimmed, caret,
assignment labels and hover buttons."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openpodgo import editor, l6helix  # noqa: E402
from openpodgo.ui.signal_flow import SignalFlowPanel  # noqa: E402

CAPS = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _editor() -> editor.PresetEditor:
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    return editor.PresetEditor(l6helix.parse_blob(blob))


def _panel(app, selected=None) -> SignalFlowPanel:
    ed = _editor()
    panel = SignalFlowPanel()
    panel.update_from(ed.preset, selected, ed.bypass_assignments())
    return panel


def test_panel_has_10_slots(app):
    panel = _panel(app)
    assert len(panel.slot_widgets) == 10
    textos = [w.model_text() for w in panel.slot_widgets]
    assert any("Tube Drive" in t for t in textos)
    # BassPreset has an empty slot (no model text)
    empty_slots = [w for w in panel.slot_widgets if w.is_empty]
    assert len(empty_slots) == 1 and empty_slots[0].model_text() == ""


def test_assignment_labels(app):
    panel = _panel(app)
    # Fixture: Tube Drive (slot 2) → FS4; wah/vol (slots 1 and 0) → EXP Toe.
    assert panel.slot_widgets[2].assign_label == "FS4"
    assert panel.slot_widgets[0].assign_label == "EXP Toe"
    assert panel.slot_widgets[1].assign_label == "EXP Toe"
    # The empty slot has no assignment.
    assert panel.slot_widgets[9].assign_label == ""


def test_bypass_is_reflected(app):
    ed = _editor()
    panel = SignalFlowPanel()
    # In the fixture, slot 5 (FX Loop) is active and slot 2 (Tube Drive) is not.
    ed.set_bypass(5, False)
    panel.update_from(ed.preset, None, ed.bypass_assignments())
    assert panel.slot_widgets[5].block_enabled is False
    assert panel.slot_widgets[0].block_enabled is True
    assert panel.slot_widgets[2].block_enabled is False


def test_selection_marks_a_single_block(app):
    panel = _panel(app, selected=2)
    assert [w.selected for w in panel.slot_widgets].count(True) == 1
    assert panel.slot_widgets[2].selected


def test_click_emits_block_selected(app):
    panel = _panel(app)
    got = []
    panel.block_selected.connect(got.append)
    panel.slot_widgets[3].clicked.emit(3)
    assert got == [3]


def test_hover_buttons_emit_signals(app):
    panel = _panel(app)
    bypassed, cleared = [], []
    panel.bypass_toggled.connect(bypassed.append)
    panel.clear_requested.connect(cleared.append)
    w = panel.slot_widgets[2]
    w.bypass_btn.click()
    w.clear_btn.click()
    assert bypassed == [2]
    assert cleared == [2]


def test_empty_slot_does_not_offer_hover_buttons(app):
    panel = _panel(app)
    empty_w = next(w for w in panel.slot_widgets if w.is_empty)
    empty_w._set_hovered(True)
    assert not empty_w.bypass_btn.isVisible()
    assert not empty_w.clear_btn.isVisible()


def test_render_offscreen(app):
    # Exercises the paintEvent (line, icons, caret) without X11.
    panel = _panel(app, selected=2)
    panel.resize(900, 110)
    pm = panel.grab()
    assert not pm.isNull() and pm.width() > 0


def test_slot_at_clamps_to_boundaries(app):
    panel = _panel(app)
    panel.resize(900, 110)
    panel.grab()  # forces the layout so widgets have geometry
    assert panel._slot_at(-100) == 0
    assert panel._slot_at(10_000) == 9


def test_drop_emits_block_moved(app):
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent
    from PySide6.QtCore import Qt
    from openpodgo.ui.signal_flow import BLOCK_MIME

    panel = _panel(app)
    panel.resize(900, 110)
    panel.grab()
    moved = []
    panel.block_moved.connect(lambda a, b: moved.append((a, b)))

    target = panel.slot_widgets[6]
    pos = QPointF(target.x() + target.width() // 2, 50)
    mime = QMimeData()
    mime.setData(BLOCK_MIME, b"3")  # dragging slot 3
    ev = QDropEvent(
        pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    panel.dropEvent(ev)
    assert moved == [(3, 6)]


def test_drop_same_position_does_not_emit(app):
    from PySide6.QtCore import QMimeData, QPointF, Qt
    from PySide6.QtGui import QDropEvent
    from openpodgo.ui.signal_flow import BLOCK_MIME

    panel = _panel(app)
    panel.resize(900, 110)
    panel.grab()
    moved = []
    panel.block_moved.connect(lambda a, b: moved.append((a, b)))

    target = panel.slot_widgets[3]
    pos = QPointF(target.x() + target.width() // 2, 50)
    mime = QMimeData()
    mime.setData(BLOCK_MIME, b"3")
    ev = QDropEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    panel.dropEvent(ev)
    assert moved == []


def test_caret_side_according_to_direction(app):
    # move_block does pop(src)+insert(dst): moving right places the block AFTER
    # the slot under the cursor (caret on the right); moving left, before.
    panel = SignalFlowPanel()
    assert panel._caret_side(0, 2) == "right"   # moving right
    assert panel._caret_side(3, 1) == "left"    # moving left
    assert panel._caret_side(2, 2) == "left"    # same slot → no shifting
    assert panel._caret_side(None, 2) == "left" # no known source
