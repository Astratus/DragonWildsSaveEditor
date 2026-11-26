# Game-data reader: provenance

`dragonwilds_save_editor/gamedata/` reads the player's own installed copy of RuneScape: Dragonwilds (`<install>\RSDragonwilds\Content\Paks`), read only, with seeks. Files are opened read-only and shared, so nothing in the game folder is written, renamed or locked, and it works while the game runs. Nothing attaches to, injects into or dumps the running game; no `.usmap` mapping file is used or produced; the game executable is not read. The reader makes no network connections.

## Format knowledge used

All code is our own. The binary layouts were taken from public descriptions, mainly the Apache-2.0 [CUE4Parse](https://github.com/FabianFG/CUE4Parse) project (read on 2026-11-26 as a format reference; no code copied or included), and then checked against the bytes of this game's containers (game version 1.0.2.2):

| Topic | Source | Checked against the game | Module |
|---|---|---|---|
| IoStore TOC v8 header, chunk ids, offset/length (5+5 byte big-endian), compression blocks (5+3+3+1 bytes), directory index (mount point, dir/file entries, string table) | CUE4Parse `IO/` | 125,297 TOC entries, 106,285 file paths; all needed packages found | `iostore.py` |
| Pak v11 footer and full directory index | CUE4Parse `Pak/`, Epic docs | 4,779 files listed (`DefaultGame.ini`, ...) | `iostore.py` |
| Zen package summary (UE 5.3+: 52 bytes), name batch, imported public export hashes, import map, export map (72-byte entries), imported package names | CUE4Parse `IoPackage`, `FZenPackageSummary` | UE 5.6 adds two int32 (Verse cell import/export offsets) before the name map: found by inspection. Imported package names = a name batch plus one int32 number per name: found by inspection. | `zen.py` |
| Export data offset = header size + cooked serial offset | CUE4Parse | every needed export ends exactly at the expected place | `zen.py` |
| Global script objects (global.utoc, chunk type 5) | CUE4Parse `IoGlobalData` | 62,376 script objects; classes resolve to `/Script/Dominion.ItemData` etc. | `zen.py`, `game.py` |
| FPackageObjectIndex (2-bit kind; package import = package index << 32 \| hash index) | CUE4Parse | every class resolves (5,671 packages) | `zen.py`, `game.py` |
| Unversioned header: uint16 fragments (skip 7 bits, has-zeroes, is-last, value count 7 bits), zero mask (1 byte / 2 bytes / uint32 words) | CUE4Parse `FUnversionedHeader` | all 5,671 main exports | `uprops.py` |
| Header writer invariants (no empty fragments, fragments after the first have a skip, a has-zeroes fragment has a zero) | our reading of the format; used only as a plausibility filter during schema inference | all 5,671 real headers satisfy them | `uprops.read_header_strict` |
| Property order = `PropertyLink` order (a class's own properties first, then its parent's) | Unreal Engine behaviour, confirmed here: the PersistenceID index moves from 36 (ItemData) to 61 (WearableEquipmentData), etc. | a subclass's schema is the parent's shifted by the subclass's own count | `schemas.py`, `derive.py` |
| FText: flags uint32, history int8; -1 None (bool + optional string), 0 Base (namespace, key, source), 11 StringTableEntry (FName table, key) | CUE4Parse `FText` | names resolve through the string tables | `uprops.py` |
| UStringTable export: empty header, bHasGuid int32, namespace, count, key/value FStrings | CUE4Parse `UStringTable` (the FStringTable layout found by inspection) | 12,098 entries in 140 tables | `stringtable.py` |
| FSoftObjectPath in cooked zen data = FName package + FName asset + FString sub-path | inspection | icons and meshes resolve | `uprops.py` |
| Game version = `ProjectVersion` in the pak's `RSDragonwilds/Config/DefaultGame.ini` | inspection | `1.0.2.2` | `game.py` |

## Native class schemas

Native classes (`/Script/Dominion.ItemData`, `RecipeData`, ...) keep their property definitions in the game executable, which is not read. Instead the development tool `python -m dragonwilds_save_editor.gamedata.infer` infers, for each class, how many bytes each property index takes, from the instances themselves, and writes `dragonwilds_save_editor/data/gamedata/schemas.json` (33 of the 50 classes the catalog reads are solved completely):

- all instances of a class are parsed jointly; every instance must end exactly at the end of its export (and, where present, the PersistenceID string, located by pattern, must start exactly where the property it belongs to starts);
- types come from a small grammar (fixed sizes 1/2/4/8/12/16/24/32 bytes, FString, FText, soft object path, TArray, nested struct, TMap), tried in order of plausibility of the values they read;
- fields the unversioned writer zero-masks (all-zero memory) never appear as written values; this is used as a filter;
- the search backtracks to the latest decision when a choice fails.

Hand seeds (types only, read off the bytes): `infer.SEEDS` (ItemData's leading properties and HeldEquipmentData's own properties) and `derive.LEADING` (UtilitySpellData and JournalEntryKnowPlaceData property 0 = an FText).

Fallbacks for classes without a complete schema (`derive.py`):

- PersistenceID: a 22-character base64url FString followed by the InternalName FString (or, in a Blueprint class default object, the last value of the export), located by pattern.
- Suffix alignment: the parent-class part (ItemData, journal-entry base) is decoded by trying every start offset and keeping the one whose parse ends exactly at the PersistenceID. Up to two parent indices with no known type are tried with plain types, and the choice must fit every instance of the class. ItemData index 22 (tree seeds only) fits only as 0 bytes; this is not understood.
- Pattern scans: FText (string-table entry / base text) and DataTable row handles; AI row names are checked against the name maps of the game's `DT_AIData*` tables.

The meaning of an index (which one is the name, the stack size, ...) was assigned by hand in `derive.py` from the decoded values (e.g. an int that is 99/999/9999 and absent for gear; an FText pointing into `ST_ItemNames`) and then validated against the editor's earlier, dump-based catalog: every ID and field agreed ([catalog_build.md](catalog_build.md#cross-check-against-the-earlier-dump-based-catalog)). That earlier catalog was used only for this validation, never as an input to the build.

## World level (map and lodestone verification)

`python -m dragonwilds_save_editor.gamedata.world` checks `data/map_points.json` and `data/lodestones.json` against the installed game. Layouts found by inspection (each array is parsed element by element to its exact end):

- **Landmark registry**: the export of class `/Script/Dominion.GameplayObjectRegistry` in `/Game/Maps/World/L_World`. Its property 4 is an array of 558 landmark structs: 0 location (3 x float64), 1 category (uint8: 6 = Sanguine Urn, 8 = kebbit burrow; also 1 Dragonkin altar, 3 quest points, 5 Anima vents, 11 agility courses, 4 unnamed), 2 InternalName (an FName: the 32-hex ID the save stores; these IDs are not stored as strings or FGuids), 3 display name (FText), 4 FGuid, 5 struct {gameplay tag}, 6 needs-discovery (bool), 7 discover distance (float).
- **Map regions**: 31 `BP_MapRegion_C` exports in `L_World`: optional property 0 = struct {quest-entry tag}, property 1 = RegionID (uint8; fog bit N = RegionID N; there is no region 0), property 2 = display name (FText into `ST_Localization`, `ST_RegionNames` or `ST_DDR_RegionNames`); the area is the `Location.Region.*` FName the export references.
- **Fixed lodestones**: `BP_WorldLodestone_C` actors in the World Partition cells `/Game/Maps/World/L_World/_Generated_/<cell>` (1,731 cell packages; 4 actors). The actor export holds its GameplayObjectRegistryIdentifier as an FGuid (four little-endian uint32 from the hex); its child export `DefaultSceneRoot` holds the location as 3 x float64; its `CTX_*` FName references are its tags.

Result for game 1.0.2.2 (recorded in each file's `install_check`): all 31 fog-bit region names and areas, all 21 Sanguine Urn and 19 kebbit-burrow IDs (with category and area tag) and the id, actor, cell, tags and location of all 4 fixed lodestones agree. The only difference was the Umbral Sands lodestone location, rounded in the data by up to 0.008 units; it now holds the game's exact values. Not confirmed from the install: urn/burrow sub-region names, area quest gating, lodestone names and areas (see [map_points.md](map_points.md), [lodestones.md](lodestones.md)).
