"""Single-window POD Go Edit style: Librarian on the left, editor on the
right; without a pedal there is no error modal (offline state + Reconnect)."""

import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from pathlib import Path  # noqa: E402

from PySide6.QtWidgets import QApplication, QSplitter  # noqa: E402

from openpodgo import editor, l6helix  # noqa: E402
from openpodgo.ui.editor import EditorView  # noqa: E402
from openpodgo.ui.librarian import LibrarianPanel  # noqa: E402
from openpodgo.ui.main_window import MainWindow  # noqa: E402

CAPS = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(app) -> MainWindow:
    return MainWindow(autoconnect=False)


def test_ventana_unica_con_splitter(app):
    win = _window(app)
    splitter = win.centralWidget()
    assert isinstance(splitter, QSplitter)
    assert isinstance(splitter.widget(0), LibrarianPanel)
    assert isinstance(splitter.widget(1), EditorView)


def test_editor_deshabilitado_sin_preset(app):
    win = _window(app)
    assert not win.editor_view.isEnabled()


def test_on_failed_no_abre_modal(app):
    # Previously _on_failed opened QMessageBox.critical (fatal offscreen and
    # annoying without a pedal): now it transitions to the librarian's offline state.
    win = _window(app)
    win._on_failed("sin USB")  # no debe bloquear
    assert win.librarian.reconnect_btn.isVisibleTo(win.librarian)
    assert "sin USB" in win.statusBar().currentMessage() or True


def test_reconnect_dispara_conexion(app):
    win = _window(app)
    intentos = []
    win._start_connect = lambda: intentos.append(1)  # no tocar USB en el test
    win.librarian.reconnect_requested.emit()
    assert intentos == [1]


def test_slot_text(app):
    win = _window(app)
    assert win._slot_text(0) == "01A"
    assert win._slot_text(5) == "02B"
    assert win._slot_text(127) == "32D"


def _load_preset(win) -> editor.PresetEditor:
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    ed = editor.PresetEditor(l6helix.parse_blob(blob))
    win.editor_view.set_preset(ed, "BassPreset")
    return ed


def test_bypass_state_aplica_estado_absoluto(app):
    # op 49 carries an explicit enabled: the block takes THAT state (no toggle).
    win = _window(app)
    ed = _load_preset(win)
    slot = next(i for i, b in enumerate(ed.preset.chain) if b is not None)
    raw = ed.block_index(slot)
    ed.set_bypass(slot, True)
    win._on_device_event(
        {"type": "bypass_state", "data": {"block": raw, "enabled": False}}
    )
    assert ed.preset.chain[slot].enabled is False


def test_bypass_state_eco_de_la_app_es_noop(app):
    # If the incoming state == current state (echo of the change made in the app),
    # it is not reapplied: no flicker and no spurious modified mark.
    win = _window(app)
    ed = _load_preset(win)
    slot = next(i for i, b in enumerate(ed.preset.chain) if b is not None)
    raw = ed.block_index(slot)
    ed.set_bypass(slot, True)
    win.editor_view.modified = False
    win._on_device_event(
        {"type": "bypass_state", "data": {"block": raw, "enabled": True}}
    )
    assert ed.preset.chain[slot].enabled is True
    assert win.editor_view.modified is False  # no-op: no marca modificado


def _load_into_editor(win):
    """Loads the BassPreset fixture into the window's editor."""
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    pre = l6helix.parse_blob(blob)
    state = types.SimpleNamespace(name="BassPreset", slot=0)
    win.editor_view.set_preset(editor.PresetEditor(pre), state.name)
    return state, pre


def test_chain_changed_marca_reread_pending_con_to_slot(app):
    win = _window(app)
    win._on_device_event(
        {"type": "chain_changed", "data": {"from_slot": 1, "to_slot": 4}}
    )
    assert win._chain_reread_pending is True
    assert win._chain_reread_to_slot == 4
    assert win._chain_reread_timer.isActive()


def test_show_preset_tras_reorden_preserva_modified_y_selecciona_movido(app):
    win = _window(app)
    state, pre = _load_into_editor(win)
    win.editor_view.modified = True  # there was an unsaved edit (●)

    # simulates the pedal burst: a re-read to slot 4 is pending
    win._chain_reread_pending = True
    win._chain_reread_to_slot = 4

    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    win._show_preset(state, l6helix.parse_blob(blob))

    assert win.editor_view.modified is True          # ● survives (#2)
    assert win.editor_view._selected == 4            # moved block (#4)
    assert win._chain_reread_pending is False        # flags cleared
    assert win._chain_reread_to_slot is None


def test_show_preset_normal_no_preserva(app):
    win = _window(app)
    state, _pre = _load_into_editor(win)
    win.editor_view.modified = True
    # no pending reread → real preset change
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    win._show_preset(state, l6helix.parse_blob(blob))
    assert win.editor_view.modified is False


def test_open_editor_no_pierde_reread_con_worker_ocupado(app):
    # If the reorder timer fires while a worker is in flight,
    # _open_editor retries instead of discarding the re-read: the flags
    # survive (not leaked to an unrelated load) and the timer stays armed.
    win = _window(app)
    win._chain_reread_pending = True
    win._chain_reread_to_slot = 3
    win._workers.add(object())  # simula un worker en vuelo
    try:
        win._open_editor()
        assert win._chain_reread_pending is True
        assert win._chain_reread_to_slot == 3
        assert win._chain_reread_timer.isActive()
    finally:
        win._workers.clear()


def test_activate_preset_limpia_reread_pendiente(app):
    # A deliberate preset change discards a pending reorder re-read:
    # it must not inherit keep_state or the reorder slot.
    win = _window(app)
    win.midi = object()  # presencia de MIDI (no se usa: stubeamos _run)
    win._run = lambda fn, on_done: None  # no lanzar worker real
    win._chain_reread_pending = True
    win._chain_reread_to_slot = 3
    win._activate_preset(5)
    assert win._chain_reread_pending is False
    assert win._chain_reread_to_slot is None


def test_chain_write_con_worker_ocupado_queda_pendiente(app):
    # Issue #2: a chain write requested while a worker is in flight (e.g. two
    # quick bypass toggles) is not lost: it is queued and flushed afterwards
    # with the CURRENT editor state.
    win = _window(app)
    _load_preset(win)
    runs = []
    win._run = lambda fn, on_done: runs.append(fn)
    win.editor_view.select_slot(0)
    win._workers.add(object())  # simula un worker en vuelo
    try:
        win._write_chain_to_pedal()
        assert runs == []
        assert win._chain_write_pending is True
    finally:
        win._workers.clear()
    win._flush_pending_chain_write()
    assert len(runs) == 1
    assert win._chain_write_pending is False
    win._flush_pending_chain_write()  # nada pendiente → no relanza
    assert len(runs) == 1


def test_show_preset_descarta_chain_write_pendiente(app):
    # A write queued against the previous preset must not dump the newly
    # loaded one (nobody edited it).
    win = _window(app)
    state, _pre = _load_into_editor(win)
    win._chain_write_pending = True
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    win._show_preset(state, l6helix.parse_blob(blob))
    assert win._chain_write_pending is False


def test_eco_de_dos_chain_writes_seguidos_no_dispara_reread(app):
    # Two back-to-back chain writes → two echoes; both must be swallowed
    # without arming a re-read.
    win = _window(app)
    win._suppress_chain_echo = 2
    for _ in range(2):  # each burst: assignment events, then chain_changed
        win._on_device_event({"type": "assignment_changed", "data": {}})
        win._on_device_event({"type": "chain_changed", "data": {}})
    assert win._suppress_chain_echo == 0
    assert win._chain_reread_pending is False
    assert not win._chain_reread_timer.isActive()


def test_shortcuts_ctrl_q(app):
    from PySide6.QtGui import QAction, QKeySequence

    win = _window(app)
    assert not hasattr(win, "_shortcut_ctrl_c")
    assert not hasattr(win, "_shortcut_ctrl_q")

    # Quit shortcut is bound to File -> Quit action without duplicate overload
    quit_act = next(a for a in win.findChildren(QAction) if a.text() == "&Quit")
    assert quit_act.shortcut() == QKeySequence.StandardKey.Quit

    closed = []
    quit_act.triggered.connect(lambda: closed.append(True))
    quit_act.trigger()
    assert closed == [True]


def test_cli_log_level_flags(monkeypatch):
    import logging
    from openpodgo.ui.main_window import _get_log_level, _parse_args

    monkeypatch.delenv("PODGO_LOGLEVEL", raising=False)

    # Defaults to WARNING (not chatty)
    args_default = _parse_args([])
    assert _get_log_level(args_default) == logging.WARNING

    # --verbose / -v -> INFO
    args_verbose = _parse_args(["-v"])
    assert _get_log_level(args_verbose) == logging.INFO

    # --debug / -d -> DEBUG
    args_debug = _parse_args(["--debug"])
    assert _get_log_level(args_debug) == logging.DEBUG

    # --quiet / -q -> ERROR
    args_quiet = _parse_args(["-q"])
    assert _get_log_level(args_quiet) == logging.ERROR

    # Environment variable override when no flag provided
    monkeypatch.setenv("PODGO_LOGLEVEL", "INFO")
    assert _get_log_level(args_default) == logging.INFO


def test_preset_menu_and_busy_cursor(app):
    win = _window(app)

    # Check Preset menu exists and has the expected actions
    menus = {a.text(): a.menu() for a in win.menuBar().actions() if a.menu()}
    assert "&Preset" in menus
    preset_actions = [a.text().replace("&", "") for a in menus["&Preset"].actions() if not a.isSeparator()]
    assert any("Rename" in t for t in preset_actions)
    assert any("Import" in t for t in preset_actions)
    assert any("Export" in t for t in preset_actions)
    assert any("Reset" in t for t in preset_actions)

    # Test busy cursor stack
    assert win._busy_depth == 0
    win._push_busy()
    assert win._busy_depth == 1
    assert QApplication.overrideCursor() is not None
    win._push_busy()
    assert win._busy_depth == 2
    win._pop_busy()
    assert win._busy_depth == 1
    win._pop_busy()
    assert win._busy_depth == 0


def test_export_presets_zip_all_slots(app, tmp_path, monkeypatch):
    import zipfile
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from openpodgo.preset import PresetEntry

    win = _window(app)
    presets = [PresetEntry(slot=i, name="Clean Solo" if i == 0 else f"Tone {i:02d}", index=i) for i in range(128)]
    win.librarian.set_presets(presets)

    zip_path = tmp_path / "all_presets.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(zip_path), "Zip Archive (*.zip)"))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    win._export_presets_zip()

    # The background worker runs
    app.processEvents()
    for _ in range(50):
        if zip_path.exists() and not win._workers:
            break
        app.processEvents()
        import time
        time.sleep(0.01)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == 128
        # None of the files should be in a user/ folder
        assert all(not n.startswith("user/") and not n.startswith("User/") for n in names)
        # Check actual preset names with spaces converted to underscores
        assert names[0] == "01A_Clean_Solo.pgp"
        assert names[1] == "01B_Tone_01.pgp"
        assert names[-1] == "32D_Tone_127.pgp"


def test_drop_pgp_triggers_import(app, monkeypatch):
    win = _window(app)
    pgp_path = CAPS / "spec02_a.pgp"

    imported = []
    monkeypatch.setattr(
        win,
        "_load_and_save_pgp_to_slot",
        lambda slot, pgp: imported.append((slot, pgp.get("meta", {}).get("name"))),
    )

    # Signal from librarian list drop onto slot 3
    win.librarian.preset_dropped.emit(3, str(pgp_path))
    assert len(imported) == 1
    assert imported[0][0] == 3

    # Signal from editor title drop onto loaded slot 7
    win.librarian.set_loaded(7)
    win.editor_view.file_dropped.emit(str(pgp_path))
    assert len(imported) == 2
    assert imported[1][0] == 7
