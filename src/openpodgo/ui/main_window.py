"""openpodgo main window, modeled on POD Go Edit: a single window with the
Librarian (setlists + presets) on the left and the active-preset editor
(Signal Flow + Inspector) on the right.

Every USB operation runs in a Worker (one job at a time, by design of the
vendor protocol); recalling a preset verifies against active_state() that the
pedal actually changed before re-reading the active preset.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QStatusBar,
    QTextEdit,
)

from .. import pgb, preset
from ..device import PodGo
from ..editor import PresetEditor
from ..midi import MidiError, MidiOut
from ..notifications import NotificationReader
from .backup_dialog import CreateBackupDialog, RestoreBackupDialog
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


class ProgressWorker(QThread):
    """Runs a function off the UI thread with progress callbacks."""

    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn(self.progress.emit))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, autoconnect: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("OpenPodGo")
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
        #: A counter, not a flag: queued chain writes can run back-to-back
        #: before the reader sees their echoes (one echo per write).
        self._suppress_chain_echo = 0
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
        #: A chain write (op 21) requested while a worker was in flight: it is
        #: flushed when the worker finishes instead of being dropped (issue #2,
        #: e.g. two quick bypass toggles).
        self._chain_write_pending = False
        self._busy_depth = 0

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
        self.librarian.export_requested.connect(self._export_preset_at)
        self.librarian.rename_requested.connect(self._rename_preset)
        self.librarian.rename_committed.connect(
            lambda slot, name: self._commit_preset_rename(slot, name)
        )
        self.librarian.preset_dropped.connect(self._import_pgp_file_to)
        self.librarian.reset_requested.connect(self._reset_preset)

        self.editor_view = EditorView()
        self.editor_view.setEnabled(False)  # until a preset is loaded
        self.editor_view.save_requested.connect(self._save_to_pedal)
        self.editor_view.import_requested.connect(self._import_preset)
        self.editor_view.bypass_midi_sent.connect(self._on_bypass_midi)
        self.editor_view.snapshot_selected.connect(self._on_snapshot)
        self.editor_view.chain_write_requested.connect(self._write_chain_to_pedal)
        self.editor_view.prev_requested.connect(lambda: self._step_preset(-1))
        self.editor_view.next_requested.connect(lambda: self._step_preset(+1))
        self.editor_view.rename_requested.connect(self._on_toolbar_rename)
        self.editor_view.file_dropped.connect(
            lambda path: self._import_pgp_file_to(
                self.librarian.loaded if self.librarian.loaded is not None else 0, path
            )
        )

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
        act_create_backup = QAction("&Create backup…", self)
        act_create_backup.triggered.connect(self._create_backup)
        file_menu.addAction(act_create_backup)

        act_restore_backup = QAction("&Restore from backup…", self)
        act_restore_backup.triggered.connect(self._restore_backup)
        file_menu.addAction(act_restore_backup)

        file_menu.addSeparator()
        act_export_zip = QAction("Export presets archive (.zip)…", self)
        act_export_zip.triggered.connect(self._export_presets_zip)
        file_menu.addAction(act_export_zip)

        act_import_zip = QAction("Import presets archive (.zip)…", self)
        act_import_zip.triggered.connect(self._import_presets_zip)
        file_menu.addAction(act_import_zip)

        file_menu.addSeparator()
        act_quit = QAction("&Quit", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        preset_menu = self.menuBar().addMenu("&Preset")
        act_p_rename = QAction("&Rename preset…", self)
        act_p_rename.setShortcut(QKeySequence("Ctrl+R"))
        act_p_rename.triggered.connect(self._preset_menu_rename)
        preset_menu.addAction(act_p_rename)

        preset_menu.addSeparator()
        act_p_import = QAction("&Import preset…", self)
        act_p_import.setShortcut(QKeySequence("Ctrl+I"))
        act_p_import.triggered.connect(self._preset_menu_import)
        preset_menu.addAction(act_p_import)

        act_p_export = QAction("&Export preset…", self)
        act_p_export.setShortcut(QKeySequence("Ctrl+E"))
        act_p_export.triggered.connect(self._preset_menu_export)
        preset_menu.addAction(act_p_export)

        preset_menu.addSeparator()
        act_p_reset = QAction("Re&set preset…", self)
        act_p_reset.triggered.connect(self._preset_menu_reset)
        preset_menu.addAction(act_p_reset)

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

    def _activate_preset(self, position: int, on_done=None) -> None:
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

        def handle_loaded(result):
            self._on_preset_loaded(result)
            if on_done is not None:
                on_done()

        self._run(job, handle_loaded)

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
        # A chain write queued against the previous editor must not dump the
        # freshly loaded preset (nobody edited it).
        self._chain_write_pending = False
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

    def _load_and_save_pgp_to_slot(self, slot: int, pgp: dict) -> None:
        self.editor_view.load_pgp(pgp)
        ed = self.editor_view.editor
        name = self.editor_view.preset_name
        slot_text = self._slot_text(slot)
        setlist = self.current_setlist
        self.statusBar().showMessage(f"Importing preset to slot {slot_text}…")

        def job():
            device = self.device
            # 1. Switch pedal to the target slot first
            if self.midi is not None:
                self.midi.recall(setlist, slot)
                for _ in range(RECALL_RETRIES):
                    time.sleep(RECALL_SETTLE_S)
                    state = device.active_state()
                    if state.slot == slot:
                        break

            # 2. Upload the DSP chain/preset structure (op 21) containing all parameters
            blob = ed.to_blob()
            self._suppress_chain_echo += 1
            device.write_chain_blob(blob)

            # 3. Save the active edit buffer to target slot with the preset name (op 71)
            device.save_preset(setlist, slot, name)
            return ed

        def on_done(ed):
            self.librarian.update_preset_name(slot, name)
            self.librarian.set_loaded(slot)
            self.editor_view.set_preset(
                ed,
                name,
                slot_text,
                keep_state=False,
                modified=False,
            )
            self.editor_view.mark_saved()
            self._status(f"“{name}” imported to {slot_text} ✓")

        self._run(job, on_done)

    def _import_preset_to(self, slot: int) -> None:
        """Import .pgp to the target slot: load editor + write to pedal + activate."""
        if self._workers:
            return
        if self.editor_view.modified and not self._confirm_discard():
            return
        pgp = self.editor_view._import_dialog()
        if pgp is None:
            return
        self._load_and_save_pgp_to_slot(slot, pgp)

    def _import_pgp_file_to(self, slot: int, path: str | Path) -> None:
        """Import a specific .pgp file directly to target slot (e.g. from dropzone)."""
        if self._workers:
            return
        if self.editor_view.modified and not self._confirm_discard():
            return
        from pathlib import Path
        from ..preset import load_pgp

        try:
            pgp = load_pgp(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Could not load the preset file:\n{exc}")
            return
        self._load_and_save_pgp_to_slot(slot, pgp)

    def _import_preset(self) -> None:
        """Import .pgp from the File menu into the currently loaded slot."""
        slot = self.librarian.loaded
        if slot is None:
            self.statusBar().showMessage(
                "No preset loaded: select a slot first"
            )
            return
        self._import_preset_to(slot)

    def _target_slot_and_name(self) -> tuple[int | None, str | None]:
        slot = self.librarian.current_slot()
        if slot is None:
            slot = self.librarian.loaded
        if slot is None:
            return None, None
        name = self.librarian.preset_name(slot) or "Preset"
        return slot, name

    def _preset_menu_rename(self) -> None:
        slot, name = self._target_slot_and_name()
        if slot is not None and name is not None:
            self._rename_preset(slot, name)

    def _preset_menu_import(self) -> None:
        slot, _ = self._target_slot_and_name()
        if slot is not None:
            self._import_preset_to(slot)

    def _preset_menu_export(self) -> None:
        slot, _ = self._target_slot_and_name()
        if slot is not None:
            self._export_preset_at(slot)

    def _preset_menu_reset(self) -> None:
        slot, _ = self._target_slot_and_name()
        if slot is not None:
            self._reset_preset(slot)

    def _export_preset(self) -> None:
        """Export .pgp from the File or Preset menu."""
        self.editor_view._export_dialog()

    def _export_preset_at(self, slot: int) -> None:
        if self._workers:
            return
        if slot == self.librarian.loaded and self.editor_view.editor is not None:
            self._export_preset()
        else:
            self._activate_preset(slot, on_done=self._export_preset)

    def _rename_preset(self, slot: int, current_name: str) -> None:
        """Trigger in-place rename in the librarian list."""
        self.librarian.start_rename_slot(slot)

    def _on_toolbar_rename(self, new_name: str) -> None:
        slot = self.librarian.loaded
        if slot is None:
            return
        self._commit_preset_rename(slot, new_name)

    def _commit_preset_rename(self, slot: int, new_name: str) -> None:
        if self._workers:
            QTimer.singleShot(100, lambda: self._commit_preset_rename(slot, new_name))
            return
        current_name = self.librarian.preset_name(slot) or ""
        if new_name == current_name:
            return
        slot_text = self._slot_text(slot)
        setlist = self.current_setlist

        def job():
            self.device.save_preset(setlist, slot, new_name)
            return self.device.active_state(), self.device.active_preset()

        def on_done(res):
            state, pre = res
            self.librarian.update_preset_name(slot, new_name)
            if slot == self.librarian.loaded:
                self.editor_view.set_preset_name(new_name)
                self.editor_view.modified = False
            self.statusBar().showMessage(f"Renamed preset {slot_text} to “{new_name}”")

        self._run(job, on_done)

    def _reset_preset(self, slot: int) -> None:
        if self._workers:
            return
        slot_text = self._slot_text(slot)
        current_name = self.librarian.preset_name(slot) or "Preset"
        reply = QMessageBox.question(
            self,
            "Reset Preset",
            f"Are you sure you want to reset preset {slot_text} (“{current_name}”) back to 'New Preset'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        setlist = self.current_setlist

        def job():
            if self.midi is not None:
                self.midi.recall(setlist, slot)
                time.sleep(RECALL_SETTLE_S)
            pgp = preset.new_preset_dict("New Preset")
            ed, _warnings = PresetEditor.from_pgp(pgp)
            blob = ed.to_blob()
            self._suppress_chain_echo += 1
            self.device.write_chain_blob(blob)
            self.device.save_preset(setlist, slot, "New Preset")
            return ed

        def on_done(ed):
            self.librarian.set_loaded(slot)
            self.librarian.update_preset_name(slot, "New Preset")
            self.editor_view.set_preset(
                ed,
                "New Preset",
                slot_text,
                keep_state=False,
                modified=False,
            )
            self.editor_view.mark_saved()
            self.statusBar().showMessage(f"Reset preset {slot_text} to “New Preset”")

        self._run(job, on_done)

    # --- backup and restore (.pgb) & archive (.zip) ---

    def _create_backup(self) -> None:
        """Open the Create Backup dialog and handle backup creation."""
        dlg = CreateBackupDialog(self, setlists=self.setlists or ["Factory", "User"])
        dlg.create_requested.connect(lambda cfg: self._start_backup_job(dlg, cfg))
        dlg.exec()

    def _start_backup_job(self, dlg: CreateBackupDialog, config: dict) -> None:
        target_path = config["path"]
        target_setlists = config.get("setlists", ["User"])
        device = self.device
        midi = self.midi
        initial_slot = self.librarian.loaded if self.librarian else 0
        initial_setlist = self.current_setlist

        def job(emit_progress):
            total_slots = len(target_setlists) * 128
            current_progress = 0
            backup_setlists = {}

            info_prod = getattr(device.info, "product", "POD Go") if device and device.info else "POD Go"
            info_ver = getattr(device.info, "version", "v2.01") if device and device.info else "v2.01"
            metadata = {
                "created_at": datetime.datetime.now().isoformat(),
                "device": info_prod,
                "version": info_ver,
                "description": config.get("description", ""),
            }

            for s_name in target_setlists:
                s_idx = 0 if s_name.lower() == "factory" else 1
                entries = []
                if device and device.connected:
                    try:
                        entries = device.list_presets(s_idx)
                    except Exception as e:
                        log.warning("Could not list presets for %s: %s", s_name, e)

                presets_in_setlist = []
                for slot in range(128):
                    slot_name = entries[slot].name if slot < len(entries) else f"Preset {slot:03d}"
                    slot_txt = f"{(slot // 4) + 1:02d}{'ABCD'[slot % 4]}"
                    emit_progress(
                        current_progress,
                        total_slots,
                        f"Reading {s_name} {slot_txt} ({slot_name})…",
                    )
                    preset_dict = None
                    if device and device.connected and midi:
                        if (
                            slot == initial_slot
                            and s_idx == initial_setlist
                            and self.editor_view
                            and self.editor_view.editor is not None
                        ):
                            try:
                                pgp_doc = self.editor_view.editor.to_pgp(slot_name)
                                preset_dict = pgp_doc.get("data", pgp_doc)
                            except Exception as e:
                                log.debug("Could not use active editor state for %s: %s", slot_name, e)

                        if preset_dict is None:
                            try:
                                midi.recall(s_idx, slot)
                                time.sleep(0.06)
                                p = device.active_preset()
                                if p:
                                    ed = PresetEditor(p)
                                    pgp_doc = ed.to_pgp(slot_name)
                                    preset_dict = pgp_doc.get("data", pgp_doc)
                            except Exception as e:
                                log.warning("Could not read preset %s slot %d: %s", s_name, slot, e)

                    if not preset_dict:
                        fallback = preset.new_preset_dict(name=slot_name)
                        preset_dict = fallback.get("data", fallback)

                    presets_in_setlist.append(preset_dict)
                    current_progress += 1

                backup_setlists[s_name] = presets_in_setlist

            # Restore original active slot
            if device and device.connected and midi and initial_slot is not None:
                try:
                    midi.recall(initial_setlist, initial_slot)
                    time.sleep(0.06)
                except Exception as e:
                    log.warning("Could not restore active slot %d: %s", initial_slot, e)

            emit_progress(total_slots, total_slots, "Compressing and saving .pgb container…")
            backup = pgb.Backup(
                globals={"System": {"device": info_prod, "version": info_ver}},
                setlists=backup_setlists,
                metadata=metadata,
            )
            pgb.write_backup(target_path, backup)
            return target_path

        def on_done(path):
            dlg.set_completed(f"Backup saved to {Path(path).name}")
            self._status(f"Backup created: {Path(path).name} ✓")

        self._run_progress(job, on_done, dlg.set_progress)

    def _restore_backup(self) -> None:
        """Open the Restore From Backup dialog."""
        dlg = RestoreBackupDialog(self)
        dlg.restore_requested.connect(lambda cfg: self._start_restore_job(dlg, cfg))
        dlg.exec()

    def _start_restore_job(self, dlg: RestoreBackupDialog, config: dict) -> None:
        backup_path = config["path"]
        target_setlists = config.get("setlists", [])
        device = self.device

        def job(emit_progress):
            emit_progress(0, 100, "Reading backup container…")
            loaded = pgb.read_backup(backup_path)

            total_items = sum(len(loaded.setlists.get(s, [])) for s in target_setlists)
            current_progress = 0

            for s_name in target_setlists:
                s_idx = 0 if s_name.lower() == "factory" else 1
                presets = loaded.setlists.get(s_name, [])
                for slot, p in enumerate(presets):
                    p_name = p.get("meta", {}).get("name") if isinstance(p, dict) else f"Preset {slot}"
                    emit_progress(
                        current_progress,
                        total_items or 1,
                        f"Restoring {s_name} slot {slot:03d} ({p_name})…",
                    )
                    if device and device.connected:
                        try:
                            device.save_preset(s_idx, slot, p_name)
                        except Exception as exc:
                            log.warning("Could not write preset to %s %d: %s", s_name, slot, exc)
                    current_progress += 1

            emit_progress(total_items or 100, total_items or 100, "Restore completed.")
            return total_items

        def on_done(count):
            dlg.set_completed(f"Restored {count} presets successfully.")
            self._reload_presets()
            self._status("Backup restoration complete ✓")

        self._run_progress(job, on_done, dlg.set_progress)

    def _export_presets_zip(self) -> None:
        """Export all presets of the setlist into a flat .zip archive."""
        default_file = f"podgo_presets_{datetime.date.today().isoformat()}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Presets Archive",
            default_file,
            "Zip Archive (*.zip)",
        )
        if not path:
            return

        device = self.device
        midi = self.midi
        current_setlist = self.current_setlist
        setlist_name = (
            self.setlists[current_setlist]
            if self.setlists and current_setlist < len(self.setlists)
            else "User"
        )
        s_idx = 0 if setlist_name.lower() == "factory" else 1
        initial_slot = self.librarian.loaded if self.librarian else 0
        total_slots = 128

        progress = QProgressDialog("Exporting presets archive…", None, 0, total_slots, self)
        progress.setWindowTitle("Export Presets Archive")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def job(emit_progress):
            presets = []
            for slot in range(total_slots):
                slot_txt = self._slot_text(slot)
                slot_name = (self.librarian.preset_name(slot) if self.librarian else None) or f"Preset {slot:03d}"
                emit_progress(slot, total_slots, f"Reading preset {slot_txt} ({slot_name})…")
                preset_dict = None
                if device and device.connected and midi:
                    if slot == initial_slot and self.editor_view.editor is not None:
                        ed = self.editor_view.editor
                        preset_dict = ed.to_pgp(slot_name)
                    if preset_dict is None:
                        try:
                            midi.recall(s_idx, slot)
                            time.sleep(0.08)
                            p = device.active_preset()
                            if p:
                                ed = PresetEditor(p)
                                preset_dict = ed.to_pgp(slot_name)
                        except Exception as e:
                            log.warning("Could not read preset slot %d: %s", slot, e)
                if not preset_dict:
                    preset_dict = preset.new_preset_dict(name=slot_name)
                presets.append(preset_dict)

            # Restore original active slot
            if device and device.connected and midi and initial_slot is not None:
                try:
                    midi.recall(s_idx, initial_slot)
                    time.sleep(0.08)
                except Exception as e:
                    log.warning("Could not restore active slot %d: %s", initial_slot, e)

            emit_progress(total_slots, total_slots, "Creating zip archive…")
            pgb.export_presets_zip(path, {setlist_name: presets}, flat=True)
            return path, len(presets)

        def on_done(res):
            path, count = res
            progress.close()
            self._status(f"Exported {count} presets to {Path(path).name} ✓")
            QMessageBox.information(
                self,
                "Archive Exported",
                f"Exported {count} presets directly to:\n{path}",
            )

        def on_progress(cur, total, msg):
            progress.setMaximum(total)
            progress.setValue(cur)
            progress.setLabelText(msg)

        worker = self._run_progress(job, on_done, on_progress)
        worker.failed.connect(lambda exc: progress.close())

    def _import_presets_zip(self) -> None:
        """Import presets from a .zip archive."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Presets Archive",
            "",
            "Zip Archive (*.zip);;All Files (*)",
        )
        if not path:
            return

        try:
            imported = pgb.import_presets_zip(path)
            counts = [f"{s_name}: {len(p_list)}" for s_name, p_list in imported.items()]
            summary = ", ".join(counts) if counts else "No presets found"
            self._status(f"Imported archive: {summary} ✓")

            # If user has presets in the archive, offer to write them to the pedal
            all_presets = imported.get("User", []) or next(iter(imported.values()), [])
            if self.device and self.device.connected and all_presets:
                ans = QMessageBox.question(
                    self,
                    "Restore Presets Archive",
                    f"Found {summary}.\n\nDo you want to restore these {len(all_presets)} presets onto your POD Go?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans == QMessageBox.StandardButton.Yes:
                    self._restore_presets_list(all_presets)
                    return

            QMessageBox.information(
                self,
                "Archive Imported",
                f"Successfully read preset archive:\n{summary}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", f"Could not import presets archive:\n{exc}")

    def _restore_presets_list(self, preset_list: list[dict]) -> None:
        device = self.device
        current_setlist = self.current_setlist
        total_items = min(len(preset_list), 128)

        progress = QProgressDialog("Restoring presets to POD Go…", None, 0, total_items, self)
        progress.setWindowTitle("Restoring Presets")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def job(emit_progress):
            for slot in range(total_items):
                p = preset_list[slot]
                p_name = p.get("meta", {}).get("name") if isinstance(p, dict) else f"Preset {slot:03d}"
                slot_txt = self._slot_text(slot)
                emit_progress(slot, total_items, f"Writing slot {slot_txt} ({p_name})…")
                if device and device.connected:
                    try:
                        if isinstance(p, dict) and "tone" in p:
                            ed, _ = PresetEditor.from_dict(p)
                            blob = ed.to_blob()
                            device.write_chain_blob(blob)
                        device.save_preset(current_setlist, slot, p_name)
                    except Exception as exc:
                        log.warning("Could not restore preset to slot %d: %s", slot, exc)
            return total_items

        def on_done(count):
            progress.close()
            self._reload_presets()
            self._status(f"Restored {count} presets to POD Go ✓")
            QMessageBox.information(
                self,
                "Restore Complete",
                f"Successfully restored {count} presets to your POD Go.",
            )

        def on_progress(cur, total, msg):
            progress.setMaximum(total)
            progress.setValue(cur)
            progress.setLabelText(msg)

        worker = self._run_progress(job, on_done, on_progress)
        worker.failed.connect(lambda exc: progress.close())

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
                self.librarian.update_preset_name(slot, name)
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
            self._chain_write_pending = True
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
                self._suppress_chain_echo += 1
                self._status("Change applied on the pedal ✓")
            else:
                self.statusBar().showMessage("Error applying the change on the pedal")

        self._run(job, on_done)

    def _flush_pending_chain_write(self) -> None:
        """Run the chain write queued while a worker was busy, if any.

        The blob is taken at run time, so it carries the latest editor state.
        """
        if self._chain_write_pending and not self._workers:
            self._chain_write_pending = False
            self._write_chain_to_pedal()

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
                self._suppress_chain_echo -= 1
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

    def _push_busy(self) -> None:
        self._busy_depth = getattr(self, "_busy_depth", 0) + 1
        if self._busy_depth == 1:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def _pop_busy(self) -> None:
        self._busy_depth = getattr(self, "_busy_depth", 0) - 1
        if self._busy_depth <= 0:
            self._busy_depth = 0
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

    def _run(self, fn, on_done) -> None:
        # The reader shares the USB: it is paused while a Worker runs and
        # resumed when it finishes (finished fires on success and on failure).
        if self._notification_reader is not None:
            self._notification_reader.pause()
        self._push_busy()
        worker = Worker(fn)
        worker.setParent(self)
        worker.done.connect(on_done)
        worker.failed.connect(self._on_failed)

        def _cleanup(w=worker):
            self._workers.discard(w)
            w.deleteLater()
            self._pop_busy()
            if self._notification_reader is not None:
                self._notification_reader.resume()
            self._flush_pending_chain_write()

        worker.finished.connect(_cleanup)
        self._workers.add(worker)
        worker.start()

    def _run_progress(self, fn, on_done, on_progress=None) -> ProgressWorker:
        if self._notification_reader is not None:
            self._notification_reader.pause()
        self._push_busy()
        worker = ProgressWorker(fn)
        worker.setParent(self)
        if on_progress:
            worker.progress.connect(on_progress)
        worker.done.connect(on_done)
        worker.failed.connect(self._on_failed)

        def _cleanup(w=worker):
            self._workers.discard(w)
            w.deleteLater()
            self._pop_busy()
            if self._notification_reader is not None:
                self._notification_reader.resume()
            self._flush_pending_chain_write()

        worker.finished.connect(_cleanup)
        self._workers.add(worker)
        worker.start()
        return worker

    def closeEvent(self, event) -> None:
        # Do not let a worker's cleanup flush a queued write during teardown.
        self._chain_write_pending = False
        self._pop_busy()
        if self._notification_reader is not None:
            self._notification_reader.stop()
            self._notification_reader.wait(1000)
            self._notification_reader = None
        for w in list(self._workers):
            if w.isRunning():
                w.wait(3000)
        self.device.disconnect()
        super().closeEvent(event)


def _parse_args(argv: list[str] | None = None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="openpodgo",
        description="Open-source editor for the Line 6 POD Go on Linux.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (INFO level logging).",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug output (DEBUG level logging).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-error output (ERROR level logging only).",
    )
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def _get_log_level(args) -> int:
    import os

    if args.debug:
        return logging.DEBUG
    elif args.verbose:
        return logging.INFO
    elif args.quiet:
        return logging.ERROR
    else:
        env_level = os.environ.get("PODGO_LOGLEVEL", "WARNING").upper()
        return getattr(logging, env_level, logging.WARNING)


def run(argv: list[str] | None = None) -> int:
    import signal
    import sys

    args = _parse_args(argv)
    log_level = _get_log_level(args)

    logging.basicConfig(
        level=log_level,
        format="%(relativeCreated)7.0fms %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    # Enable terminal Ctrl+C (SIGINT) to terminate process immediately
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication.instance() or QApplication(sys.argv)

    # Let Qt event loop periodically yield so OS signals like SIGINT trigger
    sig_timer = QTimer()
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(200)

    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()

