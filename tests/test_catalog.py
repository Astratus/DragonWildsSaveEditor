"""Tests for dragonwilds_save_editor/catalog.py: the shared derivation rules, the self-check,
building from a (synthetic) installed game, the bundled catalog and the load order.

The build tests use the tiny fake install from tests/gamedata_fixture.py; the real-install
checks are in tests/test_gamedata.py (DW_TEST_GAME_DIR). Nothing here touches %LOCALAPPDATA%
or the network.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

try:
    from . import _helpers as H  # noqa: F401  (puts the project root on sys.path)
    from . import gamedata_fixture as F
except ImportError:
    import _helpers as H  # noqa: F401
    import gamedata_fixture as F

from dragonwilds_save_editor import catalog as C  # noqa: E402
from dragonwilds_save_editor.gamedata import schemas as S  # noqa: E402

NO_LIMITS = {"MIN_COUNTS": {}, "MIN_DECODED_SHARE": 0.5, "MIN_KEPT_IDS": 0.0}


class RuleTests(unittest.TestCase):
    def test_is_needed(self):
        yes = ("RSDragonwilds/Content/Gameplay/Items/ITEM_Rune_Air.uasset",
               "RSDragonwilds/Content/Gameplay/Items/DA_Consumabe_Mount.uasset",
               "RSDragonwilds/Content/Gameplay/BaseBuilding_New/BuildingPieces/T1/DA_T1_Beam.uasset",
               "RSDragonwilds/Content/Gameplay/Character/Player/PlayerHooks/FTUE/PH_FirstCampfire.uasset",
               "RSDragonwilds/Plugins/GameFeatures/X/Content/Gameplay/AI/Wolf/BP_AI_Wolf_Data.uasset",
               "RSDragonwilds/Content/Gameplay/Character/Player/Skills/SKILL_Farming.uasset")
        no = ("RSDragonwilds/Content/Art/ITEM_Thing.uasset",
              "RSDragonwilds/Content/Gameplay/Items/ITEM_Body_MeshData_Male.uasset",
              "RSDragonwilds/Content/Gameplay/BuildingPieces_DerivedData/BUILDPIECE_X.uasset",
              "RSDragonwilds/Content/Gameplay/Attributes/DA_Attribute_Speed.uasset",
              "RSDragonwilds/Content/Gameplay/Items/ITEM_Rune_Air.uexp",
              "Engine/Content/ITEM_X.uasset")
        for p in yes:
            self.assertTrue(C.is_needed(p), p)
        for p in no:
            self.assertFalse(C.is_needed(p), p)

    def test_inventory_tab(self):
        self.assertEqual(C.inventory_tab("Item", ["ItemFilter.Type.QuestItem"]), "quest")
        self.assertEqual(C.inventory_tab("ItemFilter.Type.Equipment.Ammo.Rune.Air", []), "rune")
        self.assertEqual(C.inventory_tab("", ["ItemFilter.Type.Equipment.Ammo.Rune"]), "rune")
        self.assertEqual(C.inventory_tab("Item.Equipment.Ammo.Arrow", None), "ammo")
        self.assertEqual(C.inventory_tab("Item.Equipment.Ammo.Bolt.X", []), "ammo")
        self.assertEqual(C.inventory_tab(None, []), "bag")

    def test_is_retired(self):
        self.assertTrue(C.is_retired("/Game/Items/Deleted/ITEM_X"))
        self.assertTrue(C.is_retired("/Game/Items/DeprecatedStuff/ITEM_X"))
        self.assertTrue(C.is_retired("/Game/Items/Quest/Depreciated/ITEM_X"))
        self.assertTrue(C.is_retired("/Game/Items/Test_Items/ITEM_X"))
        self.assertTrue(C.is_retired("/Game/Items/ITEM_X_TEST"))
        self.assertTrue(C.is_retired("/Game/Items/ITEM_X", soft_deleted=True))
        self.assertFalse(C.is_retired("/Game/Items/Testing/ITEM_Contest"))

    def test_make_item_and_hints(self):
        a = C.make_item("A" * 22, "[PH] Lantern", "ItemData", "x", "ITEM_Quest_Lantern", 1, None, "", [], False, "/Game/A")
        b = C.make_item("B" * 22, None, "FuelItemData", "res_ash_logs", "ITEM_Wood_Ash", 99, 0, "", [], False, "/Game/B")
        c = C.make_item("C" * 22, "lantern", "WearableEquipmentData", None, "ITEM_Lantern_Worn", 1, 300, "", [], True, "/Game/C")
        items = C.finish_items([c, b, a])
        self.assertEqual([i["name"] for i in items], ["Lantern", "lantern", "Res Ash Logs"])
        self.assertEqual((a["placeholder_name"], a["hint"]), (True, "Quest Lantern"))
        self.assertEqual((c["hint"], c["max_durability"], c["category"], c["retired"]), ("Lantern Worn", 300, "Armour", True))
        self.assertEqual((b["derived_name"], b["category"], b["max_durability"], b["hint"]), (True, "Fuel", None, None))

    def test_unlock_entries(self):
        out = {"name": "Blue Cape", "id": "I" * 22}
        e = C.recipe_entry("/Game/Vendor/RECIPE_Cape_Blue", "RECIPE_Cape_Blue", out, "SKILL_Artisan", "Blue Cape", False)
        self.assertEqual(e, {"name": "Blue Cape", "group": "Vendor/Artisan", "source": "/Game/Vendor/RECIPE_Cape_Blue",
                             "asset": "RECIPE_Cape_Blue", "output_item": "I" * 22, "vestige": "Blue Cape"})
        e = C.recipe_entry("/Game/Deleted/RECIPE_Old_Thing", "RECIPE_Old_Thing", None, None, None, True)
        self.assertEqual((e["name"], e["group"], e["retired"]), ("Old Thing", "Other", True))
        self.assertEqual(C.building_entry("/Game/BuildingPieces/Tier1/Beams/DA_T1_Beam", "DA_T1_Beam", None, False)["name"],
                         "T1 Beam")
        self.assertEqual(C.building_entry("/Game/BuildingPieces/Tier1/Beams/DA_T1_Beam", "DA_T1_Beam", "45° Beam", False)
                         ["group"], "Tier1/Beams")
        self.assertEqual(C.player_hook_entry("/Game/PlayerHooks/FTUE/PH_FirstBed", "PH_FirstBed", "PH_FirstBed", "ph_x"),
                         {"name": "FirstBed", "group": "FTUE", "source": "/Game/PlayerHooks/FTUE/PH_FirstBed",
                          "asset": "PH_FirstBed", "internal": "ph_x"})
        spell = C.spell_entry("/Game/S/USD_InfernalRod", "USD_InfernalRod", None, "T_Icon_Tag_Skill_Magic", None)
        self.assertEqual((spell["name"], spell["group"]), ("Infernal Rod", "Magic"))
        self.assertEqual(C.skill_entry("/Game/X/SKILL_Thieving", "SKILL_Thieving", None, 0, True),
                         {"name": "Thieving", "group": "Skill", "source": "/Game/X/SKILL_Thieving",
                          "asset": "SKILL_Thieving", "retired": True})
        p = C.perk_entry("/Game/P/PerkV2_Farming_Secateurs", "PerkV2_Farming_Secateurs", None, "SKILL_Farming", 42,
                         "perk_x", False)
        self.assertEqual((p["name"], p["group"], p["required_level"]), ("Farming Secateurs", "Farming", 42))
        self.assertEqual(C.journal_entry("/Game/UI/JournalData/Entries/Recipes/Armour/JOURNAL_A_B", "JOURNAL_A_B", None)
                         ["group"], "Recipes/Armour")
        ai = C.ai_entry("/Game/Gameplay/AI/Wolf/BP_AI_DireWolf_Data", "BP_AI_DireWolf_Data", None, "WolfAlpha")
        self.assertEqual((ai["name"], ai["group"], ai["ai_row"]), ("Dire Wolf", "Wolf", "WolfAlpha"))
        self.assertNotIn("ai_row", C.ai_entry("/Game/Gameplay/AI/BP_AI_X_Data", "BP_AI_X_Data", "X", "None"))

    def test_user_data_dir_is_pluggable(self):
        C.set_user_data_dir(lambda: "/tmp/x")
        try:
            self.assertEqual(C.catalog_dir(), os.path.join("/tmp/x", "catalog"))
        finally:
            C.set_user_data_dir(None)
        self.assertTrue(C.catalog_dir().endswith(os.path.join("DragonwildsSaveEditor", "catalog")))


def _good(n_items=1600):
    items = [C.make_item("%022d" % i, "Item %d" % i, "ItemData", None, "ITEM_%d" % i, 1, None, "", [], False, "/Game/I")
             for i in range(n_items)]
    for it in items:
        it.pop("_asset")
    sizes = {"SpellsUnlocked": 50, "JournalEntries": 1400, "KilledOnceAIs": 190, "RecipesUnlocked": 1270,
             "BuildingsUnlocked": 880, "PlayerHooksTriggered": 50, "SkillPerks": 190, "Skills": 15}
    unlocks = {sec: {"%s%016d" % (sec[:6].ljust(6, "x"), i): {"name": "x"} for i in range(n)}
               for sec, n in sizes.items()}
    info = {"asset_files": 5000, "fully_decoded": 4500, "unparsable_files": []}
    return items, unlocks, info


class SelfCheckTests(unittest.TestCase):
    def test_passes(self):
        items, unlocks, info = _good()
        self.assertEqual(C.self_check(items, unlocks, info), [])
        self.assertEqual(C.self_check(items, unlocks, info, (items, unlocks)), [])

    def test_low_decoded_share(self):
        items, unlocks, info = _good()
        info["fully_decoded"] = 3000
        self.assertIn("fully decoded", " ".join(C.self_check(items, unlocks, info)))
        info["asset_files"] = 0
        self.assertIn("no catalog assets", " ".join(C.self_check(items, unlocks, info)))

    def test_unreadable_packages(self):
        items, unlocks, info = _good()
        info["unparsable_files"] = ["x"] * 60
        self.assertIn("could not be read", " ".join(C.self_check(items, unlocks, info)))

    def test_bad_ids_names_and_counts(self):
        items, unlocks, info = _good()
        items[5]["id"] = "short"
        self.assertIn("22-character PersistenceID", " ".join(C.self_check(items, unlocks, info)))
        items, unlocks, info = _good()
        items[7]["id"] = items[6]["id"]
        self.assertIn("duplicate item ID", " ".join(C.self_check(items, unlocks, info)))
        items, unlocks, info = _good()
        items[3]["inv_tab"] = "pocket"
        self.assertIn("unknown tab", " ".join(C.self_check(items, unlocks, info)))
        items, unlocks, info = _good(n_items=200)
        self.assertIn("items: only 200 found", " ".join(C.self_check(items, unlocks, info)))
        items, unlocks, info = _good()
        del unlocks["Skills"]
        self.assertIn("unlock sections differ", " ".join(C.self_check(items, unlocks, info)))
        items, unlocks, info = _good()
        unlocks["Skills"]["bad"] = {"name": "x"}
        self.assertIn("Skills has an entry without a valid ID", " ".join(C.self_check(items, unlocks, info)))

    def test_against_reference(self):
        items, unlocks, info = _good()
        ref_items, ref_unlocks, _ = _good()
        new_items = [dict(i, id="N%021d" % n) for n, i in enumerate(items)]   # every ID changed
        probs = " ".join(C.self_check(new_items, unlocks, info, (ref_items, ref_unlocks)))
        self.assertIn("IDs were found again", probs)
        small = (ref_items[:100], ref_unlocks)
        self.assertIn("implausibly many", " ".join(C.self_check(items, unlocks, info, small)))


class _GameCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dwcat_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root, schemas_path = F.make_game(os.path.join(self.tmp, "game"))
        patcher = mock.patch.object(S, "default_path", lambda: schemas_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.out = os.path.join(self.tmp, "user", "catalog")


class BuildTests(_GameCase):
    def test_refused_when_self_check_fails(self):
        with self.assertRaises(C.SelfCheckError) as cm:
            C.build(game_dir=self.root, out_dir=self.out)
        self.assertIn("items: only 4 found", str(cm.exception))
        self.assertFalse(os.path.exists(self.out))   # nothing written

    def test_build_writes_user_catalog(self):
        stages = []
        with mock.patch.multiple(C, **NO_LIMITS):
            info = C.build(game_dir=os.path.join(self.root, "RSDragonwilds"), out_dir=self.out,
                           progress=lambda *a: stages.append(a))
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["build_info.json", "items.csv", "items.json", "items_ai.tsv", "unlock_names.json"])
        self.assertEqual((info["source"], info["game_version"], info["generator_version"], info["self_check"]),
                         ("installed game", "9.9.9.9", C.GENERATOR_VERSION, "passed"))
        self.assertEqual(info["counts"]["items"], 4)
        self.assertIn(("check", 1, 1), stages)
        self.assertIn(("decode", 5, 5), stages)
        text = json.dumps(C.catalog_status(self.out)) + open(os.path.join(self.out, "items.json"), encoding="utf-8").read()
        self.assertNotIn(self.tmp, text)
        self.assertNotIn(self.tmp.replace("\\", "\\\\"), text)
        items = {i["id"]: i for i in C.load_catalog("items", out_dir=self.out)}
        self.assertEqual(items[F.ITEM_IDS["rune"]]["inv_tab"], "rune")

    def test_game_not_found(self):
        with self.assertRaises(C.GameNotFoundError):
            C.build(game_dir=self.tmp, out_dir=self.out)

    def test_cli_build_and_detect_errors(self):
        with mock.patch.multiple(C, **NO_LIMITS):
            self.assertEqual(C.main(["build", "--game-dir", self.root, "--out", self.out]), 0)
        self.assertTrue(C.is_built(self.out))
        self.assertEqual(C.main(["build", "--game-dir", self.tmp, "--out", self.out]), 2)


class BundledCatalogTests(unittest.TestCase):
    """The catalog shipped in dragonwilds_save_editor/data/catalog."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dwcat_b_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.empty_user = os.path.join(self.tmp, "user")

    def test_verifies(self):
        info = C.verify_catalog()
        self.assertEqual((info["mode"], info["source"], info["format"], info["generator"]),
                         ("bundled", "installed game", C.CATALOG_FORMAT, C.GENERATOR))
        self.assertRegex(info["game_version"], r"^\d+\.\d+\.\d+\.\d+$")
        self.assertEqual(info["generator_version"], C.GENERATOR_VERSION)
        self.assertRegex(info["built_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertGreater(info["fully_decoded"] / info["asset_files"], C.MIN_DECODED_SHARE)

    def test_loads_without_user_catalog(self):
        items = C.load_catalog("items", out_dir=self.empty_user)
        self.assertTrue(1600 <= len(items) <= 1700, len(items))
        by_id = {i["id"]: i for i in items}
        arrow = by_id["SLm1L0ZdMPSDkRmrf0eHsA"]
        self.assertEqual((arrow["name"], arrow["max_stack"], arrow["inv_tab"]), ("Adamant Fire Arrow", 999, "ammo"))
        self.assertEqual(by_id["iKbF7k2XvufGqqyg5rK-vQ"]["name"], "Nature Rune")
        self.assertEqual(by_id["Dvo6TE2d7YNnoni8XbKYzw"]["inv_tab"], "rune")
        names = C.load_catalog("unlock_names", out_dir=self.empty_user)
        self.assertEqual(set(names), set(C.UNLOCK_SECTIONS))
        self.assertEqual(len(names["KilledOnceAIs"]), 197)
        self.assertGreaterEqual(len(names["SkillPerks"]), 150)
        self.assertEqual(names["SkillPerks"]["cQfN1EsBDwTU16m3eFSDKA"]["name"], "Iron Secateurs")
        self.assertGreaterEqual(len(names["RecipesUnlocked"]), 1200)
        self.assertEqual(C.active_status(self.empty_user)["origin"], "bundled")

    def test_sources_are_package_paths(self):
        for it in C.load_catalog("items", out_dir=self.empty_user):
            self.assertRegex(it["source"], r"^/[A-Za-z0-9_]+/[^:\\]+$")
        for table in C.load_catalog("unlock_names", out_dir=self.empty_user).values():
            for e in table.values():
                self.assertRegex(e["source"], r"^/[A-Za-z0-9_]+/[^:\\]+$")

    def test_no_local_paths_or_extra_files(self):
        folder = C.bundled_dir()
        self.assertEqual(sorted(os.listdir(folder)), ["build_info.json", "items.json", "unlock_names.json"])
        for name in os.listdir(folder):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                text = f.read()
            self.assertNotRegex(text, r"[A-Za-z]:[\\/]|\\\\|Users[\\/]|AppData|RSDWArchive", name)
        with open(os.path.join(folder, C.BUILD_INFO), encoding="utf-8") as f:
            info = json.load(f)
        for key in ("seconds", "unparsable_files", "partial_files", "commit", "dump_version"):
            self.assertNotIn(key, info)

    def test_rewrite_is_byte_identical(self):
        """Re-serialising the bundled data reproduces the shipped files exactly (deterministic
        output; the recorded date is kept when the data is unchanged)."""
        src = C.bundled_dir()
        dest = os.path.join(self.tmp, "bundle")
        os.makedirs(dest)
        shutil.copyfile(os.path.join(src, C.BUILD_INFO), os.path.join(dest, C.BUILD_INFO))
        items = C.load_catalog("items", out_dir=self.empty_user)
        names = C.load_catalog("unlock_names", out_dir=self.empty_user)
        info = C.verify_catalog()
        C.write_bundle(dest, list(reversed(items)), names, info)
        for name in os.listdir(src):
            with open(os.path.join(src, name), "rb") as a, open(os.path.join(dest, name), "rb") as b:
                self.assertEqual(a.read(), b.read(), name)

    def test_verify_detects_damage(self):
        dest = os.path.join(self.tmp, "bundle")
        shutil.copytree(C.bundled_dir(), dest)
        C.verify_catalog(dest)
        with open(os.path.join(dest, "items.json"), "r+b") as f:
            f.seek(10)
            f.write(b"#")
        with self.assertRaises(C.CatalogError) as cm:
            C.verify_catalog(dest)
        self.assertIn("items.json", str(cm.exception))

    def test_compare_with_itself(self):
        items = C.load_catalog("items", out_dir=self.empty_user)
        names = C.load_catalog("unlock_names", out_dir=self.empty_user)
        rep = C.compare(items, names, items, names)
        self.assertEqual(rep["items"]["matched_ids"], len(items))
        self.assertTrue(all(f["differ"] == 0 for f in rep["items"]["fields"].values()))
        self.assertIn("items: built", C.compare_text(rep))


class LoadOrderTests(_GameCase):
    """User-built catalog vs the bundled one."""

    def setUp(self):
        super().setUp()
        with mock.patch.multiple(C, **NO_LIMITS):
            C.build(game_dir=self.root, out_dir=self.out)          # the 4-item fixture build
            items, unlocks, info = C.derive_from_game(self.root)
        for table in unlocks.values():            # verify_catalog wants every section filled
            table.setdefault("Z" * 22, {"name": "Placeholder", "group": "x", "source": "/Game/X", "asset": "X"})
        self.bundled = os.path.join(self.tmp, "bundled")
        C.write_bundle(self.bundled, items[:3], unlocks, info, built_date="2026-01-02")
        C.set_bundled_dir(lambda: self.bundled)
        self.addCleanup(C.set_bundled_dir, None)
        self.derived = (items, unlocks, info)

    def _set_generator(self, version):
        info = C.catalog_status(self.out)
        info["generator_version"] = version
        with open(os.path.join(self.out, C.BUILD_INFO), "w", encoding="utf-8") as f:
            json.dump(info, f)

    def test_compatible_user_build_wins(self):
        self.assertEqual(len(C.load_catalog("items", out_dir=self.out)), 4)
        self.assertEqual(C.active_status(self.out)["origin"], "user")

    def test_older_user_build_is_ignored(self):
        self._set_generator(1)     # a catalog built from the RSDWArchive dump by an older version
        self.assertEqual(len(C.load_catalog("items", out_dir=self.out)), 3)
        st = C.active_status(self.out)
        self.assertEqual((st["origin"], st["user_build_ignored"]), ("bundled", True))

    def test_no_user_build(self):
        empty = os.path.join(self.tmp, "none")
        self.assertEqual(len(C.load_catalog("items", out_dir=empty)), 3)
        self.assertEqual(C.active_status(empty)["origin"], "bundled")
        self.assertFalse(C.active_status(empty)["user_build_ignored"])

    def test_reset_to_bundled(self):
        removed = C.reset_to_bundled(self.out)
        self.assertEqual(len(removed), 5)
        self.assertFalse(C.is_built(self.out))
        self.assertEqual(os.listdir(self.out), [])
        self.assertEqual(len(C.load_catalog("items", out_dir=self.out)), 3)
        self.assertEqual(C.reset_to_bundled(self.out), [])

    def test_bundle_is_deterministic_and_keeps_date(self):
        with open(os.path.join(self.bundled, "items.json"), "rb") as f:
            first = f.read()
        self.assertTrue(first.startswith(b"[\n{") and first.endswith(b"}\n]\n") and b"\r" not in first)
        items, unlocks, info = self.derived
        info2 = C.write_bundle(self.bundled, items[:3], unlocks, info)
        self.assertEqual(info2["built_at"], "2026-01-02")            # unchanged data keeps the date
        with open(os.path.join(self.bundled, "items.json"), "rb") as f:
            self.assertEqual(f.read(), first)
        info3 = C.write_bundle(self.bundled, items[:2], unlocks, info)
        self.assertNotEqual(info3["built_at"], "2026-01-02")
        self.assertEqual(C.verify_catalog(self.bundled, min_items=1)["counts"]["items"], 2)
        self.assertEqual((info3["game_version"], info3["source"]), ("9.9.9.9", "installed game"))

    def test_bundle_refuses_unparsable(self):
        items, unlocks, info = self.derived
        with self.assertRaises(C.CatalogError):
            C.write_bundle(os.path.join(self.tmp, "b2"), items, unlocks, dict(info, unparsable_files=["/Game/X: bad"]))


class BuildCatalogScriptTests(_GameCase):
    def test_regenerate_check_and_verify(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_catalog", os.path.join(H.ROOT, "packaging", "build_catalog.py"))
        bc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bc)
        dest = os.path.join(self.tmp, "bundle")
        with mock.patch.multiple(C, **NO_LIMITS), mock.patch.object(C, "verify_catalog",
                                                                     lambda f=None: C.__dict__["_read_info"](f)):
            self.assertEqual(bc.main(["--game-dir", self.root, "--out", dest, "--date", "2026-02-03"]), 0)
            self.assertEqual(bc.main(["--check", "--game-dir", self.root, "--out", dest]), 0)
            with open(os.path.join(dest, "items.json"), "ab") as f:
                f.write(b" ")
            self.assertEqual(bc.main(["--check", "--game-dir", self.root, "--out", dest]), 1)
        self.assertEqual(bc.main(["--game-dir", self.tmp, "--out", dest]), 2)
        with open(os.path.join(dest, C.BUILD_INFO), encoding="utf-8") as f:
            info = json.load(f)
        self.assertEqual((info["built_at"], info["game_version"]), ("2026-02-03", "9.9.9.9"))
        self.assertNotIn(self.tmp.replace("\\", "\\\\"), json.dumps(info))


if __name__ == "__main__":
    unittest.main()
