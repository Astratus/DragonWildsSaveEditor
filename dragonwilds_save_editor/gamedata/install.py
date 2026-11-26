"""Find the player's RuneScape: Dragonwilds installation (read-only; nothing is recorded).

Where it looks, in order:

1. Steam libraries: the Steam folder (registry, else the default location), its
   steamapps/libraryfolders.vdf, and in every library steamapps/common/*Dragonwilds*.
2. The game's own logs (%LOCALAPPDATA%\\RSDragonwilds\\Saved\\Logs\\*.log), which record absolute
   paths such as ``D:/Games/Dragonwilds/RSDragonwilds/Binaries/Win64/...``.
3. Common folders on fixed drives: <drive>:\\*Dragonwilds*, <drive>:\\Games\\*Dragonwilds*,
   Program Files, SteamLibrary, Epic Games and Jagex Launcher game folders.

A folder counts as the game when it holds RSDragonwilds/Content/Paks with both IoStore
containers. The GUI falls back to a folder picker when nothing is found. Paths found here are
only used to read the game; they are never written into a catalog or its build info.
"""

import glob
import os
import re

from .. import paths
from ..catalog import GameNotFoundError
from .game import CONTAINER, GLOBAL_CONTAINER

GAME_SUBDIR = "RSDragonwilds"
PAKS_REL = (GAME_SUBDIR, "Content", "Paks")
NAME_PATTERN = "*[Dd]ragon[Ww]ilds*"
LOG_BYTES = 4 * 1024 * 1024          # read at most the first 4 MB of each log
_LOG_PATH_RE = re.compile(r"([A-Za-z]:[\\/][^\r\n\"'<>|*?]*?)[\\/]RSDragonwilds[\\/]"
                          r"(?:Binaries|Content|Plugins)[\\/]")


def paks_dir_of(folder):
    """The Paks folder if `folder` is the install root, its RSDragonwilds folder or the Paks
    folder itself (and the containers are there); else None."""
    if not folder:
        return None
    folder = os.path.abspath(folder)
    for cand in (os.path.join(folder, *PAKS_REL), os.path.join(folder, *PAKS_REL[1:]), folder):
        if os.path.isfile(os.path.join(cand, CONTAINER)) and os.path.isfile(os.path.join(cand, GLOBAL_CONTAINER)):
            return cand
    return None


def install_root(paks_dir):
    """<root> for <root>/RSDragonwilds/Content/Paks."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(paks_dir))))


# --- Steam ------------------------------------------------------------------------------------

def _steam_roots():
    roots = []
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg:
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(os.path.normpath(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                pass
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(env):
            roots.append(os.path.join(os.environ[env], "Steam"))
    roots.append(os.path.join(os.path.expanduser("~"), ".steam", "steam"))
    roots.append(os.path.join(os.path.expanduser("~"), ".local", "share", "Steam"))
    return roots


def parse_library_folders(text):
    """Library paths from a libraryfolders.vdf text ("path" values; older files use "1" ...)."""
    out = []
    for key, value in re.findall(r'"([^"]+)"\s+"([^"]*)"', text):
        if key == "path" or key.isdigit():
            v = value.replace("\\\\", "\\")
            if os.path.isabs(v) or re.match(r"^[A-Za-z]:", v):
                out.append(v)
    return out


def steam_candidates(steam_roots=None):
    """Game folders in Steam libraries."""
    libraries = []
    for root in steam_roots if steam_roots is not None else _steam_roots():
        if not os.path.isdir(root):
            continue
        libraries.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                libraries.extend(parse_library_folders(f.read()))
        except OSError:
            pass
    out = []
    for lib in libraries:
        out.extend(sorted(glob.glob(os.path.join(glob.escape(lib), "steamapps", "common", NAME_PATTERN))))
    return out


# --- the game's logs --------------------------------------------------------------------------

def default_log_dir():
    return os.path.join(paths.game_saved_dir(), "Logs")


def log_candidates(log_dir=None):
    """Install roots recorded in the game's own logs, newest log first."""
    logs = glob.glob(os.path.join(glob.escape(log_dir or default_log_dir()), "*.log"))
    logs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    out = []
    for log in logs:
        try:
            with open(log, "rb") as f:     # shared read; the game may be writing it
                text = f.read(LOG_BYTES).decode("utf-8", "replace")
        except OSError:
            continue
        for m in _LOG_PATH_RE.finditer(text):
            root = os.path.normpath(m.group(1))
            if root not in out:
                out.append(root)
    return out


# --- common folders ---------------------------------------------------------------------------

def _fixed_drives():
    if os.name != "nt":
        return []
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        drives = []
        for i in range(26):
            if mask & (1 << i):
                d = "%s:\\" % chr(65 + i)
                if k32.GetDriveTypeW(d) == 3:  # DRIVE_FIXED: never touch removable/optical drives
                    drives.append(d)
        return drives
    except (AttributeError, OSError):
        return []


COMMON_PARENTS = ("", "Games", "Program Files", "Program Files (x86)",
                  os.path.join("Program Files", "Epic Games"),
                  os.path.join("SteamLibrary", "steamapps", "common"),
                  os.path.join("Program Files (x86)", "Jagex Launcher", "Games"),
                  os.path.join("Program Files", "Jagex Launcher", "Games"))


def common_candidates(drives=None):
    out = []
    for d in drives if drives is not None else _fixed_drives():
        for parent in COMMON_PARENTS:
            base = os.path.join(d, parent)
            if os.path.isdir(base):
                out.extend(sorted(glob.glob(os.path.join(glob.escape(base), NAME_PATTERN))))
    return out


# --- all together -----------------------------------------------------------------------------

def candidates(steam_roots=None, log_dir=None, drives=None):
    """[(install root, how it was found)] of every valid game folder, best first, no duplicates."""
    found, seen = [], set()
    for how, folders in (("Steam library", lambda: steam_candidates(steam_roots)),
                         ("game log", lambda: log_candidates(log_dir)),
                         ("common folder", lambda: common_candidates(drives))):
        try:
            folders = folders()
        except OSError:
            continue
        for folder in folders:
            paks = paks_dir_of(folder)
            if not paks:
                continue
            root = install_root(paks)
            key = os.path.normcase(os.path.normpath(root))
            if key not in seen:
                seen.add(key)
                found.append((root, how))
    return found


def find_paks_dir(game_dir=None, **search):
    """The Paks folder of `game_dir` (install root, RSDragonwilds or Paks folder), or of the
    first detected installation when `game_dir` is None. Raises GameNotFoundError."""
    if game_dir:
        paks = paks_dir_of(game_dir)
        if not paks:
            raise GameNotFoundError(
                "%s is not a RuneScape: Dragonwilds installation folder (expected "
                "RSDragonwilds\\Content\\Paks with %s and %s inside)." % (game_dir, CONTAINER, GLOBAL_CONTAINER))
        return paks
    found = candidates(**search)
    if not found:
        raise GameNotFoundError(
            "RuneScape: Dragonwilds was not found on this computer. Choose its installation "
            "folder (the one that contains RSDragonwilds), or pass --game-dir FOLDER.")
    return paks_dir_of(found[0][0])
