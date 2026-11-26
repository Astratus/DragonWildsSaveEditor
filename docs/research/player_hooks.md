# PlayerHooks and the main questline (AI reference)

Written 2026-11-25. Source: RSDWArchive 1.0.2.0 datamine (`RSDragonwilds/Content/Gameplay/Character/Player/PlayerHooks/...`), the quest flows, level cells of `L_World`, the Dragonwilds wiki and the order of hooks in real saves. The raw downloads were working files and are not included.

## What a hook is

- The save list is `GameProgress.Progress.PlayerHooksTriggered`: 22-char PersistenceIDs, appended in firing order (the built unlock-name catalog (section `PlayerHooksTriggered`) maps them to names).
- The native `PlayerHooksSubsystem` (usmap names: `PlayerHooksTriggered`, `PlayerHooksThatHaveYetToBeTriggered`, `bCanBeTriggeredMultipleTimes`) fires each hook once and records it. A hook asset with `bCanBeTriggeredMultipleTimes: true` fires every time, so its list entry blocks nothing.
- So for a one-shot hook, removing its ID is what lets it fire again. Removing an ID that is not there is a no-op.
- The region intros are `BP_PlayerHook_NarrativeIntro` assets. Each shows a `WBP_<Region>Intro` widget that plays a Bink movie (`BNK_FellhollowCinematic`, `BNK_DowdunCinematic`, `BNK_UmbralCinematic`, `BNK_ScornedWildernessIntro`).

## How the intros are triggered (what was and wasn't traced)

- No quest flow, teleporter BP, game-feature data or placed actor references the four region-intro hooks. I checked all quest flows, every `BP_InteractablePlayerTeleporter*` class, the DR/UmS/SW `GameFeatureData`, and 15 `L_World` cells holding teleporters and hook volumes.
- The three placed `BP_TriggerPlayerAndWorldHookVolume` actors (labels `EnterFellhollowPlayerHookTriggerVolume`, `EnterUmbralSandsPlayerHookTriggerVolume` and the temple one) set only a **WorldHook** (Velgar/Fellhollow flyover, Fuzan intro). Their `PlayerHook` property is empty, and world hooks live in the world `.sav`, which nothing here touches.
- `BP_PlayerController` has a native event `TryPlayFellHollowIntro` (DominionPlayerController), and the usmap has `PlayerHookToTriggerOnTeleport`, which no placed teleporter sets. So the call site is native code, not data. Region entry is the trigger, and the wiki confirms where it happens in each quest (below).
- **Untraced (native):** whether anything besides the hook list, such as map fog, also gates the replay. Removing the hook is necessary for a replay. It is not proven to be sufficient. It is harmless either way (a cosmetic cutscene), so it does not lower checkpoint ratings (see `rating_rule`).

## Main-quest hooks (used in `hooks_remove`)

| Hook | ID | Fires when | Main quest / step | Evidence | Confidence |
|---|---|---|---|---|---|
| PH_FellHollowIntro | `w7i9eEkrmS07OdumshFxiA` | First entry into Fellhollow | Withering Heights, after `wh_given` (TalkToWomNEGF) and before the cleansing pool. Fellhollow needs DS complete and WH started | One-shot NarrativeIntro asset, `TryPlayFellHollowIntro`. Wiki WH: "a small intro cutscene that plays when you first enter Fellhollow". Saves: absent in the v83 backup (DS beat 2), present before ImaruGaze in the live save | high |
| PH_DowndunReachIntro | `prbKS0g1X6EsOe6Lc17yAg` | Going through the ominous door into Dowdun Reach | BKF: after speaking to Cathan (`bkf_speak_wom`, objective _1). Wiki BKF: "Go through the open gateway and enter through the ominous door. Note: This will play a small intro cutscene to the area. You will then arrive within The Approach" | Asset, wiki, `QF_DR_MainQuest_Entry` EnterDRDoor (TriggerTeleporter). Live save: last entry, added after Imaru | high (see note) |
| PH_UmbralSandsIntro | `5m02BUYiuoWdqwaF4FH4_A` | Using the Bastion door into Umbral Sands | ILH: after `ilh_given` (EnterUmS, TeleportedIntoUmS absent). At `ilh_speak_garou_elder` the player is already inside | Asset; wiki ILH: "Interacting with the door to the Umbral Sands will play a small introduction cutscene to the region" | high |
| PH_ScornedWildernessIntro | `aLtQSklcimGNk0ydqGastg` | The Dragon Gate choice "[Journey to the Scorned Wilderness]" | Regicide: after `rg_access_sw`. The choice writes SpeakZilyana and then teleports, so the intro has played at `rg_speak_zilyana` | Asset; `QF_SW_MainQuest` Entrance_Teleport; wiki Regicide: "This will play the narrative trailer for the Scorned Wilderness" | high |

Note on `bkf_speak_wom`: the same record is also written by the `RegionEntry` flow if the player walks through the door before speaking to Cathan. On that path the intro has already played. The checkpoint follows the walkthrough order (Cathan first) and removes the hook, so the worst case is the cutscene playing once more. This is recorded in that checkpoint's `open_questions`.

## Hooks deliberately NOT touched

| Hook | Why |
|---|---|
| PH_NarrativeIntro `zEbE-Up0518eqo-MOwXAZw` | New-game intro, before First Steps. The tutorial quests are excluded from the line |
| FTUE folder (34 hooks, e.g. FirstNight, Stability, FirstEnteredHigherPowerLevelRegion) | Tutorial popups, not quest flow (user rule) |
| PH_ImaruGazeStage1-3 (`2iVmJ0pl…`, `XUONlkj2…`, `06O_ekhx…`) | FTUE notifications for the Fellhollow Soul Rift / Imaru's Gaze mechanic ("find a Purification Pool"). Fired by the soul-rift state, not a quest objective. They are tutorials, so they are left alone even though they first appear during WH. The trigger is native (untraced) |
| PH_MountUnlocked `4kHW30wP…` | FTUE popup on the first mount unlock (`QFT_UnlockMount`: side quest FH_WitherBeast, or ILH beats 3/4). Tutorial |
| PH_KuldraEndCinematic `0eyyXUpK…` | `bCanBeTriggeredMultipleTimes: true` (from BP_DragonKuldraHeart_ArenaLevelData). Plays every kill, so the list entry blocks nothing |
| PH_BossAltar_Region1 `raTo7knb…` | Repeatable text and journal hint at the boss altar ("perhaps a horn"). Blocks nothing |
| PH_ExitTempleOfSaradomin `KT6IL0MW…` | Soft-deleted (`bSoftDeleted`); an early-access tutorial |
| PH_AddCorruptCharacterReplacementItems `6iBD70mY…` | Corrupt-character recovery hook (clears and refills inventory). Never touch it |
| World hooks (WH_TempleFlyover, WH_FellhollowFlyover, DA_WH_VelgarsWrath, DA_WH_UmbralSands_FuzanIntro) | Live in the world `.sav` (`WorldProgressManager.WorldHooksTriggered`), which is out of scope |

## Per-checkpoint result

- `ds_*` (3) and `wh_given`: Fellhollow, Dowdun Reach, Umbral Sands, Scorned Wilderness
- `wh_after_pool` … `bkf_speak_wom`: Dowdun Reach, Umbral Sands, Scorned Wilderness
- `bkf_speak_doric` … `ilh_given`: Umbral Sands, Scorned Wilderness
- `ilh_speak_garou_elder` … `rg_access_sw`: Scorned Wilderness
- `rg_speak_zilyana`, `rg_prepare_raid`, `rg_bring_head`: none

No checkpoint rating changed. `rg_speak_zilyana` stays high. Its inference was reworded: the SW intro is now placed (it plays on the gate teleport, before this state), but the native code that records it is still untraced. One could argue it should be raised, since every revert to it comes from a save that has been on the island. That was left as an open decision.

Map fog (`RevealedFog`, `RevealedLandmarks`) is NOT touched by checkpoints. That is a separate optional feature.
