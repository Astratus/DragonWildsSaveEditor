"""Main window for the Dragonwilds save editor GUI.

Run with ``python -m dragonwilds_save_editor [save.json]`` (or the installed
``dragonwilds-save-editor`` command / the Windows exe).
"""

import glob
import importlib
import os
import sys
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from .. import catalog
from .. import paths
from .. import save as dw_save
from .about import run_about_dialog
from .catalog_setup import run_catalog_dialog
from .context import AppContext, find_default_world, world_display_name

APP_TITLE = "Dragonwilds Save Editor"
SAVE_DIR = os.path.join(paths.game_saved_dir(), "SaveCharacters")
SMOKE_TEST = os.environ.get("DW_SMOKE_TEST") == "1"

# (tab label, module relative to this package, class name)
TAB_SPECS = [
    ("Character", ".character_tab", "CharacterTab"),
    ("Skills", ".character_tab", "SkillsTab"),
    ("Inventory", ".inventory_tab", "InventoryTab"),
    ("Add Items", ".catalog_tab", "CatalogTab"),
    ("Unlocks", ".unlocks_tab", "UnlocksTab"),
    ("Main Quest", ".quests_tab", "QuestsTab"),
    ("World", ".world_tab", "WorldTab"),
    ("Map", ".map_tab", "MapTab"),
    ("Backups", ".backups_tab", "BackupsTab"),
]


def enable_dpi_awareness():
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def find_default_save(folders=(SAVE_DIR,)):
    """The save to open at startup.

    Looks in the game's real save folder (the file the game actually loads). Within a
    folder, the most recently played character wins.
    """
    for folder in folders:
        path = _newest_save_in(folder)
        if path:
            return path
    return None


def _newest_save_in(folder):
    if not folder or not os.path.isdir(folder):
        return None
    candidates = sorted(glob.glob(os.path.join(folder, "*.json")), key=os.path.getmtime, reverse=True)
    for path in candidates:
        try:
            s = dw_save.SaveFile(path, dw_save.GameData(items=[]))   # structure check only
            if isinstance(s.root, dict) and "GameProgress" in s.root:
                return path
        except Exception:
            continue
    return None


class App:
    def __init__(self, root=None):
        self.root = root or tk.Tk()
        self.root.title(APP_TITLE)
        self.root.minsize(900, 600)
        self.root.geometry("1100x720")
        style = ttk.Style(self.root)
        names = style.theme_names()
        style.theme_use("vista" if "vista" in names else "clam")

        self.ctx = AppContext(self.root)
        self.status_var = tk.StringVar(value="Open a save file to begin.")
        self.dirty_var = tk.StringVar(value="")
        self.file_var = tk.StringVar(value="No save open")
        self.world_var = tk.StringVar(value="No world save open")
        self.world_dirty_var = tk.StringVar(value="")
        self.world_choice_var = tk.StringVar(value="")
        self._world_choices = []   # [(label, path)] behind the world combobox
        self.ctx._status = self.set_status

        self._build_menu()
        self._build_toolbar()
        self._build_notebook()
        self._build_statusbar()

        self.ctx.on_change(self.update_title)
        self.ctx.on_world_change(self._on_world_change)
        self._refresh_world_choices()
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)
        self.root.bind_all("<Control-s>", lambda e: self.on_save())
        self.root.bind_all("<Control-o>", lambda e: self.on_open())
        self.update_title()

    # ---- layout ---------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="Open...", accelerator="Ctrl+O", command=self.on_open)
        fm.add_command(label="Save", accelerator="Ctrl+S", command=self.on_save)
        fm.add_command(label="Revert / Reload", command=self.on_revert)
        fm.add_separator()
        fm.add_command(label="Open containing folder", command=self.on_open_folder)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=fm)
        wm = tk.Menu(menubar, tearoff=0)
        wm.add_command(label="Open world save...", command=self.on_open_world)
        wm.add_command(label="Save world", command=self.on_save_world)
        wm.add_command(label="Revert / Reload world", command=self.on_revert_world)
        wm.add_separator()
        wm.add_command(label="Open world folder", command=self.on_open_world_folder)
        menubar.add_cascade(label="World", menu=wm)
        hm = tk.Menu(menubar, tearoff=0)
        hm.add_command(label="Update item catalog...", command=self.on_update_catalog)
        hm.add_command(label="Reset to bundled catalog", command=self.on_reset_catalog)
        hm.add_separator()
        hm.add_command(label="About Dragonwilds Save Editor...", command=self.on_about)
        menubar.add_cascade(label="Help", menu=hm)
        self.root.config(menu=menubar)

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(6, 6, 6, 2))
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text="Character", width=10, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(bar, text="Open...", command=self.on_open).pack(side="left")
        ttk.Button(bar, text="Save", command=self.on_save).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Revert", command=self.on_revert).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Open folder", command=self.on_open_folder).pack(side="left", padx=(4, 0))
        ttk.Label(bar, textvariable=self.file_var).pack(side="left", padx=(12, 0))
        self.dirty_label = ttk.Label(bar, textvariable=self.dirty_var, foreground="#b00020",
                                     font=("Segoe UI", 9, "bold"))
        self.dirty_label.pack(side="right")

        # Second row: the ONE focused world save every tab uses (ctx.world).
        wbar = ttk.Frame(self.root, padding=(6, 2, 6, 2))
        wbar.pack(side="top", fill="x")
        ttk.Label(wbar, text="World", width=10, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.btn_world_open = ttk.Button(wbar, text="Open...", command=self.on_open_world)
        self.btn_world_save = ttk.Button(wbar, text="Save", command=self.on_save_world)
        self.btn_world_revert = ttk.Button(wbar, text="Revert", command=self.on_revert_world)
        self.btn_world_folder = ttk.Button(wbar, text="Open folder", command=self.on_open_world_folder)
        self.btn_world_open.pack(side="left")
        for b in (self.btn_world_save, self.btn_world_revert, self.btn_world_folder):
            b.pack(side="left", padx=(4, 0))
        self.world_combo = ttk.Combobox(wbar, textvariable=self.world_choice_var, state="readonly",
                                        width=32, postcommand=self._refresh_world_choices)
        self.world_combo.pack(side="left", padx=(12, 0))
        self.world_combo.bind("<<ComboboxSelected>>", lambda e: self.on_world_selected())
        ttk.Label(wbar, textvariable=self.world_var).pack(side="left", padx=(8, 0))
        ttk.Label(wbar, textvariable=self.world_dirty_var, foreground="#b00020",
                  font=("Segoe UI", 9, "bold")).pack(side="right")

        banner = ttk.Label(self.root, padding=(8, 4), background="#fff4ce", foreground="#5c4400",
                           text="Close the game before saving. Every save makes a backup.")
        banner.pack(side="top", fill="x", padx=6, pady=(2, 4))

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(side="top", fill="both", expand=True, padx=6)
        self.tabs = {}
        for label, module, cls_name in TAB_SPECS:
            frame = None
            try:
                mod = importlib.import_module(module, __package__)
                frame = getattr(mod, cls_name)(self.notebook, self.ctx)
            except Exception:  # ImportError, missing class, or a crash in the tab's __init__
                frame = self._placeholder(label, traceback.format_exc())
            self.notebook.add(frame, text=label)
            self.tabs[label] = frame

    def _placeholder(self, label, error):
        f = ttk.Frame(self.notebook, padding=12)
        ttk.Label(f, text="The %s tab could not be loaded." % label,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        txt = tk.Text(f, height=12, wrap="word")
        txt.insert("1.0", error)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, pady=(8, 0))
        f.is_placeholder = True
        return f

    def _build_statusbar(self):
        bar = ttk.Frame(self.root, relief="sunken", padding=(6, 2))
        bar.pack(side="bottom", fill="x")
        ttk.Label(bar, textvariable=self.status_var, anchor="w").pack(side="left", fill="x", expand=True)
        # Pack before the expanding notebook so a small window never squeezes it out.
        bar.pack_forget()
        bar.pack(side="bottom", fill="x", before=self.notebook)

    # ---- state display ----------------------------------------------------------
    def set_status(self, msg):
        self.status_var.set(msg)

    def update_title(self):
        name = os.path.basename(self.ctx.path) if self.ctx.path else None
        star = "*" if (self.ctx.dirty or self.ctx.world_dirty) else ""
        self.root.title("%s%s - %s" % (star, name, APP_TITLE) if name else APP_TITLE)
        if self.ctx.path:
            in_game = os.path.normcase(os.path.dirname(os.path.abspath(self.ctx.path))) == os.path.normcase(SAVE_DIR)
            where = "live game save" if in_game else "copy outside the game folder; the game won't see these edits"
            self.file_var.set("%s  (%s)" % (self.ctx.path, where))
        else:
            self.file_var.set("No save open")
        self.dirty_var.set("Unsaved changes" if self.ctx.dirty else "")
        self.update_world_row()

    def update_world_row(self):
        path = self.ctx.world_path
        if path:
            where = "live game save" if self.ctx.world_is_live else \
                "copy outside the game folder; the game won't see these edits"
            self.world_var.set("%s  (%s)" % (path, where))
        else:
            self.world_var.set("No world save open")
        n = len(self.ctx.world_changes())
        self.world_dirty_var.set("Unsaved world changes (%d)" % n if n else "")
        label = next((lab for lab, p in self._world_choices if _same(p, path)), "")
        if not label and path:
            label = self._world_label(path)
        self.world_choice_var.set(label)

    # ---- actions ------------------------------------------------------------------
    def confirm_discard(self, action="continue"):
        """True if there are no unsaved changes or the user agrees to lose them."""
        if not self.ctx.dirty:
            return True
        return messagebox.askyesno(
            APP_TITLE, "You have unsaved changes. Discard them and %s?" % action,
            icon="warning", parent=self.root)

    def open_path(self, path):
        try:
            self.ctx.load(path)
            return True
        except Exception as e:
            messagebox.showerror(APP_TITLE, "Could not open %s:\n\n%s" % (path, e), parent=self.root)
            return False

    def on_open(self, path=None):
        if not self.confirm_discard("open another file"):
            return
        if path is None:
            start = SAVE_DIR if os.path.isdir(SAVE_DIR) else os.path.expanduser("~")
            path = filedialog.askopenfilename(
                parent=self.root, title="Open character save", initialdir=start,
                filetypes=[("Character saves", "*.json"), ("All files", "*.*")])
        if path:
            self.open_path(path)

    def on_save(self):
        if not self.ctx.save:
            messagebox.showinfo(APP_TITLE, "Open a save file first.", parent=self.root)
            return None
        force = False
        if dw_save.game_is_running():
            if not messagebox.askyesno(
                    APP_TITLE, "Dragonwilds appears to be running. The game may overwrite or "
                    "reject your changes.\n\nSave anyway?", icon="warning", parent=self.root):
                self.set_status("Save cancelled: the game is running.")
                return None
            force = True
        try:
            backup = self.ctx.write(force=force)
        except Exception as e:
            messagebox.showerror(APP_TITLE, "Saving failed:\n\n%s" % e, parent=self.root)
            return None
        messagebox.showinfo(APP_TITLE, "Saved.\n\nBackup of the previous version:\n%s"
                            % os.path.basename(backup), parent=self.root)
        return backup

    def on_revert(self):
        if not self.ctx.save:
            return
        if not self.confirm_discard("reload from disk"):
            return
        self.open_path(self.ctx.path)

    def on_open_folder(self):
        folder = os.path.dirname(os.path.abspath(self.ctx.path)) if self.ctx.path else (
            SAVE_DIR if os.path.isdir(SAVE_DIR) else os.path.expanduser("~"))
        try:
            os.startfile(folder)
        except Exception as e:
            messagebox.showerror(APP_TITLE, "Could not open %s:\n\n%s" % (folder, e), parent=self.root)

    # ---- world actions ------------------------------------------------------------------
    def _world_label(self, path):
        name = world_display_name(path, self.ctx.world if _same(path, self.ctx.world_path) else None)
        base = os.path.basename(path)
        return name if os.path.splitext(base)[0] == name else "%s  (%s)" % (name, base)

    def _refresh_world_choices(self):
        try:
            paths = self.ctx.list_worlds()
        except OSError:
            paths = []
        self._world_choices = [(self._world_label(p), p) for p in paths]
        self.world_combo["values"] = [lab for lab, _ in self._world_choices]
        self.update_world_row()

    def confirm_discard_world(self, action="continue"):
        """True if the focused world has no unsaved edits or the user agrees to lose them."""
        changes = self.ctx.world_changes()
        if not changes:
            return True
        return messagebox.askyesno(
            APP_TITLE, "You have %d unsaved WORLD edit(s):\n\n- %s\n\nDiscard them and %s?"
            % (len(changes), "\n- ".join(changes[:10]), action),
            icon="warning", default="no", parent=self.root)

    def open_world_path(self, path, event="load"):
        try:
            self.root.config(cursor="watch")
            self.root.update_idletasks()
            self.ctx.load_world(path, event=event)
            return True
        except Exception as e:  # world format errors must fail soft
            messagebox.showerror(APP_TITLE, "Could not open world save %s:\n\n%s" % (path, e),
                                 parent=self.root)
            return False
        finally:
            self.root.config(cursor="")
            self._refresh_world_choices()

    def on_world_selected(self):
        label = self.world_choice_var.get()
        path = next((p for lab, p in self._world_choices if lab == label), None)
        if not path or _same(path, self.ctx.world_path):
            self.update_world_row()
            return None
        if not self.confirm_discard_world("switch to another world"):
            self.update_world_row()   # put the combobox back on the focused world
            return False
        return self.open_world_path(path)

    def on_open_world(self, path=None):
        if path is None:
            folder = self.ctx.world_folder
            start = folder if os.path.isdir(folder) else os.path.expanduser("~")
            path = filedialog.askopenfilename(
                parent=self.root, title="Open world save", initialdir=start,
                filetypes=[("World saves", "*.sav"), ("All files", "*.*")])
        if not path:
            return None
        path = os.path.normpath(path)
        if not _same(path, self.ctx.world_path) and not self.confirm_discard_world("open another world"):
            return False
        return self.open_world_path(path)

    def on_save_world(self):
        if self.ctx.world is None:
            messagebox.showinfo(APP_TITLE, "Open a world save first.", parent=self.root)
            return None
        w = self.ctx.world
        if not w.dirty:
            messagebox.showinfo(APP_TITLE, "The focused world has no unsaved changes.", parent=self.root)
            return None
        if not messagebox.askyesno(
                APP_TITLE, "Write these EXPERIMENTAL world edits to\n%s?\n\n- %s\n\nFirst, ALL character "
                "and world saves are snapshotted to the editor's backups folder (pre-world-edit_*), and this file is backed up "
                "as .pyedit.bak. The result is re-read and verified before it replaces the file.\n\n"
                "Afterwards, consider deleting Saved\\SpudCache\\* so a stale cache can't shadow the edit."
                % (w.path, "\n- ".join(self.ctx.world_changes())), icon="warning", parent=self.root):
            return None
        force = False
        if dw_save.game_is_running():
            if not messagebox.askyesno(
                    APP_TITLE, "Dragonwilds appears to be running and will likely overwrite the world "
                    "when it saves.\n\nWrite anyway?", icon="warning", default="no", parent=self.root):
                self.set_status("World save cancelled: the game is running.")
                return None
            force = True
        try:
            result = self.ctx.write_world(force=force)
        except Exception as e:
            messagebox.showerror(APP_TITLE, "Saving the world failed; the file was not replaced.\n\n%s" % e,
                                 parent=self.root)
            return None
        msg = "World saved.\n\nBackup: %s" % os.path.basename(result["backup"])
        if result.get("snapshot"):
            msg += "\nFull snapshot: %s" % result["snapshot"]
        messagebox.showinfo(APP_TITLE, msg, parent=self.root)
        return result

    def on_revert_world(self):
        if not self.ctx.world_path:
            return None
        if not self.confirm_discard_world("reload the world from disk"):
            return False
        return self.open_world_path(self.ctx.world_path, event="reload")

    def on_open_world_folder(self):
        folder = os.path.dirname(os.path.abspath(self.ctx.world_path)) if self.ctx.world_path else (
            self.ctx.world_folder if os.path.isdir(self.ctx.world_folder) else os.path.expanduser("~"))
        try:
            os.startfile(folder)
        except Exception as e:
            messagebox.showerror(APP_TITLE, "Could not open %s:\n\n%s" % (folder, e), parent=self.root)

    def _on_world_change(self):
        self.update_title()

    # ---- item catalog -----------------------------------------------------------
    def check_catalog(self):
        """Startup check, no dialog: the bundled catalog is always there, so this
        only reports a damaged install (no catalog could be loaded) in the status bar."""
        if not self.ctx.game.catalog_missing:
            return True
        self.set_status("No item catalog could be loaded (damaged install?): items and unlocks "
                        "show as raw IDs. Reinstall, or use Help > Update item catalog.")
        return False

    def on_update_catalog(self):
        """Help > Update item catalog: the optional rebuild from the installed game."""
        if run_catalog_dialog(self.root):
            self._catalog_reloaded("Item catalog updated")

    def on_reset_catalog(self):
        """Help > Reset to bundled catalog: delete the user-built catalog."""
        if not catalog.is_built():
            messagebox.showinfo(APP_TITLE, "The editor is already using its bundled item catalog.",
                                parent=self.root)
            return False
        if not messagebox.askyesno(
                APP_TITLE, "Delete the item catalog built on this computer and use the catalog "
                "bundled with the editor again?", parent=self.root):
            return False
        try:
            catalog.reset_to_bundled()
        except OSError as e:
            messagebox.showerror(APP_TITLE, "Could not remove the built catalog:\n\n%s" % e,
                                 parent=self.root)
            return False
        self._catalog_reloaded("Using the bundled item catalog")
        return True

    def _catalog_reloaded(self, what):
        try:
            self.ctx.reload_catalog()
        except Exception as e:
            messagebox.showerror(APP_TITLE, "The item catalog could not be loaded:\n\n%s" % e,
                                 parent=self.root)
            return
        info = catalog.active_status() or {}
        self.set_status("%s: %d items (game version %s)."
                        % (what, len(self.ctx.game.items), info.get("game_version") or "?"))

    def on_about(self):
        run_about_dialog(self.root)

    def on_exit(self):
        if self.confirm_discard("exit") and self.confirm_discard_world("exit"):
            self.root.destroy()


def _same(a, b):
    """True if a and b name the same file (False if either is empty/None)."""
    return bool(a) and bool(b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def main(path=None, world=None):
    enable_dpi_awareness()
    app = App()
    if SMOKE_TEST:
        # Headless smoke test: build the UI, then close it shortly after.
        app.root.after(500, app.root.destroy)
    if not path:
        path = find_default_save()
    if path:
        app.open_path(path)
    if not world:
        world = find_default_world()
    if world:
        app.open_world_path(world)
    app.root.after(200, app.check_catalog)
    app.root.mainloop()
    return app


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
