"""Visual editing view of the active preset (POD Go Edit clone, UI phase).

Signal Flow (input → 10 slots → output) + Inspector (Edit panel / embedded
Model Select). All edits are in memory (PresetEditor over the raw body); the
useful output is the .pgp export. Writing to the pedal will come with spec 03
and connects on top of this same view.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..editor import BYPASS_TARGETS, PresetEditor
from ..l6helix import Preset
from .bypass_control import BypassControlPanel
from .inspector import InspectorPanel
from .names import short_name  # noqa: F401  (re-export: lo importan los tests)
from .signal_flow import SignalFlowPanel
from .toolbar import EditorToolbar


class EditorView(QWidget):
    """Active preset editor: toolbar + chain + inspector + .pgp export."""

    reread_requested = Signal()
    save_requested = Signal()
    snapshot_selected = Signal(int)
    prev_requested = Signal()
    next_requested = Signal()
    #: slot, enabled — emitted when local bypass is toggled and MIDI is sent
    bypass_midi_sent = Signal(int, bool)
    #: emitted after reordering the chain in memory; MainWindow dumps the
    #: complete blob to the pedal (op 21) in the background.
    chain_write_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.editor: PresetEditor | None = None
        self.device = None
        self.preset_name = ""
        self.slot_text = ""
        self.modified = False
        #: slot (int), "input"/"output" (IO, #2) or None.
        self._selected: int | str | None = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        self.toolbar = EditorToolbar()
        self.toolbar.prev_preset.connect(self.prev_requested)
        self.toolbar.next_preset.connect(self.next_requested)
        self.toolbar.snapshot_selected.connect(self._snapshot_clicked)
        self.toolbar.undo_requested.connect(self.undo)
        self.toolbar.redo_requested.connect(self.redo)
        self.toolbar.reread_requested.connect(self.reread_requested)
        self.toolbar.export_requested.connect(self._export_dialog)
        self.toolbar.save_requested.connect(self.save_requested)
        root.addWidget(self.toolbar)
        QShortcut(QKeySequence.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.Redo, self, activated=self.redo)

        self.chain = SignalFlowPanel()
        self.chain.block_selected.connect(self.select_slot)
        self.chain.io_selected.connect(self.select_io)
        self.chain.bypass_toggled.connect(self.toggle_bypass)
        self.chain.menu_requested.connect(self._block_menu)
        self.chain.clear_requested.connect(self.clear_slot)
        self.chain.block_moved.connect(self.move_block)
        root.addWidget(self.chain)

        # Bypass/Control panel (spec 09): hidden sub-panel below the chain.
        self.bypass_panel = BypassControlPanel()
        self.bypass_panel.changed.connect(self._on_assignment_changed)
        self.bypass_panel.close_requested.connect(
            lambda: self._toggle_bypass_panel(False)
        )
        self.bypass_panel.hide()
        root.addWidget(self.bypass_panel)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._toggle_bypass_shortcut)

        self.inspector = InspectorPanel()
        self.inspector.bypass_toggled.connect(self.toggle_bypass)
        self.inspector.model_chosen.connect(self.apply_model)
        self.inspector.clear_requested.connect(self.clear_slot)
        self.inspector.header.bypass_btn.toggled.connect(self._toggle_bypass_panel)
        root.addWidget(self.inspector, 1)

        hint = QLabel(
            "Double-click a block → toggles local bypass + MIDI. "
            "'Export .pgp…' to import in POD Go Edit."
        )
        hint.setObjectName("hint")
        root.addWidget(hint)

    # --- state ---

    def set_preset(
        self,
        editor: PresetEditor,
        name: str,
        slot_text: str = "",
        keep_state: bool = False,
        modified: bool = False,
    ) -> None:
        """Loads the active preset into the view.

        `keep_state=True` (re-read after a reorder done ON the pedal):
        preserves the selected slot (clamped to the new chain's range) and the
        `modified` flag — a reorder IS an unsaved edit (#2), and the selection
        must not jump to the first block (#4). In this path the `modified`
        parameter is ignored (the reorder is its own edit).

        With `keep_state=False` (real preset change) the first block is
        selected and `self.modified` takes the value of `modified`: the pedal
        may report the active preset as edited on connect (spec 06), in which
        case it starts with ● instead of ○.
        """
        prev_selected = self._selected
        prev_modified = self.modified
        self.editor = editor
        self.preset_name = name
        self.slot_text = slot_text
        pre = editor.preset
        self.toolbar.set_tempo(pre.tempo)
        self.toolbar.set_snapshots(
            [s.name for s in pre.snapshots], pre.current_snapshot
        )
        if keep_state:
            self.modified = prev_modified
            self._selected = self._clamp_selection(prev_selected, pre)
        else:
            self.modified = modified
            self._selected = next(
                (i for i, b in enumerate(pre.chain) if b is not None), None
            )
        self._refresh()

    @staticmethod
    def _clamp_selection(
        selected: int | str | None, preset: Preset
    ) -> int | str | None:
        """Keeps the selection within the valid range of the new chain."""
        if isinstance(selected, str) or selected is None:
            return selected
        if not preset.chain:
            return None
        return max(0, min(selected, len(preset.chain) - 1))

    def _refresh(self) -> None:
        self.toolbar.set_title(self.slot_text, self.preset_name, self.modified)
        self.toolbar.set_undo_redo(
            self.editor.can_undo(), self.editor.can_redo()
        )
        self.chain.update_from(
            self.editor.preset, self._selected, self.editor.bypass_assignments()
        )
        if isinstance(self._selected, str):
            self.inspector.show_io(
                self.editor, self._selected, self._mark_modified, self.device
            )
        elif self._selected is not None:
            self.inspector.show_block(
                self.editor, self._selected, self._mark_modified, self.device
            )
        if self.bypass_panel.isVisible():
            self.bypass_panel.show_block(self.editor, self._selected_slot())

    def _selected_slot(self) -> int | None:
        """Selected int slot (None if Input/Output or nothing)."""
        return self._selected if isinstance(self._selected, int) else None

    def _toggle_bypass_shortcut(self) -> None:
        """Ctrl+B: toggles the panel (and keeps the header button in sync)."""
        self._toggle_bypass_panel(self.bypass_panel.isHidden())

    def _toggle_bypass_panel(self, show: bool) -> None:
        self.bypass_panel.setVisible(show)
        btn = self.inspector.header.bypass_btn
        if btn.isChecked() != show:
            btn.blockSignals(True)
            btn.setChecked(show)
            btn.blockSignals(False)
        if show and self.editor is not None:
            self.bypass_panel.show_block(self.editor, self._selected_slot())

    def _on_assignment_changed(self) -> None:
        """An assignment changed in the panel: mark modified, refresh, and sync.

        Assignments live in body[3]/body[4]; there is no punctual vendor op, so
        they are synced via the complete blob dump (op 21), like block reorder.
        """
        self._mark_modified()
        self._refresh()
        self.chain_write_requested.emit()

    def refresh(self) -> None:
        """Re-renders the view from the in-memory editor (external use).

        Used by MainWindow after applying a change received from the pedal
        (live sync): redraws Signal Flow + Inspector respecting the selected
        slot, without flicker if the slot/model did not change.
        """
        if self.editor is not None:
            self._refresh()

    def _mark_modified(self) -> None:
        self.modified = True
        self.toolbar.set_title(self.slot_text, self.preset_name, True)
        self.toolbar.set_undo_redo(
            self.editor.can_undo(), self.editor.can_redo()
        )

    def mark_saved(self) -> None:
        """Marks the preset as saved: clears the modification indicator (●)."""
        self.modified = False
        self.toolbar.set_title(self.slot_text, self.preset_name, False)

    # --- undo/redo ---

    def undo(self) -> None:
        if self.editor is not None and self.editor.undo():
            self.modified = True
            self._refresh()

    def redo(self) -> None:
        if self.editor is not None and self.editor.redo():
            self.modified = True
            self._refresh()

    # --- actions (same API triggered by UI signals) ---

    def select_slot(self, slot: int) -> None:
        self._selected = slot
        self._refresh()

    def select_io(self, io: str) -> None:
        """Selects the Input/Output block to edit its params (#2)."""
        self._selected = io
        self._refresh()

    def toggle_bypass(self, slot: int) -> None:
        block = self.editor.preset.chain[slot]
        if block is None:
            return
        new_state = not block.enabled
        self.editor.set_bypass(slot, new_state)
        self._mark_modified()
        self._refresh()
        self.bypass_midi_sent.emit(slot, new_state)

    def apply_model(self, slot: int, model_name: str) -> None:
        self.editor.swap_model(slot, model_name)
        self._selected = slot
        self._mark_modified()
        self._write_model_to_device(slot)
        self._refresh()

    def _write_model_to_device(self, slot: int) -> None:
        """Writes the model change to the pedal live (#3), if device exists.

        Same pattern as the inspector's param write (direct, with the transport
        lock). The pedal loads the model with its defaults.
        """
        if self.device is None:
            return
        try:
            blk_idx = self.editor.block_index(slot)
            wire_id = self.editor.preset.chain[slot].model_id
            self.device.set_model(block_index=blk_idx, wire_id=wire_id)
        except (ValueError, RuntimeError) as exc:
            log.warning("set_model error: %s", exc)

    def move_block(self, from_slot: int, to_slot: int) -> None:
        """Reorders the chain in memory and requests dumping the blob to the pedal."""
        if self.editor is None:
            return
        try:
            self.editor.move_block(from_slot, to_slot)
        except ValueError as exc:
            log.warning("move_block: %s", exc)
            return
        self._selected = to_slot  # keep the moved block selected
        self._mark_modified()
        self._refresh()
        self.chain_write_requested.emit()

    def clear_slot(self, slot: int) -> None:
        self.editor.clear_slot(slot)
        self._mark_modified()
        self._refresh()
        # Clearing a slot is a structural edit (removes block + its
        # assignments): synced via the complete blob dump (op 21), same as
        # moving a block.
        self.chain_write_requested.emit()

    def export_pgp(self, path) -> None:
        doc = self.editor.to_pgp(name=self.preset_name)
        Path(path).write_text(
            json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )

    # --- handlers with dialog/menu ---

    def _snapshot_clicked(self, n: int) -> None:
        for i, act in enumerate(self.toolbar.snapshot_actions):
            act.setChecked(i == n)
        self.snapshot_selected.emit(n)

    def _block_menu(self, slot: int) -> None:
        menu = QMenu(self)
        change = menu.addAction("Change model…")
        empty = self.editor.preset.chain[slot] is None
        bypass = clear = None
        assign_acts: dict = {}
        if not empty:
            bypass = menu.addAction("Bypass (double click)")
            # "Bypass Assign" submenu (manual p. 28): FS1–8, toe switch, remove.
            current = self.editor.bypass_target(slot)
            sub = menu.addMenu("Bypass Assign")
            for target in BYPASS_TARGETS:
                act = sub.addAction(target)
                act.setCheckable(True)
                act.setChecked(target == current)
                assign_acts[act] = target
            sub.addSeparator()
            assign_acts[sub.addAction("None (remove)")] = None
            clear = menu.addAction("Clear slot")
        chosen = menu.exec(self.cursor().pos())
        if chosen is change:
            self.select_slot(slot)
            self.inspector.set_mode("models")
        elif chosen is not None and chosen is bypass:
            self.toggle_bypass(slot)
        elif chosen is not None and chosen is clear:
            self.clear_slot(slot)
        elif chosen in assign_acts:
            self.assign_bypass(slot, assign_acts[chosen])

    def assign_bypass(self, slot: int, target: str | None) -> None:
        """Assigns (or removes with target=None) the block's bypass to a switch."""
        if target is None:
            self.editor.clear_bypass_assign(slot)
        else:
            self.editor.set_bypass_assign(slot, target)
        self.select_slot(slot)
        self._mark_modified()
        self._refresh()
        self.chain_write_requested.emit()

    def _export_dialog(self) -> None:
        default = f"{self.preset_name or 'preset'}.pgp"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export preset", default, "POD Go Preset (*.pgp)"
        )
        if path:
            self.export_pgp(path)

    def _import_dialog(self) -> dict | None:
        """Opens the .pgp import dialog and returns the dict, or None if cancelled."""
        from ..preset import load_pgp

        path, _filter = QFileDialog.getOpenFileName(
            self, "Import preset", "", "POD Go Preset (*.pgp)"
        )
        if not path:
            return None
        try:
            return load_pgp(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Could not import the preset:\n{exc}")
            return None

    def load_pgp(self, pgp: dict) -> bool:
        """Loads a .pgp dict into the editor. Returns True if successful."""
        ed, warnings = PresetEditor.from_pgp(pgp)
        name = pgp.get("data", {}).get("meta", {}).get("name", "Imported")
        if warnings:
            QMessageBox.information(
                self, "Unknown models",
                "The following models were not found in the catalog and "
                "were loaded as empty slots:\n\n" + "\n".join(warnings),
            )
        self.set_preset(ed, name)
        return True
