"""Cross-checking the decoder + catalog against POD Go Edit .pgp files.

fixture↔reference pairs (spec02_knob.bin, not spec02_a.bin!: the BassPreset
.pgp was exported with Drive=0.47, after moving the knob):
"""

import json
from pathlib import Path

import pytest

from openpodgo import catalog, l6helix

CAPS = Path(__file__).parent / "fixtures"

PAIRS = [
    ("spec02_knob.bin", "spec02_a.pgp"),          # BassPreset, Drive=0.47
    ("spec02_preset2.bin", "spec02_preset2.pgp"),  # Preset Two
]


def test_lookup_unknown():
    assert catalog.lookup(99999) is None


# --- full catalog from the backup (models.json) ---


def test_model_info_known():
    info = catalog.model_info("HD2_DM4TubeDrive")
    assert info is not None
    assert info.wire_id == 366  # merged from the hand-seeded ones
    assert info.param_order == ("Drive", "Bass", "Mid", "Treble", "Output")
    assert set(info.params) == {"Drive", "Bass", "Mid", "Treble", "Output"}
    assert set(info.defaults) == set(info.params)


def test_model_info_unknown():
    assert catalog.model_info("HD2_NoExiste") is None


def test_full_catalog():
    assert len(catalog.model_names()) >= 230


def test_seeded_consistent_with_backup():
    # The 16 hand-seeded models must exist in models.json with
    # exactly the same params (the source is the same .pgp format).
    for md in catalog.MODELS.values():
        info = catalog.model_info(md.name)
        assert info is not None, md.name
        assert set(info.params) == set(md.params), md.name


def test_wire_category_observed_and_inferred():
    # Observed in dumps (1=FX, 17=amp) or inferred from official category
    # validated; None where no data point exists (e.g. dynamics,
    # which isn't in the build's WIRE_CATEGORY map).
    assert catalog.model_info("HD2_DM4TubeDrive").wire_category == 1
    assert catalog.model_info("HD2_AmpGCougar800").wire_category == 17
    assert catalog.model_info("HD2_DistMinotaurMono").wire_category == 1
    assert catalog.model_info("HD2_Compressor3BandCompMono").wire_category is None


def test_eq_effects_wire_category():
    # spec08: the 8 non-STATIC EQs (incl. Acoustic Sim) are on-wire category
    # 1 (they go in an Effects block), confirmed against the pedal
    # (captures/eq_acoustic_sim_obj22.bin). Without this, available_models()
    # filters them out (wire_category None).
    for name in (
        "HD2_CaliQStereo", "HD2_EQGraphic10BandStereo",
        "HD2_EQLowCutHighCutStereo", "HD2_EQLowShelfHighShelfStereo",
        "HD2_EQParametricStereo", "HD2_EQSimple3BandStereo",
        "HD2_EQSimpleTiltStereo", "L6SPB_AcousGtrSimStereo",
    ):
        assert catalog.model_info(name).wire_category == 1, name
    # The 7 STATIC ones remain Preset EQ (on-wire category 23).
    assert (
        catalog.model_info("HD2_EQ_STATIC_ParametricStereo").wire_category == 23
    )


def test_lookup_uses_models_json():
    # lookup() must also serve models with wire_id from models.json
    # (today they're the same 16; after harvest they'll be ~all).
    md = catalog.lookup(366)
    assert md is not None
    assert md.name == "HD2_DM4TubeDrive"
    assert md.params == ("Drive", "Bass", "Mid", "Treble", "Output")


def test_display_category():
    assert catalog.display_category("HD2_AmpMandarin80") == "Amp"
    assert catalog.display_category("HD2_DistMinotaurMono") == "Dist"
    assert catalog.display_category("HD2_DM4TubeDrive") == "Dist"
    assert catalog.display_category("HD2_DL4DigDelay") == "Delay"
    assert catalog.display_category("VIC_ReverbDynRoomStereo") == "Reverb"
    assert catalog.display_category("HD2_MM4ScriptPhase") == "Mod"
    # input/output are not swappable blocks
    assert catalog.display_category("P34_AppDSPFlowInput") is None


def test_param_spec_value_type_and_display_type():
    # Mode of Auto Filter: discrete enum (valueType 0) with displayType.
    spec = catalog.model_info("HD2_FilterAutoFilterStereo").params["Mode"]
    assert spec.value_type == 0
    assert spec.display_type == "mode_pass"
    # Drive of DM4: continuous knob (valueType 1).
    drive = catalog.model_info("HD2_DM4TubeDrive").params["Drive"]
    assert drive.value_type == 1


def test_control_spec_enum_and_alias():
    cs = catalog.control_spec("mode_pass")
    assert cs is not None and cs.is_discrete
    assert cs.control_type == "segmented"
    assert cs.labels == ("Low Pass", "Band Pass", "High Pass")
    # off_on: boolean enum with labels.
    assert catalog.control_spec("off_on").labels == ("Off", "On")
    # alias: resolves to the pointed entry.
    assert catalog.control_spec("cab_low_cut") == catalog.control_spec("eq_low_cut")
    # continuous: not discrete, no labels.
    knob = catalog.control_spec("generic_knob")
    assert knob is not None and not knob.is_discrete and knob.labels is None
    # unknown / None.
    assert catalog.control_spec("no_existe_xyz") is None
    assert catalog.control_spec(None) is None


def test_eq_kind():
    # spec08: Preset EQ (STATIC) vs Effects EQ (non-STATIC) vs non-EQ.
    assert catalog.eq_kind("HD2_EQ_STATIC_ParametricStereo") == "preset"
    assert catalog.eq_kind("HD2_EQ_STATIC_CaliQStereo") == "preset"
    assert catalog.eq_kind("HD2_EQParametricStereo") == "effects"
    assert catalog.eq_kind("HD2_CaliQStereo") == "effects"
    # Acoustic Sim only exists as Effects EQ.
    assert catalog.eq_kind("L6SPB_AcousGtrSimStereo") == "effects"
    # non-EQ → None.
    assert catalog.eq_kind("HD2_DM4TubeDrive") is None
    assert catalog.eq_kind("HD2_AmpMandarin80") is None
    assert catalog.eq_kind("HD2_NoExiste") is None


def test_swap_group():
    # Dedicated preset blocks: locked to their own category.
    assert catalog.swap_group("Amp") == frozenset({"Amp"})
    assert catalog.swap_group("Cab") == frozenset({"Cab"})
    assert catalog.swap_group("Vol") == frozenset({"Vol"})
    assert catalog.swap_group("Wah") == frozenset({"Wah"})
    # Effects block: pure effects + Looper + EQ (spec08), no amp/cab/vol/wah.
    delay_group = catalog.swap_group("Delay")
    assert "Delay" in delay_group and "Reverb" in delay_group
    assert "Looper" in delay_group
    assert "EQ" in delay_group  # spec08: an Effects block can load an EQ
    assert "Amp" not in delay_group and "Cab" not in delay_group
    assert "Vol" not in delay_group and "Wah" not in delay_group
    # Looper lives in an Effects block: swapped with any effect.
    assert catalog.swap_group("Looper") == delay_group
    # Empty slot = effects block.
    assert catalog.swap_group(None) == delay_group


def test_swap_group_eq():
    # spec08: the EQ decision depends on the model (both display "EQ").
    # Preset EQ (STATIC): locked to EQ, not swappable (dedicated block).
    assert catalog.swap_group(
        "EQ", "HD2_EQ_STATIC_ParametricStereo"
    ) == frozenset({"EQ"})
    # Effects EQ (non-STATIC, incl. Acoustic Sim): effects group, swappable.
    eff = catalog.swap_group("EQ", "L6SPB_AcousGtrSimStereo")
    assert eff == catalog.swap_group("Delay")
    assert "EQ" in eff and "Delay" in eff


def test_fixture_eq_acoustic_sim_decodes():
    # spec08 RE (confirmed against the pedal): the fixture has an Effects-EQ
    # (Acoustic Sim, on-wire cat 1, id 485) and the dedicated Preset EQ (STATIC
    # Parametric, on-wire cat 23). This is the evidence for the entire distinction.
    pre = l6helix.parse_blob(
        l6helix.extract_blob((CAPS / "eq_acoustic_sim_obj22.bin").read_bytes())
    )
    by_id = {b.model_id: b for b in pre.chain if b is not None}
    # Effects EQ: Acoustic Sim in an Effects block.
    assert by_id[485].category == 1
    assert catalog.lookup(485).name == "L6SPB_AcousGtrSimStereo"
    assert catalog.eq_kind("L6SPB_AcousGtrSimStereo") == "effects"
    # Preset EQ: the dedicated block, STATIC model.
    assert by_id[472].category == 23
    assert catalog.eq_kind(catalog.lookup(472).name) == "preset"


def test_named_params_wrong_length():
    # 366 = HD2_DM4TubeDrive (5 params): a different length returns None.
    assert catalog.named_params(366, [0.1, 0.2]) is None


@pytest.mark.parametrize("bin_name,pgp_name", PAIRS)
def test_blob_cruza_con_pgp(bin_name, pgp_name):
    pre = l6helix.parse_blob(
        l6helix.extract_blob((CAPS / bin_name).read_bytes())
    )
    pgp = json.loads((CAPS / pgp_name).read_text(encoding="utf-8"))
    dsp0 = pgp["data"]["tone"]["dsp0"]
    by_pos = {
        blk["@position"]: blk
        for key, blk in dsp0.items()
        if key.startswith("block")
    }

    # Full coverage of positions: the blob chain and the .pgp
    # must cover exactly the same slots.
    assert set(range(len(pre.chain))) == set(by_pos)

    # Note: if two params of the SAME block share a value in the fixture
    # (e.g. Mid/Treble = 0.5), an incorrect order between them is not
    # detectable here; for those pairs we rely on the Helix convention
    # (see lab-notes). With distinct values, the cross-check does validate order.
    for pos, block in enumerate(pre.chain):
        jb = by_pos.get(pos)
        if block is None:
            assert jb is None or "@model" not in jb, f"slot {pos}"
            continue
        md = catalog.lookup(block.model_id)
        assert md is not None, f"model {block.model_id} not in catalog"
        assert md.name == jb["@model"], f"slot {pos}"
        assert block.enabled == jb["@enabled"], md.name
        assert block.no_snapshot_bypass == jb.get(
            "@no_snapshot_bypass", False
        ), md.name
        named = catalog.named_params(block.model_id, block.params)
        assert named is not None, (
            f"{md.name}: {len(block.params)} values vs {len(md.params)} names"
        )
        # all .pgp params (keys without @) with the same value
        for pname, jval in jb.items():
            if pname.startswith("@"):
                continue
            assert named[pname] == pytest.approx(
                jval, rel=1e-4, abs=1e-6
            ), f"{md.name}.{pname}"
        # extras that .pgp stores as @ attributes
        for extra in ("@trails", "@mic"):
            if extra in named:
                assert named[extra] == jb[extra], f"{md.name}.{extra}"
