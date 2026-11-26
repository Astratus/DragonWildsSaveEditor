"""Tests for dragonwilds_save_editor/gui/context.py (AppContext) using a hidden Tk root."""

import contextlib
import io
import os
import unittest
from unittest import mock

try:
    from . import _helpers as H
except ImportError:
    import _helpers as H

dw_save = H.dw_save

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None

from dragonwilds_save_editor.gui.context import AppContext  # noqa: E402


@unittest.skipIf(tk is None, "tkinter not available")
class AppContextTests(H.TempSaveCase):
    def setUp(self):
        super().setUp()
        try:
            self.tk = tk.Tk()
        except tk.TclError as e:
            self.skipTest("no display: %s" % e)
        self.tk.withdraw()
        self.ctx = AppContext(self.tk)
        self.ctx.game = self.game
        self.messages = []
        self.ctx._status = self.messages.append
        self.changes = 0

        def bump():
            self.changes += 1
        self.ctx.on_change(bump)

    def tearDown(self):
        self.tk.destroy()

    def test_load(self):
        self.assertIsNone(self.ctx.path)
        self.ctx.load(self.path)
        self.assertEqual(self.ctx.path, self.path)
        self.assertIsInstance(self.ctx.save, dw_save.SaveFile)
        self.assertFalse(self.ctx.dirty)
        self.assertEqual(self.changes, 1)
        self.assertEqual(self.ctx.save.to_bytes(), self.orig_bytes)

    def test_write_without_save_raises(self):
        with self.assertRaises(RuntimeError):
            self.ctx.write()
        with self.assertRaises(RuntimeError):
            self.ctx.restore_backup(H.SAMPLE_V83)

    def test_mark_dirty(self):
        self.ctx.load(self.path)
        self.ctx.mark_dirty("Fishing set")
        self.assertTrue(self.ctx.dirty)
        self.assertEqual(self.changes, 2)
        self.assertIn("unsaved", self.messages[-1])
        self.assertIn("Fishing set", self.messages[-1])

    def test_write(self):
        self.ctx.load(self.path)
        self.ctx.save.set_skill("Fishing", level=30)
        old_obj = self.ctx.save
        self.ctx.mark_dirty()

        with contextlib.redirect_stdout(io.StringIO()):
            backup = self.ctx.write()
        self.assertTrue(os.path.isfile(backup))
        self.assertEqual(H.read_bytes(backup), self.orig_bytes)
        self.assertFalse(self.ctx.dirty)
        self.assertIsNot(self.ctx.save, old_obj, "write() should reload from disk")
        self.assertEqual(self.ctx.save.original_text.encode("utf-8"), H.read_bytes(self.path))
        self.assertIn(("Fishing", 5367, 30), self.ctx.save.skills())

    def test_write_refuses_when_game_running(self):
        self.ctx.load(self.path)
        self.ctx.save.set_skill("Fishing", level=30)
        self.ctx.mark_dirty()
        with mock.patch.object(dw_save, "game_is_running", return_value=True):
            with self.assertRaises(RuntimeError):
                self.ctx.write()
            with self.assertRaises(RuntimeError):
                self.ctx.restore_backup(H.SAMPLE_V83)
        self.assertTrue(self.ctx.dirty)
        self.assertEqual(H.read_bytes(self.path), self.orig_bytes)
        self.assertEqual(self.backups(), [])

    def test_restore_backup(self):
        # Make a different "backup" file to restore from.
        src = os.path.join(self.dir, "other.json")
        s = self.open()
        s.set_skill("Fishing", level=50)
        with open(src, "wb") as f:
            f.write(s.to_bytes())
        src_bytes = H.read_bytes(src)

        self.ctx.load(self.path)
        safety = self.ctx.restore_backup(src)
        self.assertTrue(os.path.isfile(safety))
        self.assertEqual(H.read_bytes(safety), self.orig_bytes)
        self.assertEqual(H.read_bytes(self.path), src_bytes)
        self.assertEqual(H.read_bytes(src), src_bytes)
        self.assertFalse(self.ctx.dirty)
        self.assertEqual(self.ctx.save.to_bytes(), src_bytes)
        self.assertIn(("Fishing", self.game.xp_for(50), 50), self.ctx.save.skills())

    def test_restore_backup_rejects_invalid_json(self):
        bad = os.path.join(self.dir, "broken.json")
        with open(bad, "wb") as f:
            f.write(b'{"Version": 86, "GameProgress": {')
        self.ctx.load(self.path)
        with self.assertRaises(ValueError):
            self.ctx.restore_backup(bad)
        self.assertEqual(H.read_bytes(self.path), self.orig_bytes)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.ctx.save.to_bytes(), self.orig_bytes)

    def test_reload_discards_edits(self):
        self.ctx.load(self.path)
        self.ctx.save.set_skill("Fishing", level=90)
        self.ctx.mark_dirty()
        self.ctx.reload()
        self.assertFalse(self.ctx.dirty)
        self.assertEqual(self.ctx.save.to_bytes(), self.orig_bytes)


if __name__ == "__main__":
    unittest.main()
