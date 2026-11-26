# Scope, design and safety model

This page explains what the editor changes, what it deliberately leaves alone, and how it tries to keep your saves safe.
For the legal and risk notes, see [DISCLAIMER.md](../DISCLAIMER.md).

Target: RuneScape: Dragonwilds build 1.0.2.x, character save `Version` 86.

## What it edits

**Character save** (`SaveCharacters\<Character>.json`):

| Area | What you can do |
|---|---|
| Inventory | View and edit the bag, hotbar, rune/ammo/quest pouches, personal storage and equipped gear: change stack counts, repair durability, remove items (removing equipped gear also unequips it). |
| Add Items | Search the item catalog and add items, placed in the right inventory section. Counts are capped at the item's stack size. |
| Skills | Set skill XP or level (levels 1-99) for the 12 released skills. |
| Unlocks | Lock or unlock recipes, building pieces and spells. The equipped spell wheel is shown read-only; locking a spell can blank it from the wheel. |
| Main Quest | Revert the main questline to an earlier **checkpoint** (see below). |
| Map | Show or hide map regions (fog of war, cosmetic), and add or remove found Sanguine Urns and kebbit burrows. Only IDs from the bundled map catalog, or IDs the game already wrote, can be added. Removing a Sanguine Urn probably lowers max health by 10 (inferred, untested); the tab warns. |
| Backups | List, create, restore, delete and prune backups of the character save or of the focused world save (the world list also shows the copies in the full snapshots). |

**World save** (`SaveGames\<World>.sav`), **experimental**. The toolbar's **World** row picks one focused world (by default the newest), which the World and Backups tabs use; it is saved separately from the character:

- View defeated bosses, triggered world hooks, progress tags and cached guest characters (read-only), and search objects by class.
- Remove a defeated boss from the world's progress list.
- Change or remove a world progress tag value.
- **Lodestones (experimental):** list the world's fast-travel lodestones, and activate or remove the four fixed world lodestones. Player-built lodestones are read-only: build or demolish them in game.

None of the world edits have been tested in game (see [Tested status](#tested-status)).

## What it deliberately does NOT do

- **No switches, levers, seals, doors or world events.** These are world-side state, and editing them can desync the world from your quests.
- **No forward quest jumps.** You can only go *back* on the main questline. The game moves you forward, so rewards, cutscenes and world events happen for real.
- **No arbitrary quest steps.** You can't set quest variables by hand or pick a step that isn't a known, verified checkpoint.
- **No tutorial quests.** First Steps, Getting Started, Ratcatcher and Rune Mysteries depend on hidden hand-offs, start-area trigger volumes and one-time pickups. They are excluded.
- **No side quests**, apart from the hidden helper records some main quests use.
- **No multiplayer features**, and none will be added.
- **No game-file mods.** Only save files are read and written.
- Adding new world progress tags isn't supported. It also doesn't update the game's own `.sav.backup` copy.

## The main questline: linear, revert-only

The main questline (Dragon Slayer, Withering Heights, Black Knight's Fortress, Icthlarin's Little Helper, Regicide) is modelled as **one straight line of checkpoints**.
Each checkpoint is an exact snapshot of the quest record at a real resting point in the story, such as "all three seals broken, ready to challenge Imaru".

When you revert to a checkpoint:

1. Every earlier main quest must already be complete, and is left alone.
2. That quest's record is replaced by the checkpoint's exact values.
3. Every **later** main quest (and its hidden helper records) is reset to the game's own "not started" form.
4. Quest markers and the tracked quest are set, items the step needs are added back (for example the three Curse Fragments for Imaru's lair door), and "already picked up" records are cleared where the game needs to see a pickup again (for example a boss head that gives quest credit).
5. One-time region-intro cutscenes that come **later** in the story (Fellhollow, Dowdun Reach, Umbral Sands, Scorned Wilderness) are cleared from the character's triggered-hooks list, so they play again when you get there. Tutorial and repeatable hooks are never touched, and the map is not changed. After a revert, the Main Quest tab may *offer* (default No) to hide map areas whose gating quest is now not started.

Why revert-only and linear?

- **The game can't be in a mixed state.** A save where a later quest is in progress while an earlier one isn't complete never happens in normal play, and nobody knows how the game would handle it.
- **Going forward skips real events.** Rewards, world changes and one-time triggers fire when you play a step. Jumping ahead would skip them and leave the save inconsistent.
- **Going back replays content you've seen.** The target state is one the game wrote itself, and the game then moves you forward normally.

What a revert does **not** undo: items, XP, recipes, journal entries and side-quest progress you earned after that point. Only the main-quest records, markers, the tracked quest and the listed items change.

## Confidence levels

Every checkpoint has a confidence rating. It says how sure we are that the checkpoint matches what the game would have written.
Checkpoints are built from community datamined quest logic and checked against real saves and the official wiki.

| Rating | Meaning in plain words | In the editor |
|---|---|---|
| **Very high** | Every value was traced to the game's own quest logic or confirmed on the wiki, and nothing conflicts with real saves. | Applies after one confirmation. |
| **High** | Exactly one detail is inferred rather than traced, and it is believed to be safe either way. | Needs a **second confirmation** that shows you what was inferred. The engine refuses to apply it otherwise. |
| **Medium / low** | Too much is unknown. | Shown but disabled. |

The stored rating rule (`rating_rule` in `dragonwilds_save_editor/data/main_questline.json`):

> very high = every quest-record value traced to a flow write, continuation gates/world needs traced or wiki-CONFIRMED, no conflict with real saves; a remaining inference that is only an extra harmless cleanup action (e.g. removing a picked-up record) does not lower the rating. high = one untraced item that is safe either way.

The minimum enabled rating is set by `min_confidence` (currently `"high"`).
Current line: 24 checkpoints, 17 very high, 4 high and 3 medium (disabled). The research notes behind each one are indexed in [docs/research/](research/README.md).

## Safety model

1. **Per-file backup before every write.** Each save writes `<file>.<YYYYmmdd-HHMMSS>[-N].pyedit.bak` next to the original. Backups are never overwritten, and their size is checked.
2. **Full snapshot before quest and world edits.** Before a Main Quest or World save, *all* character and world saves are copied to
   `%LOCALAPPDATA%\DragonwildsSaveEditor\backups\pre-quest_<stamp>\` or `...\pre-world-edit_<stamp>\`, and the copies are hash-verified. Quest state lives partly in the world files, so this snapshot is the complete rollback.
3. **Refuses to save while the game is running.** The game holds saves in memory and would overwrite your edit, or the files could clash.
4. **Byte-exact round trip.** The character file is rewritten in exactly the game's own formatting (tabs, line endings, number text, field order). Loading and saving an unedited file gives identical bytes. A `selftest` checks this.
5. **Verify after write.** Files are written to a temporary file, read back and checked, then swapped into place. World saves also refuse to save if the file changed on disk since you opened it.
6. **Unknown fields are never touched** (`Backup`, `HistoricCorruption`, `SaveCount`, the character GUID).
7. **Edits stay in memory until you press Save.** The app warns you about unsaved character and world edits when you close it or switch worlds.

## Known unknowns

These things are not known. Contributions with evidence are welcome.

**Character save**
- What the trailing `Backup` number is. It changes every save and isn't a CRC32 or FNV hash. Working it out would need game-binary reverse engineering. Edited saves have loaded so far, so it seems not to be strictly checked.
- What `HistoricCorruption`, `char_type` and `Hardcore.AssociatedWorld` mean.
- The meaning of some status-effect fields (hashes, decay rates) and of map pin types and medal values.
- Where the inventory sections end. The section start slots are known from real saves; the end slots are inferred.
- What the game does with stacks above the normal maximum. The editor caps counts, so this doesn't come up in normal use.
- A few unlock IDs (killed-once creatures) and fill-type IDs (watering can, compost bucket) don't appear in any extracted game data and show as unknown.
- Some first-entry and one-time effects that may be account-wide rather than per character.

**Quests**
- Whether a few quest flags are first-pickup-only, or are set by level trigger volumes that aren't in the extracted data. These are the "inferred" parts of the **high** checkpoints.
- Whether clearing old quest markers affects side-quest markers (they are expected to be recreated when the game next touches them).
- Checkpoints *ahead* of the reference saves (late Black Knight's Fortress, Icthlarin's Little Helper, Regicide) are checked against the quest logic and wiki but not yet against a real save at that point.

**World save**
- What any world edit does in game. For example, whether removing a defeated boss lets it respawn.
- Whether progress tag values are read as integers or floats (the editor writes integers).
- Whether a stale `Saved\SpudCache` could hide a world edit. If you edit a world, clear that folder first.

## Tested status

- **Automated tests:** the libraries, the GUI's shared state and the questline engine have a unittest suite. The questline test applies every reachable checkpoint to a copy of a synthetic test save built from real saves, saves it, reloads it and checks that it lands exactly on the checkpoint, with a byte-exact round trip.
- **Copies:** every edit type was exercised headlessly on copies of real character and world saves.
- **In game: limited.** So far there has been little or no testing in the actual game. Treat every feature, and especially quest reverts and all World edits, as unproven in game until this section says otherwise.

<!-- MAINTAINER: fill in as in-game testing happens. -->
| Feature | Game build | In-game result | Date |
|---|---|---|---|
| Inventory edits / Add Items | _TBD_ | _not yet tested_ | |
| Skills | _TBD_ | _not yet tested_ | |
| Unlocks | _TBD_ | _not yet tested_ | |
| Main Quest revert (which checkpoint?) | _TBD_ | _not yet tested_ | |
| World tab edits | _TBD_ | _not yet tested_ | |
| Lodestones (activate/remove) | _TBD_ | _not yet tested_ | |
| Map (fog, urns, burrows) | _TBD_ | _not yet tested_ | |
