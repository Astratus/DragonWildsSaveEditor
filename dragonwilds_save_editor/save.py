"""
save - RuneScape: Dragonwilds character save editor (stdlib only, Python 3.10+).

Edits the plain-JSON character save (e.g. "MyCharacter#1.json"). Item names come
from the item catalog bundled with the editor (data/catalog/, generated from the game's own
data by the catalog module; ``dwsave catalog build`` can rebuild it locally); skill names and the XP curve come from
data/skills.json and data/xp_table.json (bundled package data, located via
paths.resource_path).

CLOSE THE GAME FIRST. Every write makes a timestamped backup
(<save>.<YYYYmmdd-HHMMSS>.pyedit.bak) and refuses to run while the game is open
(override with --force).

Usage examples (quote the path - '#' matters in some shells). ``dwsave`` is the
installed console script; from a source checkout use
``python -m dragonwilds_save_editor.save`` instead:
    dwsave "MyCharacter#1.json" info
    dwsave "MyCharacter#1.json" inv --section all
    dwsave "MyCharacter#1.json" search rune --category Resource
    dwsave "MyCharacter#1.json" add "Nature Rune" --count 500
    dwsave "MyCharacter#1.json" add "Mithril Pickaxe" --slot 25
    dwsave "MyCharacter#1.json" set-count Inventory 40 9999
    dwsave "MyCharacter#1.json" repair
    dwsave "MyCharacter#1.json" remove Inventory 73
    dwsave "MyCharacter#1.json" skills
    dwsave "MyCharacter#1.json" set-skill Mining --level 60
    dwsave "MyCharacter#1.json" --dry-run set-skill Magic --xp 200000
    dwsave "MyCharacter#1.json" selftest

Library use:
    from dragonwilds_save_editor.save import SaveFile
    s = SaveFile("MyCharacter#1.json")
    s.add_item("Nature Rune", count=500)
    s.save()

File format notes (verified against a real save, game save Version 86):
  * UE "pretty" JSON: tab indentation, CRLF line endings (newer builds may use LF;
    we keep whatever the file uses), no trailing newline, no BOM.
  * A key whose value is an object: `"key":` then newline, then `{` at the key's indent.
  * A key whose value is an array or scalar: `"key": value` / `"key": [`.
  * Empty object: `{` newline `}` (closing brace at the opening brace's indent).
  * Empty array: `[]`.
  * Arrays of only numbers/bools are written on one line: `[ 1.5, 2 ]`.
  * Other arrays: one element per line at indent+1, `]` on its own line.
  * Numbers are written as UE's %.17g; we keep each number's original text
    so untouched values round-trip byte for byte.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from . import catalog
from . import paths

DATA_DIR = paths.resource_path("data")
SECTIONS = ("Inventory", "PersonalInventory", "Loadout")
# Inventory tab slot ranges for patch 1.0.1+ (save Version 86), inferred from a real
# save: the first used slot of each tab sits at 8, 40, 72 and 104. Older editors document
# the pre-1.0.1 layout (bag 8-31, runes 32-55), which no longer applies.
INVENTORY_TABS = {
    "hotbar": range(0, 8),
    "bag": range(8, 40),
    "rune": range(40, 72),
    "ammo": range(72, 104),
    "quest": range(104, 136),
}
GAME_PROCESS_HINT = "rsdragonwilds"


# --------------------------------------------------------------------------
# UE-style JSON reading / writing
# --------------------------------------------------------------------------

class RawFloat(float):
    """A float that remembers the exact text it was parsed from."""

    def __new__(cls, text):
        obj = float.__new__(cls, text)
        obj.raw = text
        return obj


class RawInt(int):
    """An int that remembers its text (only matters for oddities like '-0')."""

    def __new__(cls, text):
        obj = int.__new__(cls, text)
        obj.raw = text
        return obj


def ue_loads(text):
    return json.loads(text, parse_float=RawFloat, parse_int=RawInt)


def _ue_string(s):
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _ue_number(v):
    raw = getattr(v, "raw", None)
    if raw is not None:
        return raw
    if isinstance(v, int):
        return str(int(v))
    if v != v or v in (float("inf"), float("-inf")):
        return "0"
    return "%.17g" % v


def _ue_scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, str):
        return _ue_string(v)
    if isinstance(v, (int, float)):
        return _ue_number(v)
    raise TypeError("Cannot serialize %r" % (v,))


def _is_inline_scalar(v):
    return isinstance(v, (int, float)) and not isinstance(v, str)  # bools are ints


def ue_dumps(value, nl="\r\n"):
    """Serialize exactly like Unreal's pretty FJsonSerializer output."""

    def tabs(n):
        return "\t" * n

    def write(v, depth):
        if isinstance(v, dict):
            if not v:
                return "{" + nl + tabs(depth) + "}"
            parts = []
            for k, x in v.items():
                head = tabs(depth + 1) + _ue_string(k)
                if isinstance(x, dict):
                    parts.append(head + ":" + nl + tabs(depth + 1) + write(x, depth + 1))
                else:
                    parts.append(head + ": " + write(x, depth + 1))
            return "{" + nl + ("," + nl).join(parts) + nl + tabs(depth) + "}"
        if isinstance(v, list):
            if not v:
                return "[]"
            if all(_is_inline_scalar(x) for x in v):
                return "[ " + ", ".join(_ue_scalar(x) for x in v) + " ]"
            items = [tabs(depth + 1) + write(x, depth + 1) for x in v]
            return "[" + nl + ("," + nl).join(items) + nl + tabs(depth) + "]"
        return _ue_scalar(v)

    return write(value, 0)


# --------------------------------------------------------------------------
# Game data (items / skills / xp)
# --------------------------------------------------------------------------

def _load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8-sig") as f:
        return json.load(f)


class GameData:
    """Item catalog, skill names and the XP table.

    Items come from catalog.load_catalog("items"): a compatible catalog rebuilt on this
    machine, else the one bundled with the editor. If neither can be read (damaged install),
    this raises catalog.CatalogNotBuiltError, unless require_catalog is False: then the item
    list is empty (unknown items show as raw IDs) and ``catalog_missing`` is True. ``items`` may also be passed in directly (tests).
    """

    def __init__(self, require_catalog=True, items=None):
        self.catalog_missing = False
        if items is None:
            try:
                items = catalog.load_catalog("items")
            except catalog.CatalogNotBuiltError:
                if require_catalog:
                    raise
                items, self.catalog_missing = [], True
        self.items = items
        self.items_by_id = {it["id"]: it for it in self.items}
        self.skills = _load_json("skills.json")
        self.skills_by_id = {s["id"]: s["name"] for s in self.skills}
        self.xp_for_level = _load_json("xp_table.json")["xp_for_level"]

    @property
    def max_level(self):
        return len(self.xp_for_level)

    def item_name(self, item_id):
        it = self.items_by_id.get(item_id)
        if not it:
            return "?unknown?"
        return it["name"] + (" [%s]" % it["hint"] if it.get("hint") else "")

    def search(self, text, category=None):
        t = text.lower()
        out = [it for it in self.items if t in it["name"].lower() or t == it["id"].lower()]
        if category:
            out = [it for it in out if it["category"].lower() == category.lower()]
        return out

    def resolve_item(self, query):
        """Name or id -> item dict. Raises LookupError listing candidates if ambiguous,
        or catalog.CatalogNotBuiltError when there is no item catalog to look in."""
        if self.catalog_missing:
            raise catalog.CatalogNotBuiltError(CATALOG_HINT)
        if query in self.items_by_id:
            return self.items_by_id[query]
        q = query.strip().lower()
        for matcher in (lambda it: it["name"].lower() == q,
                        lambda it: q in it["name"].lower()):
            found = [it for it in self.items if matcher(it)]
            if len(found) > 1:  # prefer live items over retired/placeholder ones
                live = [it for it in found if not it.get("retired") and not it.get("placeholder_name")]
                if len(live) == 1:
                    found = live
            if len(found) == 1:
                return found[0]
            if found:
                raise LookupError(found)
        raise LookupError([])

    def resolve_skill(self, query):
        q = query.strip().lower()
        for sid, name in self.skills_by_id.items():
            if q in (sid.lower(), name.lower()):
                return sid, name
        raise LookupError("Unknown skill %r. Known: %s" % (query, ", ".join(sorted(self.skills_by_id.values()))))

    def level_for_xp(self, xp):
        level = 1
        for i, need in enumerate(self.xp_for_level):
            if xp >= need:
                level = i + 1
        return level

    def xp_for(self, level):
        if not 1 <= level <= self.max_level:
            raise ValueError("Level must be 1-%d" % self.max_level)
        return self.xp_for_level[level - 1]


# --------------------------------------------------------------------------
# Save file
# --------------------------------------------------------------------------

def new_item_guid():
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")


def game_is_running():
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace").stdout
    except OSError:
        return False
    return GAME_PROCESS_HINT in out.lower()


GAME_SAVED_DIR = paths.game_saved_dir()


def snapshot_root():
    """Where full snapshots go: %LOCALAPPDATA%/DragonwildsSaveEditor/backups (created on demand)."""
    return paths.user_data_dir("backups")


def snapshot_game_saves(label="full", saved_dir=None, dest_root=None):
    """Copy every character AND world save (SaveCharacters + SaveGames) to
    <snapshot_root()>/<label>_<timestamp>/, verify each copy byte for byte, and return the folder.

    Quest edits call this first: quest progress is partly stored in the world saves,
    which this editor never modifies, so a full snapshot is the only complete rollback.
    """
    if saved_dir is None:
        saved_dir = GAME_SAVED_DIR
    if dest_root is None:
        dest_root = snapshot_root()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(dest_root, "%s_%s" % (label, stamp))
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(dest_root, "%s_%s-%d" % (label, stamp, n))
        n += 1
    copied = 0
    for sub in ("SaveCharacters", "SaveGames"):
        src_dir = os.path.join(saved_dir, sub)
        if not os.path.isdir(src_dir):
            continue
        os.makedirs(os.path.join(dest, sub))
        for name in os.listdir(src_dir):
            src = os.path.join(src_dir, name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(dest, sub, name)
            shutil.copy2(src, dst)
            with open(src, "rb") as a, open(dst, "rb") as b:
                if a.read() != b.read():
                    raise RuntimeError("Snapshot copy of %s does not match; aborting." % src)
            copied += 1
    if not copied:
        raise RuntimeError("No save files found under %s; nothing was backed up." % saved_dir)
    return dest


def _is_slot(key):
    return key.isdigit()


class SaveFile:
    def __init__(self, path, data=None):
        self.path = path
        self.game = data if data is not None else GameData()
        with open(path, "rb") as f:
            raw = f.read()
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        self.original_text = raw[3:].decode("utf-8") if self.bom else raw.decode("utf-8")
        self.nl = "\r\n" if "\r\n" in self.original_text else "\n"
        self.trailing = self.original_text[len(self.original_text.rstrip("\r\n")):]
        self.root = ue_loads(self.original_text)

    # ---- serialization -------------------------------------------------
    def to_text(self):
        return ue_dumps(self.root, self.nl) + self.trailing

    def to_bytes(self):
        body = self.to_text().encode("utf-8")
        return (b"\xef\xbb\xbf" + body) if self.bom else body

    def make_backup(self):
        """Copy the save on disk to a new, never-overwritten backup file and verify it.

        Every write goes through this, so each change gets its own restorable copy.
        """
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = "%s.%s.pyedit.bak" % (self.path, stamp)
        n = 2
        while os.path.exists(backup):  # several saves within one second
            backup = "%s.%s-%d.pyedit.bak" % (self.path, stamp, n)
            n += 1
        shutil.copy2(self.path, backup)
        if os.path.getsize(backup) != os.path.getsize(self.path):
            raise RuntimeError("Backup %s looks incomplete; not writing the save." % backup)
        return backup

    def save(self, force=False, dry_run=False):
        if dry_run:
            print("[dry-run] not writing %s" % self.path)
            return None
        if not force and game_is_running():
            raise RuntimeError("Dragonwilds appears to be running. Close it first (or pass --force).")
        backup = self.make_backup()
        folder = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(prefix=".dw_save_", dir=folder)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(self.to_bytes())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        print("Saved %s (backup: %s)" % (self.path, backup))
        return backup

    # ---- accessors -------------------------------------------------------
    @property
    def progress(self):
        return self.root["GameProgress"]

    def section(self, name):
        for s in SECTIONS:
            if s.lower() == name.lower():
                return self.progress.setdefault(s, {})
        raise KeyError("Unknown section %r (use one of %s)" % (name, ", ".join(SECTIONS)))

    def slots(self, name):
        sec = self.section(name)
        return sorted(((int(k), v) for k, v in sec.items() if _is_slot(k)), key=lambda kv: kv[0])

    def _reorder(self, sec):
        keys = list(sec.keys())
        head = [k for k in keys if not _is_slot(k) and k != "MaxSlotIndex"]
        nums = sorted((k for k in keys if _is_slot(k)), key=int)
        tail = ["MaxSlotIndex"] if "MaxSlotIndex" in sec else []
        ordered = {k: sec[k] for k in head + nums + tail}
        sec.clear()
        sec.update(ordered)

    def _timestamp(self):
        """Newest real AddedToInventoryTimestamp (FDateTime ticks) in the save, else now."""
        best = None
        for s in SECTIONS:
            for _, it in self.slots(s):
                ts = it.get("AddedToInventoryTimestamp") if isinstance(it, dict) else None
                if isinstance(ts, (int, float)) and ts > 1e17 and (best is None or ts > best):
                    best = ts
        if best is not None:
            return best
        epoch = datetime(1, 1, 1, tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - epoch
        return float((delta.days * 86400 + delta.seconds) * 10**7 + delta.microseconds * 10)

    # ---- edits ---------------------------------------------------------------
    def _check_stack(self, item, n, allow_overstack):
        mx = item.get("max_stack")
        if mx and n > mx and not allow_overstack:
            raise ValueError("%s stacks to %d in-game; asked for %d. Pass --allow-overstack to "
                             "write it anyway (oversized stacks may be clamped or lost)." % (item["name"], mx, n))

    def add_item(self, query, count=None, slot=None, section="Inventory", allow_overstack=False):
        item = self.game.resolve_item(query)
        if count is not None and not item.get("max_durability"):
            self._check_stack(item, int(count), allow_overstack)
        sec = self.section(section)
        used = {int(k) for k in sec if _is_slot(k)}
        if slot is None:
            if section.lower() == "inventory":
                # Put the item in its own tab (bag / rune / ammo / quest), never the hotbar.
                tab = item.get("inv_tab") or "bag"
                free = [s for s in INVENTORY_TABS.get(tab, INVENTORY_TABS["bag"]) if s not in used]
                if not free:
                    raise ValueError("The %s tab is full; free a slot or pass --slot." % tab)
                slot = free[0]
            else:
                slot = 0
                while slot in used:
                    slot += 1
        elif slot in used:
            raise ValueError("%s slot %d is occupied (%s)" % (
                section, slot, self.describe(sec[str(slot)])))

        entry = {"GUID": new_item_guid(), "ItemData": item["id"]}
        if item.get("max_durability"):
            entry["Durability"] = int(item["max_durability"])
        else:
            n = 1 if count is None else int(count)
            if n < 1:
                raise ValueError("Count must be >= 1")
            if n != 1:  # the game omits Count for single items
                entry["Count"] = n
        entry["AddedToInventoryTimestamp"] = self._timestamp()

        sec[str(slot)] = entry
        if "MaxSlotIndex" in sec and int(sec["MaxSlotIndex"]) < slot:
            sec["MaxSlotIndex"] = slot
        self._reorder(sec)
        return slot, item

    def set_count(self, section, slot, n, allow_overstack=False):
        it = self._get(section, slot)
        if "Durability" in it and "Count" not in it:
            raise ValueError("That item uses durability, not a count (try 'repair').")
        if n < 1:
            raise ValueError("Count must be >= 1 (use 'remove' to delete).")
        cat = self.game.items_by_id.get(it.get("ItemData"))
        if cat:
            self._check_stack(cat, n, allow_overstack)
        if n == 1:
            it.pop("Count", None)
        else:
            self._set_before_timestamp(it, "Count", int(n))
        return it

    def repair(self, section="all"):
        fixed = []
        names = SECTIONS if section.lower() == "all" else (section,)
        for s in names:
            for slot, it in self.slots(s):
                if not isinstance(it, dict) or "Durability" not in it:
                    continue
                cat = self.game.items_by_id.get(it.get("ItemData"))
                mx = cat and cat.get("max_durability")
                if mx and it["Durability"] != mx:
                    fixed.append((s, slot, self.game.item_name(it["ItemData"]), it["Durability"], mx))
                    it["Durability"] = int(mx)
        return fixed

    def remove(self, section, slot):
        sec = self.section(section)
        it = self._get(section, slot)
        del sec[str(slot)]
        self._reorder(sec)
        if self.section(section) is self.progress.get("Inventory"):
            self.unequip_pointers_to(slot)
        return it

    def loadout_pointers_to(self, inv_slot):
        """Loadout slots whose PlayerInventoryItemIndex points at this Inventory slot."""
        return [s for s, it in self.slots("Loadout")
                if isinstance(it, dict) and it.get("PlayerInventoryItemIndex") == inv_slot]

    def unequip_pointers_to(self, inv_slot):
        """Drop Loadout pointers to an Inventory slot (the item there was removed)."""
        loadout = self.section("Loadout")
        dropped = self.loadout_pointers_to(inv_slot)
        for s in dropped:
            del loadout[str(s)]
        if dropped:
            self._reorder(loadout)
        return dropped

    def skills(self):
        rows = []
        for s in self.progress.get("Skills", {}).get("Skills", []):
            xp = s.get("Xp", 0)
            rows.append((self.game.skills_by_id.get(s["Id"], s["Id"]), xp, self.game.level_for_xp(xp)))
        return rows

    def set_skill(self, name, level=None, xp=None):
        sid, sname = self.game.resolve_skill(name)
        new_xp = self.game.xp_for(level) if level is not None else int(xp)
        if new_xp < 0:
            raise ValueError("XP must be >= 0")
        skills = self.progress.setdefault("Skills", {}).setdefault("Skills", [])
        for s in skills:
            if s.get("Id") == sid:
                s["Xp"] = new_xp
                break
        else:
            skills.append({"Id": sid, "Xp": new_xp})
        return sname, new_xp, self.game.level_for_xp(new_xp)

    # ---- helpers -------------------------------------------------------------
    def _get(self, section, slot):
        sec = self.section(section)
        it = sec.get(str(slot))
        if not isinstance(it, dict):
            raise KeyError("%s slot %s is empty" % (section, slot))
        return it

    @staticmethod
    def _set_before_timestamp(it, key, value):
        if key in it:
            it[key] = value
            return
        items = list(it.items())
        it.clear()
        inserted = False
        for k, v in items:
            if k == "AddedToInventoryTimestamp" and not inserted:
                it[key] = value
                inserted = True
            it[k] = v
        if not inserted:
            it[key] = value

    def describe(self, it):
        if "PlayerInventoryItemIndex" in it:
            idx = it["PlayerInventoryItemIndex"]
            ref = self.progress.get("Inventory", {}).get(str(idx))
            name = self.game.item_name(ref["ItemData"]) if isinstance(ref, dict) and "ItemData" in ref else "empty"
            return "-> Inventory[%s] (%s)" % (idx, name)
        return self.game.item_name(it.get("ItemData", ""))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _fmt_seconds(sec):
    sec = int(float(sec))
    return "%dh %02dm" % (sec // 3600, (sec % 3600) // 60)


def cmd_info(s, a):
    r = s.root
    meta = r.get("meta_data", {})
    ch = s.progress.get("Character", {})
    print("Character : %s" % meta.get("char_name"))
    print("Version   : %s" % r.get("Version"))
    print("SaveCount : %s" % r.get("SaveCount"))
    print("Hardcore  : %s" % r.get("Hardcore", {}).get("IsHardcore"))
    if "Playtime_sim" in ch:
        print("Playtime  : %s (in-game sim), %s (wall clock)" % (
            _fmt_seconds(ch["Playtime_sim"]), _fmt_seconds(ch.get("Playtime_wall", 0))))
    print("Worlds    : %d" % len(meta.get("worlds_playtime", {})))


def cmd_inv(s, a):
    names = SECTIONS if a.section.lower() == "all" else (a.section,)
    for name in names:
        print("== %s ==" % name)
        sec = s.section(name)
        if "MaxSlotIndex" in sec:
            print("   (MaxSlotIndex %s)" % sec["MaxSlotIndex"])
        print("%5s  %-42s %-12s %-14s %s" % ("slot", "item", "category", "qty/dur", "id"))
        for slot, it in s.slots(name):
            if not isinstance(it, dict):
                continue
            if "PlayerInventoryItemIndex" in it:
                print("%5d  %s" % (slot, s.describe(it)))
                continue
            cat = s.game.items_by_id.get(it.get("ItemData"), {})
            if "Durability" in it:
                qty = "%s/%s" % (it["Durability"], cat.get("max_durability") or "?")
            else:
                qty = "x%s" % it.get("Count", 1)
            extra = ""
            if "ContentItemData" in it:
                extra = "  [holds %s, charges %s]" % (s.game.item_name(it["ContentItemData"]),
                                                      it.get("RemainingFillCharges"))
            print("%5d  %-42s %-12s %-14s %s%s" % (slot, s.describe(it)[:42], cat.get("category", "?"),
                                                   qty, it.get("ItemData"), extra))


def cmd_search(s, a):
    hits = s.game.search(a.text, a.category)
    for it in hits:
        flags = [f for f in ("retired", "placeholder_name", "derived_name") if it.get(f)]
        print("%-24s %-44s %-12s %s%s" % (
            it["id"], it["name"], it["category"],
            ("maxdur=%s " % it["max_durability"]) if it.get("max_durability") else "",
            ("(" + ", ".join(flags) + ")") if flags else ""))
    print("%d match(es)" % len(hits))


def _print_ambiguous(err):
    cands = err.args[0] if err.args else []
    if not cands:
        print("No item matches that name. Try: search <text>", file=sys.stderr)
        return
    print("Ambiguous - %d candidates (use the id instead):" % len(cands), file=sys.stderr)
    for it in cands[:40]:
        print("  %-24s %s%s  (%s)" % (it["id"], it["name"],
                                      " [%s]" % it["hint"] if it.get("hint") else "", it["category"]),
              file=sys.stderr)


def cmd_add(s, a):
    try:
        slot, item = s.add_item(a.item, count=a.count, slot=a.slot, section=a.section,
                                allow_overstack=a.allow_overstack)
    except LookupError as e:
        _print_ambiguous(e)
        return 2
    print("Added %s to %s slot %d" % (item["name"], a.section, slot))
    s.save(a.force, a.dry_run)


def cmd_set_count(s, a):
    it = s.set_count(a.section, a.slot, a.n, allow_overstack=a.allow_overstack)
    print("%s %s slot %d -> x%d" % (s.describe(it), a.section, a.slot, a.n))
    s.save(a.force, a.dry_run)


def cmd_repair(s, a):
    fixed = s.repair(a.section)
    for sec, slot, name, old, new in fixed:
        print("%s[%d] %s: %s -> %s" % (sec, slot, name, old, new))
    if not fixed:
        print("Nothing to repair.")
        return
    s.save(a.force, a.dry_run)


def cmd_remove(s, a):
    it = s.remove(a.section, a.slot)
    print("Removed %s from %s slot %d" % (s.describe(it), a.section, a.slot))
    s.save(a.force, a.dry_run)


def cmd_skills(s, a):
    for name, xp, lvl in s.skills():
        print("%-14s lvl %2d  %9s xp" % (name, lvl, format(int(xp), ",")))


def cmd_set_skill(s, a):
    name, xp, lvl = s.set_skill(a.name, level=a.level, xp=a.xp)
    print("%s -> %s xp (level %d)" % (name, format(xp, ","), lvl))
    s.save(a.force, a.dry_run)


def cmd_selftest(s, a):
    out = s.to_text()
    orig = s.original_text
    if out == orig:
        print("OK: round-trip is byte-identical (%d chars, newline=%r)." % (len(orig), s.nl))
        return 0
    i = next((k for k in range(min(len(out), len(orig))) if out[k] != orig[k]), min(len(out), len(orig)))
    print("MISMATCH at offset %d (original %d chars, output %d chars)" % (i, len(orig), len(out)))
    print("  original: %r" % orig[max(0, i - 60):i + 60])
    print("  output  : %r" % out[max(0, i - 60):i + 60])
    return 1


def build_parser():
    p = argparse.ArgumentParser(
        description="RuneScape: Dragonwilds character save editor",
        epilog="Item catalog: bundled; `dwsave catalog status` shows it, `dwsave catalog build` "
               "optionally rebuilds it from your installed game (read only; no network).")
    p.add_argument("save", help="path to the character .json save")
    p.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    p.add_argument("--force", action="store_true", help="write even if the game seems to be running")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="character summary").set_defaults(fn=cmd_info)

    sp = sub.add_parser("inv", help="list inventory")
    sp.add_argument("--section", default="all", help="Inventory | PersonalInventory | Loadout | all")
    sp.set_defaults(fn=cmd_inv)

    sp = sub.add_parser("search", help="search the item catalog")
    sp.add_argument("text")
    sp.add_argument("--category")
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("add", help="add an item by name or id")
    sp.add_argument("item")
    sp.add_argument("--count", type=int)
    sp.add_argument("--slot", type=int)
    sp.add_argument("--section", default="Inventory")
    sp.add_argument("--allow-overstack", action="store_true", help="allow counts above the item's max stack")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("set-count", help="change a stack size")
    sp.add_argument("section")
    sp.add_argument("slot", type=int)
    sp.add_argument("n", type=int)
    sp.add_argument("--allow-overstack", action="store_true", help="allow counts above the item's max stack")
    sp.set_defaults(fn=cmd_set_count)

    sp = sub.add_parser("repair", help="set durability to max")
    sp.add_argument("--section", default="all")
    sp.set_defaults(fn=cmd_repair)

    sp = sub.add_parser("remove", help="delete an item from a slot")
    sp.add_argument("section")
    sp.add_argument("slot", type=int)
    sp.set_defaults(fn=cmd_remove)

    sub.add_parser("skills", help="list skills").set_defaults(fn=cmd_skills)

    sp = sub.add_parser("set-skill", help="set a skill's level or xp")
    sp.add_argument("name")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--level", type=int)
    g.add_argument("--xp", type=int)
    sp.set_defaults(fn=cmd_set_skill)

    sub.add_parser("selftest", help="check the writer reproduces the file exactly").set_defaults(fn=cmd_selftest)
    return p


# Commands that cannot work without the item catalog (the others show raw item IDs).
CATALOG_COMMANDS = ("search", "add", "set-count", "repair")

CATALOG_HINT = ("No item catalog could be loaded: the one bundled with the editor is missing or\n"
                "damaged. Reinstall the editor, or build a catalog with\n"
                "    dwsave catalog build\n"
                "(or: python -m dragonwilds_save_editor.catalog build). It reads your installed game\n"
                "(found automatically; --game-dir FOLDER otherwise) and makes no network connection.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "catalog":
        # dwsave catalog build|status: the catalog module's own command line.
        return catalog.main(argv[1:])
    a = build_parser().parse_args(argv)
    try:
        try:
            game = GameData()
        except catalog.CatalogNotBuiltError:
            if a.cmd in CATALOG_COMMANDS:
                print("Error: %s" % CATALOG_HINT, file=sys.stderr)
                return 2
            print("Note: no item catalog could be loaded; items show as ?unknown?. "
                  "Reinstall, or run `dwsave catalog build`.",
                  file=sys.stderr)
            game = GameData(require_catalog=False)
        s = SaveFile(a.save, game)
        rc = a.fn(s, a)
    except (KeyError, ValueError, RuntimeError, LookupError, OSError) as e:
        print("Error: %s" % (e.args[0] if e.args else e), file=sys.stderr)
        return 1
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
