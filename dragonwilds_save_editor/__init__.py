"""Dragonwilds Save Editor: an unofficial character/world save editor for RuneScape: Dragonwilds.

Modules
-------
save       character save (.json) reader/writer and the ``dwsave`` command line tool
catalog    item and unlock-name catalogs (bundled; optionally rebuilt from the game's data)
questline  linear main-questline checkpoints
map        fog of war, Sanguine Urns and kebbit burrows (character save)
spud       world save (.sav, SPUD container) reader/editor
lodestones fast-travel lodestones in a world save
paths      bundled-resource and per-user folder locations
gui        the Tkinter desktop app (``python -m dragonwilds_save_editor``)
"""

__version__ = "0.1.0"
