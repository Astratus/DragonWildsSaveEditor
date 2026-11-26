"""
lodestones - fast-travel lodestones in a Dragonwilds world save: view, plus
EXPERIMENTAL activate/deactivate of the 4 FIXED world lodestones.

Lodestone state is per WORLD (see docs/research/lodestones.md). The teleport list is
L_World / GameplayObjectRegistry.Lodestones: a TArray of tagged structs
{Location, RespawnLocation, Identifier}. Fixed world lodestones (BP_WorldLodestone_C,
catalogued in data/lodestones.json) and player-built ones (BP_BaseBuilding_Lodestone_C,
whose "Lodestone Component/GameplayObjectRegistryIdentifier" matches the entry) both live
there.

Edits (activate_lodestone / deactivate_lodestone) change only that one property, IN
MEMORY on a dw_spud.WorldFile; nothing is written until WorldFile.save() (which refuses
while the game runs and snapshots every character + world save first). Player-built
lodestones are never added or removed here: build/demolish them in game.

Usage:
    python -m dragonwilds_save_editor.lodestones "<world>.sav"            # table
    python -m dragonwilds_save_editor.lodestones "<world>.sav" --json     # machine-readable

Library:
    from dragonwilds_save_editor.lodestones import list_lodestones, load_catalog
    rows = list_lodestones("<world>.sav", load_catalog())
    w = WorldFile("<copy>.sav"); activate_lodestone(w, "<catalog id>"); w.save()
"""

import argparse
import json
import math
import os
import struct
import sys

from . import paths
from . import spud as dw_spud
from .spud import FormatError, WorldFile, decode_tagged_props, encode_fstring

CATALOG_PATH = paths.resource_path("data", "lodestones.json")
REGISTRY_CLASS = "/Script/Dominion.GameplayObjectRegistry"
BUILT_CLASS = "/Game/Gameplay/BaseBuilding/Actors/Props/BP_BaseBuilding_Lodestone.BP_BaseBuilding_Lodestone_C"
WORLD_CLASS = "/Game/Gameplay/World/Misc/BP_WorldLodestone.BP_WorldLodestone_C"
COMPONENT_CLASS_SUFFIX = "LodestoneComponent"
ZERO_GUID = "0" * 32
CELL = 12800.0          # RSACell12800_X<n>_Y<n> grid size (uu)
RESPAWN_Z_OFFSET = 145.0


def load_catalog(path=CATALOG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _vector(props):
    """Tagged Vector_NetQuantize (decode_tagged_props dicts X|Y|Z, DoubleProperty) -> (x, y, z)."""
    if not isinstance(props, list):
        raise FormatError("vector is not a tagged struct")
    vals = {}
    for d in props:
        if d["type"] != "DoubleProperty" or len(d["raw"]) != 8:
            raise FormatError("unexpected vector component %r %r" % (d["name"], d["type"]))
        vals[d["name"]] = struct.unpack("<d", d["raw"])[0]
    if sorted(vals) != ["X", "Y", "Z"]:
        raise FormatError("vector has components %r" % sorted(vals))
    return (vals["X"], vals["Y"], vals["Z"])


def parse_registry_record(raw):
    """Decode a GameplayObjectRegistry.Lodestones record.

    -> [{"index", "id", "location", "respawn_location", "span": (start, end)}]
    `span` is the byte range of the entry inside `raw` (after the u32 count), so a later
    editor can drop or copy whole entries. Raises FormatError if the layout is not the
    known one or the entries do not exactly tile the record."""
    raw = bytes(raw)
    if len(raw) < 4:
        raise FormatError("record too short")
    n = struct.unpack_from("<I", raw, 0)[0]
    p, out = 4, []
    for i in range(n):
        props, q = decode_tagged_props(raw, p, len(raw))
        d = {t["name"]: t["value"] for t in props}
        names = [t["name"] for t in props]
        if names != ["Location", "RespawnLocation", "Identifier"]:
            raise FormatError("entry %d has fields %r" % (i, names))
        if not isinstance(d["Identifier"], str) or len(d["Identifier"]) != 32:
            raise FormatError("entry %d has no GUID identifier" % i)
        out.append({"index": i, "id": d["Identifier"], "location": _vector(d["Location"]),
                    "respawn_location": _vector(d["RespawnLocation"]), "span": (p, q)})
        p = q
    if p != len(raw):
        raise FormatError("%d trailing bytes after %d lodestone entries" % (len(raw) - p, n))
    return out


def _type(name, *params):
    """UE 5.4 FPropertyTypeName."""
    return encode_fstring(name) + struct.pack("<I", len(params)) + b"".join(params)


def _tag(name, type_bytes, value, flags=0):
    return encode_fstring(name) + type_bytes + struct.pack("<IB", len(value), flags) + value


_VEC_TYPE = _type("StructProperty", _type("Vector_NetQuantize", _type("/Script/Engine")))
_GUID_TYPE = _type("StructProperty", _type("Guid", _type("/Script/CoreUObject")))


def _encode_vector(x, y, z):
    body = b"".join(_tag(n, _type("DoubleProperty"), struct.pack("<d", float(v)))
                    for n, v in zip("XYZ", (x, y, z)))
    return body + encode_fstring("None")


def _encode_guid(guid_hex):
    """32 hex digits (as dw_spud prints GUIDs: four u32 words) -> the 16 stored bytes."""
    h = str(guid_hex)
    if len(h) != 32:
        raise ValueError("GUID must be 32 hex digits: %r" % guid_hex)
    return struct.pack("<4I", *(int(h[i:i + 8], 16) for i in range(0, 32, 8)))


def encode_entry(guid_hex, location):
    """One registry entry exactly as the game writes it (byte-exact against every real
    entry, see tests/test_lodestones.py): Location, RespawnLocation (Z + 145), Identifier."""
    x, y, z = (float(v) for v in location)
    g = _encode_guid(guid_hex)
    return (_tag("Location", _VEC_TYPE, _encode_vector(x, y, z))
            + _tag("RespawnLocation", _VEC_TYPE, _encode_vector(x, y, z + RESPAWN_Z_OFFSET))
            + _tag("Identifier", _GUID_TYPE, g, 0x08)   # 0x08 = native-serialized struct
            + encode_fstring("None"))


def registry_object(world):
    for o in world.all_objects():
        if o.class_name == REGISTRY_CLASS:
            return o
    return None


def registry_entries(world):
    """Registry entries of an open WorldFile ([] if the world has no registry yet)."""
    reg = registry_object(world)
    if reg is None:
        return []
    prop = reg.prop("Lodestones")
    if prop is None or prop.raw is None:
        raise FormatError("GameplayObjectRegistry has no decodable Lodestones property")
    return parse_registry_record(prop.raw)


def lodestone_actors(world):
    """Every saved actor that carries a LodestoneComponent -> [{key, class, kind, id, ...}]."""
    out = []
    for o in world.all_objects():
        props = o.properties()   # flat: component members follow their component
        comp = next((p for p in props if p.component is not None
                     and p.component.class_name.endswith(COMPONENT_CLASS_SUFFIX)), None)
        if comp is None:
            continue
        gid = next((c.value for c in comp.component.props if c.name == "GameplayObjectRegistryIdentifier"), None)
        flat = {p.path: p.value for p in props if p.type != 40}
        out.append({
            "key": o.key, "container": o.level.name, "name": o.label, "class": o.short_class,
            "kind": "built" if o.class_name == BUILT_CLASS else ("world" if o.class_name == WORLD_CLASS else "other"),
            "id": gid, "health": flat.get("HealthComponent/AuthoritativeHealth"),
            "building_piece_id": flat.get("BuildingPieceID"), "ghosted": flat.get("bIsGhosted"),
        })
    return out


def cell_of(location):
    x, y = location[0], location[1]
    return "X%d_Y%d" % (math.floor(x / CELL), math.floor(y / CELL))


def list_lodestones(world, catalog=None):
    """State of every lodestone known from the save and the catalog (read-only).

    `world` is a path or an open WorldFile. Returns a list of rows:
      id, name, area, kind ("world" | "built" | "unknown"), registered (bool),
      location (from the save, else the catalog), cell, actor (object key or None),
      health, building_piece_id, issues ([str]).
    Catalogued world lodestones that are absent from the registry are included with
    registered=False (= not activated in this world, inferred)."""
    w = world if isinstance(world, WorldFile) else WorldFile(world)
    catalog = catalog if catalog is not None else load_catalog()
    cat = {c["id"]: c for c in catalog.get("lodestones", [])}
    entries = registry_entries(w)
    actors = {a["id"]: a for a in lodestone_actors(w) if a["id"] and a["id"] != ZERO_GUID}
    rows, seen = [], set()
    for e in entries:
        c, a = cat.get(e["id"]), actors.get(e["id"])
        issues = []
        if e["id"] in seen:
            issues.append("duplicate registry entry")
        seen.add(e["id"])
        if abs(e["respawn_location"][2] - e["location"][2] - RESPAWN_Z_OFFSET) > 0.01:
            issues.append("respawn offset is not +145")
        if c is not None:
            kind = "world"
            name, area = c["name"], c["area"]
        elif a is not None and a["kind"] == "built":
            kind, name, area = "built", "Built lodestone", None
        else:
            kind, name, area = "unknown", "Unknown lodestone", None
            issues.append("no catalogued world lodestone or saved actor has this id")
        rows.append({
            "id": e["id"], "name": name, "area": area, "kind": kind, "registered": True,
            "registry_index": e["index"], "location": e["location"], "cell": cell_of(e["location"]),
            "actor": a["key"] if a else None, "health": a["health"] if a else None,
            "building_piece_id": a["building_piece_id"] if a else None, "issues": issues,
        })
    for gid, a in actors.items():
        if gid not in seen:
            rows.append({
                "id": gid, "name": "Built lodestone" if a["kind"] == "built" else a["class"],
                "area": None, "kind": a["kind"], "registered": False, "registry_index": None,
                "location": None, "cell": None, "actor": a["key"], "health": a["health"],
                "building_piece_id": a["building_piece_id"],
                "issues": ["actor has an id but no registry entry"],
            })
            seen.add(gid)
    for gid, c in cat.items():
        if gid not in seen:
            rows.append({
                "id": gid, "name": c["name"], "area": c["area"], "kind": "world", "registered": False,
                "registry_index": None, "location": tuple(c["location"]), "cell": cell_of(c["location"]),
                "actor": None, "health": None, "building_piece_id": None, "issues": [],
            })
    return rows


# ---- EXPERIMENTAL edits (fixed world lodestones only) -------------------------------

class LodestoneEditError(ValueError):
    pass


def fixed_entry(lodestone_id, catalog=None):
    """The catalogued fixed lodestone with this id, or raise LodestoneEditError."""
    catalog = catalog if catalog is not None else load_catalog()
    want = str(lodestone_id).upper()
    for c in catalog.get("lodestones", []):
        if c["id"].upper() == want:
            return c
    raise LodestoneEditError("%s is not one of the %d fixed world lodestones in data/lodestones.json; "
                             "only those can be activated or removed here."
                             % (lodestone_id, len(catalog.get("lodestones", []))))


def _refuse_built(world, lodestone_id):
    for a in lodestone_actors(world):
        if a["id"] and a["id"] != ZERO_GUID and a["id"].upper() == lodestone_id.upper():
            raise LodestoneEditError(
                "%s belongs to a saved lodestone actor (%s, %s). Player-built lodestones are never "
                "added or removed here: build/demolish them in game." % (lodestone_id, a["class"], a["key"]))


def _registry_raw(world):
    reg = registry_object(world)
    if reg is None:
        raise LodestoneEditError("This world has no GameplayObjectRegistry yet (load it in game once).")
    prop = reg.prop("Lodestones")
    if prop is None or prop.raw is None:
        raise FormatError("GameplayObjectRegistry has no decodable Lodestones property")
    raw = bytes(prop.raw)
    return reg, raw, parse_registry_record(raw)


def _baseline(world):
    """[(id, entry bytes)] of the registry as LOADED (world.original), cached per loaded
    byte string. Removing then re-adding a stone before saving puts its original bytes back
    at its original position instead of appending a re-encoded copy."""
    cached = getattr(world, "_lodestone_baseline", None)
    if cached is not None and cached[0] is world.original:
        return cached[1]
    try:
        _, raw, entries = _registry_raw(type(world).from_bytes(world.original))
        base = [(e["id"], raw[e["span"][0]:e["span"][1]]) for e in entries]
    except (LodestoneEditError, FormatError):
        base = []
    world._lodestone_baseline = (world.original, base)
    return base


def _write_entries(world, reg, items, msg):
    """items = [(id, entry bytes)] -> rewrite the Lodestones property, then validate.

    Validation: the whole file is re-serialized and fully re-parsed (dw_spud
    WorldFile.validate_bytes), the object count must be unchanged and the re-parsed registry
    must list exactly `items`. On failure the property's previous bytes are put back and
    the error is raised. WorldFile.save() later re-checks that each edited property holds
    its LAST value, so repeated lodestone edits before one save are fine."""
    new_raw = struct.pack("<I", len(items)) + b"".join(b for _i, b in items)
    want = [i for i, _b in items]
    old_raw = bytes(reg.prop("Lodestones").raw)
    world.set_raw_property(reg, "Lodestones", new_raw)
    try:
        w2 = world.validate_bytes(world.to_bytes())   # static on WorldFile
        if w2.object_count() != world.object_count():
            raise FormatError("object count changed after %s" % msg)
        got = [e["id"] for e in registry_entries(w2)]
        if got != want:
            raise FormatError("registry after %s is %r, expected %r" % (msg, got, want))
    except Exception:
        world.set_raw_property(reg, "Lodestones", old_raw)
        raise
    return want


def activate_lodestone(world, catalog_entry, catalog=None):
    """EXPERIMENTAL: add a FIXED world lodestone to L_World GameplayObjectRegistry.Lodestones.

    `catalog_entry` is a data/lodestones.json entry (or its id); the catalog's own record is
    used. New entries are appended at the end with the catalog location. If the stone was in
    the registry when the file was loaded (i.e. it was removed earlier in this session), its
    original bytes go back at their original position, so remove + re-add is an exact no-op.
    Returns True if changed, False if already active. Raises LodestoneEditError for ids not
    in the fixed catalog or belonging to a built lodestone. Touches nothing else (no events,
    switches or quest state)."""
    lid = catalog_entry["id"] if isinstance(catalog_entry, dict) else str(catalog_entry)
    _refuse_built(world, lid)
    entry = fixed_entry(lid, catalog)
    lid = entry["id"]
    reg, raw, entries = _registry_raw(world)
    if any(e["id"] == lid for e in entries):
        return False
    items = [(e["id"], raw[e["span"][0]:e["span"][1]]) for e in entries]
    base = _baseline(world)
    base_ids = [i for i, _b in base]
    if lid in base_ids:
        k = base_ids.index(lid)
        later = set(base_ids[k + 1:])
        pos = next((n for n, (i, _b) in enumerate(items) if i in later), len(items))
        items.insert(pos, base[k])
    else:
        items.append((lid, encode_entry(lid, entry["location"])))
    _write_entries(world, reg, items, "activated lodestone %s (%s)" % (entry["name"], lid))
    return True


def deactivate_lodestone(world, lodestone_id, catalog=None):
    """EXPERIMENTAL: remove a FIXED world lodestone's registry entry; the rest keep their
    order and exact bytes. Returns True if changed, False if it was not active. Refuses ids
    not in the fixed catalog and ids of built lodestones. The game may re-register the
    stone when you next touch it or when its area loads."""
    lid = str(lodestone_id)
    _refuse_built(world, lid)
    entry = fixed_entry(lid, catalog)
    lid = entry["id"]
    reg, raw, entries = _registry_raw(world)
    if not any(e["id"] == lid for e in entries):
        return False
    _baseline(world)   # remember the loaded bytes before the first change
    items = [(e["id"], raw[e["span"][0]:e["span"][1]]) for e in entries if e["id"] != lid]
    _write_entries(world, reg, items, "removed lodestone %s (%s)" % (entry["name"], lid))
    return True


def summary(rows):
    return {
        "registered": sum(1 for r in rows if r["registered"]),
        "world_registered": sum(1 for r in rows if r["kind"] == "world" and r["registered"]),
        "world_total": sum(1 for r in rows if r["kind"] == "world"),
        "built": sum(1 for r in rows if r["kind"] == "built"),
        "issues": sum(len(r["issues"]) for r in rows),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="List lodestones in a Dragonwilds world save (read-only).")
    ap.add_argument("world", help="path to a world .sav (a copy is fine)")
    ap.add_argument("--json", action="store_true", help="print JSON rows")
    a = ap.parse_args(argv)
    rows = list_lodestones(a.world)
    if a.json:
        print(json.dumps({"summary": summary(rows), "rows": rows}, indent=1, default=list))
        return 0
    for r in rows:
        loc = "" if r["location"] is None else "(%.0f, %.0f, %.0f)" % tuple(r["location"])
        print("%-5s %-6s %-32s %-24s %-28s %s%s" % (
            "yes" if r["registered"] else "no", r["kind"], r["id"], r["name"], r["area"] or (r["cell"] or ""),
            loc, ("  !" + "; ".join(r["issues"])) if r["issues"] else ""))
    print(summary(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
