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
    assert panel.folder_buttons[0].objectName() == "setlist_tab"
    assert panel.folder_buttons[0].isChecked()
    assert not panel.folder_buttons[1].isChecked()
    got = []
    panel.setlist_changed.connect(got.append)
    panel.folder_buttons[1].click()
    assert got == [1]
    assert panel.folder_buttons[1].isChecked()
    assert not panel.folder_buttons[0].isChecked()


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


def test_librarian_helpers_and_rename(app):
    panel = LibrarianPanel()
    panel.set_presets(_entries())

    assert panel.preset_name(0) == "US Deluxe Nrm"
    assert panel.preset_name(1) == "A30 Fawn Brt"
    assert panel.preset_name(4) == "Brit Plexi Brt"
    assert panel.preset_name(99) is None

    panel.list.setCurrentRow(1)
    assert panel.current_slot() == 1

    panel.update_preset_name(1, "Updated Vox")
    assert panel.preset_name(1) == "Updated Vox"
    assert "Updated Vox" in panel.list.item(1).text()


def test_preset_list_widget_long_press(app):
    panel = LibrarianPanel()
    panel.set_presets(_entries())

    renamed = []
    panel.rename_requested.connect(lambda slot, name: renamed.append((slot, name)))

    # Simulate long press on item 0
    panel.list._pressed_item = panel.list.item(0)
    panel.list._on_long_press()
    assert renamed == [(0, "US Deluxe Nrm")]
    assert not panel.list._editor.isHidden()


def test_preset_list_in_place_rename_commit(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    panel = LibrarianPanel()
    panel.set_presets(_entries())
    panel.show()

    committed = []
    panel.rename_committed.connect(lambda slot, name: committed.append((slot, name)))

    panel.start_rename_slot(1)
    assert not panel.list._editor.isHidden()
    assert panel.list._editor.text() == "A30 Fawn Brt"

    panel.list._editor.setText("Top Boost AC30")
    QTest.keyClick(panel.list._editor, Qt.Key.Key_Return)

    assert panel.list._editor.isHidden()
    assert committed == [(1, "Top Boost AC30")]


def test_preset_list_in_place_rename_cancel(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    panel = LibrarianPanel()
    panel.set_presets(_entries())
    panel.show()

    committed = []
    panel.rename_committed.connect(lambda slot, name: committed.append((slot, name)))

    panel.start_rename_slot(1)
    assert not panel.list._editor.isHidden()

    panel.list._editor.setText("Cancelled")
    QTest.keyClick(panel.list._editor, Qt.Key.Key_Escape)

    assert panel.list._editor.isHidden()
    assert committed == []


def test_preset_list_long_press_suppresses_activation(app):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtGui import QMouseEvent

    panel = LibrarianPanel()
    panel.set_presets(_entries())
    panel.show()

    activated = []
    panel.preset_activated.connect(activated.append)

    from PySide6.QtCore import QPointF
    # Press down on item 0
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(10.0, 10.0),
        QPointF(10.0, 10.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.list.mousePressEvent(press_ev)
    # Long press triggers
    panel.list._on_long_press()
    assert panel.list._long_pressed_triggered is True

    # Mouse release occurs
    rel_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(10.0, 10.0),
        QPointF(10.0, 10.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.list.mouseReleaseEvent(rel_ev)

    # Activation must NOT be triggered
    assert activated == []


def test_preset_list_drag_and_drop_pgp(app, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    panel = LibrarianPanel()
    panel.set_presets(_entries())
    panel.show()

    pgp_file = tmp_path / "custom.pgp"
    pgp_file.write_text("{}")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(pgp_file))])

    enter_ev = QDragEnterEvent(
        QPointF(10.0, 10.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.list.dragEnterEvent(enter_ev)
    assert enter_ev.isAccepted()

    # Move event over item index 1 (slot 1)
    rect = panel.list.visualItemRect(panel.list.item(1))
    move_ev = QDragMoveEvent(
        QPointF(rect.center()),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.list.dragMoveEvent(move_ev)
    assert move_ev.isAccepted()
    assert panel.list.currentItem() == panel.list.item(1)

    # Drop event
    dropped = []
    panel.preset_dropped.connect(lambda slot, path: dropped.append((slot, path)))
    drop_ev = QDropEvent(
        QPointF(rect.center()),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.list.dropEvent(drop_ev)
    assert drop_ev.isAccepted()
    assert dropped == [(1, str(pgp_file))]

    # Non-pgp file is rejected
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("hello")
    mime_bad = QMimeData()
    mime_bad.setUrls([QUrl.fromLocalFile(str(txt_file))])
    enter_bad = QDragEnterEvent(
        QPointF(10.0, 10.0),
        Qt.DropAction.CopyAction,
        mime_bad,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.list.dragEnterEvent(enter_bad)
    assert not enter_bad.isAccepted()


