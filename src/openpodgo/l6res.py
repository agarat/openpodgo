"""Parser for the official POD Go Edit resources (res/ folder).

Sources (copied to captures/podgo-edit-res):

- ``PodGo.sym``: symbol array; **the index is the on-wire id** (key 25
  of the l6-helix blob; validated 16/16 against vendor dumps) and
  ``parameters`` is the positional order of value params.
- ``*.models``: per-model metadata: display name, params with default,
  min/max, valueType (2 = bool), and the extra attributes (@mic/@trails)
  that the blob stores as params at the end; ``@enabled`` is the bypass,
  not a param.
- ``PGModelCatalog.json``: official categories (shortName) and subcategories
  (Amp/Preamp, Cab/Legacy Cab/IR) with the selectable models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Block attributes that the blob stores as params, in this order at the
#: end of the value list (same convention as pgb/catalog).
PARAM_ATTRS = ("@trails", "@mic")
#: Attributes from .models that are NOT value params in the blob: @enabled is
#: the bypass, @bypassvolume (amps) lives only in the editor/.pgp (see editor.py),
#: and @input/@output are keys 5/6 of the input/output payload.
NON_VALUE_ATTRS = ("@enabled", "@bypassvolume", "@input", "@output")

VALUE_TYPE_BOOL = 2


@dataclass(frozen=True)
class ResParam:
    name: str
    display_name: str
    default: object
    vmin: float | None
    vmax: float | None
    is_bool: bool
    #: valueType from .models (0 = enum/discrete integer, 1 = continuous, 2 = bool).
    value_type: int | None = None
    #: displayType from .models (key of res/PGControls.json: defines whether
    #: it is discrete, the control type, and the value labels).
    display_type: str | None = None


@dataclass(frozen=True)
class ResModel:
    symbol: str
    wire_id: int
    display_name: str
    category: str | None
    subcategory: str | None
    #: On-wire positional order: params from .sym + extras at the end.
    param_order: tuple[str, ...]
    params: dict[str, ResParam]
    #: Attributes from .models without on-wire evidence yet (@stereo, Pan,
    #: Lock): it is unknown whether they are blob values. Resolve with harvest.
    uncertain: tuple[str, ...] = ()


def _load_sym(res_dir: Path) -> dict[str, tuple[int, tuple[str, ...]]]:
    entries = json.loads((res_dir / "PodGo.sym").read_text(encoding="utf-8"))
    return {
        e["symbol"]: (wire_id, tuple(e.get("parameters") or ()))
        for wire_id, e in enumerate(entries)
    }


def _load_model_files(res_dir: Path) -> dict[str, dict]:
    models: dict[str, dict] = {}
    for path in sorted(res_dir.glob("*.models")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            models[entry["symbolicID"]] = entry
    return models


def _load_categories(res_dir: Path) -> dict[str, tuple[str, str | None]]:
    """symbol -> (category shortName, subcategory name or None)."""
    doc = json.loads(
        (res_dir / "PGModelCatalog.json").read_text(encoding="utf-8")
    )
    out: dict[str, tuple[str, str | None]] = {}
    for cat in doc["categories"]:
        for model in cat.get("models") or []:
            out[model["id"]] = (cat["shortName"], None)
        for sub in cat.get("subcategories") or []:
            for model in sub.get("models") or []:
                out[model["id"]] = (cat["shortName"], sub.get("name"))
    return out


def _res_param(entry: dict) -> ResParam:
    return ResParam(
        name=entry["symbolicID"],
        display_name=entry.get("name") or entry["symbolicID"],
        default=entry.get("default"),
        vmin=entry.get("min"),
        vmax=entry.get("max"),
        is_bool=entry.get("valueType") == VALUE_TYPE_BOOL
        or isinstance(entry.get("default"), bool),
        value_type=entry.get("valueType"),
        display_type=entry.get("displayType"),
    )


def load_resources(res_dir: Path) -> dict[str, ResModel]:
    """Complete official catalog: only symbols with entries in .sym and .models."""
    sym = _load_sym(res_dir)
    model_files = _load_model_files(res_dir)
    categories = _load_categories(res_dir)

    out: dict[str, ResModel] = {}
    for symbol, entry in model_files.items():
        if symbol not in sym:
            continue  # templates without on-wire presence
        wire_id, sym_params = sym[symbol]
        params = {
            p["symbolicID"]: _res_param(p)
            for p in entry.get("params") or []
            if p["symbolicID"] not in NON_VALUE_ATTRS
        }
        extras = tuple(
            attr for attr in PARAM_ATTRS if attr in params
        )
        uncertain = tuple(
            sorted(set(params) - set(sym_params) - set(extras))
        )
        cat, subcat = categories.get(symbol, (None, None))
        out[symbol] = ResModel(
            symbol=symbol,
            wire_id=wire_id,
            display_name=entry.get("name") or symbol,
            category=cat,
            subcategory=subcat,
            param_order=sym_params + extras,
            params=params,
            uncertain=uncertain,
        )
    return out
