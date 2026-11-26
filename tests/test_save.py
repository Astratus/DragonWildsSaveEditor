"""Tests for dragonwilds_save_editor/save.py. Run from the project root:  python -m unittest discover -s tests -v"""

import base64
import difflib
import json
import os
import re
import unittest
from unittest import mock

try:
    from . import _helpers as H
except ImportError:  # discovered as a top-level module
    import _helpers as H

dw_save = H.dw_save

GUID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")

NATURE_RUNE = "iKbF7k2XvufGqqyg5rK-vQ"
BRONZE_ARROW = "XvhWN00lBZJCFb6r0p-tMg"
BRONZE_PICKAXE = "V-CGfkBdlbxvc-6TkU-K_A"
FISHING = "vwY5IkQJJDwb2PKEfoc8MQ"


def find_bag_item(game):
    """A live, stackable, non-gear bag item with max_stack > 1."""
    for it in game.items:
        if (it.get("inv_tab") == "bag" and not it.get("max_durability") and (it.get("max_stack") or 0) >= 99
                and not it.get("retired") and not it.get("placeholder_name")):
            return it
    raise AssertionError("no bag item in catalog")


# --------------------------------------------------------------------------
class RoundTripTests(unittest.TestCase):
    def _check(self, path):
        before = H.read_bytes(path)
        s = dw_save.SaveFile(path, H.game_data())
        self.assertEqual(s.to_bytes(), before)
        self.assertEqual(H.read_bytes(path), before, "reading must not modify the file")

    def test_sample_save(self):
        self._check(H.SAMPLE_SAVE)

    def test_older_v83_save(self):
        self._check(H.SAMPLE_V83)

    def test_ue_dumps_small_shapes(self):
        v = dw_save.ue_loads('{"a": {}, "b": [], "c": [1, 2.5, true], "d": [{"x": 1}], "e": {"f": "q\\"t"}}')
        self.assertEqual(
            dw_save.ue_dumps(v),
            '{\r\n\t"a":\r\n\t{\r\n\t},\r\n\t"b": [],\r\n\t"c": [ 1, 2.5, true ],\r\n'
            '\t"d": [\r\n\t\t{\r\n\t\t\t"x": 1\r\n\t\t}\r\n\t],\r\n\t"e":\r\n\t{\r\n\t\t"f": "q\\"t"\r\n\t}\r\n}')

    def test_new_float_uses_17g(self):
        self.assertEqual(dw_save.ue_dumps([0.1]), "[ 0.10000000000000001 ]")


# --------------------------------------------------------------------------
class BackupTests(H.TempSaveCase):
    def test_save_creates_backup_equal_to_pre_write_file(self):
        s = self.open()
        s.set_skill("Fishing", level=30)
        backup = self.quiet_save(s)
        self.assertTrue(os.path.isfile(backup))
        self.assertEqual(H.read_bytes(backup), self.orig_bytes)
        self.assertNotEqual(H.read_bytes(self.path), self.orig_bytes)

    def test_every_save_makes_new_backup_same_second(self):
        s = self.open()
        contents = []
        backups = []
        for lvl in (10, 20, 30, 40):
            contents.append(H.read_bytes(self.path))
            s.set_skill("Fishing", level=lvl)
            backups.append(self.quiet_save(s))
        self.assertEqual(len(set(backups)), 4, backups)
        self.assertEqual(len(self.backups()), 4)
        for b, c in zip(backups, contents):
            self.assertEqual(H.read_bytes(b), c, "each backup must hold the file as it was before that write")

    def test_same_second_with_frozen_clock(self):
        fixed = dw_save.datetime(2026, 1, 2, 3, 4, 5)
        with mock.patch.object(dw_save, "datetime") as dt:
            dt.now.return_value = fixed
            s = self.open()
            names = {self.quiet_save(s) for _ in range(3)}
        self.assertEqual(len(names), 3)

    def test_dry_run_writes_nothing(self):
        s = self.open()
        s.add_item(NATURE_RUNE, count=10)
        mtime = os.path.getmtime(self.path)
        self.assertIsNone(self.quiet_save(s, dry_run=True))
        self.assertEqual(H.read_bytes(self.path), self.orig_bytes)
        self.assertEqual(os.path.getmtime(self.path), mtime)
        self.assertEqual(self.backups(), [])
        self.assertEqual(sorted(os.listdir(self.dir)), [H.SAVE_NAME])

    def test_refuses_when_game_running(self):
        s = self.open()
        s.set_skill("Fishing", level=30)
        with mock.patch.object(dw_save, "game_is_running", return_value=True):
            with self.assertRaises(RuntimeError):
                self.quiet_save(s)
            self.assertEqual(H.read_bytes(self.path), self.orig_bytes)
            self.assertEqual(self.backups(), [])
            backup = self.quiet_save(s, force=True)
        self.assertTrue(os.path.isfile(backup))

    def test_no_temp_files_left(self):
        s = self.open()
        self.quiet_save(s)
        leftovers = [f for f in os.listdir(self.dir) if f.startswith(".dw_save_")]
        self.assertEqual(leftovers, [])


# --------------------------------------------------------------------------
class AddItemTests(H.TempSaveCase):
    def setUp(self):
        super().setUp()
        self.s = self.open()
        self.inv = self.s.section("Inventory")

    def test_rune_goes_to_rune_tab(self):
        used = {int(k) for k in self.inv if k.isdigit()}
        slot, item = self.s.add_item("Nature Rune", count=5)
        self.assertEqual(item["id"], NATURE_RUNE)
        self.assertEqual(slot, min(x for x in range(40, 72) if x not in used))
        self.assertEqual(slot, 47)

    def test_arrow_goes_to_ammo_tab(self):
        used = {int(k) for k in self.inv if k.isdigit()}
        slot, _ = self.s.add_item(BRONZE_ARROW, count=50)
        self.assertEqual(slot, min(x for x in range(72, 104) if x not in used))

    def test_bag_item_goes_to_bag_never_hotbar(self):
        # Empty the hotbar so a naive "first free slot" would pick 0-7.
        for k in [str(i) for i in range(8)]:
            self.inv.pop(k, None)
        it = find_bag_item(self.game)
        used = {int(k) for k in self.inv if k.isdigit()}
        for _ in range(3):
            slot, _ = self.s.add_item(it["id"], count=2)
            self.assertIn(slot, range(8, 40))
            self.assertEqual(slot, min(x for x in range(8, 40) if x not in used))
            used.add(slot)

    def test_full_tab_raises(self):
        for i in range(40, 72):
            self.inv.setdefault(str(i), {"GUID": dw_save.new_item_guid(), "ItemData": NATURE_RUNE})
        with self.assertRaises(ValueError):
            self.s.add_item(NATURE_RUNE)

    def test_gear_gets_max_durability_and_no_count(self):
        slot, item = self.s.add_item(BRONZE_PICKAXE)
        e = self.inv[str(slot)]
        self.assertEqual(e["Durability"], item["max_durability"])
        self.assertNotIn("Count", e)

    def test_count_one_omits_count(self):
        slot, _ = self.s.add_item(NATURE_RUNE, count=1)
        self.assertNotIn("Count", self.inv[str(slot)])
        slot2, _ = self.s.add_item(BRONZE_ARROW)
        self.assertNotIn("Count", self.inv[str(slot2)])

    def test_entry_key_order(self):
        slot, _ = self.s.add_item(NATURE_RUNE, count=7)
        self.assertEqual(list(self.inv[str(slot)]), ["GUID", "ItemData", "Count", "AddedToInventoryTimestamp"])
        self.assertEqual(self.inv[str(slot)]["Count"], 7)

    def test_overstack(self):
        mx = self.game.items_by_id[NATURE_RUNE]["max_stack"]
        self.s.add_item(NATURE_RUNE, count=mx)  # exactly max is fine
        with self.assertRaises(ValueError):
            self.s.add_item(NATURE_RUNE, count=mx + 1)
        slot, _ = self.s.add_item(NATURE_RUNE, count=mx + 1, allow_overstack=True)
        self.assertEqual(self.inv[str(slot)]["Count"], mx + 1)

    def test_count_below_one_raises(self):
        with self.assertRaises(ValueError):
            self.s.add_item(NATURE_RUNE, count=0)

    def test_occupied_slot_raises(self):
        with self.assertRaises(ValueError):
            self.s.add_item(NATURE_RUNE, slot=40)

    def test_ambiguous_and_unknown_names(self):
        with self.assertRaises(LookupError) as cm:
            self.s.add_item("Logs")
        self.assertGreater(len(cm.exception.args[0]), 1)
        with self.assertRaises(LookupError):
            self.s.add_item("zzz no such item zzz")

    def test_max_slot_index_raised_and_order(self):
        self.assertEqual(int(self.inv["MaxSlotIndex"]), 113)
        self.s.add_item("Nature Rune", slot=120)
        self.assertEqual(self.inv["MaxSlotIndex"], 120)
        # a lower slot must not lower it
        self.s.add_item(NATURE_RUNE)
        self.assertEqual(self.inv["MaxSlotIndex"], 120)
        keys = list(self.inv)
        self.assertEqual(keys[-1], "MaxSlotIndex")
        nums = [int(k) for k in keys if k.isdigit()]
        self.assertEqual(nums, sorted(nums))

    def test_personal_inventory_raises_max_slot(self):
        pi = self.s.section("PersonalInventory")
        slot, _ = self.s.add_item(NATURE_RUNE, section="PersonalInventory")
        self.assertEqual(slot, 3)
        self.assertEqual(pi["MaxSlotIndex"], 3)
        self.assertEqual(list(pi)[-1], "MaxSlotIndex")

    def test_guid_format_and_unique(self):
        existing = set()
        for sec in dw_save.SECTIONS:
            for _, it in self.s.slots(sec):
                if "GUID" in it:
                    existing.add(it["GUID"])
        new = set()
        for _ in range(5):
            slot, _ = self.s.add_item(NATURE_RUNE)
            g = self.inv[str(slot)]["GUID"]
            self.assertRegex(g, GUID_RE)
            self.assertEqual(len(base64.urlsafe_b64decode(g + "==")), 16)
            new.add(g)
        self.assertEqual(len(new), 5)
        self.assertFalse(new & existing)
        self.assertEqual(len({dw_save.new_item_guid() for _ in range(1000)}), 1000)

    def test_timestamp_reuses_real_ticks(self):
        slot, _ = self.s.add_item(NATURE_RUNE)
        ts = self.inv[str(slot)]["AddedToInventoryTimestamp"]
        self.assertGreater(ts, 1e17)


# --------------------------------------------------------------------------
class EditTests(H.TempSaveCase):
    def setUp(self):
        super().setUp()
        self.s = self.open()
        self.inv = self.s.section("Inventory")

    def test_set_count(self):
        it = self.s.set_count("Inventory", 40, 5000)
        self.assertEqual(it["Count"], 5000)

    def test_set_count_one_removes_count(self):
        self.s.set_count("Inventory", 40, 1)
        self.assertNotIn("Count", self.inv["40"])

    def test_set_count_adds_count_before_timestamp(self):
        # slot 13 (Iron Secateurs) has neither Count nor Durability
        self.assertNotIn("Count", self.inv["13"])
        self.s.set_count("Inventory", 13, 1, allow_overstack=True)
        self.assertNotIn("Count", self.inv["13"])
        self.s.set_count("Inventory", 13, 3, allow_overstack=True)
        keys = list(self.inv["13"])
        self.assertLess(keys.index("Count"), keys.index("AddedToInventoryTimestamp"))

    def test_set_count_rejects(self):
        with self.assertRaises(ValueError):
            self.s.set_count("Inventory", 6, 5)  # Mithril Greatsword: durability item
        with self.assertRaises(ValueError):
            self.s.set_count("Inventory", 40, 0)
        with self.assertRaises(ValueError):
            self.s.set_count("Inventory", 40, 10000)  # rune max_stack 9999
        self.s.set_count("Inventory", 40, 10000, allow_overstack=True)
        with self.assertRaises(KeyError):
            self.s.set_count("Inventory", 14, 5)  # empty slot
        with self.assertRaises(KeyError):
            self.s.set_count("Bank", 40, 5)

    def test_repair(self):
        fixed = self.s.repair()
        got = {(sec, slot): (old, new) for sec, slot, _name, old, new in fixed}
        self.assertEqual(got[("Inventory", 10)], (371, 700))        # Steel Spade
        self.assertEqual(got[("Loadout", 0)], (1582, 1750))         # Mystic Hat
        self.assertNotIn(("Inventory", 6), got)                     # already full
        self.assertEqual(self.inv["10"]["Durability"], 700)
        self.assertEqual(self.s.repair(), [])

    def test_repair_one_section(self):
        fixed = self.s.repair("Loadout")
        self.assertTrue(fixed)
        self.assertTrue(all(f[0] == "Loadout" for f in fixed))
        self.assertEqual(self.inv["10"]["Durability"], 371)

    def test_remove(self):
        removed = self.s.remove("Inventory", 40)
        self.assertEqual(removed["ItemData"], "4wdYZE-FFMhS9Iia0ftWDg")
        self.assertNotIn("40", self.inv)
        self.assertEqual(list(self.inv)[-1], "MaxSlotIndex")
        with self.assertRaises(KeyError):
            self.s.remove("Inventory", 40)

    # BUG: remove() does not check Loadout slots 5-8, which are
    # {PlayerInventoryItemIndex: n} pointers into Inventory. Removing Inventory[72]
    # (equipped Fang Arrows, Loadout[5]) leaves a dangling pointer. It should either
    # refuse or clear the pointer. Fixed: SaveFile.remove now unequips (drops the pointer).
    def test_remove_equipped_item_leaves_no_dangling_pointer(self):
        try:
            self.s.remove("Inventory", 72)
        except (ValueError, KeyError):
            return  # refusing is acceptable
        for _, it in self.s.slots("Loadout"):
            if "PlayerInventoryItemIndex" in it:
                self.assertIn(str(it["PlayerInventoryItemIndex"]), self.inv)


# --------------------------------------------------------------------------
class SkillTests(H.TempSaveCase):
    def setUp(self):
        super().setUp()
        self.s = self.open()

    def _xp(self, sid):
        return next(x["Xp"] for x in self.s.progress["Skills"]["Skills"] if x["Id"] == sid)

    def test_set_by_level(self):
        name, xp, lvl = self.s.set_skill("Fishing", level=30)
        self.assertEqual((name, xp, lvl), ("Fishing", 5367, 30))
        self.assertEqual(self._xp(FISHING), 5367)

    def test_set_by_xp(self):
        name, xp, lvl = self.s.set_skill("fishing", xp=5366)
        self.assertEqual((xp, lvl), (5366, 29))
        self.s.set_skill(FISHING, xp=1000000)
        self.assertEqual(self.s.game.level_for_xp(self._xp(FISHING)), 99)

    def test_levels_match_xp_table(self):
        table = self.game.xp_for_level
        for lvl in range(1, 100):
            _, xp, got = self.s.set_skill("Mining", level=lvl)
            self.assertEqual(xp, table[lvl - 1])
            self.assertEqual(got, lvl)

    def test_bad_input(self):
        for lvl in (0, 100):
            with self.assertRaises(ValueError):
                self.s.set_skill("Fishing", level=lvl)
        with self.assertRaises(ValueError):
            self.s.set_skill("Fishing", xp=-1)
        with self.assertRaises(LookupError):
            self.s.set_skill("Slayer", level=5)

    def test_skills_listing(self):
        rows = dict((n, (xp, lvl)) for n, xp, lvl in self.s.skills())
        self.assertEqual(rows["Fishing"], (2435, 22))
        self.assertEqual(len(rows), 12)


# --------------------------------------------------------------------------
class FormattingTests(H.TempSaveCase):
    def _written(self):
        text = H.read_bytes(self.path)
        self.assertFalse(text.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(text.endswith(b"\n"))
        self.assertTrue(text.endswith(b"}"))
        self.assertNotIn(b"\n", text.replace(b"\r\n", b""), "bare LF found")
        self.assertNotIn(b"\r", text.replace(b"\r\n", b""), "bare CR found")
        json.loads(text.decode("utf-8"))
        return text.decode("utf-8").split("\r\n")

    def _ops(self, new_lines):
        old = self.orig_bytes.decode("utf-8").split("\r\n")
        sm = difflib.SequenceMatcher(None, old, new_lines, autojunk=False)
        return old, [op for op in sm.get_opcodes() if op[0] != "equal"]

    def test_set_skill_changes_one_line(self):
        s = self.open()
        s.set_skill("Fishing", level=30)
        self.quiet_save(s)
        old, ops = self._ops(self._written())
        self.assertEqual(len(ops), 1, ops)
        tag, i1, i2, j1, j2 = ops[0]
        self.assertEqual((tag, i2 - i1, j2 - j1), ("replace", 1, 1))
        self.assertEqual(old[i1], '\t\t\t\t\t"Xp": 2435')
        self.assertEqual(self._written()[j1], '\t\t\t\t\t"Xp": 5367')

    def _old_lines(self):
        return self.orig_bytes.decode("utf-8").split("\r\n")

    def test_add_item_is_pure_insert(self):
        s = self.open()
        s.add_item(NATURE_RUNE, count=500)  # slot 47
        self.quiet_save(s)
        new = self._written()
        old = self._old_lines()
        j = new.index('\t\t\t"47":')
        block = new[j:j + 7]
        self.assertEqual(new[:j] + new[j + 7:], old, "only the new 7-line entry may differ")
        self.assertEqual(new[j - 1], "\t\t\t},")
        self.assertEqual(block[1], "\t\t\t{")
        self.assertRegex(block[2], r'^\t\t\t\t"GUID": "[A-Za-z0-9_-]{22}",$')
        self.assertEqual(block[3], '\t\t\t\t"ItemData": "%s",' % NATURE_RUNE)
        self.assertEqual(block[4], '\t\t\t\t"Count": 500,')
        self.assertRegex(block[5], r'^\t\t\t\t"AddedToInventoryTimestamp": \d\.\d+e\+17$')
        self.assertEqual(block[6], "\t\t\t},")
        self.assertEqual(new[j + 7], '\t\t\t"72":')

    def test_set_count_and_remove_diff(self):
        s = self.open()
        s.set_count("Inventory", 40, 9999)
        s.remove("Inventory", 73)
        self.quiet_save(s)
        new = self._written()
        old = self._old_lines()
        i = old.index('\t\t\t"73":')
        expected = old[:i] + old[i + 7:]
        k = expected.index('\t\t\t\t"Count": 2838,')
        expected[k] = '\t\t\t\t"Count": 9999,'
        self.assertEqual(new, expected)

    def test_max_slot_index_line(self):
        s = self.open()
        s.add_item(NATURE_RUNE, slot=120)  # count 1: entry is 6 lines, no Count
        self.quiet_save(s)
        new = self._written()
        idx = new.index('\t\t\t"MaxSlotIndex": 120')
        self.assertEqual(new[idx - 1], "\t\t\t},")
        self.assertEqual(new[idx - 6], '\t\t\t"120":')
        self.assertEqual(new[idx - 7], "\t\t\t},")
        expected = self._old_lines()
        m = expected.index('\t\t\t"MaxSlotIndex": 113')
        expected[m] = '\t\t\t"MaxSlotIndex": 120'
        self.assertEqual(new[:idx - 6] + new[idx:], expected)

    def test_reload_round_trips(self):
        s = self.open()
        s.add_item(BRONZE_PICKAXE)
        s.repair()
        self.quiet_save(s)
        s2 = self.open()
        self.assertEqual(s2.to_bytes(), H.read_bytes(self.path))


# --------------------------------------------------------------------------
class DataFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = H.game_data()
        cls.save = dw_save.SaveFile(H.SAMPLE_SAVE, cls.game)

    def test_item_ids_unique_and_22_chars(self):
        ids = [it["id"] for it in self.game.items]
        self.assertEqual(len(ids), len(set(ids)))
        bad = [i for i in ids if not GUID_RE.match(i)]
        self.assertEqual(bad, [])

    def test_item_fields(self):
        tabs = set(dw_save.INVENTORY_TABS) | {None}
        for it in self.game.items:
            self.assertIn(it.get("inv_tab"), tabs, it["name"])
            md = it.get("max_durability")
            self.assertTrue(md is None or (isinstance(md, int) and md > 0), it["name"])

    def test_every_save_item_resolves(self):
        found = []

        def walk(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k == "ItemData" and isinstance(x, str):
                        found.append(x)
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)

        walk(self.save.root["GameProgress"])
        self.assertGreater(len(found), 40)
        missing = sorted({x for x in found if x not in self.game.items_by_id})
        self.assertEqual(missing, [])

    def test_xp_table(self):
        t = self.game.xp_for_level
        self.assertEqual(len(t), 99)
        self.assertEqual(t[0], 0)
        self.assertEqual(t[29], 5367)
        self.assertEqual(t[98], 1000000)
        self.assertTrue(all(a < b for a, b in zip(t, t[1:])))

    def test_skills(self):
        self.assertEqual(len(self.game.skills), 12)
        for s in self.save.progress["Skills"]["Skills"]:
            self.assertIn(s["Id"], self.game.skills_by_id)
            self.assertRegex(s["Id"], GUID_RE)

    def test_save_slot_layout(self):
        for sec in dw_save.SECTIONS:
            d = self.save.section(sec)
            keys = list(d)
            nums = [int(k) for k in keys if k.isdigit()]
            self.assertEqual(nums, sorted(nums))
            if "MaxSlotIndex" in d:
                self.assertEqual(keys[-1], "MaxSlotIndex")
                self.assertGreaterEqual(int(d["MaxSlotIndex"]), max(nums))


if __name__ == "__main__":
    unittest.main()
