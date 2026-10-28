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
import re
import zipfile
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
    metadata: dict = field(default_factory=dict)


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


def read_backup(path: Path | str) -> Backup:
    """Parse a .pgb. Raises ValueError if the file is not an AF6L backup."""
    data = Path(path).read_bytes()
    if data[:4] != MAGIC:
        raise ValueError(f"{path}: not a .pgb backup (magic {data[:4]!r})")

    globals_: dict = {}
    setlists: dict[str, list] = {}
    metadata: dict = {}
    for out in _zlib_streams(data):
        if out[:1] != b"{":
            continue  # IR WAV or other binary
        doc = json.loads(out)
        schema = doc.get("schema")
        if schema == "L6Setlist":
            name = doc["data"]["meta"]["name"]
            setlists[name] = doc["data"]["presets"]
        elif schema == "L6BackupMeta":
            metadata = doc.get("data", {})
        elif schema is None and "System" in doc:
            globals_ = doc
        # L6UMDArchive (IR metadata): not used for now.
    if not setlists:
        raise ValueError(f"{path}: backup without L6Setlist setlists")
    if not metadata and globals_.get("System"):
        sys = globals_["System"]
        if "device" in sys:
            metadata["device"] = str(sys["device"])
        if "version" in sys:
            metadata["version"] = str(sys["version"])
    return Backup(globals=globals_, setlists=setlists, metadata=metadata)


def inspect_backup(path: Path | str) -> dict:
    """Inspect a .pgb container and return summary metadata without loading all preset data.

    Returns dict with keys:
      - 'date': str | None
      - 'device': str | None
      - 'version': str | None
      - 'description': str | None
      - 'setlists': dict[str, int] (name -> preset count)
      - 'has_globals': bool
      - 'ir_count': int
      - 'metadata': dict
    Raises ValueError if path is not a valid AF6L container or has no setlists.
    """
    data = Path(path).read_bytes()
    if data[:4] != MAGIC:
        raise ValueError(f"{path}: not a .pgb backup (magic {data[:4]!r})")

    meta: dict = {}
    setlists: dict[str, int] = {}
    has_globals = False
    ir_count = 0

    for out in _zlib_streams(data):
        if out[:1] != b"{":
            ir_count += 1
            continue
        try:
            doc = json.loads(out)
        except Exception:
            continue
        schema = doc.get("schema")
        if schema == "L6Setlist":
            name = doc.get("data", {}).get("meta", {}).get("name", "Unknown")
            presets = doc.get("data", {}).get("presets", [])
            setlists[name] = len(presets)
        elif schema == "L6BackupMeta":
            meta = doc.get("data", {})
        elif schema is None and "System" in doc:
            has_globals = True
            if "device" not in meta and "device" in doc["System"]:
                meta["device"] = str(doc["System"]["device"])
            if "version" not in meta and "version" in doc["System"]:
                meta["version"] = str(doc["System"]["version"])

    if not setlists:
        raise ValueError(f"{path}: backup without L6Setlist setlists")

    return {
        "date": meta.get("date") or meta.get("created_at"),
        "device": meta.get("device") or ("POD Go" if has_globals else None),
        "version": meta.get("version"),
        "description": meta.get("description"),
        "setlists": setlists,
        "has_globals": has_globals,
        "ir_count": ir_count,
        "metadata": meta,
    }


def write_backup(
    path: Path | str,
    backup: Backup,
    irs: list[bytes] | None = None,
) -> None:
    """Serialize a Backup into an AF6L .pgb container file.

    Raises ValueError if backup has no setlists.
    """
    if not backup.setlists:
        raise ValueError("Cannot write backup without at least one setlist")

    # Header: AF6L magic + 12-byte zero container padding
    chunks = [MAGIC + b"\x00" * 12]

    # 1. Metadata stream (if provided)
    if backup.metadata:
        meta_doc = {
            "schema": "L6BackupMeta",
            "version": 1,
            "data": backup.metadata,
        }
        meta_json = json.dumps(meta_doc, separators=(",", ":")).encode("utf-8")
        chunks.append(zlib.compress(meta_json))

    # 2. Globals stream (if provided)
    if backup.globals:
        globals_json = json.dumps(backup.globals, separators=(",", ":")).encode("utf-8")
        chunks.append(zlib.compress(globals_json))

    # 3. Setlist streams (Factory, User, etc.)
    for name, presets in backup.setlists.items():
        doc = {
            "schema": "L6Setlist",
            "version": 6,
            "data": {
                "meta": {"name": name},
                "presets": presets,
            },
        }
        setlist_json = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        chunks.append(zlib.compress(setlist_json))

    # 4. Optional IR streams (raw WAV or binary)
    if irs:
        for ir_bytes in irs:
            chunks.append(zlib.compress(ir_bytes))

    Path(path).write_bytes(b"".join(chunks))


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return cleaned.replace(" ", "_") or "preset"


def _preset_name(p: dict, default: str = "") -> str:
    if not isinstance(p, dict):
        return default
    # 1. Line 6 .pgp format: p["data"]["meta"]["name"]
    data = p.get("data")
    if isinstance(data, dict):
        data_meta = data.get("meta")
        if isinstance(data_meta, dict) and data_meta.get("name"):
            return str(data_meta["name"])
    # 2. Direct meta format: p["meta"]["name"]
    meta = p.get("meta")
    if isinstance(meta, dict) and meta.get("name"):
        return str(meta["name"])
    # 3. Direct top-level name
    if p.get("name"):
        return str(p["name"])
    return default


def export_presets_zip(
    path: Path | str,
    presets_by_setlist: dict[str, list[dict]],
    flat: bool | None = None,
) -> None:
    """Export presets into a .zip archive organized into .pgp files.

    If flat is True (or None with a single setlist), all presets are stored
    directly at the root of the archive without setlist subfolders (e.g. '01A_Clean.pgp').
    If flat is False, presets are organized into setlist subfolders.
    """
    if flat is None:
        flat = len(presets_by_setlist) == 1

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for setlist_name, presets in presets_by_setlist.items():
            folder = _sanitize_filename(setlist_name)
            for idx, p in enumerate(presets):
                if not p:
                    continue
                p_name = _preset_name(p, f"preset_{idx:03d}")
                clean_name = _sanitize_filename(p_name)
                if 0 <= idx < 128:
                    slot_prefix = f"{(idx // 4) + 1:02d}{'ABCD'[idx % 4]}"
                else:
                    slot_prefix = f"{idx:03d}"
                base_name = f"{slot_prefix}_{clean_name}.pgp"
                filename = base_name if flat else f"{folder}/{base_name}"
                if "schema" in p:
                    doc = p
                else:
                    doc = {
                        "schema": "L6Preset",
                        "version": 6,
                        "data": p,
                    }
                content = json.dumps(doc, indent=2).encode("utf-8")
                zf.writestr(filename, content)


def import_presets_zip(path: Path | str) -> dict[str, list[dict]]:
    """Import presets from a .zip archive containing .pgp files.

    Returns a mapping of setlist_name -> list of preset dicts.
    Raises ValueError if path is not a valid zip archive.
    """
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, IsADirectoryError, FileNotFoundError) as err:
        raise ValueError(f"{path}: not a valid zip archive ({err})") from err

    with zf:
        setlists: dict[str, list[dict]] = {}
        for name in sorted(zf.namelist()):
            if not name.endswith(".pgp"):
                continue
            parts = name.split("/")
            setlist_name = parts[0] if len(parts) > 1 else "User"
            try:
                raw = zf.read(name)
                doc = json.loads(raw)
            except Exception:
                continue
            preset_data = doc.get("data") if doc.get("schema") == "L6Preset" else doc
            setlists.setdefault(setlist_name, []).append(preset_data)

        return setlists


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
