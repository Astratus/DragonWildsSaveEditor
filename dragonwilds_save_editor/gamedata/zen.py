"""Cooked zen package headers (UE 5.3+ layout as shipped with UE 5.6): summary, name map,
imported public export hashes, import map, export map and imported package names.

Only unversioned packages are supported (the game cooks every package that way).
"""

import struct

from .iostore import FormatError, Reader

PKG_UNVERSIONED_PROPERTIES = 0x2000

# FPackageObjectIndex kinds (top 2 bits)
EXPORT, SCRIPT_IMPORT, PACKAGE_IMPORT, NULL = 0, 1, 2, 3
NULL_INDEX = 0xFFFFFFFFFFFFFFFF
SUMMARY_SIZE = 52
EXPORT_ENTRY_SIZE = 72


def load_name_batch(r):
    """FNameBatch: int32 count, uint32 string bytes, uint64 hash version, count uint64 hashes,
    count big-endian uint16 headers (bit 15 = UTF-16, low 15 bits = length), then the strings."""
    n = r.i32()
    if n <= 0:
        return []
    r.u32()
    r.u64()
    r.p += 8 * n
    hdrs = r.raw(2 * n)
    out = []
    for i in range(n):
        h = (hdrs[2 * i] << 8) | hdrs[2 * i + 1]
        ln = h & 0x7FFF
        out.append(r.raw(ln * 2).decode("utf-16-le") if h & 0x8000 else r.raw(ln).decode("latin-1"))
    return out


def _name(names, idx, num=0):
    s = names[idx & 0x3FFFFFFF]
    return s if not num else "%s_%d" % (s, num - 1)


class ExportEntry:
    """One export map entry. ``klass``/``super``/``outer``/``template`` are FPackageObjectIndex."""

    __slots__ = ("serial_offset", "serial_size", "name", "outer", "klass", "super", "template",
                 "public_hash", "flags", "filter_flags", "index")


class ZenPackage:
    """A cooked package's header plus its export bytes (``export_data``)."""

    def __init__(self, data, path=None):
        self.data, self.path = data, path
        (has_versioning, self.header_size, name_idx, _name_num, self.pkg_flags,
         self.cooked_header_size, hashes_off, imports_off, exports_off,
         bundle_off, _dep_hdr_off, _dep_entries_off,
         imported_names_off) = struct.unpack_from("<IIIIIIiiiiiii", data, 0)
        if has_versioning:
            raise FormatError("versioned zen packages are not supported")
        r = Reader(data, SUMMARY_SIZE)
        # UE 5.6 (Verse cells): cell import/export map offsets come before the name map
        self.cell_import_off, self.cell_export_off = r.i32(), r.i32()
        self.names = load_name_batch(r)
        self.name = self.names[name_idx & 0x3FFFFFFF]
        n_hash = (imports_off - hashes_off) // 8
        self.imported_hashes = struct.unpack_from("<%dQ" % n_hash, data, hashes_off)
        n_imp = (exports_off - imports_off) // 8
        self.imports = struct.unpack_from("<%dQ" % n_imp, data, imports_off)
        self.exports = []
        for i in range((bundle_off - exports_off) // EXPORT_ENTRY_SIZE):
            e = ExportEntry()
            (e.serial_offset, e.serial_size, ni, nn, e.outer, e.klass, e.super, e.template,
             e.public_hash, e.flags, e.filter_flags) = struct.unpack_from(
                 "<QQIIQQQQQIB", data, exports_off + i * EXPORT_ENTRY_SIZE)
            e.name = _name(self.names, ni, nn)
            e.index = i
            self.exports.append(e)
        # imported package names: a name batch, then one int32 name number per name
        self.imported_package_names = []
        if 0 < imported_names_off < self.header_size:
            try:
                rr = Reader(data, imported_names_off)
                batch = load_name_batch(rr)
                nums = [rr.i32() for _ in batch]
                self.imported_package_names = [n if not k else "%s_%d" % (n, k - 1)
                                               for n, k in zip(batch, nums)]
            except (EOFError, struct.error, UnicodeDecodeError):
                self.imported_package_names = []

    @property
    def unversioned(self):
        return bool(self.pkg_flags & PKG_UNVERSIONED_PROPERTIES)

    def export_data(self, e):
        """The serialized bytes of export `e` (properties first)."""
        start = self.header_size + e.serial_offset
        return self.data[start:start + e.serial_size]

    def resolve(self, idx, script_objects=None):
        """(kind, value) for an FPackageObjectIndex: (EXPORT, export name), (SCRIPT_IMPORT,
        '/Script/Module.Object' or None), (PACKAGE_IMPORT, (package name, public export hash))
        or (NULL, None)."""
        if idx == NULL_INDEX:
            return NULL, None
        k, v = idx >> 62, idx & ((1 << 62) - 1)
        if k == EXPORT:
            return EXPORT, self.exports[v].name if v < len(self.exports) else None
        if k == SCRIPT_IMPORT:
            return SCRIPT_IMPORT, (script_objects or {}).get(idx)
        if k == PACKAGE_IMPORT:
            pkg_i, hash_i = v >> 32, v & 0xFFFFFFFF
            pkg = self.imported_package_names[pkg_i] if pkg_i < len(self.imported_package_names) else None
            h = self.imported_hashes[hash_i] if hash_i < len(self.imported_hashes) else None
            return PACKAGE_IMPORT, (pkg, h)
        return NULL, None


def load_script_objects(data):
    """{global object index: '/Script/Module.Object'} from global.utoc's script-objects chunk
    (a name batch, int32 count, then count x (FMinimalName, global index, outer index, CDO class
    index))."""
    r = Reader(data)
    names = load_name_batch(r)
    n = r.i32()
    by = {}
    for _ in range(n):
        ni, nn, gidx, outer, _cdo = struct.unpack_from("<IIQQQ", data, r.p)
        r.p += 32
        by[gidx] = (_name(names, ni, nn), outer)
    out = {}
    for g, (nm, outer) in by.items():
        parts = [nm]
        o, depth = outer, 0
        while o != NULL_INDEX and o in by and depth < 10:
            parts.append(by[o][0])
            o = by[o][1]
            depth += 1
        parts.reverse()
        out[g] = parts[0] + ("." + ".".join(parts[1:]) if len(parts) > 1 else "")
    return out
