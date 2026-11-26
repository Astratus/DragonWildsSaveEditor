"""Shared state passed to every GUI tab.

Contract for tab modules
------------------------
Each tab is a class ``SomethingTab(ttk.Frame)`` constructed as ``SomethingTab(notebook, ctx)``
and exposing ``refresh(self)``. It reads and edits ``ctx.save`` IN MEMORY only, then calls
``ctx.mark_dirty("what changed")``. Tabs never write the file themselves: the app's
Save action calls ``ctx.write()``, which always makes a backup first (SaveFile.save ->
SaveFile.make_backup). The one exception is restoring a backup, which goes through
``ctx.restore_backup()`` and also backs up the current file first.

Focused world (one per app)
---------------------------
``ctx.world`` is the ONE world save (dw_spud.WorldFile) every tab should use; the toolbar's
World row picks it. Tabs edit ``ctx.world`` in memory through dw_spud's edit methods, then call
``ctx.mark_world_dirty("what changed")`` (the message is kept as the change list). Register a
redraw with ``ctx.on_world_change(fn)``; it runs after every load/reload/save/restore/edit/
close, and ``ctx.world_event`` says which. Only the app's World Save (``ctx.write_world()``)
and the Backups tab (``ctx.restore_world_backup()``) write the .sav; both back it up first.
"""

import os
import shutil
import tempfile

from .. import save as dw_save
from .. import spud as dw_spud

WORLD_SAVE_DIR = dw_spud.WORLD_SAVE_DIR   # informational; functions read dw_spud's at call time


def list_worlds(folder=None):
    """World .sav files in folder (default: the game's SaveGames), newest first."""
    folder = folder or dw_spud.WORLD_SAVE_DIR
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    paths = [os.path.join(folder, n) for n in names
             if n.lower().endswith(".sav") and os.path.isfile(os.path.join(folder, n))]
    return sorted(paths, key=os.path.getmtime, reverse=True)


def find_default_world(folders=None):
    """Newest world .sav in the game's SaveGames folder (same rule the World tab used)."""
    for folder in (folders or (dw_spud.WORLD_SAVE_DIR,)):
        paths = list_worlds(folder)
        if paths:
            return paths[0]
    return None


_NAME_CACHE = {}   # normcased path -> ((mtime, size), name or None)


def world_display_name(path, world=None):
    """The world's in-game name (INFO/CINF WorldName) if it has one, else the file name.

    Cached by (mtime, size); pass an already parsed WorldFile to avoid a re-parse."""
    fallback = os.path.splitext(os.path.basename(path))[0]
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        key = None
    ck = os.path.normcase(os.path.abspath(path))
    hit = _NAME_CACHE.get(ck)
    if world is None and hit is not None and key is not None and hit[0] == key:
        return hit[1] or fallback
    try:
        w = world if world is not None else dw_spud.WorldFile(path)
        name = w.world_name()
    except Exception:
        name = None
    if key is not None and (world is None or not world.dirty):
        _NAME_CACHE[ck] = (key, name)
    return name or fallback


def is_live_world(path, folder=None):
    """True if path is directly inside the game's SaveGames folder."""
    if not path:
        return False
    return os.path.normcase(os.path.dirname(os.path.abspath(path))) == \
        os.path.normcase(os.path.abspath(folder or dw_spud.WORLD_SAVE_DIR))


def _same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class AppContext:
    def __init__(self, root):
        self.root = root                 # the Tk root window (use as dialog parent)
        # Item catalog (bundled, or rebuilt on this machine), skills, xp table. If no catalog can
        # be loaded the item list is empty (game.catalog_missing). After Help > Update item
        # catalog / Reset to bundled catalog the app calls reload_catalog().
        self.game = dw_save.GameData(require_catalog=False)
        self.save = None                 # dw_save.SaveFile or None when nothing is open
        self.dirty = False
        # Set by quest edits: the next write first snapshots ALL character + world saves.
        self.needs_full_snapshot = False
        self._listeners = []             # callables run after load/reload/write/edits
        self._status = lambda msg: None  # set by the app's status bar
        # Focused world save (see module docstring).
        self.world = None                # dw_spud.WorldFile or None
        self.world_folder = dw_spud.WORLD_SAVE_DIR   # read at startup (tests patch it)
        self.world_event = None          # last world event: load/reload/save/restore/edit/close
        self._world_notes = []           # mark_world_dirty messages for the focused world
        self._world_listeners = []

    # ---- notifications -------------------------------------------------------
    def on_change(self, fn):
        """Register fn() to be called whenever the save is loaded, reloaded or edited."""
        self._listeners.append(fn)

    def refresh_all(self):
        for fn in list(self._listeners):
            fn()

    def status(self, msg):
        self._status(msg)

    def mark_dirty(self, msg=""):
        self.dirty = True
        self.status((msg + " - " if msg else "") + "unsaved changes")
        self.refresh_all()

    def reload_catalog(self):
        """Re-read the item catalog (after an update or reset) and point the open save at it; no file I/O
        on the save, unsaved edits are kept. Tabs re-index in their refresh()."""
        self.game = dw_save.GameData(require_catalog=False)
        if self.save is not None:
            self.save.game = self.game
        self.refresh_all()

    # ---- file operations -----------------------------------------------------
    @property
    def path(self):
        return self.save.path if self.save else None

    def load(self, path):
        self.save = dw_save.SaveFile(path, self.game)
        self.dirty = False
        self.needs_full_snapshot = False
        self.status("Opened %s" % os.path.basename(path))
        self.refresh_all()

    def reload(self):
        if self.path:
            self.load(self.path)

    def write(self, force=False):
        """Write the in-memory save to disk. Always backs up first. Returns the backup path."""
        if not self.save:
            raise RuntimeError("No save is open.")
        snapshot = None
        if self.needs_full_snapshot:
            if not force and dw_save.game_is_running():
                raise RuntimeError("Dragonwilds appears to be running. Close it first.")
            # Raises (and nothing is written) if the snapshot cannot be made and verified.
            snapshot = dw_save.snapshot_game_saves("pre-quest")
        backup = self.save.save(force=force)
        # Re-read so the in-memory copy matches the disk exactly.
        self.load(self.save.path)
        msg = "Saved. Backup: %s" % os.path.basename(backup)
        if snapshot:
            msg += " | Full character+world snapshot: %s" % snapshot
        self.status(msg)
        return backup

    def restore_backup(self, backup_path, force=False):
        """Replace the open save with a backup file. Backs up the current save first."""
        if not self.save:
            raise RuntimeError("No save is open.")
        if not force and dw_save.game_is_running():
            raise RuntimeError("Dragonwilds appears to be running. Close it first.")
        dw_save.SaveFile(backup_path, self.game)  # raises if the backup isn't valid JSON
        safety = self.save.make_backup()
        shutil.copy2(backup_path, self.save.path)
        self.load(self.save.path)
        self.status("Restored %s (previous version kept as %s)"
                    % (os.path.basename(backup_path), os.path.basename(safety)))
        return safety

    # ---- focused world ---------------------------------------------------------
    def on_world_change(self, fn):
        """Register fn() to run after the focused world is loaded, reloaded, saved,
        restored, edited or closed (``ctx.world_event`` says which)."""
        self._world_listeners.append(fn)

    def refresh_world(self, event=None):
        if event:
            self.world_event = event
        for fn in list(self._world_listeners):
            fn()

    @property
    def world_path(self):
        return self.world.path if self.world is not None else None

    def world_changes(self):
        """Human-readable list of the focused world's unsaved edits ([] if none)."""
        if self.world is None or not self.world.dirty:
            return []
        return list(self._world_notes) or ["unsaved world edit(s)"]

    @property
    def world_dirty(self):
        return self.world is not None and self.world.dirty

    @property
    def world_is_live(self):
        return is_live_world(self.world_path, self.world_folder)

    def world_name(self):
        """Display name of the focused world (in-game name, else file name), or None."""
        if self.world is None:
            return None
        return world_display_name(self.world.path, self.world)

    def list_worlds(self):
        """World saves in ctx.world_folder (newest first), plus the focused one if elsewhere."""
        paths = list_worlds(self.world_folder)
        cur = self.world_path
        if cur and not any(_same_path(cur, p) for p in paths):
            paths.insert(0, cur)
        return paths

    def mark_world_dirty(self, msg=""):
        if msg:
            self._world_notes.append(msg)
        self.status((msg + " - " if msg else "") + "unsaved world changes")
        self.refresh_world("edit")

    def load_world(self, path, event="load"):
        """Parse path and focus it. Raises on an unreadable file; the old world stays focused.
        Discards unsaved edits of the previous world: callers confirm first."""
        w = dw_spud.WorldFile(path)
        self.world = w
        self._world_notes = []
        self.status("World: %s" % os.path.basename(path))
        self.refresh_world(event)
        return w

    def reload_world(self):
        if self.world_path:
            return self.load_world(self.world_path, event="reload")
        return None

    def close_world(self):
        self.world = None
        self._world_notes = []
        self.refresh_world("close")

    def write_world(self, force=False):
        """Write the focused world's edits via dw_spud.WorldFile.save(): refuses while the game
        runs (unless force) and if the file changed on disk since it was opened (always), snapshots ALL character + world saves to <editor backups folder>/pre-world-edit_*,
        makes <file>.<stamp>.pyedit.bak, verifies and replaces. Returns save()'s result dict."""
        if self.world is None:
            raise RuntimeError("No world save is open.")
        if not self.world.dirty:
            raise RuntimeError("The focused world has no unsaved changes.")
        if self.world.changed_on_disk():
            # dw_spud's force also skips this check; "force" here only means "game running".
            raise RuntimeError("The world file changed on disk since it was opened; reopen it.")
        result = self.world.save(force=force)
        self.load_world(self.world.path, event="save")
        msg = "World saved. Backup: %s" % os.path.basename(result["backup"])
        if result.get("snapshot"):
            msg += " | Full character+world snapshot: %s" % result["snapshot"]
        self.status(msg)
        return result

    def restore_world_backup(self, backup_path, force=False):
        """Replace the focused world's .sav with backup_path.

        Refuses while the game runs (unless force) and if the backup does not parse as a
        world save; backs up the current file first (<file>.<stamp>.pyedit.bak); copies via a
        verified temp file; reloads (unsaved in-memory world edits are discarded).
        Returns the safety backup path, or None if the focused file no longer existed."""
        if self.world is None:
            raise RuntimeError("No world save is open.")
        target = self.world.path
        if _same_path(backup_path, target):
            raise RuntimeError("That is the focused world file itself.")
        if not force and dw_save.game_is_running():
            raise RuntimeError("Dragonwilds appears to be running. Close it first.")
        with open(backup_path, "rb") as f:
            raw = f.read()
        dw_spud.WorldFile.validate_bytes(raw)   # raises FormatError (a ValueError) if not a world save
        safety = self.world.make_backup() if os.path.isfile(target) else None
        folder = os.path.dirname(os.path.abspath(target))
        fd, tmp = tempfile.mkstemp(prefix=".dw_spud_restore_", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            with open(tmp, "rb") as f:
                if f.read() != raw:
                    raise RuntimeError("Temp file does not match the backup; nothing restored.")
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        self.load_world(target, event="restore")
        self.status("Restored world from %s%s" % (
            os.path.basename(backup_path),
            " (previous version kept as %s)" % os.path.basename(safety) if safety else ""))
        return safety
