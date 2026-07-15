"""Catalog harvest: crosses vendor dumps (object 22) with their .pgp files.

From each pair (decoded blob, `tone` from the L6Preset JSON of the same preset)
we extract, per block: the `wire_id` (key 25) ↔ `@model`, the on-wire category
(key 9), and candidates for the positional ORDER of params (the blob stores
them by position, the JSON by name: they are aligned by value). Ambiguities
(repeated values within a block) are resolved by aggregating occurrences of the
same model across different presets and propagating constraints.

Used by tools/harvest_catalog.py (traversal of the Factory setlist with the
pedal) and validated offline against the spec 02 pairs.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from . import l6helix, pgb


class HarvestConflict(RuntimeError):
    """An on-wire id appeared with two model names (or vice versa)."""


@dataclass
class HarvestResult:
    name: str
    wire_id: int
    category: int
    #: Complete positional param order, or None if it remained ambiguous.
    param_order: list[str] | None


@dataclass
class _Agg:
    name: str
    wire_id: int
    category: int
    #: Per blob position: param names still possible.
    candidates: list[set[str]]


def _values_match(blob_value, json_value) -> bool:
    if isinstance(blob_value, bool) or isinstance(json_value, bool):
        return blob_value is json_value
    if isinstance(blob_value, (int, float)) and isinstance(json_value, (int, float)):
        return math.isclose(blob_value, json_value, rel_tol=1e-4, abs_tol=1e-6)
    return blob_value == json_value


class Accumulator:
    """Accumulates preset-blob ↔ preset-JSON pairs and resolves the catalog."""

    def __init__(self) -> None:
        self._models: dict[str, _Agg] = {}
        self._by_id: dict[int, str] = {}

    def add_preset(self, pre: l6helix.Preset, tone: dict) -> list[str]:
        """Cross-reference a preset. Returns warnings for mismatched blocks."""
        warnings: list[str] = []
        by_pos = {
            blk["@position"]: blk
            for key, blk in (tone.get("dsp0") or {}).items()
            if key.startswith("block") and isinstance(blk, dict)
        }
        for pos, block in enumerate(pre.chain):
            jb = by_pos.get(pos)
            if block is None:
                if jb is not None and "@model" in jb:
                    warnings.append(f"slot {pos}: empty in blob, {jb['@model']} in JSON")
                continue
            if jb is None or "@model" not in jb:
                warnings.append(f"slot {pos}: block in blob without matching JSON entry")
                continue
            warning = self._add_block(pos, block, jb)
            if warning:
                warnings.append(warning)
        return warnings

    def _add_block(self, pos: int, block: l6helix.Block, jb: dict) -> str | None:
        name = jb["@model"]
        params = pgb.block_params(jb)
        if len(params) != len(block.params):
            return (
                f"slot {pos} ({name}): {len(block.params)} values in blob vs "
                f"{len(params)} params in JSON"
            )
        candidates = [
            {p for p, jval in params.items() if _values_match(value, jval)}
            for value in block.params
        ]
        if any(not c for c in candidates):
            return f"slot {pos} ({name}): blob values do not match JSON"

        known_name = self._by_id.get(block.model_id)
        if known_name is not None and known_name != name:
            raise HarvestConflict(
                f"id {block.model_id}: seen as {known_name} and as {name}"
            )
        agg = self._models.get(name)
        if agg is None:
            self._models[name] = _Agg(
                name=name,
                wire_id=block.model_id,
                category=block.category,
                candidates=candidates,
            )
            self._by_id[block.model_id] = name
            return None
        if agg.wire_id != block.model_id:
            raise HarvestConflict(
                f"{name}: seen with id {agg.wire_id} and with id {block.model_id}"
            )
        merged = [a & b for a, b in zip(agg.candidates, candidates)]
        if any(not c for c in merged):
            return f"slot {pos} ({name}): inconsistent occurrence, not aggregated"
        agg.candidates = merged
        return None

    def resolved(self) -> dict[str, HarvestResult]:
        return {
            name: HarvestResult(
                name=name,
                wire_id=agg.wire_id,
                category=agg.category,
                param_order=_propagate(agg.candidates),
            )
            for name, agg in self._models.items()
        }


def _propagate(candidates: list[set[str]]) -> list[str] | None:
    """Resolve the position→name assignment by constraint propagation."""
    cands = [set(c) for c in candidates]
    changed = True
    while changed:
        changed = False
        for i, c in enumerate(cands):
            if len(c) == 1:
                value = next(iter(c))
                for j, other in enumerate(cands):
                    if j != i and value in other:
                        other.discard(value)
                        changed = True
        counts = Counter(name for c in cands for name in c)
        for name, k in counts.items():
            if k == 1:
                for c in cands:
                    if name in c and len(c) > 1:
                        c.intersection_update({name})
                        changed = True
    if all(len(c) == 1 for c in cands):
        return [next(iter(c)) for c in cands]
    return None
