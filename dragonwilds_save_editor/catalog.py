"""The item and unlock-name catalogs: a bundled copy, plus an optional rebuild from the game.

The editor ships its own catalog in ``dragonwilds_save_editor/data/catalog/`` (items.json,
unlock_names.json, build_info.json). It is generated from an installed copy of the game by the
``gamedata`` package (a read-only reader for the game's IoStore containers), with the
classification rules in this module; see docs/research/catalog_build.md.
``packaging/build_catalog.py --game-dir <install>`` regenerates the bundled copy.

Optionally ("Update item catalog" in the GUI, ``dwsave catalog build``), the same build runs on
the player's machine from the player's own installed game (found automatically, or given with
--game-dir) and writes the result to %LOCALAPPDATA%\\DragonwildsSaveEditor\\catalog. The build
checks itself (see self_check) and is only written when the check passes. A compatible
user-built catalog is used instead of the bundled one; ``reset_to_bundled()`` removes it again.

Stdlib only. No network connections: the game's files are only read, never written or locked.

    python -m dragonwilds_save_editor.catalog status     # which catalog is in use
    python -m dragonwilds_save_editor.catalog detect     # where the game is installed
    python -m dragonwilds_save_editor.catalog build [--game-dir FOLDER]   # rebuild from the game
    python -m dragonwilds_save_editor.catalog reset      # back to the bundled catalog
    python -m dragonwilds_save_editor.catalog verify     # check the bundled files
    python -m dragonwilds_save_editor.catalog compare --old FOLDER   # vs another catalog
    (``dwsave catalog ...`` runs the same commands.)

Library:
    from dragonwilds_save_editor import catalog
    items = catalog.load_catalog("items")          # list of item dicts (id, name, category, ...)
    names = catalog.load_catalog("unlock_names")   # {section: {id: {name, group, ...}}}
    catalog.active_status()                        # build info + "origin": "user" | "bundled"
    catalog.build(game_dir=None, progress=lambda stage, done, total: ...)
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time

from . import paths

CATALOG_FORMAT = 1
# Revision of the derivation (reader + rules). Bump it when a change alters the output, and
# regenerate the bundled catalog (packaging/build_catalog.py). A user-built catalog made by an
# older generator is ignored in favour of the bundled one. 1 = built from the RSDWArchive dump
# (up to 0.1.0 pre-releases); 2 = built from the installed game.
GENERATOR_VERSION = 2
GENERATOR = "dragonwilds_save_editor.gamedata"
SOURCE = "installed game"

KINDS = ("items", "unlock_names")
UNLOCK_SECTIONS = ("SpellsUnlocked", "JournalEntries", "KilledOnceAIs",
                   "RecipesUnlocked", "BuildingsUnlocked", "PlayerHooksTriggered", "SkillPerks",
                   "Skills")
# SkillPerks is a name table only (no save list of its own): perk IDs show up in the save's
# Progress.SpellsNew badge list (e.g. Iron Secateurs). It is kept apart from SpellsUnlocked so a
# perk is never offered as a lockable spell; look it up when naming SpellsNew entries.
# Skills names the IDs in GameProgress.Skills.Skills (also a name table, not an unlock list).


class CatalogError(Exception):
    """Base class for catalog problems."""


class CatalogNotBuiltError(CatalogError):
    """No usable catalog: neither a user-built one nor the bundled one (damaged install)."""


class GameNotFoundError(CatalogError):
    """The game's installation folder could not be found (or is not a game folder)."""


class SelfCheckError(CatalogError):
    """A build from the game did not pass its self-check; nothing was written."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("The catalog built from the game failed its self-check, so the current "
                         "catalog was kept:\n  - " + "\n  - ".join(self.problems))


# ---------------------------------------------------------------------------
# Paths (pluggable: tests point the catalog at a temp folder with set_user_data_dir)
# ---------------------------------------------------------------------------

def default_user_data_dir():
    """%LOCALAPPDATA%\\DragonwildsSaveEditor: the same folder as paths.user_data_dir(), but
    not created here (a status check must not leave folders behind)."""
    return os.path.join(paths._local_appdata(), paths.APP_DIR_NAME)


_user_data_dir = default_user_data_dir


def set_user_data_dir(func):
    """Use `func()` (e.g. paths.user_data_dir) as the per-user data root. None restores the default."""
    global _user_data_dir
    _user_data_dir = func or default_user_data_dir


def catalog_dir():
    """%LOCALAPPDATA%\\DragonwildsSaveEditor\\catalog (a user-built catalog lives here)."""
    return os.path.join(_user_data_dir(), "catalog")


def built_path(kind):
    return os.path.join(catalog_dir(), _FILE_FOR_KIND[kind])


_FILE_FOR_KIND = {"items": "items.json", "unlock_names": "unlock_names.json"}
BUILD_INFO = "build_info.json"
BUNDLED_FILES = ("items.json", "unlock_names.json")


def default_bundled_dir():
    """dragonwilds_save_editor/data/catalog (read-only package data; also inside the exe)."""
    return paths.resource_path("data", "catalog")


_bundled_dir = default_bundled_dir


def set_bundled_dir(func):
    """Use `func()` as the bundled catalog folder (tests). None restores the default."""
    global _bundled_dir
    _bundled_dir = func or default_bundled_dir


def bundled_dir():
    return _bundled_dir()


# ---------------------------------------------------------------------------
# Derivation rules (shared by every catalog build; the gamedata reader supplies the values)
# ---------------------------------------------------------------------------

_RE_BUILD_DA = re.compile(r"^(DA_T\d|DA_BaseBuilding|DA_FarmPlot|DA_BuildPiece)")


def is_needed(rel):
    """True if the game asset at container path `rel` ('RSDragonwilds/...uasset') feeds the catalog."""
    if not rel.startswith("RSDragonwilds/") or not rel.endswith(".uasset"):
        return False
    base = rel.rsplit("/", 1)[-1][:-len(".uasset")]
    if "/Art/" in rel or "/Audio/" in rel:
        return False
    if base.startswith("ITEM_"):
        return "_MeshData" not in base
    if base.startswith(("DA_Consumab", "DA_Recipe", "RECIPE_", "USD_", "JOURNAL_", "PerkV2_", "SKILL_")):
        return True  # DA_Consumabe_* is a typo used by the mount unlockers
    if base.startswith("BUILDPIECE_") or (_RE_BUILD_DA.match(base) and "/Gameplay/" in rel):
        return "DerivedData" not in rel
    if "/PlayerHooks/" in rel and (base.startswith("PH_") or base.startswith("BP_")):
        return True
    if "/Gameplay/AI/" in rel and (base == "DA_AI_Data" or (base.startswith("BP_") and "_Data" in base)):
        return True
    return False


def humanize(s, camel=False):
    """'armour_t4_cape' -> 'Armour T4 Cape'; with camel=True also 'InfernalRod' -> 'Infernal Rod'."""
    if camel:
        s = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    s = re.sub(r"_+", " ", s).strip()
    return " ".join(w[:1].upper() + w[1:] for w in s.split())


def _base(path):
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


_RETIRED_DIR = re.compile(r"^(deleted|depreciated|deprecated)[a-z]*$|(^|_)test($|_)", re.I)


def is_retired(path, soft_deleted=False):
    """Retired: flagged bSoftDeleted, in a Deleted/Deprecated/Test folder, or named *_TEST_*."""
    if soft_deleted:
        return True
    parts = path.split("/")
    if any(_RETIRED_DIR.search(p) for p in parts[:-1]):
        return True
    return bool(re.search(r"(^|_)(TEST|Test|DEPRECATED)(_|$)", _base(path)))


# Asset class -> category label (the labels the editor has always used).
ITEM_CATEGORY_BY_TYPE = {
    "ItemData": "Resource",
    "WearableEquipmentData": "Armour",
    "HeldEquipmentData": "Weapon/Tool",
    "FishingRodHeldEquipmentData": "Weapon/Tool",
    "HarvestToolEquipmentData": "Weapon/Tool",
    "HeldContainerEquipmentData": "Weapon/Tool",
    "SpadeToolEquipmentData": "Weapon/Tool",
    "ShieldData": "Shield",
    "TrinketItemData": "Jewellery",
    "RangedAmmoData": "Ammo",
    "FishingBaitAmmoData": "Ammo",
    "MagicAmmoData": "Ammo",
    "SeedHeldEquipmentData": "Seed",
    "HeldTreeSeedData": "Seed",
    "FuelItemData": "Fuel",
    "WhetstoneItemData": "Whetstone",
    "JournalItemData": "Other",
    "ConsumableMountUnlocker": "Mount",
    "BP_Consumables_Food_C": "Food",
    "BP_Consumables_Drink_C": "Drink",
    "BP_Consumables_Potion_C": "Potion",
    "BP_Consumables_ItemEmitter_C": "Pack",
    "BP_Consumables_SkillTome_C": "Tome",
    "BP_Consumables_Plan_Base_C": "Plan",
    "BP_Consumables_RecipeUnlocker2_C": "Pattern",
}


def is_item_type(t):
    return (t in ITEM_CATEGORY_BY_TYPE or t.startswith("BP_Consumables_")
            or t.endswith(("ItemData", "EquipmentData", "AmmoData")))


def inventory_tab(category, filters):
    """Inventory tab from the item's Category tag and ItemFilterTags (rule documented in
    docs/research/catalog_build.md)."""
    category = category or ""
    filters = list(filters or [])
    if "ItemFilter.Type.QuestItem" in filters:
        return "quest"
    if any(t.startswith("ItemFilter.Type.Equipment.Ammo.Rune") for t in filters + [category]):
        return "rune"
    if category.startswith(("Item.Equipment.Ammo.Arrow", "Item.Equipment.Ammo.Bolt")):
        return "ammo"
    return "bag"


_ITEM_PREFIX = re.compile(r"^(ITEM|DA_Consumab[le]+)_")


def make_item(pid, name, cls, internal, asset, max_stack, durability, category_tag, filters,
              retired, source):
    """One items.json entry (plus '_asset' for finish_items and recipe outputs)."""
    derived = not name
    if derived:
        name = humanize(internal or _ITEM_PREFIX.sub("", asset))
    placeholder = name.startswith("[PH]")
    if placeholder:
        name = name[4:].strip()
    return {
        "id": pid,
        "name": name,
        "category": ITEM_CATEGORY_BY_TYPE.get(cls, "Other"),
        "hint": None,
        "max_durability": durability if isinstance(durability, int) and durability > 0 else None,
        "max_stack": max_stack,
        "inv_tab": inventory_tab(category_tag, filters),
        "retired": bool(retired),
        "placeholder_name": placeholder,
        "derived_name": derived,
        "source": source,
        "_asset": asset,
    }


def finish_items(items):
    """Give items that share a display name a 'hint' (from the asset name); sort by (name, id)."""
    by_name = {}
    for it in items:
        by_name.setdefault(it["name"].lower(), []).append(it)
    for group in by_name.values():
        if len(group) > 1:
            for it in group:
                it["hint"] = humanize(_ITEM_PREFIX.sub("", it["_asset"]))
    items.sort(key=lambda it: (it["name"].lower(), it["id"]))
    return items


def group_from_dir(path, anchor):
    """Folders between `anchor` and the file, e.g. 'Tier1_Brynmoor/Beams'."""
    parts = path.split("/")[:-1]
    if anchor in parts:
        rest = parts[len(parts) - parts[::-1].index(anchor):]
        if rest:
            return "/".join(rest)
    return "/".join(parts[-2:])


def _entry(name, group, path, asset, **extra):
    e = {"name": name, "group": group, "source": path, "asset": asset}
    e.update({k: v for k, v in extra.items() if v not in (None, False, "")})
    return e


def recipe_entry(path, asset, out_item, skill_asset, vestige, retired):
    group = skill_asset[len("SKILL_"):] if skill_asset and skill_asset.startswith("SKILL_") else "Other"
    if "/Vendor" in path:
        group = "Vendor/" + group
    name = out_item["name"] if out_item else humanize(re.sub(r"^(RECIPE|DA_Recipe)_", "", asset))
    return _entry(name, group, path, asset, output_item=out_item["id"] if out_item else None,
                  vestige=vestige, retired=bool(retired))


def building_entry(path, asset, display_name, retired):
    name = display_name or humanize(re.sub(r"^(BUILDPIECE|DA_BaseBuilding|DA)_", "", asset), camel=True)
    return _entry(name, group_from_dir(path, "BuildingPieces"), path, asset, retired=bool(retired))


def player_hook_entry(path, asset, export_name, internal):
    name = asset[3:] if asset.startswith("PH_") else humanize(export_name)
    return _entry(name, "FTUE" if "/FTUE/" in path else "PlayerHook", path, asset, internal=internal)


def spell_entry(path, asset, display_name, icon, internal):
    m = re.search(r"T_Icon_Tag_Skill_([A-Za-z]+)", icon or "")
    return _entry(display_name or humanize(asset[4:], camel=True), m.group(1) if m else "Spell",
                  path, asset, internal=internal)


def skill_entry(path, asset, display_name, max_level, retired):
    return _entry(display_name or asset[len("SKILL_"):], "Skill", path, asset,
                  max_level=max_level or None, retired=bool(retired))


def perk_entry(path, asset, display_name, skill_asset, required_level, internal, retired):
    skill_asset = skill_asset or ""
    e = _entry(display_name or humanize(asset[len("PerkV2_"):], camel=True),
               skill_asset[len("SKILL_"):] if skill_asset.startswith("SKILL_") else "Perk",
               path, asset, internal=internal, retired=bool(retired))
    if required_level is not None:
        e["required_level"] = required_level
    return e


def journal_entry(path, asset, display_name):
    return _entry(display_name or humanize(asset[len("JOURNAL_"):]),
                  group_from_dir(path, "Entries") if "/Entries/" in path else "Category", path, asset)


def ai_entry(path, asset, display_name, row):
    short = re.sub(r"^BP_AI_|_Data$", "", asset)
    parts = path.split("/")
    i = parts.index("AI")
    return _entry(display_name or humanize(short, camel=True),
                  parts[i + 1] if i + 2 < len(parts) else "AI", path, asset,
                  ai_row=row if row and row != "None" else None)


# ---------------------------------------------------------------------------
# Build from the installed game
# ---------------------------------------------------------------------------

def catalog_counts(items, unlocks):
    return dict({"items": len(items)}, **{k: len(v) for k, v in unlocks.items()})


# Self-check limits. A build that misses them is not written (the current catalog is kept).
MIN_DECODED_SHARE = 0.80      # exports decoded completely by their class schema
MAX_UNPARSABLE_SHARE = 0.01   # packages that could not be read at all
MIN_COUNTS = {"items": 1500, "SpellsUnlocked": 30, "JournalEntries": 1000, "KilledOnceAIs": 100,
              "RecipesUnlocked": 1000, "BuildingsUnlocked": 600, "PlayerHooksTriggered": 30,
              "SkillPerks": 120, "Skills": 10}
MAX_COUNT_FACTOR = 3.0        # no section may grow beyond 3x the reference catalog
MIN_KEPT_IDS = 0.90           # share of the reference catalog's IDs a new build must still have
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")


def self_check(items, unlocks, info, reference=None):
    """Problems (a list of strings; empty = passed) with a catalog built from the game.

    Checks: the share of exports fully decoded and of unreadable packages; every item and unlock
    has a unique 22-character PersistenceID, a name, a valid tab and stack size; every count is
    plausible (above MIN_COUNTS and, against ``reference`` = (items, unlocks) of the catalog in
    use, not above MAX_COUNT_FACTOR times its size and keeping MIN_KEPT_IDS of its IDs)."""
    problems = []
    total = info.get("asset_files") or 0
    full = info.get("fully_decoded") or 0
    if not total:
        problems.append("no catalog assets were found in the game's data")
    else:
        if full / total < MIN_DECODED_SHARE:
            problems.append("only %d of %d game assets (%.0f%%) were fully decoded; at least %.0f%% "
                            "are needed (a game update may have changed the data layout)"
                            % (full, total, 100.0 * full / total, 100 * MIN_DECODED_SHARE))
        bad = len(info.get("unparsable_files") or [])
        if bad / total > MAX_UNPARSABLE_SHARE:
            problems.append("%d of %d game assets could not be read" % (bad, total))
    ids = set()
    for it in items:
        if not _ID_RE.match(str(it.get("id"))):
            problems.append("item without a valid 22-character PersistenceID: %r" % it.get("name"))
            break
        if it["id"] in ids:
            problems.append("duplicate item ID %s" % it["id"])
            break
        ids.add(it["id"])
        if not it.get("name") or it.get("inv_tab") not in _TABS \
                or not isinstance(it.get("max_stack"), int) or it["max_stack"] < 1:
            problems.append("item %s (%s) has an empty name, unknown tab or bad stack size"
                            % (it["id"], it.get("name")))
            break
    if set(unlocks) != set(UNLOCK_SECTIONS):
        problems.append("unlock sections differ from %s" % ", ".join(UNLOCK_SECTIONS))
    for sec, table in unlocks.items():
        if any(not _ID_RE.match(i) or not (e or {}).get("name") for i, e in table.items()):
            problems.append("%s has an entry without a valid ID or name" % sec)
    counts = catalog_counts(items, unlocks)
    for key, low in MIN_COUNTS.items():
        if counts.get(key, 0) < low:
            problems.append("%s: only %d found (expected at least %d)" % (key, counts.get(key, 0), low))
    if reference:
        ref_items, ref_unlocks = reference
        ref_counts = catalog_counts(ref_items, ref_unlocks)
        for key, n in ref_counts.items():
            if n and counts.get(key, 0) > MAX_COUNT_FACTOR * n:
                problems.append("%s: %d found, implausibly many (the current catalog has %d)"
                                % (key, counts[key], n))
        ref_ids = {i["id"] for i in ref_items}
        for t in ref_unlocks.values():
            ref_ids.update(t)
        new_ids = set(ids)
        for t in unlocks.values():
            new_ids.update(t)
        if ref_ids:
            kept = len(ref_ids & new_ids) / len(ref_ids)
            if kept < MIN_KEPT_IDS:
                problems.append("only %.0f%% of the current catalog's IDs were found again "
                                "(expected at least %.0f%%)" % (100 * kept, 100 * MIN_KEPT_IDS))
    return problems


def _reference_catalog(out_dir=None):
    """(items, unlocks) of the catalog currently in use, or None."""
    try:
        return load_catalog("items", out_dir), load_catalog("unlock_names", out_dir)
    except CatalogError:
        return None


def derive_from_game(game_dir=None, progress=None):
    """Find the game (``game_dir`` = install root, its RSDragonwilds folder or its Paks folder;
    None = detect it) and derive the catalog from it. Returns (items, unlocks, info); ``info``
    never holds a local path. Raises GameNotFoundError."""
    from .gamedata import derive, install
    paks = install.find_paks_dir(game_dir)
    items, unlocks, info = derive.derive_from_install(paks, progress=progress)
    info = dict(info, format=CATALOG_FORMAT, generator=GENERATOR, generator_version=GENERATOR_VERSION,
                source=SOURCE, built_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                counts=catalog_counts(items, unlocks))
    return items, unlocks, info


def build(game_dir=None, progress=None, out_dir=None, reference=None):
    """Rebuild the catalog from the installed game and, if it passes self_check() (against
    ``reference``, default: the catalog in use), write it to ``out_dir`` (default: the user data
    folder, where it is used instead of the bundled one). Returns the build info.
    Raises GameNotFoundError or SelfCheckError (then nothing is written)."""
    items, unlocks, info = derive_from_game(game_dir, progress)
    if progress:
        progress("check", 0, 1)
    problems = self_check(items, unlocks, info, reference or _reference_catalog(out_dir))
    if problems:
        raise SelfCheckError(problems)
    if progress:
        progress("check", 1, 1)
    info = {k: v for k, v in info.items() if k != "partial_files"}
    info["self_check"] = "passed"
    info["unparsable_files"] = len(info.get("unparsable_files") or [])
    write_catalog(out_dir or catalog_dir(), items, unlocks, info)
    return info


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_catalog(out_dir, items, unlocks, info):
    def dump(name, obj, **kw):
        _atomic_write(os.path.join(out_dir, name), json.dumps(obj, ensure_ascii=False, **kw).encode("utf-8"))

    dump("items.json", items, separators=(",", ":"))
    dump("unlock_names.json", unlocks, indent=1)
    _atomic_write(os.path.join(out_dir, "items.csv"), items_csv(items).encode("utf-8"))
    _atomic_write(os.path.join(out_dir, "items_ai.tsv"), items_tsv(items).encode("utf-8"))
    dump(BUILD_INFO, info, indent=1)  # written last: its presence marks a complete build


_CSV_COLS = ("id", "name", "category", "hint", "max_durability", "max_stack", "inv_tab",
             "retired", "placeholder_name", "derived_name", "source")


def items_csv(items):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\n")
    w.writerow(_CSV_COLS)
    for it in items:
        w.writerow(["" if it.get(c) is None else (str(it[c]) if isinstance(it[c], (bool, int, float)) else it[c])
                    for c in _CSV_COLS])
    return buf.getvalue()


def items_tsv(items):
    lines = ["id\tname\tcategory\tmax_stack\tnotes"]
    for it in items:
        notes = ["tab=%s" % it["inv_tab"]]
        if it.get("max_durability"):
            notes.append("dur=%s" % it["max_durability"])
        if it.get("hint"):
            notes.append("hint=%s" % it["hint"])
        notes += [k for k in ("retired", "placeholder_name", "derived_name") if it.get(k)]
        lines.append("\t".join([it["id"], it["name"], it["category"], str(it["max_stack"]), ";".join(notes)]))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Bundled catalog (shipped in the package; regenerated by packaging/build_catalog.py)
# ---------------------------------------------------------------------------

def _line(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def bundle_items_text(items):
    """items.json for the bundle: a JSON array, one item per line (keys sorted), LF, final
    newline. Items are ordered by (name, id), as derive_items() returns them."""
    items = sorted(items, key=lambda it: (it["name"].lower(), it["id"]))
    return "[\n" + ",\n".join(_line(it) for it in items) + "\n]\n"


def bundle_unlocks_text(unlocks):
    """unlock_names.json for the bundle: sections and IDs sorted, one entry per line."""
    parts = []
    for sec in sorted(unlocks):
        table = unlocks[sec]
        body = ",\n".join("%s:%s" % (_line(i), _line(table[i])) for i in sorted(table))
        parts.append("%s:{\n%s\n}" % (_line(sec), body) if body else "%s:{}" % _line(sec))
    return "{\n" + ",\n".join(parts) + "\n}\n"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


# Fields of a build's info that the bundled build_info.json keeps (no timings, no local data).
_BUNDLE_INFO_KEYS = ("format", "generator", "generator_version", "source", "game_version",
                     "asset_files", "asset_bytes", "fully_decoded", "partly_decoded")


def write_bundle(dest, items, unlocks, info, built_date=None):
    """Write the bundled catalog (items.json, unlock_names.json, build_info.json) to `dest`.

    Deterministic: the same inputs give byte-identical files. ``built_date`` (YYYY-MM-DD)
    defaults to the date already recorded in dest/build_info.json when the data files are
    unchanged, else today. Returns the new build info."""
    if info.get("unparsable_files"):
        raise CatalogError("Some game assets could not be parsed: %s" % ", ".join(info["unparsable_files"]))
    data = {"items.json": bundle_items_text(items).encode("utf-8"),
            "unlock_names.json": bundle_unlocks_text(unlocks).encode("utf-8")}
    files = {name: {"bytes": len(b), "sha256": _sha256(b)} for name, b in sorted(data.items())}
    old = _read_info(dest) or {}
    if not built_date:
        built_date = old.get("built_at") if old.get("files") == files else None
        built_date = built_date or time.strftime("%Y-%m-%d")
    new_info = {k: info[k] for k in _BUNDLE_INFO_KEYS if k in info}
    new_info.update({"mode": "bundled", "built_at": built_date, "files": files,
                     "counts": catalog_counts(items, unlocks)})
    for name, b in data.items():
        _atomic_write(os.path.join(dest, name), b)
    _atomic_write(os.path.join(dest, BUILD_INFO),
                  (json.dumps(new_info, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"))
    return new_info


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
_ITEM_KEYS = {"id", "name", "category", "hint", "max_durability", "max_stack", "inv_tab", "retired",
              "placeholder_name", "derived_name", "source"}
_TABS = {"bag", "rune", "ammo", "quest"}


def verify_catalog(folder=None, min_items=1500):
    """Check a catalog folder (default: the bundled one) without network access: valid JSON,
    the expected shape, counts equal to build_info.json and, when recorded, file hashes.
    Returns the build info; raises CatalogError listing every problem found."""
    folder = folder or bundled_dir()
    problems = []
    info = _read_info(folder)
    if info is None:
        raise CatalogError("%s: no readable %s with format %d" % (folder, BUILD_INFO, CATALOG_FORMAT))
    loaded = {}
    for name in BUNDLED_FILES:
        try:
            with open(os.path.join(folder, name), "rb") as f:
                raw = f.read()
            loaded[name] = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError) as e:
            problems.append("%s: %s" % (name, e))
            continue
        want = (info.get("files") or {}).get(name)
        if want and (want.get("sha256") != _sha256(raw) or want.get("bytes") != len(raw)):
            problems.append("%s: does not match the sha256/size in %s" % (name, BUILD_INFO))
        if info.get("mode") == "bundled" and (raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw):
            problems.append("%s: must be UTF-8 without BOM, with LF line endings" % name)
    items, unlocks = loaded.get("items.json"), loaded.get("unlock_names.json")
    if items is not None:
        if not isinstance(items, list) or len(items) < min_items:
            problems.append("items.json: expected a list of at least %d items" % min_items)
            items = items if isinstance(items, list) else []
        ids = set()
        for it in items:
            if not isinstance(it, dict) or set(it) != _ITEM_KEYS:
                problems.append("items.json: bad entry %r" % (it,))
                break
            if not _ID_RE.match(it["id"]) or it["id"] in ids:
                problems.append("items.json: bad or duplicate id %r" % it["id"])
            ids.add(it["id"])
            if not it["name"] or it["inv_tab"] not in _TABS or not isinstance(it["max_stack"], int) \
                    or it["max_stack"] < 1:
                problems.append("items.json: bad fields in %s (%s)" % (it["id"], it["name"]))
    if unlocks is not None:
        if not isinstance(unlocks, dict) or set(unlocks) != set(UNLOCK_SECTIONS):
            problems.append("unlock_names.json: sections must be exactly %s" % ", ".join(sorted(UNLOCK_SECTIONS)))
            unlocks = unlocks if isinstance(unlocks, dict) else {}
        for sec, table in unlocks.items():
            if not isinstance(table, dict) or not table:
                problems.append("unlock_names.json: section %s is empty" % sec)
                continue
            for i, e in table.items():
                if not _ID_RE.match(i) or not isinstance(e, dict) or not e.get("name"):
                    problems.append("unlock_names.json: bad entry %s in %s" % (i, sec))
                    break
    if items is not None and unlocks is not None and not problems:
        if catalog_counts(items, unlocks) != info.get("counts"):
            problems.append("counts differ from %s: %s vs %s"
                            % (BUILD_INFO, catalog_counts(items, unlocks), info.get("counts")))
    if problems:
        raise CatalogError("Catalog in %s failed verification:\n  - %s" % (folder, "\n  - ".join(problems)))
    return info


# ---------------------------------------------------------------------------
# Loading: a compatible user-built catalog, else the bundled one
# ---------------------------------------------------------------------------

def _read_info(folder):
    try:
        with open(os.path.join(folder, BUILD_INFO), encoding="utf-8-sig") as f:
            info = json.load(f)
        return info if isinstance(info, dict) and info.get("format") == CATALOG_FORMAT else None
    except (OSError, ValueError):
        return None


def catalog_status(out_dir=None):
    """Build info of the USER-BUILT catalog (``dwsave catalog build`` / Update item catalog), or
    None if there is none. active_status() tells which catalog is actually in use."""
    return _read_info(out_dir or catalog_dir())


def is_built(out_dir=None):
    """True if a user-built catalog exists (whether or not it is the one in use)."""
    return catalog_status(out_dir) is not None


def bundled_status():
    """Build info of the bundled catalog, or None if it is missing (damaged install)."""
    return _read_info(bundled_dir())


def _user_build_usable(info, bundled_info):
    """A user build replaces the bundled catalog when its format matches and its generator is
    at least as new as the bundled one's (a build made by older derivation rules is ignored)."""
    if not info:
        return False
    if not bundled_info:
        return True
    return int(info.get("generator_version") or 0) >= int(bundled_info.get("generator_version") or 0)


_DEFAULT = object()


def _candidates(out_dir=None, bundled=_DEFAULT):
    """[(origin, folder, info)] in load order."""
    out_dir = out_dir or catalog_dir()
    bdir = bundled_dir() if bundled is _DEFAULT else bundled
    binfo = _read_info(bdir) if bdir else None
    uinfo = catalog_status(out_dir)
    cands = []
    if _user_build_usable(uinfo, binfo):
        cands.append(("user", out_dir, uinfo))
    if bdir:
        cands.append(("bundled", bdir, binfo or {}))
    return cands


def active_status(out_dir=None):
    """Build info of the catalog load_catalog() uses, plus "origin" ("user" or "bundled") and
    "user_build_ignored" (a user build exists but is older than the bundled one).
    None if there is no usable catalog."""
    for origin, folder, info in _candidates(out_dir):
        if os.path.isfile(os.path.join(folder, _FILE_FOR_KIND["items"])):
            out = dict(info, origin=origin)
            out["user_build_ignored"] = origin == "bundled" and is_built(out_dir)
            return out
    return None


def load_catalog(kind, out_dir=None, bundled_dir=_DEFAULT):
    """'items' -> list of item dicts, 'unlock_names' -> {section: {id: entry}}.

    Load order: a compatible user-built catalog in the user data folder (``out_dir``), then
    the bundled catalog (``bundled_dir``, default: the package's data/catalog; None disables
    it). Raises CatalogNotBuiltError when neither can be read.
    """
    if kind not in _FILE_FOR_KIND:
        raise ValueError("kind must be one of %s" % ", ".join(KINDS))
    name = _FILE_FOR_KIND[kind]
    for _origin, folder, _info in _candidates(out_dir, bundled_dir):
        try:
            with open(os.path.join(folder, name), encoding="utf-8-sig") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    raise CatalogNotBuiltError(
        "No %s catalog could be loaded: the catalog bundled with the editor is missing or "
        "damaged (reinstall the editor), and none has been built on this computer. To build "
        "one from your installed game, run `dwsave catalog build` (or `python -m "
        "dragonwilds_save_editor.catalog build`; add --game-dir FOLDER if the game is not found "
        "automatically)." % kind)


def reset_to_bundled(out_dir=None):
    """Delete the user-built catalog so the bundled one is used again. Returns the paths removed."""
    out_dir = out_dir or catalog_dir()
    removed = []
    # build_info.json first: without it a half-removed build is never loaded.
    for name in (BUILD_INFO, "items.json", "unlock_names.json", "items.csv", "items_ai.tsv"):
        path = os.path.join(out_dir, name)
        try:
            os.remove(path)
            removed.append(path)
        except FileNotFoundError:
            pass
    return removed


# ---------------------------------------------------------------------------
# Comparing two catalogs (development aid: a new build vs the bundled catalog)
# ---------------------------------------------------------------------------

ITEM_FIELDS = ("name", "category", "max_stack", "max_durability", "inv_tab", "retired", "hint",
               "placeholder_name", "derived_name")


def compare(built_items, built_unlocks, old_items, old_unlocks, examples=12):
    """Field-by-field agreement between a built catalog and an older one (IDs present in only
    one of them, and per field the number of matched IDs that agree/differ). 'source' is not
    compared."""
    new = {i["id"]: i for i in built_items}
    old = {i["id"]: i for i in old_items}
    both = sorted(set(new) & set(old))
    rep = {"items": {"built": len(new), "old": len(old), "matched_ids": len(both),
                     "only_old": sorted((old[i]["name"], i) for i in set(old) - set(new)),
                     "only_built": sorted((new[i]["name"], i) for i in set(new) - set(old)),
                     "fields": {}}}
    for f in ITEM_FIELDS:
        diffs = [(old[i]["name"], old[i].get(f), new[i].get(f)) for i in both if old[i].get(f) != new[i].get(f)]
        rep["items"]["fields"][f] = {"agree": len(both) - len(diffs), "differ": len(diffs),
                                     "examples": diffs[:examples]}
    rep["unlocks"] = {}
    for sec in UNLOCK_SECTIONS:
        n, o = built_unlocks.get(sec, {}), old_unlocks.get(sec, {})
        common = sorted(set(n) & set(o))
        fields = sorted({k for i in common for k in list(n[i]) + list(o[i])} - {"source"})
        fa = {}
        for f in fields:
            d = [(o[i].get("name"), o[i].get(f), n[i].get(f)) for i in common if o[i].get(f) != n[i].get(f)]
            fa[f] = {"agree": len(common) - len(d), "differ": len(d), "examples": d[:examples]}
        rep["unlocks"][sec] = {"built": len(n), "old": len(o), "matched_ids": len(common),
                               "only_old": sorted((o[i]["name"], i) for i in set(o) - set(n)),
                               "only_built": sorted((n[i]["name"], i) for i in set(n) - set(o)),
                               "fields": fa}
    return rep


def compare_text(rep):
    """Human-readable summary of a compare() report."""
    r = rep["items"]
    lines = ["items: built %d, old %d, matched %d, only old %d, only built %d"
             % (r["built"], r["old"], r["matched_ids"], len(r["only_old"]), len(r["only_built"]))]
    for f, s in r["fields"].items():
        lines.append("  %-16s agree %5d  differ %4d" % (f, s["agree"], s["differ"]))
    for sec, s in rep["unlocks"].items():
        lines.append("%-21s built %4d old %4d matched %4d  only-old %d  only-built %d"
                     % (sec, s["built"], s["old"], s["matched_ids"], len(s["only_old"]), len(s["only_built"])))
        for f, fs in s["fields"].items():
            if fs["differ"]:
                lines.append("      %-15s agree %5d  differ %4d" % (f, fs["agree"], fs["differ"]))
    return "\n".join(lines)


def _load_folder(folder):
    with open(os.path.join(folder, "items.json"), encoding="utf-8-sig") as f:
        items = json.load(f)
    with open(os.path.join(folder, "unlock_names.json"), encoding="utf-8-sig") as f:
        unlocks = json.load(f)
    return items, unlocks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_progress():
    last = [None, 0.0]

    def cb(stage, done, total):
        now = time.time()
        if stage != last[0] or done == total or now - last[1] > 0.5:
            last[0], last[1] = stage, now
            sys.stderr.write("\r%-9s %5d / %-5d" % (stage, done, total))
            if done == total:
                sys.stderr.write("\n")
            sys.stderr.flush()
    return cb


def _status_text(out_dir=None):
    info = active_status(out_dir)
    if not info:
        return None
    where = (out_dir or catalog_dir()) if info["origin"] == "user" else bundled_dir()
    lines = ["In use: %s catalog (%s)" % (info["origin"], where)]
    if info.get("user_build_ignored"):
        lines.append("A user-built catalog exists but was made by an older generator; it is ignored.")
    lines.append(json.dumps({k: v for k, v in info.items() if k not in ("origin", "user_build_ignored")},
                            indent=1))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="rebuild the catalog from your installed game into the user data "
                                     "folder (used instead of the bundled one); reads the game only")
    b.add_argument("--game-dir", metavar="FOLDER",
                   help="the game's installation folder (default: detect it)")
    b.add_argument("--out", metavar="FOLDER", help="write the catalog here instead of the user data folder")
    sub.add_parser("detect", help="show where the game is installed (as the build would find it)")
    sub.add_parser("status", help="show which catalog is in use and its build info")
    sub.add_parser("reset", help="delete the user-built catalog and use the bundled one again")
    v = sub.add_parser("verify", help="check a catalog folder's files and counts (default: the bundled one)")
    v.add_argument("folder", nargs="?")
    c = sub.add_parser("compare", help="field-by-field comparison of two catalogs")
    c.add_argument("--old", metavar="FOLDER", help="reference catalog folder (default: the bundled one)")
    c.add_argument("--new", metavar="FOLDER", help="catalog to check (default: the user-built one)")
    c.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            info = build(a.game_dir, _cli_progress(), a.out)
            print(json.dumps(info, indent=1))
        elif a.cmd == "detect":
            from .gamedata import install
            found = install.candidates()
            if not found:
                print("The game was not found; pass --game-dir FOLDER to `catalog build`.")
                return 1
            for folder, how in found:
                print("%s  (%s)" % (folder, how))
        elif a.cmd == "status":
            text = _status_text()
            print(text or "No usable catalog: none built in %s and the bundled one is missing."
                  % catalog_dir())
            return 0 if text else 1
        elif a.cmd == "reset":
            removed = reset_to_bundled()
            print("Removed %d file(s); using the bundled catalog." % len(removed) if removed
                  else "No user-built catalog; already using the bundled catalog.")
        elif a.cmd == "verify":
            info = verify_catalog(a.folder)
            print("OK: %s" % json.dumps(info.get("counts"), sort_keys=True))
        elif a.cmd == "compare":
            new_dir = a.new or catalog_dir()
            if not os.path.isfile(os.path.join(new_dir, "items.json")):
                raise CatalogNotBuiltError("No built catalog in %s" % new_dir)
            rep = compare(*_load_folder(new_dir), *_load_folder(a.old or bundled_dir()))
            print(json.dumps(rep, indent=1, ensure_ascii=False) if a.json else compare_text(rep))
    except CatalogError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
