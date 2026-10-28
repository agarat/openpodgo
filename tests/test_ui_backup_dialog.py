"""UI tests for Backup and Restore dialogs and menu integrations."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from openpodgo import pgb
from openpodgo.ui.backup_dialog import (
    CreateBackupDialog,
    RestoreBackupDialog,
    default_backup_dir,
)
from openpodgo.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def sample_preset() -> dict:
    return {
        "device": 2162695,
        "device_version": 33619968,
        "meta": {"name": "TestTone"},
        "tone": {"dsp0": {}, "global": {}},
    }


def test_default_backup_dir():
    d = default_backup_dir()
    assert isinstance(d, Path)
    assert "POD Go" in str(d)


def test_create_backup_dialog_init(app, tmp_path):
    dlg = CreateBackupDialog(setlists=["Factory", "User"], default_dir=tmp_path)
    assert dlg.name_edit.text().startswith("POD Go Backup ")
    assert str(tmp_path) in dlg.dir_edit.text()
    assert "Factory" in dlg.setlist_checkboxes
    assert "User" in dlg.setlist_checkboxes
    assert dlg.setlist_checkboxes["Factory"].isChecked()
    assert dlg.setlist_checkboxes["User"].isChecked()


def test_create_backup_dialog_emit(app, tmp_path):
    dlg = CreateBackupDialog(default_dir=tmp_path)
    dlg.name_edit.setText("MyBackup")
    dlg.desc_edit.setText("Test Description")

    emitted_configs = []
    dlg.create_requested.connect(emitted_configs.append)

    dlg._on_create_clicked()

    assert len(emitted_configs) == 1
    cfg = emitted_configs[0]
    assert cfg["name"] == "MyBackup"
    assert cfg["description"] == "Test Description"
    assert cfg["path"] == tmp_path / "MyBackup.pgb"
    assert "User" in cfg["setlists"]


def test_create_backup_dialog_progress(app, tmp_path):
    dlg = CreateBackupDialog(default_dir=tmp_path)
    assert dlg.progress_bar.isHidden()
    dlg.set_busy(True)
    assert not dlg.progress_bar.isHidden()
    assert not dlg.create_btn.isEnabled()

    dlg.set_progress(50, 100, "Reading presets 50%...")
    assert dlg.progress_bar.value() == 50
    assert "50%" in dlg.status_label.text()

    dlg.set_completed("Backup created successfully")
    assert dlg.progress_bar.value() == 100
    assert dlg.cancel_btn.isHidden()
    assert dlg.create_btn.text() == "OK"
    assert dlg.create_btn.isEnabled()
    assert not dlg.name_edit.isEnabled()


def test_restore_backup_dialog_inspect(app, tmp_path, sample_preset):
    # Create a real test backup
    backup_file = tmp_path / "test_inspect.pgb"
    meta = {
        "date": "2026-10-21",
        "device": "POD Go",
        "version": "v2.01",
        "description": "Inspection test notes",
    }
    backup = pgb.Backup(
        globals={"System": {"device": "POD Go", "version": "v2.01"}},
        setlists={"Factory": [sample_preset], "User": [sample_preset, sample_preset]},
        metadata=meta,
    )
    pgb.write_backup(backup_file, backup)

    dlg = RestoreBackupDialog()
    ok = dlg.load_file(backup_file)
    assert ok is True
    assert dlg.date_val.text() == "2026-10-21"
    assert dlg.device_val.text() == "POD Go"
    assert dlg.version_val.text() == "v2.01"
    assert dlg.desc_val.text() == "Inspection test notes"
    assert "Factory: 1 presets" in dlg.setlists_val.text()
    assert "User: 2 presets" in dlg.setlists_val.text()
    assert dlg.restore_btn.isEnabled()


def test_main_window_has_backup_restore_actions(app):
    win = MainWindow(autoconnect=False)
    file_menu = win.menuBar().findChild(object, "")  # File menu
    actions = [a.text() for a in win.menuBar().actions()]
    assert "&File" in actions or "File" in actions

    # Verify menu actions exist on window
    menu_actions = [a.text() for a in win.findChildren(object) if hasattr(a, "text")]
    assert any("Create backup" in t for t in menu_actions)
    assert any("Restore from backup" in t for t in menu_actions)
    assert any("Export presets archive" in t for t in menu_actions)
    assert any("Import presets archive" in t for t in menu_actions)
