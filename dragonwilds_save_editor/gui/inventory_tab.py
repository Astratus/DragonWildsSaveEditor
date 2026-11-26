"""Inventory tab: view and edit Inventory / PersonalInventory / Loadout slots."""

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .context import dw_save

# Display order and labels for the Inventory tab groups (slot ranges come from dw_save).
GROUPS = (
    ("hotbar", "Hotbar"),
    ("bag", "Bag"),
    ("rune", "Rune pouch"),
    ("ammo", "Ammo"),
    ("quest", "Quest"),
)
COLUMNS = ("item", "category", "qty", "max", "id")
HEADINGS = {"item": "Item", "category": "Category", "qty": "Qty/Durability",
            "max": "Max", "id": "Item ID"}
WIDTHS = {"item": 260, "category": 110, "qty": 110, "max": 70, "id": 200}


def _group_for(slot):
    for key, _ in GROUPS:
        r = dw_save.INVENTORY_TABS[key]
        if slot in r:
            return key
    if slot >= dw_save.INVENTORY_TABS["quest"].start:
        return "quest"  # Quest is open-ended (104+)
    return "bag"


class InventoryTab(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.section_var = tk.StringVar(value=dw_save.SECTIONS[0])
        self._closed_groups = set()
        self._build()
        ctx.on_change(self.refresh)
        self.refresh()

    # ---- UI construction ------------------------------------------------------
    def _build(self):
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=6, pady=(6, 2))
        ttk.Label(top, text="Section:").pack(side="left")
        self.section_box = ttk.Combobox(top, textvariable=self.section_var, state="readonly",
                                        values=dw_save.SECTIONS, width=18)
        self.section_box.pack(side="left", padx=(4, 12))
        self.section_box.bind("<<ComboboxSelected>>", lambda e: self._section_changed())
        self.summary = ttk.Label(top, text="")
        self.summary.pack(side="left")

        btns = ttk.Frame(self)
        btns.pack(side="top", fill="x", padx=6, pady=2)
        self.buttons = []
        for text, cmd in (("Set count...", self.set_count),
                          ("Repair selected", self.repair_selected),
                          ("Repair all", self.repair_all),
                          ("Remove...", self.remove_selected),
                          ("Copy item ID", self.copy_item_id)):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side="left", padx=(0, 4))
            self.buttons.append(b)
        ttk.Label(btns, text="  orange = damaged, red = over max stack",
                  foreground="gray40").pack(side="left")

        body = ttk.Frame(self)
        body.pack(side="top", fill="both", expand=True, padx=6, pady=(2, 6))
        self.tree = ttk.Treeview(body, columns=COLUMNS, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Slot")
        self.tree.column("#0", width=190, stretch=False)
        for c in COLUMNS:
            self.tree.heading(c, text=HEADINGS[c])
            self.tree.column(c, width=WIDTHS[c], stretch=(c == "item"),
                             anchor="e" if c in ("qty", "max") else "w")
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        self.tree.tag_configure("group", font=("TkDefaultFont", 9, "bold"), background="#e8e8e8")
        self.tree.tag_configure("damaged", background="#ffe0b0")
        self.tree.tag_configure("overstack", background="#ffb0b0")
        self.tree.tag_configure("pointer", foreground="gray40")
        self.tree.tag_configure("empty", foreground="gray50")

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Set count...", command=self.set_count)
        self.menu.add_command(label="Repair selected", command=self.repair_selected)
        self.menu.add_command(label="Repair all", command=self.repair_all)
        self.menu.add_separator()
        self.menu.add_command(label="Remove...", command=self.remove_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Copy item ID", command=self.copy_item_id)
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Double-1>", lambda e: self._on_double(e))
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<<TreeviewOpen>>", lambda e: self._track_open(True))
        self.tree.bind("<<TreeviewClose>>", lambda e: self._track_open(False))

    # ---- helpers ----------------------------------------------------------------
    @property
    def section(self):
        return self.section_var.get()

    def _catalog(self, it):
        return self.ctx.game.items_by_id.get(it.get("ItemData"), {}) if isinstance(it, dict) else {}

    def _status(self, msg):
        self.ctx.status(msg)

    def _row_values(self, s, it):
        """Return (values tuple, tags list) for one slot entry."""
        if "PlayerInventoryItemIndex" in it:
            return (s.describe(it), "pointer", "", "", ""), ["pointer"]
        cat = self._catalog(it)
        tags = []
        mx_dur = cat.get("max_durability")
        mx_stack = cat.get("max_stack")
        if "Durability" in it:
            dur = it["Durability"]
            qty = "%s/%s" % (dur, mx_dur or "?")
            mx = mx_dur or ""
            if mx_dur and dur < mx_dur:
                tags.append("damaged")
        elif "RemainingFillCharges" in it:
            qty = "%s charges" % it["RemainingFillCharges"]
            mx = mx_stack or ""
        else:
            n = it.get("Count", 1)
            qty = "x%s" % n
            mx = mx_stack or ""
            if mx_stack and n > mx_stack:
                tags.append("overstack")
        return (s.describe(it), cat.get("category", "?"), qty, mx, it.get("ItemData", "")), tags

    def _selected_slots(self):
        """Selected item rows as a list of int slots (group rows ignored)."""
        out = []
        prefix = self.section + ":"
        for iid in self.tree.selection():
            if iid.startswith(prefix):
                out.append(int(iid[len(prefix):]))
        return out

    def _entry(self, slot):
        return self.ctx.save.section(self.section).get(str(slot))

    def _loadout_refs(self, inv_slot):
        """Loadout slots whose PlayerInventoryItemIndex points at Inventory[inv_slot]."""
        refs = []
        for lslot, it in self.ctx.save.slots("Loadout"):
            if isinstance(it, dict) and it.get("PlayerInventoryItemIndex") == inv_slot:
                refs.append(lslot)
        return refs

    def _need_save(self):
        if self.ctx.save is None:
            messagebox.showinfo("Inventory", "Open a save first.", parent=self)
            return False
        return True

    def _need_selection(self):
        slots = self._selected_slots()
        if not slots:
            messagebox.showinfo("Inventory", "Select an item first.", parent=self)
        return slots

    # ---- refresh ---------------------------------------------------------------
    def _section_changed(self):
        self.tree.selection_set(())
        self.tree.yview_moveto(0)
        self.refresh()

    def _track_open(self, is_open):
        iid = self.tree.focus()
        if iid.startswith("grp:"):
            (self._closed_groups.discard if is_open else self._closed_groups.add)(iid)

    def refresh(self):
        selected = self.tree.selection()
        focus = self.tree.focus()
        yview = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())

        s = self.ctx.save
        state = "normal" if s else "disabled"
        for b in self.buttons:
            b.configure(state=state)
        self.section_box.configure(state="readonly" if s else "disabled")
        if s is None:
            self.summary.configure(text="No save open.")
            return

        sec_name = self.section
        sec = s.section(sec_name)
        rows = [(slot, it) for slot, it in s.slots(sec_name) if isinstance(it, dict)]
        n_damaged = n_over = 0

        parents = {}
        if sec_name == "Inventory":
            by_group = {k: [] for k, _ in GROUPS}
            for slot, it in rows:
                by_group[_group_for(slot)].append((slot, it))
            for key, label in GROUPS:
                r = dw_save.INVENTORY_TABS[key]
                last = "%d+" % r.start if key == "quest" else "%d-%d" % (r.start, r.stop - 1)
                iid = "grp:" + key
                text = "%s %s  (%d/%d used)" % (label, last, len(by_group[key]), len(r))
                self.tree.insert("", "end", iid=iid, text=text, tags=("group",),
                                 open=iid not in self._closed_groups)
                for slot, _ in by_group[key]:
                    parents[slot] = iid

        for slot, it in rows:
            values, tags = self._row_values(s, it)
            n_damaged += "damaged" in tags
            n_over += "overstack" in tags
            self.tree.insert(parents.get(slot, ""), "end", iid="%s:%d" % (sec_name, slot),
                             text=str(slot), values=values, tags=tags)

        extra = []
        if "MaxSlotIndex" in sec:
            extra.append("MaxSlotIndex %s" % sec["MaxSlotIndex"])
        if n_damaged:
            extra.append("%d damaged" % n_damaged)
        if n_over:
            extra.append("%d over max stack" % n_over)
        self.summary.configure(text="%d item(s)%s" % (len(rows), ("  |  " + ", ".join(extra)) if extra else ""))

        keep = [i for i in selected if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        if focus and self.tree.exists(focus):
            self.tree.focus(focus)
        self.tree.update_idletasks()
        self.tree.yview_moveto(yview)

    # ---- events ----------------------------------------------------------------
    def _popup(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _on_double(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and not iid.startswith("grp:"):
            self.set_count()

    # ---- actions ---------------------------------------------------------------
    def set_count(self):
        if not self._need_save():
            return
        slots = self._need_selection()
        if not slots:
            return
        slot = slots[0]
        it = self._entry(slot)
        if not isinstance(it, dict):
            return
        name = self.ctx.save.describe(it)
        if "PlayerInventoryItemIndex" in it:
            messagebox.showinfo("Set count", "Loadout slot %d is a pointer (%s), not an item."
                                % (slot, name), parent=self)
            return
        if "Durability" in it and "Count" not in it:
            messagebox.showinfo("Set count", "%s uses durability, not a count. Use Repair instead."
                                % name, parent=self)
            return
        mx = self._catalog(it).get("max_stack")
        cur = it.get("Count", 1)
        prompt = "%s (%s slot %d)\nMax stack: %s\n\nNew count:" % (
            name, self.section, slot, mx if mx else "unknown")
        n = simpledialog.askinteger("Set count", prompt, initialvalue=cur, minvalue=1, parent=self)
        if n is None or n == cur:
            return
        try:
            self.ctx.save.set_count(self.section, slot, n)
        except ValueError as e:
            if "stacks to" not in str(e):
                messagebox.showerror("Set count", str(e), parent=self)
                return
            if not messagebox.askyesno(
                    "Allow over max stack?",
                    "%s stacks to %s in-game; you asked for %d.\nOversized stacks may be clamped "
                    "or lost by the game.\n\nAllow over max stack?" % (name, mx, n), parent=self):
                return
            self.ctx.save.set_count(self.section, slot, n, allow_overstack=True)
        self.ctx.mark_dirty("%s %s[%d] -> x%d" % (name, self.section, slot, n))

    def repair_selected(self):
        if not self._need_save():
            return
        slots = self._need_selection()
        if not slots:
            return
        fixed = []
        for slot in slots:
            it = self._entry(slot)
            if not isinstance(it, dict) or "Durability" not in it:
                continue
            mx = self._catalog(it).get("max_durability")
            if mx and it["Durability"] != mx:
                it["Durability"] = int(mx)
                fixed.append(self.ctx.save.describe(it))
        if not fixed:
            messagebox.showinfo("Repair", "Nothing selected needs repair.", parent=self)
            return
        self.ctx.mark_dirty("Repaired %s" % ", ".join(fixed))

    def repair_all(self):
        if not self._need_save():
            return
        fixed = self.ctx.save.repair(self.section)
        if not fixed:
            messagebox.showinfo("Repair", "Nothing in %s needs repair." % self.section, parent=self)
            return
        self.ctx.mark_dirty("Repaired %d item(s) in %s" % (len(fixed), self.section))

    def remove_selected(self):
        if not self._need_save():
            return
        slots = self._need_selection()
        if not slots:
            return
        s = self.ctx.save
        lines, warnings, removable = [], [], []
        for slot in slots:
            it = self._entry(slot)
            if not isinstance(it, dict) or "PlayerInventoryItemIndex" in it:
                continue  # loadout pointers are not editable here
            name = s.describe(it)
            removable.append(slot)
            lines.append("  %s[%d] %s" % (self.section, slot, name))
            if self.section == "Inventory":
                for lslot in self._loadout_refs(slot):
                    warnings.append("Loadout slot %d points at Inventory[%d] (%s); it will be left "
                                    "pointing at an empty slot." % (lslot, slot, name))
        if not lines:
            messagebox.showinfo("Remove", "Loadout pointer rows can't be removed here.", parent=self)
            return
        text = "Remove %d item(s)?\n\n%s" % (len(lines), "\n".join(lines))
        if warnings:
            text += "\n\nWARNING:\n" + "\n".join(warnings)
        if not messagebox.askyesno("Remove", text, icon="warning" if warnings else "question",
                                   parent=self):
            return
        for slot in removable:
            s.remove(self.section, slot)
        self.ctx.mark_dirty("Removed %d item(s) from %s" % (len(lines), self.section))

    def copy_item_id(self):
        if not self._need_save():
            return
        slots = self._need_selection()
        if not slots:
            return
        ids = []
        for slot in slots:
            it = self._entry(slot)
            if isinstance(it, dict) and it.get("ItemData"):
                ids.append(it["ItemData"])
            elif isinstance(it, dict) and "PlayerInventoryItemIndex" in it:
                ref = self.ctx.save.section("Inventory").get(str(it["PlayerInventoryItemIndex"]))
                if isinstance(ref, dict) and ref.get("ItemData"):
                    ids.append(ref["ItemData"])
        if not ids:
            return
        text = "\n".join(ids)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status("Copied %s" % (text if len(ids) == 1 else "%d item IDs" % len(ids)))
