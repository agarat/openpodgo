#!/usr/bin/env python3
"""Generates src/openpodgo/data/icon_map.json: model → official icon.

Sources, in order of priority:
1. PGModelCatalog.json (captures/podgo-edit-res/): exact `image` field by id.
2. Heuristic by prefix family against res/icons/models/: the suffix of the
   model name (without HD2_/VIC_/P34_, without Amp/Preamp/Cab/CabMicIr_, without
   trailing Mono/Stereo) is normalized (alphanumeric lowercase) and compared with
   the suffix of the AMP_HX_*/PRE_HX_*/CAB_HX_*/CABMICIR_HX_* files.
3. Manual OVERRIDES for renames (Litigator→BluesLitigator, etc.).

Run from repo root:  python tools/build_icon_map.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ICONS_DIR = ROOT / "res/icons/models"
PG_CATALOG = ROOT / "captures/podgo-edit-res/PGModelCatalog.json"
OUT = ROOT / "src/openpodgo/data/icon_map.json"

#: Models whose official icon uses another name (manually validated against
#: res/icons/models). Preamp* models share the PRE_HX or the amp's icon.
OVERRIDES = {
    "HD2_AmpCaliIVR1": "AMP_HX_GTR_CaliIVRhythm1.png",
    "HD2_AmpCaliIVR2": "AMP_HX_GTR_CaliIVRhythm2.png",
    "HD2_AmpGermanXtraBlue": "AMP_HX_GTR_GermanExtraBlue.png",
    "HD2_AmpGermanXtraRed": "AMP_HX_GTR_GermanExtraRed.png",
    "HD2_AmpLine6Badonk": "AMP_HX_GTR_L6-Badonk.png",
    "HD2_AmpLine6Litigator": "AMP_HX_GTR_BluesLitigator.png",
    "HD2_AmpMandarin80": "AMP_HX_GTR_MandarinOR80.png",
    "HD2_AmpSoloLeadClean": "AMP_HX_GTR_Solo100Clean.png",
    "HD2_AmpSoloLeadCrunch": "AMP_HX_GTR_Solo100Crunch.png",
    "HD2_AmpSoloLeadOD": "AMP_HX_GTR_Solo100OD.png",
    "HD2_AmpTweedBluesBrt": "AMP_HX_GTR_TweedBluesBright.png",
    "HD2_AmpTweedBluesNrm": "AMP_HX_GTR_TweedBluesNormal.png",
    "HD2_AmpUSSuperNorm": "AMP_HX_GTR_USSuperNrm.png",
    # There is no Vib channel icon: the same amp's normal channel icon is used.
    "HD2_AmpUSDeluxeVib": "AMP_HX_GTR_USDeluxeNrm.png",
    "HD2_CabMicIr_2x15USDripman": "CABMICIR_HX_2x15Dripman.png",
    "HD2_CabMicIr_4x12BlackbackH30": "CABMICIR_HX_4x12Blackback30.png",
    # HD2_PreampVintagePre has no icon in the resources: it is excluded from
    # the map, and the UI falls back to the category icon.
    "HD2_Cab1x10PrincessCopperhead": "CAB_HX_1x10_USPrincess.png",
    "HD2_Cab1x12PrincessBlue": "CAB_HX_1x12_USPrincess.png",
    # No 1x12 Match icon is available: 2x12 is used instead.
    "HD2_Cab1x12MatchG25": "CAB_HX_2x12_Match_G25.png",
    "HD2_Cab1x12MatchH30": "CAB_HX_2x12_Match_H30.png",
    "HD2_ImpulseResponse1024Mono": "FX_HX_IR_1024.png",
    "HD2_Cab1x6x9SoupProEllipse": "CAB_HX_1x6_SoupProEllipse.png",
}

_NORM = re.compile(r"[^a-z0-9]")


def norm(s: str) -> str:
    return _NORM.sub("", s.lower())


def index_by_family(icons: list[str]) -> dict[str, dict[str, str]]:
    """family → {normalized_suffix → file}."""
    families = {
        "AMP": ("AMP_HX_GTR_", "AMP_HX_BASS_"),
        "PRE": ("PRE_HX_",),
        "CAB": ("CAB_HX_",),
        "CABMICIR": ("CABMICIR_HX_",),
    }
    out: dict[str, dict[str, str]] = {f: {} for f in families}
    for fname in icons:
        for family, prefixes in families.items():
            for prefix in prefixes:
                if fname.startswith(prefix):
                    out[family].setdefault(norm(fname[len(prefix):-4]), fname)
    return out


def model_key(name: str) -> tuple[list[str], str]:
    """(candidate families in order, model suffix to normalize)."""
    base = re.sub(r"^(HD2|VIC|P34)_", "", name)
    base = re.sub(r"(Mono|Stereo)$", "", base)
    if base.startswith("CabMicIr_"):
        return ["CABMICIR", "CAB"], base[len("CabMicIr_"):]
    if base.startswith("Cab"):
        return ["CAB", "CABMICIR"], base[len("Cab"):]
    if base.startswith("Preamp"):
        # Preamp falls back to the amp's icon when there is no dedicated PRE_HX.
        return ["PRE", "AMP"], base[len("Preamp"):]
    if base.startswith("Amp"):
        return ["AMP"], base[len("Amp"):]
    return [], base


def heuristic(name: str, families: dict[str, dict[str, str]]) -> str | None:
    cands, suffix = model_key(name)
    n = norm(suffix)
    if not n:
        return None
    for fam in cands:
        if n in families[fam]:
            return families[fam][n]
    for fam in cands:
        for key, fname in sorted(families[fam].items()):
            if n in key or key in n:
                return fname
    return None


def build() -> dict[str, str]:
    sys.path.insert(0, str(ROOT / "src"))
    from openpodgo import catalog

    icons = sorted(p.name for p in ICONS_DIR.iterdir() if p.suffix == ".png")
    iconset = set(icons)
    families = index_by_family(icons)

    pg = json.loads(PG_CATALOG.read_text(encoding="utf-8"))
    direct = {
        m["id"]: m["image"]
        for c in pg["categories"]
        for m in c.get("models", [])
        if m.get("image") in iconset
    }

    out: dict[str, str] = {}
    unresolved: list[str] = []
    for name in catalog.model_names():
        # For preamps without a dedicated icon, the override of their twin Amp
        # also applies (last resort, after the heuristic).
        amp_twin = name.replace("Preamp", "Amp", 1)
        fname = (
            direct.get(name)
            or OVERRIDES.get(name)
            or heuristic(name, families)
            or OVERRIDES.get(amp_twin)
        )
        if fname is None:
            unresolved.append(name)
            continue
        assert fname in iconset, f"{name} → {fname} does not exist"
        out[name] = fname

    print(f"{len(out)}/{len(catalog.model_names())} models with icons")
    if unresolved:
        print(f"no icon ({len(unresolved)}):")
        for u in unresolved:
            print(f"  {u}")
    return out


def main() -> int:
    mapping = build()
    OUT.write_text(
        json.dumps(mapping, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"written {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
