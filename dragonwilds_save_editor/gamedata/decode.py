"""Decode an export's unversioned properties with a byte-level schema (see schemas.py).

A schema maps keys to types. A key is a tuple: the path of property indices, with 'e' for an
array element and 'k'/'v' for a map key/value. Types:

  ('fix', n)   n raw bytes        -> int (n=1), V4 (n=4), V8 (n=8), else bytes
  ('str',)     FString            -> str
  ('text',)    FText              -> dict (see uprops.read_text)
  ('soft',)    FSoftObjectPath    -> (package, asset, sub path)
  ('arr',)     TArray             -> list (element type at key + ('e',))
  ('struct',)  nested struct with its own unversioned header -> {index: value}
  ('map',)     TMap               -> [(key, value)]

A 4-byte value is ambiguous (int32, float, object reference): V4 keeps all readings. An 8-byte
value is usually an FName: V8 keeps the name (if valid) and the raw int64.
"""

import struct

from . import uprops


class V4:
    """A 4-byte value: ``i`` int32, ``f`` float32, ``obj`` the object it names if it is a valid
    package index ('/Game/Pkg.Export' or '/Script/Module.Class'), else None."""

    __slots__ = ("i", "f", "obj")

    def __init__(self, i, f, obj):
        self.i, self.f, self.obj = i, f, obj

    def __repr__(self):
        return "V4(%d|%g|%s)" % (self.i, self.f, self.obj)


class V8:
    """An 8-byte value: ``name`` the FName it reads as (or None), ``q`` the raw int64."""

    __slots__ = ("name", "q")

    def __init__(self, name, q):
        self.name, self.q = name, q

    def __repr__(self):
        return "V8(%s|%d)" % (self.name, self.q)


class SchemaMismatch(ValueError):
    """The schema does not describe the export's bytes exactly."""


class Decoder:
    """Decodes instances of one class. ``game`` (a game.GameData) resolves imported objects."""

    def __init__(self, schema, pkg, game=None):
        self.schema = schema
        self.pkg = pkg
        self.game = game
        self.inst = None

    def obj_name(self, i):
        """FPackageIndex -> full object name, or None."""
        pkg = self.pkg
        if i == 0:
            return None
        if i < 0:
            k = -i - 1
            if k >= len(pkg.imports):
                return None
            return self.game.resolve_object(pkg, pkg.imports[k]) if self.game else "import:%d" % k
        k = i - 1
        if k >= len(pkg.exports):
            return None
        return "%s.%s" % (pkg.name, pkg.exports[k].name)

    def value(self, key, p):
        """(value, next offset) for the type the schema gives `key`; KeyError if it has none."""
        t = self.schema[key]
        kind, b, inst = t[0], self.inst.b, self.inst
        if kind == "fix":
            n = t[1]
            if p + n > inst.end:
                raise uprops.Fail("eof")
            raw = b[p:p + n]
            if n == 1:
                return raw[0], p + 1
            if n == 4:
                i = struct.unpack_from("<i", raw)[0]
                f = struct.unpack_from("<f", raw)[0]
                ok = -len(self.pkg.imports) <= i <= len(self.pkg.exports)
                return V4(i, f, self.obj_name(i) if ok else None), p + 4
            if n == 8:
                q = struct.unpack_from("<q", raw)[0]
                try:
                    nm = uprops.read_name(inst, p)[0]
                except uprops.Fail:
                    nm = None
                return V8(nm, q), p + 8
            return raw, p + n
        if kind == "str":
            return uprops.read_str(inst, p)
        if kind == "text":
            return uprops.read_text(inst, p)
        if kind == "soft":
            return uprops.read_soft(inst, p)
        if kind == "struct":
            return self.struct(key, p)
        if kind == "arr":
            n = uprops.i32_at(b, p, inst.end)
            if n < 0 or n > 100000:
                raise uprops.Fail("array count")
            p += 4
            out = []
            for _ in range(n):
                v, p = self.value(key + ("e",), p)
                out.append(v)
            return out, p
        if kind == "map":
            n = uprops.i32_at(b, p + 4, inst.end)
            if n < 0 or n > 100000:
                raise uprops.Fail("map count")
            p += 8
            out = []
            for _ in range(n):
                k, p = self.value(key + ("k",), p)
                v, p = self.value(key + ("v",), p)
                out.append((k, v))
            return out, p
        raise ValueError("unknown schema type %r" % (t,))

    def struct(self, key, p):
        present, p = uprops.read_header(self.inst.b, p)
        out = {}
        for idx, zero in present:
            if zero:
                out[idx] = None  # all-zero value, not written
                continue
            out[idx], p = self.value(key + (idx,), p)
        return out, p

    def decode(self, inst):
        """{index: value} for the whole export; raises SchemaMismatch unless the bytes end
        exactly where the schema says."""
        self.inst = inst
        try:
            out, p = self.struct((), 0)
        except (KeyError, IndexError, struct.error, uprops.Fail) as e:
            raise SchemaMismatch("schema does not fit %s: %s" % (inst.label, e))
        if p != inst.end:
            raise SchemaMismatch("schema mismatch in %s (%d bytes left)" % (inst.label, inst.end - p))
        return out
