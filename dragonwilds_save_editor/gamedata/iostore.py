"""Read-only readers for Unreal Engine 5 IoStore containers (.utoc/.ucas) and pak files (.pak).

Only what RuneScape: Dragonwilds ships is supported: unencrypted containers whose blocks are
stored uncompressed, and pak v8+ files with a full directory index and uncompressed entries.
Files are opened read-only (shared, never locked) and read with seeks; nothing is ever written.
Format notes and sources: docs/research/gamedata_provenance.md.
"""

import struct

TOC_MAGIC = b"-==--==--==--==-"
FLAG_COMPRESSED, FLAG_ENCRYPTED, FLAG_SIGNED, FLAG_INDEXED = 1, 2, 4, 8
NONE_INDEX = 0xFFFFFFFF
PAK_MAGIC = 0x5A6F12E1
PAK_FOOTER_SIZE = 221          # v11 footer incl. 5 x 32-byte compression method names
PAK_ENTRY_HEADER_SIZE = 53     # FPakEntry copy in front of an uncompressed v11 entry


class FormatError(ValueError):
    """The file is not in a format (or variant) this reader supports."""


class Reader:
    """Little-endian cursor over a bytes object."""

    __slots__ = ("b", "p")

    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def _unpack(self, fmt, n):
        v = struct.unpack_from(fmt, self.b, self.p)[0]
        self.p += n
        return v

    def u8(self):
        v = self.b[self.p]
        self.p += 1
        return v

    def u16(self):
        return self._unpack("<H", 2)

    def i32(self):
        return self._unpack("<i", 4)

    def u32(self):
        return self._unpack("<I", 4)

    def i64(self):
        return self._unpack("<q", 8)

    def u64(self):
        return self._unpack("<Q", 8)

    def raw(self, n):
        v = self.b[self.p:self.p + n]
        if len(v) != n:
            raise EOFError("read past end")
        self.p += n
        return v

    def fstring(self):
        """FString: int32 length (negative = UTF-16 code units), NUL-terminated."""
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            if n < -65536:
                raise FormatError("bad FString length %d" % n)
            s = self.raw(-n * 2).decode("utf-16-le")
        else:
            if n > 65536:
                raise FormatError("bad FString length %d" % n)
            s = self.raw(n).decode("utf-8", "replace")
        return s.rstrip("\0")


def _u40be(b, o):
    return int.from_bytes(b[o:o + 5], "big")


class IoStore:
    """One .utoc/.ucas container pair (TOC version 8 layout)."""

    def __init__(self, utoc_path):
        self.utoc_path = utoc_path
        self.ucas_path = utoc_path[:-5] + ".ucas"
        with open(utoc_path, "rb") as f:
            data = f.read()
        if data[:16] != TOC_MAGIC:
            raise FormatError("not an IoStore TOC: %s" % utoc_path)
        self.version = data[16]
        (hdr_size, n_entries, n_blocks, self.block_entry_size, n_methods, method_len,
         self.block_size, dir_index_size, self.partition_count) = struct.unpack_from("<9I", data, 20)
        self.container_id = struct.unpack_from("<Q", data, 56)[0]
        self.flags = data[80]
        seeds_count = struct.unpack_from("<I", data, 84)[0]
        self.partition_size = struct.unpack_from("<Q", data, 88)[0]
        no_hash_count = struct.unpack_from("<I", data, 96)[0]
        if self.flags & FLAG_ENCRYPTED:
            raise FormatError("encrypted IoStore containers are not supported")
        p = hdr_size
        self.chunk_ids = [data[p + i * 12:p + i * 12 + 12] for i in range(n_entries)]
        p += n_entries * 12
        ol = data[p:p + n_entries * 10]
        self.offlen = [(_u40be(ol, i * 10), _u40be(ol, i * 10 + 5)) for i in range(n_entries)]
        p += n_entries * 10
        p += seeds_count * 4 + no_hash_count * 4          # perfect-hash seeds (unused here)
        self._blocks = data[p:p + n_blocks * self.block_entry_size]
        p += n_blocks * self.block_entry_size
        self.methods = [data[p + i * method_len:p + (i + 1) * method_len].rstrip(b"\0").decode()
                        for i in range(n_methods)]
        p += n_methods * method_len
        if self.flags & FLAG_SIGNED:
            hash_size = struct.unpack_from("<i", data, p)[0]
            p += 4 + hash_size * 2 + 20 * n_blocks
        self.mount_point = ""
        self.files = {}  # container path ('RSDragonwilds/Content/X.uasset') -> TOC entry index
        if self.flags & FLAG_INDEXED and dir_index_size:
            self._parse_dir_index(data[p:p + dir_index_size])
        self.index_by_chunk = {cid: i for i, cid in enumerate(self.chunk_ids)}
        self._fh = None

    def _parse_dir_index(self, b):
        r = Reader(b)
        self.mount_point = r.fstring()
        dirs = [(r.u32(), r.u32(), r.u32(), r.u32()) for _ in range(r.u32())]
        files = [(r.u32(), r.u32(), r.u32()) for _ in range(r.u32())]
        strings = [r.fstring() for _ in range(r.u32())]
        mount = self.mount_point.replace("../../../", "").strip("/")
        if not dirs:
            return
        stack = [(0, mount)]
        while stack:
            di, path = stack.pop()
            _name, child, _sibling, fi = dirs[di]
            while fi != NONE_INDEX:
                fname, nxt, entry = files[fi]
                self.files[(path + "/" if path else "") + strings[fname]] = entry
                fi = nxt
            c = child
            while c != NONE_INDEX:
                stack.append((c, (path + "/" if path else "") + strings[dirs[c][0]]))
                c = dirs[c][2]

    def _block(self, i):
        o = i * self.block_entry_size
        b = self._blocks
        return (int.from_bytes(b[o:o + 5], "little"), int.from_bytes(b[o + 5:o + 8], "little"),
                int.from_bytes(b[o + 8:o + 11], "little"), b[o + 11])

    def _open(self):
        if self._fh is None:
            self._fh = open(self.ucas_path, "rb")  # read-only, shared
        return self._fh

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read_entry(self, idx):
        """Bytes of TOC entry `idx`. Contiguous uncompressed blocks are read in one seek."""
        off, length = self.offlen[idx]
        if not length:
            return b""
        fh = self._open()
        bs = self.block_size
        first, last = off // bs, (off + length - 1) // bs
        out = bytearray()
        i = first
        while i <= last:
            boff, _csize, usize, method = self._block(i)
            if method != 0:
                raise FormatError("compressed IoStore block (method %d) is not supported" % method)
            start = off - i * bs if i == first else 0
            j, run_end = i, boff + usize
            while j + 1 <= last:
                nb = self._block(j + 1)
                if nb[3] != 0 or nb[0] != run_end:
                    break
                run_end = nb[0] + nb[2]
                j += 1
            fh.seek(boff + start)
            out += fh.read(run_end - boff - start)
            i = j + 1
        if len(out) < length:
            raise FormatError("IoStore entry %d is truncated" % idx)
        return bytes(out[:length])


class PakFile:
    """A pak file (v8+ index with a full directory index); unencrypted, uncompressed entries."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - PAK_FOOTER_SIZE))
            foot = f.read(PAK_FOOTER_SIZE)
            at = foot.find(struct.pack("<I", PAK_MAGIC))
            if at < 1:
                raise FormatError("pak footer not found in %s" % path)
            if foot[at - 1]:
                raise FormatError("encrypted pak index is not supported")
            self.version, idx_off, idx_size = struct.unpack_from("<iqq", foot, at + 4)
            f.seek(idx_off)
            r = Reader(f.read(idx_size))
            self.mount_point = r.fstring()
            r.i32()                          # entry count
            r.u64()                          # path hash seed
            if r.i32():                      # path hash index: offset, size, hash
                r.raw(8 + 8 + 20)
            if not r.i32():
                raise FormatError("pak has no full directory index")
            fdi_off, fdi_size = r.i64(), r.i64()
            r.raw(20)
            self._encoded = r.raw(r.i32())
            f.seek(fdi_off)
            fdi = Reader(f.read(fdi_size))
        self.files = {}  # 'RSDragonwilds/Config/DefaultGame.ini' -> encoded entry offset
        mount = self.mount_point.replace("../../../", "")
        for _ in range(fdi.i32()):
            d = fdi.fstring()
            for _ in range(fdi.i32()):
                name = fdi.fstring()
                self.files[(mount + d + name).lstrip("/")] = fdi.i32()

    def _entry(self, enc_off):
        b = self._encoded
        bits = struct.unpack_from("<I", b, enc_off)[0]
        p = enc_off + 4
        if (bits >> 23) & 0x3F or (bits >> 22) & 1:
            raise FormatError("compressed or encrypted pak entry is not supported")
        if bits & (1 << 31):
            off = struct.unpack_from("<I", b, p)[0]
            p += 4
        else:
            off = struct.unpack_from("<Q", b, p)[0]
            p += 8
        if bits & (1 << 30):
            usize = struct.unpack_from("<I", b, p)[0]
        else:
            usize = struct.unpack_from("<Q", b, p)[0]
        return off, usize

    def read(self, name):
        """Bytes of the file `name` (KeyError if absent)."""
        off, usize = self._entry(self.files[name])
        with open(self.path, "rb") as f:
            f.seek(off + PAK_ENTRY_HEADER_SIZE)
            data = f.read(usize)
        if len(data) != usize:
            raise FormatError("pak entry %s is truncated" % name)
        return data
