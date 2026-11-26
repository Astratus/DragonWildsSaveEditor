"""Behavioural tests for world-save edits through dragonwilds_save_editor.spud.

The real-world tests run only when DW_TEST_WORLD names world saves (a .sav, a folder of
them, or several separated by os.pathsep). They work ONLY on temporary copies and check
round trips and edit invariants, not world-specific counts. A test that needs particular
content (a defeated boss, a progress tag, a boss altar, a cached character) skips itself
when no given world has it. spud's hooks (_game_is_running, _snapshot_saves) are patched in
the save tests. The codec and "not a save" tests always run.
"""

import glob
import hashlib
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

try:
    from . import _helpers as H
except ImportError:  # discovered as a top-level module
    import _helpers as H

from dragonwilds_save_editor import spud as dw_spud  # noqa: E402

WORLDS = H.test_worlds()
WPM_PROPS = ("WorldHooksTriggered", "DefeatedBossesInternalNames", "TaggedWorldProgressValues", "bCanBeDamaged")
_GAME_DIR = os.path.normcase(os.path.abspath(os.path.join(H.REAL_LOCALAPPDATA or "?", "RSDragonwilds")))
_FEATURES = {}   # path -> {"pm", "bosses", "tags", "altar", "chars"} (parsed once per run)


def _features(path):
    if path not in _FEATURES:
        w = dw_spud.WorldFile(path)
        pm = w.progress_manager()
        _FEATURES[path] = {
            "pm": pm is not None,
            "bosses": len(w.defeated_bosses()) if pm is not None else 0,
            "tags": len(w.tagged_values()) if pm is not None else 0,
            "altar": len(w.find_objects("bossaltar")),
            "chars": len(w.cached_characters()),
        }
    return _FEATURES[path]


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _object_bytes(w):
    """key -> the object's whole chunk bytes (header, PROP, other children)."""
    return {o.key: bytes(o.chunk.to_bytes()) for o in w.all_objects()}


def _shape(w):
    """Chunk magics in tree order."""
    out, stack = [], [w.root]
    while stack:
        c = stack.pop()
        out.append(c.magic)
        stack.extend(reversed(c.children or ()))
    return out


def _tags(w):
    return {e["tag"]: e["int"] for e in w.tagged_values()}


class CodecTests(unittest.TestCase):
    """No world needed."""

    def test_record_codecs_roundtrip(self):
        z = b"\0\0\0\0"
        self.assertEqual(dw_spud.decode_string_set(dw_spud.encode_string_set(z, ["a", "bb"])), (z, ["a", "bb"]))
        prefix, ents = dw_spud.decode_tag_map(dw_spud.encode_tag_map(z, [("X.Y", b"\1\0\0\0"), ("Z", z)]))
        self.assertEqual(prefix, z)
        self.assertEqual([(e["tag"], e["value"], e["int"]) for e in ents], [("X.Y", b"\1\0\0\0", 1), ("Z", z, 0)])
        with self.assertRaises(dw_spud.FormatError):
            dw_spud.decode_string_set(dw_spud.encode_string_set(z, ["a"]) + b"junk")

    def test_not_a_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.sav")
            with open(p, "wb") as f:
                f.write(b"GVAS0000")
            with self.assertRaises(dw_spud.FormatError):
                dw_spud.WorldFile(p)
        with self.assertRaises(ValueError):          # FormatError is a ValueError
            dw_spud.WorldFile.validate_bytes(b"GVAS0000")


@unittest.skipUnless(WORLDS, "set DW_TEST_WORLD to world .sav file(s) to run real-world tests")
class WorldCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        assert not os.path.normcase(os.path.abspath(self.dir)).startswith(_GAME_DIR)
        self.src_hashes = {}

    def copy(self, src):
        self.src_hashes[src] = _sha(src)
        dst = os.path.join(self.dir, os.path.basename(src))
        shutil.copyfile(src, dst)
        return dst

    def world_with(self, bosses=0, tags=0, altar=0, chars=0):
        """Temp copy of the first given world that has at least this content, else skip."""
        for src in WORLDS:
            f = _features(src)
            if f["pm"] and f["bosses"] >= bosses and f["tags"] >= tags and f["altar"] >= altar \
                    and f["chars"] >= chars:
                return self.copy(src)
        self.skipTest("no DW_TEST_WORLD world with bosses>=%d tags>=%d altar>=%d chars>=%d"
                      % (bosses, tags, altar, chars))

    def tearDown(self):
        for src, h in self.src_hashes.items():
            self.assertEqual(_sha(src), h, "source file was modified: %s" % src)


class RoundTripTests(WorldCase):
    def _check(self, src):
        path = self.copy(src)
        before = H.read_bytes(path)
        w = dw_spud.WorldFile(path)       # parses every object against its class def
        self.assertEqual(w.to_bytes(), before)
        self.assertEqual(w.to_bytes(rebuild=True), before)
        self.assertEqual(H.read_bytes(path), before, "reading must not modify the file")
        return w

    def test_every_world(self):
        for src in WORLDS:
            with self.subTest(world=os.path.basename(src)):
                self.assertGreater(self._check(src).object_count(), 0)

    def test_game_backups(self):
        found = [src + ".backup" for src in WORLDS if os.path.isfile(src + ".backup")]
        if not found:
            self.skipTest("no .backup next to the DW_TEST_WORLD saves")
        for b in found:
            with self.subTest(backup=os.path.basename(b)):
                self._check(b)

    def test_selftest_cli(self):
        path = self.copy(min(WORLDS, key=os.path.getsize))
        before = H.read_bytes(path)
        with mock.patch("sys.stdout"):
            self.assertEqual(dw_spud.main([path, "selftest"]), 0)
        self.assertEqual(H.read_bytes(path), before)


class QueryTests(WorldCase):
    def test_progress_queries(self):
        for src in WORLDS:
            with self.subTest(world=os.path.basename(src)):
                w = dw_spud.WorldFile(self.copy(src))
                self.assertTrue(w.world_name())
                if w.progress_manager() is None:
                    continue
                self.assertTrue(all(isinstance(b, str) and b for b in w.defeated_bosses()))
                self.assertEqual(w.progress_tags(), [e["tag"] for e in w.tagged_values()])
                self.assertEqual(len(w.find_objects("WorldProgressManager")), 1)
                self.assertEqual([p.path for p in w.progress_manager().properties()], list(WPM_PROPS))
                self.assertFalse(w.remove_defeated_boss("ai_boss_nobody"))   # absent -> False
                self.assertFalse(w.dirty)

    def test_cached_characters(self):
        w = dw_spud.WorldFile(self.world_with(chars=1))
        for c in w.cached_characters():
            self.assertTrue(c["name"])
            self.assertEqual(len(c["guid"]), 32)
            self.assertEqual(c["state"]["meta_data"]["char_name"], c["name"])

    def test_boss_altar(self):
        w = dw_spud.WorldFile(self.world_with(altar=1))
        for alt in w.find_objects("bossaltar"):
            self.assertIn(alt.prop("bSummoned").value, (0, 1))


class ScalarEditTests(WorldCase):
    def test_set_tag_value_same_size(self):
        w = dw_spud.WorldFile(self.world_with(tags=1))
        before = _tags(w)
        tag, val = w.tagged_values()[0]["tag"], w.tagged_values()[0]["int"]
        self.assertTrue(w.set_tag_value(tag, val ^ 1))      # flips one bit: one byte changes
        out = w.to_bytes()
        self.assertEqual(len(out), len(w.original))
        self.assertEqual(sum(1 for a, b in zip(out, w.original) if a != b), 1)
        w2 = dw_spud.WorldFile.validate_bytes(out)
        self.assertEqual(_tags(w2), dict(before, **{tag: val ^ 1}))
        # Setting it back restores the original bytes exactly.
        w.set_tag_value(tag, val)
        self.assertEqual(w.to_bytes(), w.original)

    def test_set_tag_float_and_unknown(self):
        w = dw_spud.WorldFile(self.world_with(tags=1))
        tag = w.tagged_values()[-1]["tag"]
        w.set_tag_value(tag, 1.5, as_float=True)
        raw = {e["tag"]: e["value"] for e in w.tagged_values()}[tag]
        self.assertEqual(struct.unpack("<f", raw)[0], 1.5)
        with self.assertRaises(KeyError):
            w.set_tag_value("WorldProgress.Not.There", 1)

    def test_set_scalar_uint8(self):
        w = dw_spud.WorldFile(self.world_with(altar=1))
        before = _object_bytes(w)
        alt = w.find_objects("BossAltar")[0]
        old = alt.prop("bSummoned").value
        self.assertTrue(w.set_scalar(alt, "bSummoned", 1 - old))
        out = w.to_bytes()
        self.assertEqual(len(out), len(w.original))
        self.assertEqual(sum(1 for a, b in zip(out, w.original) if a != b), 1)
        w2 = dw_spud.WorldFile.validate_bytes(out)
        after = _object_bytes(w2)
        self.assertEqual([k for k in before if before[k] != after[k]], [alt.key])
        self.assertEqual(w2.object_by_key(alt.key).prop("bSummoned").value, 1 - old)
        with self.assertRaises(ValueError):
            w.set_scalar(w.progress_manager(), "DefeatedBossesInternalNames", 1)


class ListRemovalTests(WorldCase):
    def _assert_only_wpm_changed(self, orig, w2):
        before, after = _object_bytes(orig), _object_bytes(w2)
        self.assertEqual(set(before), set(after))
        self.assertEqual([k for k in before if before[k] != after[k]], [orig.progress_manager().key])
        self.assertEqual(_shape(orig), _shape(w2))          # same chunk tree shape everywhere
        out = w2.to_bytes()
        self.assertEqual(struct.unpack_from("<I", out, 4)[0] + 8, len(out))   # SAVE length = size - 8

    def test_remove_defeated_boss(self):
        w = dw_spud.WorldFile(self.world_with(bosses=1))
        orig = dw_spud.WorldFile.from_bytes(w.original)
        bosses = w.defeated_bosses()
        self.assertTrue(w.remove_defeated_boss(bosses[-1]))
        out = w.to_bytes()
        self.assertEqual(len(w.original) - len(out), 4 + len(bosses[-1]) + 1)
        w2 = dw_spud.WorldFile.validate_bytes(out)
        self.assertEqual(w2.object_count(), orig.object_count())
        self.assertEqual(w2.defeated_bosses(), bosses[:-1])
        self.assertEqual(w2.world_hooks(), orig.world_hooks())
        self.assertEqual(w2.tagged_values(), orig.tagged_values())
        self.assertEqual(w2.progress_manager().prop("bCanBeDamaged").value,
                         orig.progress_manager().prop("bCanBeDamaged").value)
        self.assertEqual([c["json"] for c in w2.cached_characters()],
                         [c["json"] for c in orig.cached_characters()])
        self._assert_only_wpm_changed(orig, w2)
        self.assertEqual(w2.to_bytes(), out)  # stable after the edit

    def test_remove_all_bosses_and_a_tag(self):
        w = dw_spud.WorldFile(self.world_with(bosses=1, tags=1))
        orig = dw_spud.WorldFile.from_bytes(w.original)
        tags = w.progress_tags()
        for b in list(w.defeated_bosses()):
            self.assertTrue(w.remove_defeated_boss(b))
        self.assertTrue(w.remove_progress_tag(tags[-1]))
        w2 = dw_spud.WorldFile.validate_bytes(w.to_bytes())
        self.assertEqual(w2.defeated_bosses(), [])
        self.assertEqual(w2.progress_tags(), tags[:-1])
        self.assertEqual([p.path for p in w2.progress_manager().properties()], list(WPM_PROPS))
        self._assert_only_wpm_changed(orig, w2)

    def test_unknown_entries_leave_model_untouched(self):
        w = dw_spud.WorldFile(self.world_with())
        self.assertFalse(w.remove_defeated_boss("ai_boss_nobody"))
        self.assertFalse(w.remove_progress_tag("WorldProgress.Not.There"))
        self.assertEqual(w.to_bytes(), w.original)
        self.assertFalse(w.dirty)


class SaveTests(WorldCase):
    def setUp(self):
        super().setUp()
        p1 = mock.patch.object(dw_spud, "_game_is_running", return_value=False)
        self.running = p1.start()
        self.addCleanup(p1.stop)
        p2 = mock.patch.object(dw_spud, "_snapshot_saves", return_value="SNAPSHOT")
        self.snapshot = p2.start()
        self.addCleanup(p2.stop)

    def _edited(self, bosses=1, tags=0):
        """(path, world, remaining bosses) with the last defeated boss removed in memory."""
        path = self.world_with(bosses=bosses, tags=tags)
        w = dw_spud.WorldFile(path)
        bosses = w.defeated_bosses()
        self.assertTrue(w.remove_defeated_boss(bosses[-1]))
        return path, w, bosses[:-1]

    def _no_temp_files(self):
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_save_writes_backup_and_snapshot(self):
        path, w, left = self._edited()
        orig = H.read_bytes(path)
        r = w.save()
        self.assertTrue(r["written"])
        self.snapshot.assert_called_once_with("pre-world-edit")
        self.assertEqual(r["snapshot"], "SNAPSHOT")
        self.assertTrue(r["backup"].endswith(".pyedit.bak"))
        self.assertEqual(H.read_bytes(r["backup"]), orig)
        w2 = dw_spud.WorldFile(path)
        self.assertEqual(w2.defeated_bosses(), left)
        self.assertEqual(w2.to_bytes(), H.read_bytes(path))
        self.assertFalse(w.dirty)
        self._no_temp_files()
        # A second save never overwrites the first backup.
        pm = w.progress_manager()
        prefix, hooks = dw_spud.decode_string_set(pm.prop("WorldHooksTriggered").raw)
        w.set_raw_property(pm, "WorldHooksTriggered", dw_spud.encode_string_set(prefix, hooks + ["/Game/T.T"]))
        r2 = w.save()
        self.assertNotEqual(r2["backup"], r["backup"])
        self.assertEqual(H.read_bytes(r["backup"]), orig)

    def test_dry_run_writes_nothing(self):
        path, w, _ = self._edited()
        orig = H.read_bytes(path)
        r = w.save(dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertFalse(r["written"])
        self.assertEqual(H.read_bytes(path), orig)
        self.snapshot.assert_not_called()
        self.assertEqual(len(os.listdir(self.dir)), 1)

    def test_nothing_to_save(self):
        path = self.world_with()
        r = dw_spud.WorldFile(path).save()
        self.assertFalse(r["written"])
        self.snapshot.assert_not_called()
        self.assertEqual(len(os.listdir(self.dir)), 1)

    # save() checks the LAST value of every edited property, so repeated edits of the same
    # property before one save must verify against the final state, not an earlier one.
    def test_save_after_two_boss_removals(self):
        path, w, left = self._edited(bosses=2)
        self.assertTrue(w.remove_defeated_boss(left[-1]))
        r = w.save()
        self.assertEqual(dw_spud.WorldFile(path).defeated_bosses(), left[:-1])
        self.assertEqual(dw_spud.WorldFile(path).to_bytes(), H.read_bytes(path))
        self.assertTrue(os.path.isfile(r["backup"]))

    def test_save_after_boss_removal_and_tag_edits(self):
        path, w, left = self._edited(tags=1)
        tags = _tags(w)
        first, last = w.progress_tags()[0], w.progress_tags()[-1]
        w.set_tag_value(first, tags[first] ^ 1)
        w.set_tag_value(first, tags[first])            # back to the original value
        w.remove_progress_tag(last)
        expect = {k: v for k, v in tags.items() if k != last}
        if first != last:
            w.set_tag_value(first, 7)
            expect[first] = 7
        w.save()
        w2 = dw_spud.WorldFile(path)
        self.assertEqual(w2.defeated_bosses(), left)
        self.assertEqual(_tags(w2), expect)
        self.assertEqual(w2.to_bytes(), H.read_bytes(path))

    def test_save_after_set_then_remove_same_tag(self):
        path = self.world_with(tags=1)
        w = dw_spud.WorldFile(path)
        tags = _tags(w)
        tag = w.progress_tags()[-1]
        w.set_tag_value(tag, 3)
        self.assertTrue(w.remove_progress_tag(tag))
        w.save()
        w2 = dw_spud.WorldFile(path)
        self.assertNotIn(tag, w2.progress_tags())
        self.assertEqual(_tags(w2), {k: v for k, v in tags.items() if k != tag})

    def test_save_after_edits_undone_is_byte_identical(self):
        path = self.world_with(tags=1)
        orig = H.read_bytes(path)
        w = dw_spud.WorldFile(path)
        for alt in w.find_objects("BossAltar")[:1]:
            old = alt.prop("bSummoned").value
            w.set_scalar(alt, "bSummoned", 1 - old)
            w.set_scalar(alt, "bSummoned", old)
        tag, val = w.tagged_values()[0]["tag"], w.tagged_values()[0]["int"]
        w.set_tag_value(tag, val ^ 1)
        w.set_tag_value(tag, val)
        self.assertEqual(w.to_bytes(), orig)            # edits undone -> byte-exact
        r = w.save()
        self.assertEqual(H.read_bytes(path), orig)
        self.assertEqual(H.read_bytes(r["backup"]), orig)

    def test_refuses_while_game_runs(self):
        path, w, left = self._edited()
        orig = H.read_bytes(path)
        self.running.return_value = True
        with self.assertRaises(RuntimeError):
            w.save()
        self.assertEqual(H.read_bytes(path), orig)
        self.snapshot.assert_not_called()
        self.assertEqual(len(os.listdir(self.dir)), 1)  # no backup either
        w.save(force=True)
        self.assertEqual(dw_spud.WorldFile(path).defeated_bosses(), left)

    def test_refuses_if_file_changed_on_disk(self):
        path, w, _ = self._edited()
        self.assertFalse(w.changed_on_disk())
        with open(path, "ab") as f:
            f.write(b"x")
        self.assertTrue(w.changed_on_disk())
        with self.assertRaises(RuntimeError):
            w.save()
        self.snapshot.assert_not_called()

    def test_failed_verification_does_not_replace(self):
        path, w, _ = self._edited()
        orig = H.read_bytes(path)
        # Claim an edit the output does not contain: verification must fail before writing.
        pm = w.progress_manager()
        w._expect[(pm.key, "bCanBeDamaged")] = b"\x07"
        with self.assertRaises(dw_spud.FormatError):
            w.save()
        self.assertEqual(H.read_bytes(path), orig)
        self.snapshot.assert_not_called()
        self.assertEqual(len(os.listdir(self.dir)), 1)

    def test_failed_snapshot_writes_nothing(self):
        path, w, _ = self._edited()
        orig = H.read_bytes(path)
        self.snapshot.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            w.save()
        self.assertEqual(H.read_bytes(path), orig)
        self.assertEqual(len(os.listdir(self.dir)), 1)


class ContextSaveTests(WorldCase):
    """AppContext.write_world keeps the changed-on-disk refusal even when the user forces
    a save past the game-running check (spud's force skips both)."""

    def setUp(self):
        super().setUp()
        from dragonwilds_save_editor.gui import context as C
        self.C = C
        for name, kw in (("_game_is_running", {"return_value": True}),
                         ("_snapshot_saves", {"return_value": "SNAP"})):
            p = mock.patch.object(dw_spud, name, **kw)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(H.dw_save, "game_is_running", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_force_still_refuses_changed_file(self):
        path = self.world_with(bosses=1)
        ctx = self.C.AppContext(None)
        ctx.load_world(path)
        ctx.world.remove_defeated_boss(ctx.world.defeated_bosses()[-1])
        ctx.mark_world_dirty("removed a boss")
        self.assertEqual(ctx.world_changes(), ["removed a boss"])
        with self.assertRaises(RuntimeError):
            ctx.write_world()                         # game "running"
        with open(path, "ab") as f:
            f.write(b"x")
        changed = H.read_bytes(path)
        with self.assertRaises(RuntimeError):
            ctx.write_world(force=True)               # forced, but the file changed underneath
        self.assertEqual(H.read_bytes(path), changed)
        self.assertEqual(glob.glob(glob.escape(path) + ".*.pyedit.bak"), [])

    def test_world_changes_fallback(self):
        path = self.world_with(tags=1)
        ctx = self.C.AppContext(None)
        ctx.load_world(path)
        self.assertEqual(ctx.world_changes(), [])
        self.assertFalse(ctx.world_dirty)
        ctx.mark_world_dirty("note without an edit")
        self.assertEqual(ctx.world_changes(), [])     # nothing actually changed
        ctx.load_world(path)
        tag, val = ctx.world.tagged_values()[0]["tag"], ctx.world.tagged_values()[0]["int"]
        ctx.world.set_tag_value(tag, val ^ 1)         # edited without a note
        self.assertTrue(ctx.world_dirty)
        self.assertEqual(len(ctx.world_changes()), 1)


if __name__ == "__main__":
    unittest.main()
