"""Editor toolbar, modeled after the top strip of POD Go Edit:

[▴▾] [01A Name ●] [Save] [Snapshots ▾] [↶ ↷]  …  [♩ tempo] [Reread] [Export]

Save remains disabled until spec 03 (writing to the pedal); Reread and
Export .pgp are ours in the meantime.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import assets




def _icon_button(
    image: str, fallback: str, tooltip: str = "", glyph: str | None = None
) -> QToolButton:
    btn = QToolButton()
    # Prefer the official res/ sprite; otherwise a crisp drawn vector glyph;
    # only fall back to raw text/emoji if neither is available.
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
    reread_requested = Signal()
    export_requested = Signal()
    save_requested = Signal()

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

        self.title_label = QLabel("")
        self.title_label.setObjectName("title")
        self.title_label.setTextFormat(Qt.RichText)
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

        self.reread_btn = QPushButton("Reread from pedal")
        self.reread_btn.clicked.connect(self.reread_requested)
        lay.addWidget(self.reread_btn)
        self.export_btn = QPushButton("Export .pgp…")
        self.export_btn.clicked.connect(self.export_requested)
        lay.addWidget(self.export_btn)

    # --- estado ---

    def set_title(self, slot_text: str, name: str, modified: bool) -> None:
        slot_html = f"<b>{slot_text}</b>&nbsp; " if slot_text else ""
        dot = " ●" if modified else ""
        self.title_label.setText(f"{slot_html}{name}{dot}")

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
