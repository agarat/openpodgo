"""Librarian panel in the POD Go Edit style: setlist folders + preset list.

Left column of the single window. Factory/User folders use the official icons
(2-state sprites); the preset loaded on the pedal is marked in amber with
"▸", as in the official app.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
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


class LibrarianPanel(QWidget):
    """Setlist folders on top, presets below; pure signals outward."""

    setlist_changed = Signal(int)
    preset_activated = Signal(int)  # position in the setlist (= MIDI PC)
    import_requested = Signal(int)  # target slot to import into
    refresh_requested = Signal()
    reconnect_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(210)
        self._loaded: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        logo = assets.ui_image("PODGoLogo-small")
        if logo is not None:
            logo_label = QLabel()
            logo_label.setPixmap(logo)
            logo_label.setFixedHeight(logo.height())
            lay.addWidget(logo_label)

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

        self.list = QListWidget()
        self.list.setObjectName("presetList")
        self.list.itemClicked.connect(self._on_activate)
        self.list.itemActivated.connect(self._on_activate)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        lay.addWidget(self.list, 1)

        self.refresh_btn = QPushButton("Refresh")
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
            btn.setText(name)
            btn.setCheckable(True)
            btn.setChecked(i == current)
            image = _FOLDER_IMAGES.get(name.lower())
            pm = assets.ui_image(image) if image else None
            if pm is not None:
                btn.setIcon(QIcon(pm))
                btn.setIconSize(QSize(34, 26))
                btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
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

    def _on_activate(self, item: QListWidgetItem) -> None:
        self.preset_activated.emit(item.data(Qt.UserRole))

    def _show_context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        slot = item.data(Qt.UserRole)
        menu = QMenu(self)
        act = menu.addAction("Import preset…")
        act.triggered.connect(lambda: self.import_requested.emit(slot))
        menu.exec(self.list.mapToGlobal(pos))

    # --- connection ---

    def set_offline(self, offline: bool) -> None:
        self.offline_label.setVisible(offline)
        self.reconnect_btn.setVisible(offline)
        self.list.setEnabled(not offline)
        self.refresh_btn.setEnabled(not offline)
        if offline:
            self.list.clear()
