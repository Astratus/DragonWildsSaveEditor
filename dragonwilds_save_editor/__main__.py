r"""Launch the GUI: ``python -m dragonwilds_save_editor [save.json]``.

Also the entry point of the Windows exe and of the ``dragonwilds-save-editor`` command.
Startup errors are shown in a message box (there is no console under pythonw / the exe),
or written to %LOCALAPPDATA%\DragonwildsSaveEditor\logs\dw_gui_error.log if Tk itself
cannot start.

Absolute imports on purpose: PyInstaller runs this file as a top-level script.
"""

import os
import sys
import traceback


def _show_error(text):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Dragonwilds Save Editor - startup failed", text, parent=r)
        r.destroy()
    except Exception:
        try:
            from dragonwilds_save_editor import paths
            log = os.path.join(paths.user_data_dir("logs"), "dw_gui_error.log")
        except Exception:
            import tempfile
            log = os.path.join(tempfile.gettempdir(), "dw_gui_error.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write(text)


def main(argv=None):
    """GUI entry point; returns a process exit code."""
    argv = sys.argv[1:] if argv is None else argv
    try:
        from dragonwilds_save_editor.gui.app import main as run_app
        run_app(argv[0] if argv else None)
    except Exception:
        _show_error(traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
