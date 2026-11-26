"""Unversioned property headers (FUnversionedHeader) and the primitive value readers.

A cooked, unversioned export or struct starts with a header that says WHICH property indices
are present (and which of them are all-zero and therefore not written), but not their names or
types: those live in the native classes inside the game executable, which is never read. The
types come from schemas.json instead (see schemas.py).
"""

import struct


class Fail(ValueError):
    """The bytes do not fit the expected type at this position."""


def read_header(b, p=0):
    """Parse a header at `p`. Returns (present, end): present = [(property index, is_zero)] in
    serialization order, end = offset of the first value byte.

    Fragments are uint16: skip count (7 bits), has-zeroes (bit 7), is-last (bit 8), value count
    (bits 9-15). The zero mask follows: 1 byte for <= 8 flagged values, 2 bytes for <= 16, else
    uint32 words."""
    frags, zero_num = [], 0
    while True:
        if p + 2 > len(b):
            raise Fail("eof in property header")
        (v,) = struct.unpack_from("<H", b, p)
        p += 2
        skip, has_zero, last, num = v & 0x7F, bool(v & 0x80), bool(v & 0x100), v >> 9
        frags.append((skip, has_zero, num))
        if has_zero:
            zero_num += num
        if last:
            break
    bits = []
    if zero_num:
        nbytes = 1 if zero_num <= 8 else 2 if zero_num <= 16 else ((zero_num + 31) // 32) * 4
        m = int.from_bytes(b[p:p + nbytes], "little")
        p += nbytes
        bits = [(m >> i) & 1 for i in range(zero_num)]
    present, idx, zi = [], 0, 0
    for skip, has_zero, num in frags:
        idx += skip
        for _ in range(num):
            z = False
            if has_zero:
                z = bool(bits[zi])
                zi += 1
            present.append((idx, z))
            idx += 1
    return present, p


def read_header_strict(b, p=0):
    """read_header plus the invariants Unreal's header writer keeps (no empty fragments, merged
    fragments, a has-zeroes fragment holds a zero). Raises Fail on bytes that cannot be a header;
    used as a plausibility filter by schema inference."""
    start, frags = p, []
    while True:
        if p + 2 > len(b):
            raise Fail("eof")
        (v,) = struct.unpack_from("<H", b, p)
        p += 2
        frags.append((v & 0x7F, bool(v & 0x80), bool(v & 0x100), v >> 9))
        if v & 0x100:
            break
        if len(frags) > 64:
            raise Fail("too many fragments")
    for i, (skip, _hz, last, num) in enumerate(frags):
        if num == 0 and not (last and len(frags) == 1):
            raise Fail("empty fragment")
        if i > 0 and skip == 0 and frags[i - 1][3] != 127:
            raise Fail("unmerged fragments")
    present, q = read_header(b, start)
    if q > len(b):
        raise Fail("eof")
    k = 0
    for _skip, hz, _last, num in frags:
        seg = present[k:k + num]
        k += num
        if hz and not any(z for _, z in seg):
            raise Fail("zero flag without zeroes")
    return present, q


class Inst:
    """One export's property bytes plus the package tables needed to validate values."""

    __slots__ = ("b", "names", "n_imports", "n_exports", "end", "label")

    def __init__(self, b, pkg, label=""):
        self.b = b
        self.names = pkg.names
        self.n_imports = len(pkg.imports)
        self.n_exports = len(pkg.exports)
        self.label = label
        self.end = len(b)


def i32_at(b, p, end):
    if p + 4 > end:
        raise Fail("eof")
    return struct.unpack_from("<i", b, p)[0]


def read_str(inst, p):
    """FString -> (str, next offset). Rejects implausible lengths and control characters."""
    b, end = inst.b, inst.end
    n = i32_at(b, p, end)
    p += 4
    if n == 0:
        return "", p
    if n > 0:
        if n > 8192 or p + n > end or b[p + n - 1] != 0:
            raise Fail("str")
        s = b[p:p + n - 1]
        if any(c < 9 for c in s):
            raise Fail("str ctl")
        return s.decode("utf-8", "replace"), p + n
    n = -n
    if n > 8192 or p + 2 * n > end or b[p + 2 * n - 2:p + 2 * n] != b"\0\0":
        raise Fail("wstr")
    return b[p:p + 2 * n - 2].decode("utf-16-le", "replace"), p + 2 * n


def read_name(inst, p):
    """FName (name-map index, number) -> (str, next offset)."""
    if p + 8 > inst.end:
        raise Fail("eof")
    i, n = struct.unpack_from("<II", inst.b, p)
    if i >= len(inst.names) or n > 100000:
        raise Fail("name")
    s = inst.names[i]
    return (s if not n else "%s_%d" % (s, n - 1)), p + 8


def read_text(inst, p):
    """FText -> (dict, next offset). Supported histories: -1 None (optional culture-invariant
    string), 0 Base (namespace, key, source string), 11 StringTableEntry (table, key)."""
    b, end = inst.b, inst.end
    if p + 5 > end:
        raise Fail("eof")
    flags = struct.unpack_from("<I", b, p)[0]
    if flags > 0x1F:
        raise Fail("text flags")
    h = struct.unpack_from("<b", b, p + 4)[0]
    p += 5
    if h == -1:
        has = i32_at(b, p, end)
        p += 4
        if has == 0:
            return {"type": "none"}, p
        if has != 1:
            raise Fail("text none")
        s, p = read_str(inst, p)
        return {"type": "none", "invariant": s}, p
    if h == 0:
        ns, p = read_str(inst, p)
        key, p = read_str(inst, p)
        src, p = read_str(inst, p)
        return {"type": "base", "ns": ns, "key": key, "source": src}, p
    if h == 11:
        tid, p = read_name(inst, p)
        key, p = read_str(inst, p)
        return {"type": "st", "table": tid, "key": key}, p
    raise Fail("text history %d" % h)


def read_soft(inst, p):
    """FSoftObjectPath as cooked here: FName package, FName asset, FString sub-path."""
    a, p = read_name(inst, p)
    c, p = read_name(inst, p)
    sub, p = read_str(inst, p)
    if a != "None" and not a.startswith("/"):
        raise Fail("soft")
    return (a, c, sub), p
