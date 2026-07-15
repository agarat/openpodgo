"""Parser for POD Go Edit .pgb backup files (AF6L container with zlib streams).

Fixture: the most recent backup (post-v2.01 update), the only one
containing presets with build_sha v2.01-19-g6e98447.
"""

from pathlib import Path

import pytest

from openpodgo import pgb

BACKUP = (
    Path(__file__).parent.parent
    / "captures" / "win-captures" / "POD Go Backup 2026-Jun-11(2).pgb"
)

# Device backups contain the owner's full preset library and are NOT shipped.
# This module only runs where such a backup is present locally.
pytestmark = pytest.mark.skipif(
    not BACKUP.exists(), reason="device backup (.pgb) not present"
)


@pytest.fixture(scope="module")
def backup():
    return pgb.read_backup(BACKUP)


def test_complete_setlists(backup):
    assert set(backup.setlists) == {"Factory", "User"}
    assert len(backup.setlists["Factory"]) == 128
    assert len(backup.setlists["User"]) == 128


def test_presets_are_l6preset(backup):
    p0 = backup.setlists["Factory"][0]
    assert p0["meta"]["name"] == "US Deluxe Nrm"
    assert "dsp0" in p0["tone"]
    # User slot 9 is the BassPreset from the specs.
    assert backup.setlists["User"][9]["meta"]["name"] == "BassPreset"


def test_globals(backup):
    assert "System" in backup.globals


def test_not_a_backup():
    with pytest.raises(ValueError):
        pgb.read_backup(Path(__file__))  # a .py file doesn't have AF6L magic


# --- model extraction ---


@pytest.fixture(scope="module")
def models(backup):
    return pgb.extract_models(backup)


def test_model_coverage(models):
    # The backup (Factory + User) covers the vast majority of the POD Go catalog.
    assert len(models) >= 230


def test_known_model_params(models):
    m = models["HD2_DM4TubeDrive"]
    assert set(m.params) == {"Drive", "Bass", "Mid", "Treble", "Output"}
    assert set(m.defaults) == set(m.params)


def test_at_sign_extras_as_params(models):
    # @trails/@mic are block attributes in the JSON but params in the blob
    # (convention documented in catalog.py): extracted as params.
    assert "@trails" in models["HD2_FXLoopMono1"].params
    assert "@mic" in models["HD2_Cab4x10Rhino"].params


def test_real_ranges(models):
    # Controllers carry @min/@max and observed values extend them:
    # FcHigh of the wah reaches at least the value seen in Factory (2155 Hz).
    fchigh = models["HD2_WahFasselStereo"].params["FcHigh"]
    assert fchigh.vmax >= 2155.0
    assert fchigh.vmin < fchigh.vmax


def test_bools_detected(models):
    assert models["HD2_VolPanVolStereo"].params["VolumeTaper"].is_bool
    assert not models["HD2_WahFasselStereo"].params["FcHigh"].is_bool


def test_params_consistent_across_presets(backup):
    # The same model always appears with the same param set; if not,
    # extract_models must fail (signal of mixed data from another firmware).
    pgb.extract_models(backup)  # no debe lanzar


def test_input_output_present(models):
    # The input/output blocks also have a model and named params.
    assert any(n.startswith("P34_AppDSPFlowInput") for n in models)
