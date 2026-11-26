# Development

This page is for people who want to run the editor from source, work on the code or add quest checkpoints.
For how to contribute (bug reports, pull requests, evidence rules), see [CONTRIBUTING.md](../CONTRIBUTING.md). For releases, see [RELEASING.md](RELEASING.md).

## Setup

You need Windows and Python 3.10 or newer; CI and releases use 3.12. The editor uses only the standard library (including tkinter, which the python.org Windows installer includes), so there are no runtime dependencies to install.

```powershell
winget install Python.Python.3.12      # if you don't have Python yet
git clone https://github.com/Astratus/DragonWildsSaveEditor.git
cd DragonWildsSaveEditor
```

```powershell
python -m dragonwilds_save_editor      # start the GUI
```

`scripts\run-from-source.bat` does the same without a console window; it prefers the repository's `.venv` if there is one.

An editable install is optional. It adds two commands, `dragonwilds-save-editor` (the GUI) and `dwsave` (the [command-line tool](#command-line-tool)), and lets you run the package from any folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

Work on **copies** of saves, never on your live `%LOCALAPPDATA%\RSDragonwilds\Saved` files. To start the GUI without it finding your real saves, point `LOCALAPPDATA` at an empty folder for that session:

```powershell
$env:LOCALAPPDATA = "$env:TEMP\dw-empty"; mkdir $env:LOCALAPPDATA -Force | Out-Null
python -m dragonwilds_save_editor
```

The item catalog is bundled (see [Item catalog](#item-catalog)), so with an empty `LOCALAPPDATA` the GUI starts with the full catalog. The editor makes no network connections at all (`tests/test_gamedata.py` `NoNetworkTests` fails if a module imports a networking library).

## Tests

```powershell
python -m unittest discover tests
```

CI runs the same suite on every push and pull request (Windows with Python 3.12, Ubuntu with 3.10 and 3.12; GUI tests skip on Ubuntu). It also verifies the bundled catalog (`python packaging/build_catalog.py --verify`: valid JSON, expected shape, counts and file hashes; no game install needed), then installs the package and checks the `dwsave` entry point and that the installed package loads the bundled catalog. All tests must pass before a change is merged.

- **Character fixtures.** `tests/fixtures/sample_character.json` (save Version 86) and `sample_character_v83.json` (Version 83) are **synthetic**. `tests/make_fixture.py` built them from real saves: it keeps the structure and progress, sets the name to "SampleHero", and generates new random character, world and item GUIDs, neutral playtime values, a neutral `Customization` and a new `Backup` value. The main fixture sits at Black Knight's Fortress step 7, which the questline tests rely on.
- **Item catalog fixture.** `tests/fixtures/catalog/` holds a small subset of the catalog (the items and unlock names the fixtures and tests use, cut from a real catalog by `tests/make_catalog_fixture.py`). `tests/_helpers.py` points `LOCALAPPDATA` at a temporary folder for the whole test run and copies the fixture into its `DragonwildsSaveEditor\catalog`, where it acts as a user-built catalog and takes precedence over the bundled one. So no test reads or writes your real `%LOCALAPPDATA%` (catalog, snapshots or game saves). Tests that need the bundled catalog point the user folder at an empty one with `catalog.set_user_data_dir(...)`; tests of a damaged install also hide the bundled one with `catalog.set_bundled_dir(...)`. `tests/test_catalog.py` tests the derivation rules and the self-check, builds from a tiny fake game install, checks the load order, and checks that the bundled catalog verifies, loads (about 1,600 items, skill perks present), holds only package paths and re-serialises byte for byte.
- **Game-data fixtures.** `tests/gamedata_fixture.py` writes tiny synthetic IoStore containers (`.utoc`/`.ucas`), zen packages, a script-object table and a pak with `DefaultGame.ini` into a temporary folder: a fake installation with a string table, three ItemData items, one item of a class without a schema (exercising the partial-decode fallback) and a skill. `tests/test_gamedata.py` uses it for the container, package, property, schema-decoding, derivation and install-detection tests. No real game data is in the repository.
- **World tests** use synthetic in-memory worlds. The tests against a real world skip unless the `DW_TEST_WORLD` environment variable points at a world `.sav`; they then work on a temporary copy, check that the original is untouched, and check round trips and edit invariants rather than world-specific counts. Tests that need particular content (a defeated boss, a progress tag, a registered lodestone) skip themselves when that content is missing. Real-world tests therefore skip on CI.
- **Environment variables:**

  | Variable | Effect |
  |---|---|
  | `DW_TEST_WORLD` | Path to a world `.sav`. Enables the real-world tests, which copy it to a temporary folder first. |
  | `DW_TEST_GAME_DIR` | A RuneScape: Dragonwilds installation folder. Enables the real-install tests (read only): the build from it passes the self-check, reproduces the bundled catalog byte for byte when the game version matches, and the map and lodestone data verify against its world level. |
  | `DW_SMOKE_TEST=1` | Makes the GUI close itself 0.5 s after it starts, so it can be launched headlessly. |
- **Questline test.** `tests/test_questline.py` applies every reachable checkpoint to a copy of the fixture, saves it, reloads it and checks that the save lands exactly on that checkpoint with a byte-exact round trip.

Never commit real saves, even as fixtures. If you need a new fixture, generate it with `tests/make_fixture.py` and check the result for names and GUIDs before committing.

## Command-line tool

The character-save library also works as a command-line tool: `python -m dragonwilds_save_editor.save`, or `dwsave` after an editable install. Always quote the save path, because `#` is special in some shells, and use it on a copy first.

```powershell
python -m dragonwilds_save_editor.save "MyCharacter#1.json" info
python -m dragonwilds_save_editor.save "MyCharacter#1.json" inv --section all
python -m dragonwilds_save_editor.save "MyCharacter#1.json" search rune --category Resource
python -m dragonwilds_save_editor.save "MyCharacter#1.json" add "Nature Rune" --count 500
python -m dragonwilds_save_editor.save "MyCharacter#1.json" set-count Inventory 40 9999
python -m dragonwilds_save_editor.save "MyCharacter#1.json" repair
python -m dragonwilds_save_editor.save "MyCharacter#1.json" remove Inventory 73
python -m dragonwilds_save_editor.save "MyCharacter#1.json" skills
python -m dragonwilds_save_editor.save "MyCharacter#1.json" set-skill Mining --level 60
python -m dragonwilds_save_editor.save "MyCharacter#1.json" --dry-run set-skill Magic --xp 200000
python -m dragonwilds_save_editor.save "MyCharacter#1.json" selftest
```

- `--dry-run` shows what would change and writes nothing.
- `--force` writes even if the game seems to be running. Avoid it.
- `--allow-overstack` (on `add` and `set-count`) allows counts above the item's maximum stack.
- `selftest` checks that loading and re-writing the file reproduces it byte for byte. Run it on a copy after any change to the writer.

`search`, `add`, `set-count` and `repair` need the item catalog, which is bundled; if it can't be loaded (damaged install), the other commands still work and show unknown items as `?unknown?`.

### Item catalog

The item and unlock-name catalog ships in `dragonwilds_save_editor/data/catalog/` (`items.json`, `unlock_names.json`, `build_info.json`). It is generated from an **installed copy of the game** by the `gamedata` package (a read-only, standard-library reader for the game's IoStore containers) and the classification rules in `catalog.py`. How it works: [research/catalog_build.md](research/catalog_build.md); format sources: [research/gamedata_provenance.md](research/gamedata_provenance.md).

**Load order.** `catalog.load_catalog()` uses a user-built catalog in `%LOCALAPPDATA%\DragonwildsSaveEditor\catalog\` if one exists and is compatible (same `format`, and a `generator_version` at least the bundled one's), else the bundled catalog. `catalog.active_status()` says which (`origin`: `user` or `bundled`).

**Regenerating the bundled catalog.** Use `packaging/build_catalog.py` with the game's installation folder (only read; the game may be running). Output is deterministic: entries and keys are sorted, one entry per line, UTF-8 without BOM, LF line endings (the folder is `-text` in `.gitattributes`, so git keeps the bytes). Rebuilding from the same game version gives byte-identical files, and `build_info.json` keeps its date unless the data changed. The build runs the same self-check as the user-side update, against the committed catalog, and refuses to write if it fails.

```powershell
python packaging\build_catalog.py --game-dir "<install folder>"           # regenerate (omit --game-dir to detect it)
python packaging\build_catalog.py --check --game-dir "<install folder>"   # compare a fresh build with the committed files
python packaging\build_catalog.py --verify                                # no game needed: JSON, shape, counts, hashes (CI runs this)
```

`build_info.json` records `source` ("installed game"), `game_version` (read from the pak's `Config/DefaultGame.ini`), `built_at` (date), `generator` / `generator_version`, decode statistics (`asset_files`, `asset_bytes`, `fully_decoded`, `partly_decoded`), the counts and each file's size and SHA256. It never holds a local path, and every entry's `source` is a game package path such as `/Game/Gameplay/Items/...`. Bump `catalog.GENERATOR_VERSION` when the reader or a derivation rule changes the output, so older user-built catalogs stop overriding the new bundled one.

**After a game patch** (see also [RELEASING.md](RELEASING.md#after-a-game-patch-regenerate-the-item-catalog)):

1. Build into a scratch folder and look at the self-check: `python -m dragonwilds_save_editor.catalog build --game-dir "<install>" --out build\cat-new`. A low "fully decoded" share means a native class's layout changed.
2. If so, re-infer the schemas (development tool, not used at runtime; it rewrites `data/gamedata/schemas.json`): `python -m dragonwilds_save_editor.gamedata.infer --game-dir "<install>"` (`--only CLASS` for one class, `--retry-failed` for classes without a schema, `--seconds` for the per-class time budget). Review the diff: indices that moved in a class used by `gamedata/derive.py` (the field positions at its top) need their positions updated by hand from the decoded values.
3. Compare the new build with the committed catalog: `python -m dragonwilds_save_editor.catalog compare --new build\cat-new` (field-by-field agreement, new and removed IDs).
4. Regenerate with `packaging\build_catalog.py`, run the tests (also with `DW_TEST_GAME_DIR`), and verify the map and lodestone data: `python -m dragonwilds_save_editor.gamedata.world --game-dir "<install>"`.

**User-side update** (the optional GUI action **Help > Update item catalog**, and the CLI):

```powershell
dwsave catalog status                         # which catalog is in use, and its build info
dwsave catalog detect                         # where the game is installed, and how it was found
dwsave catalog build [--game-dir FOLDER]      # rebuild from the installed game into the user data folder
dwsave catalog reset                          # delete the user-built catalog: back to the bundled one
dwsave catalog verify [FOLDER]                # check a catalog folder (default: the bundled one)
dwsave catalog compare [--new F] [--old F]    # field-by-field comparison of two catalogs
```

- Install detection (`gamedata/install.py`): Steam libraries (`libraryfolders.vdf`, `steamapps/common/*Dragonwilds*`), the absolute paths the game records in its own logs (`%LOCALAPPDATA%\RSDragonwilds\Saved\Logs`), then common folders on fixed drives. The GUI falls back to a folder picker. The folder is never stored.
- The game's files are opened read-only (shared) and read with seeks; nothing in the game folder is written, renamed or locked. The game executable and the running game are never read; no `.usmap` mapping file is used.
- The build checks itself (`catalog.self_check`): at least 80% of the catalog's game assets fully decoded by their class schema, at most 1% unreadable, a unique 22-character PersistenceID for every item and unlock, plausible counts (minimums per section; against the catalog in use, at most 3x its size and at least 90% of its IDs found again). If the check fails, nothing is written and the current catalog stays in use (`SelfCheckError`).
- The GUI never opens the update dialog on its own. **Help > Update item catalog** shows it (detected game folder, "Choose game folder...", progress bar, Cancel); **Help > Reset to bundled catalog** removes the user-built catalog.

### World saves

The world-save reader has a read-only command line (`info`, `bosses`, `tags`, `objects [class substring] [--props]`, `selftest`), and the lodestone module lists a world's lodestones:

```powershell
python -m dragonwilds_save_editor.spud "MyWorld.sav" info
python -m dragonwilds_save_editor.spud "MyWorld.sav" selftest
python -m dragonwilds_save_editor.lodestones "MyWorld.sav"          # table; add --json for JSON
```

World edits (removing a defeated boss, changing a progress tag, activating a fixed lodestone) are made through the GUI, in memory on a `spud.WorldFile`, and written by `WorldFile.save()`: it refuses while the game runs and if the file changed on disk, snapshots all character and world saves, backs up the `.sav`, writes a temporary file, re-parses it and then replaces the original.

## Project layout

```text
dragonwilds_save_editor/     the application package
  __init__.py                package docstring and `__version__` (the single source of the version)
  __main__.py                `python -m dragonwilds_save_editor` starts the GUI
  save.py                    character-save library and CLI (load, edit, byte-exact write, backups)
  catalog.py                 the item / unlock-name catalog: derivation rules, self-check, build, loading
  gamedata/                  read-only reader for the installed game (IoStore, zen packages, unversioned
                             properties, string tables), catalog derivation, install detection, the
                             schema-inference dev tool (infer.py) and the map/lodestone verifier (world.py)
  spud.py                    clean-room world-save (.sav, SPUD) reader and experimental writer
  lodestones.py              world lodestones: list; activate/remove the four fixed ones (experimental)
  map.py                     fog of war, Sanguine Urns and kebbit burrows in the character save
  questline.py               the linear, revert-only main-quest checkpoint engine
  paths.py                   bundled-resource, user-data and game-save paths
  gui/                       tkinter GUI, one module per tab (incl. map_tab.py), shared state
                             (context.py: the open character and the focused world) and
                             catalog_setup.py (the optional Update item catalog dialog)
  data/                      skills, XP table, quest checkpoints and research data, map points, lodestones,
                             catalog/ (the bundled item catalog) and gamedata/schemas.json (the inferred
                             byte layouts of the game's native classes)
tests/                       unittest suite and synthetic fixtures
packaging/                   build.ps1, PyInstaller spec, release-notes helper, build_catalog.py
scripts/                     run-from-source.bat (starts the GUI from a checkout)
docs/                        documentation; docs/research/ holds the research notes
pyproject.toml               package metadata and the `dragonwilds-save-editor` / `dwsave` commands
```

### Paths at runtime

- **Bundled read-only data** is located relative to the package, and also works inside the PyInstaller build.
- **User data** (full snapshots in `backups\`, the startup error log in `logs\`, and, only after Update item catalog, a user-built item catalog in `catalog\`) goes to `%LOCALAPPDATA%\DragonwildsSaveEditor\`, created on demand. Nothing is written next to the program.
- **Game saves** are read from `%LOCALAPPDATA%\RSDragonwilds\Saved`. Per-file `.pyedit.bak` backups are written next to the save they protect.

### Design rules

- **Byte-exact round trip.** The character writer reproduces the game's formatting exactly (see [save-format.md](save-format.md#file-formatting)). Any change to the writer must keep `selftest` and the round-trip tests passing.
- **Unknown fields are never changed:** `Backup`, `HistoricCorruption`, `SaveCount`, `meta_data.char_guid`.
- **Every write is backed up and verified.** Write to a temporary file, read it back, check it, then swap it into place. Refuse to write while the game is running.
- **Stack limits.** Counts are capped at the item's `max_stack` unless the user explicitly overrides it.
- **No forward quest edits, no arbitrary quest steps, no world switches or events.** See [SCOPE.md](SCOPE.md#what-it-deliberately-does-not-do).

## Quest checkpoints

The main questline (Dragon Slayer, Withering Heights, Black Knight's Fortress, Icthlarin's Little Helper, Regicide) is modelled as **one linear line of checkpoints**, stored in `main_questline.json` in the data folder. The line currently has 24 checkpoints; tutorial quests are deliberately excluded. The user-facing explanation is in [SCOPE.md](SCOPE.md#the-main-questline-linear-revert-only).

### What applying a checkpoint does

1. It checks that every earlier main quest is complete, and leaves those records alone.
2. It replaces that quest's record with the checkpoint's exact values (state, objective, ints, bools).
3. It resets every later main quest, and its hidden helper records, to the game's not-started form: `QuestState 0`, `QuestObjective "None"`, empty ints and bools.
4. It sets quest markers and `QuestTrackedMain`, adds back any items the step needs, and removes `ItemsPickedUp` entries where the game must see a pickup again.
5. It removes the checkpoint's `hooks_remove` IDs from `Progress.PlayerHooksTriggered`, so the one-time intro cutscenes of regions that come later in the story (Fellhollow, Dowdun Reach, Umbral Sands, Scorned Wilderness) play again. Absent IDs are a no-op. Only high-confidence region-intro hooks belong there, never tutorial, repeatable or corruption hooks (`hooks_rule` in the JSON; evidence in [research/player_hooks.md](research/player_hooks.md)).

Checkpoints never change the map. After a revert, the GUI may offer (default No) to hide map areas whose gating quest is now not started, along with their Sanguine Urns and kebbit burrows.

Before saving a quest change, the GUI snapshots **all** character and world saves, because part of the quest state lives in the world files, which the questline engine never modifies.

Example: the Withering Heights "ready to challenge Imaru" checkpoint needs no world edit. Imaru's lair door checks for the three Curse Fragments in the inventory, so the checkpoint adds them; and the quest is credited when Imaru's Head is picked up, so the checkpoint removes the head from `ItemsPickedUp`.

### Evidence and confidence ratings

Checkpoints are derived from the datamined quest flows (RSDWArchive, build 1.0.2.0) and cross-checked against real saves and the official wiki. A checkpoint is added only when **every** value in it is traced to a write in the flows.

Each checkpoint has a `confidence` rating, assigned by the `rating_rule` stored in the JSON:

| Rating | Rule | Behaviour |
|---|---|---|
| very high | Every quest-record value is traced to a flow write; continuation gates and world needs are traced or confirmed on the wiki; nothing conflicts with real saves. A remaining inference that is only an extra harmless cleanup (such as removing a picked-up record) does not lower the rating. | Applies after one confirmation. |
| high | Exactly one untraced item, which is safe either way. | Must have an `inference` field. The GUI shows it in a second confirmation, and the engine refuses the checkpoint unless the caller passes `acknowledged=True`. |
| med / low | Too much is unknown. | Disabled. |

`min_confidence` in the JSON sets the lowest enabled rating (currently `"high"`). The current line has 17 very high, 4 high and 3 medium checkpoints.

Rules for changing checkpoints:

- Keep the line **linear and revert-only**. Forward jumps, arbitrary step editing and switch or event editing will not be accepted.
- Record your reasoning in `evidence` and anything not traced in `inference`.
- Don't raise a rating unless every record-level value is traced or confirmed.
- Make sure the checkpoint doesn't conflict with real saves, ideally one sitting at that exact step.
- Add or update a test so the checkpoint is applied to a copy and lands exactly.

The research behind the current checkpoints is indexed in [research/README.md](research/README.md).

## Keeping the repository free of personal data

The public repository was prepared from a private working folder. Keep it that way:

- **Never commit** character saves (`*.json` outside the data and fixtures folders), world saves (`*.sav`), the game's `.backup` / `.verbackup` copies, `*.pyedit.bak` files or snapshot folders. `.gitignore` covers these; check `git status` before every commit anyway.
- World saves cache **other players' characters**, so they are personal data even when the world is yours.
- In notes and data, refer to saves generically ("the reference save", "World A", "World B", "GuestChar") and use placeholder file names such as `MyCharacter#1.json` and `MyWorld.sav`.
- Don't commit absolute paths that contain a user name.
- Don't paste verbatim text from the wiki into bundled data. The wiki is CC BY-NC-SA 3.0; paraphrase it and link the page (bundled quest data uses a `wiki_summary` field for this).
- Game IDs (item, quest, skill, recipe, spell and level-actor GUIDs) are the same for every player and are fine to commit.
