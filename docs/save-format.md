# Character save format

This page describes the RuneScape: Dragonwilds **character** save (`SaveCharacters\<CharacterName>.json`) as far as the community understands it, and how to edit it without breaking it.
It applies to save `Version` 86 (patch 1.0.1 and later). World saves (`SaveGames\<WorldName>.sav`) use a different, binary format (SPUD) and are not covered here; see [research/world_save_survey.md](research/world_save_survey.md) for what is known about them.

Jagex does not document this format. Everything below was worked out from real saves and cross-checked against other community editors, so treat it as best current knowledge rather than a specification.

## Contents

- [Identifiers](#identifiers)
- [Top-level structure](#top-level-structure)
- [Inventory containers](#inventory-containers)
- [Item entries](#item-entries)
- [Skills](#skills)
- [File formatting](#file-formatting)
- [Fields to leave alone](#fields-to-leave-alone)
- [Is editing detected?](#is-editing-detected)
- [Safe editing procedure](#safe-editing-procedure)
- [Data files](#data-files)

## Identifiers

All item, skill, recipe, spell and journal IDs are **22-character base64url GUIDs without padding** (alphabet `A-Z a-z 0-9 - _`), for example `hKYyX0vQ_pgLRAi2ugGK3w`.
Shrine, burrow and world IDs are 32-character uppercase hex instead.

Each item instance in an inventory also has its own `GUID` in the same 22-character format. A new item needs a fresh random GUID: 16 random bytes, encoded as base64url with the `=` padding removed. Never reuse an existing one.

## Top-level structure

```text
Version: int                      # 86 at the time of writing
meta_data: { char_guid, worlds_playtime{worldGuid: int}, char_name, char_type }
SaveCount: int                    # bumped by the game on every save
HistoricCorruption: int
Customization.CustomizationData.{BodyType, Head, HairPreset, ...}: { dataTable, rowName }
Hardcore: { IsHardcore: bool, AssociatedWorld }
GameProgress:
  Version
  Character: Health/Stamina/SpecialCharge {CurrentValue}, Sustenance/Hydration/Endurance,
             StatusEffects{...}, Mount{MountEquipped, MountsUnlockedList}, ...
  Inventory                       # main inventory (hotbar, bag, pouches)
  PersonalInventory               # small personal stash
  Loadout                         # equipped gear
  Progress: ItemsPickedUp[], RecipesUnlocked[], RecipesNew[], BuildingsUnlocked[],
            SpellsUnlocked[], AgilityCourseScores[], ...
  QuestProgress: { QuestTrackedMain, QuestTracked,
                   Quests[{QuestId, QuestState, QuestObjective, QuestInts[], QuestBools[]}],
                   QuestLocations[] }
  Skills.Skills: [{ Id, Xp }]     # 12 entries
  Journal, MapCustomization.Pins[], Spellcasting.SelectedSpells[], RevealedFog, RevealedLandmarks
Backup: uint32                    # always the last key; game-managed
```

The top-level keys appear in this order: `Version`, `meta_data`, `SaveCount`, `HistoricCorruption`, `Customization`, `Hardcore`, `GameProgress`, `Backup`.

## Inventory containers

`Inventory`, `PersonalInventory` and `Loadout` are **objects keyed by slot number as a string** (`"0"`, `"1"`, ...), not arrays.

- A missing key means an empty slot.
- Non-numeric keys such as `MaxSlotIndex` may be present. Put any metadata keys first and `MaxSlotIndex` last, and keep slot keys in ascending numeric order.
- If a container has `MaxSlotIndex` and you put an item in a higher slot, raise `MaxSlotIndex` to match. In the reference save it is 113 for `Inventory` and 11 for `Loadout`. There is no `Version` key inside these containers.

### Inventory sections (patch 1.0.1+)

| Section | Slots | Catalog `inv_tab` |
|---|---|---|
| Hotbar | 0-7 | n/a |
| Bag | 8-39 | `bag` |
| Rune pouch | 40-71 | `rune` |
| Ammo pouch | 72-103 | `ammo` |
| Quest items | 104-135 | `quest` |

These ranges are inferred from the reference save, where each section's first used slot is 8, 40, 72 and 104. Only the start offsets are confirmed; each section probably has fewer usable slots than its range. Put each item in the section named by its `inv_tab`.

Older editors document the pre-1.0.1 layout (bag 8-31, runes 32-55, ammo 56-79, quest 80-103). Patch 1.0.1 (around 2026-10-14) grew the inventory, so that layout is out of date.

### Personal inventory and loadout

- `PersonalInventory` uses slots 0-19.
- `Loadout` slots 0-4 hold equipped items: 0 Head, 1 Body, 2 Legs, 3 Cape, 4 Jewellery.
- `Loadout` slots 5-8 are not items but **pointers** into `Inventory`: `{ "PlayerInventoryItemIndex": n }` for the weapon, shield, ammo and amulet. Removing the inventory item an equipped pointer refers to must also clear the pointer.
- Don't add new `Loadout` slots.

## Item entries

Each entry has exactly one of `Count` or `Durability`, or neither:

```jsonc
{ "GUID": "<22-char>", "ItemData": "<item id>", "Count": 22,        "AddedToInventoryTimestamp": 140698833649664 } // stackable
{ "GUID": "<22-char>", "ItemData": "<item id>", "Durability": 1750, "AddedToInventoryTimestamp": 6.39e17 }         // gear
{ "GUID": "<22-char>", "ItemData": "<item id>",                     "AddedToInventoryTimestamp": 140698833649664 } // single item
{ "PlayerInventoryItemIndex": 12 }                                                                                 // Loadout pointer only
```

Rules:

- **Gear** (any item whose catalog entry has a `max_durability`) uses `Durability`, normally set to that maximum. Everything else uses `Count`.
- **`Count` is omitted when it is 1.**
- **Keep `Count` at or below the item's `max_stack`** (the game's own `MaxStackSize`). Typical values: 99 for most resources and food, 50 for some consumables, 999 for arrows and bolts, 9999 for runes, 1 for gear. One editor's README reports that counts above the maximum split or revert in game.
- **`AddedToInventoryTimestamp`**: copy it from an existing item. Values are either a small integer or a large .NET-ticks-like double.
- Some items carry extra keys: `NumUpgradesApplied`, or `RemainingFillCharges` with `ContentItemData` for filled containers. Keep them as they are.
- Avoid catalog items flagged **retired**, **placeholder** or **derived** unless you know what you're doing; they may not load.

## Skills

`GameProgress.Skills.Skills` is a list of `{ "Id": "<skill id>", "Xp": <int> }`. The level isn't stored; it is derived from XP using the game's XP table (bundled as `xp_table.json`, where `xp_for_level[i]` is the total XP for level `i + 1`).

To set level L, set `Xp` to `xp_for_level[L - 1]`. Level 99 is 1,000,000 XP. XP above that is allowed.

| Skill | Id |
|---|---|
| Agility | `pJggvotwOkuoc98igUn7xA` |
| Artisan | `Wf3i7Ha-B06DH719j1vtBw` |
| Attack | `4pefO9k1lUqfA6mvHNi1SA` |
| Construction | `waK-8EyQFQ2xEjCGYmuTRQ` |
| Cooking | `Tn7t6DQyX0-Q0cM5K7B90A` |
| Farming | `PyUi-0LU_riFY46AnnFiWg` |
| Fishing | `vwY5IkQJJDwb2PKEfoc8MQ` |
| Magic | `0hreSMRVXUihq9qjDO2CFA` |
| Mining | `jqX0Gh6QI0GFFPCDFK_CJQ` |
| Ranged | `heq7u88Q2UuLXFqLGTVwQw` |
| Runecrafting | `NOqC-z-2ckqi0El22qMFlw` |
| Woodcutting | `4zYUGF5u_0KbMLkWJmmBbQ` |

## File formatting

The game writes Unreal-style JSON. A standard JSON serializer produces valid JSON that the game very likely accepts, but the editor reproduces the original layout byte for byte so that an unedited load-and-save gives an identical file and diffs stay minimal:

- **Tab** indentation.
- **CRLF** line endings, **no BOM**, and **no trailing newline** after the final `}`.
- `": "` between a key and its value; members are separated by `,` and a newline.
- An object value opens on the next line (`"Key":` newline, then `{`). An array opens on the same line (`"Key": [`).
- An empty object is `{` newline `}` at the same indent. An empty array is `[]`.
- Arrays that contain only numbers or booleans stay on one line: `"PinLocation": [ 74051.7734375, 158204.53125 ]`.
- Other arrays put one element per line, one tab deeper.
- Floats are written in `%.17g` form (for example `6.3930928151894003e+17`). Integers stay integers.

## Fields to leave alone

| Field | Why |
|---|---|
| `Backup` | The last key in the file, a uint32 that changes on every save. It looks like a checksum, but it is not a CRC32 or FNV hash of the text (both were tested). Public editors leave it unchanged and their edits still load, so it seems not to be strictly checked. |
| `HistoricCorruption` | Undocumented; appeared in newer save versions. Probably a corruption counter. |
| `SaveCount` | Bumped by the game on every save. |
| `meta_data.char_guid` | The character's identity. |

## Is editing detected?

Researched on 2026-11-24:

- **No "modded" flag.** The character JSON has none. The only related keys are `HistoricCorruption`, `Hardcore` and `Backup`, and no source mentions an in-game "modded" message triggered by save edits.
- **Jagex's position.** The [Dragonwilds Community Modding Guidelines](https://legal.jagex.com/docs/policies/runescape-dragonwilds-community-modding-guidelines) say single-player cheats are fine and cheating in shared or multiplayer play is not.
- **No anti-cheat** is listed for the game; the only requirement is an Epic Online Services account.
- **Achievements.** Players report that Custom or Creative **world** settings, which live in the world `.sav`, disable achievements. Character edits are not reported to.
- **Steam Cloud** can overwrite local edits with an older cloud copy.

## Safe editing procedure

1. Close the game, or at least make sure this character isn't loaded. The game overwrites the file when it saves.
2. Copy the save first, ideally the whole `%LOCALAPPDATA%\RSDragonwilds\Saved` folder. The game's own `.backup` and `.verbackup` files rotate and are not a reliable backup.
3. Edit only the fields described above, and keep the formatting exactly as described.
4. Check that the result parses as JSON before writing it.
5. Better still, use the editor or its command-line tool (see [development.md](development.md#command-line-tool)), which backs up, checks for the running game, keeps the formatting and verifies the write.

## Data files

### Item catalog

The editor ships its own item catalog in the package's `data/catalog/` folder. It is generated from an installed copy of the game (version 1.0.2.2, read only) by the editor's own reader (`gamedata/`) and rules (`catalog.py`):

| File | Contents |
|---|---|
| `items.json` | One object per item: `id`, `name`, `category`, `hint`, `max_durability`, `max_stack`, `inv_tab`, `retired`, `placeholder_name`, `derived_name`, `source`. |
| `unlock_names.json` | Display names for recipe, building, spell, journal, AI and player-hook IDs, plus name tables for skill perks and skills. |
| `build_info.json` | The source ("installed game"), game version, build date, generator version, decode statistics, counts and file hashes. No local paths. |

**Help > Update item catalog** (or `dwsave catalog build`) can rebuild it on your computer from your own installed game (read only, no network connection; the result must pass a self-check). That catalog goes to `%LOCALAPPDATA%\DragonwildsSaveEditor\catalog\` (with `items.csv`, a spreadsheet copy, and `items_ai.tsv`, a compact table for grepping by name) and is used instead of the bundled one until **Help > Reset to bundled catalog**.

Every field is derived from the game's assets: the item ID is the asset's `PersistenceID`, `max_stack` its max stack size, `max_durability` its base durability, and the inventory tab comes from the item's tags; each entry's `source` is its game package path. The full rules, and the cross-checks (against the earlier catalog built from the RSDWArchive dump: every ID and field agrees; against the hand-curated lists used during development: 1,605 of 1,606 IDs match), are in [research/catalog_build.md](research/catalog_build.md).

### Bundled data

These files ship in the package's `data` folder:

| File | Contents |
|---|---|
| `skills.json` | The 12 skill IDs and names. |
| `xp_table.json` | `xp_for_level`: 99 entries, total XP per level. |
| `main_questline.json` | The main-quest checkpoints (see [development.md](development.md#quest-checkpoints)). |
| `main_quests.json`, `world_quest_stubs.json` | Quest research data behind the checkpoints. |
| `map_points.json` | Fog-of-war regions, map areas and their quest gates, Sanguine Urns and kebbit burrows (see [research/map_points.md](research/map_points.md)). |
| `lodestones.json` | The four fixed world lodestones (see [research/lodestones.md](research/lodestones.md)). |
| `catalog/` | The item catalog (above). |

Where each file comes from is recorded in [LICENSING.md](LICENSING.md), and the sources are credited in [CREDITS.md](../CREDITS.md).
