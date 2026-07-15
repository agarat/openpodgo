"""Offline tests for "preset edited" detection (spec 06, Task 1).

They cover the HONEST SEAM: while the object 14 formula is not confirmed live
(`_OBJ14_CRC_CONFIRMED = False`), `active_preset_is_edited` returns a
conservative False and DOESN'T EVEN read object 14 / 22. The crc-vs-object-14
comparison is gated behind that constant and is tested through its pure helper,
without USB.
"""

import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openpodgo import device, preset

CAPS = Path(__file__).parent / "fixtures"


def _fake_podgo():
    """PodGo with a simulated session (connected=True) without touching USB."""
    pg = device.PodGo.__new__(device.PodGo)
    pg._session = MagicMock()
    pg._session.is_open = True
    pg._read_since_write = False
    return pg


# --- Finding A: crc32-over-blob is NOT the object 14 formula ---

def test_finding_a_crc32_blob_no_esta_en_objeto14():
    """Documents/guards Finding A: no crc32 variant of the object 22 blob
    matches a slot from object 14 (real captures)."""
    blob = (CAPS / "spec02_obj22_blob.bin").read_bytes()
    obj14 = (CAPS / "spec02_obj14.bin").read_bytes()
    nonempty = [c for c in preset.parse_slot_checksums(obj14).values() if c is not None]
    assert len(nonempty) == 120  # 120 non-empty slots in the capture
    assert (zlib.crc32(blob) & 0xFFFFFFFF) not in set(nonempty)


def test_blob_crc_for_obj14_es_crc32_actual():
    blob = (CAPS / "spec02_obj22_blob.bin").read_bytes()
    assert device._blob_crc_for_obj14(blob) == (zlib.crc32(blob) & 0xFFFFFFFF)


# --- Pure comparison helper (gated by the constant, reliable only if True) ---

def test_crc_says_edited_distinto_es_editado():
    blob = b"contenido"
    distinto = (zlib.crc32(blob) & 0xFFFFFFFF) ^ 0xFFFF
    assert device._crc_says_edited(blob, distinto) is True


def test_crc_says_edited_igual_no_es_editado():
    blob = b"contenido"
    igual = zlib.crc32(blob) & 0xFFFFFFFF
    assert device._crc_says_edited(blob, igual) is False


# --- Gating: while the constant is False, no false positive is risked ---

def test_constante_arranca_en_false():
    # The seam starts disabled: the object 14 formula is not confirmed.
    assert device._OBJ14_CRC_CONFIRMED is False


def test_is_edited_gateado_devuelve_false_sin_leer_nada(monkeypatch):
    """With the constant set to False: returns False and does NOT spend USB reads."""
    monkeypatch.setattr(device, "_OBJ14_CRC_CONFIRMED", False)
    leyo = {"state": False, "checksums": False, "objeto": False}
    monkeypatch.setattr(
        preset, "read_active_state",
        lambda s: leyo.__setitem__("state", True)
        or preset.ActiveState(setlist=0, slot=7, name="X"),
    )
    monkeypatch.setattr(
        preset, "read_slot_checksums",
        lambda *a, **k: leyo.__setitem__("checksums", True) or {},
    )
    monkeypatch.setattr(
        preset, "read_object",
        lambda *a, **k: leyo.__setitem__("objeto", True) or b"",
    )
    pg = _fake_podgo()
    assert pg.active_preset_is_edited() is False
    assert leyo == {"state": False, "checksums": False, "objeto": False}


def test_is_edited_habilitado_alcanza_la_comparacion_crc(monkeypatch):
    """With the constant set to True: the crc-vs-object-14 path is reachable."""
    monkeypatch.setattr(device, "_OBJ14_CRC_CONFIRMED", True)
    blob = (CAPS / "spec02_obj22_blob.bin").read_bytes()
    stored_distinto = (device._blob_crc_for_obj14(blob) ^ 0x1) & 0xFFFFFFFF
    monkeypatch.setattr(
        preset, "read_active_state",
        lambda s: preset.ActiveState(setlist=0, slot=7, name="X"),
    )
    monkeypatch.setattr(preset, "read_slot_checksums",
                        lambda *a, **k: {7: stored_distinto})
    # read_object returns the MESSAGE; extract_blob extracts the blob. We return a
    # real message built from the capture so as not to fake extract_blob.
    msg = (CAPS / "spec02_obj22.bin").read_bytes()
    monkeypatch.setattr(preset, "read_object", lambda *a, **k: msg)
    pg = _fake_podgo()
    # blob crc != stored stamp ⇒ edited.
    assert pg.active_preset_is_edited() is True


def test_is_edited_habilitado_slot_sin_sello_es_false(monkeypatch):
    """With the constant set to True but the slot has no stamp in object 14: False."""
    monkeypatch.setattr(device, "_OBJ14_CRC_CONFIRMED", True)
    monkeypatch.setattr(
        preset, "read_active_state",
        lambda s: preset.ActiveState(setlist=0, slot=99, name="X"),
    )
    monkeypatch.setattr(preset, "read_slot_checksums", lambda *a, **k: {0: 123})
    msg = (CAPS / "spec02_obj22.bin").read_bytes()
    monkeypatch.setattr(preset, "read_object", lambda *a, **k: msg)
    pg = _fake_podgo()
    assert pg.active_preset_is_edited() is False
