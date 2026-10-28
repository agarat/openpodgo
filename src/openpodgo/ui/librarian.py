"""Librarian panel in the POD Go Edit style: setlist folders + preset list.

Left column of the single window. Factory/User folders use the official icons
(2-state sprites); the preset loaded on the pedal is marked in amber with
"▸", as in the official app.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import assets, palette

LOADED_PREFIX = "▸ "

#: setlist conocido → imagen oficial de carpeta.
_FOLDER_IMAGES = {"factory": "btn-factory-folder", "user": "btn-user-folder"}


class PresetListWidget(QListWidget):
    """QListWidget supporting in-place editing of preset names and dropping .pgp files."""

    long_pressed = Signal(int, str)  # slot, name
    rename_committed = Signal(int, str)  # slot, new_name
    preset_dropped = Signal(int, str)  # slot, file_path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._pressed_item: QListWidgetItem | None = None
        self._pressed_pos: QPoint | None = None
        self._long_pressed_triggered = False
        self._long_timer = QTimer(self)
        self._long_timer.setSingleShot(True)
        self._long_timer.setInterval(500)
        self._long_timer.timeout.connect(self._on_long_press)

        self._editing_item: QListWidgetItem | None = None
        self._editing_slot: int | None = None
        self._rename_start_time = 0.0

        self._editor = QLineEdit(self.viewport())
        self._editor.setObjectName("preset_list_edit")
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
        if self._has_pgp_url(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._has_pgp_url(event.mimeData()):
            pos = (
                event.position().toPoint()
                if hasattr(event, "position")
                else event.pos()
            )
            item = self.itemAt(pos)
            if item is not None:
                self.setCurrentItem(item)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if self._has_pgp_url(event.mimeData()):
            path = self._extract_pgp_path(event.mimeData())
            if path:
                pos = (
                    event.position().toPoint()
                    if hasattr(event, "position")
                    else event.pos()
                )
                item = self.itemAt(pos) or self.currentItem()
                if item is not None:
                    slot = item.data(Qt.UserRole)
                    if slot is not None:
                        event.acceptProposedAction()
                        self.preset_dropped.emit(slot, path)
                        return
        super().dropEvent(event)

    def start_rename(self, item: QListWidgetItem | None = None) -> None:
        if item is None:
            item = self.currentItem()
        if item is None:
            return
        slot = item.data(Qt.UserRole)
        name = item.data(Qt.UserRole + 1)
        if slot is None or name is None:
            return

        self._editing_item = item
        self._editing_slot = slot
        self._rename_start_time = time.time()

        rect = self.visualItemRect(item)
        full_text = item.text()
        prefix = full_text.split(name)[0] if name in full_text else ""
        fm = self.fontMetrics()
        prefix_width = fm.horizontalAdvance(prefix) if prefix else 0

        x = rect.x() + prefix_width + 4
        y = rect.y() + 1
        w = max(rect.width() - (prefix_width + 8), 100)
        h = max(rect.height() - 2, 22)

        self._editor.setGeometry(x, y, w, h)
        self._editor.setText(name)
        self._editor.show()
        self._editor.setFocus()
        self._editor.selectAll()

    def _commit_rename(self) -> None:
        if self._editor.isHidden() or self._editing_slot is None:
            return
        new_name = self._editor.text().strip()[:32]
        slot = self._editing_slot
        self._editor.hide()
        self._editing_slot = None
        self._editing_item = None
        if new_name:
            self.rename_committed.emit(slot, new_name)

    def cancel_rename(self) -> None:
        self._editor.hide()
        self._editing_slot = None
        self._editing_item = None

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

    def mousePressEvent(self, event) -> None:
        if not self._editor.isHidden():
            self._commit_rename()
        if event.button() == Qt.MouseButton.LeftButton:
            pos = (
                event.position().toPoint()
                if hasattr(event, "position")
                else event.pos()
            )
            item = self.itemAt(pos)
            if item is not None:
                self._pressed_item = item
                self._pressed_pos = pos
                self._long_pressed_triggered = False
                self._long_timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed_pos is not None:
            pos = (
                event.position().toPoint()
                if hasattr(event, "position")
                else event.pos()
            )
            if (pos - self._pressed_pos).manhattanLength() > QApplication.startDragDistance():
                self._long_timer.stop()
                self._pressed_item = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._long_timer.stop()
        if self._long_pressed_triggered:
            self._long_pressed_triggered = False
            self._pressed_item = None
            event.accept()
            return
        self._pressed_item = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = (
                event.position().toPoint()
                if hasattr(event, "position")
                else event.pos()
            )
            item = self.itemAt(pos)
            if item is not None:
                self._long_timer.stop()
                self._long_pressed_triggered = True
                self.start_rename(item)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _on_long_press(self) -> None:
        if self._pressed_item is not None:
            self._long_pressed_triggered = True
            slot = self._pressed_item.data(Qt.UserRole)
            name = self._pressed_item.data(Qt.UserRole + 1)
            item = self._pressed_item
            if slot is not None and name is not None:
                self.long_pressed.emit(slot, name)
                self.start_rename(item)


class LibrarianPanel(QWidget):
    """Setlist folders on top, presets below; pure signals outward."""

    setlist_changed = Signal(int)
    preset_activated = Signal(int)  # position in the setlist (= MIDI PC)
    import_requested = Signal(int)  # target slot to import into
    export_requested = Signal(int)  # target slot to export from
    rename_requested = Signal(int, str)  # (slot, current_name)
    rename_committed = Signal(int, str)  # (slot, new_name)
    preset_dropped = Signal(int, str)  # (slot, file_path)
    reset_requested = Signal(int)  # target slot to reset
    refresh_requested = Signal()
    reconnect_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(210)
        self._loaded: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        from .. import __version__
        try:
            from importlib.metadata import version
            ver_raw = version("openpodgo")
        except Exception:
            ver_raw = __version__
        ver = f"v{ver_raw.split('+')[0]}"

        self.brand_label = QLabel()
        self.brand_label.setObjectName("brand_logo")
        self.brand_label.setTextFormat(Qt.RichText)
        self.brand_label.setToolTip(f"OpenPodGo {ver}")
        self.brand_label.setText(
            f'<span style="color: #ffffff; font-weight: 700;">Open</span>'
            f'<span style="color: #2b9bf0; font-weight: 700;">Pod</span>'
            f'<span style="color: #ff9020; font-weight: 700;">Go</span> '
            f'<span style="font-family: \'Inter\', \'Ubuntu\', sans-serif; font-style: normal; font-size: 11px; font-weight: 500; color: #8a8f98;">{ver}</span>'
        )
        lay.addWidget(self.brand_label)

        self._folders = QHBoxLayout()
        self._folders.setSpacing(4)
        self.folder_buttons: list[QToolButton] = []
        lay.addLayout(self._folders)

        self.offline_label = QLabel("No pedal connected")
        self.offline_label.setObjectName("hint")
        self.offline_label.hide()
        lay.addWidget(self.offline_label)
        self.reconnect_btn = QPushButton("Reconnect")
        self.reconnect_btn.clicked.connect(self.reconnect_requested)
        self.reconnect_btn.hide()
        lay.addWidget(self.reconnect_btn)

        self.list = PresetListWidget()
        self.list.setObjectName("presetList")
        self.list.itemClicked.connect(self._on_activate)
        self.list.itemActivated.connect(self._on_activate)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self.list.long_pressed.connect(self.rename_requested)
        self.list.rename_committed.connect(self.rename_committed)
        self.list.preset_dropped.connect(self.preset_dropped)
        lay.addWidget(self.list, 1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("refresh_btn")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_requested)
        lay.addWidget(self.refresh_btn)

    # --- setlists ---

    def set_setlists(self, names: list[str], current: int) -> None:
        while self._folders.count():
            item = self._folders.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.folder_buttons = []
        for i, name in enumerate(names):
            btn = QToolButton()
            btn.setObjectName("setlist_tab")
            btn.setText(name)
            btn.setCheckable(True)
            btn.setChecked(i == current)
            btn.setCursor(Qt.PointingHandCursor)
            image = _FOLDER_IMAGES.get(name.lower())
            pm = assets.ui_image(image) if image else None
            if pm is not None:
                btn.setIcon(QIcon(pm))
                btn.setIconSize(QSize(34, 26))
                btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            else:
                btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.clicked.connect(lambda _c, n=i: self._folder_clicked(n))
            self.folder_buttons.append(btn)
            self._folders.addWidget(btn)
        self._folders.addStretch(1)

    def _folder_clicked(self, n: int) -> None:
        for i, btn in enumerate(self.folder_buttons):
            btn.setChecked(i == n)
        self.setlist_changed.emit(n)

    # --- presets ---

    def set_presets(self, presets) -> None:
        self.list.clear()
        self._loaded = None
        for p in presets:
            item = QListWidgetItem(self._label(p.slot, p.name))
            item.setData(Qt.UserRole, p.slot)
            item.setData(Qt.UserRole + 1, p.name)
            self.list.addItem(item)

    @staticmethod
    def _label(position: int, name: str, loaded: bool = False) -> str:
        bank = position // 4 + 1  # POD Go numbers banks starting from 01
        letter = "ABCD"[position % 4]
        prefix = LOADED_PREFIX if loaded else ""
        return f"{prefix}{bank:02d}{letter}  {name}"

    @property
    def loaded(self) -> int | None:
        """Position of the preset loaded on the pedal (None if unknown)."""
        return self._loaded

    def set_loaded(self, position: int | None) -> None:
        """Marks the preset loaded on the pedal (amber + ▸, official style)."""
        self._loaded = position
        amber = QBrush(QColor(palette.LOADED_AMBER))
        normal = QBrush(QColor("#e6e6e6"))
        for i in range(self.list.count()):
            item = self.list.item(i)
            pos = item.data(Qt.UserRole)
            name = item.data(Qt.UserRole + 1)
            loaded = pos == position
            item.setText(self._label(pos, name, loaded))
            item.setForeground(amber if loaded else normal)

    def update_preset_name(self, position: int, new_name: str) -> None:
        """Update the name of a preset in the list item without reloading the whole list."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == position:
                item.setData(Qt.UserRole + 1, new_name)
                loaded = (position == self._loaded)
                item.setText(self._label(position, new_name, loaded))
                break

    def current_slot(self) -> int | None:
        """Slot of the currently selected preset item, or loaded slot if none."""
        item = self.list.currentItem()
        if item is not None:
            return item.data(Qt.UserRole)
        return self._loaded

    def preset_name(self, slot: int) -> str | None:
        """Name of preset at slot."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == slot:
                return item.data(Qt.UserRole + 1)
        return None

    def start_rename_slot(self, slot: int) -> None:
        """Starts in-place rename on the list item corresponding to the given slot."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == slot:
                self.list.setCurrentItem(item)
                self.list.start_rename(item)
                break

    def _on_activate(self, item: QListWidgetItem) -> None:
        self.preset_activated.emit(item.data(Qt.UserRole))

    def _show_context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        slot = item.data(Qt.UserRole)
        name = item.data(Qt.UserRole + 1)
        menu = QMenu(self)
        act_rename = menu.addAction("Rename…")
        act_rename.triggered.connect(lambda: self.list.start_rename(item))
        menu.addSeparator()
        act_import = menu.addAction("Import preset…")
        act_import.triggered.connect(lambda: self.import_requested.emit(slot))
        act_export = menu.addAction("Export preset…")
        act_export.triggered.connect(lambda: self.export_requested.emit(slot))
        menu.addSeparator()
        act_reset = menu.addAction("Reset preset…")
        act_reset.triggered.connect(lambda: self.reset_requested.emit(slot))
        menu.exec(self.list.mapToGlobal(pos))

    # --- connection ---

    def set_offline(self, offline: bool) -> None:
        self.offline_label.setVisible(offline)
        self.reconnect_btn.setVisible(offline)
        self.list.setEnabled(not offline)
        self.refresh_btn.setEnabled(not offline)
        if offline:
            self.list.clear()

