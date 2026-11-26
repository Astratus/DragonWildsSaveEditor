# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

Every 0.x release is published as a GitHub **pre-release**. In-game testing is limited, so always back up your saves before you use the editor.

## [0.1.0] - 2026-11-26

**Pre-release.** First public build. In-game testing has been limited, so back up your whole `%LOCALAPPDATA%\RSDragonwilds\Saved` folder before you save any edit.

**100% offline:** the editor makes no network connections at all (no downloads, update checks, telemetry, accounts or sign-in). The About box's two link buttons open your web browser only when you click them.

### Added

- Windows GUI editor (`DragonwildsSaveEditor.exe`) for RuneScape: Dragonwilds character saves (save Version 86, patch 1.0.1 and later), with Character, Skills, Inventory, Add Items, Unlocks, Main Quest, World, Map and Backups tabs.
- **Main Quest** tab: revert the main questline to an earlier, verified checkpoint (24 checkpoints from Dragon Slayer to Regicide; linear and revert-only). Reverting also clears the one-time intro cutscenes of regions that come later in the story (Fellhollow, Dowdun Reach, Umbral Sands, Scorned Wilderness) so they play again. Afterwards the tab can offer (default No) to hide map areas whose gating quest is now not started.
- **Map** tab: show or hide revealed map regions (fog of war), and view or edit found Sanguine Urns and kebbit burrows.
- **World toolbar and focused world:** a second toolbar row picks one world save (by default the newest), which the World and Backups tabs use, with its own Open, Save, Revert and Open folder actions. World saves first snapshot all character and world saves and back up the `.sav`.
- **World backups:** the Backups tab switches between the character save and the focused world, listing the world's editor and game backups and its copies in the full snapshots; restoring backs up the current file first.
- **Lodestones (experimental):** list a world's fast-travel lodestones, and activate or remove the four fixed world lodestones. Player-built lodestones are read-only.
- **World-save reader** (`dragonwilds_save_editor/spud.py`): an independent clean-room implementation of the SPUD world-save container, with a read-only command line, `python -m dragonwilds_save_editor.spud`.
- **Bundled item catalog:** 1,605 items and the unlock names (including 197 AI entries), our own compilation generated from an installed copy of the game (version 1.0.2.2) by the editor's own read-only reader for the game's IoStore containers (`dragonwilds_save_editor/gamedata/`, standard library only). Every entry's `source` is the game package path. There is no first-run download.
- **Help > Update item catalog** (optional): rebuilds the catalog from the player's own installed game, found automatically (Steam libraries, the game's log, common folders) or picked with a folder dialog. The game's files are only read; the build checks itself (share of fully decoded assets, plausible counts, valid IDs) and is only used if the check passes. **Help > Reset to bundled catalog** goes back to the included one. `dwsave catalog build [--game-dir] | detect | status | reset | verify | compare` do the same from the command line.
- Map and lodestone data verified against the installed game's world level (`python -m dragonwilds_save_editor.gamedata.world`): all 31 fog-bit regions, 21 Sanguine Urns, 19 kebbit burrows and the 4 fixed lodestones agree; the Umbral Sands lodestone location now uses the game's exact values (it was rounded by up to 0.008 units).
- Unlock names come from the same catalog, including skill-perk names for perk entries in the spells "new" list.
- An installable Python package (`dragonwilds_save_editor`): `python -m dragonwilds_save_editor` starts the GUI, and the `dwsave` command (`python -m dragonwilds_save_editor.save`) edits character saves from the command line (standard library only).
- Skill, XP, quest, map and lodestone data in `dragonwilds_save_editor/data/`.
- An automatic backup before every write, a check for the running game, and formatting that matches the game's own output.
- Documentation: a user-focused README, `docs/save-format.md`, `docs/development.md`, the research notes in `docs/research/`, a licensing review, and contributing, security and code-of-conduct guides with issue and pull request templates.
- **Help > About Dragonwilds Save Editor:** version, MIT licence, the Jagex Fan Content Policy notice, a short credits summary with links, and which item catalog is in use (bundled, or updated on a given date).
- Release build: a portable zip (`DragonwildsSaveEditor-<version>-win64.zip`) with SHA256 checksums.

### Known limitations

- The exe is not code-signed, so Windows SmartScreen and some antivirus products may warn about it. See the release notes for how to verify the download.
- Steam Cloud can overwrite local edits. Don't save while the game is running.

[0.1.0]: https://github.com/Astratus/DragonWildsSaveEditor/releases/tag/v0.1.0
