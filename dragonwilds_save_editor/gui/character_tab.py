"""Character summary tab and Skills editor tab.

CharacterTab is read-only: the save does not record the maximum for Sustenance,
Hydration or Endurance, so there are no "Refill" buttons (we won't guess a value).
SkillsTab edits skill XP in memory via SaveFile.set_skill and calls ctx.mark_dirty.
"""

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

XP_WARN = 1_000_000


def _fmt_seconds(sec):
    try:
        sec = int(float(sec))
    except (TypeError, ValueError):
        return "?"
    return "%dh %02dm %02ds" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def _fmt_num(v):
    if isinstance(v, bool) or v is None:
        return str(v) if v is not None else "-"
    if isinstance(v, int):
        return "{:,}".format(v)
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)


class CharacterTab(ttk.Frame):
    INFO_FIELDS = ("Character", "Save version", "SaveCount", "Hardcore", "Playtime (in-game)",
                   "Playtime (wall clock)", "Worlds", "Character GUID", "File")
    # (label, Character key, value key inside that object)
    VITALS = (("Health", "Health", "CurrentValue"),
              ("Stamina", "Stamina", "CurrentValue"),
              ("Sustenance", "Sustenance", "SustenanceValue"),
              ("Hydration", "Hydration", "HydrationValue"),
              ("Endurance", "Endurance", "EnduranceValue"))

    def __init__(self, master, ctx):
        super().__init__(master, padding=10)
        self.ctx = ctx
        self.vars = {}

        self.empty_label = ttk.Label(self, text="No save is open. Use File > Open.")
        self.hardcore_label = tk.Label(
            self, text="WARNING: this is a HARDCORE character. A broken save cannot be recovered "
                       "by the game; keep backups.", fg="white", bg="#b00020", padx=6, pady=4)

        info = self.info_frame = ttk.LabelFrame(self, text="Character", padding=8)
        info.pack(fill="x")
        for r, name in enumerate(self.INFO_FIELDS):
            ttk.Label(info, text=name + ":").grid(row=r, column=0, sticky="w", padx=(0, 10))
            v = self.vars[name] = tk.StringVar(value="-")
            ttk.Label(info, textvariable=v).grid(row=r, column=1, sticky="w")

        vit = ttk.LabelFrame(self, text="Vitals (read-only)", padding=8)
        vit.pack(fill="x", pady=(10, 0))
        for r, (label, _, _) in enumerate(self.VITALS):
            ttk.Label(vit, text=label + ":").grid(row=r, column=0, sticky="w", padx=(0, 10))
            v = self.vars[label] = tk.StringVar(value="-")
            ttk.Label(vit, textvariable=v).grid(row=r, column=1, sticky="w")
        ttk.Label(vit, foreground="gray", wraplength=520, justify="left",
                  text="No Refill buttons: the save doesn't store the maximum for Sustenance, "
                       "Hydration or Endurance, so the editor won't guess one.").grid(
            row=len(self.VITALS), column=0, columnspan=2, sticky="w", pady=(6, 0))

        ctx.on_change(self.refresh)
        self.refresh()

    def refresh(self):
        s = self.ctx.save
        self.hardcore_label.pack_forget()
        self.empty_label.pack_forget()
        if s is None:
            for v in self.vars.values():
                v.set("-")
            self.empty_label.pack(side="top", anchor="w", before=self.info_frame)
            return
        r = s.root
        meta = r.get("meta_data", {}) or {}
        prog = r.get("GameProgress", {}) or {}
        ch = prog.get("Character", {}) or {}
        hardcore = bool((r.get("Hardcore") or {}).get("IsHardcore"))
        vals = {
            "Character": meta.get("char_name", "?"),
            "Save version": r.get("Version", "?"),
            "SaveCount": r.get("SaveCount", "?"),
            "Hardcore": "Yes" if hardcore else "No",
            "Playtime (in-game)": _fmt_seconds(ch["Playtime_sim"]) if "Playtime_sim" in ch else "-",
            "Playtime (wall clock)": _fmt_seconds(ch["Playtime_wall"]) if "Playtime_wall" in ch else "-",
            "Worlds": len(meta.get("worlds_playtime", {}) or {}),
            "Character GUID": meta.get("char_guid", "?"),
            "File": s.path,
        }
        for k, v in vals.items():
            self.vars[k].set(str(v))
        for label, key, sub in self.VITALS:
            obj = ch.get(key)
            val = obj.get(sub) if isinstance(obj, dict) else None
            self.vars[label].set(_fmt_num(val) if val is not None else "-")
        if hardcore:
            self.hardcore_label.pack(side="top", fill="x", pady=(0, 8),
                                     before=self.info_frame)


class SkillsTab(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master, padding=10)
        self.ctx = ctx
        self.rows = {}  # skill name -> dict of widgets/vars

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        self.btn_set_all = ttk.Button(bar, text="Set all to level...", command=self.set_all_prompt)
        self.btn_set_all.pack(side="left")
        self.btn_max_all = ttk.Button(bar, text="Max all (99)", command=self.max_all)
        self.btn_max_all.pack(side="left", padx=6)
        self.msg = ttk.Label(self, text="")
        self.msg.pack(fill="x")

        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(fill="both", expand=True)
        ctx.on_change(self.refresh)
        self.refresh()

    # ---- data helpers ----------------------------------------------------------
    def _skill_list(self):
        """Sorted [(name, xp, level)] for every known skill, including ones missing from the save."""
        game = self.ctx.game
        have = {}
        if self.ctx.save is not None:
            for name, xp, lvl in self.ctx.save.skills():
                have[name] = (xp, lvl)
        names = set(game.skills_by_id.values()) | set(have)
        out = []
        for n in sorted(names, key=str.lower):
            xp, lvl = have.get(n, (0, game.level_for_xp(0)))
            out.append((n, xp, lvl))
        return out

    def _progress(self, xp, level):
        game = self.ctx.game
        if level >= game.max_level:
            return 100.0, 0
        lo, hi = game.xp_for(level), game.xp_for(level + 1)
        return (100.0 * (xp - lo) / (hi - lo) if hi > lo else 100.0), hi - xp

    # ---- UI ---------------------------------------------------------------------
    def refresh(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.rows = {}
        state = "normal" if self.ctx.save is not None else "disabled"
        self.btn_set_all.configure(state=state)
        self.btn_max_all.configure(state=state)
        if self.ctx.save is None:
            self.msg.configure(text="No save is open.")
            return
        self.msg.configure(text="")
        g = self.grid_frame
        for c, h in enumerate(("Skill", "Level", "XP", "To next", "Progress", "Set level", "Set XP", "")):
            ttk.Label(g, text=h, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=c, sticky="w", padx=4)
        maxlvl = self.ctx.game.max_level
        for r, (name, xp, lvl) in enumerate(self._skill_list(), start=1):
            pct, to_next = self._progress(xp, lvl)
            ttk.Label(g, text=name).grid(row=r, column=0, sticky="w", padx=4, pady=2)
            ttk.Label(g, text=str(lvl)).grid(row=r, column=1, sticky="e", padx=4)
            ttk.Label(g, text="{:,}".format(int(xp))).grid(row=r, column=2, sticky="e", padx=4)
            ttk.Label(g, text="-" if lvl >= maxlvl else "{:,}".format(int(to_next))).grid(
                row=r, column=3, sticky="e", padx=4)
            ttk.Progressbar(g, length=140, maximum=100, value=pct).grid(row=r, column=4, padx=4)
            lvl_var = tk.StringVar(value=str(lvl))
            xp_var = tk.StringVar(value=str(int(xp)))
            spin = ttk.Spinbox(g, from_=1, to=maxlvl, width=5, textvariable=lvl_var,
                               command=lambda n=name: self._sync_from_level(n))
            spin.grid(row=r, column=5, padx=4)
            spin.bind("<KeyRelease>", lambda e, n=name: self._sync_from_level(n))
            ent = ttk.Entry(g, width=12, textvariable=xp_var)
            ent.grid(row=r, column=6, padx=4)
            ent.bind("<KeyRelease>", lambda e, n=name: self._sync_from_xp(n))
            ent.bind("<Return>", lambda e, n=name: self.apply_row(n))
            ttk.Button(g, text="Apply", command=lambda n=name: self.apply_row(n)).grid(row=r, column=7, padx=4)
            self.rows[name] = {"level": lvl_var, "xp": xp_var, "cur_xp": xp}

    def _sync_from_level(self, name):
        row = self.rows[name]
        try:
            lvl = int(row["level"].get())
            row["xp"].set(str(self.ctx.game.xp_for(lvl)))
        except (ValueError, TypeError):
            pass

    def _sync_from_xp(self, name):
        row = self.rows[name]
        try:
            xp = int(row["xp"].get().replace(",", ""))
        except ValueError:
            return
        if xp >= 0:
            row["level"].set(str(self.ctx.game.level_for_xp(xp)))

    # ---- edits ---------------------------------------------------------------------
    def _parse_xp(self, text):
        """Return a valid int XP or None (after showing an error). Warns above 1,000,000."""
        try:
            xp = int(str(text).strip().replace(",", ""))
        except ValueError:
            messagebox.showerror("Invalid XP", "XP must be a whole number >= 0.", parent=self)
            return None
        if xp < 0:
            messagebox.showerror("Invalid XP", "XP must be a whole number >= 0.", parent=self)
            return None
        if xp > XP_WARN and not messagebox.askyesno(
                "XP above level 99",
                "%s XP is above the level-99 amount (1,000,000). The game allows this, "
                "but it gives no extra level. Continue?" % "{:,}".format(xp), parent=self):
            return None
        return xp

    def set_level(self, name, level):
        if self.ctx.save is None:
            return None
        level = int(level)
        if not 1 <= level <= self.ctx.game.max_level:
            messagebox.showerror("Invalid level", "Level must be 1-%d." % self.ctx.game.max_level, parent=self)
            return None
        result = self.ctx.save.set_skill(name, level=level)
        self.ctx.mark_dirty("%s set to level %d (%s XP)" % (result[0], result[2], "{:,}".format(result[1])))
        return result

    def set_xp(self, name, xp_text):
        if self.ctx.save is None:
            return None
        xp = self._parse_xp(xp_text)
        if xp is None:
            return None
        result = self.ctx.save.set_skill(name, xp=xp)
        self.ctx.mark_dirty("%s set to %s XP (level %d)" % (result[0], "{:,}".format(result[1]), result[2]))
        return result

    def apply_row(self, name):
        """Apply the row's XP entry (the level spinbox keeps it in sync)."""
        row = self.rows.get(name)
        if not row:
            return None
        return self.set_xp(name, row["xp"].get())

    def _set_all(self, level):
        names = [n for n, _, _ in self._skill_list()]
        for n in names:
            self.ctx.save.set_skill(n, level=level)
        self.ctx.mark_dirty("All %d skills set to level %d" % (len(names), level))

    def set_all_prompt(self):
        if self.ctx.save is None:
            return
        mx = self.ctx.game.max_level
        level = simpledialog.askinteger("Set all skills", "Set every skill to level (1-%d):" % mx,
                                        minvalue=1, maxvalue=mx, parent=self)
        if level is None:
            return
        if messagebox.askyesno("Confirm", "Set ALL skills to level %d? This overwrites current XP "
                                          "(lower levels mean lost XP)." % level, parent=self):
            self._set_all(level)

    def max_all(self):
        if self.ctx.save is None:
            return
        mx = self.ctx.game.max_level
        if messagebox.askyesno("Confirm", "Set ALL skills to level %d?" % mx, parent=self):
            self._set_all(mx)
