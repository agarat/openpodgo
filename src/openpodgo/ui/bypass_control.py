"""Bypass/Control Panel (spec 09): editor sub-panel in the POD Go Edit style.

Replicates the "Bypass & Controller Assignment" window from the manual (v2.50,
pp. 27–34): a Parameter menu with the selected block's params (plus "Bypass"),
a selector grid (None, FS1–FS8, EXP Toe, EXP 1/2, Snapshots) with their
official icons, assignment indicators (label + category color ring), Min/Max
sliders for controllers, and a per-FS menu with Rename / Color / See All
Assignments.

Capabilities (see docs/specs/09-bypass-control-assign.md):
- Bypass (body[3]): full CRUD (create/move/clear + label + color), known
  structure and validated .pgp round-trip.
- Controller (body[4]): display + edit Min/Max + clear existing ones. CREATING
  controllers on arbitrary params is RE-blocked (the destination block binding
  is not carried in body[4]); the panel reports this in its status bar instead
  of writing something the pedal would not honor.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import catalog
from ..editor import FS_COLOR_NAMES, ControllerAssignUnsupported, PresetEditor
from . import assets, palette
from .inspector import ValueSpinBox

#: Official icon (swatch) by footswitch palette color index.
_FS_COLOR_ICON = {
    0: "icon-fs", 1: "icon-fs-white", 2: "icon-fs-red", 3: "icon-fs-darkorange",
    4: "icon-fs-lightorange", 5: "icon-fs-yellow", 6: "icon-fs-green",
    7: "icon-fs-turquoise", 8: "icon-fs-blue", 9: "icon-fs-violet",
    10: "icon-fs-pink", 11: "icon-fs-none",
}

#: Selector grid labels, in manual order. "Mode" and "Tap" are NOT assignable
#: (disabled, as in POD Go Edit).
SELECTOR_ORDER = (
    "None", "FS1", "FS2", "FS3", "FS4", "FS5", "FS6", "Mode", "EXP Toe",
    "FS7", "FS8", "Tap", "EXP 1", "EXP 2", "Snapshots",
)
DISABLED_SELECTORS = frozenset({"Mode", "Tap"})
#: Bypass targets that the data layer knows how to write (FS1–8 + toe switch).
BYPASS_OK = frozenset(
    {"FS1", "FS2", "FS3", "FS4", "FS5", "FS6", "FS7", "FS8", "EXP Toe"}
)
#: Official icon per selector (None → text if the asset is missing).
_SELECTOR_ICON = {
    "None": "icon-fs-none",
    "EXP Toe": "icon-ext-fs",
    "EXP 1": "icon-exp1",
    "EXP 2": "icon-exp2",
    "Snapshots": "icon-snapshot-assign",
}


def _selector_icon(name: str) -> str:
    if name in _SELECTOR_ICON:
        return _SELECTOR_ICON[name]
    return "icon-fs" if name.startswith("FS") else "icon-fs-none"


def _fs_color_icon(index: int) -> QIcon | None:
    """Palette color swatch for `index`, or None if the asset is missing."""
    pm = assets.ui_image(_FS_COLOR_ICON.get(index, "icon-fs"))
    return QIcon(pm) if pm is not None else None


class _SelectorButton(QToolButton):
    """Controller button (FS/EXP/Snapshot) with icon + label + ring."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(name)
        self.setIconSize(QSize(26, 26))
        pm = assets.ui_image(_selector_icon(name))
        if pm is not None:
            self.setIcon(QIcon(pm))
        self.setFixedSize(64, 56)
        self.set_ring(None)

    def set_ring(self, color: str | None) -> None:
        """Category color ring when the selector is assigned."""
        ring = (
            f"border: 2px solid {color};" if color else "border: 1px solid #2e3238;"
        )
        checked = "QToolButton:checked { background: #2e3238; }"
        self.setStyleSheet(
            f"QToolButton {{ {ring} border-radius: 6px; font-size: 10px;"
            " color: #cfd3d9; padding: 2px; }" + checked
        )


class AssignmentsListDialog(QDialog):
    """Assignment list for a FS (manual p. 32): delete individual / all."""

    def __init__(self, panel: "BypassControlPanel", target: str) -> None:
        super().__init__(panel)
        self._panel = panel
        self._target = target
        self.setWindowTitle(f"Assignments for {target}")
        self._lay = QVBoxLayout(self)
        self._rebuild()

    def _rebuild(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        ed = self._panel.editor
        slots = ed.bypass_blocks_on(self._target) if ed else []
        header = QLabel(f"<b>{self._target}</b> — {len(slots)} assignment(s)")
        self._lay.addWidget(header)
        for slot in slots:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            name = ed._model_display(slot)
            h.addWidget(QLabel(f"{name}  ·  Bypass"))
            h.addStretch(1)
            x = QPushButton("✕")
            x.setFixedWidth(28)
            x.clicked.connect(lambda _=False, s=slot: self._remove(s))
            h.addWidget(x)
            self._lay.addWidget(row)
        clear_all = QPushButton("Clear All")
        clear_all.clicked.connect(self._clear_all)
        self._lay.addWidget(clear_all)

    def _remove(self, slot: int) -> None:
        self._panel.editor.clear_bypass_assign(slot)
        self._panel._after_change()
        self._rebuild()

    def _clear_all(self) -> None:
        ed = self._panel.editor
        for slot in list(ed.bypass_blocks_on(self._target)):
            ed.clear_bypass_assign(slot)
        self._panel._after_change()
        self._rebuild()


class BypassControlPanel(QWidget):
    """Bypass/Control sub-panel for the selected block."""

    #: Emitted after a mutation (EditorView refreshes + marks as modified).
    changed = Signal()
    close_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.editor: PresetEditor | None = None
        self.slot: int | None = None
        self._buttons: dict[str, _SelectorButton] = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Bypass / Control")
        title.setStyleSheet("font-weight: 700; color: #cfd3d9;")
        top.addWidget(title)
        top.addStretch(1)
        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Close (Ctrl+B)")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close_requested)
        top.addWidget(close)
        root.addLayout(top)

        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("Parameter:"))
        self.param_menu = QComboBox()
        self.param_menu.currentIndexChanged.connect(self._param_changed)
        param_row.addWidget(self.param_menu, 1)
        root.addLayout(param_row)

        grid = QGridLayout()
        grid.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, name in enumerate(SELECTOR_ORDER):
            btn = _SelectorButton(name)
            if name in DISABLED_SELECTORS:
                btn.setEnabled(False)
            else:
                btn.clicked.connect(lambda _=False, n=name: self._select(n))
                if name in BYPASS_OK:
                    # Right-click on a FS: view assignments / rename / color
                    # for THAT footswitch (manual p. 32-33), independent of
                    # the selected block.
                    btn.setToolTip(
                        f"Click: assign · Right-click: view/rename/color for {name}"
                    )
                    btn.setContextMenuPolicy(Qt.CustomContextMenu)
                    btn.customContextMenuRequested.connect(
                        lambda pos, n=name, b=btn: self._fs_menu(
                            n, b.mapToGlobal(pos)
                        )
                    )
            self._group.addButton(btn)
            self._buttons[name] = btn
            grid.addWidget(btn, i // 8, i % 8)
        root.addLayout(grid)

        hint = QLabel("Right-click on a FS: view assignments, rename, color.")
        hint.setStyleSheet("color: #8a8f98; font-size: 10px;")
        root.addWidget(hint)

        # Min/Max sliders (only for existing controllers).
        self._minmax = QWidget()
        mm = QGridLayout(self._minmax)
        mm.setContentsMargins(0, 0, 0, 0)
        mm.addWidget(QLabel("Min"), 0, 0)
        self.min_slider, self.min_spin = self._make_slider()
        mm.addWidget(self.min_slider, 0, 1)
        mm.addWidget(self.min_spin, 0, 2)
        mm.addWidget(QLabel("Max"), 1, 0)
        self.max_slider, self.max_spin = self._make_slider()
        mm.addWidget(self.max_slider, 1, 1)
        mm.addWidget(self.max_spin, 1, 2)
        mm.setColumnStretch(1, 1)
        root.addWidget(self._minmax)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #8a8f98; font-size: 11px;")
        root.addWidget(self.status)
        root.addStretch(1)

    def _make_slider(self):
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 1000)
        spin = ValueSpinBox(0.0, 1.0)
        sl.sliderMoved.connect(lambda pos, s=spin: s.setValue(pos / 1000))
        sl.sliderReleased.connect(self._commit_minmax)
        spin.editingFinished.connect(self._commit_minmax)
        return sl, spin

    # --- public API ---

    def show_block(self, editor: PresetEditor, slot: int) -> None:
        """Loads the block's assignments for the given slot into the panel."""
        self.editor = editor
        self.slot = slot
        block = editor.preset.chain[slot] if slot is not None else None
        self.param_menu.blockSignals(True)
        self.param_menu.clear()
        if block is None:
            self.param_menu.addItem("(empty slot)")
            self.param_menu.blockSignals(False)
            self._render_for_param()
            return
        md = catalog.lookup(block.model_id)
        names = list(md.params) if md else []
        self.param_menu.addItem(self._param_label("Bypass", editor.bypass_target(slot)))
        for idx, pname in enumerate(names):
            ctl = editor.controller_assignment(slot, idx)
            src = ctl["source"] if ctl else None
            self.param_menu.addItem(self._param_label(pname.lstrip("@"), src), idx)
        self.param_menu.setCurrentIndex(0)
        self.param_menu.blockSignals(False)
        self._render_for_param()

    @staticmethod
    def _param_label(name: str, assign: str | None) -> str:
        return f"{name}   [{assign}]" if assign else name

    # --- internal state ---

    def _current_param(self) -> int | None:
        """Menu param index (None = 'Bypass'), or -1 if slot is empty."""
        if self.slot is None or self.editor is None:
            return -1
        if self.editor.preset.chain[self.slot] is None:
            return -1
        idx = self.param_menu.currentIndex()
        return None if idx == 0 else self.param_menu.itemData(idx)

    def _param_changed(self, _idx: int) -> None:
        self._render_for_param()

    def _category_color(self) -> str:
        cat = self.editor.slot_category(self.slot) if self.editor else None
        return palette.category_color(cat)

    def _render_for_param(self) -> None:
        """Highlights the active selector and shows/hides controls based on the param."""
        param = self._current_param()
        is_bypass = param is None
        empty = param == -1
        ed, slot = self.editor, self.slot

        # State for each selector.
        current = None
        if not empty and is_bypass:
            current = ed.bypass_target(slot)
        elif not empty:
            ctl = ed.controller_assignment(slot, param)
            current = ctl["source"] if ctl else None

        ring = self._category_color()
        for name, btn in self._buttons.items():
            assigned = name == current or (current is None and name == "None")
            btn.blockSignals(True)
            btn.setChecked(assigned)
            btn.blockSignals(False)
            btn.set_ring(ring if assigned and name != "None" else None)
            usable = not empty and self._selector_usable(name, is_bypass)
            if name not in DISABLED_SELECTORS:
                btn.setEnabled(usable)

        # Min/Max sliders only for an existing controller.
        show_mm = (not empty) and (not is_bypass) and (current is not None)
        self._minmax.setVisible(show_mm)
        if show_mm:
            ctl = ed.controller_assignment(slot, param)
            self._set_slider(self.min_slider, self.min_spin, ctl["min"])
            self._set_slider(self.max_slider, self.max_spin, ctl["max"])

        self.status.setText(self._status_text(empty, is_bypass, current))

    def _selector_usable(self, name: str, is_bypass: bool) -> bool:
        if name == "None":
            return True
        if is_bypass:
            # Bypass: FS1–8 + toe only (EXP-pedal bypass and Snapshots don't apply).
            return name in BYPASS_OK
        # Controller: Snapshots/EXP/FS; CREATION is RE-blocked unless it already
        # exists (handled on click), but kept clickable to inform the user.
        return name != "Snapshots" or True

    def _status_text(self, empty, is_bypass, current) -> str:
        if empty:
            return "Select a block to assign bypass or controllers."
        if not is_bypass and current is None:
            return (
                "Creating a controller on this parameter requires RE/harvest "
                "from the pedal (see spec 09). Min/Max and clear are available "
                "for existing controllers."
            )
        return ""

    # --- actions ---

    def _select(self, name: str) -> None:
        param = self._current_param()
        if param == -1 or self.editor is None:
            return
        try:
            if param is None:  # Bypass
                if name == "None":
                    self.editor.clear_bypass_assign(self.slot)
                elif name in BYPASS_OK:
                    self.editor.set_bypass_assign(self.slot, name)
                else:
                    return
            else:  # controller
                if name == "None":
                    self.editor.clear_controller_assign(self.slot, param)
                else:
                    self.editor.set_controller_assign(self.slot, param, name)
        except ControllerAssignUnsupported as exc:
            self.status.setText(str(exc))
            self._render_for_param()
            return
        except ValueError as exc:
            self.status.setText(str(exc))
            self._render_for_param()
            return
        self._after_change()

    def _commit_minmax(self) -> None:
        param = self._current_param()
        if param in (None, -1) or self.editor is None:
            return
        lo = self.min_spin.value()
        hi = self.max_spin.value()
        try:
            self.editor.set_controller_min_max(self.slot, param, lo, hi)
        except ValueError:
            return
        self.editor.end_gesture()
        self._after_change()

    def _fs_menu(self, target: str, global_pos) -> None:
        """Context menu for a FS button: view/rename/color for THAT switch."""
        if self.editor is None:
            return
        has = bool(self.editor.bypass_blocks_on(target))
        menu = QMenu(self)
        see = menu.addAction(f"View assignments for {target}…")
        menu.addSeparator()
        rename = menu.addAction("Rename…")
        reset = menu.addAction("Reset name")
        rename.setEnabled(has)
        reset.setEnabled(has)
        color_menu = menu.addMenu("Color")
        color_menu.setEnabled(has)
        current = self.editor.footswitch_color_index_for(target)
        color_acts: dict = {}
        for index, cname in enumerate(FS_COLOR_NAMES):
            act = color_menu.addAction(cname)
            act.setCheckable(True)
            act.setChecked(index == current)
            icon = _fs_color_icon(index)
            if icon is not None:
                act.setIcon(icon)
            color_acts[act] = index
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is see:
            AssignmentsListDialog(self, target).exec()
        elif chosen is rename:
            current_label = self.editor.footswitch_label_for(target) or ""
            text, ok = QInputDialog.getText(
                self, "Rename footswitch", f"Label for {target}:",
                text=current_label,
            )
            if ok:
                self.editor.set_fs_label_for(target, text)
                self._after_change()
        elif chosen is reset:
            self.editor.reset_fs_label_for(target)
            self._after_change()
        elif chosen in color_acts:
            self.editor.set_fs_color_index_for(target, color_acts[chosen])
            self._after_change()

    def _after_change(self) -> None:
        self.changed.emit()
        if self.editor is not None and self.slot is not None:
            self.show_block(self.editor, self.slot)

    @staticmethod
    def _set_slider(slider: QSlider, spin: ValueSpinBox, value: float) -> None:
        slider.blockSignals(True)
        slider.setValue(int(round(float(value) * 1000)))
        slider.blockSignals(False)
        spin.blockSignals(True)
        spin.setValue(float(value))
        spin.blockSignals(False)
