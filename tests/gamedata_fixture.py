"""Writers for tiny synthetic game installs (IoStore .utoc/.ucas, zen packages, a pak), used by
the gamedata and catalog tests. No real game data: every byte is produced here, following the
layouts the reader expects (docs/research/gamedata_provenance.md).

    root = make_game(tmpdir)          # a fake install root with RSDragonwilds/Content/Paks
"""

import json
import os
import struct

from dragonwilds_save_editor.gamedata import zen

NONE = 0xFFFFFFFF
BLOCK = 0x400          # small blocks so entries span several of them
SCRIPT = 1 << 62       # FPackageObjectIndex kind: script import


# --- primitives --------------------------------------------------------------------------------

def fstring(s):
    if s == "":
        return struct.pack("<i", 0)
    b = s.encode("utf-8") + b"\0"
    return struct.pack("<i", len(b)) + b


def name_batch(names):
    data = b"".join(n.encode("latin-1") for n in names)
    hdrs = b"".join(struct.pack(">H", len(n)) for n in names)
    return (struct.pack("<iIQ", len(names), len(data), 0) + b"\0" * (8 * len(names)) + hdrs + data)


def header(indices, zeros=()):
    """Unversioned property header for the sorted property `indices` (gaps < 128). `zeros` are
    indices flagged as all-zero (not written)."""
    if not indices:
        return struct.pack("<H", 0x100)
    runs, start, prev = [], indices[0], indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
            continue
        runs.append((start, prev))
        start = prev = i
    runs.append((start, prev))
    out, pos, zbits = b"", 0, []
    for n, (a, b) in enumerate(runs):
        num = b - a + 1
        has_zero = any(a <= z <= b for z in zeros)
        if has_zero:
            zbits += [1 if i in zeros else 0 for i in range(a, b + 1)]
        v = (a - pos) | (0x80 if has_zero else 0) | (0x100 if n == len(runs) - 1 else 0) | (num << 9)
        out += struct.pack("<H", v)
        pos = b + 1
    if zbits:
        m = sum(bit << i for i, bit in enumerate(zbits))
        nbytes = 1 if len(zbits) <= 8 else 2 if len(zbits) <= 16 else ((len(zbits) + 31) // 32) * 4
        out += m.to_bytes(nbytes, "little")
    return out


class Names:
    """A package name map being built; ``fname(s)`` returns the 8-byte FName."""

    def __init__(self, *names):
        self.names = []
        for n in names:
            self.index(n)

    def index(self, s):
        if s not in self.names:
            self.names.append(s)
        return self.names.index(s)

    def fname(self, s):
        return struct.pack("<II", self.index(s), 0)


def text_st(names, table, key):
    return struct.pack("<Ib", 0, 11) + names.fname(table) + fstring(key)


def text_base(source, key="0123456789ABCDEF0123456789ABCDEF"):
    return struct.pack("<Ib", 0, 0) + fstring("") + fstring(key) + fstring(source)


# --- zen package -------------------------------------------------------------------------------

def zen_package(package_name, names, exports, imported_packages=()):
    """exports: [(name, class FPackageObjectIndex, data bytes)]. Returns the package bytes."""
    names.index(package_name)
    for e in exports:
        names.index(e[0])
    nb = name_batch(names.names)
    off = zen.SUMMARY_SIZE + 8 + len(nb)
    hashes_off = off
    imports_off = hashes_off             # no imported public export hashes
    exports_off = imports_off            # no imports
    bundle_off = exports_off + zen.EXPORT_ENTRY_SIZE * len(exports)
    imported_names_off = bundle_off
    ipn = name_batch(list(imported_packages)) + b"".join(struct.pack("<i", 0) for _ in imported_packages)
    header_size = imported_names_off + len(ipn)
    table, data = b"", b""
    for i, (ename, klass, edata) in enumerate(exports):
        table += struct.pack("<QQIIQQQQQIB", len(data), len(edata), names.index(ename), 0,
                             zen.NULL_INDEX, klass, zen.NULL_INDEX, zen.NULL_INDEX, 0x1000 + i, 0, 0)
        table += b"\0" * (zen.EXPORT_ENTRY_SIZE - 69)
        data += edata
    summary = struct.pack("<IIIIIIiiiiiii", 0, header_size, names.index(package_name), 0,
                          zen.PKG_UNVERSIONED_PROPERTIES, header_size, hashes_off, imports_off,
                          exports_off, bundle_off, bundle_off, bundle_off, imported_names_off)
    out = summary + struct.pack("<ii", 0, 0) + nb + table + ipn
    assert len(out) == header_size
    return out + data


def script_objects(classes):
    """global.utoc script-objects chunk for {class name: global index} under /Script/Dominion."""
    names = ["/Script/Dominion"] + list(classes)
    out = name_batch(names) + struct.pack("<i", len(names))
    pkg_idx = SCRIPT | 1
    out += struct.pack("<IIQQQ", 0, 0, pkg_idx, zen.NULL_INDEX, zen.NULL_INDEX)
    for i, (cls, gidx) in enumerate(classes.items()):
        out += struct.pack("<IIQQQ", i + 1, 0, gidx, pkg_idx, zen.NULL_INDEX)
    return out


# --- IoStore -----------------------------------------------------------------------------------

def _dir_index(files):
    """files: {container path: entry index}."""
    strings, dirs, flist = [], [[NONE, NONE, NONE, NONE]], []

    def s(x):
        if x not in strings:
            strings.append(x)
        return strings.index(x)

    def child(di, name):
        c = dirs[di][1]
        while c != NONE:
            if strings[dirs[c][0]] == name:
                return c
            c = dirs[c][2]
        dirs.append([s(name), NONE, dirs[di][1], NONE])
        dirs[di][1] = len(dirs) - 1
        return len(dirs) - 1

    for path, entry in files.items():
        parts = path.split("/")
        di = 0
        for p in parts[:-1]:
            di = child(di, p)
        flist.append([s(parts[-1]), dirs[di][3], entry])
        dirs[di][3] = len(flist) - 1
    out = fstring("../../../")
    out += struct.pack("<I", len(dirs)) + b"".join(struct.pack("<4I", *d) for d in dirs)
    out += struct.pack("<I", len(flist)) + b"".join(struct.pack("<3I", *f) for f in flist)
    out += struct.pack("<I", len(strings)) + b"".join(fstring(x) for x in strings)
    return out


def write_iostore(utoc_path, entries, files=None):
    """entries: [(12-byte chunk id, data)]; files: {container path: entry index}."""
    ucas, offlen = b"", []
    for _cid, data in entries:
        offlen.append((len(ucas), len(data)))
        ucas += data
    n_blocks = (len(ucas) + BLOCK - 1) // BLOCK
    blocks = b""
    for i in range(n_blocks):
        size = min(BLOCK, len(ucas) - i * BLOCK)
        blocks += (i * BLOCK).to_bytes(5, "little") + size.to_bytes(3, "little") \
            + size.to_bytes(3, "little") + b"\0"
    dir_index = _dir_index(files) if files else b""
    flags = 8 if files else 0
    hdr = bytearray(144)
    hdr[0:16] = b"-==--==--==--==-"
    hdr[16] = 8
    struct.pack_into("<9I", hdr, 20, 144, len(entries), n_blocks, 12, 0, 32, BLOCK, len(dir_index), 1)
    struct.pack_into("<Q", hdr, 56, 0x1234)
    hdr[80] = flags
    struct.pack_into("<IQI", hdr, 84, 0, 0xFFFFFFFFFFFFFFFF, 0)
    toc = bytes(hdr) + b"".join(cid for cid, _ in entries)
    toc += b"".join(o.to_bytes(5, "big") + n.to_bytes(5, "big") for o, n in offlen)
    toc += blocks + dir_index
    with open(utoc_path, "wb") as f:
        f.write(toc)
    with open(utoc_path[:-5] + ".ucas", "wb") as f:
        f.write(ucas)


def chunk_id(n, kind=1):
    return struct.pack("<QHBB", n, 0, 0, kind)


# --- pak ---------------------------------------------------------------------------------------

def write_pak(path, files):
    """files: {container path: bytes}; one directory level per file is enough here."""
    body, encoded, fdi_dirs = b"", b"", {}
    for name, data in files.items():
        d, fn = name.rsplit("/", 1)
        enc_off = len(encoded)
        encoded += struct.pack("<III", (1 << 31) | (1 << 30), len(body), len(data))
        body += b"\0" * 53 + data
        fdi_dirs.setdefault("/" + d + "/", []).append((fn, enc_off))
    fdi = struct.pack("<i", len(fdi_dirs))
    for d, fl in fdi_dirs.items():
        fdi += fstring(d) + struct.pack("<i", len(fl))
        for fn, off in fl:
            fdi += fstring(fn) + struct.pack("<i", off)
    idx_off = len(body)
    index = fstring("../../../") + struct.pack("<iQii", len(files), 0, 0, 1)
    fdi_off_pos = len(index)
    index += struct.pack("<qq", 0, len(fdi)) + b"\0" * 20 + struct.pack("<i", len(encoded)) + encoded
    fdi_off = idx_off + len(index)
    index = index[:fdi_off_pos] + struct.pack("<q", fdi_off) + index[fdi_off_pos + 8:]
    footer = b"\0" * 16 + b"\0" + struct.pack("<Iiqq", 0x5A6F12E1, 11, idx_off, len(index)) + b"\0" * 20 + b"\0" * 160
    assert len(footer) == 221
    with open(path, "wb") as f:
        f.write(body + index + fdi + footer)


# --- a tiny game -------------------------------------------------------------------------------

CLASSES = {"ItemData": SCRIPT | 0x10, "MagicAmmoData": SCRIPT | 0x11, "SkillData": SCRIPT | 0x12,
           "StringTable": SCRIPT | 0x13}
ST_ITEMS = "/Game/Gameplay/Items/ST_ItemNames.ST_ItemNames"

# Test schemas: ItemData (ID at 36) and SkillData (ID at 19); MagicAmmoData has none, so it
# goes through the partial decode + suffix alignment path.
SCHEMAS = {
    "ItemData": {"id_index": 36, "chain": ["ItemData"], "instances": 2, "schema": {
        "1": ["text"], "12": ["fix", 4], "17": ["struct"], "17/0": ["fix", 8], "20": ["arr"],
        "20/e": ["fix", 8], "25": ["fix", 4], "36": ["str"], "37": ["str"], "38": ["fix", 1]}},
    "SkillData": {"id_index": 19, "chain": ["SkillData"], "instances": 1, "schema": {
        "0": ["text"], "1": ["fix", 4], "19": ["str"], "20": ["str"]}},
    "BrokenData": {"chain": ["BrokenData"], "instances": 1, "error": "no schema fits"},
}

ITEM_IDS = {"ash": "AAAAAAAAAAAAAAAAAAAAAA", "sword": "DDDDDDDDDDDDDDDDDDDDDD",
            "rune": "BBBBBBBBBBBBBBBBBBBBBB", "thing": "GGGGGGGGGGGGGGGGGGGGGG",
            "skill": "KKKKKKKKKKKKKKKKKKKKKK"}


def _item(names, pid, internal, name_key=None, stack=None, category=None, filters=(), durability=None,
          soft_deleted=False, shift=0, lead=None):
    """Property bytes of an item export (ItemData layout shifted by `shift` own properties;
    `lead` = bytes of own property 0 when shift > 0)."""
    vals = {}
    if lead is not None:
        vals[0] = lead
    if name_key:
        vals[1 + shift] = text_st(names, ST_ITEMS, name_key)
    if stack is not None:
        vals[12 + shift] = struct.pack("<i", stack)
    if category:
        vals[17 + shift] = header([0]) + names.fname(category)
    if filters:
        vals[20 + shift] = struct.pack("<i", len(filters)) + b"".join(names.fname(f) for f in filters)
    if durability:
        vals[25 + shift] = struct.pack("<i", durability)
    vals[36 + shift] = fstring(pid)
    vals[37 + shift] = fstring(internal)
    if soft_deleted:
        vals[38 + shift] = b"\x01"
    idx = sorted(vals)
    return header(idx) + b"".join(vals[i] for i in idx) + b"\0\0\0\0"


def make_game(root, version="9.9.9.9", schemas=SCHEMAS):
    """Write a fake install under `root` and the test schemas to root/schemas.json.
    Returns (install root, schemas path)."""
    paks = os.path.join(root, "RSDragonwilds", "Content", "Paks")
    os.makedirs(paks, exist_ok=True)
    pkgs = {}

    def add(path, pkg_name, names, exports):
        pkgs["RSDragonwilds/" + path] = zen_package(pkg_name, names, exports)

    n = Names()
    st = header([]) + struct.pack("<i", 0) + fstring("ItemNames") + struct.pack("<i", 4)
    for k, v in (("AshLogs", "Ash Logs"), ("BronzeSword", "Bronze Sword"), ("AirRune", "Air Rune"),
                 ("Skill", "Farming")):
        st += fstring(k) + fstring(v)
    add("Content/Gameplay/Items/ST_ItemNames.uasset", "/Game/Gameplay/Items/ST_ItemNames", n,
        [("ST_ItemNames", CLASSES["StringTable"], st)])

    n = Names()
    add("Content/Gameplay/Items/Resources/ITEM_Resources_Wood_Ash.uasset",
        "/Game/Gameplay/Items/Resources/ITEM_Resources_Wood_Ash", n,
        [("ITEM_Resources_Wood_Ash", CLASSES["ItemData"],
          _item(n, ITEM_IDS["ash"], "res_ash", "AshLogs", 99, "Item.Resource"))])
    n = Names()
    add("Content/Gameplay/Items/Held/ITEM_Sword_Bronze.uasset", "/Game/Gameplay/Items/Held/ITEM_Sword_Bronze", n,
        [("ITEM_Sword_Bronze", CLASSES["ItemData"],
          _item(n, ITEM_IDS["sword"], "sword_bronze", "BronzeSword", None, durability=500))])
    n = Names()
    add("Content/Gameplay/Items/Deleted/ITEM_Unnamed_Thing.uasset",
        "/Game/Gameplay/Items/Deleted/ITEM_Unnamed_Thing", n,
        [("ITEM_Unnamed_Thing", CLASSES["ItemData"],
          _item(n, ITEM_IDS["thing"], "res_unnamed_thing", soft_deleted=True))])
    n = Names()
    add("Plugins/GameFeatures/UmbralSands/Content/Items/ITEM_Rune_Air.uasset", "/UmbralSands/Items/ITEM_Rune_Air", n,
        [("ITEM_Rune_Air", CLASSES["MagicAmmoData"],
          _item(n, ITEM_IDS["rune"], "rune_air", "AirRune", 9999, "Item.Equipment.Ammo.Rune",
                ["ItemFilter.Type.Equipment.Ammo.Rune"], shift=1, lead=struct.pack("<i", 7)))])
    n = Names()
    skill = header([0, 1, 19, 20]) + text_st(n, ST_ITEMS, "Skill") + struct.pack("<i", 99) \
        + fstring(ITEM_IDS["skill"]) + fstring("skill_farming") + b"\0\0\0\0"
    add("Content/Gameplay/Character/Player/Skills/SKILL_Farming.uasset",
        "/Game/Gameplay/Character/Player/Skills/SKILL_Farming", n,
        [("SKILL_Farming", CLASSES["SkillData"], skill)])
    n = Names()   # Art folder: never read by the catalog
    add("Content/Art/ITEM_NotReally.uasset", "/Game/Art/ITEM_NotReally", n,
        [("ITEM_NotReally", CLASSES["ItemData"], _item(n, "XXXXXXXXXXXXXXXXXXXXXX", "x"))])

    entries, files = [], {}
    for i, (path, data) in enumerate(sorted(pkgs.items())):
        entries.append((chunk_id(i + 1), data))
        files[path] = i
    write_iostore(os.path.join(paks, "RSDragonwilds-Windows.utoc"), entries, files)
    write_iostore(os.path.join(paks, "global.utoc"), [(chunk_id(0, 5), script_objects(CLASSES))])
    write_pak(os.path.join(paks, "RSDragonwilds-Windows.pak"),
              {"RSDragonwilds/Config/DefaultGame.ini":
               ("[/Script/EngineSettings.GeneralProjectSettings]\r\nProjectVersion=%s\r\n" % version).encode()})
    spath = os.path.join(root, "schemas.json")
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(schemas, f)
    return root, spath
