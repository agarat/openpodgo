"""Librarian POD Go Edit style: Factory/User folders + preset list,
with the loaded preset marked in amber."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openpodgo.preset import PresetEntry  # noqa: E402
from openpodgo.ui.librarian import LOADED_PREFIX, LibrarianPanel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _entries():
    return [
        PresetEntry(index=10, name="US Deluxe Nrm", slot=0),
        PresetEntry(index=11, name="A30 Fawn Brt", slot=1),
        PresetEntry(index=12, name="Brit Plexi Brt", slot=4),
    ]


def test_format_01a(app):
    panel = LibrarianPanel()
    panel.set_presets(_entries())
    texts = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert texts[0].endswith("01A  US Deluxe Nrm")
    assert texts[1].endswith("01B  A30 Fawn Brt")
    assert texts[2].endswith("02A  Brit Plexi Brt")


def test_set_loaded_marks_in_amber(app):
    panel = LibrarianPanel()
    panel.set_presets(_entries())
    panel.set_loaded(1)
    assert panel.list.item(1).text().startswith(LOADED_PREFIX)
    assert not panel.list.item(0).text().startswith(LOADED_PREFIX)
    # Moving the mark removes it from the previous one.
    panel.set_loaded(4)
    assert not panel.list.item(1).text().startswith(LOADED_PREFIX)
    assert panel.list.item(2).text().startswith(LOADED_PREFIX)


def test_folders_emit_setlist_changed(app):
    panel = LibrarianPanel()
    panel.set_setlists(["Factory", "User"], current=0)
    got = []
    panel.setlist_changed.connect(got.append)
    panel.folder_buttons[1].click()
    assert got == [1]


def test_activate_preset_emits_position(app):
    panel = LibrarianPanel()
    panel.set_presets(_entries())
    got = []
    panel.preset_activated.connect(got.append)
    panel.list.itemClicked.emit(panel.list.item(2))
    assert got == [4]  # position (MIDI slot), not list index


def test_state_without_pedal(app):
    panel = LibrarianPanel()
    panel.set_offline(True)
    assert panel.reconnect_btn.isVisible() or not panel.isVisible()
    got = []
    panel.reconnect_requested.connect(lambda: got.append(1))
    panel.reconnect_btn.click()
    assert got == [1]
    panel.set_offline(False)
    assert panel.reconnect_btn.isHidden()
