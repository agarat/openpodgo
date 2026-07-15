"""Reading POD Go Edit .pgb backups (AF6L container).

Observed structure (RE editor-ui session): magic ``AF6L`` + binary header
with setlist names + consecutive zlib streams. Each stream decompresses
to a JSON (globals without schema, ``L6UMDArchive``, two ``L6Setlist``)
or to a WAV (IRs). The ``L6Setlist`` entries carry the 128 presets from
Factory and User with the same body as a ``.pgp`` (``data`` of L6Preset),
making the backup the source for the complete model catalog: parameter
names, values in real units, and controller ranges.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"AF6L"

#: Block `@` attributes that the vendor blob stores as an additional parameter
#: at the end (same convention as `catalog.py`).
PARAM_ATTRS = ("@trails", "@mic")


@dataclass
class Backup:
    """Useful content of a .pgb: globals + setlists with their presets."""

    globals: dict
    #: setlist name -> list of 128 presets (L6Preset body: meta/tone).
    setlists: dict[str, list]


@dataclass
class ParamRange:
    vmin: float | None = None
    vmax: float | None = None
    is_bool: bool = True  # becomes False upon seeing a numeric value


@dataclass
class ModelExtract:
    """A model as seen in the backup: params with range and default values."""

    name: str
    type: int | None
    params: dict[str, ParamRange] = field(default_factory=dict)
    #: first set of values seen (Factory first): serves as defaults.
    defaults: dict = field(default_factory=dict)


def _zlib_streams(data: bytes, start: int = 0):
    """Consecutive zlib streams within `data` (skipping false 0x78 hits)."""
    pos = start
    while True:
        idx = data.find(b"\x78", pos)
        if idx < 0:
            return
        if data[idx + 1: idx + 2] not in (b"\xda", b"\x9c", b"\x01"):
            pos = idx + 1
            continue
        dec = zlib.decompressobj()
        try:
            out = dec.decompress(data[idx:])
        except zlib.error:
            pos = idx + 1
            continue
        yield out
        pos = idx + (len(data) - idx - len(dec.unused_data))


def read_backup(path: Path) -> Backup:
    """Parse a .pgb. Raises ValueError if the file is not an AF6L backup."""
    data = Path(path).read_bytes()
    if data[:4] != MAGIC:
        raise ValueError(f"{path}: not a .pgb backup (magic {data[:4]!r})")

    globals_: dict = {}
    setlists: dict[str, list] = {}
    for out in _zlib_streams(data):
        if out[:1] != b"{":
            continue  # IR WAV or other binary
        doc = json.loads(out)
        schema = doc.get("schema")
        if schema == "L6Setlist":
            name = doc["data"]["meta"]["name"]
            setlists[name] = doc["data"]["presets"]
        elif schema is None and "System" in doc:
            globals_ = doc
        # L6UMDArchive (IR metadata): not used for now.
    if not setlists:
        raise ValueError(f"{path}: backup without L6Setlist setlists")
    return Backup(globals=globals_, setlists=setlists)


def block_params(block: dict) -> dict:
    """Params of a JSON block: keys without `@` + PARAM_ATTRS extras."""
    params = {k: v for k, v in sorted(block.items()) if not k.startswith("@")}
    for extra in PARAM_ATTRS:
        if extra in block:
            params[extra] = block[extra]
    return params


def extract_models(backup: Backup) -> dict[str, ModelExtract]:
    """Unique models from all presets, with ranges and defaults.

    Raises ValueError if the same model appears with different param sets
    (sign of mixed presets from incompatible firmwares).
    """
    models: dict[str, ModelExtract] = {}
    for setlist in backup.setlists.values():
        for preset in setlist:
            if not preset:
                continue
            tone = preset.get("tone") or {}
            controllers = (tone.get("controller") or {}).get("dsp0") or {}
            dsp0 = tone.get("dsp0") or {}
            for slot, block in dsp0.items():
                if not isinstance(block, dict) or "@model" not in block:
                    continue
                _merge_block(models, block, controllers.get(slot) or {})
    return models


def _merge_block(models: dict, block: dict, controller: dict) -> None:
    name = block["@model"]
    values = block_params(block)
    model = models.get(name)
    if model is None:
        model = models[name] = ModelExtract(
            name=name,
            type=block.get("@type"),
            params={p: ParamRange() for p in values},
            defaults=dict(values),
        )
    elif set(model.params) != set(values):
        raise ValueError(
            f"{name}: inconsistent params across presets "
            f"({sorted(model.params)} vs {sorted(values)})"
        )
    for pname, val in values.items():
        rng = model.params[pname]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        rng.is_bool = False
        rng.vmin = val if rng.vmin is None else min(rng.vmin, val)
        rng.vmax = val if rng.vmax is None else max(rng.vmax, val)
    # Controllers carry the actual parameter range (@min/@max).
    for pname, ctl in controller.items():
        rng = model.params.get(pname)
        if rng is None or not isinstance(ctl, dict):
            continue
        if "@min" in ctl:
            rng.is_bool = False
            rng.vmin = ctl["@min"] if rng.vmin is None else min(rng.vmin, ctl["@min"])
        if "@max" in ctl:
            rng.vmax = ctl["@max"] if rng.vmax is None else max(rng.vmax, ctl["@max"])
