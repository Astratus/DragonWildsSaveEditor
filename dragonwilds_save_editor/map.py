"""Map state in a Dragonwilds character save: fog of war, Sanguine Urns, kebbit burrows.

Stdlib only. Every function edits a dw_save.SaveFile IN MEMORY; writing goes through
SaveFile.save() (backup first, refuses while the game runs, byte-exact formatting).

Save layout (GameProgress):
  RevealedFog.RevealedRegionsBitmap   int, bit N = map RegionID N. Bit 0 is always set and is
                                      never cleared here. The game sets bits as you enter a
                                      region and never clears them. Purely cosmetic: travel
                                      gates go by quest state, not by this bitmap.
                                      Stored as UE int32, so bit 31 is written as a negative
                                      number (two's complement); reading masks to 32 bits.
  Progress.ShrinesUnlocked            [32-hex GUID]  Sanguine Urns (health shrines; each one
                                      used permanently gives +10 max health). NOT fast travel.
                                      The catalog keeps the JSON key "shrines".
  Progress.KebbitBurrowsFound         [32-hex GUID]
  Progress.KebbitBurrowsActivated     [32-hex GUID]

Kebbit burrow rule. The two burrow lists are independent in real saves: the live save has 4
burrows that are Activated but not Found (and 6 Found but not Activated), and the older v83
backup has 2 Activated, none of them Found. So the game does not keep Activated as a subset of
Found. This module therefore treats them as two independent flags:
  * set_burrow_flags(found=..., activated=...) adds/removes the ID in just the named list;
    turning Activated on does NOT add it to Found (mirrors what the game writes);
  * remove_burrow removes it from both;
  * burrow_state() summarises: "activated" if in Activated, "found" if only in Found, else
    "not found"; rows also carry in_found / in_activated.
List order is preserved; new IDs are appended at the end, uppercase like the game writes them.

Names and areas come from data/map_points.json (written by a separate research step). The file
may be missing or partial: areas then fall back to the built-in bit table below and unknown IDs
show as "(unknown name)". Only IDs from that catalog, or IDs the game itself wrote into this save,
can be added; arbitrary strings are refused.
"""

import json
import os
import re

from . import paths

MAP_PATH = paths.resource_path("data", "map_points.json")

GUID32_RE = re.compile(r"^[0-9A-Fa-f]{32}$")
UNKNOWN_NAME = "(unknown name)"

SHRINES = "ShrinesUnlocked"
FOUND = "KebbitBurrowsFound"
ACTIVATED = "KebbitBurrowsActivated"

NOT_FOUND, FOUND_ONLY, ACTIVE = "not found", "found", "activated"

# Built-in fallback: area -> map RegionIDs (bit numbers). Bit 0 belongs to no area.
BUILTIN_AREAS = (
    ("Brynmoor", tuple(range(1, 4))),
    ("Ghornfell", tuple(range(4, 7))),
    ("Fellhollow", tuple(range(7, 16))),
    ("Dowdun Reach", tuple(range(16, 26))),
    ("Umbral Sands", tuple(range(26, 30))),
    ("Scorned Wilderness", (30, 31)),
)


class MapError(ValueError):
    pass


# ---- catalog --------------------------------------------------------------------------------

def _builtin_areas():
    return [{"name": n, "bits": list(b), "gated_by_quest": None, "gate_note": "", "gate_confidence": ""}
            for n, b in BUILTIN_AREAS]


def _norm_id(i):
    return i.strip().upper() if isinstance(i, str) else None


def load_map_data(path=MAP_PATH):
    """Normalized map catalog. Never raises: a missing or broken file gives the built-in table.

    Returns {"areas": [{name, bits, gated_by_quest, gate_note, gate_confidence}],
             "fog_bits": {bit: {"region_name", "area"}},
             "shrines": {ID: rec}, "kebbit_burrows": {ID: rec},
             "source": "file" | "builtin", "warnings": [str]}
    """
    out = {"areas": [], "fog_bits": {}, "shrines": {}, "kebbit_burrows": {}, "source": "builtin", "warnings": []}
    raw = None
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("top level is not an object")
        out["source"] = "file"
    except FileNotFoundError:
        out["warnings"].append("%s not found; using the built-in region table." % os.path.basename(path))
        raw = {}
    except (OSError, ValueError) as e:
        out["warnings"].append("%s could not be read (%s); using the built-in region table."
                               % (os.path.basename(path), e))
        raw = {}

    # fog bits
    for fb in raw.get("fog_bits") or []:
        try:
            bit = int(fb["bit"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= bit < 32:
            out["fog_bits"][bit] = {"region_name": fb.get("region_name") or "", "area": fb.get("area") or ""}

    # areas: file first, else derive from fog_bits, else built-in
    areas = []
    for a in raw.get("areas") or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        try:
            bits = sorted({int(b) for b in a.get("bits") or [] if 0 < int(b) < 32})
        except (TypeError, ValueError):
            bits = []
        areas.append({"name": a["name"], "bits": bits, "gated_by_quest": a.get("gated_by_quest"),
                      "gate_note": a.get("gate_note") or "", "gate_confidence": a.get("gate_confidence") or ""})
    if not areas and out["fog_bits"]:
        by_area = {}
        for bit, fb in sorted(out["fog_bits"].items()):
            if bit and fb["area"]:
                by_area.setdefault(fb["area"], []).append(bit)
        areas = [{"name": n, "bits": b, "gated_by_quest": None, "gate_note": "", "gate_confidence": ""}
                 for n, b in by_area.items()]
    if not areas:
        areas = _builtin_areas()
    elif out["source"] == "file":
        # Fill bits an area lists nowhere from the built-in table, so no region becomes uneditable.
        builtin = {n: b for n, b in BUILTIN_AREAS}
        for a in areas:
            if not a["bits"] and a["name"] in builtin:
                a["bits"] = list(builtin[a["name"]])
    out["areas"] = areas

    for key in ("shrines", "kebbit_burrows"):
        for rec in raw.get(key) or []:
            i = _norm_id(rec.get("id")) if isinstance(rec, dict) else None
            if i and GUID32_RE.match(i):
                out[key][i] = dict(rec, id=i)
    return out


def area(map_data, name):
    for a in map_data["areas"]:
        if a["name"] == name:
            return a
    raise KeyError(name)


def region_name(map_data, bit):
    fb = map_data["fog_bits"].get(bit) or {}
    return fb.get("region_name") or "Region %d" % bit


# ---- fog bitmap -------------------------------------------------------------------------------

def _fog(save, create=False):
    fog = save.progress.get("RevealedFog")
    if not isinstance(fog, dict):
        if not create:
            return None
        fog = save.progress["RevealedFog"] = {}
    return fog


def fog_bitmap(save):
    """The bitmap as an unsigned 32-bit int (0 if the save has none)."""
    fog = _fog(save)
    v = fog.get("RevealedRegionsBitmap", 0) if fog else 0
    return int(v) & 0xFFFFFFFF


def set_fog_bitmap(save, value):
    """Store value (bit 0 forced on). Leaves the stored number untouched if nothing changes."""
    value = (int(value) | 1) & 0xFFFFFFFF
    if _fog(save) is not None and value == fog_bitmap(save):
        return value
    signed = value - (1 << 32) if value >= (1 << 31) else value  # UE int32
    _fog(save, create=True)["RevealedRegionsBitmap"] = signed
    return value


def is_revealed(save, bit):
    return bool(fog_bitmap(save) >> bit & 1)


def set_bits(save, bits, revealed):
    """Reveal or hide the given RegionIDs. Bit 0 is never cleared. Returns the new bitmap."""
    v = fog_bitmap(save)
    for b in bits:
        b = int(b)
        if not 0 <= b < 32:
            raise MapError("Region bit %d is out of range 0-31." % b)
        if b == 0:
            continue
        v = v | (1 << b) if revealed else v & ~(1 << b)
    return set_fog_bitmap(save, v)


def area_state(save, area_rec):
    """(revealed count, total) for an area."""
    v = fog_bitmap(save)
    bits = area_rec["bits"]
    return sum(1 for b in bits if v >> b & 1), len(bits)


def reveal_area(save, area_rec):
    return set_bits(save, area_rec["bits"], True)


def hide_area(save, area_rec):
    return set_bits(save, area_rec["bits"], False)


def reveal_all(save, map_data):
    bits = [b for a in map_data["areas"] for b in a["bits"]]
    return set_bits(save, bits, True)


# ---- Sanguine Urn / burrow lists ---------------------------------------------------------------------

def _list(save, key, create=False):
    prog = save.progress.get("Progress")
    lst = prog.get(key) if isinstance(prog, dict) else None
    if isinstance(lst, list):
        return lst
    if not create:
        return []
    return save.progress.setdefault("Progress", {}).setdefault(key, [])


def _in(lst, i):
    return any(_norm_id(x) == i for x in lst)


def _append(save, key, i):
    lst = _list(save, key, create=True)
    if _in(lst, i):
        return False
    lst.append(i)
    return True


def _discard(save, key, i):
    lst = _list(save, key)
    before = len(lst)
    lst[:] = [x for x in lst if _norm_id(x) != i]
    return before - len(lst)


def _game_written_ids(save, keys):
    """IDs the game itself wrote into this save file (as loaded from disk)."""
    cache = save.__dict__.setdefault("_dw_map_seen", {})
    if not cache:
        try:
            prog = json.loads(save.original_text).get("GameProgress", {}).get("Progress", {})
        except ValueError:
            prog = {}
        for k in (SHRINES, FOUND, ACTIVATED):
            cache[k] = {_norm_id(x) for x in prog.get(k) or [] if isinstance(x, str)}
    out = set()
    for k in keys:
        out |= cache.get(k, set())
    return out


def _check_id(save, map_data, kind, i):
    """Normalized id, or MapError unless it is in the catalog or was written by the game."""
    n = _norm_id(i)
    if not n or not GUID32_RE.match(n):
        raise MapError("Not a valid ID: %r (expected 32 hex characters)." % (i,))
    keys = (SHRINES,) if kind == "shrines" else (FOUND, ACTIVATED)
    if n not in map_data[kind] and n not in _game_written_ids(save, keys):
        raise MapError("%s is not a known %s ID; only catalog IDs (data/map_points.json) or IDs "
                       "already in this save can be added." % (n, "Sanguine Urn" if kind == "shrines" else "kebbit burrow"))
    return n


def point_name(map_data, kind, i):
    rec = map_data[kind].get(_norm_id(i)) or {}
    return rec.get("name") or UNKNOWN_NAME


def point_area(map_data, kind, i):
    rec = map_data[kind].get(_norm_id(i)) or {}
    return rec.get("area") or ""


def urn_rows(save, map_data):
    """[{id, name, area, unlocked, known}]: Sanguine Urns in the save, the catalog, and any the game wrote
    into the file on disk (so one removed this session can be added back)."""
    unlocked = [_norm_id(x) for x in _list(save, SHRINES)]
    seen = sorted(_game_written_ids(save, (SHRINES,)) - set(unlocked))  # removed this session
    ids = list(dict.fromkeys([i for i in unlocked if i] + list(map_data["shrines"]) + seen))
    return [{"id": i, "name": point_name(map_data, "shrines", i), "area": point_area(map_data, "shrines", i),
             "unlocked": i in unlocked, "known": i in map_data["shrines"]} for i in ids]


def unlock_urn(save, map_data, i):
    """Mark a Sanguine Urn as used (append to ShrinesUnlocked). Catalog/game IDs only."""
    return _append(save, SHRINES, _check_id(save, map_data, "shrines", i))


def remove_urn(save, i):
    """Un-use a Sanguine Urn. Probably lowers max health by 10 (inferred, untested)."""
    return _discard(save, SHRINES, _norm_id(i)) > 0


URN_REMOVE_WARNING = ("Each Sanguine Urn permanently adds +10 max health, so removing one probably "
                      "lowers max health by 10 (inferred, untested).")

# Older names (the list key is ShrinesUnlocked).
shrine_rows, unlock_shrine, remove_shrine = urn_rows, unlock_urn, remove_urn


def burrow_state(save, i):
    i = _norm_id(i)
    if _in(_list(save, ACTIVATED), i):
        return ACTIVE
    if _in(_list(save, FOUND), i):
        return FOUND_ONLY
    return NOT_FOUND


def burrow_rows(save, map_data):
    """[{id, name, area, state, in_found, in_activated, known}]."""
    found = [_norm_id(x) for x in _list(save, FOUND)]
    act = [_norm_id(x) for x in _list(save, ACTIVATED)]
    seen = sorted(_game_written_ids(save, (FOUND, ACTIVATED)) - set(found) - set(act))
    ids = list(dict.fromkeys([i for i in found + act if i] + list(map_data["kebbit_burrows"]) + seen))
    return [{"id": i, "name": point_name(map_data, "kebbit_burrows", i),
             "area": point_area(map_data, "kebbit_burrows", i), "state": burrow_state(save, i),
             "in_found": i in found, "in_activated": i in act, "known": i in map_data["kebbit_burrows"]}
            for i in ids]


def set_burrow_flags(save, map_data, i, found=None, activated=None):
    """Set the Found and/or Activated flag independently (None = leave as is).
    Adding needs a catalog/game ID; removing works for any ID. Returns True if anything changed."""
    changed = False
    for key, want in ((FOUND, found), (ACTIVATED, activated)):
        if want is None:
            continue
        if want:
            changed |= _append(save, key, _check_id(save, map_data, "kebbit_burrows", i))
        else:
            changed |= _discard(save, key, _norm_id(i)) > 0
    return changed


def remove_burrow(save, i):
    """Remove a burrow from both Found and Activated."""
    n = _norm_id(i)
    return bool(_discard(save, FOUND, n) + _discard(save, ACTIVATED, n))


# ---- suggestion after a quest revert -------------------------------------------------------------

def suggest_fog_reset(save, questline_data, map_data):
    """Areas whose gating main quest is not started (state 0 / no record) but whose fog is revealed.

    Returns [{area, quest_id, quest_name, bits (revealed ones), urns, burrows, gate_note,
    gate_confidence}] where urns (Sanguine Urns) / burrows are the IDs of that area in the save.
    Never edits anything: reverting a quest must not change the fog by itself.
    """
    from . import questline as dw_questline  # local: keeps this module importable on its own
    names = (questline_data or {}).get("quest_names", {})
    v = fog_bitmap(save)
    out = []
    for a in map_data["areas"]:
        q = a.get("gated_by_quest")
        if not q or dw_questline.quest_state(save, q) != 0:
            continue
        bits = [b for b in a["bits"] if b and v >> b & 1]
        if not bits:
            continue
        urns = [i for i in (_norm_id(x) for x in _list(save, SHRINES))
                   if point_area(map_data, "shrines", i) == a["name"]]
        burrows = [r["id"] for r in burrow_rows(save, map_data)
                   if r["state"] != NOT_FOUND and r["area"] == a["name"]]
        out.append({"area": a["name"], "quest_id": q, "quest_name": names.get(q, q), "bits": bits,
                    "urns": urns, "burrows": burrows, "gate_note": a.get("gate_note", ""),
                    "gate_confidence": a.get("gate_confidence", "")})
    return out


def apply_fog_reset(save, suggestions, include_points=True):
    """Hide the suggested bits; with include_points also drop that area's urns and burrows."""
    for s in suggestions:
        set_bits(save, s["bits"], False)
        if include_points:
            for i in s["urns"]:
                remove_urn(save, i)
            for i in s["burrows"]:
                remove_burrow(save, i)
