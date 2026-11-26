#!/usr/bin/env python3
"""Build the small synthetic item catalog the tests use (tests/fixtures/catalog/).

    python tests/make_catalog_fixture.py <built catalog folder>

Most tests load this tiny subset (installed as a "user-built" catalog in the test LOCALAPPDATA,
so it takes precedence over the bundled catalog) to keep them fast and independent of catalog
regenerations; tests/test_catalog.py also loads the full bundled catalog. The subset holds
only what the tests touch:

  * items: every ItemData ID in the sample fixtures, the questline's required items and a
    few extras the tests add by name (Nature Rune, Bronze Arrow, Bronze Pickaxe, three Logs);
  * unlock names: the hooks in the questline's hooks_remove plus the sample save's
    PlayerHooksTriggered, the sample save's SpellsNew skill perks, and its spells;
  * build_info.json, which marks the catalog as complete.

Entries are game facts (IDs, names, stack sizes) derived from the game's own data; the
``source`` field is replaced by a neutral marker. Output is sorted, so a rebuild with the
same inputs is byte-identical.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dragonwilds_save_editor import catalog  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
OUT = os.path.join(FIXTURES, "catalog")
EXTRA_ITEMS = ("iKbF7k2XvufGqqyg5rK-vQ",   # Nature Rune
               "XvhWN00lBZJCFb6r0p-tMg",   # Bronze Arrow
               "V-CGfkBdlbxvc-6TkU-K_A",   # Bronze Pickaxe
               "2rxJ495rm0GDn4h5OWKiyQ",   # Ash Logs  (several "Logs": ambiguous-name test)
               "TsGMyBWLNEWhBdNu21CwCA",   # Oak Logs
               "rwa8v0ugnp7LnvGKd3V29g")   # Willow Logs
SOURCE = "test fixture (subset of a catalog built from the installed game)"


def _walk_item_ids(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "ItemData" and isinstance(v, str):
                out.add(v)
            _walk_item_ids(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_item_ids(v, out)


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def wanted():
    items, hooks, perks, spells = set(EXTRA_ITEMS), set(), set(), set()
    for name in ("sample_character.json", "sample_character_v83.json"):
        root = _load(os.path.join(FIXTURES, name))
        _walk_item_ids(root.get("GameProgress", {}), items)
        pr = root.get("GameProgress", {}).get("Progress", {})
        hooks.update(pr.get("PlayerHooksTriggered") or [])
        perks.update(pr.get("SpellsNew") or [])
        spells.update(pr.get("SpellsUnlocked") or [])
    ql = _load(os.path.join(ROOT, "dragonwilds_save_editor", "data", "main_questline.json"))
    for cp in ql["checkpoints"]:
        for key in ("inventory_add", "inventory_remove"):
            items.update(it["id"] for it in cp.get(key, []))
        hooks.update(h["id"] for h in cp.get("hooks_remove", []))
    return items, hooks, perks, spells


def build(src):
    items_all = _load(os.path.join(src, "items.json"))
    names_all = _load(os.path.join(src, "unlock_names.json"))
    info = _load(os.path.join(src, "build_info.json"))
    want_items, hooks, perks, spells = wanted()
    items = []
    for it in items_all:
        if it["id"] in want_items:
            it = dict(it, source=SOURCE)
            items.append(it)
    items.sort(key=lambda i: i["id"])
    missing = sorted(want_items - {i["id"] for i in items})
    if missing:
        print("note: not in the built catalog: %s" % ", ".join(missing))

    def pick(section, ids):
        table = names_all.get(section, {})
        return {i: dict(table[i], source=SOURCE) for i in sorted(ids) if i in table}

    names = {
        "PlayerHooksTriggered": pick("PlayerHooksTriggered", hooks),
        "SkillPerks": pick("SkillPerks", perks),
        "SpellsUnlocked": pick("SpellsUnlocked", spells),
        "Skills": pick("Skills", names_all.get("Skills", {})),
    }
    os.makedirs(OUT, exist_ok=True)
    counts = dict({"items": len(items)}, **{k: len(v) for k, v in names.items()})
    meta = {k: info[k] for k in ("format", "source", "game_version")}
    # generator_version marks the fixture as a compatible user-built catalog, so tests load it
    # instead of the bundled one.
    meta.update({"mode": "fixture", "counts": counts, "generator": catalog.GENERATOR,
                 "generator_version": catalog.GENERATOR_VERSION})
    for name, obj in (("items.json", items), ("unlock_names.json", names), ("build_info.json", meta)):
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    print("wrote %s: %s" % (OUT, counts))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(sys.argv[1])
