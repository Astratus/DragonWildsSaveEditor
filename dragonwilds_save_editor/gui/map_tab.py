"""Map tab: fog of war (revealed regions), Sanguine Urns (health shrines) and kebbit burrows.

All logic is in dw_map; this tab edits ctx.save in memory and calls ctx.mark_dirty, so the
app's normal Save (backup first, game-running check) applies. Names and areas come from
data/map_points.json when present; otherwise the built-in region table is used and unknown
IDs show as "(unknown name)". Only catalog IDs (or IDs the game already wrote) can be added.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import map as M

ALL_AREAS = "(all areas)"
NO_AREA = "(no area)"


class MapTab(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.data = M.load_map_data()
        self.area_vars = {}      # area name -> BooleanVar
        self.area_checks = {}    # area name -> Checkbutton
        self.area_counts = {}    # area name -> StringVar ("n/m")
        self.bit_frames = {}     # area name -> Frame with per-region checkbuttons
        self.bit_vars = {}       # bit -> BooleanVar
        self.shrine_search = tk.StringVar()
        self.shrine_area = tk.StringVar(value=ALL_AREAS)
        self.burrow_search = tk.StringVar()
        self.burrow_area = tk.StringVar(value=ALL_AREAS)
        self.bitmap_var = tk.StringVar()
        self._build()
        ctx.on_change(self.refresh)
        self.refresh()

    # ---- UI construction --------------------------------------------------------
    def _build(self):
        note = ("Map state stored in the character. Fog is cosmetic: regions show as discovered when you "
                "enter them, and the game never hides them again. Quest reverts do not change the map.")
        if self.data["warnings"]:
            note += "  " + " ".join(self.data["warnings"])
        ttk.Label(self, text=note, foreground="gray30", wraplength=1050, justify="left").pack(
            side="top", fill="x", padx=8, pady=(6, 2))

        # (a) fog
        fog = ttk.LabelFrame(self, text="Discovered regions (fog of war)")
        fog.pack(side="top", fill="x", padx=6, pady=4)
        top = ttk.Frame(fog)
        top.pack(fill="x", padx=4, pady=(2, 4))
        self.reveal_all_btn = ttk.Button(top, text="Reveal all", command=self.reveal_all)
        self.reveal_all_btn.pack(side="left")
        ttk.Label(top, textvariable=self.bitmap_var, foreground="gray40").pack(side="left", padx=12)
        grid = ttk.Frame(fog)
        grid.pack(fill="x", padx=4, pady=(0, 4))
        self.fog_buttons = [self.reveal_all_btn]
        for row, a in enumerate(self.data["areas"]):
            name = a["name"]
            var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(grid, text=name, variable=var, width=22,
                                  command=lambda n=name: self.toggle_area(n))
            chk.grid(row=2 * row, column=0, sticky="w")
            cnt = tk.StringVar()
            ttk.Label(grid, textvariable=cnt, width=18).grid(row=2 * row, column=1, sticky="w")
            hide = ttk.Button(grid, text="Hide area", command=lambda n=name: self.set_area(n, False))
            hide.grid(row=2 * row, column=2, padx=2)
            more = ttk.Button(grid, text="Regions...", command=lambda n=name: self.toggle_bits(n))
            more.grid(row=2 * row, column=3, padx=2)
            gate = (a.get("gate_note") or "").split(". ")[0].split(", objective")[0]
            if len(gate) > 70:
                gate = gate[:67] + "..."
            if a.get("gated_by_quest"):
                gate = "Quest gate: " + (gate or "a main quest")
            ttk.Label(grid, text=gate, foreground="gray45").grid(row=2 * row, column=4, sticky="w", padx=8)
            bf = ttk.Frame(grid)
            for k, b in enumerate(a["bits"]):
                bv = tk.BooleanVar(value=False)
                self.bit_vars[b] = bv
                c = ttk.Checkbutton(bf, text="%d: %s" % (b, M.region_name(self.data, b)), variable=bv,
                                    command=lambda b=b: self.toggle_bit(b))
                c.grid(row=k // 5, column=k % 5, sticky="w", padx=(16, 4))
                self.fog_buttons.append(c)
            bf.grid(row=2 * row + 1, column=0, columnspan=5, sticky="w")
            bf.grid_remove()
            self.area_vars[name], self.area_checks[name] = var, chk
            self.area_counts[name], self.bit_frames[name] = cnt, bf
            self.fog_buttons += [chk, hide, more]

        # (b) Sanguine Urns + (c) kebbit burrows side by side
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(side="top", fill="both", expand=True, padx=6, pady=(2, 6))
        self.shrine_tree, sb = self._list_panel(
            pane, "Sanguine Urns (health shrines)", self.shrine_search, self.shrine_area,
            ("name", "area", "unlocked", "id"), {"name": "Name", "area": "Area", "unlocked": "Used", "id": "ID"},
            (("Mark used", self.unlock_shrines), ("Remove...", self.remove_shrines)))
        self.burrow_tree, bb = self._list_panel(
            pane, "Kebbit burrows", self.burrow_search, self.burrow_area,
            ("name", "area", "found", "activated", "id"),
            {"name": "Name", "area": "Area", "found": "Found", "activated": "Activated", "id": "ID"},
            (("Toggle Found", lambda: self.toggle_burrows("found")),
             ("Toggle Activated", lambda: self.toggle_burrows("activated")),
             ("Remove", self.remove_burrows)))
        self.list_buttons = sb + bb
        ttk.Label(self, foreground="gray40", wraplength=1050, justify="left",
                  text="Sanguine Urns: each used urn gives +10 max health. Kebbit burrows: Found and Activated "
                       "are separate lists in the save (the game can list a burrow as Activated but not Found), "
                       "so each toggle changes only its own list; Remove clears both. Yellow rows are IDs not "
                       "in data/map_points.json."
                  ).pack(side="bottom", fill="x", padx=8, pady=(0, 4), before=pane)

    def _list_panel(self, pane, title, search_var, area_var, cols, heads, actions):
        frame = ttk.LabelFrame(pane, text=title)
        pane.add(frame, weight=1)
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=4, pady=2)
        ttk.Label(top, text="Search:").pack(side="left")
        ttk.Entry(top, textvariable=search_var, width=16).pack(side="left", padx=(4, 8))
        search_var.trace_add("write", lambda *a: self.refresh_lists())
        ttk.Label(top, text="Area:").pack(side="left")
        box = ttk.Combobox(top, textvariable=area_var, state="readonly", width=18,
                           values=self._area_choices())
        box.pack(side="left", padx=4)
        box.bind("<<ComboboxSelected>>", lambda e: self.refresh_lists())
        btns = ttk.Frame(frame)
        btns.pack(fill="x", padx=4, pady=2)
        buttons = []
        for text, cmd in actions:
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side="left", padx=(0, 4))
            buttons.append(b)
        summary = ttk.Label(btns, foreground="gray30")
        summary.pack(side="left", padx=8)
        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="extended", height=10)
        widths = {"name": 260, "area": 110, "unlocked": 55, "found": 55, "activated": 70, "id": 250}
        for c in cols:
            tree.heading(c, text=heads[c])
            tree.column(c, width=widths[c], stretch=(c == "name"),
                        anchor="center" if c in ("unlocked", "found", "activated") else "w")
        ysb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        tree.tag_configure("off", foreground="gray50")
        tree.tag_configure("unknown", background="#fff4ce")
        tree.summary = summary
        return tree, buttons

    def _area_choices(self):
        return [ALL_AREAS] + [a["name"] for a in self.data["areas"]] + [NO_AREA]

    # ---- refresh --------------------------------------------------------------------
    def refresh(self):
        has = self.ctx.save is not None
        for b in self.fog_buttons + self.list_buttons:
            b.state(["!disabled"] if has else ["disabled"])
        if not has:
            self.bitmap_var.set("Open a save to see the map.")
            for v in list(self.area_vars.values()) + list(self.bit_vars.values()):
                v.set(False)
            for c in self.area_counts.values():
                c.set("")
            self.refresh_lists()
            return
        v = M.fog_bitmap(self.ctx.save)
        self.bitmap_var.set("RevealedRegionsBitmap = %d (0x%08X), %d regions discovered"
                            % (v, v, bin(v >> 1).count("1")))
        for a in self.data["areas"]:
            n, total = M.area_state(self.ctx.save, a)
            self.area_vars[a["name"]].set(n == total and total > 0)
            chk = self.area_checks[a["name"]]
            chk.state(["alternate"] if 0 < n < total else ["!alternate"])
            self.area_counts[a["name"]].set("%d/%d regions" % (n, total))
            for b in a["bits"]:
                self.bit_vars[b].set(bool(v >> b & 1))
        self.refresh_lists()

    def _match(self, row, search, area):
        q = search.get().strip().lower()
        if q and q not in row["name"].lower() and q not in row["id"].lower() and q not in row["area"].lower():
            return False
        a = area.get()
        if a == NO_AREA:
            return not row["area"]
        return a == ALL_AREAS or row["area"] == a

    def refresh_lists(self):
        keep = {}
        for tree in (self.shrine_tree, self.burrow_tree):
            keep[tree] = tree.selection()
            tree.delete(*tree.get_children())
        try:
            self._fill_lists()
        finally:
            for tree, sel in keep.items():
                sel = [i for i in sel if tree.exists(i)]
                if sel:
                    tree.selection_set(sel)

    def _fill_lists(self):
        if not self.ctx.save:
            self.shrine_tree.summary.config(text="")
            self.burrow_tree.summary.config(text="")
            return
        rows = M.shrine_rows(self.ctx.save, self.data)
        for r in rows:
            if self._match(r, self.shrine_search, self.shrine_area):
                tags = ([] if r["unlocked"] else ["off"]) + ([] if r["known"] else ["unknown"])
                self.shrine_tree.insert("", "end", iid=r["id"], tags=tags,
                                        values=(r["name"], r["area"], "yes" if r["unlocked"] else "no", r["id"]))
        self.shrine_tree.summary.config(text="%d used, %d in catalog" % (
            sum(r["unlocked"] for r in rows), len(self.data["shrines"])))
        rows = M.burrow_rows(self.ctx.save, self.data)
        for r in rows:
            if self._match(r, self.burrow_search, self.burrow_area):
                tags = ([] if r["state"] != M.NOT_FOUND else ["off"]) + ([] if r["known"] else ["unknown"])
                self.burrow_tree.insert("", "end", iid=r["id"], tags=tags, values=(
                    r["name"], r["area"], "yes" if r["in_found"] else "no",
                    "yes" if r["in_activated"] else "no", r["id"]))
        self.burrow_tree.summary.config(text="%d found, %d activated" % (
            sum(r["in_found"] for r in rows), sum(r["in_activated"] for r in rows)))

    # ---- fog actions ------------------------------------------------------------------
    def _need_save(self):
        if not self.ctx.save:
            messagebox.showinfo("Map", "Open a save file first.", parent=self)
            return False
        return True

    def _fog_changed(self, before, msg):
        if M.fog_bitmap(self.ctx.save) != before:
            self.ctx.mark_dirty(msg)
        else:
            self.refresh()

    def toggle_area(self, name):
        if not self._need_save():
            return
        n, total = M.area_state(self.ctx.save, M.area(self.data, name))
        self.set_area(name, n < total)

    def set_area(self, name, revealed):
        if not self._need_save():
            return
        before = M.fog_bitmap(self.ctx.save)
        M.set_bits(self.ctx.save, M.area(self.data, name)["bits"], revealed)
        self._fog_changed(before, "%s %s on the map" % (name, "revealed" if revealed else "hidden"))

    def toggle_bit(self, bit):
        if not self._need_save():
            return
        before = M.fog_bitmap(self.ctx.save)
        on = self.bit_vars[bit].get()
        M.set_bits(self.ctx.save, [bit], on)
        self._fog_changed(before, "Region %d %s" % (bit, "revealed" if on else "hidden"))

    def toggle_bits(self, name):
        f = self.bit_frames[name]
        if f.winfo_ismapped():
            f.grid_remove()
        else:
            f.grid()

    def reveal_all(self):
        if not self._need_save():
            return
        before = M.fog_bitmap(self.ctx.save)
        M.reveal_all(self.ctx.save, self.data)
        self._fog_changed(before, "Revealed the whole map")

    # ---- shrine / burrow actions ---------------------------------------------------------
    def _sel(self, tree, what):
        ids = list(tree.selection())
        if not ids:
            self.ctx.status("Select %s first." % what)
        return ids

    def unlock_shrines(self):
        if not self._need_save():
            return
        ids = self._sel(self.shrine_tree, "Sanguine Urns")
        n, errors = 0, []
        for i in ids:
            try:
                n += bool(M.unlock_urn(self.ctx.save, self.data, i))
            except M.MapError as e:
                errors.append(str(e))
        if errors:
            messagebox.showerror("Map", "\n\n".join(errors[:5]), parent=self)
        if n:
            self.ctx.mark_dirty("Marked %d Sanguine Urn(s) used" % n)
        elif ids and not errors:
            self.ctx.status("Already marked used.")

    def remove_shrines(self, confirm=True):
        if not self._need_save():
            return
        ids = [i for i in self._sel(self.shrine_tree, "Sanguine Urns") if self.shrine_tree.set(i, "unlocked") == "yes"]
        if not ids:
            return
        if confirm and not messagebox.askyesno(
                "Map", "Remove %d Sanguine Urn(s) from the used list?\n\n%s" % (len(ids), M.URN_REMOVE_WARNING),
                icon="warning", default="no", parent=self):
            return
        n = sum(bool(M.remove_urn(self.ctx.save, i)) for i in ids)
        if n:
            self.ctx.mark_dirty("Removed %d Sanguine Urn(s)" % n)

    def toggle_burrows(self, flag):
        """Flip one flag (found / activated) on the selected burrows, independently of the other."""
        if not self._need_save():
            return
        ids = self._sel(self.burrow_tree, "burrows")
        if not ids:
            return
        # All selected rows go the same way: on, unless every one already has the flag.
        turn_on = not all(self.burrow_tree.set(i, flag) == "yes" for i in ids)
        n, errors = 0, []
        for i in ids:
            try:
                n += bool(M.set_burrow_flags(self.ctx.save, self.data, i, **{flag: turn_on}))
            except M.MapError as e:
                errors.append(str(e))
        if errors:
            messagebox.showerror("Map", "\n\n".join(errors[:5]), parent=self)
        if n:
            self.ctx.mark_dirty("%s %s on %d kebbit burrow(s)" % (flag.capitalize(), "set" if turn_on else "cleared", n))

    def remove_burrows(self):
        if not self._need_save():
            return
        n = sum(bool(M.remove_burrow(self.ctx.save, i)) for i in self._sel(self.burrow_tree, "burrows"))
        if n:
            self.ctx.mark_dirty("Removed %d kebbit burrow(s) (Found and Activated)" % n)
