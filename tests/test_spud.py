"""Tests for dragonwilds_save_editor/spud.py (clean-room SPUD world-save reader/writer).

Synthetic tests build tiny SPUD files in memory and always run. Real-file tests run only
when DW_TEST_WORLD names world saves (a .sav, a folder of them, or several separated by
os.pathsep); they copy them into a temp dir (the originals are only read).
"""

import hashlib
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

try:
    from . import _helpers as H  # isolated LOCALAPPDATA; DW_TEST_WORLD lookup
except ImportError:  # discovered as a top-level module
    import _helpers as H

from dragonwilds_save_editor import spud as S  # noqa: E402

FS = S.encode_fstring
VER = b"\x0a\x02\x00\x00\xf9\x03\x00\x00"


# ---------------------------------------------------------------------------
# Synthetic file builder
# ---------------------------------------------------------------------------
def chunk(magic, payload):
    return magic + struct.pack("<I", len(payload)) + payload


def strtab(names):
    return struct.pack("<I", len(names)) + b"".join(FS(n) for n in names)


def cdef(name, props):
    return FS(name) + struct.pack("<H", len(props)) + b"".join(struct.pack("<IIH", *p) for p in props)


def prop_block(values):
    offs, o = [], 0
    for v in values:
        offs.append(o)
        o += len(v)
    return (struct.pack("<I", len(values)) + b"".join(struct.pack("<I", x) for x in offs) +
            struct.pack("<I", o) + b"".join(values))


def meta(classes, props, defs):
    """defs: {class name: [(prop name, prefix name or None, type)]} (None = empty CDVE)."""
    cl = b""
    for c in classes:
        d = defs.get(c)
        if d is None:
            cl += chunk(b"CDVE", b"")
            continue
        rows = [(props.index(n), 0xFFFFFFFF if pre is None else props.index(pre), t) for n, pre, t in d]
        cl += chunk(b"CDVE", b"\x00" + chunk(b"CDEF", cdef(c, rows)))
    return chunk(b"META", chunk(b"VERS", struct.pack("<I", 5)) + chunk(b"CNIX", strtab(classes)) +
                 chunk(b"PNIX", strtab(props)) + chunk(b"CLST", cl))


def tagged(name, typ, value, flags=0):
    """One UE5 tagged property; typ is a (name, [params]) tree."""
    return FS(name) + S._encode_type_name(typ) + struct.pack("<I", len(value)) + bytes([flags]) + value


def tag_key(tag):
    return tagged("TagName", ("NameProperty", []), FS(tag)) + FS("None")


def string_set(names):
    return b"\x00\x00\x00\x00" + struct.pack("<I", len(names)) + b"".join(FS(n) for n in names)


def tag_map(entries):
    return (b"\x00\x00\x00\x00" + struct.pack("<I", len(entries)) +
            b"".join(tag_key(t) + v for t, v in entries))


CORA = chunk(b"CORA", b"\x9b\x00\x00\x00" + bytes(range(155)))
GUID_A = bytes(range(16))
CHAR_GUID = bytes(range(100, 116))


def cached_record():
    inner = tagged("InnerGuid", ("StructProperty", [("Guid", [("/Script/CoreUObject", [])])]), CHAR_GUID, 0x08) + FS("None")
    elem = (tagged("CharacterGuid", ("StructProperty", [("DomCharacterGuid", [("/Script/Dominion", [])])]), inner) +
            tagged("State", ("StrProperty", []), FS('{"meta_data": {"char_name": "Guest"}}')) + FS("None"))
    return struct.pack("<I", 1) + elem


def build_world(bosses=("ai_boss_velgar", "ai_boss_imaru"),
                tags=(("WorldProgress.Imaru.CanSpawnImaru", b"\0\0\0\0"),
                      ("WorldProgress.Imaru.PendingSealDoor", b"\0\0\0\0")),
                hooks=("/Game/WH_A.WH_A",), name="Synthetic World"):
    # ---- INFO
    info_hdr = b"\x08\x00" + VER + b"\0\0\0\0" + b"\xff" + b"\0\0\0\0" + FS("2026-11-25T00:00:00.000Z")
    keys = ["VERSION", "WorldName"]
    vals = [struct.pack("<I", 9), FS(name.split()[0])]
    cinf = strtab(keys) + prop_block(vals)
    info = chunk(b"INFO", info_hdr + chunk(b"CINF", cinf))
    # ---- GLOB
    gclasses = ["/Script/Dominion.PersistenceSubsystem"]
    gprops = ["WorldSaveSettings", "WorldName", "SaveFileRevision"]
    gmeta = meta(gclasses, gprops, {gclasses[0]: [("WorldName", "WorldSaveSettings", 30),
                                                  ("SaveFileRevision", "WorldSaveSettings", 6)]})
    gobj = chunk(b"NOBJ", struct.pack("<I", 0) + FS("DomPersistence") + b"\0\0\0\0" + VER +
                 chunk(b"PROP", prop_block([FS(name), struct.pack("<i", 3)])))
    glai = chunk(b"GLAI", chunk(b"LVNI", strtab(["L_World"])) + FS("Actor_1") + struct.pack("<I", 0))
    glob = chunk(b"GLOB", FS("L_World") + gmeta + chunk(b"GOBS", gobj) + glai)
    # ---- LEVL L_World
    classes = ["/Script/Dominion.WorldProgressManager", "/Game/BP_Lever.BP_Lever_C",
               "/Script/Dominion.HealthComponent", "/Script/Unused.NoDef",
               "/Script/Dominion.CachedCharacterStates", "/Game/BP_Spawned.BP_Spawned_C"]
    props = ["WorldHooksTriggered", "DefeatedBossesInternalNames", "TaggedWorldProgressValues",
             "bCanBeDamaged", "SwitchState", "SwitchPosition", "ServerTimeOfInteraction",
             "Health Component", "AuthoritativeHealth", "Label", "Empty Component",
             "CachedCharacterStates", "Counts", "Owner"]
    defs = {
        classes[0]: [("WorldHooksTriggered", None, 64), ("DefeatedBossesInternalNames", None, 64),
                     ("TaggedWorldProgressValues", None, 64), ("bCanBeDamaged", None, 0)],
        classes[1]: [("ServerTimeOfInteraction", "SwitchState", 8), ("SwitchPosition", "SwitchState", 0),
                     ("Health Component", None, 40), ("Empty Component", None, 40), ("bCanBeDamaged", None, 0)],
        classes[2]: [("AuthoritativeHealth", None, 8), ("Label", None, 30)],
        classes[4]: [("CachedCharacterStates", None, 64), ("bCanBeDamaged", None, 0)],
        classes[5]: [("Counts", None, 0x1006), ("Owner", None, 31)],
    }
    m = meta(classes, props, defs)
    wpm = chunk(b"NOBJ", struct.pack("<I", 0) + FS("WorldProgressManager_1") + b"\0\0\0\0" + VER + CORA +
                chunk(b"PROP", prop_block([string_set(list(hooks)), string_set(list(bosses)),
                                           tag_map(list(tags)), b"\x01"])))
    comp = struct.pack("<I", 2) + prop_block([struct.pack("<f", 750.0), FS("hp")])
    lever = chunk(b"NOBJ", struct.pack("<I", 1) + FS("BP_Lever_C_UAID_1") + b"\0\0\0\0" + VER + CORA +
                  chunk(b"PROP", prop_block([struct.pack("<f", 12.5), b"\x01", comp, b"\xff\xff\xff\xff", b"\x01"])) +
                  chunk(b"CUST", b"\x04\x00\x00\x00CUST"))
    cached = chunk(b"NOBJ", struct.pack("<I", 4) + FS("CachedCharacterStates_1") + b"\0\0\0\0" + VER + CORA +
                   chunk(b"PROP", prop_block([cached_record(), b"\x01"])))
    spawn_hdr = struct.pack("<I", 5) + GUID_A + bytes(48) + b"\x01" + VER + struct.pack("<II", 1, 7)
    spwn = chunk(b"SPWN", spawn_hdr + CORA +
                 chunk(b"PROP", prop_block([struct.pack("<H", 2) + struct.pack("<ii", 5, -6), FS("NAME")])))
    kill = chunk(b"KILL", FS("BP_Breakable_Wall_C_UAID_9"))
    levl = chunk(b"LEVL", FS("L_World") + VER + m + chunk(b"LATS", wpm + lever + cached) +
                 chunk(b"SATS", spwn) + chunk(b"DATS", kill))
    # second, nearly empty cell level
    m2 = meta(["/Game/BP_Lever.BP_Lever_C", "/Script/Dominion.HealthComponent"], props,
              {"/Game/BP_Lever.BP_Lever_C": [("bCanBeDamaged", None, 0)]})
    cell = chunk(b"LEVL", FS("RSACell12800_X1_Y1") + VER + m2 +
                 chunk(b"LATS", chunk(b"NOBJ", struct.pack("<I", 0) + FS("BP_Lever_C_UAID_2") + b"\0\0\0\0" + VER +
                                      CORA + chunk(b"PROP", prop_block([b"\x00"])))) +
                 chunk(b"SATS", b"") + chunk(b"DATS", b""))
    return chunk(b"SAVE", info + glob + chunk(b"LVLS", levl + cell))


def check_lengths(raw):
    """Independent IFF length check for the known containers (outside dw_spud's parser)."""
    assert raw[:4] == b"SAVE" and struct.unpack_from("<I", raw, 4)[0] + 8 == len(raw)


# ---------------------------------------------------------------------------
# Synthetic tests
# ---------------------------------------------------------------------------
class PrimitiveTests(unittest.TestCase):
    def test_fstring_roundtrip(self):
        for s in ["", "abc", "ai_boss_imaru", "Bjørn ☃"]:
            b = FS(s)
            self.assertEqual(S.read_fstring(b, 0), (s, len(b)))
        self.assertEqual(FS(""), b"\0\0\0\0")
        self.assertLess(struct.unpack_from("<i", FS("☃"))[0], 0)

    def test_fstring_errors(self):
        with self.assertRaises(S.FormatError):
            S.read_fstring(b"\x05\0\0\0abc", 0)
        with self.assertRaises(S.FormatError):
            S.read_fstring(b"\x04\0\0\0abcd", 0)   # no NUL

    def test_type_name(self):
        self.assertEqual(S.type_name(0), "UInt8")
        self.assertEqual(S.type_name(64), "Record")
        self.assertEqual(S.type_name(0x1006), "Array<Int32>")
        self.assertEqual(S.type_name(77), "Type77")

    def test_string_set(self):
        raw = string_set(["a", "bb"])
        prefix, names = S.decode_string_set(raw)
        self.assertEqual(names, ["a", "bb"])
        self.assertEqual(S.encode_string_set(prefix, names), raw)
        with self.assertRaises(S.FormatError):
            S.decode_string_set(raw + b"x")

    def test_tag_map(self):
        raw = tag_map([("A.B", struct.pack("<i", 7)), ("C", struct.pack("<f", 1.5))])
        prefix, ents = S.decode_tag_map(raw)
        self.assertEqual([e["tag"] for e in ents], ["A.B", "C"])
        self.assertEqual(ents[0]["int"], 7)
        self.assertEqual(ents[1]["float"], 1.5)
        self.assertEqual(S.encode_tag_map(prefix, ents), raw)
        self.assertEqual(S.encode_tag_map(prefix, [(e["tag"], e["value"]) for e in ents]), raw)

    def test_tagged_props(self):
        raw = cached_record()
        props, p = S.decode_tagged_props(raw, 4)
        self.assertEqual(p, len(raw))
        self.assertEqual([x["name"] for x in props], ["CharacterGuid", "State"])
        self.assertEqual(props[0]["value"][0]["value"], S._guid_str(CHAR_GUID))
        with self.assertRaises(S.FormatError):
            S.decode_tagged_props(raw[:-5], 4)


class SyntheticWorldTests(unittest.TestCase):
    def setUp(self):
        self.raw = build_world()
        self.w = S.WorldFile.from_bytes(self.raw)

    def test_parse(self):
        w = self.w
        self.assertEqual(w.object_count(), 6)   # global + 3 named + 1 spawned + 1 cell object
        self.assertEqual(w.world_name(), "Synthetic World")
        self.assertEqual(w.defeated_bosses(), ["ai_boss_velgar", "ai_boss_imaru"])
        self.assertEqual(w.world_hooks(), ["/Game/WH_A.WH_A"])
        self.assertEqual(w.progress_tags(), ["WorldProgress.Imaru.CanSpawnImaru",
                                             "WorldProgress.Imaru.PendingSealDoor"])
        lv = w.level("L_World")
        self.assertEqual(lv.destroyed, ["BP_Breakable_Wall_C_UAID_9"])
        lever = w.find_object("BP_Lever_C")
        self.assertEqual(lever.key, "L_World|BP_Lever_C_UAID_1")
        self.assertIs(w.object_by_key(lever.key), lever)
        self.assertEqual(lever.prop("SwitchState/ServerTimeOfInteraction").value, 12.5)
        self.assertEqual(lever.prop("Health Component/AuthoritativeHealth").value, 750.0)
        self.assertEqual(lever.prop("Health Component").value, "/Script/Dominion.HealthComponent")
        self.assertIsNone(lever.prop("Empty Component").component)
        sp = w.find_objects("BP_Spawned")[0]
        self.assertEqual(sp.kind, "SPWN")
        self.assertEqual(sp.prop("Counts").value, [5, -6])
        self.assertEqual(sp.prop("Owner").as_dict()["value"], "NAME")
        self.assertEqual(len(w.find_objects("", "lever")), 2)
        self.assertEqual(w.cached_characters()[0]["name"], "Guest")
        self.assertEqual(w.cached_characters()[0]["guid"], S._guid_str(CHAR_GUID))
        self.assertEqual(w.progress_manager().short_class, "WorldProgressManager")

    def test_round_trip(self):
        self.assertEqual(self.w.to_bytes(), self.raw)
        self.assertEqual(self.w.to_bytes(rebuild=True), self.raw)
        self.assertFalse(self.w.dirty)

    def test_bad_files(self):
        with self.assertRaises(S.FormatError):
            S.WorldFile.from_bytes(b"NOPE\0\0\0\0")
        with self.assertRaises(S.FormatError):
            S.WorldFile.from_bytes(self.raw + b"\0")          # SAVE length != size
        bad = bytearray(self.raw)
        i = bad.find(b"LATS")
        bad[i + 4] ^= 1                                      # break a nested length
        with self.assertRaises(S.FormatError):
            S.WorldFile.from_bytes(bytes(bad))

    def test_remove_boss_shrinks_and_reparses(self):
        w = self.w
        self.assertTrue(w.remove_defeated_boss("ai_boss_imaru"))
        self.assertFalse(w.remove_defeated_boss("ai_boss_imaru"))
        self.assertTrue(w.dirty)
        out = w.to_bytes()
        self.assertEqual(len(out), len(self.raw) - len(FS("ai_boss_imaru")))
        self.assertEqual(out, w.to_bytes(rebuild=True))
        check_lengths(out)
        w2 = S.WorldFile.validate_bytes(out)
        self.assertEqual(w2.object_count(), w.object_count())
        self.assertEqual(w2.defeated_bosses(), ["ai_boss_velgar"])
        self.assertTrue(w._verify_new(w2))
        # other objects are byte-identical
        lever = w2.find_object("BP_Lever_C")
        self.assertEqual(lever.prop("Health Component/AuthoritativeHealth").value, 750.0)

    def test_tag_edits(self):
        w = self.w
        self.assertTrue(w.set_tag_value("WorldProgress.Imaru.CanSpawnImaru", 1))
        self.assertTrue(w.set_tag_value("WorldProgress.Imaru.PendingSealDoor", 2.5, as_float=True))
        with self.assertRaises(KeyError):
            w.set_tag_value("Nope", 1)
        self.assertTrue(w.remove_progress_tag("WorldProgress.Imaru.CanSpawnImaru"))
        self.assertFalse(w.remove_progress_tag("WorldProgress.Imaru.CanSpawnImaru"))
        w2 = S.WorldFile.validate_bytes(w.to_bytes())
        vals = w2.tagged_values()
        self.assertEqual([e["tag"] for e in vals], ["WorldProgress.Imaru.PendingSealDoor"])
        self.assertEqual(vals[0]["float"], 2.5)
        w._verify_new(w2)

    def test_component_edits(self):
        w = self.w
        lever = w.find_object("BP_Lever_C")
        self.assertTrue(w.set_scalar(lever, "Health Component/AuthoritativeHealth", 518))
        self.assertTrue(w.set_raw_property(lever, "Health Component/Label", FS("a longer label")))
        self.assertTrue(w.set_scalar(lever, "SwitchState/SwitchPosition", 0))
        self.assertFalse(w.set_scalar(lever, "SwitchState/SwitchPosition", 0))
        with self.assertRaises(ValueError):
            w.set_scalar(lever, "SwitchState/SwitchPosition", 300)
        with self.assertRaises(ValueError):
            w.set_raw_property(lever, "Health Component", b"\xff\xff\xff\xff")
        with self.assertRaises(ValueError):
            w.set_raw_property(lever, "Health Component/Label", b"\x09\0\0\0bad")
        with self.assertRaises(KeyError):
            w.set_scalar(lever, "Nope", 1)
        w2 = S.WorldFile.validate_bytes(w.to_bytes())
        l2 = w2.find_object("BP_Lever_C")
        self.assertEqual(l2.prop("Health Component/AuthoritativeHealth").value, 518.0)
        self.assertEqual(l2.prop("Health Component/Label").value, "a longer label")
        self.assertEqual(l2.prop("SwitchState/SwitchPosition").value, 0)
        self.assertEqual(l2.chunk.child(b"CUST").data, b"\x04\x00\x00\x00CUST")
        w._verify_new(w2)

    def test_verify_detects_wrong_output(self):
        w = self.w
        w.remove_defeated_boss("ai_boss_imaru")
        # an output that does not contain the edit must be rejected
        with self.assertRaises(S.FormatError):
            w._verify_new(S.WorldFile.from_bytes(self.raw))


class SyntheticSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "World.sav")
        with open(self.path, "wb") as f:
            f.write(build_world())
        self.p1 = mock.patch.object(S, "_game_is_running", return_value=False)
        self.p2 = mock.patch.object(S, "_snapshot_saves", return_value="SNAP")
        self.running = self.p1.start()
        self.snap = self.p2.start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def test_multiple_edits_one_save(self):
        w = S.WorldFile(self.path)
        w.remove_defeated_boss("ai_boss_imaru")
        w.set_tag_value("WorldProgress.Imaru.CanSpawnImaru", 5)
        w.set_tag_value("WorldProgress.Imaru.CanSpawnImaru", 6)        # last edit wins
        w.remove_progress_tag("WorldProgress.Imaru.PendingSealDoor")
        lever = w.find_object("BP_Lever_C")
        w.set_raw_property(lever, "Health Component/Label", FS("x" * 40))
        res = w.save()
        self.assertTrue(res["written"])
        self.assertEqual(res["snapshot"], "SNAP")
        self.snap.assert_called_once_with("pre-world-edit")
        self.assertTrue(os.path.exists(res["backup"]))
        self.assertTrue(res["backup"].endswith(".pyedit.bak"))
        with open(res["backup"], "rb") as f:
            self.assertEqual(f.read(), build_world())
        self.assertFalse(w.dirty)
        w2 = S.WorldFile(self.path)
        self.assertEqual(w2.defeated_bosses(), ["ai_boss_velgar"])
        self.assertEqual([(e["tag"], e["int"]) for e in w2.tagged_values()],
                         [("WorldProgress.Imaru.CanSpawnImaru", 6)])
        self.assertEqual(w2.find_object("BP_Lever_C").prop("Health Component/Label").value, "x" * 40)
        self.assertEqual(w2.object_count(), 6)
        self.assertFalse(os.path.exists(self.path + ".pyedit.tmp"))
        # second save from the reloaded object works and backups never overwrite
        w.remove_defeated_boss("ai_boss_velgar")
        res2 = w.save(snapshot=False)
        self.assertNotEqual(res2["backup"], res["backup"])
        self.assertEqual(S.WorldFile(self.path).defeated_bosses(), [])

    def test_refusals_and_dry_run(self):
        w = S.WorldFile(self.path)
        self.assertFalse(w.save()["written"])     # nothing to do
        w.remove_defeated_boss("ai_boss_imaru")
        self.running.return_value = True
        with self.assertRaises(RuntimeError):
            w.save()
        self.running.return_value = False
        res = w.save(dry_run=True)
        self.assertFalse(res["written"])
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), build_world())
        self.snap.assert_not_called()
        # file changed on disk since opening -> refuse
        with open(self.path, "ab") as f:
            f.write(b"")
        os.utime(self.path)
        with open(self.path, "wb") as f:
            f.write(build_world(bosses=("ai_boss_velgar",)))
        with self.assertRaises(RuntimeError):
            w.save()

    def test_backup_names_unique(self):
        w = S.WorldFile(self.path)
        a, b = w.make_backup(), w.make_backup()
        self.assertNotEqual(a, b)
        self.assertTrue(os.path.exists(a) and os.path.exists(b))


class CliTests(unittest.TestCase):
    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "w.sav")
            with open(p, "wb") as f:
                f.write(build_world())
            import io
            import contextlib
            for args in (["info"], ["bosses"], ["tags"], ["objects", "Lever", "--props"], ["selftest"]):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(S.main([p] + args), 0)
                self.assertTrue(buf.getvalue())
            with open(p, "rb") as f:
                self.assertEqual(f.read(), build_world())


# ---------------------------------------------------------------------------
# Real-file tests (read-only on the originals; all edits on temp copies)
# ---------------------------------------------------------------------------
def _real_worlds():
    return H.test_worlds()


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@unittest.skipUnless(_real_worlds(), "set DW_TEST_WORLD to world .sav file(s) to run real-world tests")
class RealWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.sources = _real_worlds()
        cls.hashes = {}
        cls.mtimes = {}
        cls.copies = []
        for i, src in enumerate(cls.sources):
            cls.hashes[src] = _sha(src)
            cls.mtimes[src] = os.path.getmtime(src)
            dst = os.path.join(cls.tmp.name, "world%d.sav" % i)
            shutil.copyfile(src, dst)
            if _sha(dst) != cls.hashes[src]:
                raise unittest.SkipTest("save changed while copying (game running?)")
            cls.copies.append(dst)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.p1 = mock.patch.object(S, "_game_is_running", return_value=False)
        self.p2 = mock.patch.object(S, "_snapshot_saves", return_value="SNAP")
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        mock.patch.stopall()

    def _fresh(self, i):
        path = os.path.join(self.tmp.name, "edit%d.sav" % i)
        shutil.copyfile(self.copies[i], path)
        return path

    def test_full_parse_and_round_trip(self):
        for p in self.copies:
            with open(p, "rb") as f:
                raw = f.read()
            w = S.WorldFile(p)
            self.assertGreater(w.object_count(), 0)
            self.assertEqual(w.to_bytes(), raw)
            self.assertEqual(w.to_bytes(rebuild=True), raw)
            for o in w.all_objects():
                for prop in o.properties():
                    if prop.type not in (29, 40, 64):
                        self.assertTrue(S.decode_value(prop.type, prop.raw)[1], (o.key, prop.path))
            self.assertTrue(w.world_name())
            if w.progress_manager() is not None:
                w.defeated_bosses(), w.world_hooks(), w.tagged_values()
            w.cached_characters()

    def test_edit_and_save_each_world(self):
        for i in range(len(self.copies)):
            path = self._fresh(i)
            w = S.WorldFile(path)
            n = w.object_count()
            size = os.path.getsize(path)
            if w.progress_manager() is None:
                continue
            bosses = w.defeated_bosses()
            tags = w.tagged_values()
            expect_size = size
            if bosses:
                self.assertTrue(w.remove_defeated_boss(bosses[-1]))
                expect_size -= len(FS(bosses[-1]))
            if tags:
                w.set_tag_value(tags[0]["tag"], tags[0]["int"] + 1)
            # always also do a size-changing hook edit so the small world is covered
            pm = w.progress_manager()
            prefix, hooks = S.decode_string_set(pm.prop("WorldHooksTriggered").raw)
            w.set_raw_property(pm, "WorldHooksTriggered", S.encode_string_set(prefix, hooks + ["/Game/T.T"]))
            expect_size += len(FS("/Game/T.T"))
            res = w.save()
            self.assertTrue(res["written"])
            self.assertEqual(os.path.getsize(path), expect_size)
            w2 = S.WorldFile(path)
            self.assertEqual(w2.object_count(), n)
            self.assertEqual(w2.defeated_bosses(), bosses[:-1] if bosses else [])
            self.assertEqual(w2.world_hooks(), hooks + ["/Game/T.T"])
            if tags:
                self.assertEqual(w2.tagged_values()[0]["int"], tags[0]["int"] + 1)
            with open(path, "rb") as f:
                raw = f.read()
            self.assertEqual(S.WorldFile.validate_bytes(raw).object_count(), n)

    def test_multiple_edits_then_revert_is_identical(self):
        i = 0
        path = self._fresh(i)
        with open(path, "rb") as f:
            orig = f.read()
        w = S.WorldFile(path)
        if w.progress_manager() is None:
            self.skipTest("no progress manager")
        pm = w.progress_manager()
        raw = pm.prop("DefeatedBossesInternalNames").raw
        prefix, names = S.decode_string_set(raw)
        w.set_raw_property(pm, "DefeatedBossesInternalNames", S.encode_string_set(prefix, names + ["ai_boss_x"]))
        w.set_raw_property(pm, "DefeatedBossesInternalNames", raw)    # back to the original
        self.assertEqual(w.to_bytes(), orig)
        w.save()
        with open(path, "rb") as f:
            self.assertEqual(f.read(), orig)

    def test_sources_untouched(self):
        for src in self.sources:
            if os.path.getmtime(src) == self.mtimes[src]:   # not re-saved by the game meanwhile
                self.assertEqual(_sha(src), self.hashes[src], src)
            self.assertFalse(os.path.exists(src + ".pyedit.tmp"))


if __name__ == "__main__":
    unittest.main()
