# Dragonwilds world-save (.sav / SPUD) quest-progress editing: survey

Written 2026-11-24. Everything was read-only: no tool was installed or cloned, no downloaded code was run, and the saves were never opened for writing.

Labels used below:
- **[C]** confirmed by a source URL, or by a read-only decode of the reference player's saves.
- **[I]** inference.
- **[U]** unknown.

Local saves:
- `%LOCALAPPDATA%\RSDragonwilds\Saved\SaveGames\World A.sav`: 7,914,690 B, 301 containers (L_World plus 300 RSACell levels), 11,613 objects.
- `...\World B.sav`: 251,122 B, 14 containers, 384 objects.

How they were decoded: a stdin-only Python port (about 150 lines) of OogaBoogaCode's `spud.js` plus the read side of `model.js`. It parsed both files cleanly, and the SAVE length equals the file size in both [C].

---

## 1. Which world-save editors exist

| Tool | Views / edits on the world side | Writes .sav? | Maturity | WorldProgressManager / quest / boss / door / hook state? |
|---|---|---|---|---|
| **OogaBoogaCode/RSDWSaveEditor** https://github.com/OogaBoogaCode/RSDWSaveEditor (browser, JS; `src/spud.js`, `src/model.js`, `src/app.js`) | World name, password, crossplay and clock. Difficulty mode plus 66 custom settings (CINF header and `WorldSaveSettings`). Chest and container inventories (embedded JSON). Station, weather and event JSON. An "Advanced" browser that shows every object and property: scalar, string, name, GUID, vector and array properties are editable, while anything else shows as "N bytes (read-only)". | Yes, in the browser; you download the edited file. README: "Unedited files round-trip byte-for-byte, and chunk lengths and property offsets are rebuilt on write." | 0 stars, 31 commits. Last commit 2026-10-31 ("Support the October 2026 save layout"; https://github.com/OogaBoogaCode/RSDWSaveEditor/commits/main). No corruption reports found. | **Can view, cannot edit.** WorldProgressManager's three fields are SPUD type 64 (`OpaqueRecord`, see §3), and `isEditableType` excludes 64, so the Advanced view shows them as read-only bytes. Door, lever and seal `SwitchState/SwitchPosition` (uint8) and `BP_BossAltar_Region1.bSummoned` **are** editable in its Advanced view [C, from reading `model.js` and `app.js`]. There is no quest-specific UI. |
| **haithemobeidi/RSDragonWilds-WorldEditor** https://github.com/haithemobeidi/RSDragonWilds-WorldEditor (Python and Flask: `parser.py`, `app.py`, `world_editor.py`) | Embedded JSON sections (containers, weather, world events, stations), via length-preserving text edits. Difficulty floats. Standard/Custom mode flip (2 bytes). Listing and transplanting building `Pces` pieces between worlds. World cloning (new GUID). | Yes, with auto-backup to `editor_backups\`. | 3 stars, 1 open issue. Last commit 2026-04-08 (https://github.com/haithemobeidi/RSDragonWilds-WorldEditor/commits/main), so it predates the 1.0 and Oct-2026 layout changes. BUGS.md #001: the mode conversion **breaks ownership** (locked chests and protection totems become unusable) (https://github.com/haithemobeidi/RSDragonWilds-WorldEditor/blob/main/BUGS.md). | **No.** It has no generic property decoder: it works by byte-pattern and offset search, not a class-def-driven parser. Its quest editing is character-JSON only. Its guide documents the chunk tree well: https://github.com/haithemobeidi/RSDragonWilds-WorldEditor/blob/main/docs/DRAGONWILDS_SAVE_FORMAT_GUIDE.md |
| **RSDWArchive/RSDWTools** https://github.com/RSDWArchive/RSDWTools | Character, item, spell, recipe and quest editors, plus drop tables. **No .sav editor.** | No (JSON only) | 7 stars, 2 open issues, 36 commits | No. Its quest editor is for the character file only and "does not … reset quests". |
| B1GM4NT1NGS/RSDRagonwilds-Server-to-local-coverter https://github.com/B1GM4NT1NGS/RSDRagonwilds-Server-to-local-coverter | World owner metadata only | Yes | small | No. Its own writeup says it does "not intentionally edit … world progress". |
| Elleandria, BirdRa1n, KevinStillman/dragonwilder, xxmowgli/DragonMaster, TatsumaYakoshi/DragonWilds-Ultra, websim analyzer | Character JSON and save management | — | small | No |
| gh0sted5456-us/RuneSchema https://github.com/gh0sted5456-us/RuneSchema | Runtime/PAK modding framework, not a save editor | — | 6 stars, 205 commits | Nothing about saves |
| sinbad/SPUD https://github.com/sinbad/SPUD | The upstream UE persistence plugin the format is built on | — | — | Defines the format but has no tooling |
| Nexus | The Nexus mod pages returned 403. Earlier notes (prior quest_mechanics.md) found no world-progress or quest-reset mods on https://nexusmods.com/runescapedragonwilds/mods/top. Shockbyte's guide mentions an unnamed "Dragonwilds Save Editor" for difficulty only and warns of "future issues or corruption" (https://shockbyte.com/help/knowledgebase/articles/how-to-change-your-runescape-dragonwilds-server-difficulty-world-settings). | — | — | No |

A GitHub repo search for "dragonwilds" returned 257 repos. Many are SEO/trainer spam (for example "…Mythic Loadout Trainer God Mode"), which should **not** be downloaded. No other world-progress editor turned up. GitHub code search needs a login, so unindexed code may exist [U].

**Bottom line [C]: no public tool edits WorldProgressManager, boss-defeat or world-hook state.** The only quest-adjacent world values any tool can edit are the uint8 switch and altar flags, through Ooga's generic Advanced view.

## 2. How well the SPUD format is understood

- **Upstream spec [C].** `SpudData.h` (https://github.com/sinbad/SPUD/blob/master/Source/SPUD/Public/SpudData.h) defines:
  - IFF chunks (4-char magic plus u32 length): SAVE, INFO, CINF, GLOB, META (CNIX class names, PNIX property names, CLST/CDEF class definitions), GOBS, LVLS, LEVL, LATS, SATS, DATS, NOBJ, SPWN, KILL, CORA, PROP, CUST.
  - `FSpudPropertyDef {u32 PropertyID, u32 PrefixID, u16 DataType}`.
  - PROP = `TArray<u32> offsets` + `TArray<u8> data`.
  - Storage types: 0–9 scalars, 20 vector, 21 rotator, 22 transform, 23 guid, 29 custom struct, 30 string, 31 name, 32 text, 64 opaque record, ArrayOf = 0x1000.
  - Property docs: https://github.com/sinbad/SPUD/blob/master/doc/props.md; overview: https://github.com/sinbad/SPUD/blob/master/doc/tech.md
- **Checksums and compression: none [C].** The header says only "Total Data Length (uint32) (validation check…)". Confirmed locally: the files are uncompressed, and the SAVE length matches the file size. The only integrity requirement is keeping every ancestor chunk length correct, plus the PROP offset table.
- **Dragonwilds deviations [C]** (Ooga README and haithem guide):
  - Extra header bytes on LEVL, NOBJ, SPWN and INFO (`0a 02 00 00 f9 03 00 00`, engine versions, spawn transforms). Ooga finds the child start by searching for the offset from which child chunks chain exactly to the parent's end.
  - CDEFs are wrapped in `CDVE` (1-byte header).
  - `GLAI` and `LVNI` level-index chunks.
  - Type **40** = nested component (ClassID plus its own offsets/data block).
  - Array counts are **u16**.
  - Inventories are JSON strings inside components.
- **Round-trip-safe parser/writer [C/I].** Ooga's `spud.js` (about 180 lines) plus `model.js` (about 450 lines) keep unknown bytes verbatim and rebuild lengths and offsets. That README claim is plausible, and the read side reproduced cleanly in Python here. Its write path has not been independently verified [U]. Haithem's parser is offset-patching only.
- **Property storage [C].** Each level (and GLOB) has its own META. Objects reference a ClassID into that level's CNIX, and the CDEF lists `(PNIX id, prefix id, type)` in PROP-offset order, so class IDs are **per level**. Struct members appear flattened with a prefix (e.g. `SwitchState/SwitchPosition`). Type-64 OpaqueRecords hold **UE tagged-property serialization** (`"TagName" "NameProperty" … "None"`), which neither Ooga nor haithem decodes generically. Ooga hand-codes one of them (the difficulty record).

## 3. How quest-related world state is represented (decoded read-only)

**`/Script/Dominion.WorldProgressManager`.** A single NOBJ in L_World (`WorldProgressManager_UAID_CC96E50CAECD7B3102_1790058889`, the same name in both worlds) [C]. CDEF fields: `WorldHooksTriggered` (64), `DefeatedBossesInternalNames` (64), `TaggedWorldProgressValues` (64), `bCanBeDamaged` (uint8).

Layout of the type-64 payloads, as seen in `World A.sav` [C]:
- `WorldHooksTriggered`: `u32 0, u32 count, FString[count]`, holding asset paths `/Game/Gameplay/World/WorldHooks/VelgarFlyover/WH_TempleFlyover.WH_TempleFlyover`, `…/DA_WH_VelgarsWrath…` and `…/WH_FellhollowFlyover…`.
- `DefeatedBossesInternalNames`: `u32 0, u32 2, "ai_boss_velgar", "ai_boss_imaru"`.
- `TaggedWorldProgressValues`: `u32 0, u32 2`, then per entry `"TagName" "NameProperty" u32 0 u32 size u8 0 FString(tag) "None"` followed by a 4-byte value. The tags are `WorldProgress.Imaru.CanSpawnImaru` and `WorldProgress.Imaru.PendingSealDoor`, both with value bytes 0 [C]. Whether the value is an int or a float is [U].
- In `World B.sav`, all three fields are `u32 0, u32 0` (empty) [C].

So these are simple length-prefixed lists. Removing an entry changes the PROP length, which means fixing the PROP offsets plus the PROP, NOBJ, LATS, LEVL, LVLS and SAVE lengths, which is exactly what Ooga's `patchBlock` does.

**Other world-side state:**
- **`/Script/Dominion.WorldEventManager`** (L_World): a tagged list with `WorldEvent.Dragon.Velgar` and `WorldEvent.Dragon.Imaru`, each followed by an 8-byte value that looks like a timestamp or cooldown [C strings; meaning I].
- **`/Script/Dominion.CachedCharacterStates`**: a type-64 tagged array of `{CharacterGuid (DomCharacterGuid struct), State (full character JSON string)}`, written in UE5.4+ tagged format with full type paths [C]. Only the guest "GuestChar" is cached. **This is the only place character quest-bool names (GhostCathanVisible, SealsBroken, LearnedAboutFragments…) occur in the .sav** [C]. No world object uses those names as properties.
- **Switch-type actors** (`SwitchState/ServerTimeOfInteraction` float, `SwitchState/SwitchPosition` uint8) [C]:
  - `BP_BinaryLever_DR` ×30: 27 at 1, 3 at 0
  - `BP_Seal_Switchable` (L_World, DeathQuest_Fellhollow): 0
  - `BP_Statue_InfrontOfBarrier_Switchable_{Armadyl,Guthix,Saradomin,Zamorak}`: Guthix=1
  - `BP_DragonImaru_SpawnTrigger`: SwitchPosition 0 and time 4807.6, plus `SavedDeactivationDelayRemaining` -1.0
- **Chests** (`BP_DR_BuriedChest` ×25, `BP_BuriedLever_DR`, `BP_BuriedChest_*`): `ChestType`, an `InventoryComponent` JSON, `RespawnTimerInGameTimeStartTicks`, `ChestState` (0/1/2) and `bRespawnDisabled` [C].
- **`BP_BossAltar_Region1.bSummoned`** (uint8, 0) [C].
- **No per-actor quest state.** These all store only `bCanBeDamaged=1` [C]:
  - every quest NPC: WiseOldMan_{FTUE,Village,ExitGF,VelgarLair,Dowdun}, Doric_{FTUE,_, Dowdun, Fellhollow}, GhostCathan_{Quest,Fellhollow,DRGate}, RestlessGhost*
  - `BP_NPC_Dreamstone_Dowdun`, `BP_NPC_DreamingStone_Fragment` ×9, `BP_NPC_LibraryBook` ×9, `BP_NPC_Library_Barrier_Dowdun`, `BP_NPC_Bastion_Barrier_Dowdun`, `BP_NPC_Seal_NecromanticFocus` ×3
  - `BP_SwitchableDoubleDoor_2_DR` ×46, `BP_SwitchableStatueDoor_DR`, `BP_EnergyBarrier` ×7, `BP_FinalDoor_vault*`
  - all `BP_InteractablePlayerTeleporter_RequiresQuestStep_*` (DR_Portal ×18, DowdunGateway, DeathsTemple, ScornedWilderness)
  - [I] Their visibility and interaction are therefore driven at runtime by the **character's** quest vars, not by world data. CORA (transform) is stored too, but these appear to be placed level actors.
- **Destroyed actors (DATS)** in World A: 10 entries, all breakable walls (`BP_Breakable_Vault_Wall` ×6, `BP_Breakable_Wall` ×2, `BP_Breakable_DK_Wall`, a StaticMeshActor). No quest actors [C].
- **No PlayerHooks, no QuestId keys** and no Titan/Gatekeeper/Black Knight classes or strings in either world [C]. `Progress.PlayerHooksTriggered` is character-side.

## 4. Experience reports

- **World-progress editing:** no report found of anyone editing WorldProgressManager, respawning a quest boss, or resetting a dungeon or quest NPC by world-save editing [C absence, from GitHub, web, Steam search and Nexus (blocked)].
- **Failure and corruption precedent for world edits:**
  - haithem BUGS #001 (ownership broken after the 2-byte mode flip).
  - The haithem guide warns that the game "may prune data it doesn't recognize", that a stale SpudCache can shadow edits ("clear SpudCache/ after external edits"), and that you must not edit while the game runs (https://github.com/haithemobeidi/RSDragonWilds-WorldEditor/blob/main/docs/DRAGONWILDS_SAVE_FORMAT_GUIDE.md).
  - General corruption and fix posts: https://thegeekpage.com/fix-runescape-dragonwilds-world-save-corruption-and-crashes/ and https://respawnhost.com/en/news/runescape-dragonwilds-1-0-1-save-fixes-jump-attack/
- **Character-JSON-only quest fixes have worked** (Wise Old Man, Restless Ghosts), per the prior notes.
- **In-game routes:**
  - Boss rematches exist: the Velgar Challenge Horn at the Dragonkin Altar (https://allthings.how/runescape-dragonwilds-inside-the-velgar-fight-and-its-dragon-slayer-rewards/); Imaru by re-collecting three curse fragments (https://games.gg/runescape-dragonwilds/guides/runescape-dragonwilds-soul-eater-imaru/); a Black Knight Titan Seal appearing 55 s after the kill (https://gamever.io/knowledge-base/every-dragonwilds-boss-compared-weaknesses-immunities-and-what-to-bring). These are community guides [C quote; reliability I].
  - "Boss defeats are world state" (same gamever page).
  - No official quest or dungeon reset found.
  - **A new world (or the near-empty `World B.sav`) is the clean in-game route.** World B has an empty WorldProgressManager, no Dowdun Reach cells, and no Titan state [C], so a character-only revert has no world state to conflict with there.

## 5. Effort and risk

**(a) Read-only display in the Python GUI: low effort, low risk.**
- About 200–300 lines of stdlib Python, roughly a day:
  - chunk walker with the "chain-to-end" header detection
  - META/CDEF/PNIX decode
  - PROP decode, including type 40 components and u16 arrays
  - two small type-64 readers: the FString list, and the tagged list for `TaggedWorldProgressValues` / `WorldEventManager`
- The prototype written for this survey (run via stdin) already does all of it apart from the tagged-list reader. The type-64 layouts above were read from hex dumps.
- Show: defeated bosses, world hooks, progress tags, lever/seal/statue positions, BossAltar `bSummoned`, chest states, and the cached guest characters.
- Risk: only a parse failure on future layouts, which should be handled by failing soft.

**(b) Safe editing of specific flags: medium effort, medium-high risk.**
- *Same-size edits* (`SwitchPosition` 0↔1, `bSummoned`, `ChestState`) are in-place byte flips with no length changes. Easy to implement (about half a day on top of (a)), but the game semantics are unknown [U]. Example: setting a lever to 0 may not re-close a door whose open state is also derived from the character quest.
- *List edits* (removing `ai_boss_imaru`, a hook, or a `WorldProgress.*` tag) change sizes. They need Ooga-style `patchBlock` (rewrite the PROP offsets, then about 6 ancestor lengths) plus whole-file rebuild and validation. That's about 1–2 days including a verify-by-reparse plus byte-identical round-trip test.
- Unknown [U] whether removing a boss name actually respawns the boss, or whether CanSpawnImaru, PendingSealDoor and the Imaru spawn trigger also have to change together.

What could go wrong:
- SpudCache shadowing (`Saved\SpudCache\*.lvl` must be deleted).
- The game overwrites the file on quit if it is running.
- `.sav.backup` mismatches.
- Steam Cloud conflicts.
- The game pruning or regenerating state on next save.
- Per-level class IDs (never copy records between levels).
- Format drift (Ooga already needed an Oct-2026 layout fix).
- Desync with the character quest vars causing soft-locks.
- No public test corpus for progress edits.
- Porting JS to Python: the `findChildStart` 0–512-byte pad search must be reproduced exactly, or nested headers misparse.

---

## Stub verification (data\world_quest_stubs.json)

Read-only peek at both saves. In this table, "Tool" means whether an existing tool can read or edit it.

| Stub id | (a) In world .sav? | (b) Tool | (c) Effort / risk to edit |
|---|---|---|---|
| **bkf_barrier** | **Not as state.** `BP_NPC_Bastion_Barrier_Dowdun_C` (World A, cell X17_Y4) stores only `bCanBeDamaged=1`. Of the other DR mechanisms, `BP_SwitchableDoubleDoor_2_DR` ×46 has no state, and `BP_BinaryLever_DR` ×30 has `SwitchState/SwitchPosition` (27 at 1). The `BP_InteractablePlayerTeleporter_RequiresQuestStep_DowdunGateway` has no state; the class name says it is gated by quest step. [C] → the barrier is open/closed by the character's `GateOpen` [I]. World B has no DR objects. | Ooga Advanced can view the actors and edit lever `SwitchPosition`. | Barrier: nothing to edit (character-only revert should suffice) [I]. Levers: trivial byte flips, but which lever belongs to which step is unknown → medium risk. |
| **bkf_dreamstone_actor** | **No state.** `BP_NPC_Dreamstone_Dowdun_C` (X17_Y4): only `bCanBeDamaged` [C]. Repaired/broken is presumably derived from `FixedDreamstone` (character) [I]. | View only (Ooga) | None needed [I]. |
| **bkf_shard_pickups** | **No collected state found.** `BP_NPC_DreamingStone_Fragment_C` ×9 NOBJ records with no state; they are not in DATS/KILL (DATS holds only breakable walls) [C]. 9 records vs 13 shards suggests some are in cells not saved/streamed, or are spawned differently [U]. Pickup visibility is likely driven by character `Fragment_N` / `QuestLocations` `DR_MQ_Fragment_N` [I]. | View only | Probably character-side. Re-enabling the shard hunt = clearing character vars [I]; untested. |
| **bkf_titan** | **Not present.** No Titan / Gatekeeper / BlackKnight class or string in either save. `DefeatedBossesInternalNames` contains only `ai_boss_velgar`, `ai_boss_imaru` [C] (consistent with step 7 not yet done). Whether a Titan kill is ever written there is [U] (the internal name would presumably be `ai_boss_*`). Community guide: Titan re-summonable via a Titan Seal after a kill [C quote]. | None | n/a now. If later needed: a list edit (see §5b), medium/high risk. |
| **bkf_bastion_entry** | **No world counterpart found.** No `CanEnterBastion`/`Bastion` property; the only Bastion object is the stateless barrier NPC [C]. | — | Character-only [I]. |
| **bkf_npc_positions** | **No dialogue/position state.** Each NPC "position" is a **separate placed actor class** (WiseOldMan_FTUE/Village/ExitGF/VelgarLair/Dowdun; Doric_FTUE/_/Dowdun/Fellhollow; GhostCathan_Quest/Fellhollow/DRGate), each with only `bCanBeDamaged` plus a CORA transform [C]. So "where the NPC is" = which variant is shown, presumably chosen from character quest vars [I]. | View only | None needed [I]; low risk from the world side. |
| **bkf_reward** | Character-side, as the stub says. Nothing in the world [C absence]. | — | — |
| **ds_velgar** | **Confirmed.** `WorldProgressManager.DefeatedBossesInternalNames` contains `"ai_boss_velgar"` (World A only). Related state: `WorldHooksTriggered` (3 VelgarFlyover hooks), `WorldEventManager` tag `WorldEvent.Dragon.Velgar` plus an 8-byte value, and `BP_BossAltar_Region1.bSummoned=0` [C]. | Ooga: view as opaque bytes, no edit. Nobody decodes it. | List edit, about 1–2 days. Effect of removal unknown [U]; the in-game Challenge Horn rematch is the safer route. |
| **ds_temple** | **No world mirror.** `WOMTempleHidden` and `VaultGoblinVisible` occur only inside `CachedCharacterStates` (the guest's JSON) [C]. `BP_NPC_WiseOldMan_*` actors are stateless. | — | Character-only [I]. |
| **wh_imaru** | **Confirmed.** `"ai_boss_imaru"` is in DefeatedBossesInternalNames. `TaggedWorldProgressValues` holds `WorldProgress.Imaru.CanSpawnImaru` and `WorldProgress.Imaru.PendingSealDoor` (value bytes 0). `BP_DragonImaru_SpawnTrigger_C` (cell X33_Y35) has `SwitchPosition=0`, `ServerTimeOfInteraction=4807.6`, `SavedDeactivationDelayRemaining=-1`. `WorldEvent.Dragon.Imaru` is in WorldEventManager [C]. | View only (opaque) | Coupled state across 3 objects → high risk. Rematch is reportedly possible in game by re-collecting the curse fragments. |
| **wh_seals** | **Partly.** `BP_Seal_Switchable_C` (L_World, DeathQuest_Fellhollow) has `SwitchState/SwitchPosition=0`, in both saves. `BP_NPC_Seal_NecromanticFocus_C` ×3 are stateless. The broken count lives in the character (`SealsBroken`, `WaterfallSealBroken`) [C]. | Ooga Advanced can edit `SwitchPosition` | Byte flip is easy; semantics unknown [U]. |

**World-side quest-adjacent state the stubs missed [C]:**
- `WorldProgressManager.WorldHooksTriggered` (VelgarFlyover hooks: `WH_TempleFlyover`, `DA_WH_VelgarsWrath`, `WH_FellhollowFlyover`).
- `/Script/Dominion.WorldEventManager` dragon event tags (`WorldEvent.Dragon.Velgar` / `.Imaru` plus timestamps).
- `BP_BossAltar_Region1.bSummoned`.
- `BP_DR_BuriedChest` ×25 and `BP_BuriedLever_DR` chest/respawn state (`ChestState`, `bRespawnDisabled`; one ChestType=2 chest has `bRespawnDisabled=1`, likely a quest chest [I]).
- `BP_Statue_InfrontOfBarrier_Switchable_*` (Guthix=1).
- `BP_DragonImaru_SpawnTrigger`.
- `CachedCharacterStates` (a guest's full character, which could re-sync).
- `BP_InteractablePlayerTeleporter_RequiresQuestStep_*` actors exist but are stateless.

**Net finding for the BKF step 7→6 revert [I, strong]:** the world save holds no per-step BKF state. The barrier, Dreamstone, fragments, NPC variants and teleporters are all stateless placed actors, and the Titan has no record yet. The character-only revert should therefore be consistent with either world. World B has no DR state at all.
