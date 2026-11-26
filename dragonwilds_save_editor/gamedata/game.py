"""Package access over an installed game's IoStore containers (read-only).

    with GameData(paks_dir) as gd:
        pkg = gd.package("/Game/Gameplay/Items/ST_ItemNames")

``paks_dir`` is the game's ``RSDragonwilds/Content/Paks`` folder (install.find_paks_dir()
accepts the install root and returns it). Nothing is written, renamed or locked there.
"""

import os
import re

from . import zen
from .iostore import FormatError, IoStore, PakFile

CONTAINER = "RSDragonwilds-Windows.utoc"
GLOBAL_CONTAINER = "global.utoc"
PAK = "RSDragonwilds-Windows.pak"
GAME_INI = "RSDragonwilds/Config/DefaultGame.ini"
CHUNK_SCRIPT_OBJECTS = 5

_ASSET_RE = re.compile(
    r"RSDragonwilds/(?:Plugins/(?:GameFeatures/)?(?:[^/]+/)*?([^/]+)/)?Content/(.+)\.u(?:asset|map)$")


def asset_to_package(path):
    """Container path -> package name: 'RSDragonwilds/Content/X/Y.uasset' -> '/Game/X/Y';
    'RSDragonwilds/Plugins/GameFeatures/P/Content/X.uasset' -> '/P/X'. None for other files."""
    m = _ASSET_RE.match(path)
    if not m:
        return None
    return "/%s/%s" % (m.group(1) or "Game", m.group(2))


def read_game_version(paks_dir):
    """ProjectVersion from the pak's Config/DefaultGame.ini (e.g. '1.0.2.2'), or None."""
    try:
        pak = PakFile(os.path.join(paks_dir, PAK))
        ini = pak.read(GAME_INI).decode("utf-8", "replace")
    except (OSError, KeyError, ValueError):
        return None
    m = re.search(r"^\s*ProjectVersion\s*=\s*(\S+)", ini, re.M)
    return m.group(1) if m else None


class GameData:
    """The game's main container plus the global script-object table."""

    def __init__(self, paks_dir):
        self.paks_dir = paks_dir
        self.store = IoStore(os.path.join(paks_dir, CONTAINER))
        self.global_store = IoStore(os.path.join(paks_dir, GLOBAL_CONTAINER))
        try:
            idx = next((i for i, cid in enumerate(self.global_store.chunk_ids)
                        if cid[11] == CHUNK_SCRIPT_OBJECTS), 0)
            self.script_objects = zen.load_script_objects(self.global_store.read_entry(idx))
        finally:
            self.global_store.close()
        # package name (lower case) -> container path, for .uasset/.umap files
        self.files = {p: i for p, i in self.store.files.items() if p.endswith((".uasset", ".umap"))}
        self.by_package = {}
        for p in self.files:
            pk = asset_to_package(p)
            if pk:
                self.by_package[pk.lower()] = p
        self._cache = {}
        self.bytes_read = 0

    def close(self):
        self.store.close()
        self.global_store.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def package(self, path):
        """ZenPackage for a container path ('RSDragonwilds/...uasset') or a package name
        ('/Game/...'); None if there is no such package."""
        if path.startswith("/"):
            path = self.by_package.get(path.lower())
            if not path:
                return None
        pk = self._cache.get(path)
        if pk is None:
            if path not in self.files:
                return None
            data = self.store.read_entry(self.files[path])
            self.bytes_read += len(data)
            pk = zen.ZenPackage(data, path)
            self._cache[path] = pk
        return pk

    def resolve_object(self, pkg, idx):
        """Full object name for an FPackageObjectIndex: '/Script/Mod.Class' or '/Game/Pkg.Export'."""
        kind, v = pkg.resolve(idx, self.script_objects)
        if kind == zen.SCRIPT_IMPORT:
            return v
        if kind == zen.EXPORT:
            return "%s.%s" % (pkg.name, v)
        if kind == zen.PACKAGE_IMPORT:
            pname, h = v
            if not pname:
                return None
            other = self.package(pname)
            if other is None:
                return pname + ".?"
            for e in other.exports:
                if e.public_hash == h:
                    return "%s.%s" % (pname, e.name)
            return pname + ".?"
        return None

    def class_chain(self, pkg, export):
        """[class, parent, ...] up to the first native class, e.g.
        ['BP_Consumables_Food_C', 'BP_Consumables_Base_C', 'ConsumableData']. Native parents are
        not in the paks, so the chain stops at the first /Script/ class."""
        chain = []
        full = self.resolve_object(pkg, export.klass)
        while full and len(chain) < 12:
            chain.append(full.rsplit(".", 1)[-1])
            if full.startswith("/Script/"):
                break
            pname, ename = full.rsplit(".", 1)
            other = self.package(pname)
            if other is None:
                break
            ex = next((e for e in other.exports if e.name == ename), None)
            if ex is None or ex.super == zen.NULL_INDEX:
                break
            full = self.resolve_object(other, ex.super)
        return chain

    @staticmethod
    def main_export(pkg, base):
        """The asset's own export (named like the file, or its class default object)."""
        for e in pkg.exports:
            if e.name in (base, "Default__%s_C" % base):
                return e
        return pkg.exports[0] if len(pkg.exports) == 1 else None


__all__ = ["GameData", "FormatError", "asset_to_package", "read_game_version"]
