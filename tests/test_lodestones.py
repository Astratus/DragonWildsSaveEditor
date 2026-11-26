"""Tests for dragonwilds_save_editor/lodestones.py (lodestone view + EXPERIMENTAL
fixed-lodestone edits).

The synthetic tests always run. The real-world tests and the GUI smoke test run only when
DW_TEST_WORLD names world saves (see tests/_helpers.test_worlds); they use the first one
that has a lodestone registry, work on temp COPIES and check the original is untouched.
Nothing here touches the real %LOCALAPPDATA%.
"""

import glob
import hashlib
import os
import shutil
import struct
import tempfile
import types
import unittest
from unittest import mock

try:
    from . import _helpers as H  # noqa: F401  (isolated LOCALAPPDATA, DW_TEST_WORLD lookup)
except ImportError:
    import _helpers as H  # noqa: F401

from dragonwilds_save_editor import lodestones as L  # noqa: E402
from dragonwilds_save_editor import save as dw_save  # noqa: E402
from dragonwilds_save_editor import spud as dw_spud  # noqa: E402
from dragonwilds_save_editor.spud import FormatError, encode_fstring  # noqa: E402


def _world_with_registry():
    """First DW_TEST_WORLD save that has a lodestone registry, else None."""
    for p in H.test_worlds():
        try:
            if L.registry_object(dw_spud.WorldFile(p)) is not None:
                return p
        except Exception:
            continue
    return None


TEST_WORLD = _world_with_registry()


def _type(name, *params):
    return encode_fstring(name) + struct.pack("<I", len(params)) + b"".join(params)


def _tag(name, type_bytes, value, flags=0):
    return encode_fstring(name) + type_bytes + struct.pack("<IB", len(value), flags) + value


def _vector(x, y, z):
    body = b"".join(_tag(n, _type("DoubleProperty"), struct.pack("<d", v)) for n, v in zip("XYZ", (x, y, z)))
    body += encode_fstring("None")
    return _type("StructProperty", _type("Vector_NetQuantize", _type("/Script/Engine"))), body


def _entry(guid_hex, x, y, z):
    """Independent test-side encoder (cross-checks L.encode_entry)."""
    t, loc = _vector(x, y, z)
    _, resp = _vector(x, y, z + 145.0)
    g = struct.pack("<4I", *(int(guid_hex[i:i + 8], 16) for i in range(0, 32, 8)))
    gtype = _type("StructProperty", _type("Guid", _type("/Script/CoreUObject")))
    return (_tag("Location", t, loc) + _tag("RespawnLocation", t, resp)
            + _tag("Identifier", gtype, g, 0x08) +  # 0x08 = native-serialized struct (as the game writes it)
            encode_fstring("None"))


TEMPLE = "5E74232B4126EDE0BAEFF9856FFD03C6"
DEATH = "C29B965F4A6FE5855746CDB2FB61F658"
DOWDUN = "BEE7FC7343CE7CEA0DED91847DD83D19"
UMBRAL = "122F25504BAF11D411C40A917C5811F5"
OTHER = "0123456789ABCDEF0123456789ABCDEF"
BUILT = "AAAABBBBCCCCDDDDEEEEFFFF00001111"


class SyntheticRecord(unittest.TestCase):
    def test_parse_two_entries(self):
        a, b = _entry(TEMPLE, 5065.1, 189026.1, -3632.8), _entry(OTHER, 1.0, 2.0, 3.0)
        raw = struct.pack("<I", 2) + a + b
        rows = L.parse_registry_record(raw)
        self.assertEqual([r["id"] for r in rows], [TEMPLE, OTHER])
        self.assertAlmostEqual(rows[0]["location"][1], 189026.1)
        self.assertAlmostEqual(rows[1]["respawn_location"][2], 148.0)
        self.assertEqual(rows[0]["span"], (4, 4 + len(a)))
        self.assertEqual(rows[1]["span"], (4 + len(a), len(raw)))
        # spans tile the record exactly
        self.assertEqual(raw[:4] + b"".join(raw[s:e] for s, e in (r["span"] for r in rows)), raw)

    def test_module_encoder_matches(self):
        for gid, loc in ((TEMPLE, (5065.111060671951, 189026.10601265208, -3632.75931668213)),
                         (OTHER, (-1.5, 0.0, 1e9))):
            self.assertEqual(L.encode_entry(gid, loc), _entry(gid, *loc))

    def test_empty_and_errors(self):
        self.assertEqual(L.parse_registry_record(b"\0\0\0\0"), [])
        good = struct.pack("<I", 1) + _entry(OTHER, 1, 2, 3)
        with self.assertRaises(FormatError):
            L.parse_registry_record(good + b"x")          # trailing bytes
        with self.assertRaises(Exception):
            L.parse_registry_record(struct.pack("<I", 2) + _entry(OTHER, 1, 2, 3))  # count too high

    def test_catalog(self):
        cat = L.load_catalog()
        ids = [c["id"] for c in cat["lodestones"]]
        self.assertEqual(ids, [TEMPLE, DEATH, DOWDUN, UMBRAL])
        for c in cat["lodestones"]:
            self.assertRegex(c["id"], r"^[0-9A-F]{32}$")
            for k in ("name", "area", "source", "confidence", "location"):
                self.assertIn(k, c)


# ---- synthetic edit tests: a minimal stand-in for spud.WorldFile ----------------------

def _record(*ids_locs):
    return struct.pack("<I", len(ids_locs)) + b"".join(_entry(i, *loc) for i, loc in ids_locs)


class _Obj:
    def __init__(self, class_name, props=(), lodestones=None):
        self.class_name, self._props, self.lodestones = class_name, list(props), lodestones
        self.key = self.label = self.short_class = class_name.rsplit(".", 1)[-1]
        self.level = types.SimpleNamespace(name="L_World")

    def properties(self):
        return list(self._props)

    def prop(self, path):
        if path == "Lodestones" and self.lodestones is not None:
            return types.SimpleNamespace(raw=self.lodestones)
        return None


def _built_actor(gid):
    """spud shape: a type-40 Property whose .component (PropBlock) holds the members;
    properties() is flat, so the member follows its component."""
    child = types.SimpleNamespace(name="GameplayObjectRegistryIdentifier", value=gid, type=23, component=None,
                                  path="Lodestone Component/GameplayObjectRegistryIdentifier")
    block = types.SimpleNamespace(class_name="/Script/Dominion.LodestoneComponent", props=[child])
    comp = types.SimpleNamespace(name="Lodestone Component", type=40, component=block,
                                 path="Lodestone Component", value=block.class_name)
    return _Obj(L.BUILT_CLASS, [comp, child])


class FakeWorld:
    """Just enough of dw_spud.WorldFile: the 'file' is the Lodestones record itself."""

    corrupt = False    # validate_bytes returns a world with a damaged registry (rollback test)

    def __init__(self, path=None, raw=None, built=()):
        self.original = bytes(raw)
        self.reg = _Obj(L.REGISTRY_CLASS, lodestones=self.original)
        self.objs = [self.reg] + [_built_actor(g) for g in built]
        self.edits = 0      # set_raw_property calls that changed the bytes

    @classmethod
    def from_bytes(cls, data, path=None):
        return cls(raw=data)

    @staticmethod
    def validate_bytes(raw):
        w2 = FakeWorld(raw=raw)
        if FakeWorld.corrupt:
            w2.reg.lodestones = struct.pack("<I", 0)
        return w2

    def all_objects(self):
        return list(self.objs)

    def object_count(self):
        return 1   # validate_bytes() copies only the registry, so count just that

    def set_raw_property(self, obj, prop_path, new_bytes):
        assert obj is self.reg and prop_path == "Lodestones"
        changed = bytes(new_bytes) != self.reg.lodestones
        self.reg.lodestones = bytes(new_bytes)
        self.edits += changed
        return changed

    def to_bytes(self):
        return self.reg.lodestones


CAT = L.load_catalog()
CATLOC = {c["id"]: tuple(c["location"]) for c in CAT["lodestones"]}


class SyntheticEdits(unittest.TestCase):
    def world(self, *ids, built=()):
        return FakeWorld(raw=_record(*((i, CATLOC.get(i, (1.0, 2.0, 3.0))) for i in ids)), built=built)

    def ids(self, w):
        return [e["id"] for e in L.parse_registry_record(w.to_bytes())]

    def test_activate_appends_and_deactivate_restores(self):
        w = self.world(TEMPLE, BUILT, built=[BUILT])
        before = w.to_bytes()
        self.assertTrue(L.activate_lodestone(w, CAT["lodestones"][3]))   # dict form
        self.assertEqual(self.ids(w), [TEMPLE, BUILT, UMBRAL])
        e = L.parse_registry_record(w.to_bytes())[2]
        self.assertEqual(e["location"], CATLOC[UMBRAL])
        self.assertEqual(e["respawn_location"][2], CATLOC[UMBRAL][2] + 145.0)
        self.assertTrue(L.deactivate_lodestone(w, UMBRAL))
        self.assertEqual(w.to_bytes(), before)        # byte-exact after activate + deactivate
        self.assertEqual(w.edits, 2)

    def test_deactivate_keeps_order_then_reactivate_restores_position(self):
        w = self.world(TEMPLE, DEATH, OTHER, DOWDUN, BUILT, built=[BUILT])
        before = w.to_bytes()
        self.assertTrue(L.deactivate_lodestone(w, DEATH))
        self.assertEqual(self.ids(w), [TEMPLE, OTHER, DOWDUN, BUILT])
        self.assertTrue(L.deactivate_lodestone(w, DOWDUN.lower()))   # case-insensitive id
        self.assertEqual(self.ids(w), [TEMPLE, OTHER, BUILT])
        self.assertTrue(L.activate_lodestone(w, DOWDUN))   # back where it was, not appended
        self.assertTrue(L.activate_lodestone(w, DEATH))
        self.assertEqual(w.to_bytes(), before)
        self.assertEqual(w.edits, 4)

    def test_fresh_activation_after_save_appends(self):
        w = self.world(TEMPLE, DEATH, BUILT, built=[BUILT])
        L.deactivate_lodestone(w, DEATH)
        w2 = FakeWorld(raw=w.to_bytes(), built=[BUILT])   # "saved and reopened"
        L.activate_lodestone(w2, DEATH)
        self.assertEqual(self.ids(w2), [TEMPLE, BUILT, DEATH])
        # catalog location = the exact doubles, so the re-encoded entry matches the original
        self.assertEqual(L.parse_registry_record(w2.to_bytes())[2]["location"], CATLOC[DEATH])

    def test_noop(self):
        w = self.world(TEMPLE)
        self.assertFalse(L.activate_lodestone(w, TEMPLE))
        self.assertFalse(L.deactivate_lodestone(w, UMBRAL))
        self.assertEqual(w.edits, 0)

    def test_refuses_unknown_and_built(self):
        w = self.world(TEMPLE, BUILT, built=[BUILT])
        before = w.to_bytes()
        for fn in (L.activate_lodestone, L.deactivate_lodestone):
            with self.assertRaises(L.LodestoneEditError):
                fn(w, OTHER)          # not in the fixed catalog
            with self.assertRaisesRegex(L.LodestoneEditError, "build/demolish"):
                fn(w, BUILT)          # a built lodestone's registry entry
        with self.assertRaises(L.LodestoneEditError):
            L.activate_lodestone(w, {"id": OTHER, "location": [0, 0, 0], "name": "x"})
        self.assertEqual(w.to_bytes(), before)
        self.assertEqual(w.edits, 0)

    def test_refuses_catalog_id_owned_by_built_actor(self):
        w = self.world(TEMPLE, built=[UMBRAL])
        with self.assertRaisesRegex(L.LodestoneEditError, "build/demolish"):
            L.activate_lodestone(w, UMBRAL)

    def test_failed_validation_rolls_back(self):
        w = self.world(TEMPLE, DEATH)
        before = w.to_bytes()
        with mock.patch.object(FakeWorld, "corrupt", True):
            with self.assertRaises(FormatError):
                L.activate_lodestone(w, UMBRAL)
            with self.assertRaises(FormatError):
                L.deactivate_lodestone(w, DEATH)
        self.assertEqual(w.to_bytes(), before)

    def test_no_registry(self):
        w = self.world(TEMPLE)
        w.objs = []
        with self.assertRaises(L.LodestoneEditError):
            L.activate_lodestone(w, UMBRAL)


# ---- real world (opt-in) ------------------------------------------------------------------

def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@unittest.skipUnless(TEST_WORLD, "set DW_TEST_WORLD to a world .sav with lodestones")
class RealWorld(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.copy = os.path.join(self._tmp.name, "world.sav")
        shutil.copyfile(TEST_WORLD, self.copy)
        self.src_hash = _sha(TEST_WORLD)
        for name, kw in (("game_is_running", {"return_value": False}),
                         ("snapshot_game_saves", {"return_value": "SNAPSHOT"})):
            p = mock.patch.object(dw_save, name, **kw)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.assertEqual(_sha(TEST_WORLD), self.src_hash, "source changed!")

    def test_list(self):
        before = H.read_bytes(self.copy)
        w = L.WorldFile(self.copy)
        entries = L.registry_entries(w)
        rows = L.list_lodestones(w)
        self.assertEqual(sum(1 for r in rows if r["registered"]), len(entries))
        cat_ids = {c["id"] for c in L.load_catalog()["lodestones"]}
        self.assertTrue(cat_ids <= {r["id"] for r in rows}, "every catalogued lodestone is listed")
        for r in rows:
            if r["kind"] == "built" and r["registered"]:
                self.assertIsNotNone(r["actor"])
        # world lodestones in the registry sit within 1 uu of the catalog location
        # (bit-exact for the ones seen in saves)
        for e in entries:
            if e["id"] in CATLOC:
                for a, b in zip(e["location"], CATLOC[e["id"]]):
                    self.assertLess(abs(a - b), 1.0)
        # every entry has exactly the layout the synthetic builder produces
        raw = L.registry_object(w).prop("Lodestones").raw
        for e in entries:
            s, t = e["span"]
            self.assertEqual(_entry(e["id"], *e["location"]), raw[s:t], e["id"])
            self.assertEqual(L.encode_entry(e["id"], e["location"]), raw[s:t], e["id"])
            if e["id"] in CATLOC:
                self.assertEqual(L.encode_entry(e["id"], CATLOC[e["id"]]), raw[s:t], "catalog doubles")
        self.assertEqual(w.to_bytes(), before)                 # parse round-trips
        self.assertEqual(H.read_bytes(self.copy), before)  # nothing written

    def test_dowdun_toggle_is_byte_identical(self):
        before = H.read_bytes(self.copy)
        w = L.WorldFile(self.copy)
        if DOWDUN in [e["id"] for e in L.registry_entries(w)]:
            self.assertTrue(L.deactivate_lodestone(w, DOWDUN))
            self.assertNotIn(DOWDUN, [e["id"] for e in L.registry_entries(w)])
            self.assertTrue(L.activate_lodestone(w, DOWDUN))
        else:
            self.assertTrue(L.activate_lodestone(w, DOWDUN))
            self.assertTrue(L.deactivate_lodestone(w, DOWDUN))
        self.assertEqual(w.to_bytes(), before)
        w.save()                                         # through spud's save path (mocked snapshot)
        self.assertEqual(H.read_bytes(self.copy), before)

    def test_dowdun_removed_saved_then_readded_matches_original_entry(self):
        w = L.WorldFile(self.copy)
        orig = {e["id"]: e for e in L.registry_entries(w)}
        if DOWDUN not in orig:
            self.skipTest("Dowdun Reach Entrance not active in this world")
        raw0 = L.registry_object(w).prop("Lodestones").raw
        s, t = orig[DOWDUN]["span"]
        L.deactivate_lodestone(w, DOWDUN)
        w.save()
        w2 = L.WorldFile(self.copy)
        self.assertEqual(len(L.registry_entries(w2)), len(orig) - 1)
        L.activate_lodestone(w2, DOWDUN)
        w2.save()
        w3 = L.WorldFile(self.copy)
        ents = L.registry_entries(w3)
        self.assertEqual(ents[-1]["id"], DOWDUN)                    # appended at the end
        raw3 = L.registry_object(w3).prop("Lodestones").raw
        self.assertEqual(raw3[ents[-1]["span"][0]:ents[-1]["span"][1]], raw0[s:t])  # same bytes
        self.assertEqual(sorted(e["id"] for e in ents), sorted(orig))

    def test_activate_umbral_sands(self):
        w = L.WorldFile(self.copy)
        n = len(L.registry_entries(w))
        if any(e["id"] == UMBRAL for e in L.registry_entries(w)):
            self.skipTest("Umbral Sands already active in this world")
        objs = w.object_count()
        self.assertTrue(L.activate_lodestone(w, UMBRAL))
        w.save()
        w2 = L.WorldFile(self.copy)
        ents = L.registry_entries(w2)
        self.assertEqual(len(ents), n + 1)
        if n == 26:
            self.assertEqual(len(ents), 27)
        self.assertEqual(ents[-1]["id"], UMBRAL)
        self.assertEqual(w2.object_count(), objs)
        rows = {r["id"]: r for r in L.list_lodestones(w2)}
        self.assertTrue(rows[UMBRAL]["registered"])
        self.assertEqual(rows[UMBRAL]["issues"], [])
        # only the registry object's bytes changed
        a = {o.key: bytes(o.chunk.to_bytes()) for o in L.WorldFile(TEST_WORLD).all_objects()}
        b = {o.key: bytes(o.chunk.to_bytes()) for o in w2.all_objects()}
        self.assertEqual([k for k in a if a[k] != b[k]], [L.registry_object(w2).key])

    def test_refuses_built_in_real_world(self):
        w = L.WorldFile(self.copy)
        built = [r for r in L.list_lodestones(w) if r["kind"] == "built"]
        if not built:
            self.skipTest("no built lodestones in this world")
        with self.assertRaises(L.LodestoneEditError):
            L.deactivate_lodestone(w, built[0]["id"])
        self.assertFalse(w.dirty)


# ---- GUI smoke (temp copies only) ---------------------------------------------------------

GUI_SRC = TEST_WORLD


@unittest.skipUnless(GUI_SRC, "set DW_TEST_WORLD to a world .sav with lodestones")
class GuiSmoke(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
        except Exception as e:
            self.skipTest("no Tk: %s" % e)
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = self._tmp.name
        game_dir = os.path.normcase(os.path.join(H.REAL_LOCALAPPDATA or "?", "RSDragonwilds"))
        assert not os.path.normcase(d).startswith(game_dir)
        self.worlds, self.spud = os.path.join(d, "SaveGames"), os.path.join(d, "SpudCache")
        os.makedirs(self.worlds)
        os.makedirs(self.spud)
        with open(os.path.join(self.spud, "L_World.lvl"), "wb") as f:
            f.write(b"x")
        self.world = os.path.join(self.worlds, "world.sav")
        shutil.copyfile(GUI_SRC, self.world)
        self.src_hash = _sha(GUI_SRC)
        self.char = os.path.join(d, H.SAVE_NAME)
        shutil.copyfile(H.SAMPLE_SAVE, self.char)
        self.asked, self.info = [], []
        from dragonwilds_save_editor.gui import world_tab as WT
        self.WT = WT
        patches = [
            mock.patch.object(dw_spud, "WORLD_SAVE_DIR", self.worlds),
            mock.patch.object(WT, "SPUD_CACHE_DIR", self.spud),
            mock.patch.object(dw_save, "game_is_running", return_value=False),
            mock.patch.object(dw_save, "snapshot_game_saves", return_value="SNAPSHOT"),
            mock.patch.object(WT.messagebox, "askyesno", side_effect=self._ask),
            mock.patch.object(WT.messagebox, "showinfo", side_effect=lambda t, m, **k: self.info.append(m)),
            mock.patch.object(WT.messagebox, "showerror", side_effect=lambda t, m, **k: self.info.append(m)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.answer = True

    def _ask(self, title, msg, **kw):
        self.asked.append((msg, kw))
        return self.answer

    def tearDown(self):
        self.assertEqual(_sha(GUI_SRC), self.src_hash, "source changed!")

    def test_buttons(self):
        from dragonwilds_save_editor.gui.app import App
        app = App(self.root)
        app.ctx.load(self.char)
        # The World tab edits the app's focused world (toolbar World row), not its own copy.
        from dragonwilds_save_editor.gui.context import find_default_world
        self.assertEqual(os.path.normcase(find_default_world()), os.path.normcase(self.world))
        self.assertTrue(app.open_world_path(find_default_world()))
        tab = app.tabs["World"]
        self.assertTrue(tab.uses_ctx_world)
        self.assertIs(tab.world, app.ctx.world)
        self.assertEqual(os.path.normcase(tab.world.path), os.path.normcase(self.world))
        tree = tab.lode_tree
        rows = tab._lode_rows
        fixed = [iid for iid in tree.get_children() if rows[iid]["editable"]]
        self.assertEqual([rows[i]["id"] for i in fixed], [TEMPLE, DEATH, DOWDUN, UMBRAL])
        for iid in tree.get_children():
            if rows[iid]["kind"] == "built":
                self.assertIn("readonly", tree.item(iid, "tags"))
                self.assertEqual(tree.item(iid, "values")[4], "build/demolish in game")
                tree.selection_set(iid)
                tree.event_generate("<<TreeviewSelect>>")
                tab._update_buttons()
                self.assertTrue(tab.btn_lode_on.instate(["disabled"]))
                self.assertTrue(tab.btn_lode_off.instate(["disabled"]))
                break
        n0 = len(L.registry_entries(tab.world))
        umbral_active = rows["L" + UMBRAL]["registered"]

        # Activate Umbral Sands: decline first (nothing changes), then accept.
        tree.selection_set("L" + UMBRAL)
        tab._update_buttons()
        if umbral_active:
            self.skipTest("Umbral Sands already active in this world")
        self.assertTrue(tab.btn_lode_on.instate(["!disabled"]))
        self.assertTrue(tab.btn_lode_off.instate(["disabled"]))
        self.answer = False
        tab.btn_lode_on.invoke()
        self.assertFalse(tab.world.dirty)
        msg, kw = self.asked[-1]
        self.assertEqual(kw.get("default"), self.WT.messagebox.NO)
        for s in ("EXPERIMENTAL", "QUEST GATE", "Umbral Sands", "CLOSED", "SpudCache", "pre-world-edit"):
            self.assertIn(s, msg)
        self.answer = True
        tab.btn_lode_on.invoke()
        self.assertTrue(tab.world.dirty)
        self.assertTrue(app.ctx.world_dirty)            # the toolbar sees the tab's edit
        self.assertIn("Unsaved world changes", app.world_dirty_var.get())
        self.assertEqual(tree.item("L" + UMBRAL, "values")[3], "yes")

        # Remove Dowdun Reach Entrance (if active): confirm text mentions the undo risk.
        if rows["L" + DOWDUN]["registered"]:
            tree.selection_set("L" + DOWDUN)
            tab._update_buttons()
            tab.btn_lode_off.invoke()
            msg, kw = self.asked[-1]
            self.assertIn("undo itself", msg)
            self.assertEqual(kw.get("default"), self.WT.messagebox.NO)
            self.assertEqual(tree.item("L" + DOWDUN, "values")[3], "no")
            expected = n0          # +Umbral -Dowdun
        else:
            expected = n0 + 1

        # Save through the existing world save path (snapshot mocked, game "closed").
        tab.btn_save.invoke()
        self.assertIn("Write these EXPERIMENTAL edits", self.asked[-1][0])
        dw_save.snapshot_game_saves.assert_called_once_with("pre-world-edit")
        w2 = dw_spud.WorldFile(self.world)
        ents = [e["id"] for e in L.registry_entries(w2)]
        self.assertEqual(len(ents), expected)
        self.assertIn(UMBRAL, ents)
        self.assertEqual(glob.glob(os.path.join(self.worlds, "*.pyedit.bak")).__len__(), 1)
        self.assertFalse(app.ctx.world_dirty)           # ctx.world was reloaded from the saved file
        self.assertEqual(app.ctx.world.original, H.read_bytes(self.world))
        self.assertIs(tab.world, app.ctx.world)
        self.assertFalse(app.ctx.dirty)     # the character save was never touched
        self.assertEqual(H.read_bytes(self.char), H.read_bytes(H.SAMPLE_SAVE))


if __name__ == "__main__":
    unittest.main()
