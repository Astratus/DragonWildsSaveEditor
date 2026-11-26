"""Add Items tab: browse the item catalog and add items to the open save (in memory only).

The catalog is ctx.game.items (bundled, or rebuilt on this machine by the catalog module). If
the app reloads it (Help > Update item catalog / Reset to bundled catalog), refresh() re-indexes it.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from .context import dw_save

SECTION_CHOICES = ("Inventory", "PersonalInventory")
COUNT_SECTIONS = ("Inventory", "PersonalInventory", "Loadout")
DEBOUNCE_MS = 150

COLUMNS = (
    # key, heading, width, anchor, stretch
    ("name", "Name", 260, "w", True),
    ("category", "Category", 100, "w", False),
    ("max_stack", "Max stack", 75, "e", False),
    ("max_durability", "Max durability", 95, "e", False),
    ("tab", "Tab", 60, "w", False),
    ("in_save", "In save", 65, "e", False),
    ("id", "ID", 190, "w", False),
)


def _is_hidden_kind(item):
    return bool(item.get("retired") or item.get("placeholder_name") or item.get("derived_name"))


class CatalogTab(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self._after_id = None
        self._sort_col = "name"
        self._sort_rev = False
        self._counts = {}
        self._selected = None  # item dict

        self._indexed = None   # the ctx.game.items list the caches below were built from
        self._search_text = {}
        self._display = {}
        self._build_filters([])
        self._index_items()
        self._build_tree()
        self._build_add_panel()

        ctx.on_change(self.refresh)
        self.refresh()

    def _index_items(self):
        """Precompute lowercase search text and display name per item (once per catalog)."""
        items = self.ctx.game.items
        self._indexed = items
        self._search_text = {}
        self._display = {}
        for it in items:
            name = it["name"] + (" [%s]" % it["hint"] if it.get("hint") else "")
            self._display[it["id"]] = name
            self._search_text[it["id"]] = " ".join(
                (it["name"], it.get("hint") or "", it["id"])).lower()
        self.category_box.configure(values=["All"] + sorted({it["category"] for it in items}))
        if self._selected is not None and self._selected.get("id") not in self._display:
            self._selected = None

    # ---- layout --------------------------------------------------------------
    def _build_filters(self, categories):
        bar = ttk.Frame(self, padding=(6, 6, 6, 2))
        bar.pack(fill="x")
        ttk.Label(bar, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(bar, textvariable=self.search_var, width=30)
        self.search_entry.pack(side="left", padx=(4, 10))
        self.search_var.trace_add("write", lambda *a: self._schedule_filter())

        ttk.Label(bar, text="Category:").pack(side="left")
        self.category_var = tk.StringVar(value="All")
        self.category_box = ttk.Combobox(bar, textvariable=self.category_var, state="readonly",
                                         values=["All"] + categories, width=14)
        self.category_box.pack(side="left", padx=(4, 10))
        self.category_box.bind("<<ComboboxSelected>>", lambda e: self.apply_filter())

        self.show_hidden_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show retired/unnamed items", variable=self.show_hidden_var,
                        command=self.apply_filter).pack(side="left", padx=(0, 10))
        self.only_owned_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Only items in my save", variable=self.only_owned_var,
                        command=self.apply_filter).pack(side="left")
        self.result_label = ttk.Label(bar, text="")
        self.result_label.pack(side="right")

    def _build_tree(self):
        wrap = ttk.Frame(self, padding=(6, 2))
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in COLUMNS], show="headings",
                                 selectmode="browse")
        for key, heading, width, anchor, stretch in COLUMNS:
            self.tree.heading(key, text=heading, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", lambda e: self.add_selected())

    def _build_add_panel(self):
        panel = ttk.LabelFrame(self, text="Add to save", padding=6)
        panel.pack(fill="x", padx=6, pady=(2, 6))

        self.sel_label = ttk.Label(panel, text="Select an item above.", width=48)
        self.sel_label.grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 4))

        ttk.Label(panel, text="Count:").grid(row=1, column=0, sticky="w")
        self.count_var = tk.StringVar(value="1")
        self.count_spin = ttk.Spinbox(panel, from_=1, to=1, textvariable=self.count_var, width=8)
        self.count_spin.grid(row=1, column=1, sticky="w", padx=(4, 12))

        ttk.Label(panel, text="Slot:").grid(row=1, column=2, sticky="w")
        self.slot_var = tk.StringVar()
        ttk.Entry(panel, textvariable=self.slot_var, width=6).grid(row=1, column=3, sticky="w", padx=(4, 2))
        ttk.Label(panel, text="(blank = auto)").grid(row=1, column=4, sticky="w", padx=(0, 12))

        ttk.Label(panel, text="Section:").grid(row=1, column=5, sticky="w")
        self.section_var = tk.StringVar(value=SECTION_CHOICES[0])
        ttk.Combobox(panel, textvariable=self.section_var, values=SECTION_CHOICES,
                     state="readonly", width=17).grid(row=1, column=6, sticky="w", padx=(4, 12))

        self.add_button = ttk.Button(panel, text="Add to save", command=self.add_selected)
        self.add_button.grid(row=1, column=7, sticky="w")

        self.note_label = ttk.Label(panel, text="", foreground="#666")
        self.note_label.grid(row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))
        self.fill_max_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Quick add (double-click) fills to max stack",
                        variable=self.fill_max_var).grid(row=2, column=5, columnspan=3,
                                                          sticky="w", pady=(4, 0))
        self._update_add_state()

    # ---- data ----------------------------------------------------------------
    def _compute_counts(self):
        counts = {}
        save = self.ctx.save
        if save is None:
            return counts
        for sec in COUNT_SECTIONS:
            try:
                slots = save.slots(sec)
            except (KeyError, AttributeError):
                continue
            for _, it in slots:
                if isinstance(it, dict) and "ItemData" in it:
                    n = it.get("Count", 1)
                    counts[it["ItemData"]] = counts.get(it["ItemData"], 0) + (n if isinstance(n, int) else 1)
        return counts

    def _row_values(self, it):
        return (
            self._display[it["id"]],
            it["category"],
            it.get("max_stack") or "",
            it.get("max_durability") or "",
            it.get("inv_tab") or "bag",
            self._counts.get(it["id"], "") or "",
            it["id"],
        )

    def _sort_key(self, it):
        c = self._sort_col
        if c == "name":
            return self._display[it["id"]].lower()
        if c == "in_save":
            return self._counts.get(it["id"], 0)
        if c in ("max_stack", "max_durability"):
            return it.get(c) or 0
        if c == "tab":
            return it.get("inv_tab") or "bag"
        return str(it.get(c) or "").lower()

    # ---- filtering -----------------------------------------------------------
    def _schedule_filter(self):
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._after_id = self.after(DEBOUNCE_MS, self.apply_filter)

    def filtered_items(self):
        text = self.search_var.get().strip().lower()
        cat = self.category_var.get()
        show_hidden = self.show_hidden_var.get()
        only_owned = self.only_owned_var.get()
        st = self._search_text
        out = []
        for it in self.ctx.game.items:
            if not show_hidden and _is_hidden_kind(it):
                continue
            if cat != "All" and it["category"] != cat:
                continue
            if only_owned and not self._counts.get(it["id"]):
                continue
            if text and text not in st[it["id"]]:
                continue
            out.append(it)
        out.sort(key=lambda i: (self._sort_key(i), self._display[i["id"]].lower()), reverse=self._sort_rev)
        return out

    def apply_filter(self):
        self._after_id = None
        rows = self.filtered_items()
        keep = self._selected["id"] if self._selected else None
        tree = self.tree
        children = tree.get_children()
        if children:
            tree.delete(*children)
        insert = tree.insert
        for it in rows:
            insert("", "end", iid=it["id"], values=self._row_values(it))
        if keep and tree.exists(keep):
            tree.selection_set(keep)
            tree.focus(keep)
            tree.see(keep)
        total = len(self.ctx.game.items)
        if getattr(self.ctx.game, "catalog_missing", False):
            self.result_label.configure(text="No item catalog could be loaded (Help > Update item catalog)")
        else:
            self.result_label.configure(text="%d of %d items" % (len(rows), total))
        for key, heading, *_ in COLUMNS:
            arrow = (" ▼" if self._sort_rev else " ▲") if key == self._sort_col else ""
            tree.heading(key, text=heading + arrow)

    def sort_by(self, col):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = col in ("in_save", "max_stack", "max_durability")
        self.apply_filter()

    def refresh(self):
        if self._indexed is not self.ctx.game.items:
            self._index_items()
        self._counts = self._compute_counts()
        self.apply_filter()
        self._update_add_state()

    # ---- selection / add panel -----------------------------------------------
    def _on_select(self):
        sel = self.tree.selection()
        item = self.ctx.game.items_by_id.get(sel[0]) if sel else None
        if item is not self._selected:
            self._selected = item
            self.count_var.set("1")
        self._update_add_state()

    def _update_add_state(self):
        item = self._selected
        save_open = self.ctx.save is not None
        if item is None:
            self.sel_label.configure(text="Select an item above." if save_open
                                     else "Open a save to add items.")
            self.count_spin.configure(state="disabled")
            self.note_label.configure(text="")
            self.add_button.configure(state="disabled")
            return
        owned = self._counts.get(item["id"], 0)
        self.sel_label.configure(text="%s  (%s, tab: %s)%s" % (
            self._display[item["id"]], item["category"], item.get("inv_tab") or "bag",
            "  - you have %d" % owned if owned else ""))
        if item.get("max_durability"):
            self.count_var.set("1")
            self.count_spin.configure(state="disabled", to=1)
            self.note_label.configure(text="Gear: added at full durability (%d)." % item["max_durability"])
        else:
            self.count_spin.configure(state="normal", to=item.get("max_stack") or 999999)
            mx = item.get("max_stack")
            self.note_label.configure(text="Stacks to %d in-game." % mx if mx else "")
        self.add_button.configure(state="normal" if save_open else "disabled")

    def _on_double_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row or self.tree.identify_region(event.x, event.y) == "heading":
            return
        self.tree.selection_set(row)
        self._on_select()
        self.quick_add()

    def quick_add(self):
        item = self._selected
        if item is None:
            return False
        n = 1
        if self.fill_max_var.get() and not item.get("max_durability"):
            n = item.get("max_stack") or 1
        return self._do_add(item, n, None, self.section_var.get())

    def add_selected(self):
        item = self._selected
        if item is None:
            self._info("Select an item first.")
            return False
        if item.get("max_durability"):
            count = 1
        else:
            try:
                count = int(self.count_var.get().strip())
            except ValueError:
                self._error("Count must be a whole number.")
                return False
            if count < 1:
                self._error("Count must be at least 1.")
                return False
        slot_text = self.slot_var.get().strip()
        slot = None
        if slot_text:
            try:
                slot = int(slot_text)
            except ValueError:
                self._error("Slot must be a number, or blank for automatic placement.")
                return False
            if slot < 0:
                self._error("Slot must be 0 or higher.")
                return False
        return self._do_add(item, count, slot, self.section_var.get())

    def _do_add(self, item, count, slot, section):
        save = self.ctx.save
        if save is None:
            self._info("Open a save first.")
            return False
        count_arg = None if item.get("max_durability") else count
        try:
            try:
                used_slot, _ = save.add_item(item["id"], count=count_arg, slot=slot,
                                             section=section, allow_overstack=False)
            except ValueError:
                mx = item.get("max_stack")
                if count_arg is None or not mx or count_arg <= mx:
                    raise
                if not messagebox.askyesno(
                        "Over max stack",
                        "%s stacks to %d in-game, but you asked for %d.\n\n"
                        "Oversized stacks may be clamped or lost by the game. Add anyway?"
                        % (item["name"], mx, count_arg), parent=self):
                    return False
                used_slot, _ = save.add_item(item["id"], count=count_arg, slot=slot,
                                             section=section, allow_overstack=True)
        except LookupError:
            self._error("That item could not be found in the catalog.")
            return False
        except ValueError as e:
            self._error(self._friendly(str(e)))
            return False
        except KeyError as e:
            self._error("Unknown section: %s" % e)
            return False
        self.ctx.mark_dirty("Added %d x %s to %s slot %d" % (count if count_arg else 1, item["name"],
                                                            section, used_slot))
        return True

    @staticmethod
    def _friendly(msg):
        if "is occupied" in msg:
            return msg + ".\n\nPick another slot, or leave Slot blank to use the next free one."
        if "is full" in msg:
            return msg.replace("pass --slot", "enter a slot number")
        return msg

    def _info(self, msg):
        messagebox.showinfo("Add Items", msg, parent=self)

    def _error(self, msg):
        messagebox.showerror("Could not add item", msg, parent=self)
