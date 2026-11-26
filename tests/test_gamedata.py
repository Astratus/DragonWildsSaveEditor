"""Tests for dragonwilds_save_editor.gamedata (the read-only installed-game reader).

The synthetic tests always run: tests/gamedata_fixture.py writes tiny IoStore/zen/pak files to a
temp folder. The real-install tests run only with DW_TEST_GAME_DIR set to a game installation
folder (they only read it). Nothing here touches %LOCALAPPDATA%.
"""

import ast
import json
import os
import sys
import shutil
import struct
import tempfile
import unittest

try:
    from . import _helpers as H  # noqa: F401  (puts the project root on sys.path)
    from . import gamedata_fixture as F
except ImportError:
    import _helpers as H  # noqa: F401
    import gamedata_fixture as F

from dragonwilds_save_editor import catalog as C, paths  # noqa: E402
from dragonwilds_save_editor.gamedata import (decode, derive, game, install, iostore, schemas,  # noqa: E402
                                              stringtable, uprops, zen)

GAME_DIR = os.environ.get("DW_TEST_GAME_DIR")


class _TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dwgd_")
        self.addCleanup(shutil.rmtree, self.tmp, True)


class ContainerTests(_TmpCase):
    def test_iostore_directory_index_and_multi_block_entries(self):
        big = bytes(range(256)) * 10           # spans several 1 KiB blocks
        path = os.path.join(self.tmp, "c.utoc")
        F.write_iostore(path, [(F.chunk_id(1), b"first"), (F.chunk_id(2), big), (F.chunk_id(3), b"")],
                        {"RSDragonwilds/Content/A/x.uasset": 0, "RSDragonwilds/Content/B/y.uasset": 1,
                         "RSDragonwilds/Content/A/z.txt": 2})
        with iostore.IoStore(path) as st:
            self.assertEqual(st.files, {"RSDragonwilds/Content/A/x.uasset": 0,
                                        "RSDragonwilds/Content/B/y.uasset": 1, "RSDragonwilds/Content/A/z.txt": 2})
            self.assertEqual(st.read_entry(0), b"first")
            self.assertEqual(st.read_entry(1), big)
            self.assertEqual(st.read_entry(2), b"")
            self.assertEqual(st.index_by_chunk[F.chunk_id(2)], 1)

    def test_rejects_non_toc_and_encrypted(self):
        bad = os.path.join(self.tmp, "bad.utoc")
        with open(bad, "wb") as f:
            f.write(b"x" * 200)
        with self.assertRaises(iostore.FormatError):
            iostore.IoStore(bad)
        path = os.path.join(self.tmp, "enc.utoc")
        F.write_iostore(path, [(F.chunk_id(1), b"a")])
        with open(path, "r+b") as f:
            f.seek(80)
            f.write(bytes([iostore.FLAG_ENCRYPTED]))
        with self.assertRaises(iostore.FormatError):
            iostore.IoStore(path)

    def test_compressed_block_is_refused(self):
        path = os.path.join(self.tmp, "c.utoc")
        F.write_iostore(path, [(F.chunk_id(1), b"abc")])
        with open(path, "rb") as f:
            data = bytearray(f.read())
        data[144 + 12 + 10 + 11] = 1     # first block's compression method
        with open(path, "wb") as f:
            f.write(data)
        with iostore.IoStore(path) as st, self.assertRaises(iostore.FormatError):
            st.read_entry(0)

    def test_pak(self):
        path = os.path.join(self.tmp, "p.pak")
        F.write_pak(path, {"RSDragonwilds/Config/DefaultGame.ini": b"ProjectVersion=1.2.3.4\r\n",
                           "RSDragonwilds/Config/Other.ini": b"x"})
        pak = iostore.PakFile(path)
        self.assertEqual(pak.read("RSDragonwilds/Config/DefaultGame.ini"), b"ProjectVersion=1.2.3.4\r\n")
        self.assertEqual(pak.read("RSDragonwilds/Config/Other.ini"), b"x")
        with self.assertRaises(KeyError):
            pak.read("nope")

    def test_files_are_opened_read_only(self):
        root, _ = F.make_game(self.tmp)
        paks = install.find_paks_dir(root)
        before = {n: os.path.getmtime(os.path.join(paks, n)) for n in os.listdir(paks)}
        for n in os.listdir(paks):   # read-only files must still be readable
            os.chmod(os.path.join(paks, n), 0o444)
        self.addCleanup(lambda: [os.chmod(os.path.join(paks, n), 0o666) for n in os.listdir(paks)])
        derive.derive_from_install(paks, schemas_path=os.path.join(self.tmp, "schemas.json"))
        self.assertEqual(before, {n: os.path.getmtime(os.path.join(paks, n)) for n in os.listdir(paks)})
        self.assertEqual(sorted(before), sorted(os.listdir(paks)))


class ZenAndPropertyTests(unittest.TestCase):
    def test_zen_package_round_trip(self):
        n = F.Names("Alpha")
        data = F.zen_package("/Game/X/Pkg", n, [("Pkg", F.SCRIPT | 5, b"\x00\x01"), ("Other", zen.NULL_INDEX, b"zz")],
                             imported_packages=["/Game/Y/Dep"])
        pk = zen.ZenPackage(data, "x")
        self.assertEqual(pk.name, "/Game/X/Pkg")
        self.assertTrue(pk.unversioned)
        self.assertEqual([e.name for e in pk.exports], ["Pkg", "Other"])
        self.assertEqual(pk.export_data(pk.exports[1]), b"zz")
        self.assertEqual(pk.imported_package_names, ["/Game/Y/Dep"])
        self.assertEqual(pk.resolve(F.SCRIPT | 5, {F.SCRIPT | 5: "/Script/M.C"}), (zen.SCRIPT_IMPORT, "/Script/M.C"))
        self.assertEqual(pk.resolve(1), (zen.EXPORT, "Other"))
        self.assertEqual(pk.resolve(zen.NULL_INDEX), (zen.NULL, None))

    def test_versioned_package_is_refused(self):
        data = bytearray(F.zen_package("/Game/P", F.Names(), []))
        data[0] = 1
        with self.assertRaises(iostore.FormatError):
            zen.ZenPackage(bytes(data))

    def test_script_objects(self):
        so = zen.load_script_objects(F.script_objects({"ItemData": F.SCRIPT | 7}))
        self.assertEqual(so[F.SCRIPT | 7], "/Script/Dominion.ItemData")

    def test_header_with_zero_mask(self):
        b = F.header([1, 2, 3, 40], zeros={2})
        present, end = uprops.read_header(b)
        self.assertEqual(present, [(1, False), (2, True), (3, False), (40, False)])
        self.assertEqual(end, len(b))
        self.assertEqual(uprops.read_header_strict(b)[0], present)
        self.assertEqual(uprops.read_header(F.header([]))[0], [])

    def test_strict_header_rejects_garbage(self):
        for junk in (struct.pack("<HH", 0x0000, 0x0100), struct.pack("<H", 0x0080 | 0x0100 | (1 << 9)) + b"\0", b"\x01"):
            with self.assertRaises(uprops.Fail):
                uprops.read_header_strict(junk)

    def test_values(self):
        n = F.Names("Tag.A")
        b = F.fstring("hello") + F.text_st(n, "/Game/ST.ST", "K") + F.text_base("Src") \
            + struct.pack("<Ib", 0, -1) + struct.pack("<i", 0) + n.fname("/Game/Soft") + n.fname("Soft") + F.fstring("")
        pk = zen.ZenPackage(F.zen_package("/Game/P", n, []), "p")   # after all names are added
        inst = uprops.Inst(b, pk)
        s, p = uprops.read_str(inst, 0)
        t1, p = uprops.read_text(inst, p)
        t2, p = uprops.read_text(inst, p)
        t3, p = uprops.read_text(inst, p)
        soft, p = uprops.read_soft(inst, p)
        self.assertEqual((s, t1, t2["source"], t3), ("hello", {"type": "st", "table": "/Game/ST.ST", "key": "K"},
                                                     "Src", {"type": "none"}))
        self.assertEqual((soft, p), (("/Game/Soft", "Soft", ""), len(b)))
        with self.assertRaises(uprops.Fail):
            uprops.read_soft(inst, 0)               # 'hello' is not a package path
        with self.assertRaises(uprops.Fail):
            uprops.read_text(uprops.Inst(struct.pack("<Ib", 0, 42), pk), 0)

    def test_decoder_checks_the_exact_end(self):
        n = F.Names("Item.Tag", "A", "B")
        pk = zen.ZenPackage(F.zen_package("/Game/P", n, []), "p")
        sch = {(1,): ("fix", 4), (3,): ("struct",), (3, 0): ("fix", 8), (4,): ("arr",), (4, "e"): ("str",),
               (5,): ("map",), (5, "k"): ("fix", 8), (5, "v"): ("fix", 1)}
        body = F.header([1, 3, 4, 5]) + struct.pack("<i", -1) + F.header([0]) + n.fname("Item.Tag") \
            + struct.pack("<i", 2) + F.fstring("a") + F.fstring("b") \
            + struct.pack("<ii", 0, 2) + n.fname("A") + b"\x01" + n.fname("B") + b"\x02"
        out = decode.Decoder(sch, pk).decode(uprops.Inst(body, pk, "t"))
        self.assertEqual(out[1].i, -1)
        self.assertEqual(out[3][0].name, "Item.Tag")
        self.assertEqual(out[4], ["a", "b"])
        self.assertEqual([(k.name, v) for k, v in out[5]], [("A", 1), ("B", 2)])
        with self.assertRaises(decode.SchemaMismatch):
            decode.Decoder(sch, pk).decode(uprops.Inst(body + b"\0", pk, "t"))
        with self.assertRaises(decode.SchemaMismatch):
            decode.Decoder({(1,): ("fix", 4)}, pk).decode(uprops.Inst(body, pk, "t"))

    def test_string_table(self):
        st = F.header([]) + struct.pack("<i", 0) + F.fstring("NS") + struct.pack("<i", 1) \
            + F.fstring("k") + F.fstring("v")
        pk = zen.ZenPackage(F.zen_package("/Game/ST", F.Names(), [("ST", F.SCRIPT | 1, st)]), "st")
        self.assertEqual(stringtable.decode(pk, pk.exports[0]), ("NS", {"k": "v"}))


class SchemaFileTests(unittest.TestCase):
    def test_bundled_schemas(self):
        sch = schemas.load_schemas()
        self.assertEqual(sch["ItemData"][1], schemas.ITEM_ID)
        part = sch[schemas.ITEM_PART][0]
        for idx, t in ((1, ("text",)), (12, ("fix", 4)), (17, ("struct",)), (20, ("arr",)), (25, ("fix", 4)),
                       (36, ("str",)), (37, ("str",))):
            self.assertEqual(part[(idx,)], t, idx)
        self.assertEqual(sch["RecipeData"][1], 23)
        self.assertEqual(sch["SkillPerkData"][1], 9)

    def test_no_local_paths_in_schemas(self):
        with open(schemas.default_path(), encoding="utf-8") as f:
            text = f.read()
        self.assertNotRegex(text, r"[A-Za-z]:[\\/]|Users[\\/]|AppData")

    def test_key_round_trip(self):
        for k in ((1,), (20, "e"), (5, "k", 0)):
            self.assertEqual(schemas.str_to_key(schemas.key_to_str(k)), k)


class DeriveTests(_TmpCase):
    def setUp(self):
        super().setUp()
        self.root, self.schemas = F.make_game(self.tmp)
        self.items, self.unlocks, self.info = derive.derive_from_install(
            install.find_paks_dir(self.root), schemas_path=self.schemas)
        self.by_id = {i["id"]: i for i in self.items}

    def test_items(self):
        ids = F.ITEM_IDS
        self.assertEqual(set(self.by_id), {ids["ash"], ids["sword"], ids["rune"], ids["thing"]})  # not Art/
        ash = self.by_id[ids["ash"]]
        self.assertEqual((ash["name"], ash["max_stack"], ash["inv_tab"], ash["category"], ash["retired"]),
                         ("Ash Logs", 99, "bag", "Resource", False))
        sword = self.by_id[ids["sword"]]
        self.assertEqual((sword["max_durability"], sword["max_stack"]), (500, 1))
        thing = self.by_id[ids["thing"]]
        self.assertEqual((thing["name"], thing["derived_name"], thing["retired"]), ("Res Unnamed Thing", True, True))

    def test_partial_decode_with_suffix_alignment(self):
        rune = self.by_id[F.ITEM_IDS["rune"]]   # MagicAmmoData: no schema of its own
        self.assertEqual((rune["name"], rune["max_stack"], rune["inv_tab"], rune["category"]),
                         ("Air Rune", 9999, "rune", "Ammo"))
        self.assertEqual(self.info["partial_files"], ["/UmbralSands/Items/ITEM_Rune_Air"])
        self.assertEqual(self.info["item_tails_decoded"], 1)

    def test_unlock_names(self):
        self.assertEqual(set(self.unlocks), set(C.UNLOCK_SECTIONS))
        skill = self.unlocks["Skills"][F.ITEM_IDS["skill"]]
        self.assertEqual((skill["name"], skill["max_level"], skill["asset"]), ("Farming", 99, "SKILL_Farming"))

    def test_sources_are_package_paths_and_info_has_no_paths(self):
        for it in self.items:
            self.assertRegex(it["source"], r"^/(Game|UmbralSands)/[^:\\]+$")
        self.assertEqual(self.info["game_version"], "9.9.9.9")
        self.assertEqual((self.info["fully_decoded"], self.info["partly_decoded"], self.info["unparsable_files"]),
                         (4, 1, []))
        self.assertNotIn(self.tmp, json.dumps(self.info))
        self.assertNotIn(self.tmp, json.dumps([self.items, self.unlocks]))

    def test_unreadable_package_is_reported_not_fatal(self):
        paks = install.find_paks_dir(self.root)
        utoc = os.path.join(paks, "RSDragonwilds-Windows.utoc")
        with iostore.IoStore(utoc) as st:
            idx = st.files["RSDragonwilds/Content/Gameplay/Items/Resources/ITEM_Resources_Wood_Ash.uasset"]
            off = st.offlen[idx][0]
        with open(utoc[:-5] + ".ucas", "r+b") as f:   # break that package's summary
            f.seek(off)
            f.write(struct.pack("<I", 1))
        items, _u, info = derive.derive_from_install(paks, schemas_path=self.schemas)
        self.assertEqual(len(info["unparsable_files"]), 1)
        self.assertIn("ITEM_Resources_Wood_Ash", info["unparsable_files"][0])
        self.assertNotIn(F.ITEM_IDS["ash"], {i["id"] for i in items})


class InstallTests(_TmpCase):
    def fake_install(self, *parts):
        root = os.path.join(self.tmp, *parts)
        paks = os.path.join(root, *install.PAKS_REL)
        os.makedirs(paks)
        for n in (game.CONTAINER, game.GLOBAL_CONTAINER):
            open(os.path.join(paks, n), "wb").close()
        return root

    def test_paks_dir_of_accepts_root_subfolder_and_paks(self):
        root = self.fake_install("Games", "RuneScape Dragonwilds")
        paks = os.path.join(root, *install.PAKS_REL)
        for folder in (root, os.path.join(root, "RSDragonwilds"), paks):
            self.assertEqual(install.paks_dir_of(folder), paks)
        self.assertEqual(install.install_root(paks), root)
        self.assertIsNone(install.paks_dir_of(self.tmp))
        self.assertIsNone(install.paks_dir_of(None))

    def test_steam_libraries(self):
        steam = os.path.join(self.tmp, "Steam")
        lib = os.path.join(self.tmp, "Lib2")
        root = self.fake_install("Lib2", "steamapps", "common", "RuneScape Dragonwilds")
        os.makedirs(os.path.join(steam, "steamapps"))
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n'
                    '\t\t"apps"\n\t\t{\n\t\t\t"123"\t\t"456"\n\t\t}\n\t}\n}\n'
                    % (steam.replace("\\", "\\\\"), lib.replace("\\", "\\\\")))
        self.assertEqual(install.steam_candidates([steam]), [root])
        found = install.candidates(steam_roots=[steam], log_dir=self.tmp, drives=[])
        self.assertEqual(found, [(root, "Steam library")])

    @unittest.skipUnless(sys.platform == "win32", "the game log records Windows drive-letter paths")
    def test_game_log(self):
        root = self.fake_install("Elsewhere", "DW")
        logs = os.path.join(self.tmp, "Logs")
        os.makedirs(logs)
        with open(os.path.join(logs, "RSDragonwilds.log"), "w", encoding="utf-8") as f:
            f.write("LogInit: Display: Loading %s/RSDragonwilds/Binaries/Win64/X.dll\n"
                    % root.replace("\\", "/"))
        self.assertEqual([os.path.normcase(p) for p in install.log_candidates(logs)], [os.path.normcase(root)])
        found = install.candidates(steam_roots=[], log_dir=logs, drives=[])
        self.assertEqual([(os.path.normcase(r), how) for r, how in found], [(os.path.normcase(root), "game log")])

    def test_common_folders_and_dedup(self):
        root = self.fake_install("Games", "Dragonwilds")
        found = install.candidates(steam_roots=[], log_dir=self.tmp, drives=[self.tmp])
        self.assertEqual(found, [(root, "common folder")])
        steam_root = self.fake_install("SteamLibrary", "steamapps", "common", "RSDragonwilds")
        found = install.candidates(steam_roots=[os.path.join(self.tmp, "SteamLibrary")], log_dir=self.tmp,
                                   drives=[self.tmp])
        self.assertEqual(found, [(steam_root, "Steam library"), (root, "common folder")])

    def test_find_paks_dir(self):
        root = self.fake_install("G", "Dragonwilds")
        self.assertEqual(install.find_paks_dir(root), os.path.join(root, *install.PAKS_REL))
        with self.assertRaises(C.GameNotFoundError):
            install.find_paks_dir(self.tmp)
        with self.assertRaises(C.GameNotFoundError):
            install.find_paks_dir(None, steam_roots=[], log_dir=self.tmp, drives=[])
        self.assertEqual(install.find_paks_dir(None, steam_roots=[], log_dir=self.tmp,
                                               drives=[os.path.join(self.tmp, "G")]),
                         os.path.join(root, *install.PAKS_REL))


class NoNetworkTests(unittest.TestCase):
    """The editor makes no network connections: no module of the package imports a networking
    library. The only exception is gui/about.py's webbrowser call, which opens the user's own
    browser when they click one of its two link buttons."""

    NETWORK = ("socket", "ssl", "http", "urllib.request", "urllib.error", "ftplib", "smtplib", "poplib",
               "imaplib", "telnetlib", "xmlrpc", "asyncio", "requests", "httpx", "aiohttp", "urllib3",
               "websocket", "selectors")

    def test_package_imports_no_network_modules(self):
        pkg = paths.base_dir() if not getattr(__import__("sys"), "frozen", False) else None
        self.assertTrue(pkg and os.path.isdir(pkg))
        offenders, browser = [], []
        for d, _dirs, files in os.walk(pkg):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(d, fn)
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read(), path)
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                        names = [node.module] + ["%s.%s" % (node.module, a.name) for a in node.names]
                    for name in names:
                        if any(name == m or name.startswith(m + ".") for m in self.NETWORK):
                            offenders.append("%s: %s" % (os.path.relpath(path, pkg), name))
                        if name == "webbrowser":
                            browser.append(os.path.relpath(path, pkg).replace(os.sep, "/"))
        self.assertEqual(offenders, [])
        self.assertEqual(browser, ["gui/about.py"])

    def test_no_urls_fetched(self):
        for d, _dirs, files in os.walk(paths.base_dir()):
            for fn in files:
                if fn.endswith(".py"):
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        text = f.read()
                    self.assertNotIn("urlopen", text, fn)
                    self.assertNotIn("githubusercontent", text, fn)


@unittest.skipUnless(GAME_DIR, "set DW_TEST_GAME_DIR to a RuneScape: Dragonwilds install folder")
class RealInstallTests(unittest.TestCase):
    """Read-only checks against a real installation (run locally, never on CI)."""

    @classmethod
    def setUpClass(cls):
        cls.paks = install.find_paks_dir(GAME_DIR)
        cls.items, cls.unlocks, cls.info = C.derive_from_game(GAME_DIR)

    def test_self_check_passes(self):
        bundled = (C.load_catalog("items", bundled_dir=C.bundled_dir(), out_dir=os.devnull),
                   C.load_catalog("unlock_names", bundled_dir=C.bundled_dir(), out_dir=os.devnull))
        self.assertEqual(C.self_check(self.items, self.unlocks, self.info, bundled), [])
        self.assertEqual(self.info["unparsable_files"], [])
        self.assertNotIn(GAME_DIR.rstrip("\\/"), json.dumps([self.info, self.items, self.unlocks]))

    def test_matches_bundled_catalog_for_the_same_game_version(self):
        binfo = C.bundled_status()
        if binfo.get("game_version") != self.info["game_version"]:
            self.skipTest("installed game %s, bundled catalog %s" % (self.info["game_version"], binfo.get("game_version")))
        tmp = tempfile.mkdtemp(prefix="dwgd_real_")
        try:
            shutil.copyfile(os.path.join(C.bundled_dir(), C.BUILD_INFO), os.path.join(tmp, C.BUILD_INFO))
            C.write_bundle(tmp, self.items, self.unlocks, self.info)
            for name in C.BUNDLED_FILES + (C.BUILD_INFO,):
                with open(os.path.join(C.bundled_dir(), name), "rb") as a, open(os.path.join(tmp, name), "rb") as b:
                    self.assertEqual(a.read(), b.read(), name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_map_and_lodestone_data_verify(self):
        from dragonwilds_save_editor.gamedata import world
        with game.GameData(self.paks) as gd:
            rep = world.verify(gd)
        self.assertEqual(rep["problems"], [])
        self.assertEqual((rep["shrines"]["install"], rep["kebbit_burrows"]["install"]), (21, 19))
        self.assertEqual(rep["fog_bits"]["install_region_ids"], list(range(1, 32)))
        self.assertEqual(rep["lodestones"]["install_actors"], 4)


if __name__ == "__main__":
    unittest.main()
