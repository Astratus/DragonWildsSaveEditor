"""spud: reader/writer for RuneScape: Dragonwilds world saves (SPUD .sav files).

Stdlib only (Python 3.12). Independently written (clean room, see
docs/research/spud_cleanroom.md). The container format follows sinbad/SPUD
(https://github.com/sinbad/SPUD, MIT licence, Copyright (c) Steve Streeting);
the Dragonwilds-specific details were worked out from real world saves.

Format summary (as found in the real files)
-------------------------------------------
* IFF-style chunks: 4-byte ASCII magic + u32 LE payload length + payload. The
  root is SAVE; its length is the file size minus 8. No checksum, no compression.
* Container chunks may carry header bytes before their first child (versions,
  names, spawn transforms). The child start is found by trying offsets until a
  run of valid child chunks ends exactly at the parent's end. Header bytes are
  kept verbatim.
    SAVE  -> INFO, GLOB, LVLS
    INFO  -> header (system version, engine versions, FText title, timestamp) + CINF
    GLOB  -> header FString level name + META, GOBS (NOBJ...), GLAI (leaf)
    LVLS  -> LEVL...
    LEVL  -> header FString name + 8 version bytes; META, LATS, SATS, DATS
    META  -> VERS, CNIX (class names), PNIX (property names), CLST
    CLST  -> CDVE... (1 header byte + one CDEF, or empty)
    LATS  -> NOBJ...   SATS -> SPWN...   DATS -> KILL... (FString name)
    NOBJ  -> header [u32 ClassID, FString Name, ...] + CORA?, PROP, CUST?
    SPWN  -> header [u32 ClassID, 16-byte GUID, transform..., ...] + CORA, PROP, CUST?
* CDEF = FString class name, u16 count, count x {u32 PropertyID, u32 PrefixID,
  u16 DataType}. IDs index the level's PNIX; classes index the level's CNIX.
* PROP = u32 n, n x u32 offsets, u32 data length, data. Values are in CDEF order.
* DataType 40 = nested component: u32 ClassID + a PROP-shaped block, or just
  0xFFFFFFFF for "no component".
* DataType 64 = opaque record holding Unreal FArchive data (TSet/TMap/TArray
  with tagged-property structs inside).
* ArrayOf (0x1000 | t) = u16 count + elements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
from datetime import datetime

from . import paths

__all__ = [
    "FormatError", "WorldFile", "WorldObject", "Property", "WORLD_SAVE_DIR",
    "type_name", "read_fstring", "encode_fstring", "decode_string_set",
    "encode_string_set", "decode_tag_map", "encode_tag_map", "decode_tagged_props",
]

WORLD_SAVE_DIR = os.path.join(paths.game_saved_dir(), "SaveGames")

PROGRESS_MANAGER_CLASS = "/Script/Dominion.WorldProgressManager"
CACHED_CHARACTERS_CLASS = "/Script/Dominion.CachedCharacterStates"
GLOBAL_LEVEL = "@GLOB"


class FormatError(ValueError):
    """The bytes are not a SPUD save this module understands."""


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------
ARRAY_FLAG = 0x1000
_TYPE_NAMES = {
    0: "UInt8", 1: "UInt16", 2: "UInt32", 3: "UInt64", 4: "Int8", 5: "Int16",
    6: "Int32", 7: "Int64", 8: "Float", 9: "Double", 20: "Vector", 21: "Rotator",
    22: "Transform", 23: "Guid", 29: "CustomStruct", 30: "String", 31: "Name",
    32: "Text", 40: "Component", 64: "Record",
}
_SCALAR_FMT = {0: "<B", 1: "<H", 2: "<I", 3: "<Q", 4: "<b", 5: "<h", 6: "<i", 7: "<q", 8: "<f", 9: "<d"}
_STRINGY = (30, 31)


def type_name(t):
    """Readable name for a SPUD storage type code (e.g. 0x1006 -> 'Array<Int32>')."""
    if t & ARRAY_FLAG:
        return "Array<%s>" % type_name(t & ~ARRAY_FLAG)
    return _TYPE_NAMES.get(t, "Type%d" % t)


# --------------------------------------------------------------------------
# Primitive helpers
# --------------------------------------------------------------------------
def _u32(buf, p):
    if p + 4 > len(buf):
        raise FormatError("unexpected end of data at %d" % p)
    return struct.unpack_from("<I", buf, p)[0]


def read_fstring(buf, pos):
    """Read an Unreal FString: int32 length incl. NUL (negative = UTF-16). -> (str, newpos)."""
    if pos + 4 > len(buf):
        raise FormatError("FString length runs past the end at %d" % pos)
    n = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if n == 0:
        return "", pos
    if n > 0:
        end = pos + n
        if end > len(buf) or buf[end - 1] != 0:
            raise FormatError("bad FString (length %d) at %d" % (n, pos - 4))
        return bytes(buf[pos:end - 1]).decode("latin-1"), end
    end = pos + (-n) * 2
    if end > len(buf) or buf[end - 2:end] != b"\x00\x00":
        raise FormatError("bad UTF-16 FString (length %d) at %d" % (n, pos - 4))
    return bytes(buf[pos:end - 2]).decode("utf-16-le"), end


def encode_fstring(s):
    """Encode an FString the way Unreal does: ASCII as 8-bit, otherwise UTF-16 (negative length)."""
    if s == "":
        return b"\x00\x00\x00\x00"
    if all(ord(c) < 128 for c in s):
        b = s.encode("ascii") + b"\x00"
        return struct.pack("<i", len(b)) + b
    b = s.encode("utf-16-le") + b"\x00\x00"
    return struct.pack("<i", -(len(b) // 2)) + b


def _guid_str(raw16):
    a, b, c, d = struct.unpack("<4I", raw16)
    return "%08X%08X%08X%08X" % (a, b, c, d)


# --------------------------------------------------------------------------
# Unreal tagged properties (inside type-64 records)
# --------------------------------------------------------------------------
_TAG_HAS_ARRAY_INDEX = 0x01
_TAG_HAS_GUID = 0x02
_TAG_HAS_EXTENSIONS = 0x04
_TAG_BINARY = 0x08
_TAG_BOOL_TRUE = 0x10
_TAG_KNOWN_FLAGS = 0x01 | 0x02 | 0x08 | 0x10 | 0x20


def _read_type_name(buf, p, depth=0):
    if depth > 16:
        raise FormatError("type name nested too deeply")
    name, p = read_fstring(buf, p)
    n = _u32(buf, p)
    p += 4
    if n > 64:
        raise FormatError("implausible type-parameter count %d" % n)
    params = []
    for _ in range(n):
        sub, p = _read_type_name(buf, p, depth + 1)
        params.append(sub)
    return (name, params), p


def _type_str(tn):
    name, params = tn
    return name if not params else "%s(%s)" % (name, ",".join(_type_str(x) for x in params))


def _encode_type_name(tn):
    name, params = tn
    out = encode_fstring(name) + struct.pack("<I", len(params))
    for sub in params:
        out += _encode_type_name(sub)
    return out


def decode_tagged_props(raw, p=0, end=None):
    """Decode UE5.4+ tagged properties from raw[p:end] up to and including the 'None' terminator.

    Each tag is: FString name, FPropertyTypeName (pre-order list of FString + u32 parameter
    count), u32 value size, u8 flags, [optional array index / guid], value bytes.
    Returns (list_of_dicts, position_after_None). Each dict has name, type (string),
    type_tree, size, flags, start/end of the value, raw (value bytes) and value (decoded
    where the type is simple, nested list for tagged structs, else None).
    """
    if end is None:
        end = len(raw)
    props = []
    while True:
        if p >= end:
            raise FormatError("tagged properties have no 'None' terminator")
        name, p = read_fstring(raw, p)
        if name == "None":
            return props, p
        tstart = p
        tree, p = _read_type_name(raw, p)
        size = _u32(raw, p)
        p += 4
        if p >= end:
            raise FormatError("tag %r truncated" % name)
        flags = raw[p]
        p += 1
        if flags & ~_TAG_KNOWN_FLAGS:
            raise FormatError("tag %r has unsupported flags 0x%02x" % (name, flags))
        array_index = 0
        if flags & _TAG_HAS_ARRAY_INDEX:
            array_index = struct.unpack_from("<i", raw, p)[0]
            p += 4
        if flags & _TAG_HAS_GUID:
            p += 16
        vstart, vend = p, p + size
        if vend > end:
            raise FormatError("tag %r value runs past its container" % name)
        value = _decode_tag_value(tree, flags, raw, vstart, vend)
        props.append({
            "name": name, "type": _type_str(tree), "type_tree": tree, "size": size,
            "flags": flags, "array_index": array_index, "type_start": tstart,
            "start": vstart, "end": vend, "raw": bytes(raw[vstart:vend]), "value": value,
        })
        p = vend


def _decode_tag_value(tree, flags, raw, s, e):
    t = tree[0]
    n = e - s
    try:
        if t == "BoolProperty":
            return bool(flags & _TAG_BOOL_TRUE)
        if t in ("StrProperty", "NameProperty", "SoftObjectProperty", "ObjectProperty") :
            v, q = read_fstring(raw, s)
            return v if q == e else None
        simple = {"IntProperty": ("<i", 4), "UInt32Property": ("<I", 4), "Int64Property": ("<q", 8),
                  "UInt64Property": ("<Q", 8), "FloatProperty": ("<f", 4), "DoubleProperty": ("<d", 8),
                  "Int16Property": ("<h", 2), "UInt16Property": ("<H", 2), "Int8Property": ("<b", 1)}
        if t in simple and simple[t][1] == n:
            return struct.unpack_from(simple[t][0], raw, s)[0]
        if t == "ByteProperty" and n == 1:
            return raw[s]
        if t == "StructProperty":
            if flags & _TAG_BINARY:
                if n == 16 and tree[1] and tree[1][0][0] == "Guid":
                    return _guid_str(raw[s:e])
                return None
            sub, q = decode_tagged_props(raw, s, e)
            return sub if q == e else None
    except (FormatError, struct.error):
        return None
    return None


def _tags_to_plain(props):
    """Tagged-property list -> plain dict (name -> value), recursing into structs."""
    out = {}
    for t in props:
        v = t["value"]
        if isinstance(v, list):
            v = _tags_to_plain(v)
        out[t["name"]] = v
    return out


def decode_string_set(raw):
    """Decode a record holding a TSet/TArray of strings: u32 prefix (0), u32 count, FString x count.

    Returns (prefix_bytes, names). Raises FormatError if the record is anything else.
    """
    raw = bytes(raw)
    if len(raw) < 8:
        raise FormatError("string-set record too short")
    prefix = raw[:4]
    if prefix != b"\x00\x00\x00\x00":
        raise FormatError("string-set record has a non-zero removal count")
    n = _u32(raw, 4)
    p = 8
    names = []
    for _ in range(n):
        s, p = read_fstring(raw, p)
        names.append(s)
    if p != len(raw):
        raise FormatError("string-set record has %d trailing bytes" % (len(raw) - p))
    return prefix, names


def encode_string_set(prefix, names):
    return bytes(prefix) + struct.pack("<I", len(names)) + b"".join(encode_fstring(n) for n in names)


def _encode_tag_key(tag):
    value = encode_fstring(tag)
    return (encode_fstring("TagName") + _encode_type_name(("NameProperty", [])) +
            struct.pack("<I", len(value)) + b"\x00" + value + encode_fstring("None"))


def decode_tag_map(raw, value_size=4):
    """Decode a TMap<FGameplayTag, value>: u32 prefix (0), u32 count, then per entry a
    tagged GameplayTag struct ('TagName' NameProperty ... 'None') and value_size value bytes.

    Returns (prefix_bytes, entries); each entry is a dict with tag, value (bytes),
    int / float interpretations (for 4-byte values) and key_raw (the exact key bytes).
    """
    raw = bytes(raw)
    if len(raw) < 8:
        raise FormatError("tag-map record too short")
    prefix = raw[:4]
    if prefix != b"\x00\x00\x00\x00":
        raise FormatError("tag-map record has a non-zero removal count")
    n = _u32(raw, 4)
    p = 8
    entries = []
    for _ in range(n):
        kstart = p
        props, p = decode_tagged_props(raw, p)
        tags = [x for x in props if x["name"] == "TagName"]
        if len(props) != 1 or not tags or not isinstance(tags[0]["value"], str):
            raise FormatError("tag-map key is not a plain GameplayTag")
        key_raw = raw[kstart:p]
        if p + value_size > len(raw):
            raise FormatError("tag-map value truncated")
        val = raw[p:p + value_size]
        p += value_size
        e = {"tag": tags[0]["value"], "value": val, "key_raw": key_raw}
        if value_size == 4:
            e["int"] = struct.unpack("<i", val)[0]
            e["float"] = struct.unpack("<f", val)[0]
        elif value_size == 8:
            e["int"] = struct.unpack("<q", val)[0]
            e["float"] = struct.unpack("<d", val)[0]
        entries.append(e)
    if p != len(raw):
        raise FormatError("tag-map record has %d trailing bytes" % (len(raw) - p))
    return prefix, entries


def encode_tag_map(prefix, entries):
    """Inverse of decode_tag_map. entries: dicts (tag, value[, key_raw]) or (tag, value_bytes) tuples."""
    out = [bytes(prefix), struct.pack("<I", len(entries))]
    for e in entries:
        if isinstance(e, dict):
            tag, val, key = e["tag"], e["value"], e.get("key_raw")
        else:
            tag, val = e
            key = None
        out.append(key if key is not None else _encode_tag_key(tag))
        out.append(bytes(val))
    return b"".join(out)


# --------------------------------------------------------------------------
# Chunk tree
# --------------------------------------------------------------------------
KNOWN_MAGICS = frozenset(
    b"SAVE INFO CINF SHOT GLOB META VERS CNIX PNIX CLST CDVE CDEF GOBS GLAI LVNI LVLS "
    b"LEVL LATS SATS DATS NOBJ SPWN KILL CORA PROP CUST".split())
CONTAINERS = frozenset(
    b"SAVE INFO GLOB META CLST CDVE GOBS LVLS LEVL LATS SATS DATS NOBJ SPWN".split())


def _is_magic(m, strict):
    if strict:
        return m in KNOWN_MAGICS
    return len(m) == 4 and all(48 <= c <= 57 or 65 <= c <= 90 for c in m)


class Chunk:
    """One IFF chunk. Containers have header + children; leaves have data."""

    __slots__ = ("magic", "header", "children", "data", "parent", "src", "dirty", "owner")

    def __init__(self, magic, header=b"", children=None, data=None):
        self.magic = magic
        self.header = header
        self.children = children
        self.data = data
        self.parent = None
        self.src = None      # original bytes of the whole chunk (for fast unedited output)
        self.dirty = True
        self.owner = None    # PropBlock for PROP chunks

    @property
    def is_container(self):
        return self.children is not None

    def child(self, magic):
        for c in self.children or ():
            if c.magic == magic:
                return c
        return None

    def mark_dirty(self):
        c = self
        while c is not None and not c.dirty:
            c.dirty = True
            c = c.parent

    def payload(self, rebuild=False):
        if self.children is None:
            if self.owner is not None:
                return self.owner.to_bytes(rebuild)
            return self.data
        return self.header + b"".join(c.to_bytes(rebuild) for c in self.children)

    def to_bytes(self, rebuild=False):
        if not rebuild and not self.dirty and self.src is not None:
            return self.src
        body = self.payload(rebuild)
        return self.magic + struct.pack("<I", len(body)) + body


def _chain(buf, s, e, strict):
    """Child chunk spans if [s, e) is exactly a sequence of chunks, else None."""
    out = []
    p = s
    while p < e:
        if e - p < 8:
            return None
        m = bytes(buf[p:p + 4])
        if not _is_magic(m, strict):
            return None
        n = struct.unpack_from("<I", buf, p + 4)[0]
        q = p + 8 + n
        if q > e:
            return None
        out.append((m, p, q))
        p = q
    return out


def _find_children(buf, s, e, min_hdr=0):
    """Smallest header length h >= min_hdr such that buf[s+h:e] chains exactly into chunks."""
    for strict in (True, False):
        for h in range(min_hdr, e - s):
            got = _chain(buf, s + h, e, strict)
            if got:
                return h, got
    return None


def _header_hint(buf, magic, s, e):
    """Lower bound for the header length of some containers (skips names that could
    otherwise be mistaken for chunk data)."""
    try:
        if magic in (b"LEVL", b"GLOB"):
            return read_fstring(buf, s)[1] - s
        if magic == b"NOBJ":
            return read_fstring(buf, s + 4)[1] - s
        if magic == b"SPWN":
            return 20
    except FormatError:
        return 0
    return 0


def parse_chunk(buf, p, end, parent=None):
    """Parse the chunk at p (must end by `end`) from a memoryview. Returns (Chunk, next position)."""
    if p + 8 > end:
        raise FormatError("chunk header past end at %d" % p)
    magic = bytes(buf[p:p + 4])
    n = struct.unpack_from("<I", buf, p + 4)[0]
    s, e = p + 8, p + 8 + n
    if e > end:
        raise FormatError("chunk %r at %d (length %d) overruns its parent" % (magic, p, n))
    if magic in CONTAINERS:
        if s == e:
            ch = Chunk(magic, b"", [])
        else:
            found = _find_children(buf, s, e, _header_hint(buf, magic, s, e))
            if found is None:
                raise FormatError("container %r at %d: no child chunks fit" % (magic.decode(), p))
            h, spans = found
            ch = Chunk(magic, bytes(buf[s:s + h]), [])
            for (_m, cp, _cq) in spans:
                sub, _ = parse_chunk(buf, cp, e, ch)
                ch.children.append(sub)
    else:
        ch = Chunk(magic, data=bytes(buf[s:e]))
    ch.parent = parent
    ch.src = buf[p:e]          # zero-copy view of the original bytes
    ch.dirty = False
    return ch, e


# --------------------------------------------------------------------------
# META (class/property tables)
# --------------------------------------------------------------------------
class ClassDef:
    __slots__ = ("name", "props")

    def __init__(self, name, props):
        self.name = name
        self.props = props   # list of (prop_id, prefix_id, data_type)


def _read_string_table(data):
    n = _u32(data, 0)
    p = 4
    out = []
    for _ in range(n):
        s, p = read_fstring(data, p)
        out.append(s)
    if p != len(data):
        raise FormatError("string table has trailing bytes")
    return out


def _read_cdef(data):
    name, p = read_fstring(data, 0)
    if p + 2 > len(data):
        raise FormatError("CDEF truncated")
    n = struct.unpack_from("<H", data, p)[0]
    p += 2
    if p + 10 * n != len(data):
        raise FormatError("CDEF %r: size does not match %d property defs" % (name, n))
    props = [struct.unpack_from("<IIH", data, p + 10 * i) for i in range(n)]
    return ClassDef(name, props)


class Meta:
    def __init__(self, chunk):
        cnix, pnix, clst = chunk.child(b"CNIX"), chunk.child(b"PNIX"), chunk.child(b"CLST")
        if cnix is None or pnix is None or clst is None:
            raise FormatError("META lacks CNIX/PNIX/CLST")
        self.class_names = _read_string_table(cnix.data)
        self.prop_names = _read_string_table(pnix.data)
        by_name = {}
        for cdve in clst.children:
            for c in (cdve.children if cdve.children is not None else [cdve]):
                if c.magic == b"CDEF":
                    cd = _read_cdef(c.data)
                    by_name[cd.name] = cd
        self.by_name = by_name

    def class_name(self, cid):
        if cid >= len(self.class_names):
            raise FormatError("class id %d out of range (%d classes)" % (cid, len(self.class_names)))
        return self.class_names[cid]

    def classdef(self, cid):
        name = self.class_name(cid)
        cd = self.by_name.get(name)
        if cd is None:
            raise FormatError("no class definition for %r" % name)
        return cd

    def pname(self, pid):
        if pid == 0xFFFFFFFF:
            return ""
        if pid >= len(self.prop_names):
            raise FormatError("property id %d out of range" % pid)
        return self.prop_names[pid]


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------
def decode_value(t, raw):
    """Decode a SPUD property value. Returns (value, ok)."""
    n = len(raw)
    try:
        if t in _SCALAR_FMT:
            f = _SCALAR_FMT[t]
            return (struct.unpack(f, raw)[0], True) if struct.calcsize(f) == n else (None, False)
        if t in (20, 21):
            if n == 24:
                return list(struct.unpack("<3d", raw)), True
            if n == 12:
                return list(struct.unpack("<3f", raw)), True
            return None, False
        if t == 22:
            if n == 80:
                return list(struct.unpack("<10d", raw)), True
            if n == 40:
                return list(struct.unpack("<10f", raw)), True
            return None, False
        if t == 23:
            return (_guid_str(raw), True) if n == 16 else (None, False)
        if t in _STRINGY:
            v, q = read_fstring(raw, 0)
            return (v, True) if q == n else (None, False)
        if t == 32:
            if n < 5:
                return None, False
            hist = struct.unpack_from("<b", raw, 4)[0]
            if hist == -1:
                has = _u32(raw, 5)
                if has == 0:
                    return ("", True) if n == 9 else (None, False)
                v, q = read_fstring(raw, 9)
                return (v, True) if q == n else (None, False)
            return None, False
        if t & ARRAY_FLAG:
            et = t & ~ARRAY_FLAG
            cnt = struct.unpack_from("<H", raw, 0)[0]
            p = 2
            out = []
            if et in _SCALAR_FMT:
                f = _SCALAR_FMT[et]
                sz = struct.calcsize(f)
                if 2 + cnt * sz != n:
                    return None, False
                return [struct.unpack_from(f, raw, 2 + i * sz)[0] for i in range(cnt)], True
            if et in _STRINGY:
                for _ in range(cnt):
                    v, p = read_fstring(raw, p)
                    out.append(v)
                return (out, True) if p == n else (None, False)
            if et == 23:
                if 2 + 16 * cnt != n:
                    return None, False
                return [_guid_str(raw[2 + 16 * i:18 + 16 * i]) for i in range(cnt)], True
            return None, False
    except (FormatError, struct.error):
        return None, False
    return None, False


class Property:
    """One property value of an object (or of one of its components)."""

    __slots__ = ("block", "index", "name", "prefix", "type", "path", "raw", "component")

    def __init__(self, block, index, name, prefix, t, path, raw, component):
        self.block = block
        self.index = index
        self.name = name
        self.prefix = prefix
        self.type = t
        self.path = path
        self.raw = raw
        self.component = component   # PropBlock for type 40 with a component, else None

    @property
    def type_name(self):
        return type_name(self.type)

    @property
    def value(self):
        if self.type == 40:
            return None if self.component is None else self.component.class_name
        return decode_value(self.type, self.raw)[0]

    def as_dict(self, max_raw=64):
        v = self.value
        d = {"path": self.path, "name": self.name, "prefix": self.prefix, "type": self.type,
             "type_name": self.type_name, "size": len(self.raw), "value": v}
        if self.type == 64 or v is None:
            d["raw"] = self.raw[:max_raw].hex()
            d["raw_truncated"] = len(self.raw) > max_raw
        return d

    def __repr__(self):
        return "<Property %s %s %d bytes>" % (self.path, self.type_name, len(self.raw))


class PropBlock:
    """A PROP payload (or a component's PROP-shaped body): offsets + data in CDEF order."""

    def __init__(self, meta, class_id, data, base_path, comp_prefix=b""):
        self.meta = meta
        self.class_id = class_id
        self.class_name = meta.class_name(class_id)
        self.classdef = meta.classdef(class_id)
        self.prefix_bytes = comp_prefix       # u32 class id for components, b"" for PROP
        self.src = data
        self.modified = False
        self.parent_prop = None
        n = _u32(data, 0)
        if 8 + 4 * n > len(data):
            raise FormatError("PROP offset table truncated")
        offs = list(struct.unpack_from("<%dI" % n, data, 4))
        dl = _u32(data, 4 + 4 * n)
        base = 8 + 4 * n
        if base + dl != len(data):
            raise FormatError("PROP data length %d does not match block size" % dl)
        defs = self.classdef.props
        if n != len(defs):
            raise FormatError("%s: %d offsets for %d property defs" % (self.class_name, n, len(defs)))
        ends = offs[1:] + [dl]
        if any(o > e for o, e in zip(offs, ends)) or (offs and offs[0] != 0):
            raise FormatError("%s: property offsets are not contiguous" % self.class_name)
        self.props = []
        for i, ((pid, pre, t), o, e) in enumerate(zip(defs, offs, ends)):
            name, prefix = meta.pname(pid), meta.pname(pre)
            path = "/".join(x for x in (base_path, prefix, name) if x)
            raw = bytes(data[base + o:base + e])
            comp = None
            if t == 40 and len(raw) != 4:
                if len(raw) < 12:
                    raise FormatError("%s: component %r too short" % (self.class_name, path))
                comp = PropBlock(meta, _u32(raw, 0), raw[4:], path, raw[:4])
            elif t == 40 and raw != b"\xff\xff\xff\xff":
                raise FormatError("%s: unexpected 4-byte component %r" % (self.class_name, path))
            prop = Property(self, i, name, prefix, t, path, raw, comp)
            if comp is not None:
                comp.parent_prop = prop
            self.props.append(prop)

    def iter_props(self):
        for p in self.props:
            yield p
            if p.component is not None:
                yield from p.component.iter_props()

    def body(self, rebuild=False):
        if not rebuild and not self.modified:
            return self.src
        vals = []
        for p in self.props:
            if p.component is not None:
                vals.append(p.component.to_bytes(rebuild))
            else:
                vals.append(p.raw)
        offs, o = [], 0
        for v in vals:
            offs.append(o)
            o += len(v)
        return (struct.pack("<I", len(vals)) + struct.pack("<%dI" % len(vals), *offs) +
                struct.pack("<I", o) + b"".join(vals))

    def to_bytes(self, rebuild=False):
        return self.prefix_bytes + self.body(rebuild)

    def mark_modified(self):
        b = self
        while b is not None:
            b.modified = True
            if b.parent_prop is None:
                break
            b = b.parent_prop.block
        return b   # the root (PROP) block


# --------------------------------------------------------------------------
# Objects and levels
# --------------------------------------------------------------------------
class WorldObject:
    """A named (NOBJ) or spawned (SPWN) object with its properties."""

    def __init__(self, level, chunk):
        self.level = level
        self.chunk = chunk
        self.kind = chunk.magic.decode()
        h = chunk.header
        self.class_id = _u32(h, 0)
        self.class_name = level.meta.class_name(self.class_id)
        if self.kind == "NOBJ":
            self.name = read_fstring(h, 4)[0]
            self.guid = None
            ident = self.name
        else:
            if len(h) < 20:
                raise FormatError("SPWN header too short")
            self.guid = _guid_str(h[4:20])
            self.name = None
            ident = self.guid
        self.key = "%s|%s" % (level.name, ident)
        prop = chunk.child(b"PROP")
        if prop is None:
            raise FormatError("object %s has no PROP chunk" % self.key)
        self.prop_chunk = prop
        self.block = PropBlock(level.meta, self.class_id, prop.data, "")
        prop.owner = self.block
        self._paths = None

    @property
    def short_class(self):
        return self.class_name.rsplit(".", 1)[-1].rsplit("/", 1)[-1]

    @property
    def label(self):
        return self.name if self.name is not None else self.guid

    def properties(self):
        """All properties, flattened: component properties follow their component."""
        return list(self.block.iter_props())

    def _path_map(self):
        if self._paths is None:
            m = {}
            for p in self.block.iter_props():
                m.setdefault(p.path, p)
            self._paths = m
        return self._paths

    def prop(self, path):
        return self._path_map().get(path)

    def __repr__(self):
        return "<WorldObject %s %s>" % (self.short_class, self.key)


class Level:
    def __init__(self, chunk, is_global):
        self.chunk = chunk
        self.is_global = is_global
        level_name = read_fstring(chunk.header, 0)[0] if chunk.header else ""
        self.level_name = level_name
        self.name = GLOBAL_LEVEL if is_global else level_name
        meta = chunk.child(b"META")
        if meta is None:
            raise FormatError("level %r has no META" % level_name)
        self.meta = Meta(meta)
        self.objects = []
        self.destroyed = []
        for c in chunk.children:
            if c.magic in (b"LATS", b"SATS", b"GOBS"):
                for o in c.children:
                    if o.magic in (b"NOBJ", b"SPWN"):
                        self.objects.append(WorldObject(self, o))
            elif c.magic == b"DATS":
                for k in c.children:
                    if k.magic == b"KILL":
                        self.destroyed.append(read_fstring(k.data, 0)[0])


# --------------------------------------------------------------------------
# Game hooks (patched in tests)
# --------------------------------------------------------------------------
def _dw_save():
    from . import save as dw_save   # local import: keeps this module importable on its own
    return dw_save


def _game_is_running():
    return _dw_save().game_is_running()


def _snapshot_saves(label):
    return _dw_save().snapshot_game_saves(label)


# --------------------------------------------------------------------------
# WorldFile
# --------------------------------------------------------------------------
class WorldFile:
    """A parsed world save. Edits are made in memory; save() writes them safely."""

    def __init__(self, path=None, data=None):
        self.path = path
        if data is None:
            if path is None:
                raise ValueError("need a path or data")
            with open(path, "rb") as f:
                data = f.read()
        self._load(bytes(data))
        self._disk_sha = hashlib.sha256(data).hexdigest() if path is not None and os.path.exists(path) else None

    @classmethod
    def from_bytes(cls, data, path=None):
        wf = cls.__new__(cls)
        wf.path = path
        wf._load(bytes(data))
        wf._disk_sha = None
        return wf

    def _load(self, data):
        if len(data) < 8 or data[:4] != b"SAVE":
            raise FormatError("not a SPUD save (no SAVE chunk)")
        n = struct.unpack_from("<I", data, 4)[0]
        if n + 8 != len(data):
            raise FormatError("SAVE length %d does not match file size %d" % (n, len(data)))
        self._orig = data
        self.root, _ = parse_chunk(memoryview(data), 0, len(data))
        self.levels = []
        glob = self.root.child(b"GLOB")
        if glob is not None:
            self.levels.append(Level(glob, True))
        lvls = self.root.child(b"LVLS")
        if lvls is not None:
            for c in lvls.children:
                if c.magic == b"LEVL":
                    self.levels.append(Level(c, False))
        self._objects = [o for lv in self.levels for o in lv.objects]
        self._by_key = {}
        for o in self._objects:
            if o.key in self._by_key:
                raise FormatError("duplicate object key %r" % o.key)
            self._by_key[o.key] = o
        self._expect = {}   # (object key, path) -> expected raw bytes after all edits

    # ---- basic access -------------------------------------------------------
    def to_bytes(self, rebuild=False):
        """Serialize. rebuild=True re-encodes every chunk instead of reusing unedited bytes."""
        return bytes(self.root.to_bytes(rebuild))

    def all_objects(self):
        return list(self._objects)

    def object_count(self):
        return len(self._objects)

    def level(self, name):
        for lv in self.levels:
            if lv.name == name:
                return lv
        return None

    def find_objects(self, class_substr="", name_substr=""):
        cs, ns = class_substr.lower(), name_substr.lower()
        return [o for o in self._objects
                if cs in o.class_name.lower() and ns in (o.label or "").lower()]

    def find_object(self, class_name):
        """First object whose full class path equals class_name, else whose short class
        name (after the last '.') equals it."""
        for o in self._objects:
            if o.class_name == class_name:
                return o
        for o in self._objects:
            if o.short_class == class_name:
                return o
        return None

    def object_by_key(self, key):
        return self._by_key.get(key)

    @property
    def dirty(self):
        return bool(self._expect)

    # Integration helpers (added when the GUI/lodestone callers moved to dw_spud).
    @property
    def original(self):
        """The bytes this WorldFile was parsed from (after a save: the bytes written)."""
        return self._orig

    def changed_on_disk(self):
        """True if self.path's bytes differ from what was opened/saved (False if unknown)."""
        if not self.path or self._disk_sha is None:
            return False
        try:
            with open(self.path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest() != self._disk_sha
        except OSError:
            return True

    # ---- generic edits --------------------------------------------------------
    def _resolve(self, obj, prop_path):
        if isinstance(obj, str):
            o = self.object_by_key(obj)
            if o is None:
                raise KeyError("no object %r" % obj)
            obj = o
        if self._by_key.get(obj.key) is not obj:
            raise ValueError("object does not belong to this WorldFile (stale after save?)")
        p = obj.prop(prop_path)
        if p is None:
            raise KeyError("%s has no property %r" % (obj.key, prop_path))
        return obj, p

    def set_raw_property(self, obj, prop_path, new_bytes):
        """Replace one property's value bytes (size may change). Offsets and every
        ancestor length are rebuilt on output. Returns True if the bytes changed."""
        obj, p = self._resolve(obj, prop_path)
        new_bytes = bytes(new_bytes)
        if p.type == 40:
            raise ValueError("refusing to replace a whole component (%s)" % prop_path)
        if p.type != 64 and p.type != 29:
            _v, ok = decode_value(p.type, new_bytes)
            if not ok:
                raise ValueError("new bytes are not a valid %s value" % p.type_name)
        if new_bytes == p.raw:
            return False
        p.raw = new_bytes
        p.block.mark_modified()
        obj.prop_chunk.mark_dirty()
        self._expect[(obj.key, p.path)] = new_bytes
        return True

    def set_scalar(self, obj, prop_path, value):
        """Set a scalar (types 0-9) property in place (same size). Returns True if changed."""
        obj, p = self._resolve(obj, prop_path)
        fmt = _SCALAR_FMT.get(p.type)
        if fmt is None:
            raise ValueError("%s is %s, not a scalar" % (prop_path, p.type_name))
        if p.type in (8, 9):
            value = float(value)
        else:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError("%s needs an integer" % prop_path)
            value = int(value)
        try:
            raw = struct.pack(fmt, value)
        except struct.error as e:
            raise ValueError("%r does not fit %s: %s" % (value, p.type_name, e)) from None
        return self.set_raw_property(obj, p.path, raw)

    # ---- verification ---------------------------------------------------------
    @staticmethod
    def validate_bytes(raw):
        """Fully parse raw bytes (every chunk, object and property). Returns the parsed
        WorldFile; raises FormatError on any inconsistency."""
        wf = WorldFile.from_bytes(raw)
        if wf.to_bytes(rebuild=True) != bytes(raw):
            raise FormatError("re-encoding the parsed file does not reproduce it")
        return wf

    @staticmethod
    def _skeleton(wf, skip_prop):
        """Every chunk header / leaf, in order, with PROP leaves replaced by a marker."""
        out = []
        stack = [wf.root]
        while stack:
            c = stack.pop()
            if c.children is not None:
                out.append((c.magic, c.header, len(c.children)))
                stack.extend(reversed(c.children))
            elif c.magic == b"PROP" and skip_prop:
                out.append((c.magic, None, None))
            else:
                out.append((c.magic, c.data, None))
        return out

    def _verify_new(self, new_wf):
        """Check a re-parsed output against the original file plus the recorded edits."""
        orig = WorldFile.from_bytes(self._orig)
        if new_wf.object_count() != orig.object_count():
            raise FormatError("object count changed: %d -> %d" % (orig.object_count(), new_wf.object_count()))
        if self._skeleton(new_wf, True) != self._skeleton(orig, True):
            raise FormatError("something other than property values changed")
        seen = set()
        for a, b in zip(orig.all_objects(), new_wf.all_objects()):
            if a.key != b.key or a.class_name != b.class_name:
                raise FormatError("object order/identity changed at %s" % a.key)
            pa, pb = a.properties(), b.properties()
            if [p.path for p in pa] != [p.path for p in pb]:
                raise FormatError("property layout of %s changed" % a.key)
            for x, y in zip(pa, pb):
                if x.type == 40:
                    continue
                want = self._expect.get((a.key, x.path), x.raw)
                if (a.key, x.path) in self._expect:
                    seen.add((a.key, x.path))
                if y.raw != want:
                    raise FormatError("%s %s: value is not what was expected" % (a.key, x.path))
        missing = set(self._expect) - seen
        if missing:
            raise FormatError("edits not found in output: %s" % sorted(missing))
        return True

    # ---- WorldProgressManager --------------------------------------------------
    def progress_manager(self):
        lv = self.level("L_World")
        objs = lv.objects if lv is not None else self._objects
        for o in objs:
            if o.class_name == PROGRESS_MANAGER_CLASS:
                return o
        return self.find_object(PROGRESS_MANAGER_CLASS)

    def _pm_prop(self, name):
        pm = self.progress_manager()
        if pm is None:
            raise LookupError("this world has no WorldProgressManager")
        p = pm.prop(name)
        if p is None:
            raise LookupError("WorldProgressManager has no %s" % name)
        return pm, p

    def defeated_bosses(self):
        return decode_string_set(self._pm_prop("DefeatedBossesInternalNames")[1].raw)[1]

    def world_hooks(self):
        return decode_string_set(self._pm_prop("WorldHooksTriggered")[1].raw)[1]

    def tagged_values(self):
        """[{tag, value (4 bytes), int, float, key_raw}] from TaggedWorldProgressValues."""
        return decode_tag_map(self._pm_prop("TaggedWorldProgressValues")[1].raw)[1]

    def progress_tags(self):
        return [e["tag"] for e in self.tagged_values()]

    def remove_defeated_boss(self, name):
        """Remove one internal boss name (e.g. 'ai_boss_imaru'). Returns False if absent."""
        pm, p = self._pm_prop("DefeatedBossesInternalNames")
        prefix, names = decode_string_set(p.raw)
        if name not in names:
            return False
        names = [n for n in names if n != name]
        return self.set_raw_property(pm, p.path, encode_string_set(prefix, names))

    def remove_progress_tag(self, tag):
        """Remove one TaggedWorldProgressValues entry. Returns False if absent."""
        pm, p = self._pm_prop("TaggedWorldProgressValues")
        prefix, entries = decode_tag_map(p.raw)
        keep = [e for e in entries if e["tag"] != tag]
        if len(keep) == len(entries):
            return False
        return self.set_raw_property(pm, p.path, encode_tag_map(prefix, keep))

    def set_tag_value(self, tag, value, as_float=False):
        """Set an existing tag's 4-byte value (int32, or float32 if as_float). Returns True
        if the bytes changed; KeyError if the tag is not present (adding is not supported)."""
        pm, p = self._pm_prop("TaggedWorldProgressValues")
        prefix, entries = decode_tag_map(p.raw)
        hit = [e for e in entries if e["tag"] == tag]
        if not hit:
            raise KeyError("tag %r is not in TaggedWorldProgressValues" % tag)
        new = struct.pack("<f", float(value)) if as_float else struct.pack("<i", int(value))
        for e in hit:
            e["value"] = new
        return self.set_raw_property(pm, p.path, encode_tag_map(prefix, entries))

    # ---- other read-only views ------------------------------------------------
    def cached_characters(self):
        """Other characters cached in this world: [{guid, name, state (dict|None), json}]."""
        out = []
        for o in self.find_objects(CACHED_CHARACTERS_CLASS):
            if o.class_name != CACHED_CHARACTERS_CLASS:
                continue
            p = o.prop("CachedCharacterStates")
            if p is None or p.type != 64:
                continue
            raw = p.raw
            n = _u32(raw, 0)
            pos = 4
            for _ in range(n):
                props, pos = decode_tagged_props(raw, pos)
                plain = _tags_to_plain(props)
                cg = plain.get("CharacterGuid")
                guid = cg.get("InnerGuid") if isinstance(cg, dict) else cg
                text = plain.get("State")
                state = None
                if isinstance(text, str):
                    try:
                        state = json.loads(text)
                    except ValueError:
                        state = None
                name = None
                if isinstance(state, dict):
                    name = (state.get("meta_data") or {}).get("char_name")
                out.append({"guid": guid, "name": name, "state": state, "json": text})
            if pos != len(raw):
                raise FormatError("CachedCharacterStates has %d trailing bytes" % (len(raw) - pos))
        return out

    def custom_info(self):
        """Decode the INFO/CINF key/value table: {key: raw bytes}."""
        info = self.root.child(b"INFO")
        cinf = info.child(b"CINF") if info is not None else None
        if cinf is None:
            return {}
        d = cinf.data
        n = _u32(d, 0)
        p = 4
        keys = []
        for _ in range(n):
            k, p = read_fstring(d, p)
            keys.append(k)
        m = _u32(d, p)
        offs = list(struct.unpack_from("<%dI" % m, d, p + 4))
        p += 4 + 4 * m
        dl = _u32(d, p)
        data = d[p + 4:p + 4 + dl]
        ends = offs[1:] + [dl]
        return {k: data[o:e] for k, o, e in zip(keys, offs, ends)}

    def world_name(self):
        """Display name: WorldSaveSettings/WorldName of the global object, else INFO/CINF WorldName."""
        for lv in self.levels:
            if lv.is_global:
                for o in lv.objects:
                    p = o.prop("WorldSaveSettings/WorldName")
                    if p is not None and isinstance(p.value, str):
                        return p.value
        raw = self.custom_info().get("WorldName")
        if raw:
            try:
                return read_fstring(raw, 0)[0]
            except FormatError:
                pass
        return None

    # ---- saving ----------------------------------------------------------------
    def make_backup(self):
        """Copy the file on disk to <file>.<stamp>.pyedit.bak (never overwrites)."""
        if not self.path or not os.path.exists(self.path):
            raise FileNotFoundError("nothing on disk to back up")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = "%s.%s.pyedit.bak" % (self.path, stamp)
        n = 2
        while os.path.exists(dest):
            dest = "%s.%s-%d.pyedit.bak" % (self.path, stamp, n)
            n += 1
        shutil.copy2(self.path, dest)
        with open(self.path, "rb") as a, open(dest, "rb") as b:
            if a.read() != b.read():
                raise OSError("backup copy %s does not match the original" % dest)
        return dest

    def save(self, force=False, dry_run=False, snapshot=True):
        """Write pending edits back to self.path.

        Refuses while the game runs (unless force) or if the file changed on disk since it
        was opened (unless force). Verifies the output by a full re-parse: same object
        count, nothing but the edited property values changed, and every edit's final
        value present. Then snapshots all saves (snapshot=True), writes <file>.<stamp>.pyedit.bak,
        writes a temp file, re-reads and re-checks it, and os.replace()s it into place.
        Returns a dict describing what was done.
        """
        if not self.path:
            raise ValueError("this WorldFile has no path")
        result = {"path": self.path, "written": False, "dry_run": dry_run, "backup": None,
                  "snapshot": None, "edits": len(self._expect)}
        if not self.dirty:
            return result
        if not force and _game_is_running():
            raise RuntimeError("Dragonwilds is running; close the game before saving a world.")
        if not force and self._disk_sha is not None:
            with open(self.path, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != self._disk_sha:
                    raise RuntimeError("the world file changed on disk since it was opened; reopen it.")
        new = self.to_bytes()
        self._verify_new(self.validate_bytes(new))
        result["size"] = len(new)
        if dry_run:
            return result
        if snapshot:
            result["snapshot"] = _snapshot_saves("pre-world-edit")
        result["backup"] = self.make_backup()
        tmp = self.path + ".pyedit.tmp"
        with open(tmp, "wb") as f:
            f.write(new)
            f.flush()
            os.fsync(f.fileno())
        try:
            with open(tmp, "rb") as f:
                back = f.read()
            if back != new:
                raise OSError("temp file read-back mismatch")
            self._verify_new(self.validate_bytes(back))
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        self._load(new)
        self._disk_sha = hashlib.sha256(new).hexdigest()
        result["written"] = True
        return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _cmd_info(w, a):
    print("World name : %s" % w.world_name())
    print("Levels     : %d (incl. global)" % len(w.levels))
    print("Objects    : %d" % w.object_count())
    print("Destroyed  : %d" % sum(len(lv.destroyed) for lv in w.levels))
    try:
        print("Bosses     : %s" % (", ".join(w.defeated_bosses()) or "-"))
        print("Tags       : %d   Hooks: %d" % (len(w.tagged_values()), len(w.world_hooks())))
    except LookupError as e:
        print("Progress   : %s" % e)
    for c in w.cached_characters():
        print("Cached char: %s (%s)" % (c["name"], c["guid"]))


def _cmd_bosses(w, a):
    for n in w.defeated_bosses():
        print(n)


def _cmd_tags(w, a):
    for e in w.tagged_values():
        print("%-50s int=%d float=%g raw=%s" % (e["tag"], e["int"], e["float"], e["value"].hex()))
    for h in w.world_hooks():
        print("hook: %s" % h)


def _cmd_objects(w, a):
    for o in w.find_objects(a.substr or ""):
        print("%s  %s" % (o.key, o.class_name))
        if a.props:
            for p in o.properties():
                d = p.as_dict(32)
                print("    %-50s %-12s %s" % (p.path, p.type_name, d.get("value") if d.get("value") is not None else d.get("raw")))


def selftest(path):
    """Parse, check byte-exact output (fast and full rebuild), decode the progress
    records, and run an in-memory size-changing edit + re-parse. Never writes."""
    with open(path, "rb") as f:
        data = f.read()
    w = WorldFile.from_bytes(data)
    assert w.to_bytes() == data, "fast round trip differs"
    assert w.to_bytes(rebuild=True) == data, "full rebuild round trip differs"
    n = w.object_count()
    nprops = sum(len(o.properties()) for o in w.all_objects())
    undecoded = sum(1 for o in w.all_objects() for p in o.properties()
                    if p.type not in (40, 64, 29) and not decode_value(p.type, p.raw)[1])
    print("parsed %d objects, %d properties (%d undecoded non-record values); round trip OK"
          % (n, nprops, undecoded))
    if w.progress_manager() is not None:
        hooks = w.world_hooks()
        pm = w.progress_manager()
        p = pm.prop("WorldHooksTriggered")
        prefix, names = decode_string_set(p.raw)
        assert encode_string_set(prefix, names) == p.raw
        tp = pm.prop("TaggedWorldProgressValues")
        tprefix, ents = decode_tag_map(tp.raw)
        assert encode_tag_map(tprefix, [(e["tag"], e["value"]) for e in ents]) == tp.raw
        w.set_raw_property(pm, "WorldHooksTriggered", encode_string_set(prefix, names + ["/Game/SelfTest.SelfTest"]))
        out = w.to_bytes()
        w2 = WorldFile.validate_bytes(out)
        w._verify_new(w2)
        assert w2.world_hooks() == hooks + ["/Game/SelfTest.SelfTest"]
        assert len(out) == len(data) + len(encode_fstring("/Game/SelfTest.SelfTest"))
        print("in-memory size-changing edit re-parsed OK (%d -> %d bytes); nothing written"
              % (len(data), len(out)))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dragonwilds world save (SPUD) reader")
    ap.add_argument("file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    sub.add_parser("bosses")
    sub.add_parser("tags")
    po = sub.add_parser("objects")
    po.add_argument("substr", nargs="?", default="")
    po.add_argument("--props", action="store_true", help="also list properties")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "selftest":
            selftest(a.file)
            return 0
        w = WorldFile(a.file)
        {"info": _cmd_info, "bosses": _cmd_bosses, "tags": _cmd_tags, "objects": _cmd_objects}[a.cmd](w, a)
    except (FormatError, LookupError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
