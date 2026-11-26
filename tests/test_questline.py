"""Linear questline checkpoints (dragonwilds_save_editor.questline). Works on a temp copy of the save."""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from . import _helpers as H  # noqa: F401  (isolated LOCALAPPDATA + fixture catalog)
except ImportError:
    import _helpers as H  # noqa: F401

from dragonwilds_save_editor import save as dw_save  # noqa: E402
from dragonwilds_save_editor import catalog as C  # noqa: E402
from dragonwilds_save_editor import questline as L  # noqa: E402

SAVE = os.path.join(ROOT, "tests", "fixtures", "sample_character.json")  # synthetic, at BKF step 7
WH = "uftGB0es-CGrvXyPoxW31w"
BKF = "3MpWS0mD8A6yFVmjVAA2Qg"
DR_INTRO = "prbKS0g1X6EsOe6Lc17yAg"   # PH_DowndunReachIntro
FH_INTRO = "w7i9eEkrmS07OdumshFxiA"   # PH_FellHollowIntro


class QuestlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "copy.json")
        shutil.copy2(SAVE, self.path)
        self.s = dw_save.SaveFile(self.path)
        self.d = L.load()

    def tearDown(self):
        self.tmp.cleanup()

    def test_sample_save_is_at_bkf_step7(self):
        self.assertEqual(L.current_checkpoint(self.s, self.d)["id"], "bkf_step7_gatekeeper")

    def test_revert_to_imaru_is_exact_and_linear(self):
        before = {v["QuestVariableName"] for v in L.find_quest(self.s, WH)["QuestBools"]}
        L.apply(self.s, self.d, L.checkpoint(self.d, "wh_ready_imaru"))
        wh = L.find_quest(self.s, WH)
        after = {v["QuestVariableName"] for v in wh["QuestBools"]}
        self.assertEqual(before - after, {"ImaruDefeated", "HasRecievedImaruHead"})
        self.assertEqual(after - before, set())
        self.assertEqual((wh["QuestState"], wh["QuestObjective"]), (1, "ChallangeImaru"))
        self.assertEqual(L._vars(wh, "QuestInts"), {"DeathQuest_Beat": 5, "StandStoneInt": 2, "SealsBroken": 3})
        self.assertEqual(L.find_quest(self.s, BKF),
                         {"QuestId": BKF, "QuestState": 0, "QuestObjective": "None", "QuestInts": [], "QuestBools": []})
        self.assertNotIn("ALQSs0j7loBVpum0CaDH2w", self.s.progress["Progress"]["ItemsPickedUp"])
        for frag in ("TQY6cUXdLjzqCIuXB3vAvw", "ObT03UmkX-U-WJ667Rk0vA", "o9Nec0TWzFiYJIeiYQBjVw"):
            self.assertTrue(L._holds(self.s, frag))
        self.assertEqual(L.current_checkpoint(self.s, self.d)["id"], "wh_ready_imaru")
        # every earlier main quest untouched and complete
        order = self.d["main_quest_order"]
        for qid in order[:order.index(WH)]:
            self.assertEqual(L.quest_state(self.s, qid), 2)

    def test_written_file_round_trips(self):
        dw_save.game_is_running = lambda: False
        L.apply(self.s, self.d, L.checkpoint(self.d, "wh_ready_imaru"))
        self.s.save()
        s2 = dw_save.SaveFile(self.path)
        self.assertEqual(s2.to_text(), s2.original_text)
        self.assertEqual(L.current_checkpoint(s2, self.d)["id"], "wh_ready_imaru")

    def test_forward_is_refused(self):
        L.apply(self.s, self.d, L.checkpoint(self.d, "wh_ready_imaru"))
        with self.assertRaises(L.QuestlineError):
            L.apply(self.s, self.d, L.checkpoint(self.d, "bkf_given_by_death"))

    def test_current_is_refused(self):
        with self.assertRaises(L.QuestlineError):
            L.apply(self.s, self.d, L.checkpoint(self.d, "bkf_step7_gatekeeper"))

    def test_high_needs_acknowledgement(self):
        cp = L.checkpoint(self.d, "wh_given")
        self.assertEqual(cp["confidence"], "high")
        self.assertTrue(cp["enabled"])
        self.assertTrue(L.needs_ack(cp))
        with self.assertRaises(L.QuestlineError):
            L.apply(self.s, self.d, cp)                    # not acknowledged -> refused
        L.apply(self.s, self.d, cp, acknowledged=True)     # acknowledged -> applied
        self.assertEqual(L.find_quest(self.s, WH)["QuestObjective"], "TalkToWomNEGF")

    def test_every_high_checkpoint_states_its_inference(self):
        for c in self.d["checkpoints"]:
            if c["confidence"] == "high":
                self.assertTrue(c.get("inference"), c["id"])

    def test_every_reachable_checkpoint_lands_exactly(self):
        """Apply each enabled checkpoint behind the sample save to a fresh copy, write, reload."""
        dw_save.game_is_running = lambda: False
        order = self.d["main_quest_order"]
        applied = 0
        for cp in self.d["checkpoints"]:
            live = dw_save.SaveFile(SAVE)
            if L.status(live, self.d, cp)[0] != "available":
                continue
            with self.subTest(cp=cp["id"]):
                shutil.copy2(SAVE, self.path)
                s = dw_save.SaveFile(self.path)
                L.apply(s, self.d, cp, acknowledged=True)
                s.save()
                s2 = dw_save.SaveFile(self.path)
                self.assertEqual(s2.to_text(), s2.original_text)
                self.assertEqual((L.current_checkpoint(s2, self.d) or {}).get("id"), cp["id"])
                qi = order.index(cp["quest_id"])
                for q in order[:qi]:
                    self.assertEqual(L.quest_state(s2, q), 2)
                for q in order[qi + 1:]:
                    for r in [q] + L.related_ids(self.d, q):
                        rec = L.find_quest(s2, r)
                        if rec:
                            self.assertEqual((rec["QuestState"], rec["QuestBools"]), (0, []))
                for it in cp["inventory_add"]:
                    self.assertTrue(L._holds(s2, it["id"]))
                for it in cp["inventory_remove"]:
                    self.assertFalse(L._holds(s2, it["id"]))
                drop = {h["id"] for h in cp["hooks_remove"]}
                after = L._hooks_list(s2)
                self.assertFalse(drop & set(after), cp["id"])
                self.assertEqual(after, [x for x in L._hooks_list(live) if x not in drop])
                applied += 1
        self.assertGreaterEqual(applied, 13)

    def test_imaru_revert_replays_dowdun_intro_only(self):
        before = list(L._hooks_list(self.s))
        self.assertIn(DR_INTRO, before)          # the test copy has entered Dowdun Reach
        lines = L.apply(self.s, self.d, L.checkpoint(self.d, "wh_ready_imaru"))
        self.assertTrue(any("Dowdun Reach intro" in ln and DR_INTRO in ln for ln in lines))
        after = L._hooks_list(self.s)
        self.assertEqual(after, [x for x in before if x != DR_INTRO])   # order kept, nothing else touched
        self.assertIn(FH_INTRO, after)           # Fellhollow was entered before this checkpoint

    def test_written_hook_removal_round_trips(self):
        dw_save.game_is_running = lambda: False
        L.apply(self.s, self.d, L.checkpoint(self.d, "wh_ready_imaru"))
        self.s.save()
        s2 = dw_save.SaveFile(self.path)
        self.assertEqual(s2.to_text(), s2.original_text)
        self.assertNotIn(DR_INTRO, L._hooks_list(s2))

    def test_absent_hook_is_noop(self):
        hooks = L._hooks_list(self.s)
        hooks[:] = [x for x in hooks if x != DR_INTRO]
        snapshot = list(hooks)
        lines = L.apply(self.s, self.d, L.checkpoint(self.d, "wh_ready_imaru"))
        self.assertEqual(L._hooks_list(self.s), snapshot)
        self.assertFalse(any("Replay" in ln for ln in lines))

    def test_hooks_remove_ids_are_known_intro_hooks(self):
        known = C.load_catalog("unlock_names")["PlayerHooksTriggered"]   # fixture catalog
        for c in self.d["checkpoints"]:
            self.assertIn("hooks_remove", c, c["id"])
            for h in c["hooks_remove"]:
                self.assertIn(h["id"], known, (c["id"], h))
                self.assertTrue(h.get("label"))
                self.assertNotEqual(known[h["id"]]["group"], "FTUE", (c["id"], h))
        # a hook that fires later must also be removed by every earlier checkpoint (linear)
        seen = set()
        for c in reversed(self.d["checkpoints"]):
            ids = {h["id"] for h in c["hooks_remove"]}
            self.assertTrue(seen <= ids, c["id"])
            seen = ids

    def test_very_high_needs_no_acknowledgement(self):
        self.assertFalse(L.needs_ack(L.checkpoint(self.d, "wh_ready_imaru")))

    def test_below_floor_is_disabled(self):
        self.d["checkpoints"].append({"id": "x", "label": "x", "quest_id": WH, "confidence": "med"})
        floor = L.CONFIDENCE_RANK[self.d["min_confidence"]]
        for c in self.d["checkpoints"]:
            if c["id"] == "x":
                self.assertLess(L.CONFIDENCE_RANK[c["confidence"]], floor)
    def test_nonlinear_save_is_refused(self):
        # Make an earlier main quest incomplete: nothing after it may be applied.
        L.find_quest(self.s, "yrRZnkmro-IvH_OmZ3f-5A")["QuestState"] = 1
        with self.assertRaises(L.QuestlineError):
            L.apply(self.s, self.d, L.checkpoint(self.d, "wh_ready_imaru"))

    def test_revert_within_bkf(self):
        L.apply(self.s, self.d, L.checkpoint(self.d, "bkf_given_by_death"))
        bkf = L.find_quest(self.s, BKF)
        self.assertEqual((bkf["QuestState"], bkf["QuestObjective"]), (1, "DR_Main_Objective_0"))
        self.assertEqual(L._vars(bkf, "QuestBools"), {"GivenQuestOnLogin": True, "RecievedDRQuestFromDeath": True})
        self.assertEqual(L.quest_state(self.s, WH), 2)


if __name__ == "__main__":
    unittest.main()
