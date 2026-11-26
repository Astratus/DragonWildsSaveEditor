"""Help > About: version, licence, the Jagex Fan Content Policy notice (paragraph 8.1, see
docs/LICENSING.md), a short credits summary and which item catalog is in use (bundled or
updated on this computer).

The text is in a read-only Text widget so it can be selected and copied.
run_about_dialog(parent) shows it modally.
"""

import tkinter as tk
import webbrowser
from tkinter import ttk

from .. import __version__, catalog

TITLE = "About Dragonwilds Save Editor"
APP_NAME = "Dragonwilds Save Editor"
REPO_URL = "https://github.com/Astratus/DragonWildsSaveEditor"
CREDITS_URL = REPO_URL + "/blob/main/CREDITS.md"

DESCRIPTION = "Unofficial save editor for RuneScape: Dragonwilds (character and world saves)."
LICENCE_LINE = "Free, non-commercial, MIT License."
# Required notice, Jagex Fan Content Policy 8.1 (exact wording; also in LICENSE, README, CREDITS.md).
JAGEX_NOTICE = ("Created using intellectual property belonging to Jagex Limited under the terms of "
                "Jagex's Fan Content Policy. This content is not endorsed by or affiliated with Jagex.")
TRADEMARKS = ("RuneScape, RuneScape: Dragonwilds and Jagex are trademarks of Jagex Limited. "
              "All game names, IDs and other game data belong to Jagex Limited.")
CREDITS = (
    "Credits:\n"
    "\u2022 World-save (SPUD) format: sinbad/SPUD, MIT License (independent clean-room reader).\n"
    "\u2022 Item catalog: our own compilation of Jagex game data (IDs, names, stack sizes), "
    "generated from an installed copy of the game.\n"
    "\u2022 Game file formats: CUE4Parse (Apache-2.0) used as a format reference; no code included.\n"
    "\u2022 Cross-checks: the RuneScape: Dragonwilds Wiki (CC BY-NC-SA 3.0).")


OFFLINE_LINE = ("Works entirely offline: no network connections. (The two buttons below open "
                "your web browser, only when you click them.)")


def catalog_line(info=None):
    """One line describing the item catalog in use (``info`` defaults to active_status()):
    "bundled (from game version 1.0.2.2)" or "updated <date> (from your installed game, ...)"."""
    if info is None:
        info = catalog.active_status()
    if not info:
        return "Item catalog: none could be loaded (reinstall, or Help > Update item catalog)."
    version = info.get("game_version") or "?"
    origin = info.get("origin") or ("bundled" if info.get("mode") == "bundled" else "user")
    if origin == "bundled":
        line = "bundled (from game version %s)" % version
    else:
        line = "updated %s (from your installed game, version %s)" % (
            str(info.get("built_at") or "?").split("T")[0], version)
    items = (info.get("counts") or {}).get("items")
    if items is not None:
        line += ", %d items" % items
    return "Item catalog: " + line + "."


def about_text(info=None):
    """The full body text of the About box (without the title line)."""
    return "\n\n".join([DESCRIPTION, LICENCE_LINE, OFFLINE_LINE, JAGEX_NOTICE, TRADEMARKS,
                        CREDITS, catalog_line(info)])


class AboutDialog(tk.Toplevel):
    def __init__(self, parent, info=None):
        super().__init__(parent)
        self.title(TITLE)
        self.transient(parent)
        self.resizable(False, False)

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        self.heading = "%s %s" % (APP_NAME, __version__)
        ttk.Label(body, text=self.heading, font=("TkDefaultFont", 12, "bold")).pack(anchor="w")

        text = about_text(info)
        lines = sum(len(p) // 70 + 1 for p in text.split("\n"))
        self.text = tk.Text(body, width=72, height=min(lines, 24), wrap="word", relief="flat",
                            borderwidth=0, highlightthickness=0, padx=0, pady=0,
                            background=ttk.Style(self).lookup("TFrame", "background") or self.cget("background"))
        self.text.insert("1.0", text)
        # Read-only but still selectable/copyable (state=disabled would block focus on some Tk builds).
        self.text.bind("<Key>", self._readonly_key)
        self.text.pack(anchor="w", fill="x", pady=(8, 0))

        links = ttk.Frame(body)
        links.pack(fill="x", pady=(10, 0))
        ttk.Button(links, text="Full credits", command=lambda: self.open_url(CREDITS_URL)).pack(side="left")
        ttk.Button(links, text="Project page", command=lambda: self.open_url(REPO_URL)).pack(
            side="left", padx=(6, 0))
        self.close_btn = ttk.Button(links, text="Close", command=self.destroy)
        self.close_btn.pack(side="right")

        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.close_btn.focus_set()

    def get_text(self):
        return self.heading + "\n\n" + self.text.get("1.0", "end-1c")

    @staticmethod
    def _readonly_key(event):
        # Allow copy / select-all and navigation; block anything that edits.
        if event.state & 0x4 and event.keysym.lower() in ("c", "a", "insert"):
            return None
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
                            "Shift_L", "Shift_R", "Control_L", "Control_R", "Escape", "Tab"):
            return None
        return "break"

    @staticmethod
    def open_url(url):
        try:
            webbrowser.open(url)
        except Exception:  # no browser available: nothing else to do
            pass


def run_about_dialog(parent, info=None, auto_close_ms=None):
    """Show the About box modally. auto_close_ms closes it unattended (tests / smoke run)."""
    dlg = AboutDialog(parent, info=info)
    if auto_close_ms is not None:
        dlg.after(auto_close_ms, dlg.destroy)
    try:
        dlg.grab_set()
    except tk.TclError:   # parent not viewable (e.g. withdrawn); the dialog still works
        pass
    parent.wait_window(dlg)
    return dlg
