"""Tests for backup and restore (.pgb) and preset archive (.zip) operations.

Covers TDD contract for writing and reading .pgb containers and .zip bundles.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openpodgo import pgb

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_preset() -> dict:
    pgp_file = FIXTURES / "spec02_a.pgp"
    if pgp_file.exists():
        data = json.loads(pgp_file.read_bytes())
        return data["data"]
    return {
        "device": 2162695,
        "device_version": 33619968,
        "meta": {"name": "TestTone", "application": "openpodgo"},
        "tone": {"dsp0": {}, "global": {}},
    }


def test_write_and_read_backup_roundtrip(tmp_path: Path, sample_preset: dict):
    """Writing a Backup object to a .pgb produces a valid AF6L container that read_backup can load."""
    out_file = tmp_path / "device_backup.pgb"
    globals_data = {"System": {"device": 2162695, "version": "v2.01"}}
    factory_presets = [dict(sample_preset) for _ in range(4)]
    user_presets = [dict(sample_preset) for _ in range(4)]

    original_backup = pgb.Backup(
        globals=globals_data,
        setlists={
            "Factory": factory_presets,
            "User": user_presets,
        },
    )

    pgb.write_backup(out_file, original_backup)

    assert out_file.exists()
    content = out_file.read_bytes()
    assert content[:4] == pgb.MAGIC

    loaded = pgb.read_backup(out_file)
    assert loaded.globals == globals_data
    assert set(loaded.setlists.keys()) == {"Factory", "User"}
    assert len(loaded.setlists["Factory"]) == 4
    assert len(loaded.setlists["User"]) == 4
    assert loaded.setlists["User"][0]["meta"]["name"] == sample_preset["meta"]["name"]


def test_write_backup_requires_setlists(tmp_path: Path):
    """Attempting to write an empty backup with no setlists raises ValueError."""
    out_file = tmp_path / "empty.pgb"
    empty_backup = pgb.Backup(globals={}, setlists={})
    with pytest.raises(ValueError, match="at least one setlist"):
        pgb.write_backup(out_file, empty_backup)


def test_write_backup_with_irs(tmp_path: Path, sample_preset: dict):
    """IR binary streams in .pgb should be written and preserved without breaking read_backup."""
    out_file = tmp_path / "with_irs.pgb"
    mock_ir_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00data\x00\x00\x00\x00"
    backup = pgb.Backup(
        globals={"System": {}},
        setlists={"User": [sample_preset]},
    )

    pgb.write_backup(out_file, backup, irs=[mock_ir_wav])
    loaded = pgb.read_backup(out_file)
    assert "User" in loaded.setlists
    assert len(loaded.setlists["User"]) == 1


def test_export_and_import_presets_zip_roundtrip(tmp_path: Path, sample_preset: dict):
    """Presets can be exported into a .zip archive of .pgp files and imported back."""
    zip_path = tmp_path / "presets_bundle.zip"
    presets_by_setlist = {
        "Factory": [sample_preset],
        "User": [sample_preset],
    }

    pgb.export_presets_zip(zip_path, presets_by_setlist)
    assert zip_path.exists()

    # Import back from zip
    imported = pgb.import_presets_zip(zip_path)
    assert "Factory" in imported
    assert "User" in imported
    assert len(imported["Factory"]) == 1
    assert len(imported["User"]) == 1
    assert imported["Factory"][0]["meta"]["name"] == sample_preset["meta"]["name"]


def test_export_presets_zip_flat(tmp_path: Path, sample_preset: dict):
    """Presets exported with flat=True (or single setlist) are at archive root without user subfolder."""
    import zipfile

    zip_path = tmp_path / "presets_flat.zip"
    pgb.export_presets_zip(zip_path, {"User": [sample_preset]}, flat=True)
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == 1
        assert not names[0].startswith("user/")
        assert not names[0].startswith("User/")
        assert names[0].startswith("01A_")

    imported = pgb.import_presets_zip(zip_path)
    assert "User" in imported
    assert len(imported["User"]) == 1
    assert imported["User"][0]["meta"]["name"] == sample_preset["meta"]["name"]


def test_import_presets_zip_invalid_file(tmp_path: Path):
    """Importing from a non-zip file raises ValueError."""
    corrupt_file = tmp_path / "bad.zip"
    corrupt_file.write_text("not a zip")
    with pytest.raises(ValueError, match="not a valid zip"):
        pgb.import_presets_zip(corrupt_file)


def test_backup_metadata_and_inspection(tmp_path: Path, sample_preset: dict):
    """Metadata is saved into the .pgb and correctly summarized by inspect_backup."""
    out_file = tmp_path / "metadata_backup.pgb"
    metadata = {
        "date": "2026-10-21",
        "device": "POD Go Wireless",
        "version": "v2.01",
        "description": "Custom concert backup",
    }
    mock_ir = b"RIFFmockwavdata"
    backup = pgb.Backup(
        globals={"System": {"device": 2162695, "version": "v2.01"}},
        setlists={
            "Factory": [sample_preset, sample_preset],
            "User": [sample_preset],
        },
        metadata=metadata,
    )

    pgb.write_backup(out_file, backup, irs=[mock_ir])

    # Test full read
    loaded = pgb.read_backup(out_file)
    assert loaded.metadata == metadata

    # Test inspection without reading all preset contents
    info = pgb.inspect_backup(out_file)
    assert info["date"] == "2026-10-21"
    assert info["device"] == "POD Go Wireless"
    assert info["version"] == "v2.01"
    assert info["description"] == "Custom concert backup"
    assert info["setlists"] == {"Factory": 2, "User": 1}
    assert info["has_globals"] is True
    assert info["ir_count"] == 1


def test_inspect_backup_invalid_file(tmp_path: Path):
    """inspect_backup raises ValueError on non-pgb or malformed files."""
    bad_file = tmp_path / "corrupt.pgb"
    bad_file.write_bytes(b"NOT_A_PGB_FILE")
    with pytest.raises(ValueError, match="not a .pgb backup"):
        pgb.inspect_backup(bad_file)

