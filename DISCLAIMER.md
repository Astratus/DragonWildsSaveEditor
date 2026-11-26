# Disclaimer

Please read this before using the Dragonwilds Save Editor.

## Unofficial project

This is an unofficial, fan-made tool. It is **not affiliated with, endorsed by, sponsored by or supported by Jagex Ltd.**
RuneScape, RuneScape: Dragonwilds and Dragonwilds are trademarks of Jagex Ltd. All other trademarks belong to their owners.

Please don't contact Jagex support about problems caused by this tool. Open an issue on this project instead.

## Single-player use only

The tool is meant for **your own characters and worlds, in single-player play.**

Jagex's [RuneScape: Dragonwilds Community Modding Guidelines](https://legal.jagex.com/docs/policies/runescape-dragonwilds-community-modding-guidelines) say:

> "While single-player cheats are fine, using mods to cheat in multiplayer or any shared gameplay is prohibited."

and

> "Mods should never damage or corrupt save data or give unfair advantages in shared spaces."

The guidelines also say Jagex "may take action at our discretion against mods we deem harmful, disruptive or otherwise inappropriate."

So don't use edited characters to gain an advantage in multiplayer or any other shared game, and don't edit other people's saves without their permission.
This project has no multiplayer features and won't add any. You are responsible for following Jagex's rules and terms. They can change at any time, so check the page above yourself.

## Use at your own risk, no warranty

This software is provided **"as is", without warranty of any kind** (see [LICENSE](LICENSE)).

- **Save corruption is possible.** The save format is not documented by Jagex. It was worked out by the community, and parts of it are still unknown (see below). A game update can change the format at any time.
- The editor makes backups before every write (see [docs/SCOPE.md](docs/SCOPE.md#safety-model)). Even so, **keep your own copy** of the whole save folder before you edit anything:
  `%LOCALAPPDATA%\RSDragonwilds\Saved`
- **Steam Cloud can overwrite your edits.** If the game syncs an older cloud copy, your changes are lost, or an edited file is replaced. If edits keep reverting, turn off Steam Cloud for the game while you edit.
- Always close the game completely before editing. The editor refuses to save while the game is running, but don't rely on that alone.

The authors and contributors are not liable for lost progress, corrupted saves or any other damage.

## Unknown save fields

Some fields in the character save are not understood. The editor **never changes** them:

- **`Backup`**, the number at the very end of the character file, changes on every save. It is *not* a CRC32 or FNV hash of the text (those were tested), and no public documentation of it exists. It is left untouched and undocumented. Edited saves have loaded so far, which suggests the game doesn't check it strictly, but that is not guaranteed.
- **`HistoricCorruption`** is undocumented. It appeared in newer save versions and is probably a corruption counter. Left untouched.
- `SaveCount` and the character GUID are also left untouched.

More open questions are listed in [docs/SCOPE.md](docs/SCOPE.md#known-unknowns).

## The World tab is experimental

World saves (`.sav`) use a binary format. The World tab can read them and make a few small structural edits (removing a defeated boss, changing or removing a progress tag).

**None of the World tab's edits have been tested in game.** The editor checks that the written file is structurally valid and reads back correctly. It does **not** know what the game will do with the change. Treat every World edit as an experiment on a world you can afford to lose, and keep a backup.

## No game files are modified

The editor only reads and writes **save files** (character `.json` and world `.sav` files) and its own backups. It does not touch the game's installation, executables, `.pak` files or memory, and it doesn't inject or hook anything.

## Game data

The bundled item, skill, unlock and quest data (`dragonwilds_save_editor/data/`) was extracted from the game files by the community, not by Jagex, and was cross-checked against several sources. It may be incomplete or out of date after a game update.
All of that data belongs to Jagex. See [CREDITS.md](CREDITS.md) for the projects and people it came from.
