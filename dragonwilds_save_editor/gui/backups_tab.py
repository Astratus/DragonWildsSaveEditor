"""Backups tab: list, create, restore, delete and prune backups of the open character save
OR of the focused world save (selector at the top).

Kinds of backup found next to the file (character .json or world .sav):
  <file>.<YYYYmmdd-HHMMSS>[-N].pyedit.bak   made by this editor (safe to delete/prune)
  <file>.backup                              the game's previous save (never deleted here)
  <file>.<N>.verbackup                       the game's per-version copy (never deleted here)
World saves additionally list the copies of the same file name inside the full snapshots
  <editor backups folder>/<label>_<YYYYmmdd-HHMMSS>[-N]/SaveGames/<file>
  (pre-quest, pre-world-edit, full; %LOCALAPPDATA%\\DragonwildsSaveEditor\\backups)
which are never deleted here.
"""

import hashlib
import json
import os
import re
import subprocess
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .context import dw_save

KIND_EDITOR = "Editor backup"
KIND_PREVIOUS = "Game: previous save"
KIND_VERSION = "Game: version backup"
KIND_SNAPSHOT = "Snapshot: "      # + label, e.g. "Snapshot: pre-world-edit"

MODE_CHARACTER = "character"
MODE_WORLD = "world"

BANNER = ("Every save made by this editor creates a backup automatically. "
          "The game's own .backup files rotate and get overwritten.")

_EDITOR_RE = re.compile(r"^\.\d{8}-\d{6}(-\d+)?\.pyedit\.bak$")
_VERSION_RE = re.compile(r"^\.\d+\.verbackup$")
_SNAP_DIR_RE = re.compile(r"^(?P<label>.+)_(?P<stamp>\d{8}-\d{6})(?:-(?P<n>\d+))?$")


def classify(save_path, file_path):
    """Return the backup kind of file_path for save_path, or None if it isn't one."""
    base = os.path.basename(save_path)
    name = os.path.basename(file_path)
    if os.path.normcase(os.path.dirname(os.path.abspath(file_path))) != \
            os.path.normcase(os.path.dirname(os.path.abspath(save_path))):
        return None
    if not name.startswith(base):
        return None
    rest = name[len(base):]
    if _EDITOR_RE.match(rest):
        return KIND_EDITOR
    if rest == ".backup":
        return KIND_PREVIOUS
    if _VERSION_RE.match(rest):
        return KIND_VERSION
    return None


def find_backups(save_path):
    """[(path, kind, mtime, size)] for every backup of save_path, newest first."""
    folder = os.path.dirname(os.path.abspath(save_path))
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        p = os.path.join(folder, name)
        kind = classify(save_path, p)
        if not kind or not os.path.isfile(p):
            continue
        st = os.stat(p)
        out.append((p, kind, st.st_mtime, st.st_size))
    out.sort(key=_sort_key, reverse=True)
    return out


def find_snapshot_copies(save_path, sub="SaveGames", snapshot_root=None):
    """[(path, kind, mtime, size)]: copies of save_path's file name in the full snapshots
    <snapshot_root>/<label>_<stamp>/<sub>/ (default root: dw_save.snapshot_root())."""
    root = snapshot_root or dw_save.snapshot_root()
    base = os.path.basename(save_path)
    out = []
    try:
        dirs = os.listdir(root)
    except OSError:
        return out
    for d in dirs:
        m = _SNAP_DIR_RE.match(d)
        if not m:
            continue
        p = os.path.join(root, d, sub, base)
        if os.path.isfile(p):
            st = os.stat(p)
            out.append((p, KIND_SNAPSHOT + m.group("label"), st.st_mtime, st.st_size))
    return out


def find_world_backups(world_path, snapshot_root=None):
    """Every backup of a world .sav, newest first: editor/game backups next to it plus the
    copies in <editor backups folder>/<label>_<stamp>/SaveGames/."""
    rows = find_backups(world_path) + find_snapshot_copies(world_path, "SaveGames", snapshot_root)
    rows.sort(key=_sort_key, reverse=True)
    return rows


def _stamp_time(stamp):
    return time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))


def _sort_key(row):
    """Editor backups keep the save's mtime (shutil.copy2), so order them by the
    creation stamp in their name, snapshots by their folder's stamp; game files by mtime."""
    p, kind, mtime, _ = row
    if kind.startswith(KIND_SNAPSHOT):
        m = _SNAP_DIR_RE.match(os.path.basename(os.path.dirname(os.path.dirname(p))))
        if m:
            try:
                return (_stamp_time(m.group("stamp")), int(m.group("n") or 1))
            except ValueError:
                pass
    if kind == KIND_EDITOR:
        m = re.search(r"\.(\d{8}-\d{6})(?:-(\d+))?\.pyedit\.bak$", p)
        if m:
            try:
                t = _stamp_time(m.group(1))
                return (t, int(m.group(2) or 1))
            except ValueError:
                pass
    return (mtime, 0)


def digest(root):
    """Small comparable summary of a parsed save: SaveCount, items by slot, skill XP."""
    gp = root.get("GameProgress", {}) if isinstance(root, dict) else {}
    items = {}
    for sec in dw_save.SECTIONS:
        for k, v in (gp.get(sec) or {}).items():
            if k.isdigit() and isinstance(v, dict):
                items[(sec, k)] = (v.get("ItemData"), v.get("Count", 1), v.get("Durability"),
                                   v.get("PlayerInventoryItemIndex"))
    skills = {}
    for s in ((gp.get("Skills") or {}).get("Skills") or []):
        if isinstance(s, dict):
            skills[s.get("Id")] = s.get("Xp", 0)
    return {"SaveCount": root.get("SaveCount") if isinstance(root, dict) else None,
            "items": items, "skills": skills}


def diff_summary(old, cur, skill_names=None):
    """Short text describing how backup `old` differs from current `cur`."""
    keys = set(old["items"]) | set(cur["items"])
    changed = sum(1 for k in keys if old["items"].get(k) != cur["items"].get(k))
    xp_changes = []
    for sid in set(old["skills"]) | set(cur["skills"]):
        a, b = old["skills"].get(sid, 0), cur["skills"].get(sid, 0)
        if a != b:
            name = (skill_names or {}).get(sid, sid)
            xp_changes.append("%s %+d" % (name, round(a - b)))
    parts = ["%d item slot%s differ" % (changed, "" if changed == 1 else "s") if changed
             else "items same"]
    if xp_changes:
        if len(xp_changes) <= 2:
            parts.append("XP: " + ", ".join(sorted(xp_changes)))
        else:
            parts.append("XP differs in %d skills" % len(xp_changes))
    else:
        parts.append("XP same")
    a, b = old.get("SaveCount"), cur.get("SaveCount")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        parts.append("SaveCount %+d" % (a - b) if a != b else "SaveCount same")
    return "; ".join(parts)


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def world_compare(backup_hash, backup_size, cur_hash, cur_size):
    """Short text comparing a world backup with the focused world's file on disk."""
    if backup_hash is None:
        return "unreadable"
    if cur_hash is None:
        return "current file missing"
    if backup_hash == cur_hash:
        return "identical to the current file"
    return "differs from the current file (%+d bytes)" % (backup_size - cur_size)


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


class BackupsTab(ttk.Frame):
    COLUMNS = ("file", "kind", "modified", "size", "savecount", "summary")
    HEADINGS = ("File", "Kind", "Modified (file)", "Size", "SaveCount", "Summary (backup vs current)")
    WIDTHS = (300, 140, 140, 70, 75, 340)

    def __init__(self, parent, ctx, snapshot_root=None):
        super().__init__(parent)
        self.ctx = ctx
        self.snapshot_root = snapshot_root   # None = dw_save.snapshot_root()
        self._cache = {}        # path -> ((mtime, size), digest or None)
        self._hashes = {}       # path -> ((mtime, size), sha256 or None)   (world mode)
        self._rows = {}         # tree iid -> (path, kind, mtime, size)
        self._build()
        ctx.on_change(self._on_character_change)
        if hasattr(ctx, "on_world_change"):
            ctx.on_world_change(self._on_world_change)
        self.refresh()

    # ---- UI ------------------------------------------------------------------
    def _build(self):
        banner = ttk.Label(self, text=BANNER, wraplength=900, justify="left",
                           foreground="#1a4d8f", padding=(8, 6))
        banner.pack(fill="x")

        sel = ttk.Frame(self, padding=(6, 0))
        sel.pack(fill="x")
        ttk.Label(sel, text="Show backups of:").pack(side="left")
        self.mode_var = tk.StringVar(value=MODE_CHARACTER)
        for text, val in (("Character save", MODE_CHARACTER), ("Focused world save", MODE_WORLD)):
            ttk.Radiobutton(sel, text=text, value=val, variable=self.mode_var,
                            command=self.refresh).pack(side="left", padx=(8, 0))
        self.target_var = tk.StringVar()
        ttk.Label(sel, textvariable=self.target_var, foreground="#555555").pack(side="left", padx=(12, 0))

        bar = ttk.Frame(self, padding=(6, 0))
        bar.pack(fill="x")
        self.btn_backup = ttk.Button(bar, text="Back up now", command=self.backup_now)
        self.btn_restore = ttk.Button(bar, text="Restore selected", command=self.restore_selected)
        self.btn_delete = ttk.Button(bar, text="Delete selected", command=self.delete_selected)
        self.btn_folder = ttk.Button(bar, text="Open backups folder", command=self.open_folder)
        self.btn_refresh = ttk.Button(bar, text="Refresh list", command=self.refresh)
        for b in (self.btn_backup, self.btn_restore, self.btn_delete, self.btn_folder, self.btn_refresh):
            b.pack(side="left", padx=(0, 6), pady=4)

        body = ttk.Frame(self, padding=(6, 0))
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=self.COLUMNS, show="headings", selectmode="extended")
        for col, head, w in zip(self.COLUMNS, self.HEADINGS, self.WIDTHS):
            self.tree.heading(col, text=head)
            self.tree.column(col, width=w, anchor="e" if col in ("size", "savecount") else "w",
                             stretch=(col == "summary"))
        ys = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_buttons())
        self.tree.bind("<Double-1>", lambda e: self.restore_selected())

        ret = ttk.Frame(self, padding=(6, 4))
        ret.pack(fill="x")
        self.retention_var = tk.StringVar()
        ttk.Label(ret, textvariable=self.retention_var).pack(side="left")
        ttk.Label(ret, text="   Clean up: keep newest").pack(side="left")
        self.keep_var = tk.StringVar(value="20")
        ttk.Spinbox(ret, from_=1, to=9999, width=6, textvariable=self.keep_var).pack(side="left", padx=4)
        self.btn_prune = ttk.Button(ret, text="Clean up editor backups...", command=self.prune)
        self.btn_prune.pack(side="left")

    def _set_state(self, widget, enabled):
        widget.state(["!disabled"] if enabled else ["disabled"])

    # ---- mode ------------------------------------------------------------------
    @property
    def mode(self):
        return self.mode_var.get()

    def set_mode(self, mode):
        self.mode_var.set(mode)
        self.refresh()

    def _world(self):
        return getattr(self.ctx, "world", None)

    def target_path(self):
        """The file whose backups are listed: the character save or the focused world."""
        if self.mode == MODE_WORLD:
            w = self._world()
            return w.path if w is not None else None
        return self.ctx.save.path if self.ctx.save is not None else None

    def _on_character_change(self):
        if self.mode == MODE_CHARACTER:
            self.refresh()

    def _on_world_change(self):
        # In-memory edits don't change the files on disk; skip the rescan for them.
        if self.mode == MODE_WORLD and getattr(self.ctx, "world_event", None) != "edit":
            self.refresh()

    def _update_buttons(self):
        has = self.target_path() is not None
        sel = self.selected()
        self._set_state(self.btn_backup, has)
        self._set_state(self.btn_folder, has)
        self._set_state(self.btn_refresh, has)
        self._set_state(self.btn_restore, has and len(sel) == 1)
        self._set_state(self.btn_delete, has and bool(sel) and all(k == KIND_EDITOR for _, k in sel))
        self._set_state(self.btn_prune, has)

    # ---- data ----------------------------------------------------------------
    def _digest_for(self, path, mtime, size):
        key = (mtime, size)
        hit = self._cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        try:
            with open(path, "rb") as f:
                raw = f.read()
            d = digest(json.loads(raw.decode("utf-8-sig")))
        except (OSError, ValueError, UnicodeDecodeError, AttributeError, TypeError):
            d = None
        self._cache[path] = (key, d)
        return d

    def _hash_for(self, path, mtime, size):
        key = (mtime, size)
        hit = self._hashes.get(path)
        if hit and hit[0] == key:
            return hit[1]
        try:
            h = file_sha256(path)
        except OSError:
            h = None
        self._hashes[path] = (key, h)
        return h

    def _display_name(self, p):
        """File name; snapshot copies also show their snapshot folder."""
        root = self.snapshot_root or dw_save.snapshot_root()
        try:
            rel = os.path.relpath(p, root)
        except ValueError:
            return os.path.basename(p)
        if rel.startswith(".."):
            return os.path.basename(p)
        return os.path.join(os.path.basename(root), rel)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        if self.mode == MODE_WORLD:
            self.tree.heading("savecount", text="Same as current")
            self._refresh_world()
        else:
            self.tree.heading("savecount", text="SaveCount")
            self._refresh_character()
        self._update_buttons()

    def _refresh_character(self):
        save = self.ctx.save
        if save is None:
            self.target_var.set("")
            self.retention_var.set("No save open.")
            return
        self.target_var.set(save.path)
        try:
            cur = digest(save.root)
        except Exception:
            cur = None
        names = getattr(self.ctx.game, "skills_by_id", {})
        rows = find_backups(save.path)
        live = set()
        ed_count = ed_size = 0
        for i, (p, kind, mtime, size) in enumerate(rows):
            live.add(p)
            d = self._digest_for(p, mtime, size)
            if d is None:
                sc, summ = "unreadable", "unreadable (not valid JSON)"
            else:
                sc = "" if d["SaveCount"] is None else str(d["SaveCount"])
                summ = diff_summary(d, cur, names) if cur else ""
            if kind == KIND_EDITOR:
                ed_count += 1
                ed_size += size
            iid = "r%d" % i
            self._rows[iid] = (p, kind, mtime, size)
            self.tree.insert("", "end", iid=iid, values=(
                os.path.basename(p), kind,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
                _fmt_size(size), sc, summ))
        for p in [p for p in self._cache if p not in live]:
            del self._cache[p]
        self.retention_var.set("Editor backups: %d, %s total." % (ed_count, _fmt_size(ed_size)))

    def _refresh_world(self):
        w = self._world()
        if w is None:
            self.target_var.set("")
            self.retention_var.set("No world save focused. Pick one in the World row at the top.")
            return
        self.target_var.set(w.path)
        try:
            st = os.stat(w.path)
            cur_hash, cur_size = self._hash_for(w.path, st.st_mtime, st.st_size), st.st_size
        except OSError:
            cur_hash, cur_size = None, 0
        rows = find_world_backups(w.path, self.snapshot_root)
        live = {w.path}
        ed_count = ed_size = snaps = 0
        for i, (p, kind, mtime, size) in enumerate(rows):
            live.add(p)
            h = self._hash_for(p, mtime, size)
            same = "" if h is None or cur_hash is None else ("yes" if h == cur_hash else "no")
            if kind == KIND_EDITOR:
                ed_count += 1
                ed_size += size
            elif kind.startswith(KIND_SNAPSHOT):
                snaps += 1
            iid = "r%d" % i
            self._rows[iid] = (p, kind, mtime, size)
            self.tree.insert("", "end", iid=iid, values=(
                self._display_name(p), kind,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
                _fmt_size(size), same, world_compare(h, size, cur_hash, cur_size)))
        for p in [p for p in self._hashes if p not in live]:
            del self._hashes[p]
        self.retention_var.set("Editor backups: %d, %s total. Snapshot copies: %d (kept in the editor's backups folder, "
                               "never deleted here)." % (ed_count, _fmt_size(ed_size), snaps))

    def selected(self):
        return [(self._rows[i][0], self._rows[i][1]) for i in self.tree.selection() if i in self._rows]

    # ---- actions -------------------------------------------------------------
    def _need_save(self):
        if self.target_path() is None:
            if self.mode == MODE_WORLD:
                messagebox.showinfo("No world focused", "Pick a world save in the World row at the top.",
                                    parent=self)
            else:
                messagebox.showinfo("No save open", "Open a save file first.", parent=self)
            return False
        return True

    def backup_now(self):
        if not self._need_save():
            return None
        try:
            if self.mode == MODE_WORLD:
                path = self._world().make_backup()
            else:
                path = self.ctx.save.make_backup()
        except (OSError, RuntimeError) as e:
            messagebox.showerror("Backup failed", str(e), parent=self)
            return None
        self.ctx.status("Backup created: %s" % os.path.basename(path))
        messagebox.showinfo("Backup created", "Created:\n%s" % os.path.basename(path), parent=self)
        self.refresh()
        return path

    def restore_selected(self):
        if not self._need_save():
            return None
        sel = self.selected()
        if len(sel) != 1:
            messagebox.showinfo("Restore", "Select exactly one backup to restore.", parent=self)
            return None
        if self.mode == MODE_WORLD:
            return self._restore_world(*sel[0])
        path, kind = sel[0]
        msg = ("Restore %s (%s) over\n%s?\n\n"
               "The current file on disk is backed up first, so this can be undone." %
               (os.path.basename(path), kind, os.path.basename(self.ctx.save.path)))
        if self.ctx.dirty:
            msg += "\n\nYou have UNSAVED changes in the editor. They will be discarded."
        else:
            msg += "\n\nAny unsaved in-memory changes are discarded."
        if not messagebox.askyesno("Restore backup", msg, icon="warning", parent=self):
            return None
        try:
            safety = self.ctx.restore_backup(path)
        except RuntimeError as e:
            if "running" not in str(e).lower():
                messagebox.showerror("Restore failed", str(e), parent=self)
                return None
            if not messagebox.askyesno(
                    "Game is running",
                    "%s\n\nThe game may overwrite the restored file or crash. "
                    "Restore anyway?" % e, icon="warning", parent=self):
                return None
            try:
                safety = self.ctx.restore_backup(path, force=True)
            except (OSError, RuntimeError, ValueError) as e2:
                messagebox.showerror("Restore failed", str(e2), parent=self)
                return None
        except (OSError, ValueError) as e:
            messagebox.showerror("Restore failed", "Could not restore: %s" % e, parent=self)
            return None
        messagebox.showinfo("Restored", "Restored %s.\nPrevious file kept as %s." %
                            (os.path.basename(path), os.path.basename(safety)), parent=self)
        self.refresh()  # ctx.load already refreshed, but the list changed too
        return safety

    def _restore_world(self, path, kind):
        target = self._world().path
        if dw_save.game_is_running():
            messagebox.showerror("Restore refused", "Dragonwilds appears to be running. Close the game "
                                 "first; it would overwrite the restored world.", parent=self)
            return None
        msg = ("Restore this world backup:\n%s\n(%s)\n\nover the focused world:\n%s ?\n\n"
               "The current .sav is backed up first (.pyedit.bak), so this can be undone. "
               "Consider deleting Saved\\SpudCache\\* afterwards so a stale cache can't shadow it."
               % (self._display_name(path), kind, target))
        changes = self.ctx.world_changes() if hasattr(self.ctx, "world_changes") else []
        if changes:
            msg += "\n\nYou have %d UNSAVED world edit(s). They will be discarded." % len(changes)
        if not messagebox.askyesno("Restore world backup", msg, icon="warning", default="no", parent=self):
            return None
        try:
            safety = self.ctx.restore_world_backup(path)
        except (OSError, RuntimeError, ValueError) as e:
            messagebox.showerror("Restore failed", "Could not restore: %s" % e, parent=self)
            return None
        messagebox.showinfo("Restored", "Restored %s.\nPrevious file kept as %s." %
                            (os.path.basename(path), os.path.basename(safety) if safety else "(none)"),
                            parent=self)
        self.refresh()
        return safety

    def open_folder(self):
        """Open the selected backup's folder (with the file selected), else the target's folder."""
        if not self._need_save():
            return
        sel = self.selected()
        try:
            if len(sel) == 1 and os.path.isfile(sel[0][0]):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(sel[0][0])])
            else:
                os.startfile(os.path.dirname(os.path.abspath(self.target_path())))
        except (OSError, AttributeError) as e:
            messagebox.showerror("Open folder", str(e), parent=self)

    def _delete_files(self, paths):
        """Delete editor backups of the current target only. Returns (deleted, refused) lists."""
        deleted, refused = [], []
        save_path = self.target_path()
        for p in paths:
            if classify(save_path, p) != KIND_EDITOR or \
                    os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(save_path)):
                refused.append(p)
                continue
            try:
                os.remove(p)
                deleted.append(p)
            except OSError:
                refused.append(p)
        return deleted, refused

    def delete_selected(self):
        if not self._need_save():
            return None
        sel = self.selected()
        if not sel:
            messagebox.showinfo("Delete", "Select one or more editor backups.", parent=self)
            return None
        game = [p for p, k in sel if k != KIND_EDITOR]
        if game:
            messagebox.showwarning(
                "Delete", "Only editor backups (.pyedit.bak) can be deleted here. "
                "The game's own files and snapshot copies are left alone:\n" +
                "\n".join(os.path.basename(p) for p in game), parent=self)
            return None
        paths = [p for p, _ in sel]
        if not messagebox.askyesno(
                "Delete backups", "Permanently delete %d editor backup%s?\n\n%s" %
                (len(paths), "" if len(paths) == 1 else "s",
                 "\n".join(os.path.basename(p) for p in paths[:15]) + ("\n..." if len(paths) > 15 else "")),
                icon="warning", parent=self):
            return None
        deleted, refused = self._delete_files(paths)
        if refused:
            messagebox.showwarning("Delete", "Could not delete:\n" +
                                   "\n".join(os.path.basename(p) for p in refused), parent=self)
        self.ctx.status("Deleted %d backup(s)" % len(deleted))
        self.refresh()
        return deleted

    def prune(self, keep=None):
        if not self._need_save():
            return None
        if keep is None:
            try:
                keep = int(self.keep_var.get())
            except ValueError:
                keep = -1
        if keep < 1:
            messagebox.showerror("Clean up", "Enter a number of backups to keep (1 or more).", parent=self)
            return None
        eds = [r for r in find_backups(self.target_path()) if r[1] == KIND_EDITOR]  # newest first
        doomed = [r[0] for r in eds[keep:]]
        if not doomed:
            messagebox.showinfo("Clean up", "There are %d editor backups; nothing to remove." % len(eds),
                                parent=self)
            return []
        size = sum(r[3] for r in eds[keep:])
        if not messagebox.askyesno(
                "Clean up editor backups",
                "Keep the newest %d editor backups and delete %d older ones (%s)?\n\n"
                "Only .pyedit.bak files are touched. The game's .backup and .verbackup "
                "files and the full snapshots are never deleted." % (keep, len(doomed), _fmt_size(size)),
                icon="warning", parent=self):
            return None
        deleted, refused = self._delete_files(doomed)
        if refused:
            messagebox.showwarning("Clean up", "Could not delete:\n" +
                                   "\n".join(os.path.basename(p) for p in refused), parent=self)
        self.ctx.status("Cleaned up %d old editor backup(s)" % len(deleted))
        self.refresh()
        return deleted
