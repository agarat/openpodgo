"""Parser for official POD Go Edit resources (captures/podgo-edit-res).

Authoritative source of the catalog: PodGo.sym (the INDEX of the array is the
on-wire id, validated 16/16 against vendor dumps), *.models (display names,
defaults, ranges, types) and PGModelCatalog.json (official categories).
"""

from pathlib import Path

import pytest

from openpodgo import catalog, l6res

RES = Path(__file__).parent.parent / "captures" / "podgo-edit-res"

# The official POD Go Edit resources are proprietary and are NOT shipped. This
# module only runs where a user has placed them under captures/podgo-edit-res/.
pytestmark = pytest.mark.skipif(
    not RES.is_dir(), reason="proprietary POD Go Edit resources not present"
)


@pytest.fixture(scope="module")
def res():
    return l6res.load_resources(RES)


def test_coverage(res):
    # 272 effects + 106 amps + 108 preamps + 87 cabs (and some fixed).
    assert len(res) >= 550


def test_known_model(res):
    m = res["HD2_DM4TubeDrive"]
    assert m.wire_id == 366
    assert m.display_name == "Tube Drive"
    assert m.category == "Dist"
    assert m.param_order == ("Drive", "Bass", "Mid", "Treble", "Output")
    assert set(m.params) == set(m.param_order)


def test_extras_at_end(res):
    # The blob orders: .sym params + (@mic/@trails) attributes at the end.
    assert res["HD2_Cab4x10Rhino"].param_order[-1] == "@mic"
    assert res["HD2_DL4DigDelay"].param_order[-1] == "@trails"
    assert res["HD2_FXLoopMono1"].param_order == ("Send", "Return", "Mix", "@trails")


def test_bools_and_ranges(res):
    vp = res["HD2_VolPanVolStereo"]
    assert vp.params["VolumeTaper"].is_bool  # valueType 2
    assert vp.params["Pedal"].is_bool is False
    wah = res["HD2_WahFasselStereo"]
    fchigh = wah.params["FcHigh"]
    assert not fchigh.is_bool
    assert fchigh.vmax > fchigh.vmin
    assert fchigh.default is not None


def test_16_seeded_match(res):
    # Ids and param order of the seeded catalog == official resources.
    for wire_id, md in catalog.MODELS.items():
        m = res[md.name]
        assert m.wire_id == wire_id, md.name
        assert m.param_order == md.params, md.name


def test_uncertain_marked(res):
    # @stereo/Pan/Lock have no on-wire evidence: they remain marked, not
    # guessed (the pedal harvest will resolve them).
    assert res["HD2_ReverbHxSpringStereo"].uncertain == ("@stereo",)
    assert res["HD2_DM4TubeDrive"].uncertain == ()
    # The sym+extras rule is validated live (RINDANSE, lab-notes):
    assert len(res["HD2_DelayTransistorTapeStereo"].param_order) == 11
    assert res["HD2_DelayTransistorTapeStereo"].param_order[-1] == "@trails"


def test_official_categories(res):
    assert res["HD2_AmpGCougar800"].category == "Amp"
    assert res["HD2_AmpGCougar800"].subcategory == "Amp"
    assert res["HD2_PreampGCougar800"].subcategory == "Preamp"
    assert res["HD2_Cab4x10Rhino"].subcategory == "Legacy Cab"
    assert res["HD2_EQ_STATIC_ParametricStereo"].category == "EQ"
    # input/output exist but with non-swappable category
    assert res["P34_AppDSPFlowInput"].category in (None, "Input")
