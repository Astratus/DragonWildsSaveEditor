"""Linear main-questline checkpoints for Dragonwilds character saves.

Rules (keep the questline linear, keep it safe):
  * The main questline is one ordered line of checkpoints (data/main_questline.json).
  * Only checkpoints marked enabled (very high confidence) can be applied.
  * Only REVERTS are allowed: the target must be behind the character's current position.
    Moving forward is left to the game, so rewards and world events happen for real.
  * Applying checkpoint C of quest Q:
      - quests before Q must already be complete; they are not touched,
      - Q's quest record is replaced by C's exact record (state, objective, ints, bools),
      - every main quest after Q is reset to the game's own "not started" form,
      - C's quest-marker locations are set or removed, QuestTrackedMain is set,
      - required inventory items are added and "picked up before" entries removed,
      - one-shot region-intro hooks that fire later in the story (hooks_remove) are removed
        from Progress.PlayerHooksTriggered so the intro cutscene plays again (docs/research/player_hooks.md).
  * Character file only. The GUI snapshots all character AND world saves before writing.
"""

import json
import os

from . import paths

DATA_PATH = paths.resource_path("data", "main_questline.json")
ABSENT = "__absent__"


class QuestlineError(Exception):
    pass


CONFIDENCE_RANK = {"low": 0, "med": 1, "medium": 1, "high": 2, "very high": 3}


def load(path=DATA_PATH):
    """Load the line. A checkpoint is enabled iff its confidence >= data["min_confidence"]
    (default "very high") and it is not explicitly marked "blocked"."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    floor = CONFIDENCE_RANK[data.get("min_confidence", "very high")]
    for c in data["checkpoints"]:
        ok = CONFIDENCE_RANK.get(c.get("confidence", "low"), 0) >= floor and not c.get("blocked")
        c["enabled"] = ok
        if not ok and not c.get("disabled_reason"):
            c["disabled_reason"] = c.get("blocked") or "Confidence is %s; the minimum is %s." % (
                c.get("confidence"), data.get("min_confidence", "very high"))
        elif ok:
            c.pop("disabled_reason", None)
    return data


def needs_ack(cp):
    """Checkpoints below 'very high' must be explicitly acknowledged before applying."""
    return CONFIDENCE_RANK.get(cp.get("confidence", "low"), 0) < CONFIDENCE_RANK["very high"]


def inference_text(cp):
    """What kept this checkpoint below very high: the 'inference' field, else its open questions."""
    if cp.get("inference"):
        return cp["inference"]
    oq = cp.get("open_questions") or []
    return " ".join(oq) if oq else "No inference was recorded for this checkpoint."


def related_ids(data, qid):
    """Other save rows that belong to the same main quest (e.g. First Steps has 4)."""
    return data.get("related_quest_ids", {}).get(qid, [])


# ---- save helpers ------------------------------------------------------------------

def _qp(save):
    return save.progress.setdefault("QuestProgress", {})


def find_quest(save, qid):
    return next((q for q in _qp(save).get("Quests", []) if q.get("QuestId") == qid), None)


def quest_state(save, qid):
    q = find_quest(save, qid)
    return q.get("QuestState", 0) if q else 0


def _vars(q, kind):
    return {v["QuestVariableName"]: v["QuestVariableValue"] for v in q.get(kind, [])}


def _rebuild(existing, wanted):
    """Ordered [{QuestVariableName, QuestVariableValue}] = wanted, keeping existing order first."""
    out, seen = [], set()
    for v in existing:
        n = v.get("QuestVariableName")
        if n in wanted and n not in seen:
            out.append({"QuestVariableName": n, "QuestVariableValue": wanted[n]})
            seen.add(n)
    for n, val in wanted.items():
        if n not in seen:
            out.append({"QuestVariableName": n, "QuestVariableValue": val})
    return out


def _location(save, loc_id):
    for loc in _qp(save).get("QuestLocations", []):
        if loc.get("QuestLocationId") == loc_id:
            return loc.get("QuestLocationsState")
    return ABSENT


# ---- position on the line -----------------------------------------------------------

def checkpoint(data, cid):
    for c in data["checkpoints"]:
        if c["id"] == cid:
            return c
    raise KeyError(cid)


def active_quest(save, data):
    """(index, quest_id) of the first main quest that is not complete; (len, None) if all done."""
    order = data["main_quest_order"]
    for i, qid in enumerate(order):
        if quest_state(save, qid) != 2:
            return i, qid
    return len(order), None


def matches(save, cp):
    """True if the character's record for cp's quest equals cp's state, objective and ints."""
    q = find_quest(save, cp["quest_id"])
    if not q:
        return False
    return (q.get("QuestState") == cp["state"] and q.get("QuestObjective") == cp["objective"]
            and _vars(q, "QuestInts") == {k: v for k, v in cp.get("ints", {}).items()})


def current_checkpoint(save, data):
    """The checkpoint the save currently sits on exactly, or None."""
    for c in data["checkpoints"]:
        if matches(save, c):
            # the quest must also be the active one (linear)
            if active_quest(save, data)[1] == c["quest_id"]:
                return c
    return None


def is_behind(save, data, cp):
    """True if cp is strictly behind the character's current position."""
    order = data["main_quest_order"]
    a_idx, a_qid = active_quest(save, data)
    c_idx = order.index(cp["quest_id"])
    if c_idx < a_idx:
        return True
    if c_idx > a_idx:
        return False
    cur = current_checkpoint(save, data)
    if cur is None:
        return False  # mid-quest at an unmapped point: only earlier quests are safe targets
    ids = [c["id"] for c in data["checkpoints"]]
    return ids.index(cp["id"]) < ids.index(cur["id"])


def status(save, data, cp):
    """'current' | 'available' | 'ahead' | 'disabled' (+ reason)."""
    cur = current_checkpoint(save, data)
    if cur is not None and cur["id"] == cp["id"]:
        return "current", "The character is at this checkpoint."
    if not cp.get("enabled"):
        return "disabled", cp.get("disabled_reason", "Not very high confidence.")
    if is_behind(save, data, cp):
        problem = linearity_problem(save, data, cp)
        if problem:
            return "disabled", problem
        return "available", "Revert available."
    return "ahead", "Ahead of the character. Play forward in game; the editor only reverts."


def linearity_problem(save, data, cp):
    order = data["main_quest_order"]
    for qid in order[:order.index(cp["quest_id"])]:
        if quest_state(save, qid) != 2:
            name = data.get("quest_names", {}).get(qid, qid)
            return "%s is not complete, so the line is not linear up to this checkpoint." % name
    return None


# ---- planning & applying ------------------------------------------------------------------

def plan(save, data, cp, include_optional=False):
    """List of human-readable change lines for applying cp."""
    lines = []
    order = data["main_quest_order"]
    names = data.get("quest_names", {})
    q = find_quest(save, cp["quest_id"]) or {}
    qn = names.get(cp["quest_id"], cp["quest_id"])

    def diff(label, before, after):
        if before != after:
            lines.append("%s: %s -> %s" % (label, before, after))

    diff("%s state" % qn, q.get("QuestState"), cp["state"])
    diff("%s objective" % qn, q.get("QuestObjective"), cp["objective"])
    have_i, want_i = _vars(q, "QuestInts"), dict(cp.get("ints", {}))
    for k in sorted(set(have_i) | set(want_i)):
        diff("%s int %s" % (qn, k), have_i.get(k, ABSENT), want_i.get(k, ABSENT))
    have_b, want_b = _vars(q, "QuestBools"), _wanted_bools(cp)
    for k in sorted(set(have_b) | set(want_b)):
        diff("%s flag %s" % (qn, k), have_b.get(k, ABSENT), want_b.get(k, ABSENT))
    for rid, rec in (cp.get("related_records") or {}).items():
        rq = find_quest(save, rid) or {}
        if (rq.get("QuestState"), rq.get("QuestObjective")) != (rec["QuestState"], rec["QuestObjective"]):
            lines.append("%s (linked record %s): state %s -> %s, objective %s -> %s" % (
                qn, rid, rq.get("QuestState"), rec["QuestState"], rq.get("QuestObjective"), rec["QuestObjective"]))
    for qid in order[order.index(cp["quest_id"]) + 1:]:
        for rid in [qid] + related_ids(data, qid):
            lq = find_quest(save, rid)
            if lq and (lq.get("QuestState") != 0 or lq.get("QuestInts") or lq.get("QuestBools")):
                lines.append("%s%s: reset to not started (state %s -> 0, %d flags cleared)" % (
                    names.get(qid, qid), "" if rid == qid else " (linked record %s)" % rid,
                    lq.get("QuestState"), len(lq.get("QuestBools", []))))
    for loc, want in cp.get("locations", {}).items():
        diff("map marker %s" % loc, _location(save, loc), want)
    diff("tracked main quest", _qp(save).get("QuestTrackedMain", ABSENT), cp.get("tracked_main", ABSENT))
    for it in cp.get("inventory_add", []):
        if not _holds(save, it["id"]):
            lines.append("add item: %d x %s" % (it.get("count", 1), it.get("label", it["id"])))
    for rem in cp.get("progress_remove", []) + (cp.get("progress_remove_optional", []) if include_optional else []):
        for i in rem["ids"]:
            if i in _progress_list(save, rem["list"]):
                lines.append("remove from %s: %s" % (rem["list"], rem.get("label", i)))
    for it in cp.get("inventory_remove", []):
        if _holds(save, it["id"]):
            lines.append("remove item from inventory: %s" % it.get("label", it["id"]))
    hooks = _hooks_list(save)
    for h in cp.get("hooks_remove", []):
        if h["id"] in hooks:
            lines.append("Replay the %s (remove hook %s from PlayerHooksTriggered)" % (h.get("label", "intro"), h["id"]))
    return lines


def _hooks_list(save):
    """Progress.PlayerHooksTriggered, or [] when absent (never creates the key)."""
    lst = save.progress.get("Progress", {}).get("PlayerHooksTriggered")
    return lst if isinstance(lst, list) else []


def _as_dict(v):
    """Accept {name: value} or [{QuestVariableName, QuestVariableValue}]."""
    if isinstance(v, dict):
        return dict(v)
    return {x["QuestVariableName"]: x["QuestVariableValue"] for x in v}


def _wanted_bools(cp):
    want = {b: True for b in cp.get("bools_true", [])}
    want.update({b: False for b in cp.get("bools_false", [])})
    return want


def _holds(save, item_id):
    for sec in ("Inventory", "PersonalInventory"):
        for _, it in save.slots(sec):
            if isinstance(it, dict) and it.get("ItemData") == item_id:
                return True
    return False


def _progress_list(save, name):
    if name.startswith("Journal."):
        return save.progress.setdefault("Journal", {}).setdefault(name.split(".", 1)[1], [])
    return save.progress.setdefault("Progress", {}).setdefault(name, [])


def apply(save, data, cp, include_optional=False, acknowledged=False):
    """Apply checkpoint cp to the character save in memory. Returns the plan lines.

    High-confidence (below very high) checkpoints need acknowledged=True: the caller must
    have shown inference_text(cp) to the user and got an explicit yes."""
    if not cp.get("enabled"):
        raise QuestlineError(cp.get("disabled_reason", "Checkpoint is not enabled."))
    if needs_ack(cp) and not acknowledged:
        raise QuestlineError("This checkpoint is %s confidence and must be acknowledged first: %s"
                             % (cp.get("confidence"), inference_text(cp)))
    if not is_behind(save, data, cp):
        raise QuestlineError("Only reverts are allowed: this checkpoint is not behind the character.")
    problem = linearity_problem(save, data, cp)
    if problem:
        raise QuestlineError(problem)
    lines = plan(save, data, cp, include_optional)
    order = data["main_quest_order"]

    # 1. the checkpoint quest's record
    q = find_quest(save, cp["quest_id"])
    if q is None:
        q = {"QuestId": cp["quest_id"]}
        _qp(save).setdefault("Quests", []).append(q)
    q["QuestState"] = cp["state"]
    q["QuestObjective"] = cp["objective"]
    q["QuestInts"] = _rebuild(q.get("QuestInts", []), dict(cp.get("ints", {})))
    q["QuestBools"] = _rebuild(q.get("QuestBools", []), _wanted_bools(cp))

    # 1b. other save rows of the same quest, when the checkpoint defines them
    for rid, rec in (cp.get("related_records") or {}).items():
        rq = find_quest(save, rid)
        if rq is None:
            rq = {"QuestId": rid}
            _qp(save).setdefault("Quests", []).append(rq)
        rq["QuestState"] = rec["QuestState"]
        rq["QuestObjective"] = rec["QuestObjective"]
        rq["QuestInts"] = _rebuild(rq.get("QuestInts", []), _as_dict(rec.get("QuestInts", [])))
        rq["QuestBools"] = _rebuild(rq.get("QuestBools", []), _as_dict(rec.get("QuestBools", [])))

    # 2. later main quests (and their related rows) -> the game's own not-started form
    blank = data["not_started"]
    for qid in order[order.index(cp["quest_id"]) + 1:]:
        for rid in [qid] + related_ids(data, qid):
            lq = find_quest(save, rid)
            if lq is not None:
                lq["QuestState"] = blank["QuestState"]
                lq["QuestObjective"] = blank["QuestObjective"]
                lq["QuestInts"] = []
                lq["QuestBools"] = []

    # 3. quest-marker locations
    locs = _qp(save).setdefault("QuestLocations", [])
    for loc_id, want in cp.get("locations", {}).items():
        idx = next((i for i, l in enumerate(locs) if l.get("QuestLocationId") == loc_id), None)
        if want == ABSENT:
            if idx is not None:
                del locs[idx]
        elif idx is None:
            locs.append({"QuestLocationId": loc_id, "QuestLocationsState": want})
        else:
            locs[idx]["QuestLocationsState"] = want

    # 4. tracked main quest
    if cp.get("tracked_main"):
        _qp(save)["QuestTrackedMain"] = cp["tracked_main"]

    # 5. items the next step needs, and "picked up before" entries that would block it
    for it in cp.get("inventory_add", []):
        if not _holds(save, it["id"]):
            save.add_item(it["id"], count=it.get("count", 1))
    for rem in cp.get("progress_remove", []) + (cp.get("progress_remove_optional", []) if include_optional else []):
        lst = _progress_list(save, rem["list"])
        lst[:] = [x for x in lst if x not in rem["ids"]]
    # 6. items that must NOT be held at this checkpoint (e.g. a boss head that would auto-complete)
    for it in cp.get("inventory_remove", []):
        for sec in ("Inventory", "PersonalInventory"):
            for slot, held in list(save.slots(sec)):
                if isinstance(held, dict) and held.get("ItemData") == it["id"]:
                    save.remove(sec, slot)
    # 7. one-shot region-intro hooks that fire later in the story (so the intro plays again).
    #    Only the listed IDs are removed; absent IDs are a no-op; other hooks are untouched.
    drop = {h["id"] for h in cp.get("hooks_remove", [])}
    hooks = _hooks_list(save)
    if drop and any(x in drop for x in hooks):
        hooks[:] = [x for x in hooks if x not in drop]
    return lines
