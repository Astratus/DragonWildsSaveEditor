"""UStringTable exports (the game's display-name tables, e.g. ST_ItemNames).

Layout: an empty unversioned property header, int32 bHasGuid (0), then FStringTable: FString
namespace, int32 count, count x (FString key, FString text); per-key metadata follows and is
ignored.
"""

from . import uprops
from .iostore import FormatError, Reader


def decode(pkg, export):
    """(namespace, {key: text}) of a string-table export."""
    b = pkg.export_data(export)
    present, p = uprops.read_header(b, 0)
    if present:
        raise FormatError("string table with properties: %s" % pkg.path)
    r = Reader(b, p)
    if r.i32() != 0:
        raise FormatError("unexpected GUID flag in string table %s" % pkg.path)
    namespace = r.fstring()
    n = r.i32()
    if not 0 <= n <= 200000:
        raise FormatError("bad entry count %d in string table %s" % (n, pkg.path))
    out = {}
    for _ in range(n):
        k = r.fstring()
        out[k] = r.fstring()
    return namespace, out
