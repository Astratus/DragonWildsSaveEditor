"""Development tool: infer byte-level schemas of the game's native classes (schemas.json).

    python -m dragonwilds_save_editor.gamedata.infer --game-dir <install> [--only CLASS] [--seconds 40]

Run it after a game patch when ``catalog build`` reports a low decoded share (see
docs/development.md). It is not used at runtime.

Native classes keep their property definitions in the game executable, which is never read.
Instead, all instances of a class are parsed jointly, property index by property index: for
each index a byte-level type is chosen from a small grammar, and every instance must then parse
to exactly the end of its export (and, where present, the PersistenceID string, located by
pattern, must start exactly where the property it belongs to starts). Wrong choices fail
quickly (bad string lengths, bad FText history, bad header, running past the end) and the
search backtracks to the latest decision. Fields the unversioned writer zero-masks never appear
as written values, which is used as a filter.

Types are those of decode.py. The result records how many bytes each property index takes, not
what it means; meanings are assigned in derive.py.
"""

import argparse
import collections
import json
import re
import struct
import sys
import time

from .. import catalog
from . import install, schemas as S, uprops
from .derive import base_name, export_inst
from .game import GameData
from .uprops import Fail, read_soft, read_str, read_text

_i32 = uprops.i32_at
DEADLINE = [None]  # absolute time.time() after which every search gives up

TOP_CANDIDATES = [("text",), ("soft",), ("str",), ("fix", 4), ("fix", 8), ("arr",), ("struct",),
                  ("fix", 1), ("fix", 16), ("fix", 24), ("fix", 12), ("map",), ("fix", 2), ("fix", 32)]
ELEM_CANDIDATES = [("soft",), ("str",), ("text",), ("struct",), ("fix", 8), ("fix", 4), ("fix", 16),
                   ("fix", 24), ("fix", 1), ("fix", 12), ("arr",)]
KEY_CANDIDATES = [("fix", 8), ("fix", 4), ("str",), ("fix", 1), ("struct",), ("fix", 16)]


def _nice4(inst, b, p):
    i = struct.unpack_from("<i", b, p)[0]
    if -inst.n_imports <= i <= inst.n_exports:
        return 1.0
    if -100000 < i < 1000000:
        return 0.9
    f = struct.unpack_from("<f", b, p)[0]
    if f == f and 1e-4 < abs(f) < 1e7:
        r = f * 100
        return 0.9 if abs(r - round(r)) < 1e-3 else 0.6
    return 0.0


def _nice8(inst, b, p):
    i, n = struct.unpack_from("<II", b, p)
    if i < len(inst.names) and n == 0:
        return 1.0
    if i < len(inst.names) and n < 1000:
        return 0.8
    d = struct.unpack_from("<d", b, p)[0]
    if d == d and 1e-6 < abs(d) < 1e9:
        return 0.6
    q = struct.unpack_from("<q", b, p)[0]
    return 0.5 if 0 < q < 1 << 40 else 0.0


def _nice_start(inst, p):
    """How plausible is offset p as the start of the next value (or the end)?"""
    if p == inst.end:
        return 1.0
    if p > inst.end:
        return 0.0
    if p + 4 <= inst.end:
        i = struct.unpack_from("<i", inst.b, p)[0]
        if -inst.n_imports <= i <= 64 or (0 < i < 300 and p + 4 + i <= inst.end):
            return 1.0
        if p + 2 <= inst.end:
            h = struct.unpack_from("<H", inst.b, p)[0]
            if h & 0x100 and (h >> 9) <= 40 and (h & 0x7F) < 64:
                return 0.9
        return _nice4(inst, inst.b, p) * 0.8
    return 0.5


def score_candidate(search, key, t, jobs, field):
    """Mean plausibility of reading type t at every job (0 if any job fails)."""
    try:
        newp = Search.value(_Probe(search), key, t, jobs, field)
    except (Fail, _Stop):
        return -1.0
    except Exception:
        return -1.0
    tot = 0.0
    for (inst, p), q in zip(jobs, newp):
        kind = t[0]
        if kind == "fix":
            n = t[1]
            if n == 1:
                v = inst.b[p]
                sc = 1.0 if v == 1 else (0.7 if v < 32 else 0.2)
            elif n == 4:
                sc = _nice4(inst, inst.b, p)
            elif n == 8:
                sc = _nice8(inst, inst.b, p)
            elif n in (12, 16, 24, 32):
                w = 4 if n in (12, 16) else 8
                sc = min((_nice4(inst, inst.b, p + o) if w == 4 else _nice8(inst, inst.b, p + o)) for o in range(0, n, w))
                sc *= 0.9
            else:
                sc = 0.3
        elif kind in ("text", "soft", "str"):
            sc = 1.0
        else:
            sc = 0.85
        tot += 0.5 * sc + 0.5 * _nice_start(inst, q)
    return tot / max(1, len(jobs))


class _Stop(Exception):
    pass


class _Probe:
    """A throw-away view of a Search used to score one candidate: nested unknown keys get their
    first candidate without being recorded."""

    def __init__(self, search):
        self._s = search
        self.fixed = search.fixed
        self.schema = dict(search.schema)
        self.level = search.level
        self.root_len = getattr(search, "root_len", 0)
        self.depth = 0

    def typeof(self, key, cands, jobs=None, field=False):
        t = self.fixed.get(key) or self.schema.get(key)
        if t is not None:
            return t
        self.depth += 1
        if self.depth > 3:
            raise _Stop()
        cands = Search.allowed(self, key, cands)
        t = cands[0]
        self.schema[key] = t
        return t

    def value(self, key, t, jobs, field=False):
        return Search.value(self, key, t, jobs, field)

    def struct(self, key, jobs):
        return Search.struct(self, key, jobs)


class Search:
    """Chronological backtracking over lazily-made type decisions (replayed from scratch)."""

    def __init__(self, fixed=None, max_runs=20000):
        self.fixed = dict(fixed or {})  # key -> type, never revised
        self.decisions = []             # [(key, candidates, choice index)]
        self.schema = {}
        self.max_runs = max_runs
        self.fail_info = None

    level = 9  # nesting allowed for newly decided types (iterative deepening, see allowed())

    def allowed(self, key, cands):
        depth = len(key) - getattr(self, "root_len", 0)
        if self.level <= 0 or depth > self.level:
            return [c for c in cands if c[0] not in ("arr", "struct", "map")]
        return cands

    def typeof(self, key, cands, jobs=None, field=False):
        if key in self.fixed:
            return self.fixed[key]
        t = self.schema.get(key)
        if t is not None:
            return t
        if self.level < 2 and len(key) > 1 and key[:-1] in self.fixed:
            raise Fail("new field in a known struct")
        cands = self.allowed(key, cands)
        i = self._replay_i
        if jobs and i >= len(self.decisions):
            sc = [(score_candidate(self, key, c, jobs, field), -n, c) for n, c in enumerate(cands)]
            sc.sort(reverse=True)
            cands = [c for s_, _, c in sc if s_ >= 0] or [cands[0]]
        i = self._replay_i
        if i < len(self.decisions):
            k, c, ch = self.decisions[i]
            assert k == key, (k, key)
        else:
            self.decisions.append((key, cands, 0))
            ch = 0
        self._replay_i += 1
        t = cands[ch]
        self.schema[key] = t
        return t

    # -- joint parsing ------------------------------------------------------------------
    def value(self, key, t, jobs, field=False):
        """jobs: [(inst, pos)] -> new positions. field=True: a struct/class field, which the
        unversioned serializer never writes when its memory is all zero (it is zero-masked)."""
        kind = t[0]
        out = []
        if kind == "fix":
            n = t[1]
            for inst, p in jobs:
                if p + n > inst.end:
                    raise Fail("eof")
                if field and n != 8 and not any(inst.b[p:p + n]):  # FName index 0 is all-zero bytes
                    raise Fail("zero field")
                out.append(p + n)
            return out
        if kind == "str":
            if field:
                for i, p in jobs:
                    if _i32(i.b, p, i.end) == 0:
                        raise Fail("empty str field")
            return [read_str(i, p)[1] for i, p in jobs]
        if kind == "text":
            return [read_text(i, p)[1] for i, p in jobs]
        if kind == "soft":
            return [read_soft(i, p)[1] for i, p in jobs]
        if kind == "struct":
            return self.struct(key, jobs)
        if kind == "arr":
            counts, starts = [], []
            for inst, p in jobs:
                n = _i32(inst.b, p, inst.end)
                if n < 0 or n > 20000 or p + 4 + n > inst.end or (field and n == 0):
                    raise Fail("arr count")
                counts.append(n)
                starts.append(p + 4)
            pos = list(starts)
            ek = key + ("e",)
            e = 0
            while True:
                live = [j for j, n in enumerate(counts) if n > e]
                if not live:
                    break
                et = self.typeof(ek, ELEM_CANDIDATES, [(jobs[j][0], pos[j]) for j in live])
                newp = self.value(ek, et, [(jobs[j][0], pos[j]) for j in live])
                for j, np_ in zip(live, newp):
                    pos[j] = np_
                e += 1
            return pos
        if kind == "map":
            counts, pos = [], []
            for inst, p in jobs:
                rem = _i32(inst.b, p, inst.end)
                n = _i32(inst.b, p + 4, inst.end)
                if rem != 0 or n < 0 or n > 20000 or p + 8 + n > inst.end or (field and n == 0):
                    raise Fail("map")
                counts.append(n)
                pos.append(p + 8)
            e = 0
            while True:
                live = [j for j, n in enumerate(counts) if n > e]
                if not live:
                    break
                kt = self.typeof(key + ("k",), KEY_CANDIDATES, [(jobs[j][0], pos[j]) for j in live])
                newp = self.value(key + ("k",), kt, [(jobs[j][0], pos[j]) for j in live])
                vt = self.typeof(key + ("v",), ELEM_CANDIDATES)
                newp = self.value(key + ("v",), vt, [(jobs[j][0], q) for j, q in zip(live, newp)])
                for j, np_ in zip(live, newp):
                    pos[j] = np_
                e += 1
            return pos
        raise ValueError(t)

    def struct(self, key, jobs):
        heads = []
        for inst, p in jobs:
            try:
                present, q = uprops.read_header_strict(inst.b, p)
            except (struct.error, IndexError, ValueError):
                raise Fail("header")
            limit = 250 if len(key) <= 0 else 64
            if q > inst.end or (present and present[-1][0] > limit) or sum(1 for x in key if x == "e") + len(key) > 8:
                raise Fail("header")
            heads.append((present, q))
        pos = [q for _, q in heads]
        sets = [{i: z for i, z in pr} for pr, _ in heads]
        all_idx = sorted(set().union(*[set(s) for s in sets])) if sets else []
        for idx in all_idx:
            live = [j for j, s in enumerate(sets) if idx in s and not s[idx]]
            if not live:
                continue
            k = key + (idx,)
            t = self.typeof(k, TOP_CANDIDATES, [(jobs[j][0], pos[j]) for j in live], True)
            newp = self.value(k, t, [(jobs[j][0], pos[j]) for j in live], field=True)
            for j, np_ in zip(live, newp):
                pos[j] = np_
        return pos

    def run_once(self, insts, root):
        self._replay_i = 0
        self.schema = {}
        ends = self.struct(root, [(i, 0) for i in insts])
        for inst, e in zip(insts, ends):
            if e != inst.end:
                raise Fail("trailing %d bytes in %s" % (inst.end - e, inst.label))

    def solve(self, insts, root=()):
        runs = 0
        while True:
            runs += 1
            if runs > self.max_runs or (DEADLINE[0] and time.time() > DEADLINE[0]):
                raise RuntimeError("search budget exhausted (%d decisions)" % len(self.decisions))
            try:
                self.run_once(insts, root)
                out = dict(self.fixed)
                out.update(self.schema)
                return out, runs
            except Fail as e:
                self.fail_info = str(e)
                # decisions after the replay point were never reached: drop them
                del self.decisions[self._replay_i:]
                while self.decisions:
                    k, c, ch = self.decisions[-1]
                    if ch + 1 < len(c):
                        self.decisions[-1] = (k, c, ch + 1)
                        break
                    self.decisions.pop()
                else:
                    raise RuntimeError("no schema fits (last failure: %s)" % e)


class Unknown(Exception):
    pass


class StrictSearch(Search):
    """Parses with a complete schema; raises Unknown at the first key without a type."""

    def __init__(self, schema):
        super().__init__(fixed=schema)

    def typeof(self, key, cands, jobs=None, field=False):
        t = self.fixed.get(key)
        if t is None:
            raise Unknown(key)
        return t


class RangeSearch(Search):
    """DFS over the unknown top-level indices of several instances, each parsed from a known
    position over a list of indices that must end exactly at a known offset."""

    def run_once(self, jobs, root):
        self._replay_i = 0
        self.schema = {}
        # jointly, in index order
        pos = [p for _, p, _, _ in jobs]
        all_idx = sorted(set().union(*[set(ix) for _, _, ix, _ in jobs]))
        for idx in all_idx:
            if idx > getattr(self, "deepest", -1):
                self.deepest = idx
            live = [j for j, jb in enumerate(jobs) if idx in jb[2]]
            k = root + (idx,)
            t = self.typeof(k, TOP_CANDIDATES, [(jobs[j][0], pos[j]) for j in live], True)
            newp = self.value(k, t, [(jobs[j][0], pos[j]) for j in live], field=True)
            for j, np_ in zip(live, newp):
                pos[j] = np_
                if np_ > jobs[j][3]:
                    raise Fail("past gap end")
        for (inst, _, _, end), p in zip(jobs, pos):
            if p != end:
                raise Fail("gap mismatch %d in %s" % (end - p, inst.label))


def walk(schema, inst, root=()):
    """Parse an instance's top level with a known schema. Returns (present, positions dict
    idx->start, stuck_idx or None, end pos)."""
    present, p = uprops.read_header(inst.b, 0)
    s = StrictSearch(schema)
    starts = {}
    for idx, z in present:
        if z:
            continue
        starts[idx] = p
        try:
            p = s.value(root + (idx,), s.typeof(root + (idx,), None), [(inst, p)], field=True)[0]
        except Unknown:
            return present, starts, idx, p
    return present, starts, None, p


def _job(schema, inst, anchor, anchor_pos):
    """('done'|'stuck'|'bad', job). A job is (inst, start, indices to decide, gap end)."""
    try:
        present, starts, stuck, p = walk(schema, inst)
    except Fail:
        return "bad", None
    if anchor and anchor[0] in starts and id(inst) in anchor_pos and starts[anchor[0]] != anchor_pos[id(inst)]:
        return "bad", None
    if stuck is None:
        return ("done", None) if p == inst.end else ("bad", None)
    p = starts[stuck]
    nz = [i for i, z in present if not z and i >= stuck]
    end = inst.end
    if anchor and id(inst) in anchor_pos and anchor[0] in nz and anchor[0] > stuck:
        end = anchor_pos[id(inst)]
        nz = [i for i in nz if i < anchor[0]]
    return "stuck", (inst, p, nz, end)


def _solve_jobs(schema, jobs, max_runs, validate=None):
    """Solve the jobs at several nesting levels; with `validate(new) -> number of instances the
    extended schema breaks`, prefer a solution that breaks none."""
    err, best = None, None
    for level in (1, 5, 2, 0):
        rs = RangeSearch(fixed=schema, max_runs=max_runs)
        rs.level = level
        try:
            new, runs = rs.solve(jobs)
        except RuntimeError as e:
            err = e
            continue
        new = {k: v for k, v in new.items() if k not in schema}
        if validate is None:
            return new, runs
        nbad = validate(new)
        if nbad == 0:
            return new, runs
        if best is None or nbad < best[0]:
            best = (nbad, new, runs)
    if best:
        return best[1], best[2]
    raise err


def infer_class(insts, anchor=None, schema=None, max_runs=4000, log=None, max_rounds=500):
    """Infer the top-level schema of a class from all its instances.

    anchor: (property index, function(inst) -> start offset of that property's value or None).
    Rounds: walk every instance with the known types; solve the instances with the fewest
    undecided indices before their next exact boundary (anchor or end); re-walk everything; if
    an instance now fails, undo the round and solve it again with that instance included."""
    schema = dict(schema or {})
    anchor_pos = {}
    if anchor:
        for inst in insts:
            a = anchor[1](inst)
            if a is not None:
                anchor_pos[id(inst)] = a
    history = []  # [(added keys, group instances)]

    def validate(new):
        trial = dict(schema)
        trial.update(new)
        return sum(1 for inst in insts if _job(trial, inst, anchor, anchor_pos)[0] == "bad")

    extra = []
    for rnd in range(max_rounds):
        pending, bad = [], []
        for inst in insts:
            st, job = _job(schema, inst, anchor, anchor_pos)
            if st == "stuck":
                pending.append(job)
            elif st == "bad":
                bad.append(inst)
        new = None
        if not bad:
            if not pending:
                return schema
            m = min(len(j[2]) for j in pending)
            pending.sort(key=lambda j: len(j[2]))
            for extra_n in (2, 1, 0):
                jobs = [j for j in pending if len(j[2]) <= m + extra_n][:150]
                if extra_n and len(jobs) == len([j for j in pending if len(j[2]) <= m + extra_n - 1][:150]):
                    continue
                group = [j[0] for j in jobs]
                try:
                    new, runs = _solve_jobs(schema, jobs, max_runs // 3 if extra_n else max_runs, validate)
                    break
                except RuntimeError as e:
                    err = e
                bad = group[:20]
                if log:
                    log("round %d: %d instances unsolvable (e.g. %s idx %s); undoing"
                        % (rnd, len(jobs), jobs[0][0].label.rsplit("/", 1)[-1], jobs[0][2]))
        if new is None:
            if not history:
                raise RuntimeError("no schema fits %s" % bad[0].label)
            group = list(bad)[:20]
            while history:
                added, g = history.pop()
                for k in added:
                    del schema[k]
                group = (list(g) + [b for b in group if b not in g])[:240]
                if log:
                    log("round %d: undo %s, redo with %d (e.g. %s)"
                        % (rnd, added[:4], len(group), bad[0].label.rsplit("/", 1)[-1]))
                jobs = []
                for inst in group:
                    st, job = _job(schema, inst, anchor, anchor_pos)
                    if st == "stuck":
                        jobs.append(job)
                try:
                    new, runs = _solve_jobs(schema, jobs, max_runs, validate)
                    break
                except RuntimeError as e:
                    err = e
            if new is None:
                raise RuntimeError("stuck after undo at round %d: %s" % (rnd, err))
        if not new:
            raise RuntimeError("no progress at round %d" % rnd)
        if log:
            log("round %d: %d inst -> %s" % (rnd, len(jobs), new))
        schema.update(new)
        history.append((list(new), group))
    raise RuntimeError("too many rounds")


# ---------------------------------------------------------------------------
# Driver over every class the catalog reads
# ---------------------------------------------------------------------------

def collect(gd):
    """({leaf class: [Inst]}, {leaf class: class chain}) for the main export of every package
    the catalog reads."""
    by, chains = collections.defaultdict(list), {}
    for rel in sorted(x for x in gd.files if catalog.is_needed(x)):
        pk = gd.package(rel)
        e = gd.main_export(pk, base_name(rel))
        if not e:
            continue
        ch = gd.class_chain(pk, e)
        inst = export_inst(pk, e, rel)
        if inst.end != len(inst.b) and inst.b[-4:] != bytes(4):
            raise ValueError("unexpected export tail in %s" % rel)
        by[ch[0]].append(inst)
        chains[ch[0]] = ch
    return by, chains


# Hand seeds (types only, read off the bytes; see docs/research/gamedata_provenance.md). Keys are
# property indices of that class (an int stands for a top-level index).
SEEDS = {
    "HeldEquipmentData": {0:('soft',),1:('fix',4),2:('fix',4),3:('fix',4),4:('fix',4),5:('fix',4),6:('fix',4),7:('fix',4),8:('fix',1),9:('fix',4),11:('fix',4),12:('fix',4),13:('fix',4),14:('fix',4),16:('fix',8),24:('fix',4),25:('struct',),(25,0):('fix',4),(25,1):('fix',8),26:('struct',),(26,0):('fix',4),(26,1):('fix',8),27:('fix',4),28:('fix',4),29:('fix',4),30:('fix',4),31:('fix',1),33:('arr',),(33,'e'):('fix',8),35:('fix',4),36:('fix',1),37:('fix',4),39:('struct',),(39,0):('fix',8),43:('fix',1),44:('fix',4),45:('fix',4),46:('fix',4),47:('fix',4),48:('fix',4),54:('fix',1),55:('fix',1),57:('fix',1),58:('fix',1),60:('fix',4),61:('fix',4),62:('arr',),(62,'e'):('fix',4),104:('fix',1),105:('fix',1)},
    "ItemData": {
        (0,): ("fix", 4), (1,): ("text",), (2,): ("text",), (6,): ("soft",), (7,): ("soft",),
        (8,): ("soft",), (9,): ("fix", 1), (12,): ("fix", 4), (13,): ("fix", 4), (16,): ("fix", 4),
        (17,): ("struct",), (17, 0): ("fix", 8), (19,): ("struct",), (19, 0): ("fix", 8),
        (20,): ("arr",), (20, "e"): ("fix", 8), (21,): ("struct",), (21, 0): ("fix", 8),
        (24,): ("struct",), (24, 0): ("fix", 4), (24, 1): ("fix", 8), (36,): ("str",), (37,): ("str",),
    },
}

def shift_schema(schema, by):
    """Parent schema -> the same fields in a subclass whose own properties come first
    (unversioned property order follows PropertyLink: own properties, then the parent's)."""
    out = {}
    for k, v in schema.items():
        if by + k[0] < 0:
            return None
        out[(k[0] + by,) + k[1:]] = v
    return out


def _merge(a, b):
    out = dict(a)
    out.update(b)
    return out


def vote_id_index(insts):
    """Majority guess of the PersistenceID property index: where the export ends right after
    the InternalName string, the ID is the second-to-last written index (third-to-last with a
    trailing 1-byte bool)."""
    votes = collections.Counter()
    for inst in insts:
        m = S.find_id(inst)
        try:
            _, q = read_str(inst, m + 27)
        except Fail:
            continue
        present, _ = uprops.read_header(inst.b, 0)
        nz = [i for i, z in present if not z]
        tail = inst.end - q
        if tail == 0 and len(nz) >= 2:
            votes[nz[-2]] += 2
        elif tail == 1 and len(nz) >= 3:
            votes[nz[-3]] += 1
    return votes.most_common(1)[0][0] if votes else None


def try_infer(insts, parents, log=None, own=None):
    """parents: [(schema, id index)] of possible base classes (most specific first)."""
    with_id = [i for i in insts if S.find_id(i) is not None]
    common = None
    for inst in with_id:
        present, _ = uprops.read_header(inst.b, 0)
        s = {i for i, z in present if not z}
        common = s if common is None else common & s
    cands = sorted(common or [], reverse=True)
    guess = vote_id_index(with_id)
    if guess is not None:
        cands = [guess] + [c for c in cands if c != guess]
    errs = []
    for k in cands[:6] + [None]:
        anchor = (k, S.find_id) if k is not None else None
        seeds = []
        for psch, pk in parents:
            if pk is None:
                seeds.append(psch)
            elif k is not None and k >= pk:
                sh = shift_schema(psch, k - pk)
                if sh:
                    seeds.append(sh)
            if len(seeds) >= 6:
                break
        seeds.append({})
        if own:
            seeds = [_merge(sd, own) for sd in seeds]
        for seed in seeds:
            try:
                sch = infer_class(insts, anchor=anchor, schema=seed, max_runs=1500, log=log)
                if k is not None:
                    for inst in with_id[:50]:
                        _, starts, stuck, _ = walk(sch, inst)
                        if starts.get(k) != S.find_id(inst):
                            raise RuntimeError("anchor %d is not the ID" % k)
                return sch, k
            except RuntimeError as e:
                errs.append("%s%s: %s" % (k, "+seed" if seed else "", str(e)[:200]))
    raise RuntimeError("; ".join(errs))


def infer_all(gd, out=None, only=None, seconds=40.0, retry_failed=False, skip=None, log=print):
    """Infer schemas for every class (parents first) into `out` (a schemas.json dict)."""

    by, chains = collect(gd)
    out = dict(out or {})
    for cls in sorted(by, key=lambda c: (c != "ItemData", len(chains[c]), -len(by[c]))):
        if (only and cls != only) or (skip and re.search(skip, cls)):
            continue
        if retry_failed and out.get(cls, {}).get("schema"):
            continue
        insts = by[cls]
        t = time.time()
        parents = []
        for parent in chains[cls][1:]:
            if parent in out and out[parent].get("schema"):
                parents.append(({S.str_to_key(k): tuple(v) for k, v in out[parent]["schema"].items()},
                                out[parent].get("id_index")))
        # native parents are not visible in the paks: try every solved class (with an ID index)
        # as a possible parent; infer_class rejects a seed that doesn't fit.
        solved = sorted(((d["id_index"], c) for c, d in out.items()
                         if d.get("schema") and d.get("id_index") is not None and c != cls), reverse=True)
        for pk_, c in solved:
            parents.append(({S.str_to_key(k): tuple(v) for k, v in out[c]["schema"].items()}, pk_))
        own = {(k if isinstance(k, tuple) else (k,)): v for k, v in SEEDS.get(cls, {}).items()}
        res, err = None, None
        DEADLINE[0] = time.time() + seconds
        try:
            res = try_infer(insts, parents, own=own)
        except RuntimeError as e:
            err = e
        dt = time.time() - t
        if res:
            sch, k = res
            out[cls] = {"chain": chains[cls], "instances": len(insts), "id_index": k,
                        "schema": {S.key_to_str(kk): list(v)
                                   for kk, v in sorted(sch.items(), key=lambda x: str(x[0]))}}
            log("OK   %-45s %4d inst  id@%s  %d keys  %.1fs" % (cls, len(insts), k, len(sch), dt))
        else:
            out[cls] = {"chain": chains[cls], "instances": len(insts), "error": str(err)[:500]}
            log("FAIL %-45s %4d inst  %.1fs  %s" % (cls, len(insts), dt, str(err)[:150]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--game-dir", help="the game's installation folder (default: detect it)")
    ap.add_argument("--schemas", default=None, help="schemas.json to update (default: the package's)")
    ap.add_argument("--out", default=None, help="write here instead of --schemas")
    ap.add_argument("--only", help="infer only this class")
    ap.add_argument("--seconds", type=float, default=40, help="time budget per class")
    ap.add_argument("--retry-failed", action="store_true", help="only classes without a schema")
    ap.add_argument("--skip", help="regex of classes to skip (e.g. single-instance AI blueprints)")
    a = ap.parse_args(argv)
    src = a.schemas or S.default_path()
    try:
        old = S.load_raw(src)
    except (OSError, ValueError):
        old = {}
    with GameData(install.find_paks_dir(a.game_dir)) as gd:
        out = infer_all(gd, old, a.only, a.seconds, a.retry_failed, a.skip,
                        log=lambda s: (print(s), sys.stdout.flush()))
    with open(a.out or src, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
