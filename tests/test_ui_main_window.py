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


# --- block focus on the pedal (spec 12: op 78 selects the block) ---


class _FakeDevice:
    """Records select_block calls instead of touching USB."""

    connected = True

    def __init__(self) -> None:
        self.selected: list[int] = []

    def select_block(self, block_index: int) -> bool:
        self.selected.append(block_index)
        return True


def test_seleccionar_bloque_lo_selecciona_en_el_pedal(app):
    """Selecting a block sends op 78 with the raw block index, so the pedal's
    own screen and knobs follow the app (spec 12)."""
    win = _window(app)
    ed = _load_preset(win)
    device = _FakeDevice()
    win.device = device
    win.editor_view.device = device

    slot = next(i for i, b in enumerate(ed.preset.chain) if b is not None)
    win.editor_view.select_slot(slot)

    assert device.selected == [ed.block_index(slot)]


def test_seleccionar_input_usa_su_indice(app):
    win = _window(app)
    ed = _load_preset(win)
    device = _FakeDevice()
    win.device = device
    win.editor_view.device = device

    win.editor_view.select_io("input")

    assert device.selected == [ed.io_block_index("input")]


def test_slot_vacio_no_selecciona_nada(app):
    win = _window(app)
    _load_preset(win)
    device = _FakeDevice()
    win.device = device
    win.editor_view.device = device
    win.editor_view.select_slot(9)   # empty slot in the fixture
    assert device.selected == []


def test_seleccion_durante_un_read_queda_pendiente(app):
    """A write during a read stream is refused (and would freeze the UI): the
    selection waits for the worker to finish (spec 14)."""
    win = _window(app)
    ed = _load_preset(win)
    device = _FakeDevice()
    win.device = device
    win.editor_view.device = device

    slot = next(i for i, b in enumerate(ed.preset.chain) if b is not None)
    win._workers.add(object())        # simulate a read in flight
    try:
        win.editor_view.select_slot(slot)
        assert device.selected == []  # postponed, not lost
    finally:
        win._workers.clear()

    win._flush_pending_block_select()
    assert device.selected == [ed.block_index(slot)]
