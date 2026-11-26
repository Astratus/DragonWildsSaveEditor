"""Tests for the app-level focused world (AppContext world API), the world row in the
toolbar, and world backups on the Backups tab.

Uses two SYNTHETIC world saves (built in memory by tests/test_spud.build_world: "World A"
with two defeated bosses and two progress tags, "World B" with none), written to a temp
folder, so these tests always run and need no real save. spud.WORLD_SAVE_DIR,
save.snapshot_root, game_is_running and snapshot_game_saves are patched, so nothing is
written outside the temp dir.
"""

import glob
import hashlib
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

try:
    from . import _helpers as H
except ImportError:  # discovered as a top-level module
    import _helpers as H

from dragonwilds_save_editor import spud as dw_spud  # noqa: E402

try:
    from .test_spud import build_world
except ImportError:  # discovered as a top-level module
    from test_spud import build_world

dw_save = H.dw_save

try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:  # pragma: no cover
    tk = None

from dragonwilds_save_editor.gui import backups_tab as BT  # noqa: E402
from dragonwilds_save_editor.gui import context as C  # noqa: E402

BIG, SMALL = "World A.sav", "World B.sav"
WORLD_BYTES = {
    BIG: build_world(name="World A"),                          # bosses velgar + imaru, two tags
    SMALL: build_world(bosses=(), tags=(), hooks=(), name="World B"),
}
_GAME_DIR = os.path.normcase(os.path.abspath(os.path.join(H.REAL_LOCALAPPDATA or "?", "RSDragonwilds")))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class _TempWorlds(unittest.TestCase):
    """Temp layout:  <tmp>/SaveGames/{BIG,SMALL}  <tmp>/snapshots/  <tmp>/elsewhere/"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        assert not os.path.normcase(os.path.abspath(self.dir)).startswith(_GAME_DIR)
        self.worlds = os.path.join(self.dir, "SaveGames")
        self.snaps = os.path.join(self.dir, "snapshots")
        self.other = os.path.join(self.dir, "elsewhere")
        for d in (self.worlds, self.snaps, self.other):
            os.makedirs(d)
        self.snapshot_calls = []
        patches = [
            mock.patch.object(dw_spud, "WORLD_SAVE_DIR", self.worlds),
            mock.patch.object(dw_save, "snapshot_root", return_value=self.snaps),
            mock.patch.object(dw_save, "game_is_running", return_value=False),
            mock.patch.object(dw_save, "snapshot_game_saves",
                              side_effect=lambda label="full", **k: self.snapshot_calls.append(label) or "SNAP"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def copy(self, name, folder=None, as_name=None):
        dst = os.path.join(folder or self.worlds, as_name or name)
        with open(dst, "wb") as f:
            f.write(WORLD_BYTES[name])
        return dst

    def pyedit_baks(self, path):
        return sorted(glob.glob(glob.escape(path) + ".*.pyedit.bak"))


# ---------------------------------------------------------------------------
# Listing helpers (no Tk)
# ---------------------------------------------------------------------------

class WorldListingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def touch(self, *parts, data=b"x", mtime=None):
        p = os.path.join(self.dir, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        if mtime:
            os.utime(p, (mtime, mtime))
        return p

    def test_list_worlds_newest_first_only_sav(self):
        now = time.time()
        a = self.touch("w", "A.sav", mtime=now - 100)
        b = self.touch("w", "B.sav", mtime=now)
        self.touch("w", "A.sav.backup")
        self.touch("w", "A.sav.20261125-160929.pyedit.bak")
        self.touch("w", "notes.txt")
        folder = os.path.join(self.dir, "w")
        self.assertEqual(C.list_worlds(folder), [b, a])
        self.assertEqual(C.find_default_world([os.path.join(self.dir, "missing"), folder]), b)
        self.assertIsNone(C.find_default_world([os.path.join(self.dir, "missing")]))
        self.assertEqual(C.list_worlds(os.path.join(self.dir, "missing")), [])

    def test_is_live_world(self):
        folder = os.path.join(self.dir, "SaveGames")
        self.assertTrue(C.is_live_world(os.path.join(folder, "X.sav"), folder))
        self.assertFalse(C.is_live_world(os.path.join(self.dir, "X.sav"), folder))
        self.assertFalse(C.is_live_world(None, folder))

    def test_display_name_falls_back_to_file_name(self):
        p = self.touch("w", "Garbage World.sav", data=b"not a world")
        self.assertEqual(C.world_display_name(p), "Garbage World")

    def test_find_world_backups(self):
        world = self.touch("SaveGames", "My World.sav", data=b"current")
        ed1 = self.touch("SaveGames", "My World.sav.20261125-160929.pyedit.bak", data=b"e1")
        ed2 = self.touch("SaveGames", "My World.sav.20261125-160929-2.pyedit.bak", data=b"e2")
        prev = self.touch("SaveGames", "My World.sav.backup", data=b"prev", mtime=1000000000)
        self.touch("SaveGames", "Other.sav.20261125-160929.pyedit.bak")
        self.touch("SaveGames", "My World.sav.tmp")
        snaps = os.path.join(self.dir, "backups")
        s_full = self.touch("backups", "full_20261124-204942", "SaveGames", "My World.sav", data=b"current")
        s_pq = self.touch("backups", "pre-quest_20261124-235401", "SaveGames", "My World.sav")
        s_pw = self.touch("backups", "pre-world-edit_20261125-160929-2", "SaveGames", "My World.sav")
        self.touch("backups", "pre-quest_20261124-235401", "SaveGames", "My World.sav.backup")
        self.touch("backups", "pre-quest_20261124-235401", "SaveCharacters", "My World.sav")
        self.touch("backups", "not-a-snapshot", "SaveGames", "My World.sav")
        self.touch("backups", "pre-quest_20261125-000000", "SaveGames", "Other.sav")

        rows = BT.find_world_backups(world, snaps)
        got = [(os.path.normcase(p), k) for p, k, _, _ in rows]
        want = [
            (ed2, BT.KIND_EDITOR), (s_pw, "Snapshot: pre-world-edit"), (ed1, BT.KIND_EDITOR),
            (s_pq, "Snapshot: pre-quest"), (s_full, "Snapshot: full"),
        ]
        self.assertEqual(got[:5], [(os.path.normcase(p), k) for p, k in want])
        self.assertIn((os.path.normcase(prev), BT.KIND_PREVIOUS), got)
        self.assertEqual(len(got), 6)
        # Character backups listing is unchanged: snapshots are not included there.
        self.assertEqual(len(BT.find_backups(world)), 3)

    def test_world_compare(self):
        self.assertEqual(BT.world_compare("a", 10, "a", 10), "identical to the current file")
        self.assertIn("+5 bytes", BT.world_compare("a", 15, "b", 10))
        self.assertEqual(BT.world_compare(None, 1, "b", 1), "unreadable")
        self.assertEqual(BT.world_compare("a", 1, None, 0), "current file missing")


# ---------------------------------------------------------------------------
# AppContext world API
# ---------------------------------------------------------------------------

@unittest.skipIf(tk is None, "tkinter not available")
class ContextWorldTests(_TempWorlds):
    def setUp(self):
        super().setUp()
        try:
            self.tk = tk.Tk()
        except tk.TclError as e:
            self.skipTest("no display: %s" % e)
        self.tk.withdraw()
        self.addCleanup(self.tk.destroy)
        self.ctx = C.AppContext(self.tk)
        self.ctx.game = H.game_data()
        self.events = []
        self.ctx.on_world_change(lambda: self.events.append(self.ctx.world_event))
        self.messages = []
        self.ctx._status = self.messages.append

    def test_defaults_follow_patched_folder(self):
        self.assertEqual(self.ctx.world_folder, self.worlds)
        self.assertIsNone(self.ctx.world)
        self.assertFalse(self.ctx.world_dirty)
        self.assertIsNone(self.ctx.world_name())
        small = self.copy(SMALL)
        big = self.copy(BIG)
        os.utime(small, (time.time() - 50, time.time() - 50))
        self.assertEqual(C.find_default_world(), big)
        self.assertEqual(self.ctx.list_worlds(), [big, small])

    def test_load_world_and_listeners(self):
        small = self.copy(SMALL)
        self.ctx.load_world(small)
        self.assertEqual(self.ctx.world_path, small)
        self.assertIsInstance(self.ctx.world, dw_spud.WorldFile)
        self.assertEqual(self.events, ["load"])
        self.assertTrue(self.ctx.world_is_live)
        self.assertEqual(self.ctx.world_name(), "World B")
        self.assertFalse(self.ctx.world_dirty)
        self.ctx.reload_world()
        self.assertEqual(self.events, ["load", "reload"])
        # A copy outside SaveGames is not live, and is added to the switch list.
        out = self.copy(SMALL, self.other)
        self.ctx.load_world(out)
        self.assertFalse(self.ctx.world_is_live)
        self.assertEqual(self.ctx.list_worlds()[0], out)
        self.ctx.close_world()
        self.assertIsNone(self.ctx.world)
        self.assertEqual(self.events[-1], "close")

    def test_load_invalid_keeps_old_world(self):
        small = self.copy(SMALL)
        bad = os.path.join(self.worlds, "bad.sav")
        with open(bad, "wb") as f:
            f.write(b"definitely not a world")
        self.ctx.load_world(small)
        with self.assertRaises(Exception):
            self.ctx.load_world(bad)
        self.assertEqual(self.ctx.world_path, small)
        self.assertEqual(self.events, ["load"])

    def test_write_world(self):
        big = self.copy(BIG)
        orig = _sha(big)
        self.ctx.load_world(big)
        with self.assertRaises(RuntimeError):
            self.ctx.write_world()        # nothing to save yet
        old = self.ctx.world
        old.remove_defeated_boss("ai_boss_imaru")
        self.ctx.mark_world_dirty("removed Imaru")
        self.assertEqual(self.events[-1], "edit")
        self.assertTrue(self.ctx.world_dirty)
        self.assertIn("unsaved world changes", self.messages[-1])
        result = self.ctx.write_world()
        self.assertEqual(self.snapshot_calls, ["pre-world-edit"])
        self.assertEqual(_sha(result["backup"]), orig)
        self.assertEqual(self.pyedit_baks(big), [result["backup"]])
        self.assertNotEqual(_sha(big), orig)
        self.assertIsNot(self.ctx.world, old)
        self.assertFalse(self.ctx.world_dirty)
        self.assertEqual(self.events[-1], "save")
        self.assertNotIn("ai_boss_imaru", self.ctx.world.defeated_bosses())

    def test_write_world_refuses_while_game_runs(self):
        big = self.copy(BIG)
        orig = _sha(big)
        self.ctx.load_world(big)
        self.ctx.world.remove_defeated_boss("ai_boss_imaru")
        with mock.patch.object(dw_save, "game_is_running", return_value=True):
            with self.assertRaises(RuntimeError):
                self.ctx.write_world()
        self.assertEqual(_sha(big), orig)
        self.assertEqual(self.pyedit_baks(big), [])
        self.assertEqual(self.snapshot_calls, [])
        self.assertTrue(self.ctx.world_dirty)

    def test_restore_world_backup(self):
        big = self.copy(BIG)
        orig = _sha(big)
        src = self.copy(SMALL, self.other)      # any valid world save works as the "backup"
        src_hash = _sha(src)
        self.ctx.load_world(big)
        self.ctx.world.remove_defeated_boss("ai_boss_imaru")   # unsaved edit gets discarded
        safety = self.ctx.restore_world_backup(src)
        self.assertEqual(_sha(safety), orig)
        self.assertEqual(self.pyedit_baks(big), [safety])
        self.assertEqual(_sha(big), src_hash)
        self.assertEqual(_sha(src), src_hash)
        self.assertFalse(self.ctx.world_dirty)
        self.assertEqual(self.events[-1], "restore")
        self.assertEqual(self.ctx.world.original, H.read_bytes(src))
        self.assertEqual([n for n in os.listdir(self.worlds) if n.endswith(".tmp")], [])

    def test_restore_world_backup_refusals(self):
        big = self.copy(BIG)
        orig = _sha(big)
        bad = os.path.join(self.other, "bad.sav")
        with open(bad, "wb") as f:
            f.write(b"not a world save")
        good = self.copy(SMALL, self.other)
        with self.assertRaises(RuntimeError):
            self.ctx.restore_world_backup(good)            # no world focused
        self.ctx.load_world(big)
        with self.assertRaises(ValueError):
            self.ctx.restore_world_backup(bad)
        with self.assertRaises(RuntimeError):
            self.ctx.restore_world_backup(big)             # itself
        with mock.patch.object(dw_save, "game_is_running", return_value=True):
            with self.assertRaises(RuntimeError):
                self.ctx.restore_world_backup(good)
        self.assertEqual(_sha(big), orig)
        self.assertEqual(self.pyedit_baks(big), [])


# ---------------------------------------------------------------------------
# GUI: Backups tab world mode and the App's world row (hidden root, temp copies)
# ---------------------------------------------------------------------------

@unittest.skipIf(tk is None, "tkinter not available")
class WorldGuiTests(_TempWorlds):
    def setUp(self):
        super().setUp()
        try:
            self.tk = tk.Tk()
        except tk.TclError as e:
            self.skipTest("no display: %s" % e)
        self.tk.withdraw()
        self.addCleanup(self._destroy)
        self.asked, self.shown = [], []
        self.answer = True
        for name in ("showinfo", "showerror", "showwarning"):
            p = mock.patch.object(messagebox, name, side_effect=lambda t, m, **k: self.shown.append(m))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(messagebox, "askyesno", side_effect=self._ask)
        p.start()
        self.addCleanup(p.stop)
        self.char = os.path.join(self.dir, H.SAVE_NAME)
        shutil.copyfile(H.SAMPLE_SAVE, self.char)

    def _destroy(self):
        try:
            self.tk.destroy()
        except tk.TclError:
            pass

    def _ask(self, title, msg, **kw):
        self.asked.append((msg, kw))
        return self.answer

    def make_snapshot(self, label, stamp, name, src_name):
        d = os.path.join(self.snaps, "%s_%s" % (label, stamp), "SaveGames")
        os.makedirs(d, exist_ok=True)
        return self.copy(src_name, d, as_name=name)

    def test_backups_tab_world_mode(self):
        big = self.copy(BIG)
        snap_same = self.make_snapshot("full", "20261124-204942", BIG, BIG)
        snap_other = self.make_snapshot("pre-quest", "20261124-235401", BIG, SMALL)
        ctx = C.AppContext(self.tk)
        ctx.game = H.game_data()
        ctx.load(self.char)
        tab = BT.BackupsTab(self.tk, ctx)
        self.assertEqual(tab.mode, BT.MODE_CHARACTER)
        self.assertEqual(tab.tree.get_children(), ())   # temp char save has no backups yet

        tab.set_mode(BT.MODE_WORLD)
        self.assertEqual(tab.tree.get_children(), ())
        self.assertIn("No world", tab.retention_var.get())
        ctx.load_world(big)                               # listener refreshes the list
        rows = {tab._rows[i][0]: tab.tree.item(i, "values") for i in tab.tree.get_children()}
        self.assertEqual(set(rows), {snap_same, snap_other})
        self.assertEqual(rows[snap_same][4], "yes")
        self.assertEqual(rows[snap_other][4], "no")
        self.assertIn("pre-quest_20261124-235401", rows[snap_other][0])

        # Back up now -> editor backup of the world appears.
        bak = tab.backup_now()
        self.assertEqual(self.pyedit_baks(big), [bak])
        self.assertEqual(len(tab.tree.get_children()), 3)

        # Snapshots can't be deleted.
        iid = next(i for i in tab.tree.get_children() if tab._rows[i][0] == snap_other)
        tab.tree.selection_set(iid)
        tab._update_buttons()
        self.assertTrue(tab.btn_delete.instate(["disabled"]))
        self.assertIsNone(tab.delete_selected())
        self.assertTrue(os.path.isfile(snap_other))

        # Restore: declined -> nothing changes; default button is No.
        orig = _sha(big)
        self.answer = False
        self.assertIsNone(tab.restore_selected())
        self.assertEqual(self.asked[-1][1].get("default"), "no")
        self.assertEqual(_sha(big), orig)
        # Refused while the game runs (no prompt to force).
        self.answer = True
        n_asked = len(self.asked)
        with mock.patch.object(dw_save, "game_is_running", return_value=True):
            self.assertIsNone(tab.restore_selected())
        self.assertEqual(len(self.asked), n_asked)
        self.assertEqual(_sha(big), orig)
        # Accepted -> restored, current file backed up first.
        iid = next(i for i in tab.tree.get_children() if tab._rows[i][0] == snap_other)
        tab.tree.selection_set(iid)
        safety = tab.restore_selected()
        self.assertEqual(_sha(safety), orig)
        self.assertEqual(_sha(big), _sha(snap_other))
        self.assertEqual(ctx.world.original, H.read_bytes(snap_other))

        # Delete the editor backup made by "Back up now".
        iid = next(i for i in tab.tree.get_children() if tab._rows[i][0] == bak)
        tab.tree.selection_set(iid)
        self.assertEqual(tab.delete_selected(), [bak])
        self.assertFalse(os.path.exists(bak))

        # Character mode still lists character backups.
        tab.set_mode(BT.MODE_CHARACTER)
        cbak = tab.backup_now()
        self.assertTrue(cbak.endswith(".pyedit.bak") and cbak.startswith(self.char))
        self.assertEqual([tab._rows[i][0] for i in tab.tree.get_children()], [cbak])
        self.assertEqual(tab.tree.heading("savecount", "text"), "SaveCount")

    def test_app_world_row(self):
        from dragonwilds_save_editor.gui.app import App
        big = self.copy(BIG)
        small = self.copy(SMALL)
        os.utime(small, (time.time() - 50, time.time() - 50))
        app = App(self.tk)
        app.open_path(self.char)
        self.assertTrue(app.open_world_path(C.find_default_world()))
        self.assertEqual(app.ctx.world_path, big)
        self.assertIn("live game save", app.world_var.get())
        labels = list(app.world_combo["values"])
        self.assertEqual(labels, ["World A", "World B"])
        self.assertEqual(app.world_choice_var.get(), "World A")

        wt = app.tabs["World"]
        self.assertTrue(wt.uses_ctx_world)
        self.assertIs(wt.world, app.ctx.world)
        self.assertIn("World A", wt.state_var.get())

        # Switch via the combobox.
        app.world_choice_var.set("World B")
        self.assertTrue(app.on_world_selected())
        self.assertEqual(app.ctx.world_path, small)
        self.assertIs(wt.world, app.ctx.world)
        self.assertIn("World B", wt.state_var.get())

        # A world copy outside SaveGames is labelled as such and joins the list.
        out = self.copy(SMALL, self.other, as_name="Copy.sav")
        self.assertTrue(app.on_open_world(out))
        self.assertIn("copy outside the game folder", app.world_var.get())
        self.assertIn("World B  (Copy.sav)", app.world_combo["values"])

        # Unsaved ctx edit: switching asks (declined -> stays), exit asks (declined -> stays).
        app.open_world_path(big)
        app.ctx.world.remove_defeated_boss("ai_boss_imaru")
        app.ctx.mark_world_dirty("removed Imaru")
        self.assertIn("Unsaved world changes (1)", app.world_dirty_var.get())
        self.assertTrue(self.tk.title().startswith("*"))
        self.answer = False
        app.world_choice_var.set("World B")
        self.assertFalse(app.on_world_selected())
        self.assertEqual(app.ctx.world_path, big)
        self.assertEqual(app.world_choice_var.get(), "World A")
        self.assertEqual(self.asked[-1][1].get("default"), "no")
        self.assertFalse(app.on_revert_world())
        app.on_exit()
        self.assertTrue(self.tk.winfo_exists())

        # Save world through the toolbar: snapshot + per-file backup, file replaced.
        orig = _sha(big)
        self.answer = True
        result = app.on_save_world()
        self.assertEqual(self.snapshot_calls, ["pre-world-edit"])
        self.assertEqual(_sha(result["backup"]), orig)
        self.assertNotEqual(_sha(big), orig)
        self.assertFalse(app.ctx.world_dirty)
        self.assertEqual(app.world_dirty_var.get(), "")
        self.assertIs(wt.world, app.ctx.world)
        self.assertNotIn("ai_boss_imaru", [wt.boss_list.get(i) for i in range(wt.boss_list.size())])

        # Edits made in the World tab go to ctx.world; the toolbar sees them; Revert drops them.
        tag = sorted(wt.world.progress_tags())[0]
        cur = {e["tag"]: e["int"] for e in wt.world.tagged_values()}[tag]
        self.answer = True
        wt.set_tag(tag, 0 if cur else 1)
        self.assertTrue(app.ctx.world_dirty)
        self.assertIn("Unsaved world changes (1)", app.world_dirty_var.get())
        self.assertIn("UNSAVED WORLD EDITS", wt.state_var.get())
        self.assertTrue(wt.btn_save.instate(["!disabled"]))
        self.assertTrue(app.on_revert_world())
        self.assertFalse(app.ctx.world_dirty)
        self.assertEqual({e["tag"]: e["int"] for e in wt.world.tagged_values()}[tag], cur)
        self.assertTrue(wt.btn_save.instate(["disabled"]))

        # Exit with nothing unsaved closes the window.
        app.on_exit()
        self.assertFalse(self._exists())

    def _exists(self):
        try:
            return self.tk.winfo_exists()
        except tk.TclError:
            return False


if __name__ == "__main__":
    unittest.main()
