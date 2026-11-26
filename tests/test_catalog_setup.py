"""The item catalog as the app and the CLI use it: the bundled catalog on first run (no
dialog, no network), a user-built catalog taking precedence, Help > Update item catalog (with a
fake build: no network) and Reset to bundled catalog, a damaged install with no catalog at all,
and the skill-perk names on the Unlocks tab. Everything runs against the isolated test
LOCALAPPDATA (see tests/_helpers.py), whose user-built catalog is the small fixture; "no
user-built catalog" points the catalog at an empty temp folder, "no catalog at all" also hides
the bundled one.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

try:
    from . import _helpers as H
except ImportError:  # discovered as a top-level module
    import _helpers as H

from dragonwilds_save_editor import catalog  # noqa: E402

dw_save = H.dw_save

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None

PERK = "cQfN1EsBDwTU16m3eFSDKA"   # Iron Secateurs: a skill perk in the sample save's SpellsNew


def _no_user_catalog(case):
    """Point the user catalog folder at an empty temp folder for the rest of the test."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    catalog.set_user_data_dir(lambda: tmp.name)
    case.addCleanup(catalog.set_user_data_dir, None)
    return tmp.name


def _no_bundled_catalog(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    catalog.set_bundled_dir(lambda: tmp.name)
    case.addCleanup(catalog.set_bundled_dir, None)


class _NoUserCatalog(unittest.TestCase):
    """Fresh install: nothing built on this computer, only the bundled catalog."""

    def setUp(self):
        self.user_dir = _no_user_catalog(self)


class _NoCatalog(_NoUserCatalog):
    """Damaged install: no user-built catalog AND no bundled catalog."""

    def setUp(self):
        super().setUp()
        _no_bundled_catalog(self)


class GameDataBundled(_NoUserCatalog):
    def test_first_run_uses_bundled_catalog(self):
        g = dw_save.GameData()
        self.assertFalse(g.catalog_missing)
        self.assertGreaterEqual(len(g.items), 1600)
        self.assertEqual(g.resolve_item("Nature Rune")["id"], "iKbF7k2XvufGqqyg5rK-vQ")
        info = catalog.active_status()
        self.assertEqual((info["origin"], info["mode"]), ("bundled", "bundled"))
        self.assertFalse(catalog.is_built())


class GameDataWithoutCatalog(_NoCatalog):
    def test_required_by_default(self):
        with self.assertRaises(catalog.CatalogNotBuiltError):
            dw_save.GameData()

    def test_optional_catalog_shows_raw_ids(self):
        g = dw_save.GameData(require_catalog=False)
        self.assertTrue(g.catalog_missing)
        self.assertEqual(g.items, [])
        self.assertEqual(g.item_name("iKbF7k2XvufGqqyg5rK-vQ"), "?unknown?")
        self.assertEqual(len(g.skills), 12)                  # bundled data still loads
        with self.assertRaises(catalog.CatalogNotBuiltError):
            g.resolve_item("Nature Rune")


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = dw_save.main(list(args))
    return rc, out.getvalue(), err.getvalue()


class CliWithoutCatalog(_NoCatalog):
    def test_add_explains_how_to_build(self):
        rc, _, err = run_cli(H.SAMPLE_SAVE, "--dry-run", "add", "Nature Rune")
        self.assertEqual(rc, 2)
        self.assertIn("Reinstall", err)
        self.assertIn("dwsave catalog build", err)
        self.assertIn("python -m dragonwilds_save_editor.catalog build", err)

    def test_read_only_commands_still_work(self):
        rc, out, err = run_cli(H.SAMPLE_SAVE, "selftest")
        self.assertEqual(rc, 0, err)
        self.assertIn("byte-identical", out)
        self.assertIn("catalog", err)

    def test_catalog_subcommand_is_delegated(self):
        rc, out, _ = run_cli("catalog", "status")
        self.assertEqual(rc, 1)
        self.assertIn("No usable catalog", out)


class CliBundledOnly(_NoUserCatalog):
    def test_status_reports_bundled(self):
        rc, out, _ = run_cli("catalog", "status")
        self.assertEqual(rc, 0)
        self.assertIn("In use: bundled catalog", out)
        self.assertIn('"source": "installed game"', out)

    def test_add_works_offline(self):
        rc, out, err = run_cli(H.SAMPLE_SAVE, "--dry-run", "add", "Nature Rune", "--count", "5")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("catalog", err)

    def test_reset_without_user_build(self):
        rc, out, _ = run_cli("catalog", "reset")
        self.assertEqual(rc, 0)
        self.assertIn("already using the bundled catalog", out)

    def test_verify_bundled(self):
        rc, out, err = run_cli("catalog", "verify")
        self.assertEqual(rc, 0, err)
        self.assertIn("OK", out)


class CliWithFixtureCatalog(unittest.TestCase):
    def test_catalog_status(self):
        rc, out, _ = run_cli("catalog", "status")
        self.assertEqual(rc, 0)
        self.assertIn("In use: user catalog", out)
        self.assertIn('"game_version"', out)


@unittest.skipIf(tk is None, "tkinter not available")
class _TkCase(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest("no display: %s" % e)
        self.root.withdraw()
        self.addCleanup(self._destroy)

    def _destroy(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def pump(self, until, limit=200):
        for _ in range(limit):
            self.root.update()
            if until():
                return True
            self.root.after(10)
        return False


class CatalogDialogTests(_TkCase):
    def make(self, build_fn, found=os.path.join("X:", "Games", "Dragonwilds")):
        from dragonwilds_save_editor.gui.catalog_setup import CatalogDialog
        return CatalogDialog(self.root, build_fn=build_fn, detect_fn=lambda: found)

    def test_successful_build_reports_progress(self):
        calls = []

        def fake_build(game_dir=None, progress=None):
            calls.append(game_dir)
            for i in range(3):
                progress("decode", i + 1, 3)
            return {"counts": {"items": 3}}

        dlg = self.make(fake_build)
        text = dlg.text_var.get()
        for want in ("Optional", "installed copy", "only read", "no network connection",
                     "Reset to bundled catalog", "the current catalog is kept"):
            self.assertIn(want, text)
        for gone in ("RSDWArchive", "download", "MB"):
            self.assertNotIn(gone, text)
        self.assertIn("\\DragonwildsSaveEditor\\catalog", text)
        self.assertIn(os.path.join("X:", "Games", "Dragonwilds"), dlg.game_var.get())
        self.assertEqual(str(dlg.start_btn.cget("text")), "Update from game")
        dlg.on_start()
        self.assertTrue(self.pump(lambda: dlg.result))
        self.assertEqual(calls, [os.path.join("X:", "Games", "Dragonwilds")])
        self.assertEqual(dlg.info, {"counts": {"items": 3}})

    def test_not_found_offers_folder_picker(self):
        seen = []
        dlg = self.make(lambda game_dir=None, progress=None: seen.append(game_dir) or {}, found=None)
        self.assertIn("not found", dlg.game_var.get())
        self.assertTrue(dlg.start_btn.instate(["disabled"]))
        dlg.on_start()                       # nothing to build from yet
        self.assertIsNone(dlg._worker)
        with mock.patch("dragonwilds_save_editor.gui.catalog_setup.filedialog.askdirectory",
                        return_value=os.path.join("X:", "DW")):
            dlg.on_pick()
        self.assertTrue(self.pump(lambda: dlg.result))
        self.assertEqual(seen, [os.path.normpath(os.path.join("X:", "DW"))])

    def test_wrong_folder_and_failed_self_check_keep_the_catalog(self):
        def not_game(game_dir=None, progress=None):
            raise catalog.GameNotFoundError("%s is not a RuneScape: Dragonwilds installation folder" % game_dir)

        dlg = self.make(not_game)
        dlg.on_start()
        self.assertTrue(self.pump(lambda: dlg._worker is None))
        self.assertFalse(dlg.result)
        self.assertIn("is not a RuneScape: Dragonwilds installation folder", dlg.text_var.get())
        self.assertTrue(dlg.pick_btn.instate(["!disabled"]))
        self.assertTrue(dlg.start_btn.instate(["disabled"]))     # the folder was not a game

        def bad_check(game_dir=None, progress=None):
            raise catalog.SelfCheckError(["items: only 3 found (expected at least 1500)"])

        dlg2 = self.make(bad_check)
        dlg2.on_start()
        self.assertTrue(self.pump(lambda: dlg2._worker is None))
        self.assertFalse(dlg2.result)
        self.assertIn("current catalog was kept", dlg2.text_var.get())
        self.assertIn("items: only 3 found", dlg2.text_var.get())
        self.assertEqual(str(dlg2.start_btn.cget("text")), "Try again")

    def test_cancel(self):
        dlg = self.make(lambda game_dir=None, progress=None: {})
        dlg.on_cancel()
        self.assertFalse(dlg.result)


def _help_menu(root):
    menubar = root.nametowidget(root.cget("menu"))
    cascades = {menubar.entrycget(i, "label"): menubar.entrycget(i, "menu")
                for i in range(menubar.index("end") + 1) if menubar.type(i) == "cascade"}
    help_menu = root.nametowidget(cascades["Help"])
    items = {help_menu.entrycget(i, "label"): i for i in range(help_menu.index("end") + 1)
             if help_menu.type(i) == "command"}
    return help_menu, items


class AppCatalogTests(_TkCase):
    def test_first_run_uses_bundled_catalog_without_dialog(self):
        from dragonwilds_save_editor.gui import app as A
        _no_user_catalog(self)
        with mock.patch.object(A, "run_catalog_dialog") as dlg:
            a = A.App(self.root)
            self.assertTrue(a.check_catalog())               # the startup check: no dialog
        dlg.assert_not_called()
        self.assertFalse(a.ctx.game.catalog_missing)
        self.assertGreaterEqual(len(a.ctx.game.items), 1600)
        tab = a.tabs["Add Items"]
        self.assertIn("of %d items" % len(a.ctx.game.items), tab.result_label.cget("text"))

    def test_update_then_reset_to_bundled(self):
        from dragonwilds_save_editor.gui import app as A
        from dragonwilds_save_editor.gui.about import catalog_line
        user = _no_user_catalog(self)
        a = A.App(self.root)
        a.ctx.load(H.SAMPLE_SAVE)
        bundled_count = len(a.ctx.game.items)
        self.assertIn("Item catalog: bundled (from game version %s)" % catalog.bundled_status()["game_version"],
                      catalog_line())

        def fake_dialog(parent, **kw):                       # "update": the fixture catalog is built
            shutil.copytree(H.FIXTURE_CATALOG, os.path.join(user, "catalog"))
            return True
        help_menu, items = _help_menu(self.root)
        with mock.patch.object(A, "run_catalog_dialog", side_effect=fake_dialog) as dlg:
            help_menu.invoke(items["Update item catalog..."])
        dlg.assert_called_once()
        self.assertEqual(len(a.ctx.game.items), 92)
        self.assertIs(a.ctx.save.game, a.ctx.game)
        self.assertIn("Item catalog updated: 92 items", a.status_var.get())
        self.assertIn("of 92 items", a.tabs["Add Items"].result_label.cget("text"))
        self.assertIn("Item catalog: updated ", catalog_line())

        with mock.patch.object(A.messagebox, "askyesno", return_value=True):
            help_menu.invoke(items["Reset to bundled catalog"])
        self.assertFalse(catalog.is_built())
        self.assertEqual(len(a.ctx.game.items), bundled_count)
        self.assertIn("Using the bundled item catalog", a.status_var.get())
        # A second reset has nothing to remove.
        with mock.patch.object(A.messagebox, "showinfo") as info:
            self.assertFalse(a.on_reset_catalog())
        info.assert_called_once()

    def test_cancelled_update_changes_nothing(self):
        from dragonwilds_save_editor.gui import app as A
        a = A.App(self.root)
        before = a.ctx.game
        with mock.patch.object(A, "run_catalog_dialog", return_value=False):
            a.on_update_catalog()
        self.assertIs(a.ctx.game, before)

    def test_damaged_install_keeps_raw_ids(self):
        from dragonwilds_save_editor.gui import app as A
        _no_user_catalog(self)
        _no_bundled_catalog(self)
        with mock.patch.object(A, "run_catalog_dialog") as dlg:
            a = A.App(self.root)
            self.assertFalse(a.check_catalog())
        dlg.assert_not_called()
        self.assertTrue(a.ctx.game.catalog_missing)
        self.assertIn("Update item catalog", a.status_var.get())


class UnlocksPerkNames(_TkCase):
    def test_spells_new_perk_is_named_not_listed(self):
        from dragonwilds_save_editor.gui.context import AppContext
        from dragonwilds_save_editor.gui.unlocks_tab import UnlocksTab
        ctx = AppContext(self.root)
        ctx.load(H.SAMPLE_SAVE)
        tab = UnlocksTab(self.root, ctx)
        self.assertEqual(tab.perk_name(PERK), "Iron Secateurs")
        tab.kind_var.set("Spells")
        tab.refresh()
        self.assertIn("Iron Secateurs", tab.note.cget("text"))
        self.assertNotIn(PERK, tab.tree.get_children())      # a perk is never offered as a spell


class AboutBoxTests(_TkCase):
    def test_help_menu_has_about(self):
        from dragonwilds_save_editor.gui import app as A
        a = A.App(self.root)
        help_menu, items = _help_menu(self.root)
        self.assertIn("About Dragonwilds Save Editor...", items)
        self.assertIn("Update item catalog...", items)
        self.assertIn("Reset to bundled catalog", items)
        self.assertNotIn("Rebuild item catalog...", items)
        with mock.patch.object(A, "run_about_dialog") as dlg:
            help_menu.invoke(items["About Dragonwilds Save Editor..."])
        dlg.assert_called_once_with(a.root)

    def test_dialog_shows_notice_version_and_catalog(self):
        from dragonwilds_save_editor import __version__
        from dragonwilds_save_editor.gui.about import AboutDialog
        notice = ("Created using intellectual property belonging to Jagex Limited under the terms "
                  "of Jagex's Fan Content Policy. This content is not endorsed by or affiliated "
                  "with Jagex.")
        dlg = AboutDialog(self.root, info={"format": 1, "game_version": "1.0.2.2", "mode": "bundled",
                                           "counts": {"items": 5}})
        text = dlg.get_text()
        self.assertIn(notice, text)
        self.assertIn(__version__, text)
        self.assertIn("MIT License", text)
        self.assertIn("are trademarks of Jagex Limited", text)
        self.assertIn("from game version 1.0.2.2", text)
        self.assertIn("Works entirely offline: no network connections.", text)
        self.assertNotIn("RSDWArchive", text)
        self.assertTrue(dlg.bind("<Escape>"))                # Escape closes (not deliverable
        dlg.close_btn.invoke()                               # to a window of a hidden root)
        self.assertFalse(dlg.winfo_exists())

    def test_catalog_lines(self):
        from dragonwilds_save_editor.gui.about import catalog_line
        _no_user_catalog(self)
        n = len(catalog.load_catalog("items"))
        self.assertEqual(catalog_line(), "Item catalog: bundled (from game version %s), %d items."
                         % (catalog.bundled_status()["game_version"], n))
        updated = catalog_line({"format": 1, "game_version": "1.0.3.0",
                                "built_at": "2026-12-01T10:00:00", "origin": "user"})
        self.assertEqual(updated, "Item catalog: updated 2026-12-01 (from your installed game, version 1.0.3.0).")
        _no_bundled_catalog(self)
        self.assertIn("none could be loaded", catalog_line())


if __name__ == "__main__":
    unittest.main()
