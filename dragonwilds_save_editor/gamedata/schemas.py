"""Byte-level schemas of the game's native data classes (data/gamedata/schemas.json).

Native classes (``/Script/Dominion.ItemData``, ``RecipeData``, ...) keep their property
definitions in the game executable, which is never read. schemas.json instead records, per
class, how many bytes each property index takes (and the nesting), as inferred from the
instances themselves by the development tool ``python -m dragonwilds_save_editor.gamedata.infer``
(see docs/development.md). It says nothing about what a property means: field meanings are
assigned in derive.py.

File shape: {class: {"chain": [...], "instances": n, "id_index": k or null,
"schema": {"1": ["text"], "17/0": ["fix", 8], "20/e": ["fix", 8], ...}} or "error": "..."}.
"""

import json
import re

from .. import paths
from . import uprops

SCHEMAS_FILE = ("data", "gamedata", "schemas.json")
ID_RE = re.compile(rb"\x17\x00\x00\x00[A-Za-z0-9_-]{22}\x00")   # FString of 22 base64url chars
ID_TEXT_RE = re.compile(r"[A-Za-z0-9_-]{22}")
ITEM_ID = 36            # ItemData's PersistenceID index (a subclass shifts it by its own count)
ITEM_PART = "_ItemDataPart"


def key_to_str(k):
    return "/".join(str(x) for x in k)


def str_to_key(s):
    return tuple(int(x) if x.lstrip("-").isdigit() else x for x in s.split("/")) if s else ()


def default_path():
    return paths.resource_path(*SCHEMAS_FILE)


def load_raw(path=None):
    with open(path or default_path(), encoding="utf-8") as f:
        return json.load(f)


def load_schemas(path=None, raw=None):
    """{class: (schema {key tuple: type tuple}, id index or None)} for every solved class, plus
    ITEM_PART: the ItemData part merged from all item classes (see item_part_schema)."""
    raw = raw if raw is not None else load_raw(path)
    out = {}
    for cls, d in raw.items():
        if d.get("schema"):
            out[cls] = ({str_to_key(k): tuple(v) for k, v in d["schema"].items()}, d.get("id_index"))
    out[ITEM_PART] = (item_part_schema(out), ITEM_ID)
    return out


def is_item_class(cls):
    from ..catalog import is_item_type
    return cls == "ItemData" or is_item_type(cls)


def item_part_schema(schemas):
    """The ItemData part (indices 0..) merged from every solved item class: each class only
    shows the fields its own instances set. Unversioned properties are ordered own fields first,
    then the parent's, so a subclass's ItemData part is shifted by (its ID index - ITEM_ID).
    Classes whose layout is not "own fields, then ItemData's" are skipped; indices with
    conflicting types are dropped."""
    merged, bad = {}, set()
    base = schemas.get("ItemData", ({}, ITEM_ID))[0]
    for cls, (sch, k) in schemas.items():
        if cls == ITEM_PART or k is None or not is_item_class(cls):
            continue
        sh = k - ITEM_ID
        if any(sch.get((key[0] + sh,) + key[1:], t) != t for key, t in base.items()):
            continue
        for key, t in sch.items():
            i = key[0] - sh
            if i < 0:
                continue
            nk = (i,) + key[1:]
            if nk in merged and merged[nk] != t:
                bad.add(nk)
            merged[nk] = t
    for nk in bad:
        merged.pop(nk, None)
    return merged


def find_id(inst):
    """Offset of the PersistenceID FString, or None: a 22-char base64url FString followed by
    another FString (InternalName) and at most 16 more bytes. The InternalName can itself be 22
    characters long; then the first of the two adjacent matches is the ID."""
    found = []
    for m in ID_RE.finditer(inst.b, 0, inst.end):
        try:
            _, q = uprops.read_str(inst, m.end())
        except uprops.Fail:
            continue
        if 0 <= inst.end - q <= 16:
            found.append(m.start())
    return found[0] if len(found) == 1 else None


def is_persistence_id(v):
    return isinstance(v, str) and ID_TEXT_RE.fullmatch(v) is not None
