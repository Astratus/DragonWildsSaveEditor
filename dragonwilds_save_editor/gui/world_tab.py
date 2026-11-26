"""World tab (EXPERIMENTAL): view and edit the app's FOCUSED world save (ctx.world).

The world is picked in the toolbar's World row (switch/Open/Save/Revert live there). This tab
edits ctx.world in memory and calls ctx.mark_world_dirty(); redraws come from
ctx.on_world_change. "Save world" here and the toolbar's Save both go through
ctx.write_world() -> dw_spud.WorldFile.save(): refuse while the game runs (unless confirmed),
snapshot ALL character + world saves to <editor backups folder>/pre-world-edit_*, back up the .sav as
<file>.<stamp>.pyedit.bak, write a temp file, re-parse and verify it, then replace.
World saves are NOT part of ctx.write(); the character Save button never touches them.
"""

import json
import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .context import list_worlds  # noqa: F401
from .. import lodestones as dw_lodestones
from .. import save as dw_save
from .. import spud as dw_spud

TITLE = "World save (experimental)"
BANNER = ("EXPERIMENTAL. World saves are binary and only partly understood. What these edits do "
          "in game (e.g. whether a boss respawns) is UNKNOWN. Edits stay in memory until you press "
          "\"Save world\"; saving first snapshots every character and world save, then backs up "
          "this .sav. Close the game first.")
CONFIRM_TAIL = ("\n\nThis is EXPERIMENTAL: the file stays structurally valid, but the in-game "
                "effect is unknown and the game may ignore, undo or misread it.\n\n"
                "Nothing is written yet. When you press \"Save world\", ALL character and world "
                "saves are snapshotted to the editor's backups folder (pre-world-edit_*) first, and this .sav gets "
                "its own .pyedit.bak.")


LODE_NOTE = ("Activated = listed in this world's fast-travel registry (L_World GameplayObjectRegistry."
             "Lodestones). Only the 4 fixed world lodestones can be activated/removed here. "
             "Player-built lodestones are shown read-only (grey): build/demolish them in game.")
TEMPLE_ID = "5E74232B4126EDE0BAEFF9856FFD03C6"   # starting stone (lodestones.json)
SPUD_CACHE_DIR = os.path.join(dw_save.GAME_SAVED_DIR, "SpudCache")


def spud_cache_files(folder=None):
    """Files in Saved\\SpudCache (read-only check; this editor never deletes them)."""
    folder = folder or SPUD_CACHE_DIR
    try:
        return sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
    except OSError:
        return []


def _fmt_value(p, max_raw=32):
    """Short display text for a dw_spud Property."""
    if p.type == 40:
        return p.value or "(none)"
    d = p.as_dict(max_raw)
    v = d.get("value")
    if v is None:
        return "%d bytes: %s%s" % (d["size"], d.get("raw", ""), "..." if d.get("raw_truncated") else "")
    text = repr(v) if isinstance(v, str) else str(v)
    return text if len(text) <= 200 else text[:200] + "..."


def _tag_ints(world):
    """{tag: value as int32} of the world's TaggedWorldProgressValues."""
    return {e["tag"]: e["int"] for e in world.tagged_values()}


class WorldTab(ttk.Frame):
    uses_ctx_world = True   # edits ctx.world (the toolbar's focused world), never its own copy

    def __init__(self, master, ctx, folder=None):   # folder: kept for compatibility, unused
        super().__init__(master)
        self.ctx = ctx
        self.spud_dir = SPUD_CACHE_DIR   # only ever listed, never written
        self.state_var = tk.StringVar(value="No world loaded.")
        self._build()
        ctx.on_world_change(self._fill)
        self._fill()

    @property
    def world(self):
        return self.ctx.world

    # ---- layout -----------------------------------------------------------------
    def _build(self):
        ttk.Label(self, text=BANNER, wraplength=1000, justify="left", background="#fde7e9",
                  foreground="#8a1c1c", padding=(8, 6)).pack(fill="x", padx=6, pady=(6, 2))

        bar = ttk.Frame(self, padding=(6, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Editing the focused world. Pick, open or revert it in the World row "
                            "at the top of the window.").pack(side="left")
        self.btn_save = ttk.Button(bar, text="Save world", command=self.save_world)
        self.btn_save.pack(side="right")
        self.btn_discard = ttk.Button(bar, text="Discard edits", command=self.discard)
        self.btn_discard.pack(side="right", padx=4)

        ttk.Label(self, textvariable=self.state_var, padding=(8, 0), foreground="#1a4d8f").pack(fill="x")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.nb = nb

        # Defeated bosses
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Defeated bosses")
        self.boss_list = tk.Listbox(f, height=8, exportselection=False)
        self.boss_list.pack(fill="both", expand=True)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(6, 0))
        self.btn_rm_boss = ttk.Button(b, text="Remove selected boss (experimental)...",
                                      command=self.remove_boss)
        self.btn_rm_boss.pack(side="left")
        ttk.Label(f, text="World hooks triggered (read-only):").pack(anchor="w", pady=(10, 0))
        self.hook_list = tk.Listbox(f, height=5)
        self.hook_list.pack(fill="both", expand=True)

        # Progress tags
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Progress tags")
        self.tag_tree = self._tree(f, ("tag", "int", "float", "raw"),
                                   ("Tag (TaggedWorldProgressValues)", "As int32", "As float", "Raw bytes"),
                                   (380, 90, 120, 100))
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(6, 0))
        self.btn_set_tag = ttk.Button(b, text="Set value of selected tag (experimental)...",
                                      command=self.set_tag)
        self.btn_set_tag.pack(side="left")
        ttk.Label(b, text="  Whether the game reads these 4 bytes as an int or a float is unknown; "
                          "values are written as int32.").pack(side="left")

        # Lodestones
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Lodestones (experimental)")
        ttk.Label(f, text=LODE_NOTE, wraplength=980, justify="left").pack(fill="x", pady=(0, 4))
        self.lode_tree = self._tree(f, ("name", "area", "kind", "active", "note"),
                                    ("Lodestone", "Area", "Kind", "Active", "Note"),
                                    (200, 230, 70, 60, 300), height=8)
        self.lode_tree.tag_configure("readonly", foreground="#8a8a8a")
        self.lode_tree.bind("<<TreeviewSelect>>", lambda e: self._update_buttons())
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(6, 0))
        self.btn_lode_on = ttk.Button(b, text="Activate selected (experimental)...",
                                      command=self.activate_lodestone)
        self.btn_lode_on.pack(side="left")
        self.btn_lode_off = ttk.Button(b, text="Remove selected (experimental)...",
                                       command=self.remove_lodestone)
        self.btn_lode_off.pack(side="left", padx=4)
        self.lode_status = tk.StringVar()
        ttk.Label(b, textvariable=self.lode_status).pack(side="left", padx=8)
        self._lode_rows = {}

        # Cached characters
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Cached characters")
        top = ttk.Frame(f)
        top.pack(fill="both", expand=True)
        self.char_tree = self._tree(top, ("name", "guid", "size"), ("Name", "Character GUID", "State size"),
                                    (200, 300, 100), height=5)
        self.char_tree.bind("<<TreeviewSelect>>", lambda e: self._show_char())
        self.char_text = tk.Text(f, height=16, wrap="none")
        self.char_text.pack(fill="both", expand=True, pady=(6, 0))
        self.char_text.config(state="disabled")

        # Object finder (diagnostics)
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Find objects")
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Label(b, text="Class contains:").pack(side="left")
        self.find_var = tk.StringVar()
        e = ttk.Entry(b, textvariable=self.find_var, width=40)
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda ev: self.find())
        ttk.Button(b, text="Find", command=self.find).pack(side="left")
        self.find_count = tk.StringVar()
        ttk.Label(b, textvariable=self.find_count).pack(side="left", padx=8)
        self.obj_tree = self._tree(f, ("type", "value"), ("Type", "Value"), (110, 500), show="tree headings")
        self.obj_tree.column("#0", width=420)
        self.obj_tree.heading("#0", text="Object / property")

        self._update_buttons()

    def _tree(self, parent, cols, heads, widths, height=12, show="headings"):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=cols, show=show, height=height, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="w", stretch=(c == cols[-1]))
        ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ys.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    # ---- loading ------------------------------------------------------------------
    def refresh(self):
        """Tab contract: redraw from the focused world (the character save is only read)."""
        self._fill()

    def discard(self):
        """Drop unsaved edits by reloading the focused world from disk (asks first)."""
        w = self.world
        if w is None or not w.dirty:
            return False
        if not messagebox.askyesno(TITLE, "Discard %d unsaved world edit(s)?" % len(self.ctx.world_changes()),
                                   icon="warning", default=messagebox.NO, parent=self):
            return False
        try:
            self.ctx.reload_world()
        except Exception as e:  # format errors must fail soft
            messagebox.showerror(TITLE, "Could not reload %s:\n\n%s" % (w.path, e), parent=self)
            return False
        return True

    # ---- display ---------------------------------------------------------------------
    def _update_buttons(self):
        w = self.world
        has_wpm = w is not None and w.progress_manager() is not None

        def st(btn, on):
            btn.state(["!disabled"] if on else ["disabled"])
        st(self.btn_save, w is not None and w.dirty)
        st(self.btn_discard, w is not None and w.dirty)
        st(self.btn_rm_boss, has_wpm and bool(self._safe(w.defeated_bosses)))
        st(self.btn_set_tag, has_wpm and bool(self._safe(w.tagged_values)))
        row = self._selected_lodestone()
        editable = w is not None and row is not None and row["editable"]
        st(self.btn_lode_on, editable and not row["registered"])
        st(self.btn_lode_off, editable and row["registered"])

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:   # undecodable/missing progress records: treat as empty
            return None

    def _fill(self):
        w = self.world
        for lb in (self.boss_list, self.hook_list):
            lb.delete(0, "end")
        for t in (self.tag_tree, self.char_tree, self.obj_tree):
            t.delete(*t.get_children())
        self._set_char_text("")
        self._fill_lodestones()
        if w is None:
            self.state_var.set("No world loaded. Pick one in the World row at the top of the window.")
            self._update_buttons()
            return
        try:
            bosses, hooks, tags = w.defeated_bosses(), w.world_hooks(), w.tagged_values()
            chars = w.cached_characters()
        except Exception as e:
            self.state_var.set("Could not decode world progress: %s" % e)
            self._update_buttons()
            return
        for n in bosses or []:
            self.boss_list.insert("end", n)
        if not bosses:
            self.boss_list.insert("end", "(no defeated bosses recorded)")
        for h in hooks:
            self.hook_list.insert("end", h)
        for i, e in enumerate(tags):
            self.tag_tree.insert("", "end", iid="t%d" % i,
                                 values=(e["tag"], e["int"], "%g" % e["float"], e["value"].hex()))
        self._chars = chars
        for i, c in enumerate(chars):
            self.char_tree.insert("", "end", iid="c%d" % i,
                                  values=(c["name"], c["guid"], "%d chars" % len(c["json"] or "")))
        state = "%s - %s: %d objects in %d levels" % (
            w.world_name() or "?", os.path.basename(w.path), w.object_count(), len(w.levels))
        if w.progress_manager() is None:
            state += " | no WorldProgressManager"
        if w.dirty:
            state += " | UNSAVED WORLD EDITS: " + "; ".join(self.ctx.world_changes())
        self.state_var.set(state)
        self._update_buttons()

    def _fill_lodestones(self):
        self.lode_tree.delete(*self.lode_tree.get_children())
        self._lode_rows = {}
        self.lode_status.set("")
        if self.world is None:
            return
        try:
            rows = dw_lodestones.list_lodestones(self.world)
        except Exception as e:  # fail soft: the rest of the tab still works
            self.lode_status.set("Could not decode lodestones: %s" % e)
            return
        # Fixed (catalogued) stones first in catalog order, then the read-only rest.
        order = {c["id"]: i for i, c in enumerate(dw_lodestones.load_catalog()["lodestones"])}
        rows.sort(key=lambda r: (0, order[r["id"]]) if r["kind"] == "world" and r["id"] in order
                  else (1, r["registry_index"] if r["registry_index"] is not None else 1e9))
        nb = 0
        for r in rows:
            fixed = r["kind"] == "world" and r["id"] in order
            r["editable"] = fixed
            if fixed:
                note = "; ".join(r["issues"])
            elif r["kind"] == "built":
                nb += 1
                note = "build/demolish in game"
                r["name"] = "Built lodestone #%d" % nb
            else:
                note = "read-only; " + "; ".join(r["issues"])
            area = r["area"] or ("cell %s" % r["cell"] if r["cell"] else "")
            iid = "L" + r["id"]
            self.lode_tree.insert("", "end", iid=iid, tags=() if fixed else ("readonly",),
                                  values=(r["name"], area, "fixed" if fixed else r["kind"],
                                          "yes" if r["registered"] else "no", note))
            self._lode_rows[iid] = r
        s = dw_lodestones.summary(rows)
        self.lode_status.set("%d/%d fixed active, %d built" % (s["world_registered"], s["world_total"], s["built"]))

    def _selected_lodestone(self):
        sel = self.lode_tree.selection() if hasattr(self, "lode_tree") else ()
        return self._lode_rows.get(sel[0]) if sel else None

    def _pick_lodestone(self, lodestone_id):
        if lodestone_id is not None:
            row = self._lode_rows.get("L" + str(lodestone_id).upper())
            if row is None:
                messagebox.showerror(TITLE, "%s is not listed in this world." % lodestone_id, parent=self)
            return row
        row = self._selected_lodestone()
        if row is None:
            messagebox.showinfo(TITLE, "Select a lodestone first.", parent=self)
        return row

    def _gate_warning(self, row):
        """Text about the quest that gates the lodestone's area, or ''."""
        area = (row.get("area") or "").split(" / ")[0]
        try:
            from .. import map as dw_map
            from .. import questline as dw_questline
            a = dw_map.area(dw_map.load_map_data(), area)
            names = dw_questline.load().get("quest_names", {})
        except Exception:
            return ""
        qid = a.get("gated_by_quest") if a else None
        if not qid:
            return ""
        qname = names.get(qid, qid)
        save = self.ctx.save
        who = None
        if save is not None:
            try:
                who = save.root.get("meta_data", {}).get("char_name") or os.path.basename(save.path)
            except Exception:
                who = os.path.basename(save.path or "")
        state = None
        if save is not None:
            try:
                # read-only lookup (dw_questline.quest_state would setdefault QuestProgress)
                quests = save.progress.get("QuestProgress", {}).get("Quests", [])
                q = next((q for q in quests if q.get("QuestId") == qid), None)
                state = q.get("QuestState", 0) if q else 0
            except Exception:
                state = None
        head = ("%s is quest-gated by \"%s\" (%s confidence). Teleporting there skips that gate."
                % (area, qname, a.get("gate_confidence") or "?"))
        if state is None:
            return ("QUEST GATE: %s No character is open, so whether \"%s\" is started could not be "
                    "checked. Every character in this world gets the teleport." % (head, qname))
        if state == 0:
            return ("WARNING - QUEST GATE: %s The open character (%s) has NOT started \"%s\", so this "
                    "skips progression and may confuse the quest line. Every character in this world "
                    "gets the teleport." % (head, who, qname))
        return ("Quest gate: %s The open character (%s) has started \"%s\" (state %s), but every "
                "character in this world gets the teleport." % (head, who, qname, state))

    def _lode_common_warnings(self):
        files = spud_cache_files(self.spud_dir)
        if files:
            cache = ("The game keeps a working copy of the loaded world in Saved\\SpudCache (%d file(s) "
                     "there now%s). This editor does not clear it. If the game is running or that cache "
                     "is written back over the world, this edit is lost. Close the game completely "
                     "before saving; if the change doesn't show in game, close it again and delete "
                     "Saved\\SpudCache\\* by hand, then start the game."
                     % (len(files), ", incl. L_World.lvl" if "L_World.lvl" in files else ""))
        else:
            cache = ("Saved\\SpudCache is empty. Keep the game closed until the world is saved so the "
                     "game's cache copy can't overwrite this edit.")
        return ("- The game must be CLOSED. \"Save world\" refuses while it runs.\n- " + cache +
                "\n- Nothing is written yet. \"Save world\" first snapshots ALL character and world "
                "saves to the editor's backups folder (pre-world-edit_*), backs up this .sav, then verifies the result.")

    def _lode_confirm(self, text):
        return messagebox.askyesno(TITLE, text, icon="warning", default=messagebox.NO, parent=self)

    def activate_lodestone(self, lodestone_id=None, confirm=True):
        if self.world is None:
            return None
        row = self._pick_lodestone(lodestone_id)
        if row is None:
            return None
        if not row.get("editable"):
            messagebox.showinfo(TITLE, "%s is read-only: build/demolish it in game." % row["name"], parent=self)
            return None
        if row["registered"]:
            messagebox.showinfo(TITLE, "%s is already active." % row["name"], parent=self)
            return False
        gate = self._gate_warning(row)
        text = ("Activate fixed lodestone \"%s\" (%s) in this world?\n\nEXPERIMENTAL: this adds it to the "
                "world's fast-travel list. That this is all the game needs is inferred, not observed; the "
                "stone itself may still look inactive." % (row["name"], row["area"]))
        if gate:
            text += "\n\n" + gate
        text += "\n\n" + self._lode_common_warnings()
        if confirm and not self._lode_confirm(text):
            return None
        try:
            changed = dw_lodestones.activate_lodestone(self.world, row["id"])
        except Exception as e:
            messagebox.showerror(TITLE, str(e), parent=self)
            return None
        self.ctx.mark_world_dirty("Activated lodestone %s" % row["name"])
        return changed

    def remove_lodestone(self, lodestone_id=None, confirm=True):
        if self.world is None:
            return None
        row = self._pick_lodestone(lodestone_id)
        if row is None:
            return None
        if not row.get("editable"):
            messagebox.showinfo(TITLE, "%s is read-only: build/demolish it in game." % row["name"], parent=self)
            return None
        if not row["registered"]:
            messagebox.showinfo(TITLE, "%s is not active." % row["name"], parent=self)
            return False
        text = ("Remove fixed lodestone \"%s\" (%s) from this world's fast-travel list?\n\nEXPERIMENTAL: "
                "removing may undo itself. The game probably re-registers the stone when you next touch "
                "it, or as soon as its area loads." % (row["name"], row["area"]))
        if row["id"] == TEMPLE_ID:
            text += ("\n\nThis is the starting Temple of Saradomin lodestone; it is registered even in a "
                     "brand-new world, so removing it is probably pointless.")
        text += "\n\n" + self._lode_common_warnings()
        if confirm and not self._lode_confirm(text):
            return None
        try:
            changed = dw_lodestones.deactivate_lodestone(self.world, row["id"])
        except Exception as e:
            messagebox.showerror(TITLE, str(e), parent=self)
            return None
        self.ctx.mark_world_dirty("Removed lodestone %s" % row["name"])
        return changed

    def _set_char_text(self, text):
        self.char_text.config(state="normal")
        self.char_text.delete("1.0", "end")
        self.char_text.insert("1.0", text)
        self.char_text.config(state="disabled")

    def _show_char(self):
        sel = self.char_tree.selection()
        if not sel:
            return
        c = self._chars[int(sel[0][1:])]
        text = json.dumps(c["state"], indent=2) if c["state"] is not None else (c["json"] or "")
        self._set_char_text(text)

    def find(self, limit=300):
        self.obj_tree.delete(*self.obj_tree.get_children())
        if self.world is None:
            return []
        objs = self.world.find_objects(self.find_var.get().strip())
        for i, o in enumerate(objs[:limit]):
            iid = self.obj_tree.insert("", "end", text="%s  [%s]" % (o.short_class, o.level.name),
                                       values=("spawned" if o.kind == "SPWN" else "placed", o.label))
            self._add_props(iid, o.block.props)
        self.find_count.set("%d object(s)%s" % (len(objs), " (first %d shown)" % limit if len(objs) > limit else ""))
        return objs

    def _add_props(self, parent, props):
        for p in props:
            iid = self.obj_tree.insert(parent, "end", text=p.path,
                                       values=(dw_spud.type_name(p.type), _fmt_value(p)))
            if p.component is not None:
                self._add_props(iid, p.component.props)

    # ---- edits (in memory) --------------------------------------------------------------
    def remove_boss(self, name=None, confirm=True):
        if self.world is None:
            return None
        if name is None:
            sel = self.boss_list.curselection()
            bosses = self.world.defeated_bosses()
            if not sel or sel[0] >= len(bosses):
                messagebox.showinfo(TITLE, "Select a boss in the list first.", parent=self)
                return None
            name = bosses[sel[0]]
        if confirm and not messagebox.askyesno(
                TITLE, "Remove %r from DefeatedBossesInternalNames?%s" % (name, CONFIRM_TAIL),
                icon="warning", parent=self):
            return None
        try:
            changed = self.world.remove_defeated_boss(name)
        except Exception as e:
            messagebox.showerror(TITLE, str(e), parent=self)
            return None
        if not changed:
            messagebox.showinfo(TITLE, "%s is not in the defeated-boss list." % name, parent=self)
            return False
        self.ctx.mark_world_dirty("Removed defeated boss %s" % name)
        return self.world.defeated_bosses()   # the bosses still recorded

    def set_tag(self, tag=None, value=None, confirm=True):
        if self.world is None:
            return None
        if tag is None:
            sel = self.tag_tree.selection()
            if not sel:
                messagebox.showinfo(TITLE, "Select a tag first.", parent=self)
                return None
            tag = self.tag_tree.item(sel[0], "values")[0]
        if value is None:
            cur = _tag_ints(self.world).get(tag)
            value = simpledialog.askinteger(TITLE, "New int32 value for\n%s\n(current: %s)" % (tag, cur),
                                            parent=self)
            if value is None:
                return None
        if confirm and not messagebox.askyesno(
                TITLE, "Set %s to %d?%s" % (tag, value, CONFIRM_TAIL), icon="warning", parent=self):
            return None
        try:
            old = _tag_ints(self.world).get(tag)
            self.world.set_tag_value(tag, value)
        except Exception as e:
            messagebox.showerror(TITLE, str(e), parent=self)
            return None
        self.ctx.mark_world_dirty("%s %s -> %s" % (tag, old, value))
        return old

    # ---- writing --------------------------------------------------------------------------
    def save_world(self, confirm=True):
        w = self.world
        if w is None or not w.dirty:
            return None
        if confirm and not messagebox.askyesno(
                TITLE, "Write these EXPERIMENTAL edits to\n%s?\n\n- %s\n\nFirst, ALL character and "
                "world saves are snapshotted to the editor's backups folder (pre-world-edit_*), and this file is backed up "
                "as .pyedit.bak. The result is re-read and verified before it replaces the file.\n\n"
                "Afterwards, consider deleting Saved\\SpudCache\\* so a stale cache can't shadow the edit."
                % (w.path, "\n- ".join(self.ctx.world_changes())), icon="warning", parent=self):
            return None
        force = False
        if dw_save.game_is_running():
            if not messagebox.askyesno(
                    TITLE, "Dragonwilds appears to be running and will likely overwrite the world "
                    "when it saves.\n\nWrite anyway?", icon="warning", default=messagebox.NO,
                    parent=self):
                return None
            force = True
        try:
            result = self.ctx.write_world(force=force)   # reloads ctx.world; listeners redraw
        except Exception as e:
            messagebox.showerror(TITLE, "Saving the world failed; the file was not replaced.\n\n%s" % e,
                                 parent=self)
            return None
        msg = "World saved.\n\nBackup: %s" % os.path.basename(result["backup"])
        if result.get("snapshot"):
            msg += "\nFull snapshot: %s" % result["snapshot"]
        self.ctx.status(msg.replace("\n\n", " | ").replace("\n", " | "))
        if confirm:
            messagebox.showinfo(TITLE, msg, parent=self)
        return result
