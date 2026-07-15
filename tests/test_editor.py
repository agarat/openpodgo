"""In-memory preset editing (raw msgpack body) and export to .pgp.

Reference round-trip: vendor dumps of BassPreset/Preset Two against
the real .pgp files exported by POD Go Edit (same pairs as test_catalog).
"""

import json
import math
from pathlib import Path

import pytest

from openpodgo import catalog, editor, l6helix

CAPS = Path(__file__).parent / "fixtures"

PAIRS = [
    ("spec02_knob.bin", "spec02_a.pgp", "BassPreset"),
    ("spec02_preset2.bin", "spec02_preset2.pgp", "Preset Two"),
]


def _editor(bin_name="spec02_knob.bin") -> editor.PresetEditor:
    blob = l6helix.extract_blob((CAPS / bin_name).read_bytes())
    return editor.PresetEditor(l6helix.parse_blob(blob))


def _slot_of(pre: l6helix.Preset, model_id: int) -> int:
    for i, blk in enumerate(pre.chain):
        if blk is not None and blk.model_id == model_id:
            return i
    raise AssertionError(f"model {model_id} not found in the chain")


# --- mutations ---


def test_set_param():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)  # Tube Drive, Drive=0.47 en el fixture
    before = list(ed.preset.chain[slot].params)
    ed.set_param(slot, 0, 0.55)
    after = ed.preset.chain[slot].params
    assert after[0] == pytest.approx(0.55)
    assert after[1:] == before[1:]


def test_set_param_preserva_tipo_bool():
    ed = _editor()
    slot = _slot_of(ed.preset, 224)  # VolPan: params [Pedal, VolumeTaper(bool)]
    ed.set_param(slot, 1, 1)
    assert ed.preset.chain[slot].params[1] is True


def test_set_bypass():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.set_bypass(slot, False)
    assert ed.preset.chain[slot].enabled is False
    ed.set_bypass(slot, True)
    assert ed.preset.chain[slot].enabled is True


def test_swap_model():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)  # Tube Drive → Triangle Fuzz (95)
    ed.swap_model(slot, "HD2_DistTriangleFuzzMono")
    blk = ed.preset.chain[slot]
    assert blk.model_id == 95
    assert blk.enabled is True
    assert blk.category == 1  # FX, same as any dist
    assert len(blk.params) == 3  # Sustain, Tone, Level

    # The params node {2: n_total, 3: n_snapshoteables} must be
    # identical to a real Triangle Fuzz (in the Preset Two fixture).
    otro = _editor("spec02_preset2.bin")
    real = otro.params_node(_slot_of(otro.preset, 95))
    nuevo = ed.params_node(slot)
    assert (nuevo[2], nuevo[3]) == (real[2], real[3])


def test_swap_model_restricts_category():
    # #5: an Amp slot can only be swapped for another Amp; not an effect.
    ed = _editor()
    amp_slot = _slot_of(ed.preset, 3)  # HD2_AmpGCougar800
    with pytest.raises(ValueError, match="not compatible"):
        ed.swap_model(amp_slot, "HD2_DistTriangleFuzzMono")
    # Changing the amp for another amp is allowed.
    ed.swap_model(amp_slot, "HD2_AmpMandarin80")
    assert ed.preset.chain[amp_slot].model_id == catalog.model_info(
        "HD2_AmpMandarin80"
    ).wire_id
    # An effects block (Dist) accepts other effects, not amps/cabs.
    fx_slot = _slot_of(ed.preset, 366)
    with pytest.raises(ValueError, match="not compatible"):
        ed.swap_model(fx_slot, "HD2_AmpMandarin80")
    ed.swap_model(fx_slot, "HD2_DL4DigDelay")  # Dist → Delay: OK


def test_swap_model_preset_eq_only_accepts_static():
    # spec08: the dedicated Preset EQ can only be swapped for another STATIC EQ;
    # not for an Effects-EQ (Acoustic Sim) or an effect.
    ed = _editor("eq_acoustic_sim_obj22.bin")
    eq_slot = _slot_of(ed.preset, 472)  # HD2_EQ_STATIC_ParametricStereo
    ed.swap_model(eq_slot, "HD2_EQ_STATIC_CaliQStereo")  # STATIC → STATIC: OK
    assert ed.preset.chain[eq_slot].model_id == catalog.model_info(
        "HD2_EQ_STATIC_CaliQStereo"
    ).wire_id
    with pytest.raises(ValueError, match="not compatible|EQ"):
        ed.swap_model(eq_slot, "L6SPB_AcousGtrSimStereo")  # Effects-EQ: no
    with pytest.raises(ValueError, match="not compatible"):
        ed.swap_model(eq_slot, "HD2_DistTriangleFuzzMono")  # effect: no


def test_swap_model_effects_block_accepts_effects_eq():
    # spec08: an Effects block accepts an Effects-EQ (Acoustic Sim) and other
    # effects, but not a Preset EQ STATIC.
    ed = _editor("eq_acoustic_sim_obj22.bin")
    fx_slot = _slot_of(ed.preset, 287)  # HD2_DistStuporODMono (Effects block)
    ed.swap_model(fx_slot, "L6SPB_AcousGtrSimStereo")  # → Effects-EQ: OK
    assert ed.preset.chain[fx_slot].model_id == 485
    with pytest.raises(ValueError, match="is not compatible|EQ"):
        ed.swap_model(fx_slot, "HD2_EQ_STATIC_ParametricStereo")  # Preset EQ: no


def test_swap_model_acoustic_sim_swappable():
    # The Effects-EQ Acoustic Sim now passes the filter (wire_category=1) and
    # can be removed (swapped for an effect).
    ed = _editor("eq_acoustic_sim_obj22.bin")
    aco_slot = _slot_of(ed.preset, 485)  # L6SPB_AcousGtrSimStereo
    ed.swap_model(aco_slot, "HD2_DL4DigDelay")  # Effects-EQ → Delay: OK
    assert ed.preset.chain[aco_slot].model_id == 334


def test_io_params_read_and_write():
    # #2: input = [noiseGate, threshold, decay]; output = [pan, gain].
    ed = _editor()
    assert ed.io_values("input") == [False, -48.0, 0.5]
    assert ed.io_values("output") == [0.5, 0.0]
    # Input is the raw index 0 of DSP_CHAIN; output the last one.
    assert ed.io_block_index("input") == 0
    assert ed.io_block_index("output") == 11
    # set_io_param preserves the on-wire type.
    ed.set_io_param("input", 1, -40.0)
    assert ed.io_values("input")[1] == -40.0
    ed.set_io_param("input", 0, True)
    assert ed.io_values("input")[0] is True
    ed.set_io_param("output", 0, 0.3)
    assert ed.io_values("output")[0] == pytest.approx(0.3)


def test_io_param_undo():
    ed = _editor()
    ed.set_io_param("output", 1, -6.0)
    assert ed.io_values("output")[1] == -6.0
    assert ed.undo()
    assert ed.io_values("output")[1] == 0.0


def test_swap_model_looper_class7():
    # The looper is chain class 7 (id at key 8, params at key 7, category 22),
    # not a normal class-6 block. Inserting it must build that layout and store
    # only the 4 on-wire params (RE'd from the pedal).
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.swap_model(slot, "HD2_LooperOneSwitchMono")
    entry = ed._chain_entries()[slot]
    assert entry[l6helix.ENTRY_CLASS] == l6helix.CLASS_LOOPER
    blk = ed.preset.chain[slot]
    assert blk.model_id == 430
    assert blk.category == 22
    assert blk.params == [0.0, 0.0, 20.0, 20000.0]
    # Round-trips through build_blob (saved to the pedal as the raw body).
    pre2 = l6helix.parse_blob(l6helix.build_blob(ed.body))
    assert pre2.chain[slot].model_id == 430
    assert pre2.chain[slot].params == [0.0, 0.0, 20.0, 20000.0]


def test_swap_model_not_seeded():
    # With official resources, models never seen in a dump are already
    # swappable (wire_id from .sym + validated inferred category).
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.swap_model(slot, "HD2_DistMinotaurMono")
    blk = ed.preset.chain[slot]
    info = catalog.model_info("HD2_DistMinotaurMono")
    assert blk.model_id == info.wire_id
    assert blk.category == 1
    assert len(blk.params) == len(info.param_order)


def _controller_count(ed) -> int:
    return sum(len(entries or []) for entries in ed.body[4])


def test_clear_slot():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)  # Tube Drive: sin param Pedal
    before = _controller_count(ed)
    ed.clear_slot(slot)
    assert ed.preset.chain[slot] is None
    # The footswitch pointing to the block disappears…
    for group in ed.body[3][8] or []:
        for entry in group or []:
            assert entry[11][8] != slot + 1
    # …and the controllers (tied to blocks with Pedal) remain intact.
    assert _controller_count(ed) == before


def test_clear_slot_con_pedal():
    ed = _editor()
    slot = _slot_of(ed.preset, 224)  # VolPan: tied to the expression pedal
    before = _controller_count(ed)
    ed.clear_slot(slot)
    assert ed.preset.chain[slot] is None
    assert _controller_count(ed) == before - 1


# --- undo/redo ---


def test_undo_returns_false_with_no_history():
    ed = _editor()
    assert ed.can_undo() is False
    assert ed.undo() is False
    assert ed.can_redo() is False
    assert ed.redo() is False


def test_undo_set_param():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    original = ed.preset.chain[slot].params[0]
    ed.set_param(slot, 0, 0.55)
    assert ed.can_undo() is True
    assert ed.undo() is True
    assert ed.preset.chain[slot].params[0] == pytest.approx(original)
    assert ed.can_redo() is True


def test_redo_restores_the_edit():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.set_param(slot, 0, 0.55)
    ed.undo()
    assert ed.redo() is True
    assert ed.preset.chain[slot].params[0] == pytest.approx(0.55)
    assert ed.can_redo() is False


def test_redo_clears_after_editing():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.set_param(slot, 0, 0.55)
    ed.undo()
    ed.set_bypass(slot, False)
    assert ed.can_redo() is False


def test_slider_drag_coalescing():
    # Many consecutive set_param on the same parameter = ONE undo step
    # (the state before the complete gesture).
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    original = ed.preset.chain[slot].params[0]
    for v in (0.50, 0.52, 0.55, 0.60):
        ed.set_param(slot, 0, v)
    assert ed.undo() is True
    assert ed.preset.chain[slot].params[0] == pytest.approx(original)
    assert ed.can_undo() is False


def test_end_gesture_separates_steps():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.set_param(slot, 0, 0.55)
    ed.end_gesture()
    ed.set_param(slot, 0, 0.60)
    ed.undo()
    assert ed.preset.chain[slot].params[0] == pytest.approx(0.55)
    ed.undo()
    assert ed.can_undo() is False


def test_different_params_do_not_coalesce():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.set_param(slot, 0, 0.55)
    ed.set_param(slot, 1, 0.70)
    ed.undo()
    assert ed.preset.chain[slot].params[0] == pytest.approx(0.55)


def test_undo_swap_model():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    before = list(ed.preset.chain[slot].params)
    ed.swap_model(slot, "HD2_DistTriangleFuzzMono")
    ed.undo()
    blk = ed.preset.chain[slot]
    assert blk.model_id == 366
    assert blk.params == before


def test_undo_clear_slot_restaura_controllers():
    ed = _editor()
    slot = _slot_of(ed.preset, 224)  # VolPan, tied to the expression pedal
    before = _controller_count(ed)
    ed.clear_slot(slot)
    ed.undo()
    assert ed.preset.chain[slot] is not None
    assert _controller_count(ed) == before


# --- bypass_assignments ---


def test_bypass_assignments():
    # Fixture spec02_knob: FS1→block 8, FS2→block 5, FS4→block 3,
    # FS5→block 4, FS6→block 9; group 9 = EXP Toe (wah + volume).
    ed = _editor()
    assert ed.bypass_assignments() == {
        7: "FS1",
        4: "FS2",
        2: "FS4",
        3: "FS5",
        8: "FS6",
        1: "EXP Toe",
        0: "EXP Toe",
    }


def test_bypass_assignments_tras_clear():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)  # Tube Drive, assigned to FS4
    ed.clear_slot(slot)
    assert slot not in ed.bypass_assignments()


# --- export .pgp ---


def _approx_equal(a, b, path=""):
    """Structural equality with tolerance for floats."""
    if isinstance(a, float) or isinstance(b, float):
        assert not isinstance(a, bool) and not isinstance(b, bool), path
        assert math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-6), f"{path}: {a} != {b}"
    elif isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), (
            f"{path}: keys {sorted(a)} != {sorted(b)}"
        )
        for k in a:
            _approx_equal(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _approx_equal(x, y, f"{path}[{i}]")
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


@pytest.mark.parametrize("bin_name,pgp_name,preset_name", PAIRS)
def test_to_pgp_contra_export_oficial(bin_name, pgp_name, preset_name):
    ed = _editor(bin_name)
    out = ed.to_pgp(name=preset_name)
    ref = json.loads((CAPS / pgp_name).read_text(encoding="utf-8"))

    assert out["schema"] == "L6Preset"
    assert out["version"] == ref["version"]
    assert out["meta"] == ref["meta"]
    assert out["data"]["device"] == ref["data"]["device"]
    assert out["data"]["device_version"] == ref["data"]["device_version"]
    assert out["data"]["meta"]["name"] == preset_name
    # The build_sha from the .pgp is the firmware that SAVED the preset
    # (Preset Two keeps v1.30); the blob only carries the current firmware,
    # which is what we export.
    assert out["data"]["meta"]["build_sha"] == "v2.00-5-g665e64e"

    tone = out["data"]["tone"]
    ref_tone = ref["data"]["tone"]
    _approx_equal(tone["dsp0"], ref_tone["dsp0"], "dsp0")
    _approx_equal(tone["dsp1"], ref_tone["dsp1"], "dsp1")
    _approx_equal(tone["controller"], ref_tone["controller"], "controller")
    _approx_equal(tone["footswitch"], ref_tone["footswitch"], "footswitch")
    for i in range(4):
        _approx_equal(tone[f"snapshot{i}"], ref_tone[f"snapshot{i}"], f"snapshot{i}")
    # @cursor_group (cursor position in the official editor) is not in the
    # blob: compare everything else of the global node.
    glob = dict(tone["global"])
    ref_glob = dict(ref_tone["global"])
    glob.pop("@cursor_group"), ref_glob.pop("@cursor_group")
    _approx_equal(glob, ref_glob, "global")


def test_to_pgp_tras_editar():
    ed = _editor()
    slot = _slot_of(ed.preset, 366)
    ed.set_param(slot, 0, 0.55)
    out = ed.to_pgp(name="BassPreset")
    blocks = out["data"]["tone"]["dsp0"]
    edited = next(
        b for b in blocks.values()
        if isinstance(b, dict) and b.get("@model") == "HD2_DM4TubeDrive"
    )
    assert edited["Drive"] == pytest.approx(0.55)


# --- to_blob ---


def test_to_blob_round_trip():
    ed = _editor("spec02_knob.bin")
    blob = ed.to_blob()
    back = l6helix.parse_blob(blob)
    assert back.body == ed.body
    assert len(back.chain) == len(ed.preset.chain)


def test_to_blob_tras_editar():
    ed = _editor("spec02_knob.bin")
    ed.set_param(2, 0, 0.5)  # Tube Drive Drive at 50%
    blob = ed.to_blob()
    back = l6helix.parse_blob(blob)
    assert back.body == ed.body  # edit persisted
    drive_param = back.chain[2].params[0]
    assert drive_param == 0.5


def test_to_blob_container_valido():
    ed = _editor("spec02_knob.bin")
    blob = ed.to_blob()
    from openpodgo.l6helix import split_container
    offsets, body_bytes = split_container(blob)
    assert len(offsets) >= 2, "expected at least start + end offset"
    assert body_bytes, "the body must not be empty"


# --- block_index ---


def test_block_index():
    ed = _editor("spec02_knob.bin")
    # BassPreset: slot 0=VolPan, 1=Wah, 2=TubeDrive, ..., 8=Growler, 9=empty.
    # The device addresses by the RAW INDEX in DSP_CHAIN, with INPUT at
    # position 0; that's why block_index(slot) = slot + 1 in this chain.
    # (Confirmed against the pedal: set_param k98=3 changes the TubeDrive.)
    assert ed.block_index(0) == 1   # raw idx 1 (raw 0 = INPUT)
    assert ed.block_index(2) == 3   # raw idx 3 = TubeDrive
    assert ed.block_index(8) == 9   # raw idx 9 = Growler


def test_block_index_empty_slot():
    ed = _editor("spec02_knob.bin")
    with pytest.raises(ValueError, match="empty"):
        ed.block_index(9)  # empty slot


def test_block_index_out_of_range():
    ed = _editor("spec02_knob.bin")
    with pytest.raises(ValueError, match="out of range"):
        ed.block_index(99)


# --- move_block ---


def _chain_ids(pre) -> list:
    return [None if b is None else b.model_id for b in pre.chain]


def test_move_block_reorders_the_chain():
    ed = _editor("spec02_knob.bin")
    before = _chain_ids(ed.preset)
    moved = before[0]
    ed.move_block(0, 3)
    after = _chain_ids(ed.preset)
    # block 0 lands at slot 3; the middle ones shift left.
    assert after == [before[1], before[2], before[3], moved, *before[4:]]


def test_move_block_remaps_footswitch():
    ed = _editor("spec02_knob.bin")
    assign = ed.bypass_assignments()
    # In the fixture, slot 1 is assigned to the EXP toe.
    assert assign[1] == "EXP Toe"
    ed.move_block(1, 6)
    after = ed.bypass_assignments()
    # The assignment follows the block to its new position (slot 6).
    assert after.get(6) == "EXP Toe"
    assert 1 not in after or after[1] != "EXP Toe"


def test_move_block_remaps_snapshots():
    ed = _editor("spec02_knob.bin")
    before = list(ed.preset.snapshots[0].enables)
    # enables = [input, 10 blocks, output]; block at slot s is at index s+1.
    blocks_before = before[1:11]
    ed.move_block(1, 6)
    after = ed.preset.snapshots[0].enables
    blocks_after = after[1:11]
    expected = blocks_before[:1] + blocks_before[2:7] + blocks_before[1:2] + blocks_before[7:]
    assert blocks_after == expected
    assert after[0] == before[0] and after[11] == before[11]  # input/output intact


def test_move_block_preserva_export_pgp():
    ed = _editor("spec02_knob.bin")
    moved_id = ed.preset.chain[2].model_id
    ed.move_block(2, 5)
    out = ed.to_pgp(name="Movido")
    # The moved block appears at its new @position with its params intact.
    block = out["data"]["tone"]["dsp0"]["block5"]
    assert block["@position"] == 5
    back = l6helix.parse_blob(ed.to_blob())
    assert back.chain[5].model_id == moved_id


def test_move_block_noop_misma_posicion():
    ed = _editor("spec02_knob.bin")
    before = _chain_ids(ed.preset)
    ed.move_block(2, 2)
    assert _chain_ids(ed.preset) == before
    assert not ed.can_undo()  # no undo step generated


def test_move_block_undo():
    ed = _editor("spec02_knob.bin")
    before = _chain_ids(ed.preset)
    ed.move_block(0, 4)
    assert _chain_ids(ed.preset) != before
    assert ed.undo()
    assert _chain_ids(ed.preset) == before


def test_move_block_empty_slot_fails():
    ed = _editor("spec02_knob.bin")
    with pytest.raises(ValueError, match="empty"):
        ed.move_block(9, 2)  # slot 9 is empty


def test_move_block_out_of_range():
    ed = _editor("spec02_knob.bin")
    with pytest.raises(ValueError, match="out of range"):
        ed.move_block(0, 99)


# --- bypass / controller assignments (spec 09) ---
#
# Slots from fixture spec02_knob: 0=VolPan, 1=Wah, 2=TubeDrive, 3=AutoFilter,
# 4=FXLoop, 5=Amp, 6=Cab, 7=ParametricEQ, 8=Growler, 9=empty.


def _pgp_footswitch(ed):
    return ed.to_pgp(name="x")["data"]["tone"]["footswitch"]["dsp0"]


def _pgp_controller(ed):
    return ed.to_pgp(name="x")["data"]["tone"]["controller"]["dsp0"]


def test_bypass_target_lee():
    ed = _editor()
    assert ed.bypass_target(2) == "FS4"   # Tube Drive
    assert ed.bypass_target(0) == "EXP Toe"  # Volume
    assert ed.bypass_target(5) is None    # Amp, no assignment


def test_bypass_blocks_on():
    ed = _editor()
    # Toe switch group: Conductor (slot1) and Volume (slot0), in that order.
    assert ed.bypass_blocks_on("EXP Toe") == [1, 0]
    assert ed.bypass_blocks_on("FS4") == [2]
    assert ed.bypass_blocks_on("FS8") == []


def test_footswitch_label_y_color():
    ed = _editor()
    assert ed.footswitch_label(2) == "Tube Drive"
    assert ed.footswitch_color(2) == 525824
    assert ed.footswitch_label(5) is None


def test_controller_assignment_lee():
    ed = _editor()
    a = ed.controller_assignment(1, 0)  # Wah, Pedal → EXP 1
    assert a == {"source": "EXP 1", "num": 1, "min": 0.0, "max": 1.0}
    b = ed.controller_assignment(0, 0)  # Volume, Pedal → EXP 2
    assert b["source"] == "EXP 2" and b["num"] == 2
    assert ed.controller_assignment(2, 0) is None  # Tube Drive sin controller


def test_set_bypass_assign_mueve():
    ed = _editor()
    ed.set_bypass_assign(2, "FS3")  # Tube Drive: FS4 → FS3
    assert ed.bypass_target(2) == "FS3"
    assert ed.bypass_blocks_on("FS4") == []
    assert _pgp_footswitch(ed)["block2"]["@fs_index"] == 3


def test_set_bypass_assign_bloque_nuevo():
    ed = _editor()
    ed.set_bypass_assign(5, "FS3")  # Amp, previously unassigned
    assert ed.bypass_target(5) == "FS3"
    fs = _pgp_footswitch(ed)["block5"]
    assert fs["@fs_index"] == 3
    assert fs["@fs_label"] == "G Cougar 800"
    assert fs["@fs_primary"] is True


def test_set_bypass_assign_compartido():
    ed = _editor()
    ed.set_bypass_assign(5, "FS4")  # shares FS4 with Tube Drive (slot 2)
    assert ed.bypass_blocks_on("FS4") == [2, 5]
    # El segundo en el grupo no es primario.
    assert "@fs_primary" not in _pgp_footswitch(ed)["block5"]


def test_clear_bypass_assign():
    ed = _editor()
    ed.clear_bypass_assign(2)
    assert ed.bypass_target(2) is None
    assert "block2" not in _pgp_footswitch(ed)


def test_set_fs_label_y_reset():
    ed = _editor()
    ed.set_fs_label(2, "Boost")
    assert ed.footswitch_label(2) == "Boost"
    assert _pgp_footswitch(ed)["block2"]["@fs_label"] == "Boost"
    ed.reset_fs_label(2)
    assert ed.footswitch_label(2) == "Tube Drive"


def test_set_fs_color_index():
    ed = _editor()
    # Default is Auto (key 15 False, index 0).
    assert ed.footswitch_color_index(2) == 0
    ed.set_fs_color_index(2, 2)  # Red
    assert ed.footswitch_color_index(2) == 2
    # Back to Auto clears the custom flag.
    ed.set_fs_color_index(2, 0)
    assert ed.footswitch_color_index(2) == 0


def test_set_fs_color_index_out_of_range():
    ed = _editor()
    with pytest.raises(ValueError, match="out of range"):
        ed.set_fs_color_index(2, 99)


def test_set_fs_label_no_assignment_fails():
    ed = _editor()
    with pytest.raises(ValueError, match="has no bypass assignment"):
        ed.set_fs_label(5, "Nope")


def test_per_footswitch_operations():
    # FS4 has a single block (Tube Drive, slot 2).
    ed = _editor()
    assert ed.footswitch_label_for("FS4") == "Tube Drive"
    assert ed.footswitch_color_index_for("FS4") == 0  # Auto
    ed.set_fs_label_for("FS4", "Boost")
    assert ed.footswitch_label(2) == "Boost"
    ed.set_fs_color_index_for("FS4", 2)  # Red
    assert ed.footswitch_color_index(2) == 2
    ed.reset_fs_label_for("FS4")
    assert ed.footswitch_label(2) == "Tube Drive"


def test_footswitch_label_for_multiple():
    # The toe switch has two blocks (Volume + Conductor) with different labels.
    ed = _editor()
    assert ed.footswitch_label_for("EXP Toe") == "Multiple"


def test_fs_color_for_applies_to_all_blocks():
    # Sharing FS3 with two blocks and giving it a color: both change.
    ed = _editor()
    ed.set_bypass_assign(2, "FS3")
    ed.set_bypass_assign(5, "FS3")
    ed.set_fs_color_index_for("FS3", 6)  # Green
    assert ed.footswitch_color_index(2) == 6
    assert ed.footswitch_color_index(5) == 6


def test_set_fs_label_for_no_assignment_fails():
    ed = _editor()
    with pytest.raises(ValueError, match="has no assignments"):
        ed.set_fs_label_for("FS8", "Nope")


def test_bypass_assign_undo():
    ed = _editor()
    ed.set_bypass_assign(2, "FS3")
    ed.undo()
    assert ed.bypass_target(2) == "FS4"


def test_set_controller_min_max():
    ed = _editor()
    ed.set_controller_min_max(1, 0, 0.2, 0.8)
    a = ed.controller_assignment(1, 0)
    assert a["min"] == pytest.approx(0.2) and a["max"] == pytest.approx(0.8)
    pgp = _pgp_controller(ed)["block1"]["Pedal"]
    assert pgp["@min"] == pytest.approx(0.2)
    assert pgp["@max"] == pytest.approx(0.8)


def test_clear_controller_assign():
    ed = _editor()
    ed.clear_controller_assign(1, 0)  # Wah, Pedal (EXP 1)
    assert ed.controller_assignment(1, 0) is None
    assert "block1" not in _pgp_controller(ed)
    # El otro controller (Volume/EXP 2) sigue exportando bien.
    assert "block0" in _pgp_controller(ed)


def test_clear_controller_undo():
    ed = _editor()
    ed.clear_controller_assign(1, 0)
    ed.undo()
    assert ed.controller_assignment(1, 0) is not None


def test_set_controller_assign_re_bloqueado():
    ed = _editor()
    with pytest.raises(editor.ControllerAssignUnsupported):
        ed.set_controller_assign(2, 0, "EXP 1")  # Tube Drive: RE-blocked


# --- from_pgp roundtrip ---


def test_from_pgp_roundtrip_a(preset_a):
    from openpodgo.preset import load_pgp

    pgp = load_pgp(preset_a)
    ed, warnings = editor.PresetEditor.from_pgp(pgp)
    assert not warnings, f"Unexpected warnings: {warnings}"
    rebuilt = ed.to_pgp("test")
    _assert_pgp_equivalent(rebuilt, pgp)


def _assert_pgp_equivalent(a: dict, b: dict):
    ta = a["data"]["tone"]
    tb = b["data"]["tone"]

    def normalize(v):
        if isinstance(v, float):
            import struct
            return struct.unpack("<f", struct.pack("<f", v))[0]
        return v

    def blocks(tone):
        return sorted(
            (k, v) for k, v in tone["dsp0"].items()
            if k.startswith("block")
        )

    for (ka, va), (kb, vb) in zip(blocks(ta), blocks(tb)):
        assert ka == kb, f"block key mismatch: {ka} vs {kb}"
        for key in va:
            if key.startswith("@"):
                continue
            assert key in vb, f"param {key} missing in rebuilt {ka}"
            assert normalize(va[key]) == normalize(vb[key]), (
                f"{ka}.{key}: {va[key]} vs {vb[key]}"
            )


def test_from_pgp_full_roundtrip(preset_a):
    """Full round-trip: .pgp → body → .pgp, verifies ALL sections."""
    from openpodgo.preset import load_pgp

    pgp = load_pgp(preset_a)
    ed, warnings = editor.PresetEditor.from_pgp(pgp)
    assert not warnings, f"Unexpected warnings: {warnings}"
    rebuilt = ed.to_pgp("test")
    ta = rebuilt["data"]["tone"]
    tb = pgp["data"]["tone"]
    _assert_footswitch_equivalent(ta, tb)
    _assert_controllers_equivalent(ta, tb)
    _assert_snapshots_equivalent(ta, tb)
    _assert_global_equivalent(ta, tb)


def _assert_footswitch_equivalent(ta: dict, tb: dict):
    fa = ta.get("footswitch", {}).get("dsp0", {})
    fb = tb.get("footswitch", {}).get("dsp0", {})
    for bk, entry in fa.items():
        assert bk in fb, f"footswitch block {bk} missing"
        for key in ("@fs_enabled", "@fs_index", "@fs_label",
                     "@fs_ledcolor", "@fs_momentary"):
            assert entry.get(key) == fb[bk].get(key), (
                f"footswitch {bk}.{key}: {entry.get(key)} vs {fb[bk].get(key)}"
            )


def _assert_controllers_equivalent(ta: dict, tb: dict):
    ca = ta.get("controller", {}).get("dsp0", {})
    cb = tb.get("controller", {}).get("dsp0", {})
    assert ca.keys() == cb.keys(), (
        f"controller blocks differ: {set(ca)} vs {set(cb)}"
    )
    for bk in ca:
        for pname, ctl_a in ca[bk].items():
            ctl_b = cb[bk][pname]
            for key in ("@controller", "@min", "@max"):
                assert ctl_a.get(key) == ctl_b.get(key), (
                    f"controller {bk}.{pname}.{key}: "
                    f"{ctl_a.get(key)} vs {ctl_b.get(key)}"
                )


def _assert_snapshots_equivalent(ta: dict, tb: dict):
    for i in range(4):
        sk = f"snapshot{i}"
        sa = ta.get(sk, {})
        sb = tb.get(sk, {})
        for key in ("@name", "@valid", "@tempo", "@pedalstate", "@ledcolor"):
            assert sa.get(key) == sb.get(key), (
                f"snapshot{i}.{key}: {sa.get(key)} vs {sb.get(key)}"
            )
        ba = sa.get("blocks", {}).get("dsp0", {})
        bb = sb.get("blocks", {}).get("dsp0", {})
        assert ba.keys() == bb.keys(), (
            f"snapshot{i} blocks keys differ: {set(ba)} vs {set(bb)}"
        )
        for bk in ba:
            assert ba[bk] == bb.get(bk), (
                f"snapshot{i} block {bk} enable: {ba[bk]} vs {bb.get(bk)}"
            )
        ca = sa.get("controllers", {}).get("dsp0", {})
        cb = sb.get("controllers", {}).get("dsp0", {})
        for bk in ca:
            for pname, va in ca[bk].items():
                vb = cb.get(bk, {}).get(pname, {})
                for ck in ("@fs_enabled", "@value"):
                    assert va.get(ck) == vb.get(ck), (
                        f"snapshot{i} {bk}.{pname}.{ck}: "
                        f"{va.get(ck)} vs {vb.get(ck)}"
                    )


def _assert_global_equivalent(ta: dict, tb: dict):
    ga = ta.get("global", {})
    gb = tb.get("global", {})
    for key in ("@current_snapshot", "@tempo", "@pedalstate"):
        assert ga.get(key) == gb.get(key), (
            f"global.{key}: {ga.get(key)} vs {gb.get(key)}"
        )


def test_from_pgp_unknown_model():
    """Unknown model → empty slot + warning."""
    pgp = {
        "schema": "L6Preset",
        "version": 6,
        "meta": {"original": 0, "pbn": 0, "premium": 0},
        "data": {
            "device": 2162695,
            "device_version": 33619968,
            "meta": {"application": "POD Go Edit", "appversion": 33554432,
                     "name": "Test", "modifieddate": 0},
            "tone": {
                "controller": {"dsp0": {}},
                "dsp0": {
                    "input": {"@input": 0, "@model": "P34_AppDSPFlowInput",
                              "noiseGate": True, "threshold": -60.0, "decay": 0.05},
                    "block0": {"@position": 0, "@model": "FAKE_UnknownModel99",
                               "@enabled": True, "UnknownParam": 0.5},
                    "output": {"@model": "P34_AppDSPFlowOutput", "@output": 0,
                               "pan": 0.5, "gain": 0.0},
                },
                "dsp1": {},
                "footswitch": {"dsp0": {}},
                "global": {"@current_snapshot": 0, "@tempo": 120.0,
                           "@pedalstate": 0},
            },
        },
    }
    ed, warnings = editor.PresetEditor.from_pgp(pgp)
    assert "FAKE_UnknownModel99" in warnings, f"Expected warning, got {warnings}"
    assert ed.preset.chain[0] is None, "Unknown model should become empty slot"


def test_from_pgp_roundtrip_preset2(preset_two):
    """Round-trip with the Preset Two fixture (2nd .pgp)."""
    from openpodgo.preset import load_pgp

    pgp = load_pgp(preset_two)
    ed, warnings = editor.PresetEditor.from_pgp(pgp)
    assert not warnings, f"Unexpected warnings: {warnings}"
    rebuilt = ed.to_pgp("test")
    ta = rebuilt["data"]["tone"]
    tb = pgp["data"]["tone"]
    _assert_footswitch_equivalent(ta, tb)
    _assert_controllers_equivalent(ta, tb)
    _assert_snapshots_equivalent(ta, tb)
    _assert_global_equivalent(ta, tb)
