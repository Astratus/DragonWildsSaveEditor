# lodestones.md: fast-travel lodestone storage (AI-oriented)

Research date 2026-11-25. Game build ~1.0.2.0, world saves = SPUD `.sav`. Helper: `lodestones.py` (list; EXPERIMENTAL activate/remove of the 4 fixed stones, see "Implemented edits" below; tests: `tests/test_lodestones.py`; the real-save tests need `DW_TEST_WORLD=<copy of a world .sav>`). Catalog: `lodestones.json`.

## Install check (2026-11-26, game 1.0.2.2)

`python -m dragonwilds_save_editor.gamedata.world` reads the `BP_WorldLodestone_C` actors from the installed game's `L_World` cells (read only; layouts in [gamedata_provenance.md](gamedata_provenance.md#world-level-map-and-lodestone-verification)). The install has exactly 4 such actors, and for all 4 the id (GameplayObjectRegistryIdentifier FGuid), actor name, cell, `CTX_*` tags and location match `lodestones.json`. The three locations taken from world saves equal the install's doubles exactly. **Umbral Sands** was the only difference: its datamine location was rounded (up to 0.008 units off); `lodestones.json` now holds the install's exact values `[ 244688.567988, 96414.792213, 1373.703057 ]`, so an activation writes the same location as the game's actor. Not confirmed from the install: the names and areas (wiki and region polygons) and `spud_level` (world saves). None of the lodestone ids is in the `L_World` landmark registry, which agrees with lodestones being registered at runtime.

## Implemented edits (2026-11-25)
- `activate_lodestone(world, catalog_entry_or_id)` / `deactivate_lodestone(world, id)` in `lodestones.py`, on an open `spud.WorldFile`, in memory. They rewrite only `GameplayObjectRegistry.Lodestones` (u32 count + entries) via `set_raw_property`, then re-serialize and fully re-parse the file (`WorldFile.validate_bytes`; object count unchanged, registry ids as intended; on failure the property is rolled back). No events, switches, quest state or other properties are touched. (2026-11-26: moved from the earlier, now removed, world module to the clean-room `spud.py`.)
- Only ids in `lodestones.json` are accepted; an id that matches a saved lodestone actor (built) is refused ("build/demolish them in game"). Already in the wanted state = no-op (returns False).
- Remove keeps the other entries' order and exact bytes. Activate appends `encode_entry(id, catalog location)` at the end. Exception: if the stone was in the registry when the file was loaded (removed earlier in the same session), its original bytes go back at the original position, so remove + re-add before saving is byte-identical.
- Catalog `location` for Temple, Death's Domain and Dowdun Reach Entrance is now the exact double the game wrote (so `encode_entry` reproduces the game's entry byte-for-byte); Umbral Sands now uses the installed game's exact actor location (2026-11-26; it was datamine-precision, within 0.01 uu).
- All lodestone edit checks share one "expected id list after the latest edit", because `WorldFile.save()` re-runs every recorded check on the final file.
- GUI: World tab > "Lodestones (experimental)": the 4 fixed stones (name, area, active) + built ones greyed/read-only ("build/demolish in game"). Activate/Remove ask for confirmation (default No) with: experimental note; removal may undo itself (re-registration on touch or area load); quest gate of the stone's area from `map_points.json` `areas[].gated_by_quest`, with a WARNING if the open character has not started that quest; Temple removal "probably pointless"; game must be closed; SpudCache. Saving = the existing "Save world" (refuses while the game runs, snapshots ALL character + world saves to `pre-world-edit_*` in the editor's backups folder, `.pyedit.bak`, verify, replace).
- SpudCache: neither `spud.py` nor the GUI deletes `Saved\SpudCache\*` (the game rewrites it while a world is loaded). The dialogs list how many files are there and say to keep the game closed and, if the change doesn't show, delete the cache by hand.
- Tested: synthetic round trips/refusals; real copies (both worlds): Dowdun remove + re-add (and add + remove in the small world) = byte-identical file after `save()`; remove, save, reopen, re-add = same entry bytes appended at the end; Umbral Sands activation saves and parses back with 27 entries (big world), only the registry object changes. In-game effect still unverified.

## TL;DR
- Lodestone state is **per world**, shared by every character in that world. There is **nothing in the character JSON** (the only hit, `GameProgress.ActorsInteractedWith`, is a class-name list that the game discards on load with a "Unknown Actor Class ... skipping" warning).
- The fast-travel list is one array: level `L_World`, object `GameplayObjectRegistry_UAID_004E01B922A1A82801_2090510967` (class `/Script/Dominion.GameplayObjectRegistry`), property **`Lodestones`** (SPUD type 64 = record, decoded as UE5 tagged properties).
- Each entry = `{Location: Vector_NetQuantize (3 doubles), RespawnLocation: same with Z + 145, Identifier: Guid}`. The map UI teleports by `Identifier` (game log: `HandleLodestoneIconClicked() : Lodestone with ID <Identifier> clicked`; IDs logged = IDs in the array).
- Two kinds of lodestone feed it:
  - **Fixed world lodestones** (`BP_WorldLodestone_C`): 4 in the game. Their `GameplayObjectRegistryIdentifier` is baked into the level (identical in every world). Their own SPUD record holds no state (identifier saved as all zeros, plus `bCanBeDamaged`).
  - **Player-built lodestones** (`BP_BaseBuilding_Lodestone_C`, Construction build piece; wiki: 32 stone, 20 rune essence, 1 vault core). Runtime-spawned (SPWN) actors in `L_World`; `Lodestone Component/GameplayObjectRegistryIdentifier` = a random GUID per placement = the registry `Identifier`.
- There is **no "activated"/"repaired" flag** anywhere. "Activated" = "has a registry entry" (inferred, high).

## Exact layout of `GameplayObjectRegistry.Lodestones`
```
u32 count
repeat count:
  FString "Location"        FPropertyTypeName StructProperty<Vector_NetQuantize</Script/Engine>>  u32 size=0x87  u8 flags=0
      "X" DoubleProperty u32 8 u8 0 <f64>   "Y" ...   "Z" ...   "None"
  FString "RespawnLocation" (same type)  X,Y same as Location, Z = Location.Z + 145.0 (exact in all 27 sampled entries)
  FString "Identifier"      StructProperty<Guid</Script/CoreUObject>>  u32 16  u8 flags=0x08  <16 bytes: 4 x u32 LE>
  FString "None"
```
- No trailing bytes; entries tile the record exactly (`parse_registry_record` checks this and returns each entry's byte span).
- `tests/test_lodestones.py` rebuilds every real entry byte-for-byte from (id, location) with a small encoder, so writing a new entry is a solved formatting problem.
- Location values are full doubles of the actor's world transform (for world lodestones they match the datamined `DefaultSceneRoot` location within 0.01 uu; the datamine JSON only prints ~float precision).
- Order: append order (build order). World lodestones sit among built ones (Temple first; Death's Domain and Dowdun Reach Entrance appear where they were activated).
- Sibling properties on the same object: `Beds` (adds `ClaimingCharacterGuid`, `ClaimingAccountGuidStr`, `ClaimingCharName`, `RespawnRotationByte`: beds are owned, lodestones are not), `Gravestones`, `bCanBeDamaged`.
- The registry object also exists in `Saved/SpudCache/L_World.lvl` while a world is loaded (stale-cache risk for edits).

## Every fixed lodestone (datamine RSDWArchive 1.0.2.0 `Content/Maps/World/L_World/_Generated_/<cell>.json`, confirmed by the wiki's 4 "Permanent locations" map markers)
| Name (wiki) | Area / sub-region (map polygons) | Identifier | Location (uu) | Actor (cell) | Confidence |
|---|---|---|---|---|---|
| Temple of Saradomin (starting "Lodestone (Inactive)") | Brynmoor / Temple Woods | 5E74232B4126EDE0BAEFF9856FFD03C6 | 5065, 189026, -3633 | StaticMeshActor_UAID_7486E239CD4644CE01_2105747359 (5DE2Q7722I32URAIIDX90NY5T) | very high |
| Death's Domain | Fellhollow / Forgotten Temple (tag CTX_Fellhollow) | C29B965F4A6FE5855746CDB2FB61F658 | 133137, 38672, -3349 | StaticMeshActor_UAID_AC1A3DB43E39778602_1347654207 (24MG3D1C2GJRN9CALY7J7APUE) | very high |
| Dowdun Reach Entrance | Dowdun Reach / The Approach (tags CTX_Fellhollow, CTX_DowdunReach) | BEE7FC7343CE7CEA0DED91847DD83D19 | 220779, 28802, -5538 | StaticMeshActor_UAID_AC1A3DB43E3906B902_1575504920 (8BLAK65ZWMQLJSO4WHZEFWBTL) | very high |
| Umbral Sands | Umbral Sands / Alcarrid Oasis (tag CTX_UmbralSands) | 122F25504BAF11D411C40A917C5811F5 | 244689, 96415, 1374 | BP_WorldLodestone_C_UAID_AC1A3DB43E393BDC02_1489140288 (D0PFFXG3QO5HY781FKOL02PKA) | high (never seen in a save) |

Completeness: the wiki map lists exactly these 4; the 3 seen in saves match the datamine IDs exactly. Three of the actors were renamed `StaticMeshActor_*`, so a class search of `L_World.json` alone finds only one; a full scan of all `_Generated_` cells was not done (medium risk of a hidden 5th, low).

Not lodestones (don't confuse): `BP_InteractablePlayerTeleporter*` (Dowdun Reach portals with `NS_VFX_DRLodestone_*` effects, quest-gated), `BP_Spectral_Door...Teleporter`, Nightmare Crucible teleporters, `PoiDiscoverySystemActor` POIs, Sanguine Urns (`ShrinesUnlocked`).

## This save's state (sample worlds, IDs only)
- Large world: 26 registry entries = 3 fixed (Temple, Death's Domain, Dowdun Reach Entrance) + 23 built. Umbral Sands is **not** registered. Every built entry has a matching `BP_BaseBuilding_Lodestone` actor and vice versa (no orphans). Built health 518-750 (max 750). Coordinates per entry: run `python -m dragonwilds_save_editor.lodestones "<copy>.sav"`.
- Small world: 1 entry (Temple) and 0 built lodestones. So the Temple entry exists **without** any built lodestone; the wiki says it "activates" only when you build another one, so the registry entry alone may not mean usable (or the Temple self-registers at world start). Unknown which.
- No change in the registry across all available copies (backups full_20261124-204942, pre-quest_20261124-235401, the game's .backup files and the live files): no activation happened in that window, so there is no before/after diff. Activation mechanics are therefore inferred from structure + logs, not observed.

## What references a lodestone
- Map teleport UI: by `Identifier` (log-confirmed).
- `RespawnLocation`: arrival point for teleports (Z + 145). Whether lodestones are also death-respawn points is not shown; the field name is shared with beds (which are respawn points). Unknown.
- Built lodestone actor: `Lodestone Component/GameplayObjectRegistryIdentifier`, `BuildingPieceID` (base-building piece index; pieces may be referenced by stability/building systems), `HealthComponent/AuthoritativeHealth`, `StabilityValue`, `bIsGhosted`, `FurnitureBonus`.
- Fixed lodestone actor: the identifier is baked into the level asset; the saved record holds zeros. Its BP has an `OnInteraction` handler (`BndEvt__BP_WorldLodestone_LodestoneInteraction...`), which is most likely what registers it (inferred).
- No owner, character GUID, quest variable, event or switch references a lodestone.

## Edit feasibility (original assessment; items 1-2 are now implemented, see above)
Both edits touch only `GameplayObjectRegistry.Lodestones` (a size-changing record edit in `L_World`). They involve **no events (WorldEventManager) and no switches/levers/seals**. `spud.WorldFile.set_raw_property` supports size-changing record edits; `lodestones` re-parses after each edit and `save()` checks the object count is unchanged. A future `add/remove` would go in `lodestones.py` using `parse_registry_record` spans + the entry encoder from the test, then `w.save()` (snapshot, .pyedit.bak, game-running check). Also delete `Saved/SpudCache/*` (or edit only with the game closed and the world not loaded) so the cache can't shadow the edit.

1. **Add (activate) a fixed lodestone** (e.g. Umbral Sands): append `{Location = catalog location, RespawnLocation = Location + (0,0,145), Identifier = catalog id}` and bump the count. Format confidence very high (byte-exact encoder). In-game effect confidence: medium-high. Risks: if registration happens on interaction only and the game also keeps hidden "activated" state in the BP (none is saved, so unlikely), the stone could look inactive while still being a teleport target; slightly different double coordinates than the game would write (harmless, values are actor positions). Don't add a stone in an area the character can't legally reach yet (Umbral Sands is quest-gated): teleporting there would skip progression.
2. **Remove (deactivate) a fixed lodestone**: drop its entry. Format confidence very high. Effect: medium. It probably re-registers the next time the player interacts with it; if registration is at BeginPlay instead (the Temple case hints at this), it may come back on its own as soon as its cell loads. Removing the Temple one is pointless/risky (starting stone).
3. **Remove a built lodestone from the list only**: NOT recommended. The SPWN actor still exists with the same identifier, so the world would be desynced (a standing lodestone that is not a target, or re-registered on load). Correct removal = destroy the building piece in game. Deleting the SPWN object would need new spud support (object removal; changes object count) and could break base-building stability data. Not feasible safely.
4. **Add a built lodestone**: needs spawning a new actor (SPWN with class/prop tables, transform, building piece ID). Not feasible; build it in game.
5. **"Repair"**: there is no repaired state for world lodestones; built ones have `HealthComponent/AuthoritativeHealth` (same-size float, `set_scalar` could set 750). Low value.

Recommended scope for a GUI: list (done), and at most "activate/deactivate fixed world lodestone" with the warnings above. Overall confidence in the storage model: high (structure, IDs and UI use are confirmed; the activation trigger is inferred).

## Unknowns
- What exactly registers a fixed lodestone (interaction vs. BeginPlay) and whether the Temple entry alone makes it usable. Test: in a throwaway world, note the registry, interact with a fixed lodestone, save, diff with `lodestones.py`.
- Whether teleport destinations are validated against the actor (e.g. cell loaded / actor exists) or only the registry entry.
- Whether a full cell scan would reveal more `BP_WorldLodestone_C` actors (the wiki says 4).
- Whether `RespawnLocation` is used for death respawn.
