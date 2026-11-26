"""Main Quest tab: a linear timeline of very-high-confidence checkpoints (revert only).

Uses dw_questline. Applying a checkpoint edits the character save in memory; saving through
the app first snapshots ALL character + world saves (ctx.needs_full_snapshot), then backs
up and writes the character file.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import map as M
from .. import questline as L

STATUS_TEXT = {"current": "You are here", "available": "Can revert here", "ahead": "Ahead",
               "disabled": "Not available"}


class QuestsTab(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        try:
            self.data = L.load()
            self.load_error = None
        except Exception as e:  # missing/broken data file
            self.data = {"checkpoints": [], "main_quest_order": [], "quest_names": {}}
            self.load_error = str(e)
        self.optional_var = tk.BooleanVar(value=False)
        self._build()
        ctx.on_change(self.refresh)
        self.refresh()

    def _build(self):
        ttk.Label(
            self, foreground="#8a4b00", wraplength=1000, justify="left",
            text=("The main questline is one line of checkpoints. You can only move BACK to a checkpoint "
                  "behind you; quests before it stay complete as they are, and every main quest after it is "
                  "reset to not started. Only checkpoints traced to the game's own quest scripts with very "
                  "high confidence are enabled. Items, XP and recipes you already earned are kept. Saving "
                  "first copies ALL your character and world saves to the backups folder.")
        ).pack(fill="x", padx=8, pady=(8, 4))

        self.pos_var = tk.StringVar()
        ttk.Label(self, textvariable=self.pos_var, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8)

        self.tree = ttk.Treeview(self, columns=("quest", "conf", "status"), show="tree headings",
                                 height=8, selectmode="browse")
        self.tree.heading("#0", text="Checkpoint (story order)")
        self.tree.heading("quest", text="Quest")
        self.tree.heading("conf", text="Confidence")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=430)
        self.tree.column("quest", width=170)
        self.tree.column("conf", width=90, anchor="center")
        self.tree.column("status", width=130, anchor="center")
        self.tree.tag_configure("current", background="#dff0d8")
        self.tree.tag_configure("available", foreground="#1a4f8a")
        self.tree.tag_configure("ahead", foreground="#777777")
        self.tree.tag_configure("disabled", foreground="#aaaaaa")
        self.tree.pack(fill="x", padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show())

        row = ttk.Frame(self)
        row.pack(fill="x", padx=8)
        self.apply_btn = ttk.Button(row, text="Revert to this checkpoint", command=self.apply_selected)
        self.apply_btn.pack(side="left")
        self.opt_chk = ttk.Checkbutton(row, variable=self.optional_var, command=self._show,
                                       text="Also remove this step's rewards (optional)")
        self.opt_chk.pack(side="left", padx=10)

        self.detail = tk.Text(self, height=16, wrap="word", state="disabled")
        self.detail.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    def _set_detail(self, text):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")

    def _selected(self):
        sel = self.tree.selection()
        return L.checkpoint(self.data, sel[0]) if sel else None

    def refresh(self):
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        if self.load_error:
            self.pos_var.set("Quest data could not be loaded: %s" % self.load_error)
            self.apply_btn.state(["disabled"])
            return
        if not self.ctx.save:
            self.pos_var.set("Open a save file to manage the main quest.")
            self._set_detail("")
            self.apply_btn.state(["disabled"])
            return
        names = self.data.get("quest_names", {})
        cur = L.current_checkpoint(self.ctx.save, self.data)
        _, aq = L.active_quest(self.ctx.save, self.data)
        self.pos_var.set("Current position: %s" % (
            cur["label"] if cur else
            "%s (between checkpoints)" % names.get(aq, aq) if aq else "main questline complete"))
        for cp in self.data["checkpoints"]:
            st, _ = L.status(self.ctx.save, self.data, cp)
            conf = cp.get("confidence", "")
            if L.needs_ack(cp) and cp.get("enabled"):
                conf += " (!)"
            self.tree.insert("", "end", iid=cp["id"], text=cp["label"], tags=(st,),
                             values=(names.get(cp["quest_id"], cp["quest_id"]), conf, STATUS_TEXT[st]))
        target = keep[0] if keep and self.tree.exists(keep[0]) else (cur["id"] if cur else None)
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)
        self._show()

    def _show(self):
        cp = self._selected()
        if not cp or not self.ctx.save:
            self._set_detail("")
            self.apply_btn.state(["disabled"])
            return
        st, why = L.status(self.ctx.save, self.data, cp)
        has_opt = bool(cp.get("progress_remove_optional"))
        self.opt_chk.state(["!disabled"] if has_opt and st == "available" else ["disabled"])
        lines = [cp["label"], "Status: %s. %s" % (STATUS_TEXT[st], why), ""]
        if L.needs_ack(cp):
            lines += ["CONFIDENCE: %s (not very high). The inference that held it back:" % cp.get("confidence"),
                      "  " + L.inference_text(cp), ""]
        if cp.get("world_note"):
            lines += ["World save: " + cp["world_note"], ""]
        if st == "available":
            plan = L.plan(self.ctx.save, self.data, cp, include_optional=self.optional_var.get() and has_opt)
            lines.append("Reverting here would change:")
            lines += ["  " + p for p in plan] or ["  (nothing)"]
            lines.append("")
        if has_opt:
            lines.append("Optional reward removal: " + "; ".join(o["label"] for o in cp["progress_remove_optional"]))
        if cp.get("open_questions"):
            lines += ["", "Known unknowns:"] + ["  - " + q for q in cp["open_questions"]]
        if cp.get("evidence"):
            ev = cp["evidence"] if isinstance(cp["evidence"], list) else [cp["evidence"]]
            lines += ["", "Evidence:"] + ["  - %s" % e for e in ev[:12]]
        self._set_detail("\n".join(lines))
        self.apply_btn.state(["!disabled"] if st == "available" else ["disabled"])

    def apply_selected(self):
        cp = self._selected()
        if not cp or not self.ctx.save:
            return False
        opt = self.optional_var.get() and bool(cp.get("progress_remove_optional"))
        try:
            plan = L.plan(self.ctx.save, self.data, cp, include_optional=opt)
        except Exception as e:
            messagebox.showerror("Main quest", str(e), parent=self)
            return False
        text = "Revert the main quest to:\n%s\n\n%s\n\nNothing is written until you Save. Saving first snapshots " \
               "all character and world saves." % (cp["label"], "\n".join(plan[:40]) +
                                                   ("\n..." if len(plan) > 40 else ""))
        if not messagebox.askyesno("Revert main quest", text, icon="warning", parent=self):
            return False
        ack = False
        if L.needs_ack(cp):
            warn = ("This checkpoint is rated %s confidence, NOT very high.\n\nWhat held it back:\n%s\n\n"
                    "Every value was traced to the game's quest scripts except the point above. Your saves will "
                    "still be snapshotted before writing.\n\nAre you sure you want to revert to it?"
                    % (cp.get("confidence"), L.inference_text(cp)))
            if not messagebox.askyesno("Confirm %s-confidence checkpoint" % cp.get("confidence"), warn,
                                       icon="warning", default="no", parent=self):
                return False
            ack = True
        try:
            L.apply(self.ctx.save, self.data, cp, include_optional=opt, acknowledged=ack)
        except Exception as e:
            messagebox.showerror("Main quest", "Could not revert:\n\n%s" % e, parent=self)
            return False
        self.ctx.needs_full_snapshot = True
        msg = "Main quest reverted to: %s" % cp["label"]
        if self.offer_fog_reset():
            msg += "; map areas hidden again"
        self.ctx.mark_dirty(msg)
        return True

    def offer_fog_reset(self):
        """Optional follow-up to a revert: the checkpoint never changes the map itself. If a map
        area is gated by a main quest that is now not started but still shows as discovered,
        ask (default No) whether to hide it and drop its Sanguine Urns and kebbit burrows."""
        try:
            m = M.load_map_data()
            sug = M.suggest_fog_reset(self.ctx.save, self.data, m)
        except Exception:
            return False
        if not sug:
            return False
        lines = []
        for s in sug:
            lines.append("- %s (%d region%s), opened by %s, which is now not started"
                         % (s["area"], len(s["bits"]), "" if len(s["bits"]) == 1 else "s", s["quest_name"]))
        ns = sum(len(s["urns"]) for s in sug)
        nb = sum(len(s["burrows"]) for s in sug)
        text = ("Your map still shows these areas as discovered:\n\n%s\n\nHide them again?"
                % "\n".join(lines))
        if ns or nb:
            text += " This also removes their %d used Sanguine Urn(s) and %d kebbit burrow(s)." % (ns, nb)
        if ns:
            text += "\n\n" + M.URN_REMOVE_WARNING
        text += ("\n\nThis is optional. The fog is cosmetic: travel is gated by quest state, not the map, and the "
                 "game re-reveals areas when you enter them. You can also change this later on the Map tab.")
        if not messagebox.askyesno("Map after revert", text, default="no", parent=self):
            return False
        M.apply_fog_reset(self.ctx.save, sug, include_points=True)
        return True
