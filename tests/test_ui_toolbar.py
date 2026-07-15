"""Editor toolbar in the POD Go Edit style: ◂▸ preset, 01A title, Save
(disabled until spec 03), snapshots, undo/redo, and tempo."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openpodgo import editor, l6helix  # noqa: E402
from openpodgo.ui.editor import EditorView  # noqa: E402

CAPS = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _view(app) -> EditorView:
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    view = EditorView()
    view.set_preset(
        editor.PresetEditor(l6helix.parse_blob(blob)), "BassPreset",
        slot_text="01A",
    )
    return view


def _slot_of(view, model_id: int) -> int:
    for i, blk in enumerate(view.editor.preset.chain):
        if blk is not None and blk.model_id == model_id:
            return i
    raise AssertionError(f"model {model_id} is not in the chain")


def test_titulo_con_slot_y_nombre(app):
    view = _view(app)
    text = view.toolbar.title_label.text()
    assert "01A" in text and "BassPreset" in text
    view.toggle_bypass(_slot_of(view, 366))
    assert "●" in view.toolbar.title_label.text()


def test_save_btn_habilitado(app):
    view = _view(app)
    assert view.toolbar.save_btn.isEnabled()


def test_tempo_visible(app):
    view = _view(app)
    assert view.toolbar.tempo_label.text()  # el fixture trae tempo


def test_undo_redo_estado_de_botones(app):
    view = _view(app)
    assert not view.toolbar.undo_btn.isEnabled()
    assert not view.toolbar.redo_btn.isEnabled()
    view.toggle_bypass(_slot_of(view, 366))
    assert view.toolbar.undo_btn.isEnabled()
    view.undo()
    assert view.toolbar.redo_btn.isEnabled()


def test_undo_restaura_valor_y_ui(app):
    view = _view(app)
    slot = _slot_of(view, 366)
    view.select_slot(slot)
    original = view.editor.preset.chain[slot].params[0]
    view.inspector.rows[0].set_value(0.55)
    view.undo()
    assert view.editor.preset.chain[slot].params[0] == pytest.approx(original)
    assert view.inspector.rows[0].spin.value() == pytest.approx(
        original, abs=1e-3
    )
    view.redo()
    assert view.editor.preset.chain[slot].params[0] == pytest.approx(
        0.55, abs=1e-3
    )


def test_snapshot_menu_emite_senal(app):
    view = _view(app)
    got = []
    view.snapshot_selected.connect(got.append)
    view.toolbar.snapshot_actions[1].trigger()
    assert got == [1]


def test_prev_next_emiten(app):
    view = _view(app)
    got = []
    view.prev_requested.connect(lambda: got.append("prev"))
    view.next_requested.connect(lambda: got.append("next"))
    view.toolbar.prev_btn.click()
    view.toolbar.next_btn.click()
    assert got == ["prev", "next"]


def test_reread_y_export_siguen_en_la_toolbar(app):
    view = _view(app)
    got = []
    view.reread_requested.connect(lambda: got.append("reread"))
    view.toolbar.reread_btn.click()
    assert got == ["reread"]
    assert view.toolbar.export_btn.isEnabled()
