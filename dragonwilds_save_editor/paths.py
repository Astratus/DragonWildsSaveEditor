"""Filesystem locations used by the editor (stdlib only).

* resource_path(*parts)  - read-only files shipped inside the package
                           (dragonwilds_save_editor/data/*.json, ...). Works from a source
                           checkout, an installed wheel and a PyInstaller build (the bundle
                           keeps the same dragonwilds_save_editor/data layout under
                           sys._MEIPASS).
* user_data_dir()        - per-user writable folder for snapshots, logs and settings:
                           %LOCALAPPDATA%\\DragonwildsSaveEditor (created on demand).
* game_saved_dir()       - the game's own save root: %LOCALAPPDATA%\\RSDragonwilds\\Saved.

No user-specific path is hard-coded anywhere; everything derives from LOCALAPPDATA
(with a home-directory fallback on systems that do not set it).
"""

import os
import sys

APP_DIR_NAME = "DragonwildsSaveEditor"
GAME_DIR_NAME = "RSDragonwilds"

PACKAGE_NAME = "dragonwilds_save_editor"
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def base_dir():
    """Folder holding the package's read-only resources (the package directory itself)."""
    if getattr(sys, "frozen", False):
        # PyInstaller: the spec copies the package's data/ to <bundle>/dragonwilds_save_editor/data.
        bundle = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        return os.path.join(bundle, PACKAGE_NAME)
    return _PACKAGE_DIR


def resource_path(*parts):
    """Absolute path of a bundled read-only file, e.g. resource_path("data", "items.json")."""
    return os.path.join(base_dir(), *parts)


def _local_appdata():
    path = os.environ.get("LOCALAPPDATA")
    if path:
        return path
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def user_data_dir(*parts):
    """%LOCALAPPDATA%\\DragonwildsSaveEditor[\\parts...], created if missing."""
    path = os.path.join(_local_appdata(), APP_DIR_NAME, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def game_saved_dir():
    """%LOCALAPPDATA%\\RSDragonwilds\\Saved (may not exist; never created here)."""
    return os.path.join(_local_appdata(), GAME_DIR_NAME, "Saved")
