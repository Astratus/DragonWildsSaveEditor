"""Help > Update item catalog: rebuild the item catalog from the player's installed game.

The editor ships its own item catalog (data/catalog/), so this is never needed to start. On
request, catalog.build() reads the player's own installed copy of the game (found
automatically, or chosen with a folder picker), checks the result (catalog.self_check) and only
then stores it in the user data folder. The game folder is only read; no network connection is
made. The build runs on a worker thread; progress comes back through root.after polling and the
thread never touches Tk.

run_catalog_dialog(parent) -> True if a catalog was built, else False.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from .. import catalog

TITLE = "Update item catalog"
POLL_MS = 100
STAGES = {"open": "Opening the game's data", "decode": "Reading game assets",
          "derive": "Building the catalog", "check": "Checking the result"}

INTRO = (
    "Optional. The editor already includes an item catalog (item names, stack sizes, unlock "
    "names), generated from the game's data, so you don't need this to use it.\n\n"
    "Update item catalog rebuilds the catalog from YOUR installed copy of RuneScape: "
    "Dragonwilds, for example after a game patch the bundled catalog does not cover yet. The "
    "game's files are only read (never changed), it works while the game is running, and no "
    "network connection is made. The result is checked before it is used; if the check fails, "
    "the current catalog is kept.\n\n"
    "It is stored in %LOCALAPPDATA%\\DragonwildsSaveEditor\\catalog and used instead of the "
    "bundled catalog until you choose Help > Reset to bundled catalog.")

NOT_FOUND = ("The game was not found automatically. Choose its installation folder (the one "
             "that contains the RSDragonwilds folder).")


def _detect():
    """The first detected install root, or None."""
    from ..gamedata import install
    found = install.candidates()
    return found[0][0] if found else None


class CatalogDialog(tk.Toplevel):
    def __init__(self, parent, build_fn=None, detect_fn=None):
        super().__init__(parent)
        self.title(TITLE)
        self.transient(parent)
        self.resizable(False, False)
        self.result = False
        self.info = None
        self._build_fn = build_fn or catalog.build
        self._queue = queue.Queue()
        self._worker = None
        self._cancelled = False
        try:
            self.game_dir = (detect_fn or _detect)()
        except Exception:   # detection is best effort; the folder picker remains
            self.game_dir = None

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        self.text_var = tk.StringVar(value=INTRO)
        ttk.Label(body, textvariable=self.text_var, wraplength=480, justify="left").pack(anchor="w")
        self.game_var = tk.StringVar()
        ttk.Label(body, textvariable=self.game_var, wraplength=480, justify="left").pack(anchor="w", pady=(10, 0))
        self.stage_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.stage_var, foreground="gray30").pack(anchor="w", pady=(12, 2))
        self.progress = ttk.Progressbar(body, length=480, mode="determinate", maximum=1)
        self.progress.pack(fill="x")
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self.on_cancel)
        self.cancel_btn.pack(side="right")
        self.pick_btn = ttk.Button(btns, text="Choose game folder...", command=self.on_pick)
        self.pick_btn.pack(side="right", padx=(0, 6))
        self.start_btn = ttk.Button(btns, text="Update from game", command=self.on_start)
        self.start_btn.pack(side="right", padx=(0, 6))
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self._show_game()
        (self.start_btn if self.game_dir else self.pick_btn).focus_set()

    def _show_game(self):
        if self.game_dir:
            self.game_var.set("Game folder: %s" % self.game_dir)
            self.start_btn.state(["!disabled"])
        else:
            self.game_var.set(NOT_FOUND)
            self.start_btn.state(["disabled"])

    # ---- actions --------------------------------------------------------------
    def on_start(self):
        if self._worker is not None or not self.game_dir:
            return
        self._set_running(True)
        self.stage_var.set("Starting...")
        self._worker = threading.Thread(target=self._run, args=(self.game_dir,), daemon=True)
        self._worker.start()
        self.after(POLL_MS, self._poll)

    def on_pick(self):
        folder = filedialog.askdirectory(parent=self, title="Choose the RuneScape: Dragonwilds folder",
                                         mustexist=True)
        if folder:
            self.game_dir = os.path.normpath(folder)
            self._show_game()
            self.on_start()

    def on_cancel(self):
        # The worker only reads; it is a daemon thread and stops at its next progress report.
        self._cancelled = True
        self.result = False
        self.destroy()

    # ---- worker ---------------------------------------------------------------
    def _run(self, game_dir):
        def progress(stage, done, total):
            if self._cancelled:
                raise _Cancelled()
            self._queue.put(("progress", stage, done, total))
        try:
            info = self._build_fn(game_dir=game_dir, progress=progress)
            self._queue.put(("done", info))
        except _Cancelled:
            pass
        except catalog.GameNotFoundError as e:
            self._queue.put(("notfound", str(e)))
        except catalog.SelfCheckError as e:
            self._queue.put(("check", "\n".join("• " + p for p in e.problems)))
        except Exception as e:  # CatalogError, OSError, unreadable game files, ...
            self._queue.put(("error", "%s: %s" % (type(e).__name__, e)))

    def _poll(self):
        if self._cancelled or not self.winfo_exists():
            return
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, stage, done, total = msg
                    self.stage_var.set("%s: %d of %d" % (STAGES.get(stage, stage), done, total))
                    self.progress.configure(maximum=max(total, 1), value=done)
                elif kind == "done":
                    self.info = msg[1]
                    self.result = True
                    self.destroy()
                    return
                elif kind == "notfound":
                    self.game_dir = None
                    self._failed(msg[1])
                    return
                elif kind == "check":
                    self._failed("The catalog built from the game did not pass its check, so the "
                                 "current catalog was kept (nothing was changed):\n\n%s\n\nA game "
                                 "update may have changed the data layout; a newer editor version "
                                 "will handle it." % msg[1])
                    return
                else:
                    self._failed("Building the catalog failed (nothing was changed):\n\n%s" % msg[1])
                    return
        except queue.Empty:
            pass
        self.after(POLL_MS, self._poll)

    def _failed(self, text):
        self._worker = None
        self.text_var.set(text)
        self.stage_var.set("")
        self.progress.configure(value=0)
        self.start_btn.configure(text="Try again")
        self._set_running(False)
        self._show_game()

    def _set_running(self, running):
        for b in (self.start_btn, self.pick_btn):
            b.state(["disabled"] if running else ["!disabled"])


class _Cancelled(Exception):
    pass


def run_catalog_dialog(parent, build_fn=None, detect_fn=None, auto_cancel_ms=None):
    """Show the dialog modally; True if a catalog was built. auto_cancel_ms closes it unattended
    (tests)."""
    dlg = CatalogDialog(parent, build_fn=build_fn, detect_fn=detect_fn)
    if auto_cancel_ms is not None:
        dlg.after(auto_cancel_ms, dlg.on_cancel)
    try:
        dlg.grab_set()
    except tk.TclError:   # parent not viewable yet (e.g. withdrawn); the dialog still works
        pass
    parent.wait_window(dlg)
    return dlg.result
