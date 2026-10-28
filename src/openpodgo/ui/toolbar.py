"""Editor toolbar, modeled after the top strip of POD Go Edit:

[▴▾] [01A Name ●] [Save] [Snapshots ▾] [↶ ↷]  …  [♩ tempo] [Reread] [Export]

Save remains disabled until spec 03 (writing to the pedal); Reread and
Export .pgp are ours in the meantime.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import assets


class EditablePresetTitle(QLabel):
    """Preset title label that becomes editable in-place on long-press or double-click."""

    rename_committed = Signal(str)
    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("title")
        self.setTextFormat(Qt.RichText)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Long-press or double-click to rename; drop .pgp to import")
        self.setAcceptDrops(True)

        self._slot_text = ""
        self._preset_name = ""
        self._modified = False
        self._press_pos = None
        self._long_pressed_triggered = False
        self._rename_start_time = 0.0

        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(500)
        self._long_press_timer.timeout.connect(self._on_long_press)

        self._editor = QLineEdit(self)
        self._editor.setObjectName("title_edit")
        self._editor.hide()
        self._editor.returnPressed.connect(self._commit_rename)
        self._editor.installEventFilter(self)

    @staticmethod
    def _has_pgp_url(mime) -> bool:
        if mime is None or not mime.hasUrls():
            return False
        for url in mime.urls():
            if url.toLocalFile().lower().endswith(".pgp"):
                return True
        return False

    @staticmethod
    def _extract_pgp_path(mime) -> str | None:
        if mime is None or not mime.hasUrls():
            return None
        for url in mime.urls():
            f = url.toLocalFile()
            if f.lower().endswith(".pgp"):
                return f
        return None

    def dragEnterEvent(self, event) -> None:
        if self.isEnabled() and self._has_pgp_url(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.isEnabled() and self._has_pgp_url(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if self.isEnabled() and self._has_pgp_url(event.mimeData()):
            path = self._extract_pgp_path(event.mimeData())
            if path:
                event.acceptProposedAction()
                self.file_dropped.emit(path)
                return
        super().dropEvent(event)

    def set_preset_info(self, slot_text: str, name: str, modified: bool) -> None:
        self._editor.hide()
        self._slot_text = slot_text
        self._preset_name = name
        self._modified = modified
        self._update_text()

    def _update_text(self) -> None:
        slot_html = f"<b>{self._slot_text}</b>&nbsp; " if self._slot_text else ""
        dot = " ●" if self._modified else ""
        self.setText(f"{slot_html}{self._preset_name}{dot}")

    def mousePressEvent(self, event) -> None:
        if not self.isEnabled():
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._editor.isHidden():
            self._press_pos = event.pos()
            self._long_press_timer.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._long_press_timer.stop()
        if self._long_pressed_triggered:
            self._long_pressed_triggered = False
            self._press_pos = None
            event.accept()
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is not None:
            if (event.pos() - self._press_pos).manhattanLength() > 6:
                self._long_press_timer.stop()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.isEnabled():
            super().mouseDoubleClickEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._long_press_timer.stop()
            self._long_pressed_triggered = True
            self.start_rename()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _on_long_press(self) -> None:
        self._long_pressed_triggered = True
        self.start_rename()

    def _editor_geometry(self) -> tuple[int, int, int, int]:
        fm = self.fontMetrics()
        slot_prefix = f"{self._slot_text} " if self._slot_text else ""
        x = fm.horizontalAdvance(slot_prefix) + 2 if slot_prefix else 0
        w = max(self.width() - x, 140)
        h = max(self.height(), 24)
        return x, 0, w, h

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._editor.isHidden():
            x, y, w, h = self._editor_geometry()
            self._editor.setGeometry(x, y, w, h)

    def start_rename(self) -> None:
        if not self._preset_name or not self.isEnabled():
            return
        self._rename_start_time = time.time()
        if self._slot_text:
            self.setText(f"<b>{self._slot_text}</b>&nbsp; ")
        else:
            self.setText("")
        x, y, w, h = self._editor_geometry()
        self._editor.setGeometry(x, y, w, h)
        self._editor.setText(self._preset_name)
        self._editor.show()
        self._editor.setFocus()
        self._editor.selectAll()

    def _commit_rename(self) -> None:
        if self._editor.isHidden():
            return
        new_name = self._editor.text().strip()[:32]
        self._editor.hide()
        if new_name and new_name != self._preset_name:
            self._preset_name = new_name
            self._update_text()
            self.rename_committed.emit(new_name)
        else:
            self._update_text()

    def cancel_rename(self) -> None:
        self._editor.hide()
        self._update_text()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._editor:
            if event.type() == event.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel_rename()
                    return True
                elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._commit_rename()
                    return True
            elif event.type() == event.Type.FocusOut:
                if time.time() - self._rename_start_time > 0.25:
                    self._commit_rename()
                    return True
        return super().eventFilter(watched, event)


def _icon_button(
    image: str, fallback: str, tooltip: str = "", glyph: str | None = None
) -> QToolButton:
    btn = QToolButton()
    pm = assets.ui_image(image)
    if pm is None and glyph is not None:
        pm = assets.glyph_icon(glyph)
    if pm is not None:
        btn.setIcon(QIcon(pm))
        btn.setIconSize(QSize(18, 18))
    else:
        btn.setText(fallback)
    btn.setAutoRaise(True)
    btn.setCursor(Qt.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


class EditorToolbar(QWidget):
    """Editor top strip (pure signals; state is set via set_*)."""

    prev_preset = Signal()
    next_preset = Signal()
    snapshot_selected = Signal(int)
    undo_requested = Signal()
    redo_requested = Signal()
    import_requested = Signal()
    export_requested = Signal()
    save_requested = Signal()
    rename_requested = Signal(str)
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(8)

        updown = QVBoxLayout()
        updown.setContentsMargins(0, 0, 0, 0)
        updown.setSpacing(0)
        self.prev_btn = QToolButton()
        self.prev_btn.setArrowType(Qt.UpArrow)
        self.prev_btn.setFixedSize(22, 14)
        self.prev_btn.setToolTip("Previous preset")
        self.prev_btn.clicked.connect(self.prev_preset)
        self.next_btn = QToolButton()
        self.next_btn.setArrowType(Qt.DownArrow)
        self.next_btn.setFixedSize(22, 14)
        self.next_btn.setToolTip("Next preset")
        self.next_btn.clicked.connect(self.next_preset)
        updown.addWidget(self.prev_btn)
        updown.addWidget(self.next_btn)
        lay.addLayout(updown)

        self.title_label = EditablePresetTitle(self)
        self.title_label.rename_committed.connect(self.rename_requested)
        self.title_label.file_dropped.connect(self.file_dropped)
        lay.addWidget(self.title_label)

        self.save_btn = _icon_button(
            "btn-preset-save", "Save",
            "Save the active buffer to the current slot", glyph="save",
        )
        self.save_btn.clicked.connect(self.save_requested)
        lay.addWidget(self.save_btn)

        self.snapshots_btn = _icon_button(
            "icon-snapshots", "📷", "Preset snapshots", glyph="camera"
        )
        self.snapshots_btn.setPopupMode(QToolButton.InstantPopup)
        self._snap_menu = QMenu(self)
        self.snapshot_actions = []
        for i in range(4):
            act = self._snap_menu.addAction(f"{i + 1}: SNAPSHOT {i + 1}")
            act.setCheckable(True)
            act.triggered.connect(lambda _c, n=i: self.snapshot_selected.emit(n))
            self.snapshot_actions.append(act)
        self.snapshots_btn.setMenu(self._snap_menu)
        lay.addWidget(self.snapshots_btn)

        self.undo_btn = _icon_button(
            "btn-undo", "↶", "Undo (Ctrl+Z)", glyph="undo"
        )
        self.undo_btn.clicked.connect(self.undo_requested)
        self.undo_btn.setEnabled(False)
        lay.addWidget(self.undo_btn)
        self.redo_btn = _icon_button(
            "btn-redo", "↷", "Redo (Ctrl+Shift+Z)", glyph="redo"
        )
        self.redo_btn.clicked.connect(self.redo_requested)
        self.redo_btn.setEnabled(False)
        lay.addWidget(self.redo_btn)

        lay.addStretch(1)

        self.tempo_label = QLabel("")
        self.tempo_label.setToolTip("Preset tempo")
        lay.addWidget(self.tempo_label)

        self.import_btn = QPushButton("Import .pgp…")
        self.import_btn.clicked.connect(self.import_requested)
        lay.addWidget(self.import_btn)
        self.export_btn = QPushButton("Export .pgp…")
        self.export_btn.clicked.connect(self.export_requested)
        lay.addWidget(self.export_btn)

    # --- estado ---

    def set_title(self, slot_text: str, name: str, modified: bool) -> None:
        self.title_label.set_preset_info(slot_text, name, modified)

    def start_rename(self) -> None:
        self.title_label.start_rename()

    def set_snapshots(self, names: list[str], current: int) -> None:
        for i, act in enumerate(self.snapshot_actions):
            label = names[i] if i < len(names) and names[i] else f"SNAPSHOT {i + 1}"
            act.setText(f"{i + 1}: {label}")
            act.setChecked(i == current)

    def set_tempo(self, tempo: float | None) -> None:
        self.tempo_label.setText(f"♩ {tempo:g}" if tempo else "")

    def set_undo_redo(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)
