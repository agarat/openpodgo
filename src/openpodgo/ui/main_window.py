"""openpodgo main window, modeled on POD Go Edit: a single window with the
Librarian (setlists + presets) on the left and the active-preset editor
(Signal Flow + Inspector) on the right.

Every USB operation runs in a Worker (one job at a time, by design of the
vendor protocol); recalling a preset verifies against active_state() that the
pedal actually changed before re-reading the active preset.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
)

from ..device import PodGo
from ..editor import PresetEditor
from ..midi import MidiError, MidiOut
from ..notifications import NotificationReader
from .editor import EditorView
from .librarian import LibrarianPanel
from .theme import apply_dark_theme

log = logging.getLogger(__name__)

#: Wait after the MIDI recall before reading the active preset (the pedal takes
#: a moment to load it; there is slot verification + retry below).
RECALL_SETTLE_S = 0.3
RECALL_RETRIES = 4


class Worker(QThread):
    """Runs a function (that touches USB) off the UI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, autoconnect: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("openpodgo")
        self.resize(1280, 720)

        self.device = PodGo()
        self.midi: MidiOut | None = None
        self.setlists: list[str] = []
        self._info = ""
        self._workers: set[Worker] = set()  # live refs until finished
        self._notification_reader: NotificationReader | None = None
        #: After a reorder initiated by US, the pedal echoes chain_changed.
        #: We already have the correct state in memory, so we drop that echo
        #: instead of re-reading the whole preset (which costs ~5 s of handshakes).
        self._suppress_chain_echo = False
        #: The next re-read comes from a reorder ON the pedal: we must preserve
        #: selection + ● (#2/#4) instead of resetting them.
        self._chain_reread_pending = False
        #: Target slot of the reorder (key 76 of the notification), to select
        #: the moved block after the re-read. None if unknown.
        self._chain_reread_to_slot: int | None = None
        #: A reorder done ON the pedal arrives as a burst of ~8 notifications
        #: (op 49 {75,76}); this timer coalesces the burst into ONE re-read
        #: ~500 ms after the last event.
        self._chain_reread_timer = QTimer(self)
        self._chain_reread_timer.setSingleShot(True)
        self._chain_reread_timer.timeout.connect(self._open_editor)

        self._build_ui()
        self._build_menu()
        if autoconnect:
            self._start_connect()
        else:
            self.librarian.set_offline(True)

    # --- construction ---

    def _build_ui(self) -> None:
        self.librarian = LibrarianPanel()
        self.librarian.setlist_changed.connect(self._on_setlist_changed)
        self.librarian.preset_activated.connect(self._activate_preset)
        self.librarian.refresh_requested.connect(self._reload_presets)
        self.librarian.reconnect_requested.connect(lambda: self._start_connect())
        self.librarian.import_requested.connect(self._import_preset_to)

        self.editor_view = EditorView()
        self.editor_view.setEnabled(False)  # until a preset is loaded
        self.editor_view.reread_requested.connect(self._open_editor)
        self.editor_view.save_requested.connect(self._save_to_pedal)
        self.editor_view.bypass_midi_sent.connect(self._on_bypass_midi)
        self.editor_view.snapshot_selected.connect(self._on_snapshot)
        self.editor_view.chain_write_requested.connect(self._write_chain_to_pedal)
        self.editor_view.prev_requested.connect(lambda: self._step_preset(-1))
        self.editor_view.next_requested.connect(lambda: self._step_preset(+1))

        splitter = QSplitter()
        splitter.addWidget(self.librarian)
        splitter.addWidget(self.editor_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1040])
        self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Not connected")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_import = QAction("&Import preset…", self)
        act_import.triggered.connect(self._import_preset)
        file_menu.addAction(act_import)
        act_export = QAction("&Export preset…", self)
        act_export.triggered.connect(self._export_preset)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        act_quit = QAction("&Quit", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        m = self.menuBar().addMenu("&Device")
        act_reload = QAction("&Refresh presets", self)
        act_reload.triggered.connect(self._reload_presets)
        m.addAction(act_reload)

    # --- connection ---

    def _start_connect(self) -> None:
        if self._workers:
            return
        self.statusBar().showMessage("Connecting to the POD Go and reading presets…")
        try:
            self.midi = MidiOut()
        except MidiError as exc:
            self.midi = None
            log.warning("MIDI not available: %s", exc)

        # Connection + setlists + presets + active preset in ONE job, to avoid
        # overlapping two threads on the same USB device.
        def job():
            info = self.device.connect()
            self.device.write_connect()
            setlists = self.device.list_setlists() or ["Factory", "User"]
            state = self.device.active_state()
            current = (
                state.setlist
                if state.setlist < len(setlists)
                else next(
                    (i for i, n in enumerate(setlists) if n.lower() == "user"),
                    0,
                )
            )
            presets = self.device.list_presets(current)
            pre = self.device.active_preset()
            # Does the pedal report the active preset as edited? Computed in the
            # worker thread (USB does not run on the UI thread). Today it always
            # returns False: it is gated pending confirmation of the obj-14
            # checksum formula against a real pedal (spec 06), so this is a
            # latent seam that turns itself on once the gate opens.
            edited = self.device.active_preset_is_edited()
            # The event channel is opened last, right before starting the
            # reader, to minimize the un-polled window (best-effort).
            try:
                self.device.open_event_channel()
            except Exception as exc:  # noqa: BLE001 — live sync is best-effort
                log.warning("Could not open the event channel (live sync off): %s", exc)
            return info, setlists, current, presets, state, pre, edited

        self._run(job, self._on_connected)

    def _on_connected(self, result) -> None:
        info, setlists, current, presets, state, pre, edited = result
        self._info = info
        self.setlists = setlists
        self.librarian.set_offline(False)
        self.librarian.set_setlists(setlists, current)
        self.librarian.set_presets(presets)
        if state.setlist == current:
            self.librarian.set_loaded(state.slot)
        self._show_preset(state, pre, edited)
        self._status(f"{len(presets)} presets")
        self._sync_pedal_setlist(current)
        self._start_notification_reader()

    def _start_notification_reader(self) -> None:
        """Start the pedal's notification reader (live sync)."""
        if self._notification_reader is not None:
            return
        if self.device._event_session is None:
            log.info("Event channel not available: live sync disabled")
            return
        reader = NotificationReader(self.device.poll_event)
        reader.event.connect(self._on_device_event)
        self._notification_reader = reader
        reader.resume()
        reader.start()
        log.info("NotificationReader started (live sync active)")

    def _on_failed(self, msg: str) -> None:
        # No modal (the app must be usable without a pedal): offline state in the
        # Librarian + detail in the status bar.
        self.librarian.set_offline(True)
        self.statusBar().showMessage(
            f"Not connected — {msg} · Is the pedal on? Is the udev rule applied?"
        )

    # --- setlists/presets ---

    @property
    def current_setlist(self) -> int:
        for i, btn in enumerate(self.librarian.folder_buttons):
            if btn.isChecked():
                return i
        return 0

    def _on_setlist_changed(self, _idx: int) -> None:
        self._load_presets(self.current_setlist, sync_pedal=True)

    def _reload_presets(self) -> None:
        self._load_presets(self.current_setlist, sync_pedal=False)

    def _load_presets(self, setlist: int, sync_pedal: bool) -> None:
        if self._workers:
            return  # a USB operation is already in progress
        name = (
            self.setlists[setlist]
            if setlist < len(self.setlists)
            else str(setlist)
        )
        self.statusBar().showMessage(f"Reading presets from “{name}”…")
        if sync_pedal:
            self._sync_pedal_setlist(setlist)
        self._run(lambda: self.device.list_presets(setlist), self._on_presets)

    def _sync_pedal_setlist(self, setlist: int) -> None:
        if self.midi is None:
            return
        try:
            self.midi.select_setlist(setlist)
        except (MidiError, ValueError) as exc:
            log.warning("could not select setlist over MIDI: %s", exc)

    def _on_presets(self, presets) -> None:
        self.librarian.set_presets(presets)
        self._status(f"{len(presets)} presets")

    # --- loading a preset (click / ▴▾) ---

    def _activate_preset(self, position: int) -> None:
        if self._workers:
            return
        if self.midi is None:
            self.statusBar().showMessage(
                "MIDI not available: cannot change the preset"
            )
            return
        if self.editor_view.modified and not self._confirm_discard():
            return
        # A deliberate preset change is NOT a reorder re-read: if a chain_changed
        # burst left pending flags (e.g. its timer was deferred by a worker), we
        # clear them so this load does not inherit keep_state nor jump to the
        # reorder slot (#2/#4).
        self._chain_reread_pending = False
        self._chain_reread_to_slot = None
        setlist = self.current_setlist
        self.statusBar().showMessage("Loading preset on the pedal…")

        def job():
            self.midi.recall(setlist, position)
            state = None
            for _ in range(RECALL_RETRIES):
                time.sleep(RECALL_SETTLE_S)
                state = self.device.active_state()
                if state.slot == position:
                    break
            # A just-RECALLed preset is clean by definition (the pedal just
            # loaded it from storage): edited=False, without paying an extra USB
            # round-trip with active_preset_is_edited().
            return state, self.device.active_preset(), False

        self._run(job, self._on_preset_loaded)

    def _on_preset_loaded(self, result) -> None:
        state, pre, edited = result
        self.librarian.set_loaded(state.slot)
        self._show_preset(state, pre, edited)

    def _step_preset(self, delta: int) -> None:
        item_count = self.librarian.list.count()
        if not item_count:
            return
        current = self.librarian.loaded
        if current is None:
            current = 0 if delta > 0 else 1
        self._activate_preset(max(0, min(127, current + delta)))

    def _confirm_discard(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Unexported changes",
            "The edited preset has in-memory changes that will be lost when "
            "loading another preset. Continue?",
        )
        return answer == QMessageBox.Yes

    # --- active-preset editor ---

    def _open_editor(self) -> None:
        """Re-read the active preset from the pedal (objects 23 + 22)."""
        if self._workers:
            # If a reorder re-read is pending, we do not lose it: it is retried
            # when the in-flight worker is released. Without this the
            # _chain_reread_* flags would stay armed and (wrongly) be consumed
            # by the next unrelated load (#2/#4).
            if self._chain_reread_pending:
                self._chain_reread_timer.start(500)
            return
        self.statusBar().showMessage("Reading the active preset…")

        def job():
            state = self.device.active_state()
            pre = self.device.active_preset()
            # Edited? Computed in the worker (USB off the UI thread). Today it
            # returns False (gated, pending live RE, spec 06). When the gate
            # opens it will re-read objs 23/22 that the job already read: a minor
            # redundancy to optimize later, no premature optimization.
            edited = self.device.active_preset_is_edited()
            return state, pre, edited

        self._run(job, self._on_preset_loaded)

    def _show_preset(self, state, pre, edited=False) -> None:
        self.editor_view.setEnabled(True)
        self.editor_view.device = self.device
        keep = self._chain_reread_pending
        # `modified=edited` only applies with keep_state=False; the
        # reorder-on-pedal path (keep_state=True, spec 05) preserves modified only.
        self.editor_view.set_preset(
            PresetEditor(pre),
            state.name,
            self._slot_text(state.slot),
            keep_state=keep,
            modified=edited,
        )
        if keep and self._chain_reread_to_slot is not None:
            # select exactly the moved block (#4), not just preserve.
            self.editor_view.select_slot(self._chain_reread_to_slot)
        self._chain_reread_pending = False
        self._chain_reread_to_slot = None
        self._status(
            f"“{state.name}” ({self._slot_text(state.slot)}) — in-memory changes"
        )

    @staticmethod
    def _slot_text(position: int) -> str:
        return f"{position // 4 + 1:02d}{'ABCD'[position % 4]}"

    def _on_snapshot(self, n: int) -> None:
        if self.midi is None:
            self.statusBar().showMessage(
                "MIDI not available: cannot change the snapshot"
            )
            return
        try:
            self.midi.snapshot(n)
            self.statusBar().showMessage(f"Snapshot {n + 1} activated on the pedal")
        except (MidiError, ValueError) as exc:
            self.statusBar().showMessage(f"MIDI error: {exc}")

    def _on_bypass_midi(self, slot: int, enabled: bool) -> None:
        """Send the MIDI CC of the footswitch that controls the slot's bypass."""
        if self.midi is None:
            return
        ed = self.editor_view.editor
        if ed is None:
            return
        labels = ed.bypass_assignments()
        label = labels.get(slot)
        if label is None or not label.startswith("FS"):
            return
        fs_num = int(label[2:])
        try:
            self.midi.footswitch(fs_num, on=enabled)
            log.info("MIDI FS%d → %s (slot %d)", fs_num, "on" if enabled else "off", slot)
        except (MidiError, ValueError) as exc:
            log.warning("MIDI FS%d failed: %s", fs_num, exc)

    # --- import/export ---

    def _import_preset_to(self, slot: int) -> None:
        """Import .pgp to the target slot: load editor + write to pedal + activate."""
        if self._workers:
            return
        if self.editor_view.modified and not self._confirm_discard():
            return
        pgp = self.editor_view._import_dialog()
        if pgp is None:
            return
        self.editor_view.load_pgp(pgp)
        setlist = self.current_setlist
        name = self.editor_view.preset_name
        self.statusBar().showMessage(f"Importing preset to slot {self._slot_text(slot)}…")

        def job():
            device = self.device
            ed = self.editor_view.editor
            if ed is None:
                return None
            ok = device.save_preset(setlist, slot, name)
            if not ok:
                return None
            if self.midi is not None:
                self.midi.recall(setlist, slot)
                for _ in range(RECALL_RETRIES):
                    time.sleep(RECALL_SETTLE_S)
                    state = device.active_state()
                    if state.slot == slot:
                        break
            else:
                state = device.active_state()
            pre = device.active_preset()
            edited = device.active_preset_is_edited()
            return state, pre, edited

        def on_done(result):
            if result is None:
                self.statusBar().showMessage("Error importing the preset")
                return
            state, pre, edited = result
            self.librarian.set_loaded(state.slot)
            self._show_preset(state, pre, edited)
            self._status(f"Imported to {self._slot_text(slot)} ✓")

        self._run(job, on_done)

    def _import_preset(self) -> None:
        """Import .pgp from the File menu into the currently loaded slot."""
        slot = self.librarian.loaded
        if slot is None:
            self.statusBar().showMessage(
                "No preset loaded: select a slot first"
            )
            return
        self._import_preset_to(slot)

    def _export_preset(self) -> None:
        """Export .pgp from the File menu."""
        self.editor_view._export_dialog()

    # --- writing to the pedal ---

    @staticmethod
    def _flush_editor_params(device, editor) -> bool:
        """Send all of the editor's parameters to the pedal via set_param.

        Does not include bypass or model — continuous parameters only. Does not
        abort on individual failures: it logs and continues. Returns True
        (best-effort).
        """
        log.info("Sending the editor's parameters to the pedal…")
        ok_count = 0
        fail_count = 0
        for slot in range(len(editor.preset.chain)):
            block = editor.preset.chain[slot]
            if block is None:
                continue
            try:
                blk_idx = editor.block_index(slot)
            except ValueError:
                continue
            for i, val in enumerate(block.params):
                if device.set_param(block_index=blk_idx, param_idx=i, value=float(val)):
                    ok_count += 1
                else:
                    log.warning("set_param failed (continuing): slot=%d idx=%d", slot, i)
                    fail_count += 1
        if fail_count:
            log.warning("Flush complete: %d ok, %d failures", ok_count, fail_count)
        return True

    def _save_to_pedal(self) -> None:
        if self._workers:
            return
        slot = self.librarian.loaded
        if slot is None:
            self.statusBar().showMessage("No preset loaded to save")
            return
        setlist = self.current_setlist
        name = self.editor_view.preset_name
        self.statusBar().showMessage("Saving preset on the pedal…")

        def job():
            device = self.device
            ed = self.editor_view.editor
            if ed is None:
                return False
            log.info("Saving preset “%s” to setlist=%d slot=%d…", name, setlist, slot)
            return device.save_preset(setlist, slot, name)

        def on_done(ok: bool) -> None:
            if ok:
                # Saved OK: clears the unsaved-changes indicator (●), so the
                # discard dialog does not pop up when switching presets.
                self.editor_view.mark_saved()
                self._status(
                    f"“{name}” saved to slot {self._slot_text(slot)} ✓"
                )
            else:
                self.statusBar().showMessage("Error saving to the pedal")

        self._run(job, on_done)

    def _write_chain_to_pedal(self) -> None:
        """Dump the whole chain to the pedal (op 21) after moving a block.

        It is a large, chunked write: it goes through `_run` (which pauses the
        reader) instead of directly, so as not to contend with event polling.
        """
        if self._workers:
            return
        ed = self.editor_view.editor
        if ed is None or self.device is None:
            return
        blob = ed.to_blob()
        # Affected block (the selected one): goes in the op 33 of the
        # "apply/refresh" closing so the pedal refreshes the footswitch/LED
        # without toggling it (see device._apply_edit). None if there is no block.
        block_index = None
        slot = self.editor_view._selected_slot()
        if slot is not None:
            try:
                block_index = ed.block_index(slot)
            except ValueError:
                block_index = None
        self.statusBar().showMessage("Applying change on the pedal…")
        log.info("[timing] chain write: requested (%d B)", len(blob))

        def job():
            log.info("[timing] chain write: job start")
            r = self.device.write_chain_blob(blob, block_index)
            log.info("[timing] chain write: job done (%s)", r)
            return r

        def on_done(ok: bool) -> None:
            log.info("[timing] chain write: on_done (%s)", ok)
            if ok:
                # The pedal will echo chain_changed for our own write: we drop
                # it (we already have the state in memory) so as not to re-read.
                self._suppress_chain_echo = True
                self._status("Block order applied on the pedal ✓")
            else:
                self.statusBar().showMessage("Error reordering on the pedal")

        self._run(job, on_done)

    # --- live sync: changes coming from the pedal ---

    def _on_device_event(self, ev: dict) -> None:
        """Dispatch a pedal notification to the matching handler."""
        kind = ev.get("type")
        data = ev.get("data", {})
        log.info("Pedal event: %s %s", kind, data)
        if kind == "set_param":
            self._on_param_from_device(
                data.get("block"), data.get("param"), data.get("value")
            )
        elif kind == "bypass_state":
            self._on_bypass_state_from_device(
                data.get("block"), data.get("enabled")
            )
        elif kind == "snapshot":
            # A snapshot change rewrites many params: we re-read the preset.
            self._open_editor()
        elif kind == "chain_changed":
            if self._suppress_chain_echo:
                # Echo of our own chain write: the in-memory editor is already
                # up to date, no need to re-read (saves ~5 s of handshakes).
                self._suppress_chain_echo = False
                log.info("chain_changed: own echo, dropped (no re-read)")
            else:
                # Reorder done ON the pedal: arrives as a burst (op 49 {75,76}).
                # We restart the timer on each event → a single re-read once the
                # burst settles. The re-read must preserve selection + ●
                # (#2/#4): it is an unsaved edit, not a preset change.
                self._chain_reread_pending = True
                to_slot = data.get("to_slot")
                if to_slot is not None:
                    # last swap of the burst = final target of the moved block.
                    self._chain_reread_to_slot = to_slot
                self._chain_reread_timer.start(500)
        elif kind == "assignment_changed":
            # Bypass/controller assignment change done ON the pedal (opcode
            # 31/34). It does not carry the new blob, so we re-read the active
            # preset (debounced). If it is an echo of OUR own op 21,
            # _suppress_chain_echo is active: we ignore it WITHOUT consuming the
            # flag (the final chain_changed of the same burst consumes it).
            if not self._suppress_chain_echo:
                self._chain_reread_pending = True
                self._chain_reread_timer.start(500)
        elif kind == "preset_loaded":
            self._open_editor()
        elif kind == "tempo":
            value = data.get("value")
            if value is not None:
                self.editor_view.toolbar.set_tempo(value)

    def _on_param_from_device(self, raw_block, param, value) -> None:
        ed = self.editor_view.editor
        if ed is None or raw_block is None or param is None or value is None:
            return
        slot = ed.slot_from_block_index(raw_block)
        if slot is None:
            return
        chain = ed.preset.chain
        block = chain[slot] if slot < len(chain) else None
        if block is None or param >= len(block.params):
            return
        # No end_gesture: a knob sweep from the pedal (same slot+idx) coalesces
        # into a single undo step, like dragging a slider.
        ed.set_param(slot, param, value)
        self.editor_view.modified = True
        self.editor_view.refresh()

    def _on_bypass_state_from_device(self, raw_block, enabled) -> None:
        """Apply the ABSOLUTE bypass state the pedal reports (op 49).

        Unlike the old toggle (op 39), it carries the explicit `enabled`, so:
        (a) the wah is reflected even if it does not send OP_BYPASS (#6), and
        (b) when the change originated in the app, the pedal echo carries the
        SAME state and the `block.enabled == enabled` guard makes it a no-op (no
        flicker, no undo noise).
        """
        ed = self.editor_view.editor
        if ed is None or raw_block is None or enabled is None:
            return
        slot = ed.slot_from_block_index(raw_block)
        if slot is None:
            return
        chain = ed.preset.chain
        block = chain[slot] if slot < len(chain) else None
        if block is None or block.enabled == enabled:
            return
        ed.set_bypass(slot, enabled)
        self.editor_view.modified = True
        self.editor_view.refresh()

    # --- helpers ---

    def _status(self, tail: str) -> None:
        midi_txt = f"MIDI {self.midi.port}" if self.midi else "MIDI not available"
        self.statusBar().showMessage(f"{self._info}  ·  {tail}  ·  {midi_txt}")

    def _run(self, fn, on_done) -> None:
        # The reader shares the USB: it is paused while a Worker runs and
        # resumed when it finishes (finished fires on success and on failure).
        if self._notification_reader is not None:
            self._notification_reader.pause()
        worker = Worker(fn)
        worker.setParent(self)
        worker.done.connect(on_done)
        worker.failed.connect(self._on_failed)

        def _cleanup(w=worker):
            self._workers.discard(w)
            w.deleteLater()
            if self._notification_reader is not None:
                self._notification_reader.resume()

        worker.finished.connect(_cleanup)
        self._workers.add(worker)
        worker.start()

    def closeEvent(self, event) -> None:
        if self._notification_reader is not None:
            self._notification_reader.stop()
            self._notification_reader.wait(1000)
            self._notification_reader = None
        for w in list(self._workers):
            if w.isRunning():
                w.wait(3000)
        self.device.disconnect()
        super().closeEvent(event)


def run() -> int:
    import os
    level = os.environ.get("PODGO_LOGLEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(relativeCreated)7.0fms %(levelname)s %(name)s: %(message)s",
    )
    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()
