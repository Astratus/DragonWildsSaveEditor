# Dragonwilds Save Editor

[![CI](https://github.com/Astratus/DragonWildsSaveEditor/actions/workflows/ci.yml/badge.svg)](https://github.com/Astratus/DragonWildsSaveEditor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Network: none](https://img.shields.io/badge/network-none-brightgreen.svg)](#offline-and-private)

A free, unofficial Windows save editor for **RuneScape: Dragonwilds**, for single-player use. **100% offline:** it makes no network connections at all, and needs no account or online service.

Edit your inventory, skills and unlocks, or step the main questline back to an earlier checkpoint to replay a fight. The editor backs up your saves before every write and refuses to save while the game is running.

> **Unofficial.** Not affiliated with or endorsed by Jagex. Single-player only. Use at your own risk, and read the [disclaimer](DISCLAIMER.md) first.

<!-- TODO: add a real screenshot at docs/images/main-window.png, then uncomment:
![The editor's Inventory tab](docs/images/main-window.png)
-->

## Offline and private

- **No network connections at all:** no downloads, no update checks, no telemetry or analytics, no accounts or sign-in.
- **Works fully offline**, from the first start. Everything stays on your PC.
- **The item catalog is bundled**, and you can rebuild it from your own installed copy of the game (**Help > Update item catalog**), which is only read, never changed.
- **Your saves are only read and written locally**, with a backup before every write.

The editor's code imports no networking module, and a unit test checks that. The only links are the two buttons in **Help > About** ("Full credits", "Project page"): they open your web browser, and only when you click them. Details in [SECURITY.md](SECURITY.md).

## Features

| Tab | What it does |
|---|---|
| **Character** | A read-only summary of your character. |
| **Skills** | Set the XP or level (1-99) of all 12 skills. |
| **Inventory** | View your hotbar, bag, rune, ammo and quest pouches, personal storage and equipped gear. Change stack sizes, repair gear and remove items. |
| **Add Items** | Search a catalog of 1,600+ items and add them. Items go into the right inventory section, and counts stay within the normal stack size. The catalog is included, generated from the game's own files (see [The item catalog](#the-item-catalog)). |
| **Unlocks** | Lock or unlock recipes, building pieces and spells. |
| **Main Quest** | Revert the main questline to an earlier, verified checkpoint, for example "ready to challenge Imaru". It only goes back, never forward. See [how it works](docs/SCOPE.md#the-main-questline-linear-revert-only). |
| **World** *(experimental)* | Look inside the world picked in the toolbar's **World** row: defeated bosses, progress tags, cached guest characters, lodestones and an object search. A few small edits are possible, including activating or removing the four fixed lodestones, but **none have been tested in game**. |
| **Map** | Show or hide map regions (fog of war), and view or edit the Sanguine Urns and kebbit burrows you have found. The fog is cosmetic: travel is gated by quest progress, not the map. |
| **Backups** | Create, restore, delete and prune backups of the open character or the focused world. |

The toolbar has two rows: **Character** (open, save, revert the character save) and **World** (pick the world save that the World tab and world backups use, and save or revert it). Character and world saves are saved separately.

## Safety first

- **Close the game completely** before you edit, including any launcher or background process. The game keeps your save in memory and will overwrite your changes. The editor refuses to save while it detects the game, but don't rely on that alone.
- **Keep your own backup.** Copy the whole `%LOCALAPPDATA%\RSDragonwilds\Saved` folder somewhere safe before your first edit (paste that path into the Explorer address bar).
- **The editor backs up too.** Every save writes a timestamped copy of the file next to it, and quest or world edits first snapshot *all* your character and world saves. See [Restoring a backup](#restoring-a-backup).
- **Steam Cloud can undo your edits.** If your changes disappear when you start the game, Steam restored an older cloud copy. In Steam, right-click the game, choose **Properties > General** and turn off **Steam Cloud**, then edit again. You can turn it back on afterwards.
- **In-game testing is still limited.** Treat quest reverts and all World edits as experimental. The current test status is in [docs/SCOPE.md](docs/SCOPE.md#tested-status).

## Download and install

1. Download `DragonwildsSaveEditor-<version>-win64.zip` from the [latest release](https://github.com/Astratus/DragonWildsSaveEditor/releases/latest).
2. Extract the whole zip to a folder of your choice. Keep the `DragonwildsSaveEditor` folder together: the exe needs the `_internal` folder next to it.
3. Run `DragonwildsSaveEditor.exe`. Nothing is installed, and you don't need Python.

The exe is not code-signed, so Windows SmartScreen may say "Windows protected your PC". Choose **More info > Run anyway**, but only for a file you downloaded from this project's Releases page. To check the download, compare its hash with `SHA256SUMS.txt` on the release page:

```powershell
Get-FileHash .\DragonwildsSaveEditor-<version>-win64.zip
```

Prefer not to run an unsigned exe? You can [run it from source](#building-from-source) instead.

## Quick start

1. Close the game and back up your `Saved` folder (see [Safety first](#safety-first)).
2. Open the editor. It loads your most recent character and newest world automatically. Use **Open...** to pick another one. Everything it needs is included: there is no first-run download.
3. Make your changes. Nothing is written until you save.
4. Press **Save** (Ctrl+S). A backup is made first.
5. Start the game and check the result.

### The item catalog

The item catalog (item names, stack sizes, inventory tabs, unlock names) is included with the editor and works offline from the first start. It is our own compilation, generated from an installed copy of the game (version 1.0.2.2); **Help > About** shows which catalog is in use.

**Help > Update item catalog** is optional: it rebuilds the catalog **from your own installed game**, for example after a game patch that the included catalog doesn't cover yet. The editor finds the game automatically (Steam libraries, the game's own log, common folders) or lets you pick its folder. It only reads the game's files, works while the game is running, makes no network connection, and checks the result before using it: if the check fails, your current catalog is kept. The result is stored in `%LOCALAPPDATA%\DragonwildsSaveEditor\catalog`; **Help > Reset to bundled catalog** goes back to the included one. From the command line: `dwsave catalog build [--game-dir FOLDER]`.

### Where are my saves?

| What | Location |
|---|---|
| Characters | `%LOCALAPPDATA%\RSDragonwilds\Saved\SaveCharacters\<CharacterName>.json` |
| Worlds | `%LOCALAPPDATA%\RSDragonwilds\Saved\SaveGames\<WorldName>.sav` |
| Editor snapshots, logs and an updated item catalog (if you made one) | `%LOCALAPPDATA%\DragonwildsSaveEditor\` |

`%LOCALAPPDATA%` is usually `C:\Users\<you>\AppData\Local`.

### Restoring a backup

**In the app:** open the **Backups** tab, select a backup and click **Restore selected**. Your current file is backed up first, so a restore can be undone too.

**By hand**, with the game closed:

- **Character backups** sit next to your save, named like `MyCharacter.json.20260101-120000.pyedit.bak`. Copy one over `MyCharacter.json`, dropping the `.20260101-120000.pyedit.bak` part of the name.
- **Full snapshots**, made before every Main Quest or World save, are in `%LOCALAPPDATA%\DragonwildsSaveEditor\backups\`. Each `pre-quest_<date>` or `pre-world-edit_<date>` folder holds a `SaveCharacters` and a `SaveGames` folder. Copy both back into `%LOCALAPPDATA%\RSDragonwilds\Saved\`, replacing the existing files.
- Files ending in `.backup` or `.verbackup` are the game's own rotating copies. The editor never deletes them, but they are not a reliable backup.

## FAQ

**Is this cheating? Can I get banned?**
Jagex's [Community Modding Guidelines](https://legal.jagex.com/docs/policies/runescape-dragonwilds-community-modding-guidelines) say: *"While single-player cheats are fine, using mods to cheat in multiplayer or any shared gameplay is prohibited."* We don't know of any bans for single-player save editing, but we can't promise anything. Keep edited characters out of multiplayer and shared games. Steam lists no anti-cheat for the game, only an Epic Online Services account requirement. Rules can change, so check the guidelines yourself.

**Will my character be flagged as "modded"?**
We found no "modded" flag in the character save, and the editor doesn't add one. It writes the file in the game's exact format and leaves fields it doesn't understand (such as the trailing `Backup` value) untouched. Edited saves have loaded fine so far. See [Unknown save fields](DISCLAIMER.md#unknown-save-fields).

**Will I lose achievements?**
Player reports on the Steam Community forums say achievements are disabled by choosing Custom or Creative *world* settings in game, not by editing a character. We haven't seen a report of character edits disabling achievements, but this isn't officially documented.

**Can it corrupt my save?**
It's possible. The format isn't officially documented. The editor backs up, verifies every write and leaves unknown fields alone, but keep your own backup too.

**Can I jump ahead in a quest?**
No, by design. You can only revert to verified checkpoints, so the game plays every later step, reward and world event for real. [Here's why.](docs/SCOPE.md#the-main-questline-linear-revert-only)

**Does it connect to the internet?**
No. It makes no network connections at all, including **Help > Update item catalog**, which reads your installed game. See [Offline and private](#offline-and-private).

**Does it work in multiplayer or on other people's worlds?**
It isn't meant for that and has no multiplayer features.

**My edits vanished when I started the game.**
That is almost always Steam Cloud. See [Safety first](#safety-first).

## Building from source

You need Windows and [Python](https://www.python.org/downloads/) 3.10 or newer, 3.12 recommended (tkinter is included in the Windows installer). The editor uses only the standard library. After cloning, you can also double-click `scripts\run-from-source.bat` to start it without a console window.

```powershell
git clone https://github.com/Astratus/DragonWildsSaveEditor.git
cd DragonWildsSaveEditor
python -m dragonwilds_save_editor            # start the GUI
python -m unittest discover tests            # run the tests
```

Setup, the command-line tool, the project layout and building the Windows zip are covered in [docs/development.md](docs/development.md). Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

- [docs/SCOPE.md](docs/SCOPE.md): what the editor does and doesn't do, checkpoint confidence levels, the safety model, known unknowns and tested status
- [docs/save-format.md](docs/save-format.md): the character save format
- [docs/development.md](docs/development.md): developer setup, tests and project layout
- [docs/RELEASING.md](docs/RELEASING.md): how releases are built and published
- [docs/LICENSING.md](docs/LICENSING.md): licensing review of the sources this project builds on
- [docs/research/](docs/research/README.md): the research notes behind the quest checkpoints, the map, lodestones, the item catalog and the world-save reader
- [CHANGELOG.md](CHANGELOG.md)

## How this was made

This editor was built with an AI coding assistant (Claude, by Anthropic), and most of the code was written by the AI. The maintainer directed the work, made the design decisions, tested the editor on their own saves in game and sent it back when it got things wrong. The project's main rules also came from the maintainer: back up before every change, keep the quest line linear and revert-only, make no network connections and credit every source accurately.

You don't have to take that on trust. Everything here can be checked:

- **The code is all public**, including the [research notes](docs/research/README.md) behind each feature.
- **Automated tests run on every push** ([CI](.github/workflows/ci.yml)), including a check that no network code gets added.
- **The editor refuses to save while the game is running**, and it backs up before every change.
- **Every source is credited** in [CREDITS.md](CREDITS.md). The world-save reader is a [clean-room implementation](docs/research/spud_cleanroom.md), and the item catalog is built from the game's own files.

> *"AI is like magic. Magic can take jobs, hack your computer, and demand sacrifice. But a good mage knows the only thing that requires sacrifice is greed."*
> That is why this editor is free, offline and open source.

Found a bug, or something the AI got wrong? Please [open an issue](https://github.com/Astratus/DragonWildsSaveEditor/issues).

## Credits, licence and disclaimer

This editor builds on the work of the Dragonwilds community. See [CREDITS.md](CREDITS.md).

The code is released under the [MIT licence](LICENSE). The licence covers this project's own code only, not Jagex game data or third-party data; see [docs/LICENSING.md](docs/LICENSING.md).

RuneScape, RuneScape: Dragonwilds and Jagex are trademarks of Jagex Limited. Please read the [disclaimer](DISCLAIMER.md) before use.

*Created using intellectual property belonging to Jagex Limited under the terms of Jagex's Fan Content Policy. This content is not endorsed by or affiliated with Jagex.*
