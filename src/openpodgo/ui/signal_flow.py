"""Signal Flow panel in the POD Go Edit style.

Horizontal line with the input (⊙) on the left, the output (→) on the right,
and the preset's 10 blocks as official pedal/amp icons. As in the official app:
bypassed block = dimmed, selected block = caret pointing to the inspector,
gray label above with the bypass assignment ("FS2", "EXP Toe"), and
bypass/clear buttons on hover.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QToolButton, QWidget

from .. import catalog
from . import assets, palette
from .names import short_name

#: MIME type for dragging a block within the chain (carries the source slot).
BLOCK_MIME = "application/x-podgo-block-slot"

#: Block geometry: label strip + icon + caret zone.
LABEL_H = 16
ICON_W, ICON_H = 56, 64
CARET_H = 10
BLOCK_W = ICON_W + 8

_LINE_COLOR = "#3a3f47"
_LABEL_COLOR = "#9aa0a8"
_CARET_COLOR = "#e6e6e6"
_EMPTY_BORDER = "#4a4f57"


class BlockWidget(QWidget):
    """A chain slot, painted with the model's official icon."""

    clicked = Signal(int)
    double_clicked = Signal(int)
    menu_requested = Signal(int)
    bypass_requested = Signal(int)
    clear_requested = Signal(int)

    def __init__(self, slot: int) -> None:
        super().__init__()
        self.slot = slot
        self.setFixedSize(BLOCK_W, LABEL_H + ICON_H + CARET_H)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda _pos: self.menu_requested.emit(self.slot)
        )
        self.model_name: str | None = None
        self.assign_label = ""
        self.block_enabled = True
        self.selected = False
        self._display = ""
        self._press_pos: QPoint | None = None
        self.bypass_btn = self._hover_button(
            "btn-signalflow-bypass", "⏻", self.bypass_requested
        )
        self.clear_btn = self._hover_button(
            "btn-signalflow-delete", "✕", self.clear_requested
        )
        self.bypass_btn.move(BLOCK_W - 20, LABEL_H)
        self.clear_btn.move(0, LABEL_H)

    def _hover_button(self, image: str, fallback: str, signal) -> QToolButton:
        btn = QToolButton(self)
        pm = assets.ui_image(image)
        if pm is not None:
            btn.setIcon(QIcon(pm))
            btn.setIconSize(QSize(16, 16))
        else:
            btn.setText(fallback)
        btn.setFixedSize(20, 20)
        btn.setAutoRaise(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: signal.emit(self.slot))
        btn.hide()
        return btn

    # --- estado ---

    @property
    def is_empty(self) -> bool:
        return self.model_name is None

    def model_text(self) -> str:
        """Visible model name ("" if the slot is empty)."""
        return self._display

    def update_block(
        self, block, model_name: str | None, assign_label: str = ""
    ) -> None:
        """Refreshes the slot with the decoded block (or None if empty)."""
        self.assign_label = assign_label
        if block is None:
            self.model_name = None
            self._display = ""
            self.block_enabled = True
            self.setToolTip("Empty slot — right-click to add a block")
        else:
            self.model_name = model_name
            info = catalog.model_info(model_name) if model_name else None
            if info is not None and info.display_name:
                self._display = info.display_name
            elif model_name:
                self._display = short_name(model_name)
            else:
                self._display = f"Modelo {block.model_id}"
            self.block_enabled = block.enabled
            self.setToolTip(
                f"{self._display} — doble click: bypass"
                + (f" ({assign_label})" if assign_label else "")
            )
        self.update()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    # --- pintura ---

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        if self.assign_label:
            font = p.font()
            font.setPixelSize(10)
            p.setFont(font)
            p.setPen(QColor(_LABEL_COLOR))
            p.drawText(
                0, 0, self.width(), LABEL_H, Qt.AlignCenter, self.assign_label
            )

        icon_area = self.rect().adjusted(
            (self.width() - ICON_W) // 2,
            LABEL_H,
            -(self.width() - ICON_W) // 2,
            -CARET_H,
        )
        if self.is_empty:
            pen = QPen(QColor(_EMPTY_BORDER))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(icon_area.adjusted(6, 6, -6, -6), 6, 6)
            p.setPen(QColor(_LABEL_COLOR))
            font = p.font()
            font.setPixelSize(18)
            p.setFont(font)
            p.drawText(icon_area, Qt.AlignCenter, "+")
        else:
            pm = assets.model_icon(self.model_name) if self.model_name else None
            if not self.block_enabled:
                p.setOpacity(0.45)
            if pm is not None:
                scaled = pm.scaled(
                    icon_area.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                x = icon_area.x() + (icon_area.width() - scaled.width()) // 2
                y = icon_area.y() + (icon_area.height() - scaled.height()) // 2
                p.drawPixmap(x, y, scaled)
            else:
                # No assets: flat block in the category's color.
                cat = (
                    catalog.display_category(self.model_name)
                    if self.model_name
                    else None
                )
                color = QColor(palette.category_color(cat))
                if not self.block_enabled:
                    color = palette.dimmed(color)
                p.setBrush(color)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(icon_area.adjusted(4, 4, -4, -4), 6, 6)
            p.setOpacity(1.0)

        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_CARET_COLOR))
            cx = self.width() // 2
            base = self.height() - CARET_H + 2
            p.drawPolygon(
                [
                    QPoint(cx - 6, base),
                    QPoint(cx + 6, base),
                    QPoint(cx, base + 7),
                ]
            )

    # --- interaction ---

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self.clicked.emit(self.slot)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Starts block dragging when the threshold is exceeded (non-empty only)."""
        if (
            self.is_empty
            or self._press_pos is None
            or not (event.buttons() & Qt.LeftButton)
        ):
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        self._set_hovered(False)  # ocultar botones de hover durante el drag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(BLOCK_MIME, str(self.slot).encode())
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.MoveAction)
        self._press_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit(self.slot)
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event) -> None:
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hovered(False)
        super().leaveEvent(event)

    def _set_hovered(self, hovered: bool) -> None:
        show = hovered and not self.is_empty
        self.bypass_btn.setVisible(show)
        self.clear_btn.setVisible(show)


class _IoWidget(QWidget):
    """Chain endpoint: input (⊙ guitar) or output (→).

    Clickable: selects the Input/Output block to edit its params (#2).
    """

    clicked = Signal(str)

    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind
        self.selected = False
        self.setFixedSize(40, LABEL_H + ICON_H + CARET_H)
        self.setCursor(Qt.PointingHandCursor)
        self._pm = assets.chain_icon(kind)
        self._fallback = "⊙" if kind == "input" else "→"
        self.setToolTip(
            "Input — click to edit the noise gate"
            if kind == "input"
            else "Output — click to edit pan/level"
        )

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.kind)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = self.rect().adjusted(2, LABEL_H + 14, -2, -CARET_H - 14)
        if self._pm is not None:
            scaled = self._pm.scaled(
                area.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            x = area.x() + (area.width() - scaled.width()) // 2
            y = area.y() + (area.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            p.setPen(QColor(_LABEL_COLOR))
            p.drawText(self.rect(), Qt.AlignCenter, self._fallback)
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_CARET_COLOR))
            cx = self.width() // 2
            base = self.height() - CARET_H + 2
            p.drawPolygon(
                [
                    QPoint(cx - 6, base),
                    QPoint(cx + 6, base),
                    QPoint(cx, base + 7),
                ]
            )


class SignalFlowPanel(QWidget):
    """Chain strip: ⊙ → 10 blocks → →, over the signal line."""

    block_selected = Signal(int)
    io_selected = Signal(str)
    bypass_toggled = Signal(int)
    menu_requested = Signal(int)
    clear_requested = Signal(int)
    block_moved = Signal(int, int)  # (source slot, destination slot)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self._drop_slot: int | None = None
        self._drag_src: int | None = None  # source slot of the current drag (#3)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(4)
        self.io_input = _IoWidget("input")
        self.io_input.clicked.connect(self.io_selected)
        lay.addWidget(self.io_input)
        self.slot_widgets: list[BlockWidget] = []
        for slot in range(10):
            w = BlockWidget(slot)
            w.clicked.connect(self.block_selected)
            w.double_clicked.connect(self.bypass_toggled)
            w.bypass_requested.connect(self.bypass_toggled)
            w.menu_requested.connect(self.menu_requested)
            w.clear_requested.connect(self.clear_requested)
            self.slot_widgets.append(w)
            lay.addWidget(w)
        self.io_output = _IoWidget("output")
        self.io_output.clicked.connect(self.io_selected)
        lay.addWidget(self.io_output)
        lay.addStretch(1)

    def update_from(
        self, preset, selected, assignments: dict[int, str] | None = None
    ) -> None:
        assignments = assignments or {}
        for slot, widget in enumerate(self.slot_widgets):
            block = preset.chain[slot]
            md = catalog.lookup(block.model_id) if block else None
            widget.update_block(
                block,
                md.name if md else None,
                assignments.get(slot, "") if block else "",
            )
            widget.set_selected(slot == selected)
        self.io_input.set_selected(selected == "input")
        self.io_output.set_selected(selected == "output")

    # --- block dragging ---

    def _slot_at(self, x: int) -> int:
        """Slot whose widget contains the cursor's x (clamped to the edges)."""
        for w in self.slot_widgets:
            if x < w.x() + w.width():
                return w.slot
        return self.slot_widgets[-1].slot

    def _caret_side(self, src: int | None, dst: int) -> str:
        """Side of slot `dst` where the block will land on drop (#3).

        `move_block` does pop(src)+insert(dst): when moving right the block
        ends up AFTER the slot under the cursor; when moving left (or with no
        source), before. This way the caret marks the actual final position,
        without "shifting".
        """
        if src is not None and src < dst:
            return "right"
        return "left"

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(BLOCK_MIME):
            self._drag_src = int(bytes(event.mimeData().data(BLOCK_MIME)).decode())
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(BLOCK_MIME):
            return
        self._drop_slot = self._slot_at(int(event.position().x()))
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, _event) -> None:
        self._drop_slot = None
        self._drag_src = None
        self.update()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(BLOCK_MIME):
            return
        src = int(bytes(event.mimeData().data(BLOCK_MIME)).decode())
        dst = self._slot_at(int(event.position().x()))
        self._drop_slot = None
        self._drag_src = None
        self.update()
        if dst != src:
            self.block_moved.emit(src, dst)
        event.acceptProposedAction()

    def paintEvent(self, _event) -> None:
        # Signal line behind the blocks, at the icon's vertical center.
        p = QPainter(self)
        y = LABEL_H + ICON_H // 2
        p.setPen(QPen(QColor(_LINE_COLOR), 2))
        if self.slot_widgets:
            x1 = 8
            last = self.slot_widgets[-1]
            x2 = last.x() + last.width() + 40
            p.drawLine(x1, y, min(x2, self.width() - 8), y)
        # Insertion indicator during a drag: on the side where the block
        # actually lands on drop (#3), not always on the left edge.
        if self._drop_slot is not None:
            w = self.slot_widgets[self._drop_slot]
            if self._caret_side(self._drag_src, self._drop_slot) == "right":
                bx = w.x() + w.width() + 2
            else:
                bx = w.x() - 2
            p.setPen(QPen(QColor(_CARET_COLOR), 3))
            p.drawLine(bx, LABEL_H, bx, LABEL_H + ICON_H)
