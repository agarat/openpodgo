"""Tests for the l6-helix container decoder (spec 02 Phase B).

Real fixtures from captures/ (see docs/specs/02-lab-notes.md):
- spec02_a.bin: message {102,103,104} from object 22 with "BassPreset" (Drive 0.42).
- spec02_obj22_blob.bin: the blob (key 104) from that same message, already extracted.
"""

from pathlib import Path

import msgpack
import pytest

from openpodgo import l6helix

CAPS = Path(__file__).parent / "fixtures"


def test_extract_blob_from_obj22_message():
    blob = l6helix.extract_blob((CAPS / "spec02_a.bin").read_bytes())
    assert blob == (CAPS / "spec02_obj22_blob.bin").read_bytes()
    assert len(blob) == 3823


def test_extract_blob_rejects_status_error():
    # Real form of a device error (lab-notes E2): status 255, code -3.
    msg = msgpack.packb({102: 1002, 103: 255, 104: {111: -3}})
    with pytest.raises(l6helix.DeviceStatusError) as exc:
        l6helix.extract_blob(msg)
    assert "-3" in str(exc.value)


def test_split_container_offsets():
    blob = (CAPS / "spec02_obj22_blob.bin").read_bytes()
    offsets, body = l6helix.split_container(blob)
    assert len(offsets) == 12
    assert offsets[0] == 0x3D  # the first one points to the body start
    # the body is a complete MessagePack map, no leftover bytes
    assert isinstance(
        msgpack.unpackb(body, raw=False, strict_map_key=False), dict
    )


def test_split_container_invalid_magic():
    fake = msgpack.packb("not-helix\x00") + b"\x00" * 8
    with pytest.raises(ValueError):
        l6helix.split_container(fake)


# --- parse_blob: dataclasses on real dumps ---


def _preset(bin_name: str) -> "l6helix.Preset":
    return l6helix.parse_blob(
        l6helix.extract_blob((CAPS / bin_name).read_bytes())
    )


def test_parse_blob_chain_basspreset():
    # Expected chain per lab-notes: vol, wah, tube drive, autofilter,
    # fx loop, amp, cab, parametric eq, growler, empty slot.
    p = _preset("spec02_a.bin")
    assert [b.model_id if b else None for b in p.chain] == [
        224, 238, 366, 255, 119, 3, 60, 472, 371, None,
    ]
    assert [b.enabled for b in p.chain if b] == [
        True, False, False, False, False, True, True, False, False,
    ]
    assert all(b.no_snapshot_bypass is False for b in p.chain if b)
    # categories by slot type: 17=amp, 15=cab, 23=static EQ, 9=fx loop
    assert p.chain[5].category == 17
    assert p.chain[6].category == 15
    assert p.chain[7].category == 23
    assert p.chain[4].category == 9


def test_parse_blob_params_tube_drive():
    # spec02_a.bin is the dump with Drive=0.42 (BEFORE moving the knob).
    p = _preset("spec02_a.bin")
    drive = p.chain[2]
    assert drive.params == pytest.approx(
        [0.42, 0.66, 0.5, 0.5, 0.77], abs=1e-6
    )


def test_parse_blob_meta_and_global():
    p = _preset("spec02_a.bin")
    assert p.product == "P34"
    assert p.firmware == "v2.00-5-g665e64e"
    assert p.tempo == 120.0
    # the full map remains accessible for keys not yet decoded
    assert set(p.body) >= {0, 3, 4, 5, 7, 10}


def test_parse_blob_snapshots():
    p = _preset("spec02_a.bin")
    assert p.current_snapshot == 0
    assert [s.name for s in p.snapshots] == [
        "SNAPSHOT 1", "SNAPSHOT 2", "SNAPSHOT 3", "SNAPSHOT 4",
    ]
    assert [s.valid for s in p.snapshots] == [True, False, False, False]
    s0 = p.snapshots[0]
    assert s0.tempo == 120.0
    # 12 chain slots: [input, 10 blocks, output]
    assert s0.enables == [
        True, True, False, False, False, False,
        True, True, False, False, True, True,
    ]


def test_parse_blob_input_output():
    # input: [noiseGate, threshold, decay]; output: [pan, gain]
    p = _preset("spec02_a.bin")
    assert p.input_params == [False, -48.0, 0.5]
    assert p.output_params == [0.5, 0.0]


def test_parse_blob_preset2():
    p = _preset("spec02_preset2.bin")
    assert [b.model_id if b else None for b in p.chain] == [
        119, 224, 239, 88, 95, 404, 334, 30, 67, 472,
    ]
    assert p.chain[7].enabled is True  # Mandarin80 amp
    assert len(p.chain[7].params) == 13


def test_blobs_equal_normalized_identical():
    blob = (CAPS / "spec02_obj22_blob.bin").read_bytes()
    assert l6helix.blobs_equal_normalized(blob, blob) is True


def test_blobs_equal_normalized_reserialized():
    # Same content, different bytes (build_blob uses minimal encoding): must
    # compare EQUAL despite not being byte-for-byte (key order / encoding).
    blob = (CAPS / "spec02_obj22_blob.bin").read_bytes()
    _, body_bytes = l6helix.split_container(blob)
    body = msgpack.unpackb(body_bytes, raw=False, strict_map_key=False)
    rebuilt = l6helix.build_blob(body)
    assert rebuilt != blob
    assert l6helix.blobs_equal_normalized(blob, rebuilt) is True


def test_blobs_equal_normalized_mutated_param():
    # Changing a block parameter ⇒ NOT equal (this is "edited").
    blob = (CAPS / "spec02_obj22_blob.bin").read_bytes()
    _, body_bytes = l6helix.split_container(blob)
    body = msgpack.unpackb(body_bytes, raw=False, strict_map_key=False)
    for entry in body[0][22]:
        if entry.get(19) == 6:  # CLASS_BLOCK
            entry[20][11][4][0] = 99.0  # first param value of the block
            break
    else:
        raise AssertionError("no block found to mutate")
    mutated = l6helix.build_blob(body)
    assert l6helix.blobs_equal_normalized(blob, mutated) is False


def test_parse_blob_unknown_class():
    # A new entry class must fail loudly, not silently drop slots.
    body = msgpack.packb(
        {0: {21: 0, 22: [{19: 99, 20: None}]}}, use_bin_type=True
    )
    table = b"\xda\x00\x04" + b"\x00" * 4
    blob = msgpack.packb("l6-helix\x00") + table + body
    with pytest.raises(ValueError, match="unknown class"):
        l6helix.parse_blob(blob)
