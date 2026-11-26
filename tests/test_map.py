"""Tests for dragonwilds_save_editor/map.py (fog bitmap, Sanguine Urns, kebbit burrows, post-revert suggestion).

Works on a temp copy of the save; uses tests/fixtures/map_points_min.json as the catalog so the
tests do not depend on the bundled map_points.json.
"""

import os
import unittest

try:
    from . import _helpers as H
except ImportError:  # discovered as a top-level module
    import _helpers as H

from dragonwilds_save_editor import map as M  # noqa: E402
from dragonwilds_save_editor import questline as L  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "map_points_min.json")
NEW_SHRINE = "00000000000000000000000000000ABC"
OLD_SHRINE = "824A3798412A1067890E86A2AEB609FF"
NEW_BURROW = "11111111111111111111111111111DEF"
FOUND_ONLY = "804AED6240B09B374F6FEFB3A165FC09"      # in Found, not Activated
ACT_NOT_FOUND = "EDB3BF37460645E5CCBFAC9444293910"  # in Activated, not Found (written by the game)


class MapTests(H.TempSaveCase):
    def setUp(self):
        super().setUp()
        self.m = M.load_map_data(FIXTURE)
        self.s = self.open()

    def reopen_after_save(self):
        self.quiet_save(self.s)
        self.s = self.open()
        self.assertEqual(self.s.to_text(), self.s.original_text)
        return self.s

    # ---- catalog ---------------------------------------------------------------
    def test_missing_catalog_falls_back(self):
        m = M.load_map_data(os.path.join(self.dir, "nope.json"))
        self.assertEqual([a["name"] for a in m["areas"]], [n for n, _ in M.BUILTIN_AREAS])
        self.assertEqual(m["shrines"], {})
        self.assertTrue(m["warnings"])
        rows = M.urn_rows(self.s, m)
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(r["name"] == M.UNKNOWN_NAME for r in rows))

    def test_partial_catalog(self):
        p = os.path.join(self.dir, "partial.json")
        with open(p, "w") as f:
            f.write('{"shrines": [{"id": "824a3798412a1067890e86a2aeb609ff", "name": "X"}]}')
        m = M.load_map_data(p)
        self.assertEqual(len(m["areas"]), 6)
        self.assertEqual(M.point_name(m, "shrines", OLD_SHRINE), "X")

    # ---- fog -----------------------------------------------------------------------
    def test_bitmap_and_bit0(self):
        self.assertEqual(M.fog_bitmap(self.s), 67108863)
        M.set_bits(self.s, [0, 1, 2], False)
        self.assertTrue(M.is_revealed(self.s, 0))
        self.assertFalse(M.is_revealed(self.s, 1))
        self.assertEqual(M.set_fog_bitmap(self.s, 0), 1)
        self.assertEqual(M.fog_bitmap(self.s), 1)
        for a in self.m["areas"]:
            M.hide_area(self.s, a)
        self.assertEqual(M.fog_bitmap(self.s), 1)

    def test_hide_dowdun(self):
        dd = M.area(self.m, "Dowdun Reach")
        self.assertEqual(M.area_state(self.s, dd), (10, 10))
        self.assertEqual(M.hide_area(self.s, dd), 65535)
        self.assertEqual(M.area_state(self.s, dd), (0, 10))
        self.assertEqual(self.reopen_after_save().progress["RevealedFog"]["RevealedRegionsBitmap"], 65535)

    def test_reveal_all_writes_int32(self):
        M.reveal_all(self.s, self.m)
        self.assertEqual(M.fog_bitmap(self.s), 0xFFFFFFFF)
        self.assertEqual(self.s.progress["RevealedFog"]["RevealedRegionsBitmap"], -1)
        self.assertEqual(M.fog_bitmap(self.reopen_after_save()), 0xFFFFFFFF)

    def test_unchanged_bitmap_is_byte_exact(self):
        M.reveal_area(self.s, M.area(self.m, "Brynmoor"))
        self.assertEqual(self.s.to_bytes(), self.orig_bytes)

    # ---- Sanguine Urns (ShrinesUnlocked) --------------------------------------------------------------------
    def test_urn_add_remove_round_trip(self):
        self.assertTrue(M.unlock_urn(self.s, self.m, NEW_SHRINE.lower()))
        self.assertEqual(self.s.progress["Progress"]["ShrinesUnlocked"][-1], NEW_SHRINE)
        self.assertFalse(M.unlock_urn(self.s, self.m, NEW_SHRINE))  # no duplicates
        s = self.reopen_after_save()
        self.assertIn(NEW_SHRINE, s.progress["Progress"]["ShrinesUnlocked"])
        self.assertTrue(M.remove_urn(s, NEW_SHRINE))
        self.quiet_save(s)
        self.assertEqual(H.read_bytes(self.path), self.orig_bytes)

    def test_removed_game_urn_can_be_readded(self):
        lst = self.s.progress["Progress"]["ShrinesUnlocked"]
        sid = lst[3]  # not in the fixture catalog, but written by the game
        M.remove_urn(self.s, sid)
        self.assertNotIn(sid, lst)
        self.assertTrue(M.unlock_urn(self.s, self.m, sid))

    def test_unknown_ids_refused(self):
        for bad in ("hello", "", "ZZZZ3798412A1067890E86A2AEB609FF", "1234567890ABCDEF1234567890ABCDEE"):
            with self.subTest(bad=bad):
                with self.assertRaises(M.MapError):
                    M.unlock_urn(self.s, self.m, bad)
                with self.assertRaises(M.MapError):
                    M.set_burrow_flags(self.s, self.m, bad, activated=True)
        self.assertEqual(self.s.to_bytes(), self.orig_bytes)

    # ---- burrows -------------------------------------------------------------------
    def test_burrow_states_from_save(self):
        self.assertEqual(M.burrow_state(self.s, FOUND_ONLY), M.FOUND_ONLY)
        self.assertEqual(M.burrow_state(self.s, ACT_NOT_FOUND), M.ACTIVE)
        self.assertEqual(M.burrow_state(self.s, NEW_BURROW), M.NOT_FOUND)
        rows = {r["id"]: r for r in M.burrow_rows(self.s, self.m)}
        self.assertEqual(len(rows), 13)  # 8 found + 4 activated-only + 1 catalog-only
        self.assertFalse(rows[ACT_NOT_FOUND]["in_found"])

    def test_burrow_flags_independent_round_trip(self):
        pr = self.s.progress["Progress"]
        self.assertTrue(M.set_burrow_flags(self.s, self.m, NEW_BURROW, activated=True))
        self.assertEqual(pr["KebbitBurrowsActivated"][-1], NEW_BURROW)
        self.assertNotIn(NEW_BURROW, pr["KebbitBurrowsFound"], "Activated must not force Found")
        M.set_burrow_flags(self.s, self.m, NEW_BURROW, found=True)
        self.assertEqual(pr["KebbitBurrowsFound"][-1], NEW_BURROW)
        s = self.reopen_after_save()
        pr = s.progress["Progress"]
        self.assertTrue(M.set_burrow_flags(s, self.m, NEW_BURROW, activated=False))
        self.assertIn(NEW_BURROW, pr["KebbitBurrowsFound"])
        self.assertNotIn(NEW_BURROW, pr["KebbitBurrowsActivated"])
        self.assertTrue(M.remove_burrow(s, NEW_BURROW))
        self.assertFalse(M.remove_burrow(s, NEW_BURROW))
        self.quiet_save(s)
        self.assertEqual(H.read_bytes(self.path), self.orig_bytes)

    def test_order_preserved(self):
        pr = self.s.progress["Progress"]
        before = list(pr["KebbitBurrowsFound"])
        M.set_burrow_flags(self.s, self.m, ACT_NOT_FOUND, found=True)
        self.assertEqual(pr["KebbitBurrowsFound"], before + [ACT_NOT_FOUND])
        self.assertIn(ACT_NOT_FOUND, pr["KebbitBurrowsActivated"])
        M.remove_burrow(self.s, before[2])
        self.assertEqual(pr["KebbitBurrowsFound"], before[:2] + before[3:] + [ACT_NOT_FOUND])

    # ---- suggestion -------------------------------------------------------------------
    def test_no_suggestion_on_live_save(self):
        self.assertEqual(M.suggest_fog_reset(self.s, L.load(), self.m), [])

    def test_suggestion_after_revert_to_imaru(self):
        d = L.load()
        L.apply(self.s, d, L.checkpoint(d, "wh_ready_imaru"))
        self.assertEqual(M.fog_bitmap(self.s), 67108863, "a quest revert must not touch the fog")
        sug = M.suggest_fog_reset(self.s, d, self.m)
        self.assertEqual([x["area"] for x in sug], ["Dowdun Reach"])  # Fellhollow's quest is started
        dd = sug[0]
        self.assertEqual(dd["bits"], list(range(16, 26)))
        self.assertEqual(dd["urns"], ["FBA02FCB4F0443D2E48EBAA3ABDC5FE2"])
        self.assertEqual(sorted(dd["burrows"]), sorted([FOUND_ONLY, ACT_NOT_FOUND]))
        M.apply_fog_reset(self.s, sug)
        self.assertEqual(M.fog_bitmap(self.s), 65535)
        self.assertEqual(M.burrow_state(self.s, FOUND_ONLY), M.NOT_FOUND)
        self.assertNotIn(dd["urns"][0], self.s.progress["Progress"]["ShrinesUnlocked"])
        self.assertEqual(M.suggest_fog_reset(self.s, d, self.m), [])
        s = self.reopen_after_save()
        self.assertEqual(M.fog_bitmap(s), 65535)


if __name__ == "__main__":
    unittest.main()
