"""Build the item and unlock-name catalog from the player's installed game.

    items, unlocks, info = derive_from_install(paks_dir, progress=None)

Output shapes are the catalog's (items.json list, unlock_names.json {section: {id: entry}}).
The classification rules (categories, inventory tab, retired, names, groups) are shared with
dragonwilds_save_editor.catalog; this module only reads the values those rules need.

Reading an asset: its main export is decoded with its class schema (schemas.py). Classes the
schema inference could not solve completely fall back to:

* PersistenceID: a 22-char base64url FString followed by the InternalName FString (or, in a
  Blueprint class default object, the last value of the export), located by pattern;
* suffix alignment: the parent-class part (ItemData, journal-entry base) is decoded by trying
  every start offset and keeping the one whose parse ends exactly at the PersistenceID; up to
  two parent indices with no known type are tried with plain types, and the choice must fit
  every instance of the class;
* pattern scans for FText values and DataTable row handles.

Field positions (which index is the name, the stack size, ...) were assigned from the decoded
values and validated against the earlier catalog; see docs/research/catalog_build.md.
Every source field holds a package path ('/Game/...'), never a disk path.
"""

import itertools
import re
import struct
import time

from .. import catalog as rules
from . import decode, schemas as S, stringtable, uprops
from .game import GameData, asset_to_package, read_game_version

GENERATOR = "dragonwilds_save_editor.gamedata"

# --- field positions --------------------------------------------------------------------------
# ItemData-relative indices; a subclass adds (its PersistenceID index - ITEM_ID).
ITEM_ID = S.ITEM_ID
ITEM_NAME, ITEM_STACK, ITEM_CATEGORY, ITEM_FILTERS, ITEM_DURABILITY = 1, 12, 17, 20, 25
# Relative to the class's PersistenceID index K.
RECIPE_FIELDS = {"items_created": -20, "skill": -11}  # RecipeData K=23 -> 3, 12
PERK_FIELDS = {"name": -9, "unlock": -4}             # SkillPerkData K=9 -> 0, 5
JOURNAL_NAME = -5                                    # every JournalEntry* class (base-class field)
SPELL_NAME = 0                                       # UtilitySpellData: SpellDisplayName (absolute)
NAME_FIELD = {"BuildingPieceData": -21,              # K=22 -> DisplayName at 1
              "SkillData": -19}                      # K=19 -> Name at 0
MAX_LEVEL_FIELD = {"SkillData": -18}                 # K=19 -> MaxLevel at 1

# Leading properties of classes the inference could not solve completely (types read off the
# bytes, checked on every instance): UtilitySpellData index 0 = SpellDisplayName;
# JournalEntryKnowPlaceData index 0 = the journal name field.
LEADING = {"UtilitySpellData": {(0,): ("text",)},
           "JournalEntryKnowPlaceData": {(0,): ("text",)}}
JOURNAL_BASE = "JournalEntryKnowLoreData"  # no own fields: its schema is the journal-entry base

# Types tried for parent indices without a known type during suffix alignment. ('fix', 0) is
# needed for ItemData index 22, which only fits as 0 bytes (tree seeds; not understood).
PLAIN_TYPES = [("fix", 4), ("fix", 1), ("fix", 8), ("str",), ("text",), ("soft",), ("fix", 16),
               ("fix", 12), ("fix", 24), ("fix", 0)]

_DECODE_ERRORS = (ValueError, KeyError, IndexError, struct.error, EOFError)


def base_name(path):
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


# --- reading ----------------------------------------------------------------------------------

class Strings:
    """String tables by table id ('/Game/Gameplay/Items/ST_ItemNames.ST_ItemNames'), loaded lazily."""

    def __init__(self, gd):
        self.gd, self.cache = gd, {}

    def table(self, tid):
        if tid not in self.cache:
            pk = self.gd.package(tid.split(".", 1)[0])
            entries = {}
            if pk is not None and pk.exports:
                ex = next((e for e in pk.exports if e.name == tid.rsplit(".", 1)[-1]), pk.exports[0])
                try:
                    entries = stringtable.decode(pk, ex)[1]
                except (ValueError, EOFError, struct.error):
                    entries = {}
            self.cache[tid] = entries
        return self.cache[tid]

    def text(self, v):
        """FText value -> str or None (invariant string, base source string, or table entry)."""
        if not isinstance(v, dict):
            return None
        if v.get("type") == "none":
            return v.get("invariant") or None
        if v.get("type") == "base":
            return v.get("source") or None
        if v.get("type") == "st":
            return self.table(v["table"]).get(v["key"]) or None
        return None


class Asset:
    """One catalog asset: its main export decoded (fully, or partly with ``partial``)."""

    def __init__(self, rel, pkg, export, chain, props, id_index, partial):
        self.rel = rel                         # container path (RSDragonwilds/...uasset)
        self.package = asset_to_package(rel)   # '/Game/...': used for rules and 'source'
        self.pkg, self.export, self.chain = pkg, export, chain
        self.props, self.k, self.partial = props, id_index, partial
        self.base = base_name(rel)
        self.tails = None

    @property
    def cls(self):
        return self.chain[0] if self.chain else ""

    def pid(self):
        v = self.props.get(self.k) if self.k is not None else None
        return v if S.is_persistence_id(v) else None

    def internal(self):
        v = self.props.get(self.k + 1) if self.k is not None else None
        return v if isinstance(v, str) else None

    def soft_deleted(self):
        return self.props.get(self.k + 2) == 1 if self.k is not None else False

    def inst(self):
        return export_inst(self.pkg, self.export, self.rel)


def export_inst(pkg, export, label):
    """uprops.Inst over an export's property bytes. A plain object's export ends with a 4-byte
    bHasGuid (false) after its properties; a class default object does not."""
    b = pkg.export_data(export)
    inst = uprops.Inst(b, pkg, label)
    if not export.name.startswith("Default__"):
        inst.end = len(b) - 4
    return inst


def decode_asset(gd, schemas, rel):
    """Asset for the container path `rel`, or None if it has no main export."""
    pkg = gd.package(rel)
    ex = gd.main_export(pkg, base_name(rel))
    if ex is None:
        return None
    chain = gd.class_chain(pkg, ex)
    inst = export_inst(pkg, ex, rel)
    cls = chain[0] if chain else ""
    sch, k = schemas.get(cls, (None, None))
    if sch is not None:
        try:
            return Asset(rel, pkg, ex, chain, decode.Decoder(sch, pkg, gd).decode(inst), k, False)
        except decode.SchemaMismatch:
            pass
    item_sch = schemas.get(S.ITEM_PART)
    itemish = bool(chain) and rules.is_item_type(cls)
    lead = dict(sch) if sch else dict(LEADING.get(cls, {}))
    props, k = partial_decode(gd, pkg, inst, lead, item_sch[0] if itemish and item_sch else None)
    asset = Asset(rel, pkg, ex, chain, props, k, True)
    if not itemish and cls.startswith("JournalEntry") and JOURNAL_BASE in schemas:
        item_sch, itemish = schemas[JOURNAL_BASE], True
    if k is not None and item_sch and itemish and k >= item_sch[1]:
        present, _ = uprops.read_header(inst.b, 0)
        idp = S.find_id(inst)
        asset.tails = (tail_decode(gd, pkg, inst, item_sch[0], item_sch[1], k, idp, present)
                       if idp is not None else {})
    return asset


def partial_decode(gd, pkg, inst, sch, tail_schema=None):
    """Fallback for a class without a complete schema: decode the leading properties `sch`
    knows, then find PersistenceID / InternalName (/ bSoftDeleted) at the end. `tail_schema`
    (ItemData-relative, ID at ITEM_ID) types the fields after InternalName.
    Returns (props, id index or None)."""
    present, p = uprops.read_header(inst.b, 0)
    dec = decode.Decoder(sch, pkg, gd)
    dec.inst = inst
    props = {}
    for idx, zero in present:
        if zero:
            continue
        if (idx,) not in sch:
            break
        try:
            props[idx], p = dec.value((idx,), p)
        except _DECODE_ERRORS:
            break
    pos = S.find_id(inst)
    nz = [i for i, z in present if not z]
    if pos is None:
        # a Blueprint CDO stores only what differs from its parent: the ID can be the last
        # value, with no InternalName after it
        m = list(S.ID_RE.finditer(inst.b, 0, inst.end))
        tail = inst.b[m[0].end():inst.end] if len(m) == 1 else b"x"
        if len(m) == 1 and tail in (b"", bytes(4)) and nz:
            props[nz[-1]] = m[0].group()[4:-1].decode()
            return props, nz[-1]
        return props, None
    pid = inst.b[pos + 4:pos + 26].decode()
    try:
        internal, q = uprops.read_str(inst, pos + 27)
    except uprops.Fail:
        return props, None
    for k in nz:  # the ID index: followed by InternalName and fields that parse to the end
        if k + 1 not in nz:
            continue
        after = [i for i in nz if i > k + 1]
        r, vals, ok = q, {}, True
        if tail_schema is not None:
            tsch = {(key[0] - ITEM_ID + k,) + key[1:]: t for key, t in tail_schema.items()}
            d2 = decode.Decoder(tsch, pkg, gd)
            d2.inst = inst
            try:
                for i in after:
                    vals[i], r = d2.value((i,), r)
            except _DECODE_ERRORS:
                ok = False
        else:
            # without a schema: allow a trailing bool and/or an object reference
            size = inst.end - q
            ok = (len(after), size) in ((0, 0), (1, 1), (1, 4), (2, 5))
            if ok and size in (1, 5) and after and after[0] == k + 2:
                vals[k + 2] = inst.b[q]
            r = inst.end
        if ok and r == inst.end:
            props.update(vals)
            props[k] = pid
            props[k + 1] = internal
            return props, k
    if nz and inst.b[pos + 27:inst.end] in (b"", bytes(4)):  # Blueprint CDO: ID is the last value
        props[nz[-1]] = pid
        return props, nz[-1]
    return props, None


def tail_decode(gd, pkg, inst, parent_schema, parent_id, k, id_pos, present):
    """Decode only the parent-class part (the properties just before the PersistenceID) of an
    instance whose own leading properties have no schema: try every start offset and keep those
    whose parse lands exactly on the ID string. Up to two parent indices without a known type
    are tried with PLAIN_TYPES. Returns {(untyped indices, types): [values per landing]}."""
    shift = k - parent_id
    idx = [i for i, z in present if not z and shift <= i < k]
    if not idx:
        return {}
    base = {(key[0] + shift,) + key[1:]: t for key, t in parent_schema.items()}
    missing = [i for i in idx if (i,) not in base]
    if len(missing) > 2:
        return {}
    _, hdr_end = uprops.read_header(inst.b, 0)
    out = {}
    for combo in itertools.product(PLAIN_TYPES, repeat=len(missing)):
        sch = dict(base)
        for i, t in zip(missing, combo):
            sch[(i,)] = t
        dec = decode.Decoder(sch, pkg, gd)
        dec.inst = inst
        for start in range(id_pos - 1, hdr_end - 1, -1):
            p, vals = start, {}
            try:
                for i in idx:
                    vals[i], p = dec.value((i,), p)
                    if p > id_pos:
                        raise uprops.Fail("past the ID")
            except _DECODE_ERRORS:
                continue
            if p == id_pos:
                out.setdefault((tuple(missing), combo), []).append(vals)
    return out


def resolve_tails(assets_tails):
    """assets_tails: [(asset, tails)] of one class. Keep the type combination that lands exactly
    once in every instance that has candidates, and apply its values. Returns how many assets
    got values."""
    common = None
    for _a, hits in assets_tails:
        ok = {c for c, v in hits.items() if len(v) == 1}
        if hits:
            common = ok if common is None else common & ok
    if not common:
        return 0
    combo = sorted(common, key=lambda c: [PLAIN_TYPES.index(t) for t in c[1]])[0]
    n = 0
    for a, hits in assets_tails:
        if combo in hits and len(hits[combo]) == 1:
            a.props.update(hits[combo][0])
            n += 1
    return n


def fix_id_index(a):
    """Classes solved without an ID anchor: the ID is the string property that looks like a
    PersistenceID and is followed by another string (InternalName)."""
    if a.k is not None:
        return
    for i, v in sorted(a.props.items()):
        if S.is_persistence_id(v) and isinstance(a.props.get(i + 1), str):
            a.k = i
            return


# --- value helpers ----------------------------------------------------------------------------

def tag_name(v):
    """Gameplay tag struct {0: V8} -> 'A.B.C'."""
    if isinstance(v, dict) and isinstance(v.get(0), decode.V8):
        return v[0].name or ""
    return ""


def obj_asset(v):
    """V4 object reference -> asset name ('/Game/X/ITEM_Y.ITEM_Y' -> 'ITEM_Y')."""
    if isinstance(v, decode.V4) and v.obj:
        last = v.obj.rsplit(".", 1)[-1]
        return last[:-2] if last.endswith("_C") else last
    return None


def scan_texts(inst):
    """FText values found by pattern: StringTableEntry (history 11) into an ST_ table, or Base
    (history 0) with a 32-hex key. [(offset, text dict)] in byte order."""
    b, out = inst.b, []
    for m in re.finditer(rb"[\x00-\x1f]\x00\x00\x00\x0b", b[:inst.end]):
        try:
            v, _ = uprops.read_text(inst, m.start())
        except _DECODE_ERRORS:
            continue
        if v["type"] == "st" and v["table"].startswith("/") and "/ST_" in v["table"] and v["key"]:
            out.append((m.start(), v))
    for m in re.finditer(rb"[\x00-\x1f]\x00\x00\x00\x00", b[:inst.end]):
        try:
            v, _ = uprops.read_text(inst, m.start())
        except _DECODE_ERRORS:
            continue
        if v["type"] == "base" and re.fullmatch(r"[0-9A-F]{32}", v["key"] or "") and v["source"]:
            out.append((m.start(), v))
    out.sort(key=lambda x: x[0])
    return out


def row_handles(inst, pkg):
    """DataTableRowHandle values by pattern: nested header 0x0500 (fields 0 and 1), an import
    from a DT_* package, then a valid FName -> [(table package, row name)]."""
    b, out = inst.b, []
    for m in re.finditer(rb"\x00\x05", b[:inst.end]):
        p = m.start() + 2
        if p + 12 > inst.end:
            break
        i = struct.unpack_from("<i", b, p)[0]
        if not (-len(pkg.imports) <= i < 0):
            continue
        kind, v = pkg.resolve(pkg.imports[-i - 1])
        if kind != 2 or not v[0] or "/DT_" not in v[0]:
            continue
        try:
            name, _ = uprops.read_name(inst, p + 4)
        except uprops.Fail:
            continue
        out.append((v[0], name))
    return out


def ai_row_names(gd):
    """Row names of the game's DT_AIData* tables (their packages' name maps hold the row names)."""
    rows = {}
    for rel in gd.files:
        if "/Gameplay/AI/DT_AIData" in rel:
            pk = gd.package(rel)
            rows.update({n: rel for n in pk.names if "/" not in n and "." not in n})
    rows.setdefault("", "")
    return rows


def ai_row(a, rows):
    """AIDataTableRowHandle.RowName: written whole (DataTable reference + RowName) or, in a
    Blueprint CDO that inherits the table, as RowName only. The FName must be a row name of one
    of the DT_AIData* tables."""
    inst = a.inst()
    found = [r for t, r in row_handles(inst, a.pkg) if ("/DT_AI" in t or "AIData" in t) and r in rows]
    for p in range(inst.end + 1):
        try:
            name, _ = uprops.read_name(inst, p)
        except uprops.Fail:
            continue
        if name in rows and name != "None":
            found.append(name)
    return found[0] if found else None


# --- derivation -------------------------------------------------------------------------------

def derive_items(assets, strings):
    """The items list (items.json shape, plus '_asset'), sorted by (name, id)."""
    out = []
    for a in assets:
        if not (a.base.startswith("ITEM_") or a.base.startswith("DA_Consumab")):
            continue
        if not a.chain or not rules.is_item_type(a.cls) or a.k is None:
            continue
        pid = a.pid()
        if not pid:
            continue
        sh = a.k - ITEM_ID
        p = a.props
        name = strings.text(p.get(ITEM_NAME + sh))
        stack = p.get(ITEM_STACK + sh)
        dur = p.get(ITEM_DURABILITY + sh)
        filters = [x.name for x in (p.get(ITEM_FILTERS + sh) or []) if isinstance(x, decode.V8) and x.name]
        out.append(rules.make_item(
            pid, name, a.cls, a.internal(), a.base,
            max_stack=stack.i if isinstance(stack, decode.V4) else 1,
            durability=dur.i if isinstance(dur, decode.V4) else None,
            category_tag=tag_name(p.get(ITEM_CATEGORY + sh)), filters=filters,
            retired=rules.is_retired(a.package, a.soft_deleted()), source=a.package))
    return rules.finish_items(out)


def _first_text(a, strings):
    """The first FText property (index order) that resolves; for partly decoded assets, the
    first FText found by the byte scan."""
    texts = [v for _i, v in sorted(a.props.items())
             if isinstance(v, dict) and v.get("type") in ("st", "base", "none")]
    if not texts and a.partial:
        texts = [v for _, v in scan_texts(a.inst())]
    for v in texts:
        t = strings.text(v)
        if t:
            return t
    return None


def _display_name(a, strings):
    i = NAME_FIELD.get(a.cls)
    if i is not None and a.k is not None and not a.partial:
        return strings.text(a.props.get(a.k + i))
    return _first_text(a, strings)


def _max_level(a):
    i = MAX_LEVEL_FIELD.get(a.cls)
    if i is None or a.k is None:
        return None
    v = a.props.get(a.k + i)
    return v.i if isinstance(v, decode.V4) else None


def derive_unlocks(assets, items, strings, gd):
    """{section: {id: entry}} (unlock_names.json shape). `items` still carry '_asset'."""
    out = {s: {} for s in rules.UNLOCK_SECTIONS}
    item_by_asset = {it["_asset"]: it for it in items}
    vestige_for_recipe = {}
    for a in assets:  # patterns/vestiges -> the recipes they teach (an array of recipe refs)
        if a.cls == "BP_Consumables_RecipeUnlocker2_C" and a.k is not None and a.pid():
            for v in a.props.values():
                if isinstance(v, list):
                    for x in v:
                        r = obj_asset(x)
                        if r and r.startswith(("RECIPE_", "DA_Recipe")):
                            vestige_for_recipe.setdefault(
                                r, strings.text(a.props.get(a.k - ITEM_ID + ITEM_NAME)))
    rows = None
    for a in sorted(assets, key=lambda x: x.rel):
        pid = a.pid()
        if not pid:
            continue
        path, base, cls, k = a.package, a.base, a.cls, a.k
        retired = rules.is_retired(path, a.soft_deleted())
        if cls in ("RecipeData", "RuneRecipeData"):
            created = a.props.get(k + RECIPE_FIELDS["items_created"]) if not a.partial else None
            out_asset = None
            if isinstance(created, list) and created and isinstance(created[0], dict):
                out_asset = obj_asset(created[0].get(0))
            skill = obj_asset(a.props.get(k + RECIPE_FIELDS["skill"])) if not a.partial else None
            e = rules.recipe_entry(path, base, item_by_asset.get(out_asset), skill,
                                   vestige_for_recipe.get(base), retired)
            out["RecipesUnlocked"][pid] = e
        elif cls == "BuildingPieceData":
            out["BuildingsUnlocked"][pid] = rules.building_entry(path, base, _display_name(a, strings), retired)
        elif "/PlayerHooks/" in path:
            out["PlayerHooksTriggered"][pid] = rules.player_hook_entry(path, base, a.export.name, a.internal())
        elif base.startswith("USD_"):
            icon = next((n for n in a.pkg.names if n.startswith("T_Icon_Tag_Skill_")), "")
            out["SpellsUnlocked"][pid] = rules.spell_entry(path, base, strings.text(a.props.get(SPELL_NAME)),
                                                           icon, a.internal())
        elif cls == "SkillData" or base.startswith("SKILL_"):
            out["Skills"][pid] = rules.skill_entry(path, base, _display_name(a, strings), _max_level(a), retired)
        elif cls == "SkillPerkData" or base.startswith("PerkV2_"):
            info = a.props.get(k + PERK_FIELDS["unlock"]) if not a.partial else None
            skill, lvl = "", None
            if isinstance(info, dict):
                if isinstance(info.get(0), tuple):
                    skill = info[0][1]
                if isinstance(info.get(1), decode.V4):
                    lvl = info[1].i
            name = strings.text(a.props.get(k + PERK_FIELDS["name"])) if not a.partial else None
            out["SkillPerks"][pid] = rules.perk_entry(path, base, name, skill, lvl, a.internal(), retired)
        elif base.startswith("JOURNAL_"):
            name = None
            if cls.startswith("JournalEntry") and k is not None:
                name = strings.text(a.props.get(k + JOURNAL_NAME))
            elif cls.startswith("JournalSubCategory"):
                texts = scan_texts(a.inst())
                name = strings.text(texts[-1][1]) if texts else None
            out["JournalEntries"][pid] = rules.journal_entry(path, base, name)
        elif "/Gameplay/AI/" in path:
            if rows is None:
                rows = ai_row_names(gd)
            texts = scan_texts(a.inst())
            out["KilledOnceAIs"][pid] = rules.ai_entry(
                path, base, strings.text(texts[0][1]) if texts else None, ai_row(a, rows))
    return out


def derive_from_install(paks_dir, progress=None, schemas_path=None):
    """Read the installed game's containers and derive the catalog.

    Returns (items, unlocks, info). ``info`` holds counts and decode statistics, never a path;
    ``info["partial_files"]`` lists the package paths that were only partly decoded."""
    t0 = time.time()
    if progress:
        progress("open", 0, 1)
    schemas = S.load_schemas(schemas_path)
    with GameData(paks_dir) as gd:
        if progress:
            progress("open", 1, 1)
        rels = sorted(p for p in gd.files if rules.is_needed(p))
        assets, partial, unreadable = [], [], []
        for i, rel in enumerate(rels):
            try:
                a = decode_asset(gd, schemas, rel)
            except _DECODE_ERRORS as e:   # a package that cannot be parsed at all
                unreadable.append("%s: %s" % (asset_to_package(rel) or rel, e))
                a = None
            if a is not None:
                fix_id_index(a)
                if a.partial:
                    partial.append(a.package)
                assets.append(a)
            if progress and (i % 250 == 0 or i + 1 == len(rels)):
                progress("decode", i + 1, len(rels))
        if progress:
            progress("derive", 0, 1)
        by_cls = {}
        for a in assets:
            if a.tails is not None:
                by_cls.setdefault(a.cls, []).append((a, a.tails))
        tails = sum(resolve_tails(v) for v in by_cls.values())
        strings = Strings(gd)
        items = derive_items(assets, strings)
        unlocks = derive_unlocks(assets, items, strings, gd)
        for it in items:
            it.pop("_asset", None)
        if progress:
            progress("derive", 1, 1)
        info = {
            "generator": GENERATOR,
            "source": "installed game",
            "game_version": read_game_version(paks_dir),
            "asset_files": len(rels),
            "asset_bytes": gd.bytes_read,
            "string_tables": len(strings.cache),
            "fully_decoded": len(assets) - len(partial),
            "partly_decoded": len(partial),
            "item_tails_decoded": tails,
            "unparsable_files": sorted(unreadable),
            "partial_files": sorted(partial),
            "seconds": round(time.time() - t0, 1),
        }
    return items, unlocks, info
