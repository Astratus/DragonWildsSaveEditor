"""Verify the bundled map and lodestone data against the installed game's world level.

    python -m dragonwilds_save_editor.gamedata.world [--game-dir FOLDER] [--json]

Development/verification tool (not used at runtime). It reads ``/Game/Maps/World/L_World`` and
its World Partition cell packages and checks data/map_points.json and data/lodestones.json:

* Landmark registry: the L_World export of class ``/Script/Dominion.GameplayObjectRegistry``.
  Its property 4 is an array of landmark structs: 0 location (3 x float64), 1 category (uint8:
  6 = Sanguine Urn, 8 = kebbit burrow, ...), 2 InternalName (FName: the 32-hex ID the save
  stores), 3 display name (FText), 4 FGuid, 5 struct {0: gameplay tag FName}, 6 needs-discovery
  (bool), 7 discover distance (float).
* Map regions: the ``BP_MapRegion_C`` exports in L_World: optional property 0 = struct
  {quest-entry tag}, property 1 = RegionID (uint8; fog bit N = RegionID N), property 2 = display
  name (FText into a string table); the area is the ``Location.Region.*`` FName the export uses.
* Fixed lodestones: ``BP_WorldLodestone_C`` actors in the cell packages under
  ``/Game/Maps/World/L_World/_Generated_/``. The actor export holds its
  GameplayObjectRegistryIdentifier as an FGuid (matched by bytes); its child export
  ``DefaultSceneRoot`` holds the location as 3 x float64 (matched by value, within 1 uu); its
  ``CTX_*`` FName references are its tags.

The layouts were found by inspecting this game build (unversioned properties carry no names);
each array is parsed element by element to its exact end, so a layout change shows up as an
error rather than wrong values.
"""

import argparse
import json
import re
import struct
import sys

from .. import paths
from . import install, stringtable, uprops
from .game import GameData

WORLD = "/Game/Maps/World/L_World"
CELLS = "/Maps/World/L_World/_Generated_/"
LODESTONE_PKG = "/Game/Gameplay/World/Misc/BP_WorldLodestone"
CAT_SHRINE, CAT_KEBBIT = 6, 8
AREA_BY_TAG = {"Brynmoor": "Brynmoor", "Ghornfell": "Ghornfell", "Fellhollow": "Fellhollow",
               "DowdunReach": "Dowdun Reach", "UmbralSands": "Umbral Sands",
               "ScornedWilderness": "Scorned Wilderness"}
TAG_BY_AREA = {v: k for k, v in AREA_BY_TAG.items()}
MAX_LOCATION_DEV = 1.0


def guid_bytes(h):
    """32-hex ID -> the 16 bytes of the FGuid (four little-endian uint32)."""
    return struct.pack("<4I", *[int(h[i:i + 8], 16) for i in range(0, 32, 8)])


class _Cursor:
    def __init__(self, gd, pkg, b, p=0):
        self.gd, self.pkg, self.b, self.p = gd, pkg, b, p
        self._tables = {}

    def unpack(self, fmt):
        v = struct.unpack_from(fmt, self.b, self.p)
        self.p += struct.calcsize(fmt)
        return v

    def u8(self):
        return self.unpack("<B")[0]

    def i32(self):
        return self.unpack("<i")[0]

    def raw(self, n):
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def fname(self):
        i, n = self.unpack("<II")
        s = self.pkg.names[i & 0x3FFFFFFF]
        return s if not n else "%s_%d" % (s, n - 1)

    def fstr(self):
        n = self.i32()
        if n >= 0:
            return self.raw(n)[:-1].decode("utf-8") if n else ""
        return self.raw(-2 * n)[:-2].decode("utf-16-le")

    def header(self):
        present, self.p = uprops.read_header(self.b, self.p)
        return present

    def ftext(self):
        """FText -> display string or None (histories -1, 0, 3 (format: its pattern), 11)."""
        self.i32()
        h = struct.unpack_from("<b", self.b, self.p)[0]
        self.p += 1
        if h == -1:
            return self.fstr() if self.i32() else None
        if h == 0:
            self.fstr()
            self.fstr()
            return self.fstr()
        if h == 11:
            table, key = self.fname(), self.fstr()
            return _string(self.gd, table, key)
        if h == 3:
            fmt = self.ftext()
            for _ in range(self.i32()):
                self.fstr()
                t = self.u8()
                if t in (0, 1, 3):
                    self.raw(8)
                elif t == 2:
                    self.raw(4)
                elif t == 4:
                    self.ftext()
                else:
                    raise ValueError("FText argument type %d" % t)
            return fmt
        raise ValueError("FText history %d" % h)

    def tag_struct(self):
        tag = None
        for _i, zero in self.header():
            if not zero:
                tag = self.fname()
        return tag


_TABLES = {}


def _string(gd, table, key):
    if (id(gd), table) not in _TABLES:
        pk = gd.package(table.split(".")[0])
        _TABLES[(id(gd), table)] = stringtable.decode(pk, pk.exports[0])[1] if pk else {}
    v = _TABLES[(id(gd), table)].get(key)
    return re.sub(r"\s+", " ", v).strip() if v is not None else None


def _fname_refs(pkg, b, prefix):
    out = set()
    for o in range(len(b) - 7):
        i, n = struct.unpack_from("<II", b, o)
        if n == 0 and i < len(pkg.names) and pkg.names[i].startswith(prefix):
            out.add(pkg.names[i])
    return sorted(out)


def _class_of(gd, pkg, e):
    return gd.resolve_object(pkg, e.klass) or ""


def read_landmarks(gd):
    """The L_World landmark registry: [{id, category, location, name, tag, needs_discovery,
    discover_distance}]."""
    pk = gd.package(WORLD)
    reg = next(e for e in pk.exports if _class_of(gd, pk, e).endswith("Dominion.GameplayObjectRegistry"))
    c = _Cursor(gd, pk, pk.export_data(reg))
    top = c.header()
    if [i for i, _ in top][:1] != [4]:
        raise ValueError("unexpected landmark registry layout: %s" % top)
    readers = (lambda: c.unpack("<3d"), c.u8, c.fname, c.ftext, lambda: c.raw(16).hex(),
               c.tag_struct, c.u8, lambda: c.unpack("<f")[0])
    keys = ("location", "category", "id", "name", "guid", "tag", "needs_discovery", "discover_distance")
    out = []
    for _ in range(c.i32()):
        d = {}
        for i, zero in c.header():
            d[keys[i]] = None if zero else readers[i]()
        out.append(d)
    return out


def read_map_regions(gd):
    """{RegionID: [{actor, name, area, quest_tag}]} from the BP_MapRegion_C exports in L_World."""
    pk = gd.package(WORLD)
    out = {}
    for e in pk.exports:
        if not _class_of(gd, pk, e).endswith("BP_MapRegion.BP_MapRegion_C"):
            continue
        b = pk.export_data(e)
        c = _Cursor(gd, pk, b)
        present = c.header()
        quest = c.tag_struct() if present and present[0][0] == 0 else None
        if [i for i, _ in present if i in (1, 2)] != [1, 2]:
            raise ValueError("unexpected map region layout in %s: %s" % (e.name, present))
        rid = c.u8()
        name = c.ftext()
        area = _fname_refs(pk, b, "Location.Region.")
        out.setdefault(rid, []).append({
            "actor": e.name, "name": name, "quest_tag": quest,
            "area": AREA_BY_TAG.get(area[0].split(".")[2]) if area else None})
    return out


def read_world_lodestones(gd, ids):
    """For each 32-hex id in `ids`: {cell, actor, tags, root bytes} of the BP_WorldLodestone_C
    actor whose export holds that FGuid; plus the number of such actors in the level."""
    found, actors = {}, 0
    for rel in sorted(p for p in gd.files if CELLS in p):
        cp = gd.package(rel)
        if LODESTONE_PKG not in cp.imported_package_names:
            gd._cache.pop(rel, None)
            continue
        for e in cp.exports:
            if not _class_of(gd, cp, e).endswith("BP_WorldLodestone.BP_WorldLodestone_C"):
                continue
            actors += 1
            b = cp.export_data(e)
            root = next((x for x in cp.exports if x.outer == e.index and x.name == "DefaultSceneRoot"), None)
            for h in ids:
                if guid_bytes(h) in b:
                    found[h] = {"cell": cp.name.rsplit("/", 1)[-1], "package": cp.name, "actor": e.name,
                                "tags": _fname_refs(cp, b, "CTX_"),
                                "root": cp.export_data(root) if root else b""}
        gd._cache.pop(rel, None)
    return found, actors


def _closest_vector(b, want):
    best = None
    for o in range(max(0, len(b) - 23)):
        v = struct.unpack_from("<3d", b, o)
        dev = max(abs(x - y) for x, y in zip(v, want))
        if dev == dev and (best is None or dev < best[0]):
            best = (dev, list(v))
    return best or (float("inf"), None)


def load_json(name):
    with open(paths.resource_path("data", name), encoding="utf-8") as f:
        return json.load(f)


def verify(gd, map_points=None, lodestones=None):
    """Compare the bundled data with the install. Returns a report dict; report["problems"]
    lists every disagreement (empty = everything checked agrees)."""
    mp = map_points or load_json("map_points.json")
    ls = (lodestones or load_json("lodestones.json"))["lodestones"]
    problems, rep = [], {}
    marks = read_landmarks(gd)
    by_id = {m["id"]: m for m in marks if m.get("id")}
    for kind, cat in (("shrines", CAT_SHRINE), ("kebbit_burrows", CAT_KEBBIT)):
        js = {e["id"]: e for e in mp[kind]}
        inst = {m["id"] for m in marks if m.get("category") == cat}
        missing = sorted(set(js) - set(by_id))
        wrong = sorted(i for i in js if i in by_id and by_id[i]["category"] != cat)
        extra = sorted(inst - set(js))
        tag_bad = []
        if kind == "kebbit_burrows":
            tag_bad = sorted(i for i, e in js.items() if i in by_id and by_id[i].get("tag")
                             != "Agility.KebbitBurrow.Region." + TAG_BY_AREA.get(e.get("area"), "?"))
        rep[kind] = {"json": len(js), "install": len(inst), "missing_in_install": missing,
                     "wrong_category": wrong, "only_in_install": extra, "area_tag_differs": tag_bad}
        for what, lst in (("missing in the install", missing), ("wrong landmark category", wrong),
                          ("in the install only", extra), ("area tag differs", tag_bad)):
            if lst:
                problems.append("%s: %s: %s" % (kind, what, ", ".join(lst)))
    regions = read_map_regions(gd)
    fog = {"install_region_ids": sorted(regions), "differs": []}
    for fb in mp["fog_bits"]:
        bit = fb["bit"]
        if bit == 0:
            if 0 in regions:
                fog["differs"].append("bit 0 has a map region in the install")
            continue
        r = regions.get(bit) or []
        if len(r) != 1 or r[0]["name"] != fb["region_name"] or r[0]["area"] != fb["area"]:
            fog["differs"].append("bit %d: json %r/%r, install %s" % (bit, fb["region_name"], fb["area"],
                                                                      [(x["name"], x["area"]) for x in r]))
    extra_bits = sorted(set(regions) - {fb["bit"] for fb in mp["fog_bits"]})
    if extra_bits:
        fog["differs"].append("map regions without a fog_bits entry: %s" % extra_bits)
    rep["fog_bits"] = fog
    problems += ["fog_bits: " + d for d in fog["differs"]]
    found, actors = read_world_lodestones(gd, [x["id"] for x in ls])
    lrep = {"install_actors": actors, "json": len(ls), "entries": []}
    for x in ls:
        f = found.get(x["id"])
        if not f:
            problems.append("lodestone %s (%s): id not found in the install" % (x["id"], x["name"]))
            lrep["entries"].append({"id": x["id"], "found": False})
            continue
        dev, loc = _closest_vector(f["root"], x["location"])
        e = {"id": x["id"], "found": True, "actor_ok": f["actor"] == x.get("actor"),
             "cell_ok": f["cell"] == x.get("cell"), "tags_ok": f["tags"] == sorted(x.get("tags") or []),
             "location_dev": dev, "install_location": loc, "package": f["package"]}
        lrep["entries"].append(e)
        for k in ("actor_ok", "cell_ok", "tags_ok"):
            if not e[k]:
                problems.append("lodestone %s: %s differs" % (x["name"], k[:-3]))
        if dev > MAX_LOCATION_DEV:
            problems.append("lodestone %s: location differs by %.3f uu" % (x["name"], dev))
        elif dev:
            problems.append("lodestone %s: location differs by %.6f uu (install %r)" % (x["name"], dev, loc))
    if actors != len(ls):
        problems.append("lodestones: %d BP_WorldLodestone_C actors in the install, %d in the json"
                        % (actors, len(ls)))
    rep["lodestones"] = lrep
    rep["problems"] = problems
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--game-dir", help="the game's installation folder (default: detect it)")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = ap.parse_args(argv)
    with GameData(install.find_paks_dir(a.game_dir)) as gd:
        rep = verify(gd)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        for kind in ("shrines", "kebbit_burrows"):
            r = rep[kind]
            print("%-15s json %3d  install %3d" % (kind, r["json"], r["install"]))
        print("fog_bits        install region ids %s" % rep["fog_bits"]["install_region_ids"])
        for e in rep["lodestones"]["entries"]:
            print("lodestone %s  found=%s  location dev %s  install %r"
                  % (e["id"], e["found"], e.get("location_dev"), e.get("install_location")))
        print("problems: %s" % (("\n  - " + "\n  - ".join(rep["problems"])) if rep["problems"] else "none"))
    return 1 if rep["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
