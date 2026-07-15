"""POD Go model catalog: on-wire id → name and param order.

The IDs (key 25 of the block in the l6-helix blob) are stable across
presets. The names and param ORDER come from crossing vendor dumps
with POD Go Edit `.pgp` files (spec 02 Phase A/B); the .pgp lists params
by name and the blob by position. Seeded with the 16 observed models;
grow by adding new dump↔.pgp pairs (or crossing with vesco-helixnamer).

Names starting with `@` are block attributes in the .pgp
(`@trails`, `@mic`) that the blob stores as an additional parameter at
the end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Full catalog generated from the .pgb backup (tools/build_catalog.py).
MODELS_JSON = Path(__file__).parent / "data" / "models.json"
#: Control definitions by displayType (copy of res/PGControls.json):
#: marks discrete params and gives their value labels.
CONTROLS_JSON = Path(__file__).parent / "data" / "controls.json"


@dataclass(frozen=True)
class ModelDef:
    name: str
    params: tuple[str, ...]


MODELS: dict[int, ModelDef] = {
    3: ModelDef("HD2_AmpGCougar800", (
        "Drive", "Bass", "LowMid", "HighMid", "Treble",
        "ChVol", "Master", "Boost", "Contour",
    )),
    30: ModelDef("HD2_AmpMandarin80", (
        "Drive", "Bass", "Mid", "Treble", "Presence", "ChVol", "Master",
        "Sag", "Hum", "Ripple", "Bias", "BiasX", "FAC",
    )),
    # Cabs: EarlyReflections goes BEFORE Level (PodGo.sym). The value-based
    # cross-reference could not distinguish them (both 0.0 in both fixtures).
    60: ModelDef("HD2_Cab4x10Rhino", (
        "Distance", "LowCut", "HighCut", "EarlyReflections", "Level", "@mic",
    )),
    67: ModelDef("HD2_Cab4x12MandarinEM", (
        "Distance", "LowCut", "HighCut", "EarlyReflections", "Level", "@mic",
    )),
    88: ModelDef("HD2_DistCompulsiveDriveMono", (
        "Gain", "Tone", "LPHP", "Version", "Level",
    )),
    95: ModelDef("HD2_DistTriangleFuzzMono", ("Sustain", "Tone", "Level")),
    119: ModelDef("HD2_FXLoopMono1", ("Send", "Return", "Mix", "@trails")),
    224: ModelDef("HD2_VolPanVolStereo", ("Pedal", "VolumeTaper")),
    238: ModelDef("HD2_WahConductorStereo", (
        "Pedal", "FcLow", "FcHigh", "Mix", "Level",
    )),
    239: ModelDef("HD2_WahFasselStereo", (
        "Pedal", "FcLow", "FcHigh", "Mix", "Level",
    )),
    255: ModelDef("HD2_FilterAutoFilterStereo", (
        "Mode", "FilterGain", "FilterQ", "Sens", "Attack", "Decay",
        "Frequency", "FreqDepth", "Direction", "Mix", "Level",
    )),
    334: ModelDef("HD2_DL4DigDelay", (
        "Time", "Feedback", "Bass", "Treble", "Mix", "Level",
        "SyncSelect1", "TempoSync1", "@trails",
    )),
    366: ModelDef("HD2_DM4TubeDrive", (
        "Drive", "Bass", "Mid", "Treble", "Output",
    )),
    371: ModelDef("HD2_FM4Growler", (
        "Speed", "Freq", "Q", "Pitch", "Mix", "Level",
        "SyncSelect1", "TempoSync1",
    )),
    404: ModelDef("HD2_MM4ScriptPhase", (
        "Speed", "Level", "SyncSelect1", "TempoSync1",
    )),
    472: ModelDef("HD2_EQ_STATIC_ParametricStereo", (
        "LowFreq", "LowQ", "LowGain", "MidFreq", "MidQ", "MidGain",
        "HighFreq", "HighQ", "HighGain", "LowCut", "HighCut", "Level",
    )),
}


@dataclass(frozen=True)
class ParamSpec:
    """Parameter range from the backup (None = no data)."""

    vmin: float | None
    vmax: float | None
    is_bool: bool
    #: valueType from .models: 0 = enum/discrete integer, 1 = continuous, 2 = bool.
    value_type: int | None = None
    #: displayType from .models: key of controls.json (discrete value labels
    #: and control type). See control_spec().
    display_type: str | None = None


@dataclass(frozen=True)
class ModelInfo:
    """A model from models.json: params with range, defaults and wire_id."""

    name: str
    type: int | None
    params: dict[str, ParamSpec]
    defaults: dict
    #: On-wire ID (key 25 of blob) = index in PodGo.sym.
    wire_id: int | None
    #: Positional param order in the blob; None if uncertain attributes exist.
    param_order: tuple[str, ...] | None
    #: On-wire category (key 9); observed or inferred, None if no data.
    wire_category: int | None
    #: Official visible name ("Tube Drive") and UI category/subcategory.
    display_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    #: Attributes without on-wire evidence (@stereo, Pan, Lock).
    uncertain: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def _full_catalog() -> dict[str, ModelInfo]:
    if not MODELS_JSON.exists():
        return {}
    doc = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    return {
        name: ModelInfo(
            name=name,
            type=entry["type"],
            params={
                p: ParamSpec(
                    spec["min"], spec["max"], spec["bool"],
                    spec.get("value_type"), spec.get("display_type"),
                )
                for p, spec in entry["params"].items()
            },
            defaults=entry["defaults"],
            wire_id=entry["wire_id"],
            param_order=(
                tuple(entry["param_order"]) if entry["param_order"] else None
            ),
            wire_category=entry.get("wire_category"),
            display_name=entry.get("display_name"),
            category=entry.get("category"),
            subcategory=entry.get("subcategory"),
            uncertain=tuple(entry.get("uncertain") or ()),
        )
        for name, entry in doc["models"].items()
    }


@lru_cache(maxsize=1)
def _by_wire_id() -> dict[int, ModelDef]:
    by_id = dict(MODELS)
    for info in _full_catalog().values():
        if info.wire_id is not None and info.param_order:
            by_id.setdefault(info.wire_id, ModelDef(info.name, info.param_order))
    return by_id


def model_info(name: str) -> ModelInfo | None:
    """Model from the full catalog by name, or None."""
    return _full_catalog().get(name)


def model_names() -> list[str]:
    """All model names from the full catalog, sorted."""
    return sorted(_full_catalog())


#: Official categories that are not eligible chain blocks.
_NON_BLOCK_CATEGORIES = {None, "None", "Input", "Output"}

#: Fallback by prefix for models without an official category.
_PREFIX_CATEGORIES: tuple[tuple[str, str | None], ...] = (
    ("P34_", None),
    ("HD2_Amp", "Amp"),
    ("HD2_Preamp", "Amp"),
    ("HD2_Cab", "Cab"),
    ("HD2_Dist", "Dist"),
    ("HD2_DM", "Dist"),
    ("HD2_Compressor", "Dyn"),
    ("HD2_EQ", "EQ"),
    ("HD2_Delay", "Delay"),
    ("HD2_DL", "Delay"),
    ("HD2_Reverb", "Reverb"),
    ("VIC_", "Reverb"),
    ("HD2_Chorus", "Mod"),
    ("HD2_Flanger", "Mod"),
    ("HD2_Phaser", "Mod"),
    ("HD2_Rotary", "Mod"),
    ("HD2_Tremolo", "Mod"),
    ("HD2_Ring", "Mod"),
    ("HD2_MM", "Mod"),
    ("HD2_Filter", "Filter"),
    ("HD2_FM", "Filter"),
    ("HD2_Pitch", "Pitch"),
    ("HD2_Synth", "Pitch"),
    ("HD2_Wah", "Wah"),
    ("HD2_Vol", "Vol"),
    ("HD2_FXLoop", "Send/Return"),
)


def display_category(name: str) -> str | None:
    """UI category for a model (None = input/output, not eligible)."""
    info = _full_catalog().get(name)
    if info is not None and info.category is not None:
        return None if info.category in _NON_BLOCK_CATEGORIES else info.category
    for prefix, cat in _PREFIX_CATEGORIES:
        if name.startswith(prefix):
            return cat
    return "Other"


def eq_kind(model_name: str) -> str | None:
    """EQ block kind for a model (spec08): "preset" | "effects" | None.

    "preset" = the preset's dedicated EQ (models `_STATIC_`, on-wire
    category 23). "effects" = an EQ loaded in an Effects block (non-STATIC,
    on-wire category 1, including Acoustic Sim which only exists as Effects
    EQ). None if the model is not an EQ. Resolves the ambiguity that both
    types are display category "EQ".
    """
    if display_category(model_name) != "EQ":
        return None
    return "preset" if "_STATIC_" in model_name else "effects"


@dataclass(frozen=True)
class ControlSpec:
    """How to render a parameter, per its displayType (controls.json)."""

    is_discrete: bool
    control_type: str | None
    #: Discrete value labels (only if the control defines them).
    labels: tuple[str, ...] | None


@lru_cache(maxsize=1)
def _controls() -> dict[str, dict]:
    if not CONTROLS_JSON.exists():
        return {}
    return json.loads(CONTROLS_JSON.read_text(encoding="utf-8"))


@lru_cache(maxsize=512)
def control_spec(display_type: str | None) -> ControlSpec | None:
    """ControlSpec for the displayType, resolving aliases; None if unknown."""
    if not display_type:
        return None
    controls = _controls()
    entry = controls.get(display_type)
    seen = set()
    while entry is not None and "alias" in entry and entry["alias"] not in seen:
        seen.add(entry["alias"])
        entry = controls.get(entry["alias"])
    if entry is None:
        return None
    fmt = entry.get("format")
    labels = tuple(fmt) if isinstance(fmt, list) else None
    return ControlSpec(
        is_discrete=bool(entry.get("isDiscrete")),
        control_type=entry.get("controlType"),
        labels=labels,
    )


#: Model change restriction per slot (#5). Matches the "Block Types" in
#: the manual: Preset blocks have a dedicated category; the 4 Effects
#: blocks interchange between "pure" effects. The blob does not mark
#: preset-vs-effects, so restriction is by the current model's category.
#: Categories that an Effects block can load (manual "Effects" menu:
#: Dist, Dyn, EQ, Mod, Delay, Reverb, Pitch, Filter, Looper). Looper lives
#: ALWAYS in an Effects block (no dedicated block), one per preset.
#: EQ is here because a non-STATIC EQ (Effects EQ, incl. Acoustic Sim) is
#: just another effect (spec08); the dedicated Preset EQ uses
#: _PRESET_EQ_GROUP.
_EFFECT_GROUP = frozenset(
    {"Dist", "Dyn", "EQ", "Mod", "Delay", "Reverb", "Pitch", "Filter", "Looper"}
)
#: Dedicated Preset EQ group (spec08): locked to EQ and not clearable, like
#: Amp/Cab. Preset-vs-Effects distinction resolved by eq_kind().
_PRESET_EQ_GROUP = frozenset({"EQ"})
#: Categories locked to themselves. Amp/Cab/Vol/Wah/FX-Loop are Preset
#: blocks (don't appear in the Effects menu). EQ is NOT here: its ambiguity
#: (dedicated Preset EQ vs Effects EQ) is resolved by eq_kind() on the model.
_LOCKED_CATEGORIES = frozenset(
    {"Amp", "Cab", "Vol", "Wah", "Send/Return"}
)


#: Preferred sub-tab order by category (POD Go Edit separates Amp/Preamp
#: and Cab/Legacy Cab/IR into their own filters). Other categories have
#: no subcategories, so they don't show sub-tabs.
_SUBCATEGORY_ORDER: dict[str, tuple[str, ...]] = {
    "Amp": ("Amp", "Preamp"),
    "Cab": ("Cab", "Legacy Cab", "Impulse Response"),
}


def subcategories(category: str | None) -> list[str]:
    """Subcategories present in `category` (e.g. Amp → [Amp, Preamp]).

    Returns [] if the category has no real subcategories: the UI only
    shows the sub-tab row when there are 2 or more (#5/#3 follow-up).
    """
    if category is None:
        return []
    present: list[str] = []
    for info in _full_catalog().values():
        sub = info.subcategory
        if info.category == category and sub and sub not in present:
            present.append(sub)
    order = _SUBCATEGORY_ORDER.get(category)
    if order:
        present.sort(key=lambda s: order.index(s) if s in order else len(order))
    return present


def swap_group(
    category: str | None, model_name: str | None = None
) -> frozenset[str]:
    """Categories a block can be swapped to (#5, spec08).

    For EQ the decision depends on the MODEL, not the visible category
    (Preset EQ and Effects EQ are both display "EQ"): a Preset EQ (STATIC)
    is locked to EQ and not clearable; an Effects EQ is just another effect.
    An empty slot (category None, no model) is an Effects block. Other
    Preset blocks (amp/cab/vol/wah/fx-loop) are locked to their own category.
    """
    kind = eq_kind(model_name) if model_name else None
    if kind == "preset":
        return _PRESET_EQ_GROUP
    if kind == "effects":
        return _EFFECT_GROUP
    if category in _LOCKED_CATEGORIES:
        return frozenset({category})
    return _EFFECT_GROUP


#: On-wire param metadata for Input/Output (#2), from res/io.models
#: (stable per firmware). Each item: (symbol, visible name, ParamSpec).
#: Input carries [noiseGate, threshold, decay]; output [pan, gain].
IO_PARAM_META: dict[str, tuple[tuple[str, str, ParamSpec], ...]] = {
    "input": (
        ("noiseGate", "Input Gate", ParamSpec(False, True, True, 2, "off_on")),
        ("threshold", "Threshold", ParamSpec(-96.0, 0.0, False, 1, "volume")),
        ("decay", "Decay", ParamSpec(0.01, 1.0, False, 1, "time_ms")),
    ),
    "output": (
        ("pan", "Pan", ParamSpec(0.0, 1.0, False, 1, "pan")),
        ("gain", "Level", ParamSpec(-120.0, 20.0, False, 1, "volume")),
    ),
}


def io_param_meta(io: str) -> tuple[tuple[str, str, ParamSpec], ...]:
    """(symbol, name, ParamSpec) for Input/Output params."""
    return IO_PARAM_META[io]


def lookup(model_id: int) -> ModelDef | None:
    """Model definition, or None if not yet in the catalog."""
    return _by_wire_id().get(model_id)


def named_params(model_id: int, values: list) -> dict | None:
    """name→value map for a block, or None if it cannot be mapped.

    Returns None both for models outside the catalog and when the value
    count does not match the definition (sign the definition is outdated
    for this firmware).
    """
    md = _by_wire_id().get(model_id)
    if md is None or len(md.params) != len(values):
        return None
    return dict(zip(md.params, values))
