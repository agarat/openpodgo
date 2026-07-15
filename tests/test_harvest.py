"""Harvesting wire_id/category/param order by cross-checking blob ↔ .pgp.

The two fixture↔official-export pairs must exactly reproduce the 16
models hand-seeded in catalog.MODELS (same ids and, where the value cross-check
reaches, same param order).
"""

import json
from pathlib import Path

import pytest

from openpodgo import catalog, harvest, l6helix

CAPS = Path(__file__).parent / "fixtures"

PAIRS = [
    ("spec02_knob.bin", "spec02_a.pgp"),
    ("spec02_preset2.bin", "spec02_preset2.pgp"),
]


@pytest.fixture()
def acc() -> harvest.Accumulator:
    acc = harvest.Accumulator()
    for bin_name, pgp_name in PAIRS:
        pre = l6helix.parse_blob(
            l6helix.extract_blob((CAPS / bin_name).read_bytes())
        )
        pgp = json.loads((CAPS / pgp_name).read_text(encoding="utf-8"))
        warnings = acc.add_preset(pre, pgp["data"]["tone"])
        assert warnings == []
    return acc


def test_wire_ids_and_categories(acc):
    resolved = acc.resolved()
    expected_ids = {md.name: mid for mid, md in catalog.MODELS.items()}
    assert {r.name: r.wire_id for r in resolved.values()} == expected_ids
    # Known categories from lab-notes.
    assert resolved["HD2_AmpGCougar800"].category == 17
    assert resolved["HD2_Cab4x10Rhino"].category == 15
    assert resolved["HD2_DL4DigDelay"].category == 8
    assert resolved["HD2_FXLoopMono1"].category == 9
    assert resolved["HD2_EQ_STATIC_ParametricStereo"].category == 23


def test_param_order_resolved(acc):
    # Where the value cross-check resolves the full order, it must
    # match the hand-seeded one (which came from these same pairs).
    resolved = acc.resolved()
    seeded = {md.name: list(md.params) for md in catalog.MODELS.values()}
    completos = {
        r.name: r.param_order for r in resolved.values()
        if r.param_order is not None
    }
    assert completos  # at least some models are fully resolved
    for name, order in completos.items():
        assert order == seeded[name], name


def test_id_conflict_detected(acc):
    pre = l6helix.parse_blob(
        l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    )
    pgp = json.loads((CAPS / "spec02_a.pgp").read_text(encoding="utf-8"))
    tone = pgp["data"]["tone"]
    # Tamper with a block name: same on-wire id with a different name.
    for blk in tone["dsp0"].values():
        if blk.get("@model") == "HD2_DM4TubeDrive":
            blk["@model"] = "HD2_DistMinotaurMono"
    with pytest.raises(harvest.HarvestConflict):
        acc.add_preset(pre, tone)


def test_misaligned_preset_warns_and_continues():
    # If the blob and JSON don't match (different chain), a warning is issued and it doesn't break.
    acc = harvest.Accumulator()
    pre = l6helix.parse_blob(
        l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    )
    pgp = json.loads((CAPS / "spec02_preset2.pgp").read_text(encoding="utf-8"))
    warnings = acc.add_preset(pre, pgp["data"]["tone"])
    assert warnings  # different preset chains: nothing matches cleanly
