"""Dialogs for Creating and Restoring POD Go Backups (.pgb).

Modeled after POD Go Edit Pilot's Guide v2.50 (pp. 18–19).
Supports metadata inspection, setlist selection, progress reporting, and error handling.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import pgb

log = logging.getLogger(__name__)


def default_backup_dir() -> Path:
    """Return default directory for POD Go backup files."""
    docs = Path.home() / "Documents" / "Line 6" / "POD Go" / "Backups"
    if not docs.parent.parent.parent.exists():
        docs = Path.home() / "POD Go Backups"
    return docs


class CreateBackupDialog(QDialog):
    """Dialog to configure and start creating a .pgb device backup."""

    create_requested = Signal(dict)

    def __init__(
        self,
        parent: QWidget | None = None,
        setlists: list[str] | None = None,
        default_dir: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create POD Go Backup")
        self.resize(480, 360)

        self._setlists = setlists or ["Factory", "User"]
        self._default_dir = Path(default_dir) if default_dir else default_backup_dir()
        self._is_busy = False

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Form fields
        form = QFormLayout()
        form.setSpacing(10)

        today_str = datetime.date.today().isoformat()
        self.name_edit = QLineEdit(f"POD Go Backup {today_str}")
        self.name_edit.setObjectName("backupName")
        form.addRow("Backup &Name:", self.name_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Optional notes or description")
        form.addRow("&Description:", self.desc_edit)

        # Destination folder with Browse button
        dir_layout = QHBoxLayout()
        self.dir_edit = QLineEdit(str(self._default_dir))
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self.dir_edit, 1)
        dir_layout.addWidget(self.browse_btn)
        form.addRow("Where:", dir_layout)

        layout.addLayout(form)

        # Setlist options group
        setlist_group = QGroupBox("Items to Include")
        setlist_layout = QVBoxLayout(setlist_group)
        self.setlist_checkboxes: dict[str, QCheckBox] = {}
        for s_name in self._setlists:
            cb = QCheckBox(f"{s_name} Setlist")
            cb.setChecked(True)
            self.setlist_checkboxes[s_name] = cb
            setlist_layout.addWidget(cb)
        layout.addWidget(setlist_group)

        # Progress and status
        self.status_label = QLabel("Choose backup destination and click Create Backup.")
        self.status_label.setObjectName("hint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        layout.addStretch(1)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.create_btn = QPushButton("Create Backup")
        self.create_btn.setDefault(True)
        self.create_btn.clicked.connect(self._on_create_clicked)
        btn_layout.addWidget(self.create_btn)

        layout.addLayout(btn_layout)

    def _browse_dir(self) -> None:
        current = self.dir_edit.text().strip() or str(self._default_dir)
        chosen = QFileDialog.getExistingDirectory(self, "Select Backup Destination Directory", current)
        if chosen:
            self.dir_edit.setText(chosen)

    def _on_create_clicked(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Please provide a name for the backup file.")
            self.name_edit.setFocus()
            return

        dest_dir = Path(self.dir_edit.text().strip())
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid Destination", f"Could not create destination directory:\n{exc}")
            return

        filename = f"{name}.pgb" if not name.endswith(".pgb") else name
        target_path = dest_dir / filename

        if target_path.exists():
            confirm = QMessageBox.question(
                self,
                "Overwrite Backup",
                f"File '{filename}' already exists.\nDo you want to overwrite it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        selected_setlists = [
            s_name for s_name, cb in self.setlist_checkboxes.items() if cb.isChecked()
        ]
        if not selected_setlists:
            QMessageBox.warning(self, "No Setlists Selected", "Select at least one setlist to include in the backup.")
            return

        config = {
            "path": target_path,
            "name": name,
            "description": self.desc_edit.text().strip(),
            "setlists": selected_setlists,
        }
        self.set_busy(True)
        self.create_requested.emit(config)

    def set_busy(self, busy: bool) -> None:
        self._is_busy = busy
        self.name_edit.setEnabled(not busy)
        self.desc_edit.setEnabled(not busy)
        self.dir_edit.setEnabled(not busy)
        self.browse_btn.setEnabled(not busy)
        for cb in self.setlist_checkboxes.values():
            cb.setEnabled(not busy)
        self.create_btn.setEnabled(not busy)
        if busy:
            self.progress_bar.show()
            self.cancel_btn.setText("Cancel Operation")
        else:
            self.cancel_btn.setText("Close")

    def set_progress(self, current: int, total: int, status: str = "") -> None:
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        if status:
            self.status_label.setText(status)

    def set_completed(self, message: str) -> None:
        self._is_busy = False
        self.name_edit.setEnabled(False)
        self.desc_edit.setEnabled(False)
        self.dir_edit.setEnabled(False)
        self.browse_btn.setEnabled(False)
        for cb in self.setlist_checkboxes.values():
            cb.setEnabled(False)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"✓ {message}")
        self.cancel_btn.hide()
        self.create_btn.setText("OK")
        self.create_btn.setEnabled(True)
        self.create_btn.setDefault(True)
        self.create_btn.setFocus()
        try:
            self.create_btn.clicked.disconnect()
        except Exception:
            pass
        self.create_btn.clicked.connect(self.accept)

    def set_error(self, message: str) -> None:
        self.set_busy(False)
        self.status_label.setText(f"Error: {message}")
        self.create_btn.setEnabled(True)
        self.cancel_btn.setText("Close")


class RestoreBackupDialog(QDialog):
    """Dialog to inspect a .pgb backup and selectively restore its contents."""

    restore_requested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restore From Backup")
        self.resize(520, 440)

        self._inspected_info: dict | None = None
        self._backup_path: Path | None = None
        self._is_busy = False

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # File picker
        file_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select a .pgb backup file…")
        self.path_edit.textChanged.connect(self._on_path_typed)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse_file)
        file_layout.addWidget(self.path_edit, 1)
        file_layout.addWidget(self.browse_btn)
        layout.addLayout(file_layout)

        # Backup Details Preview Card
        self.preview_group = QGroupBox("Backup Information")
        preview_form = QFormLayout(self.preview_group)
        preview_form.setSpacing(6)

        self.date_val = QLabel("—")
        self.device_val = QLabel("—")
        self.version_val = QLabel("—")
        self.desc_val = QLabel("—")
        self.desc_val.setWordWrap(True)
        self.setlists_val = QLabel("—")

        preview_form.addRow("Date:", self.date_val)
        preview_form.addRow("Device:", self.device_val)
        preview_form.addRow("Firmware:", self.version_val)
        preview_form.addRow("Description:", self.desc_val)
        preview_form.addRow("Contents:", self.setlists_val)
        layout.addWidget(self.preview_group)

        # Selective restore options
        self.items_group = QGroupBox("Items to Restore")
        self.items_layout = QVBoxLayout(self.items_group)

        self.cb_globals = QCheckBox("Global Settings")
        self.cb_globals.setChecked(True)
        self.items_layout.addWidget(self.cb_globals)

        self.setlist_checkboxes: dict[str, QCheckBox] = {}
        # Placeholders for Factory/User
        for s_name in ("Factory", "User"):
            cb = QCheckBox(f"{s_name} Setlist")
            cb.setChecked(True)
            self.setlist_checkboxes[s_name] = cb
            self.items_layout.addWidget(cb)

        self.cb_irs = QCheckBox("Impulse Responses (IRs)")
        self.cb_irs.setEnabled(False)
        self.items_layout.addWidget(self.cb_irs)

        layout.addWidget(self.items_group)

        # Warning
        self.warn_label = QLabel("⚠️ Restoring will overwrite selected presets on the connected POD Go.")
        self.warn_label.setObjectName("hint")
        self.warn_label.setStyleSheet("color: #e5a020; font-weight: 500;")
        self.warn_label.setWordWrap(True)
        layout.addWidget(self.warn_label)

        # Status and Progress
        self.status_label = QLabel("Select a backup file to preview and restore.")
        self.status_label.setObjectName("hint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        layout.addStretch(1)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.restore_btn = QPushButton("Restore Backup")
        self.restore_btn.setEnabled(False)
        self.restore_btn.setDefault(True)
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        btn_layout.addWidget(self.restore_btn)

        layout.addLayout(btn_layout)

    def _browse_file(self) -> None:
        start_dir = str(default_backup_dir())
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select POD Go Backup File",
            start_dir,
            "POD Go Backup (*.pgb);;All Files (*)",
        )
        if chosen:
            self.path_edit.setText(chosen)

    def _on_path_typed(self, text: str) -> None:
        p = Path(text.strip())
        if p.is_file():
            self.load_file(p)
        else:
            self._clear_preview()

    def load_file(self, path: Path | str) -> bool:
        """Inspect and display metadata from a .pgb file."""
        p = Path(path)
        try:
            info = pgb.inspect_backup(p)
        except Exception as exc:
            self._clear_preview()
            self.status_label.setText(f"Cannot read backup: {exc}")
            return False

        self._inspected_info = info
        self._backup_path = p

        self.date_val.setText(info.get("date") or "—")
        self.device_val.setText(info.get("device") or "POD Go")
        self.version_val.setText(info.get("version") or "—")
        self.desc_val.setText(info.get("description") or "(None)")

        setlists_info = info.get("setlists", {})
        summary_parts = [f"{name}: {cnt} presets" for name, cnt in setlists_info.items()]
        if info.get("ir_count", 0) > 0:
            summary_parts.append(f"IRs: {info['ir_count']}")
        self.setlists_val.setText(", ".join(summary_parts) or "—")

        # Update checkboxes based on contents
        self.cb_globals.setEnabled(info.get("has_globals", False))
        self.cb_globals.setChecked(info.get("has_globals", False))

        for name, cb in self.setlist_checkboxes.items():
            if name in setlists_info:
                cb.setEnabled(True)
                cb.setChecked(True)
                cb.setText(f"{name} Setlist ({setlists_info[name]} presets)")
            else:
                cb.setEnabled(False)
                cb.setChecked(False)
                cb.setText(f"{name} Setlist (not in backup)")

        ir_count = info.get("ir_count", 0)
        self.cb_irs.setEnabled(ir_count > 0)
        self.cb_irs.setChecked(ir_count > 0)
        self.cb_irs.setText(f"Impulse Responses ({ir_count} IRs)" if ir_count else "Impulse Responses (None in backup)")

        self.restore_btn.setEnabled(True)
        self.status_label.setText("Backup inspected successfully. Choose items and click Restore Backup.")
        return True

    def _clear_preview(self) -> None:
        self._inspected_info = None
        self._backup_path = None
        self.date_val.setText("—")
        self.device_val.setText("—")
        self.version_val.setText("—")
        self.desc_val.setText("—")
        self.setlists_val.setText("—")
        self.restore_btn.setEnabled(False)

    def _on_restore_clicked(self) -> None:
        if not self._backup_path or not self._inspected_info:
            return

        selected_setlists = [
            s_name for s_name, cb in self.setlist_checkboxes.items() if cb.isChecked() and cb.isEnabled()
        ]
        restore_globals = self.cb_globals.isChecked() and self.cb_globals.isEnabled()
        restore_irs = self.cb_irs.isChecked() and self.cb_irs.isEnabled()

        if not selected_setlists and not restore_globals and not restore_irs:
            QMessageBox.warning(self, "No Items Selected", "Please select at least one item to restore.")
            return

        confirm = QMessageBox.warning(
            self,
            "Confirm Restore",
            "Restoring will overwrite current presets on your pedal.\nAre you sure you want to proceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        config = {
            "path": self._backup_path,
            "setlists": selected_setlists,
            "globals": restore_globals,
            "irs": restore_irs,
        }
        self.set_busy(True)
        self.restore_requested.emit(config)

    def set_busy(self, busy: bool) -> None:
        self._is_busy = busy
        self.path_edit.setEnabled(not busy)
        self.browse_btn.setEnabled(not busy)
        self.cb_globals.setEnabled(not busy and (self._inspected_info.get("has_globals", False) if self._inspected_info else False))
        for name, cb in self.setlist_checkboxes.items():
            in_backup = name in (self._inspected_info.get("setlists", {}) if self._inspected_info else {})
            cb.setEnabled(not busy and in_backup)
        self.cb_irs.setEnabled(not busy and ((self._inspected_info.get("ir_count", 0) > 0) if self._inspected_info else False))
        self.restore_btn.setEnabled(not busy)
        if busy:
            self.progress_bar.show()
            self.cancel_btn.setText("Cancel Operation")
        else:
            self.cancel_btn.setText("Close")

    def set_progress(self, current: int, total: int, status: str = "") -> None:
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        if status:
            self.status_label.setText(status)

    def set_completed(self, message: str) -> None:
        self._is_busy = False
        self.path_edit.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.cb_globals.setEnabled(False)
        for cb in self.setlist_checkboxes.values():
            cb.setEnabled(False)
        self.cb_irs.setEnabled(False)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"✓ {message}")
        self.cancel_btn.hide()
        self.restore_btn.setText("OK")
        self.restore_btn.setEnabled(True)
        self.restore_btn.setDefault(True)
        self.restore_btn.setFocus()
        try:
            self.restore_btn.clicked.disconnect()
        except Exception:
            pass
        self.restore_btn.clicked.connect(self.accept)

    def set_error(self, message: str) -> None:
        self.set_busy(False)
        self.status_label.setText(f"Error: {message}")
        self.restore_btn.setEnabled(True)
        self.cancel_btn.setText("Close")
