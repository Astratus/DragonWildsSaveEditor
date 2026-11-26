"""Unlocks tab: view and edit unlocked recipes, building pieces and spells.

Lists edited (all 22-char base64url IDs, under GameProgress.Progress):
  RecipesUnlocked   (badge list RecipesNew)
  BuildingsUnlocked (badge list BuildingPiecesNew)
  SpellsUnlocked    (badge list SpellsNew)
GameProgress.Spellcasting.SelectedSpells (48 equipped slots, "" = empty) is shown read-only;
locking a spell offers to blank it from those slots, keeping the list length unchanged.

Names come from the unlock-name catalog (catalog.load_catalog("unlock_names"): bundled, or
rebuilt on this machine); unknown IDs show raw. SpellsNew can also hold skill-perk IDs
(not spells): those are named from the catalog's SkillPerks table and never listed as spells.
"""

import json
import re
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .. import catalog
ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")

# label -> (unlocked list key, "new" badge list key)
KINDS = (
    ("Recipes", "RecipesUnlocked", "RecipesNew"),
    ("Buildings", "BuildingsUnlocked", "BuildingPiecesNew"),
    ("Spells", "SpellsUnlocked", "SpellsNew"),
)
KIND_BY_LABEL = {k[0]: k for k in KINDS}
STATES = ("All", "Unlocked only", "Locked only")
ALL_GROUPS = "(all groups)"
NO_GROUP = "(no group)"

COLUMNS = ("name", "group", "id", "unlocked", "new")
HEADINGS = {"name": "Name", "group": "Group", "id": "ID", "unlocked": "Unlocked", "new": "New"}
WIDTHS = {"name": 300, "group": 150, "id": 210, "unlocked": 80, "new": 60}


def is_valid_id(s):
    return bool(ID_RE.match(s or ""))


def load_names(path=None):
    """{list key: {id: {name, group, source}}}; empty dict if the catalog (or the file at
    ``path``) is missing or bad."""
    try:
        if path is None:
            data = catalog.load_catalog("unlock_names")
        else:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
    except (OSError, ValueError, catalog.CatalogError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, table in data.items():
        if isinstance(table, dict):
            out[key] = {i: (v if isinstance(v, dict) else {"name": str(v)}) for i, v in table.items()}
    return out


class UnlocksTab(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.names = load_names()
        self._names_game = ctx.game   # names are reloaded when the app reloads its catalog
        self.kind_var = tk.StringVar(value=KINDS[0][0])
        self.search_var = tk.StringVar()
        self.group_var = tk.StringVar(value=ALL_GROUPS)
        self.state_var = tk.StringVar(value=STATES[0])
        self._build()
        ctx.on_change(self.refresh)
        self.refresh()

    # ---- UI construction ------------------------------------------------------
    def _build(self):
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=6, pady=(6, 2))
        ttk.Label(top, text="List:").pack(side="left")
        box = ttk.Combobox(top, textvariable=self.kind_var, state="readonly",
                           values=[k[0] for k in KINDS], width=10)
        box.pack(side="left", padx=(4, 12))
        box.bind("<<ComboboxSelected>>", lambda e: self._kind_changed())
        ttk.Label(top, text="Search:").pack(side="left")
        ent = ttk.Entry(top, textvariable=self.search_var, width=24)
        ent.pack(side="left", padx=(4, 12))
        self.search_var.trace_add("write", lambda *a: self.refresh())
        ttk.Label(top, text="Group:").pack(side="left")
        self.group_box = ttk.Combobox(top, textvariable=self.group_var, state="readonly", width=20)
        self.group_box.pack(side="left", padx=(4, 12))
        self.group_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        sb = ttk.Combobox(top, textvariable=self.state_var, state="readonly", values=STATES, width=13)
        sb.pack(side="left")
        sb.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        btns = ttk.Frame(self)
        btns.pack(side="top", fill="x", padx=6, pady=2)
        self.buttons = []
        for text, cmd in (("Unlock selected", self.unlock_selected),
                          ("Lock selected", self.lock_selected),
                          ("Unlock all shown...", self.unlock_all_filtered),
                          ("Clear \"new\" badges", self.clear_new),
                          ("Add by ID...", self.add_by_id),
                          ("Copy ID", self.copy_id)):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side="left", padx=(0, 4))
            self.buttons.append(b)

        self.summary = ttk.Label(self, text="", foreground="gray30")
        self.summary.pack(side="top", fill="x", padx=6, pady=(2, 0))
        self.note = ttk.Label(self, foreground="gray40", text="")
        self.note.pack(side="top", fill="x", padx=6)

        body = ttk.Frame(self)
        body.pack(side="top", fill="both", expand=True, padx=6, pady=(2, 2))
        self.tree = ttk.Treeview(body, columns=COLUMNS, show="headings", selectmode="extended")
        for c in COLUMNS:
            self.tree.heading(c, text=HEADINGS[c], command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=WIDTHS[c], stretch=(c == "name"),
                             anchor="center" if c in ("unlocked", "new") else "w")
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.tag_configure("locked", foreground="gray50")
        self.tree.tag_configure("new", background="#fff4ce")
        self.tree.tag_configure("equipped", background="#dcebff")
        self.tree.bind("<Delete>", lambda e: self.lock_selected())

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Unlock selected", command=self.unlock_selected)
        self.menu.add_command(label="Lock selected", command=self.lock_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Copy ID", command=self.copy_id)
        self.tree.bind("<Button-3>", self._popup)

        self.selected_frame = ttk.LabelFrame(self, text="Equipped spell slots (SelectedSpells, read-only)")
        self.selected_text = tk.Text(self.selected_frame, height=3, wrap="word", relief="flat",
                                     background=self.winfo_toplevel().cget("background"))
        self.selected_text.pack(fill="x", padx=4, pady=2)
        self.selected_text.config(state="disabled")
        self._sort_col = "name"
        self._sort_rev = False

    # ---- data helpers -----------------------------------------------------------
    @property
    def kind(self):
        return KIND_BY_LABEL.get(self.kind_var.get(), KINDS[0])

    def _prog(self):
        return self.ctx.save.progress.setdefault("Progress", {})

    def _list(self, key, create=False):
        """The save's list for key. Missing: [] (not stored) unless create=True."""
        prog = self.ctx.save.progress.get("Progress")
        lst = prog.get(key) if isinstance(prog, dict) else None
        if isinstance(lst, list):
            return lst
        if not create:
            return []
        lst = self._prog()[key] = []
        return lst

    def _selected_spells(self):
        sc = self.ctx.save.progress.get("Spellcasting") if self.ctx.save else None
        ss = sc.get("SelectedSpells") if isinstance(sc, dict) else None
        return ss if isinstance(ss, list) else None

    def _known(self):
        return self.names.get(self.kind[1], {})

    def _known_name(self, i):
        return (self._known().get(i) or {}).get("name") or ""

    def _known_group(self, i):
        return (self._known().get(i) or {}).get("group") or ""

    def _display_name(self, i):
        return self._known_name(i) or "(unknown name)"

    def perk_name(self, i):
        """Name of a skill perk (SpellsNew can hold perk IDs), or ''."""
        return ((self.names.get("SkillPerks") or {}).get(i) or {}).get("name") or ""

    def badge_only_perks(self, new_key, unlocked):
        """'New' badges in new_key that are skill perks, not entries of this list: [(id, name)]."""
        out = []
        for i in dict.fromkeys(self._list(new_key)):
            if isinstance(i, str) and i not in unlocked and i not in self._known():
                name = self.perk_name(i)
                if name:
                    out.append((i, name))
        return out

    def _all_ids(self):
        """Union of save IDs (save order first) and known IDs."""
        seen = dict.fromkeys(self._list(self.kind[1]) if self.ctx.save else [])
        for i in self._known():
            seen.setdefault(i, None)
        return [i for i in seen if isinstance(i, str) and i]

    def _rows(self):
        """Filtered rows: list of (id, name, group, unlocked, new)."""
        if not self.ctx.save:
            return []
        unlocked = set(self._list(self.kind[1]))
        new = set(self._list(self.kind[2]))
        q = self.search_var.get().strip().lower()
        g = self.group_var.get()
        st = self.state_var.get()
        out = []
        for i in self._all_ids():
            name, grp = self._display_name(i), self._known_group(i)
            u = i in unlocked
            if st == STATES[1] and not u or st == STATES[2] and u:
                continue
            if g == NO_GROUP and grp or g not in (ALL_GROUPS, NO_GROUP) and grp != g:
                continue
            known = self._known_name(i).lower()
            if q and q not in known and q not in i.lower():
                continue
            out.append((i, name, grp, u, i in new))
        # Named entries first (alphabetical), unknown IDs after in save order.
        out.sort(key=lambda r: (not self._known_name(r[0]), self._known_name(r[0]).lower()))
        return out

    def _selected_ids(self):
        return [self.tree.set(iid, "id") for iid in self.tree.selection()]

    # ---- refresh ------------------------------------------------------------------
    def _kind_changed(self):
        self.group_var.set(ALL_GROUPS)
        self.refresh()

    def refresh(self):
        if self._names_game is not self.ctx.game:
            self.names = load_names()
            self._names_game = self.ctx.game
        self.tree.delete(*self.tree.get_children())
        for b in self.buttons:
            b.state(["!disabled"] if self.ctx.save else ["disabled"])
        if not self.ctx.save:
            self.summary.config(text="Open a save to see unlocks.")
            self.note.config(text="")
            self.group_box.config(values=[ALL_GROUPS])
            self.selected_frame.pack_forget()
            return
        label, key, new_key = self.kind
        known = self._known()
        groups = sorted({(v or {}).get("group") or "" for v in known.values()} - {""})
        self.group_box.config(values=[ALL_GROUPS] + groups + [NO_GROUP])
        if self.group_var.get() not in [ALL_GROUPS, NO_GROUP] + groups:
            self.group_var.set(ALL_GROUPS)

        rows = self._rows()
        col = COLUMNS.index(self._sort_col)
        keyf = {0: lambda r: r[1].lower(), 1: lambda r: r[2].lower(), 2: lambda r: r[0],
                3: lambda r: r[3], 4: lambda r: r[4]}[col]
        rows.sort(key=keyf, reverse=self._sort_rev)
        equipped = set(self._selected_spells() or []) if label == "Spells" else set()
        for i, name, grp, u, n in rows:
            tags = []
            if not u:
                tags.append("locked")
            if n:
                tags.append("new")
            if i in equipped:
                tags.append("equipped")
            self.tree.insert("", "end", iid=i, values=(name, grp, i, "yes" if u else "no",
                                                       "NEW" if n else ""), tags=tags)

        lst = self._list(key)
        named = sum(1 for i in set(lst) if self._known_name(i))
        self.summary.config(text="%s: %d unlocked, %d marked new, %d known names; showing %d rows."
                            % (label, len(lst), len(self._list(new_key)), len(known), len(rows)))
        note = ("Unknown IDs are shown raw. Named: %d of %d unlocked. Names come from the catalog "
                "built from the game's data." % (named, len(set(lst))))
        if not self.names:
            note = ("No unlock names: no item catalog could be loaded (Help > Update item "
                    "catalog). IDs are shown raw.")
        if label == "Spells":
            perks = self.badge_only_perks(new_key, set(lst))
            if perks:
                note += " Also marked new (skill perks, not spells): %s." % ", ".join(n for _, n in perks)
        self.note.config(text=note)
        if label == "Spells":
            ss = self._selected_spells()
            self.selected_frame.pack(side="bottom", fill="x", padx=6, pady=(2, 6))
            self.selected_text.config(state="normal")
            self.selected_text.delete("1.0", "end")
            if ss is None:
                self.selected_text.insert("1.0", "No SelectedSpells list in this save.")
            else:
                filled = ["%d: %s" % (n, self._display_name(s)) for n, s in enumerate(ss) if s]
                self.selected_text.insert("1.0", "%d of %d slots filled (blue rows). %s"
                                          % (len(filled), len(ss), "; ".join(filled)))
            self.selected_text.config(state="disabled")
        else:
            self.selected_frame.pack_forget()

    def _sort_by(self, col):
        self._sort_rev = (not self._sort_rev) if self._sort_col == col else False
        self._sort_col = col
        self.refresh()

    # ---- actions ----------------------------------------------------------------------
    def _need_save(self):
        if not self.ctx.save:
            messagebox.showinfo("Unlocks", "Open a save file first.", parent=self)
            return False
        return True

    def _unlock(self, ids):
        """Append ids not already present, keeping order. Returns the number added."""
        lst = self._list(self.kind[1], create=True)
        have = set(lst)
        added = 0
        for i in ids:
            if i not in have:
                lst.append(i)
                have.add(i)
                added += 1
        return added

    def unlock_selected(self):
        if not self._need_save():
            return
        ids = self._selected_ids()
        if not ids:
            self.ctx.status("Select rows to unlock.")
            return
        n = self._unlock(ids)
        if n:
            self.ctx.mark_dirty("Unlocked %d %s" % (n, self.kind[0].lower()))
        else:
            self.ctx.status("Already unlocked.")

    def lock_selected(self):
        if not self._need_save():
            return
        ids = set(self._selected_ids())
        if not ids:
            self.ctx.status("Select rows to lock.")
            return
        label, key, new_key = self.kind
        clear_slots = False
        ss = self._selected_spells() if label == "Spells" else None
        in_slots = [i for i in ids if ss and i in ss]
        if in_slots:
            ans = messagebox.askyesnocancel(
                "Unlocks", "%d of these spells are equipped in SelectedSpells slots:\n\n%s\n\n"
                "Also clear them from the equipped slots? (Recommended: a locked spell left "
                "equipped may confuse the game.)\n\nYes = lock and clear slots, No = lock only, "
                "Cancel = do nothing." % (len(in_slots), "\n".join(self._display_name(i) for i in in_slots)),
                icon="warning", parent=self)
            if ans is None:
                return
            clear_slots = ans
        lst, new = self._list(key), self._list(new_key)
        before = len(lst)
        lst[:] = [i for i in lst if i not in ids]
        new[:] = [i for i in new if i not in ids]
        removed = before - len(lst)
        cleared = 0
        if clear_slots:
            for n, s in enumerate(ss):
                if s in ids:
                    ss[n] = ""  # keep the list length: empty slots are ""
                    cleared += 1
        if removed or cleared:
            msg = "Locked %d %s" % (removed, label.lower())
            if cleared:
                msg += ", cleared %d equipped slot(s)" % cleared
            self.ctx.mark_dirty(msg)
        else:
            self.ctx.status("Nothing to lock.")

    def unlock_all_filtered(self):
        if not self._need_save():
            return
        ids = [r[0] for r in self._rows() if not r[3] and self._known_name(r[0])]
        if not ids:
            messagebox.showinfo("Unlocks", "No locked, known items in the current view.", parent=self)
            return
        if not messagebox.askyesno("Unlocks", "Unlock %d known %s shown in the current view?"
                                   % (len(ids), self.kind[0].lower()), parent=self):
            return
        n = self._unlock(ids)
        self.ctx.mark_dirty("Unlocked %d %s" % (n, self.kind[0].lower()))

    def clear_new(self):
        if not self._need_save():
            return
        new = self._list(self.kind[2])
        if not new:
            self.ctx.status("No \"new\" badges to clear.")
            return
        n = len(new)
        del new[:]
        self.ctx.mark_dirty("Cleared %d \"new\" badges (%s)" % (n, self.kind[0].lower()))

    def add_by_id(self, value=None):
        if not self._need_save():
            return
        if value is None:
            value = simpledialog.askstring("Add by ID", "%s ID (22-char base64url):" % self.kind[0],
                                           parent=self)
        if value is None:
            return
        value = value.strip()
        if not is_valid_id(value):
            messagebox.showerror("Unlocks", "Not a valid ID: %r\n\nIDs are 22 characters of "
                                 "A-Z, a-z, 0-9, '-' and '_'." % value, parent=self)
            return
        if self._unlock([value]):
            self.ctx.mark_dirty("Unlocked %s" % value)
        else:
            self.ctx.status("%s is already unlocked." % value)

    def copy_id(self):
        ids = self._selected_ids()
        if ids:
            self.clipboard_clear()
            self.clipboard_append("\n".join(ids))
            self.ctx.status("Copied %d ID(s)." % len(ids))

    def _popup(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
