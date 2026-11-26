#!/usr/bin/env python3
"""Build a SYNTHETIC test fixture from a real character save.

    python tests/make_fixture.py <real_save.json> <out.json>

Keeps the save's STRUCTURE and game progress (quests, inventory layout, skills,
unlocks: everything the tests check) and replaces every identity field:

  * meta_data.char_name   -> "SampleHero"
  * meta_data.char_guid   -> a new random 32-hex GUID
  * worlds_playtime       -> new random world GUID keys, neutral values
  * Customization         -> every rowName set to "Default"
  * item GUIDs            -> fresh random 22-char base64url GUIDs
  * Backup                -> a new random uint32

Game IDs (items, quests, skills, recipes, level actors) are kept. Output uses the
exact UE formatting (tabs, CRLF, no BOM, no trailing newline, %.17g floats, inline
numeric arrays) via dragonwilds_save_editor.save.ue_dumps, and the result is re-parsed as a check.
"""

import os
import random
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dragonwilds_save_editor import save as dw_save  # noqa: E402

SAMPLE_NAME = "SampleHero"
NEUTRAL_PLAYTIME_BASE = 1767225600  # 2026-01-01 00:00 UTC


def _hex_guid():
    return secrets.token_hex(16).upper()


def _regen_item_guids(node):
    if isinstance(node, dict):
        if "GUID" in node and "ItemData" in node:
            node["GUID"] = dw_save.new_item_guid()
        for v in node.values():
            _regen_item_guids(v)
    elif isinstance(node, list):
        for v in node:
            _regen_item_guids(v)


def neutralise(root):
    meta = root["meta_data"]
    old_name = meta.get("char_name")
    old_guid = meta.get("char_guid")
    meta["char_name"] = SAMPLE_NAME
    meta["char_guid"] = _hex_guid()
    wp = meta.get("worlds_playtime") or {}
    meta["worlds_playtime"] = {_hex_guid(): dw_save.RawInt(str(NEUTRAL_PLAYTIME_BASE + 3600 * i))
                               for i in range(len(wp))}
    cust = root.get("Customization", {}).get("CustomizationData", {})
    for part in cust.values():
        if isinstance(part, dict) and "rowName" in part:
            part["rowName"] = "Default"
    _regen_item_guids(root.get("GameProgress", {}))
    if "Backup" in root:
        root["Backup"] = dw_save.RawInt(str(random.getrandbits(32)))
    return old_name, old_guid, list(wp)


def build(src, out):
    with open(src, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in text else "\n"
    root = dw_save.ue_loads(text)
    old_name, old_guid, old_worlds = neutralise(root)
    new_text = dw_save.ue_dumps(root, nl="\r\n")
    for secret in [old_name, old_guid] + old_worlds:
        if secret and secret.lower() in new_text.lower():
            raise SystemExit("identity value survived: %r" % secret)
    data = new_text.encode("utf-8")
    with open(out, "wb") as f:
        f.write(data)
    s = dw_save.SaveFile(out, dw_save.GameData(items=[]))   # structure only; no catalog needed
    assert s.to_bytes() == data, "fixture does not round-trip"
    print("wrote %s (%d bytes, source line endings %r)" % (out, len(data), nl))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    build(sys.argv[1], sys.argv[2])
