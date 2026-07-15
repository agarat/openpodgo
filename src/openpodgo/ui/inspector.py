"""POD Go Edit-style inspector: Edit panel + embedded Model Select.

Lower half of the editor. The header (tinted with the category color) shows
icon + category + model, the Edit/Models toggle and the bypass button. Below
it, a stack with:
- EditPanel: thick sliders filled with the category color, value on the right
  in a spinbox (×100 for 0..1 knobs, like the pedal display).
- ModelSelectPanel: category row + model grid with their official icons; a
  click applies the model (replaces the old modal dialog).
"""

from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import catalog
from ..editor import PresetEditor
from . import assets, palette
from .names import short_name

#: Order of the category row (like the official Model Select).
CATEGORY_ORDER = (
    "Amp", "Cab", "Dist", "Dyn", "EQ", "Mod", "Delay", "Reverb",
    "Pitch", "Filter", "Wah", "Vol", "Send/Return", "Looper",
)


@lru_cache(maxsize=1)
def available_models() -> tuple[tuple[str, str, str], ...]:
    """(name, short name, category) of the swappable models.

    Same universe as the old ModelPickerDialog: known wire_id + param order +
    on-wire category (the rest are enabled once harvested).
    """
    out = []
    for name in catalog.model_names():
        info = catalog.model_info(name)
        cat = catalog.display_category(name)
        if (
            info is None
            or info.wire_id is None
            or info.param_order is None
            or info.wire_category is None
            or cat is None
        ):
            continue
        out.append((name, info.display_name or short_name(name), cat))
    return tuple(out)


def _display_name(model_name: str | None, model_id: int | None = None) -> str:
    if model_name is None:
        return f"Model {model_id}" if model_id is not None else ""
    info = catalog.model_info(model_name)
    if info is not None and info.display_name:
        return info.display_name
    return short_name(model_name)


class ValueSpinBox(QDoubleSpinBox):
    """Numeric value to the right of the slider, with arrows and direct typing.

    For 0..1 knobs it shows ×100 (like the pedal display); for everything else
    it uses compact notation.
    """

    def __init__(self, vmin: float, vmax: float) -> None:
        super().__init__()
        self._knob = (vmin, vmax) == (0.0, 1.0)
        self.setRange(vmin, vmax)
        self.setDecimals(4)
        self.setSingleStep(0.01 if self._knob else (vmax - vmin) / 100 or 1.0)
        self.setKeyboardTracking(False)
        self.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setFixedWidth(86)

    def textFromValue(self, value: float) -> str:
        if self._knob:
            return f"{value * 100:.1f}"
        return f"{value:.4g}"

    def valueFromText(self, text: str) -> float:
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            return self.value()
        return value / 100 if self._knob else value


class ParamRow:
    """A row of the Edit panel.

    Variants depend on the parameter type (catalog.ParamSpec + control_spec):
    - ``enum``: combo with the control's labels. Covers labeled discretes
      (Low/Band/High Pass, sync notes…) and 2-value params (bool included: it
      uses the catalog labels or synthesizes Off/On). The on-wire value is
      ``vmin + index`` (or ``bool(index)`` for bools).
    - ``int``: integer-step slider + integer spinbox (unlabeled discrete, e.g.
      large ranges).
    - ``cont``: 1000-step slider + spinbox (continuous, as always).
    - ``bool``: checkbox, only as a defensive fallback when there is no way to
      derive labels (unreachable with the current data).
    """

    SLIDER_STEPS = 1000

    def __init__(self, label: str, value, spec, on_change) -> None:
        self.label = label
        self._on_change = on_change
        self.spin = None
        self.combo = None
        cs = catalog.control_spec(spec.display_type) if spec is not None else None
        is_bool = isinstance(value, bool) or (
            spec is not None and spec.is_bool
        )

        if (
            spec is not None
            and spec.vmin is not None
            and spec.vmax is not None
            and spec.vmax > spec.vmin
        ):
            self._vmin, self._vmax = float(spec.vmin), float(spec.vmax)
        else:
            self._vmin, self._vmax = 0.0, 1.0

        is_discrete = spec is not None and (
            spec.value_type == 0 or (cs is not None and cs.is_discrete)
        )
        n_steps = int(round(self._vmax - self._vmin))
        labels = cs.labels if cs is not None else None

        # Combo for 2-value (bool) params or labeled discretes. A bool uses the
        # catalog labels if it has them (Linear/Logarithmic, …); otherwise it
        # synthesizes Off/On. The other labeled discretes (Low/Band/High Pass,
        # sync notes…) already came through as a combo.
        if is_bool:
            combo_labels = (
                list(labels) if labels and len(labels) == 2 else ["Off", "On"]
            )
            emit_bool = True
        elif is_discrete and labels and len(labels) == n_steps + 1:
            combo_labels = list(labels)
            emit_bool = False
        else:
            combo_labels = None
            emit_bool = False

        if combo_labels is not None and len(combo_labels) >= 2:
            self._kind = "enum"
            self.widget = QComboBox()
            self.combo = self.widget
            self.widget.addItems(combo_labels)
            self._set_combo_silent(value)
            if emit_bool:
                # bool → preserve the on-wire type editor.set_param expects.
                self.widget.currentIndexChanged.connect(
                    lambda i: on_change(bool(i))
                )
            else:
                self.widget.currentIndexChanged.connect(
                    lambda i: on_change(int(i + self._vmin))
                )
            return

        # Fallback: bool with no derivable label (unreachable with the current
        # data, kept per the agreed rule of spec 07).
        if is_bool:
            self._kind = "bool"
            self.widget = QCheckBox()
            self.widget.setChecked(bool(value))
            self.widget.toggled.connect(lambda v: on_change(bool(v)))
            return

        # int (unlabeled usable discrete) or continuous.
        self._kind = "int" if is_discrete and n_steps >= 1 else "cont"
        self._steps = n_steps if self._kind == "int" else self.SLIDER_STEPS
        self.widget = QSlider(Qt.Horizontal)
        self.widget.setRange(0, self._steps)
        self.widget.setFixedHeight(22)
        self.spin = ValueSpinBox(self._vmin, self._vmax)
        if self._kind == "int":
            self.spin.setDecimals(0)
            self.spin.setSingleStep(1)
        self._set_silent(float(value))
        self.widget.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)

    # --- slider ↔ spin sync ---

    def _to_value(self, pos: int) -> float:
        value = self._vmin + (self._vmax - self._vmin) * pos / self._steps
        return round(value) if self._kind == "int" else value

    def _to_pos(self, value: float) -> int:
        span = self._vmax - self._vmin
        pos = round((float(value) - self._vmin) / span * self._steps)
        return max(0, min(self._steps, pos))

    def _slider_changed(self, pos: int) -> None:
        value = self._to_value(pos)
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        self._on_change(value)

    def _spin_changed(self, value: float) -> None:
        self.widget.blockSignals(True)
        self.widget.setValue(self._to_pos(value))
        self.widget.blockSignals(False)
        self._on_change(value)

    def _set_silent(self, value: float) -> None:
        self.widget.blockSignals(True)
        self.widget.setValue(self._to_pos(value))
        self.widget.blockSignals(False)
        if self.spin is not None:
            self.spin.blockSignals(True)
            self.spin.setValue(float(value))
            self.spin.blockSignals(False)

    def _set_combo_silent(self, value) -> None:
        idx = int(round(float(value))) - int(self._vmin)
        idx = max(0, min(self.combo.count() - 1, idx))
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)

    # --- public API ---

    def set_value(self, value) -> None:
        """Change the value from code (fires on_change, like a click)."""
        if self._kind == "bool":
            self.widget.setChecked(bool(value))
        elif self._kind == "enum":
            self.combo.setCurrentIndex(
                int(round(float(value))) - int(self._vmin)
            )
        else:
            self.widget.setValue(self._to_pos(float(value)))

    def set_value_silent(self, value) -> None:
        """Refresh the value without firing on_change (undo/redo, snapshots)."""
        if self._kind == "bool":
            self.widget.blockSignals(True)
            self.widget.setChecked(bool(value))
            self.widget.blockSignals(False)
        elif self._kind == "enum":
            self._set_combo_silent(value)
        else:
            self._set_silent(float(value))


class EditPanel(QWidget):
    """Parameter grid of the block, in its category color."""

    def __init__(self) -> None:
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 8, 12, 8)
        self._lay.setSpacing(6)
        self._lay.addStretch(1)
        self.rows: list[ParamRow] = []

    def rebuild(self, editor: PresetEditor, slot: int, block, on_modified,
                color: str, device=None) -> None:
        self.clear()
        md = catalog.lookup(block.model_id)
        info = catalog.model_info(md.name) if md else None
        for idx, value in enumerate(block.params):
            if md and idx < len(md.params):
                pname = md.params[idx]
                spec = info.params.get(pname) if info else None
            else:
                pname, spec = f"P{idx + 1}", None

            def changed(v, i=idx):
                editor.set_param(slot, i, v)
                on_modified()

            def write_param(i=idx):
                if device is None:
                    return
                try:
                    blk_idx = editor.block_index(slot)
                    val = float(editor.preset.chain[slot].params[i])
                    log.info("write_param slot=%d idx=%d val=%.4f", slot, i, val)
                    device.set_param(block_index=blk_idx, param_idx=i, value=val)
                except (ValueError, RuntimeError) as exc:
                    log.warning("write_param error: %s", exc)

            row = ParamRow(pname.lstrip("@"), value, spec, changed)
            if row.spin is not None:
                row.widget.sliderReleased.connect(write_param)
                row.widget.sliderReleased.connect(editor.end_gesture)
                row.spin.editingFinished.connect(write_param)
            elif row.combo is not None:
                # Each enum selection is a discrete commit: write right away.
                row.combo.currentIndexChanged.connect(write_param)
                row.combo.currentIndexChanged.connect(
                    lambda _i: editor.end_gesture()
                )
            self.rows.append(row)
            self._lay.insertWidget(self._lay.count() - 1, self._row_widget(row))
        self._apply_color(color)

    def rebuild_io(self, editor: PresetEditor, io: str, on_modified,
                   color: str, device=None) -> None:
        """Parameter rows of the Input/Output block (#2)."""
        self.clear()
        values = editor.io_values(io)
        for idx, (_sym, label, spec) in enumerate(catalog.io_param_meta(io)):
            value = values[idx] if idx < len(values) else 0.0

            def changed(v, i=idx):
                editor.set_io_param(io, i, v)
                on_modified()

            def write_param(i=idx):
                if device is None:
                    return
                try:
                    blk_idx = editor.io_block_index(io)
                    val = float(editor.io_values(io)[i])
                    log.info("write io=%s idx=%d val=%.4f", io, i, val)
                    device.set_param(block_index=blk_idx, param_idx=i, value=val)
                except (ValueError, RuntimeError) as exc:
                    log.warning("write io error: %s", exc)

            row = ParamRow(label, value, spec, changed)
            if row.spin is not None:
                row.widget.sliderReleased.connect(write_param)
                row.widget.sliderReleased.connect(editor.end_gesture)
                row.spin.editingFinished.connect(write_param)
            elif row.combo is not None:
                row.combo.currentIndexChanged.connect(write_param)
                row.combo.currentIndexChanged.connect(
                    lambda _i: editor.end_gesture()
                )
            self.rows.append(row)
            self._lay.insertWidget(self._lay.count() - 1, self._row_widget(row))
        self._apply_color(color)

    def _row_widget(self, row: ParamRow) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(1)
        label = QLabel(row.label)
        label.setStyleSheet("font-size: 12px; color: #cfd3d9;")
        grid.addWidget(label, 0, 0)
        if row.spin is None:
            grid.addWidget(row.widget, 0, 1, alignment=Qt.AlignRight)
        else:
            grid.addWidget(row.spin, 0, 1, 2, 1, alignment=Qt.AlignBottom)
            grid.addWidget(row.widget, 1, 0)
        grid.setColumnStretch(0, 1)
        return w

    def update_values(self, block) -> None:
        """Refresh the values without rebuilding rows (avoids flicker)."""
        for row, value in zip(self.rows, block.params):
            row.set_value_silent(value)

    def _apply_color(self, color: str) -> None:
        self.setStyleSheet(
            "QSlider::groove:horizontal {"
            " height: 18px; background: #232529; border-radius: 3px; }"
            f"QSlider::sub-page:horizontal {{ background: {color};"
            " border-radius: 3px; }"
            "QSlider::handle:horizontal {"
            " width: 8px; margin: -2px 0; background: #e6e6e6;"
            " border-radius: 3px; }"
        )

    def clear(self) -> None:
        self.rows = []
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # setParent(None) removes the widget from screen now (deleteLater
                # only runs in the event loop and would leave ghost rows).
                w.setParent(None)
                w.deleteLater()


class ModelSelectPanel(QWidget):
    """Category row + model grid with official icons."""

    model_chosen = Signal(str)
    clear_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._models = available_models()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(2)
        self._cat_group = QButtonGroup(self)
        self._cat_group.setExclusive(True)
        self.none_btn = self._category_button("None", None)
        self.none_btn.setCheckable(False)
        self.none_btn.clicked.connect(self.clear_requested)
        top.addWidget(self.none_btn)
        self._cat_buttons: dict[str, QToolButton] = {}
        for cat in CATEGORY_ORDER:
            btn = self._category_button(cat, cat)
            btn.setCheckable(True)
            self._cat_group.addButton(btn)
            self._cat_buttons[cat] = btn
            btn.toggled.connect(
                lambda on, c=cat: on and self._set_category(c)
            )
            top.addWidget(btn)
        top.addStretch(1)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.setFixedWidth(150)
        self._search.textChanged.connect(lambda _t: self._refresh())
        top.addWidget(self._search)
        lay.addLayout(top)

        # Sub-tab row (Amp/Preamp, Cab/Legacy Cab/IR). Hidden unless the current
        # category has 2+ subcategories.
        self._subcat_bar = QWidget()
        self._subcat_lay = QHBoxLayout(self._subcat_bar)
        self._subcat_lay.setContentsMargins(0, 0, 0, 0)
        self._subcat_lay.setSpacing(2)
        self._subcat_group = QButtonGroup(self)
        self._subcat_group.setExclusive(True)
        self._subcat_buttons: list[QToolButton] = []
        self._subcat_bar.hide()
        lay.addWidget(self._subcat_bar)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setIconSize(QSize(52, 52))
        self._list.setGridSize(QSize(96, 86))
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(True)
        self._list.itemClicked.connect(self._chosen)
        lay.addWidget(self._list, 1)

        self._category: str | None = None
        #: Active sub-tab within the category (None = all).
        self._subcategory: str | None = None
        #: Categories allowed for this slot (None = all), see #5.
        self._allowed: set[str] | None = None
        #: EQ kind of the slot (spec08): "preset" | "effects" | None. Filters
        #: the models of the EQ category (Preset EQ STATIC vs Effects EQ).
        self._eq_kind: str | None = None
        self._refresh()

    def set_allowed_categories(
        self,
        allowed: set[str] | None,
        can_clear: bool = True,
        eq_kind: str | None = None,
    ) -> None:
        """Restrict the visible categories to the slot's group (#5).

        Hides the disallowed category buttons and the “None” button when the
        slot is a Preset block (it cannot be emptied, see the manual).
        `eq_kind` (spec08) filters the models of the EQ category to the slot's
        block type: "preset" shows the 7 STATIC, "effects" the 8 non-STATIC
        (with Acoustic Sim).
        """
        self._allowed = set(allowed) if allowed is not None else None
        self._eq_kind = eq_kind
        for cat, btn in self._cat_buttons.items():
            btn.setVisible(self._allowed is None or cat in self._allowed)
        # spec08: the EQ button shows the icon of the slot's type (sliders for
        # the Preset EQ, knobs for the Effects EQ).
        eq_btn = self._cat_buttons.get("EQ")
        if eq_btn is not None:
            pm = assets.category_icon("EQ", eq_kind)
            if pm is not None:
                eq_btn.setIcon(QIcon(pm))
        self.none_btn.setVisible(can_clear)
        # If the active category/sub fell outside the allowed group (the slot
        # type changed), we reset it so as not to show an empty grid.
        if self._allowed is not None and self._category not in self._allowed:
            self._category = None
            self._subcategory = None
            self._rebuild_subcats(None)
        self._refresh()

    def _category_button(self, label: str, cat: str | None) -> QToolButton:
        btn = QToolButton()
        pm = assets.category_icon(cat)
        if pm is not None:
            btn.setIcon(QIcon(pm))
            btn.setIconSize(QSize(26, 26))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setText(label)
        color = palette.category_color(cat) if cat else "#9aa0a8"
        btn.setStyleSheet(
            f"QToolButton {{ color: {color}; font-size: 10px; border: none;"
            " padding: 2px; }"
            "QToolButton:checked { background: #2e3238; border-radius: 6px; }"
        )
        return btn

    # --- state ---

    def select_category(self, category: str | None) -> None:
        if category is None:
            self._set_category(None)
            return
        btn = self._cat_buttons.get(category)
        if btn is not None:
            btn.setChecked(True)  # fires _set_category via toggled

    def _set_category(self, category: str | None) -> None:
        self._category = category
        self._subcategory = None
        self._rebuild_subcats(category)
        self._refresh()

    def _rebuild_subcats(self, category: str | None) -> None:
        """Rebuild the sub-tab row for `category` (Amp/Preamp, etc.).

        Hides the row unless there are 2+ subcategories. The first ("All") does
        not filter; each other restricts the grid to its subcategory.
        """
        for btn in self._subcat_buttons:
            self._subcat_group.removeButton(btn)
        self._subcat_buttons = []
        while self._subcat_lay.count():
            item = self._subcat_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        subs = catalog.subcategories(category)
        if len(subs) < 2:
            self._subcat_bar.hide()
            return
        for i, label in enumerate(["All", *subs]):
            sub = None if i == 0 else label
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(i == 0)
            btn.setStyleSheet(
                "QToolButton { color: #cfd3d9; font-size: 11px; border: none;"
                " padding: 2px 8px; }"
                "QToolButton:checked { background: #2e3238; border-radius: 6px;"
                " color: #ffffff; }"
            )
            btn.clicked.connect(lambda _c=False, s=sub: self._set_subcategory(s))
            self._subcat_group.addButton(btn)
            self._subcat_buttons.append(btn)
            self._subcat_lay.addWidget(btn)
        self._subcat_lay.addStretch(1)
        self._subcat_bar.show()

    def _set_subcategory(self, subcategory: str | None) -> None:
        self._subcategory = subcategory
        self._refresh()

    def set_filter(self, text: str) -> None:
        self._search.setText(text)

    def set_current_model(self, model_name: str | None) -> None:
        """Mark the slot's model (and its category) in the grid."""
        if model_name is None:
            return
        cat = catalog.display_category(model_name)
        if cat:
            self.select_category(cat)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == model_name:
                self._list.setCurrentItem(item)
                break

    def _refresh(self) -> None:
        text = self._search.text().lower()
        self._list.clear()
        for name, short, category in self._models:
            if self._allowed is not None and category not in self._allowed:
                continue
            # spec08: within EQ, show only the slot's type (Preset vs Effects);
            # the rest of the categories are not filtered by eq_kind.
            if (
                category == "EQ"
                and self._eq_kind is not None
                and catalog.eq_kind(name) != self._eq_kind
            ):
                continue
            if self._category is not None and category != self._category:
                continue
            if self._subcategory is not None:
                info = catalog.model_info(name)
                if info is None or info.subcategory != self._subcategory:
                    continue
            if text and text not in name.lower() and text not in short.lower():
                continue
            item = QListWidgetItem(short)
            pm = assets.model_icon(name)
            if pm is not None:
                item.setIcon(QIcon(pm))
            item.setData(Qt.UserRole, name)
            item.setToolTip(f"{short}  ·  {category}")
            self._list.addItem(item)

    def _chosen(self, item: QListWidgetItem) -> None:
        self.model_chosen.emit(item.data(Qt.UserRole))

    # --- API for tests/automation ---

    def visible_models(self) -> list[str]:
        return [
            self._list.item(i).data(Qt.UserRole)
            for i in range(self._list.count())
        ]

    def choose_first(self) -> None:
        if self._list.count():
            self._chosen(self._list.item(0))


class InspectorHeader(QWidget):
    """Top bar of the inspector, tinted with the category color."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(38)
        self._bg = QColor(palette.BACKGROUND)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_icons = (
            assets.ui_image("btn-models"),   # go to models
            assets.ui_image("btn-params"),   # back to params
        )
        self.toggle_btn.setText("Models")
        if self._toggle_icons[0] is not None:
            self.toggle_btn.setIcon(QIcon(self._toggle_icons[0]))
        lay.addWidget(self.toggle_btn)

        self.icon_label = QLabel()
        self.icon_label.setFixedHeight(30)
        lay.addWidget(self.icon_label)
        self.category_label = QLabel("")
        self.category_label.setStyleSheet("font-weight: 700;")
        lay.addWidget(self.category_label)
        self.model_label = QLabel("")
        self.model_label.setStyleSheet("color: #ffffff; font-weight: 600;")
        lay.addWidget(self.model_label)
        lay.addStretch(1)

        # Bypass/Control panel toggle (spec 09): footswitch/pedal icon.
        self.bypass_btn = QToolButton()
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setCursor(Qt.PointingHandCursor)
        self.bypass_btn.setToolTip("Bypass / Control (Ctrl+B)")
        _bc = assets.ui_image("btn-ctrl-assign")
        if _bc is not None:
            self.bypass_btn.setIcon(QIcon(_bc))
            self.bypass_btn.setIconSize(QSize(22, 22))
        else:
            self.bypass_btn.setText("FS")
        lay.addWidget(self.bypass_btn)

        self.power_btn = QToolButton()
        self.power_btn.setCursor(Qt.PointingHandCursor)
        self.power_btn.setToolTip("Block bypass")
        # 2-state sprite: frame 0 = active, frame 1 = bypassed.
        self._power_icons = (
            assets.ui_image("btn-inspector-bypass", frame=0),
            assets.ui_image("btn-inspector-bypass", frame=1),
        )
        if self._power_icons[0] is not None:
            self.power_btn.setIcon(QIcon(self._power_icons[0]))
            self.power_btn.setIconSize(QSize(22, 22))
        else:
            self.power_btn.setText("⏻")
        lay.addWidget(self.power_btn)

    def set_io(self, title: str) -> None:
        """Input/Output block header: no models toggle, no bypass."""
        color = palette.category_color(None)
        self._bg = palette.tinted_bg(color)
        self.category_label.setText(title)
        self.category_label.setStyleSheet("font-weight: 700; color: #cfd3d9;")
        self.model_label.setText("")
        self.model_label.setStyleSheet("color: #ffffff; font-weight: 600;")
        self.icon_label.clear()
        self.power_btn.setVisible(False)
        self.toggle_btn.setVisible(False)
        self.bypass_btn.setVisible(False)
        self.update()

    def set_block(self, category: str | None, model_name: str | None,
                  display: str, enabled: bool) -> None:
        self.toggle_btn.setVisible(True)
        self.bypass_btn.setVisible(model_name is not None)
        color = palette.category_color(category)
        self._bg = palette.tinted_bg(color)
        self.category_label.setText(category or "")
        self.category_label.setStyleSheet(
            f"font-weight: 700; color: {color};"
        )
        self.model_label.setText(display)
        pm = assets.model_icon(model_name) if model_name else None
        if pm is not None:
            self.icon_label.setPixmap(
                pm.scaledToHeight(28, Qt.SmoothTransformation)
            )
        else:
            self.icon_label.clear()
        self.power_btn.setVisible(model_name is not None)
        power_pm = self._power_icons[0 if enabled else 1]
        if power_pm is not None:
            self.power_btn.setIcon(QIcon(power_pm))
        if not enabled:
            # Bypassed block: dimmed header, as in the official app.
            self.category_label.setStyleSheet(
                f"font-weight: 700; color: {palette.dimmed(color).name()};"
            )
            self.model_label.setStyleSheet("color: #8a8f98; font-weight: 600;")
        else:
            self.model_label.setStyleSheet("color: #ffffff; font-weight: 600;")
        self.update()

    def set_mode(self, mode: str) -> None:
        idx = 0 if mode == "edit" else 1
        self.toggle_btn.setText("Models" if mode == "edit" else "Params")
        pm = self._toggle_icons[idx]
        if pm is not None:
            self.toggle_btn.setIcon(QIcon(pm))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)


class InspectorPanel(QWidget):
    """Header + Edit/Model Select stack of the selected block."""

    bypass_toggled = Signal(int)
    model_chosen = Signal(int, str)
    clear_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._slot: int | None = None
        self._model_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.header = InspectorHeader()
        self.header.power_btn.clicked.connect(self._power_clicked)
        self.header.toggle_btn.toggled.connect(self._toggled)
        lay.addWidget(self.header)

        self._stack = QStackedWidget()
        self.edit = EditPanel()
        scroll = QScrollArea()
        scroll.setWidget(self.edit)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._stack.addWidget(scroll)
        self.models = ModelSelectPanel()
        self.models.model_chosen.connect(self._model_chosen)
        self.models.clear_requested.connect(self._clear_requested)
        self._stack.addWidget(self.models)
        lay.addWidget(self._stack, 1)

    # --- public API ---

    @property
    def rows(self) -> list[ParamRow]:
        return self.edit.rows

    def mode(self) -> str:
        return "edit" if self._stack.currentIndex() == 0 else "models"

    def set_mode(self, mode: str) -> None:
        self._stack.setCurrentIndex(0 if mode == "edit" else 1)
        self.header.set_mode(mode)
        self.header.toggle_btn.blockSignals(True)
        self.header.toggle_btn.setChecked(mode == "models")
        self.header.toggle_btn.blockSignals(False)

    def show_block(self, editor: PresetEditor, slot: int, on_modified,
                   device=None) -> None:
        """Show the slot's block (rebuild only if slot/model changed)."""
        block = editor.preset.chain[slot]
        if block is None:
            self._slot, self._model_id = slot, None
            self.header.set_block(None, None, "Empty slot", True)
            self.edit.clear()
            self._apply_swap_filter(None)
            self.set_mode("models")
            return
        md = catalog.lookup(block.model_id)
        model_name = md.name if md else None
        category = (
            catalog.display_category(model_name) if model_name else "Otros"
        )
        display = _display_name(model_name, block.model_id)
        self.header.set_block(category, model_name, display, block.enabled)
        same = (slot, block.model_id) == (self._slot, self._model_id)
        if same and self.edit.rows:
            self.edit.update_values(block)
        else:
            self.edit.rebuild(
                editor, slot, block, on_modified,
                palette.category_color(category), device,
            )
            self._apply_swap_filter(category, model_name)
            self.models.set_current_model(model_name)
            self.set_mode("edit")
        self._slot, self._model_id = slot, block.model_id

    def show_io(self, editor: PresetEditor, io: str, on_modified,
                device=None) -> None:
        """Show the params of the Input/Output block (#2)."""
        self._slot, self._model_id = io, None
        self.header.set_io("Input" if io == "input" else "Output")
        self.edit.rebuild_io(
            editor, io, on_modified, palette.category_color(None), device,
        )
        self.set_mode("edit")

    def _apply_swap_filter(
        self, category: str | None, model_name: str | None = None
    ) -> None:
        """Restrict the Model Select to the slot's swap group (#5, spec08)."""
        allowed = catalog.swap_group(category, model_name)
        # spec08: the slot's EQ kind. Only the dedicated Preset EQ (STATIC
        # model) is "preset"; any other slot (Effects block or empty) is
        # "effects". Filters the grid of the EQ category.
        eq_kind = (
            "preset"
            if model_name and catalog.eq_kind(model_name) == "preset"
            else "effects"
        )
        # Effects block (a group of several categories or empty slot): can be
        # emptied. Preset block (a single locked category): cannot.
        self.models.set_allowed_categories(
            allowed, can_clear=len(allowed) > 1, eq_kind=eq_kind
        )

    # --- internal wiring ---

    def _power_clicked(self) -> None:
        if self._slot is not None:
            self.bypass_toggled.emit(self._slot)

    def _toggled(self, checked: bool) -> None:
        self.set_mode("models" if checked else "edit")

    def _model_chosen(self, name: str) -> None:
        if self._slot is not None:
            self.model_chosen.emit(self._slot, name)

    def _clear_requested(self) -> None:
        if self._slot is not None:
            self.clear_requested.emit(self._slot)
