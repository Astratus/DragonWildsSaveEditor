# Real Dragonwilds character-save quest samples

Written 2026-11-24. Everything was read-only: the files were copied to `(working file, not included)` first. The data is in `(working file, not included)`: 5 distinct samples, with the main quests only and every QuestLocation.

The scripts are in `(working file, not included)`: `extract_quests.py`, `scan_zips.py` and `make_out.py`.

**What was excluded:** the edited test copies in the working folder (`gui_*`, `questtest`, `questgui`, `integ`, and `*.pyedit.bak`). They are outputs of our own editor, not genuine game states.

Quest IDs:
- DS: Dragon Slayer, `yrRZnkmro-IvH_OmZ3f-5A`
- WH: Withering Heights, `uftGB0es-CGrvXyPoxW31w`
- BKF: Black Knight's Fortress, `3MpWS0mD8A6yFVmjVAA2Qg`

QuestState values: 0 = not started, 1 = in progress, 2 = complete.

## Summary

| # | Sample | Ver / SaveCount | DS | WH | BKF | Tracked main |
|---|---|---|---|---|---|---|
| 1 | GuestChar (cached in `World A.sav`) | 86 / 759 | 2, QuestBeat 4 | **1, DeathQuest_Beat 4, SealsBroken 1** | 0 | (key absent) |
| 2 | the reference save | 86 / 1322 | 2, QuestBeat 5 | 2, Beat 5, SealsBroken 3, ImaruDefeated true | **1, QuestBeat 3** | BKF |
| 3 | the reference save's .backup | 86 / 1321 | same as #2 | same as #2 | same as #2 | BKF |
| 4 | the older (v83) reference save | 83 / 295 | **1, QuestBeat 2** | 0 | 0 | (key absent) |
| 5 | Public EA sample (public GitHub, Early Access 2025-07) | 56 / 49 | **1, QuestBeat 2** | record absent | record absent | (key absent) |

In every sample, the four earlier main quests (First Steps, Getting Started, Ratcatcher, Rune Mysteries) are state 2.

**Is any sample "seals broken, ready to challenge Imaru"? No.** The closest is #1: WH is in progress at DeathQuest_Beat 4, but with only 1 of 3 seals broken. No sample has SealsBroken 3 with ImaruDefeated absent.

## 1. GuestChar: WH in progress, Beat 4, 1 seal broken

- DS: state 2, objective `Return to the Wise old man after killing velgar`. Ints: `QuestBeat=4` (not 5, even though the state is 2). It has 31 bools.
- WH: state 1, objective `BreakRemainingtwoSeals`.
  - Ints: `DeathQuest_Beat=4`, `NotFoundStones=2`, `StandStoneInt=2`, `SealsBroken=1`.
  - Bools, all true: HasEnteredBefore, HasTriggeredSearchStructureVolume, SpokenToDeath, LearnedAboutFragments, AskedAboutDeath, AskedAboutFellhollow, AskedAboutWithering, AskedAboutUnderworld, HasSpokenToPostiePete, HasTriggeredFHTPVolume, HasUsedCleansingPool, HasTriggeredSSVol, SpokenToCathan, WaterfallStoneDone, FortressStoneDone, VillageStoneDone, InvestigatedStandingStones, WaterfallSealBroken.
  - Absent: SilverthornSealBroken, EmberwoodSealBroken, ImaruDefeated, and the crime/statue bools.
  - Oddity: `NotFoundStones=2` stays even though all three `*StoneDone` bools are true, so the game does not reset that counter.
- BKF: state 0, objective `None`, empty ints and bools. Icthlarin's Little Helper: state 0. There is no Regicide record.
- There is no `QuestTrackedMain` or `QuestTracked` key.
- 41 QuestLocations, of which these relate to WH:
  - True: NPCDeath, VillageArea, FortressArea.
  - False: DragonsLairCathanArea, EnterDeathsDomainTarget, DeathsTempleArea, PostiePeteTarget, EnterFHArea, CleansingPoolTarget, StandingStonesArea, StandStoneVillage, StandStoneWaterfall, StandStoneFortress, FallArea.
  - The last location is DR_SQ3_Dragon=false.
  - Absent: SlayImaruTarget, DeathTempleTarget and every `DR_MQ_*` location. Locations are appended lazily, the first time the game touches them.
- World-side context, from world_save_survey.md for the same `World A.sav`: `DefeatedBossesInternalNames` contains ai_boss_imaru (the world host killed her). `WorldProgress.Imaru.CanSpawnImaru`/`PendingSealDoor` = 0, and `BP_Seal_Switchable` = 0.

## 2 and 3. Reference save: WH complete, BKF in progress (Beat 3)

The live save (SaveCount 1322) and the .backup (1321) hold identical quest data.

- DS: state 2, same objective as #1. Ints: `QuestBeat=5`. It has 28 bools.
- WH: state 2, objective `ReturnToDeath`.
  - Ints: `DeathQuest_Beat=5`, `StandStoneInt=2`, `SealsBroken=3`. The `NotFoundStones` int is absent.
  - Bools, all true: the 18 listed for #1, plus SilverthornSealBroken, SpokenToSuspicious, LearnedCrime, LearnedMotive, SpokenToSnickering, SpokenToShady, ArmadylStatueSpokenTo, EmberwoodSealBroken, **ImaruDefeated**, HasRecievedImaruHead.
  - So a completed WH keeps the objective `ReturnToDeath` at Beat 5.
- BKF: state 1, objective `DR_Main_Objective_5`.
  - Ints: `QuestBeat=3`, `Shard_Amount=13`.
  - Bools that are true: GivenQuestOnLogin, RecievedDRQuestFromDeath, EnteredDRCathanCheck, SpokenToDoric, LearnedAboutInfernalFragments, SpokenToOldMan, WOM_Optional_1..4, Library_Book1..3, Library_Puzzle_Complete, SpokenToDreamstone, Fragment_1..13, SpokenToFishingGoblin, SpokenToMage, TakenGlassOwl, PlayerGivenFragmentMage, FishingGoblinShardGiven, SpokenToChef, PlayerGivenFragment_Chef, Fragments_All, GateOpen, FixedDreamstone.
  - Bools that are false: Library_Book4, Fragments_LessThan5, Fragments_LessThan10, Fragments_LessThan13.
- Icthlarin's Little Helper and Regicide: state 0.
- QuestTrackedMain = BKF. QuestTracked = `9Kod2UgSkm8YrJCwMgmAdQ`.
- 69 QuestLocations. The WH ones match #1, except that VillageArea and FortressArea are now **false**. The additions are:
  - PostiePete_LettersForTheDead: true.
  - SlayImaruTarget: false.
  - DeathTempleTarget: false.
  - DR_MQ_Doric: true.
  - DR_MQ_Cathan, DR_MQ_Death, DR_MQ_OldMan_Target, DR_MQ_DreamingStone and DR_MQ_Fragment_1..13: all false.

## 4. Reference save, older v83 copy: DS in progress, WH/BKF not started

- DS: state 1, objective `Investigate the castle`. Ints: `QuestBeat=2`. It has 11 bools.
- WH and BKF: state 0, objective `None`, empty ints and bools. There is no Regicide record and no tracked key.

## 5. Public EA sample (public, Early Access v56): DS in progress

- DS: state 1, objective `Investigate the castle`. Ints: `QuestBeat=2`. It has 11 bools.
- There are no WH or BKF records: that content predates the save.
- Source: a public GitHub repository holding an Early Access world save and its .backup (only the .backup has cached character state).

## What the other sources gave

- **A full manual snapshot of the reference saves**: byte-identical to the live files.
- **Steam userdata**: there is no `1374490` folder for either Steam account (678383161, 97981249), so there are no cloud copies.
- **The reference player's world saves**: `World B.sav` and its backup contain no cached character state.
- **Public repos**: zips were downloaded via codeload and scanned without extracting. These had no sample saves with quest data:
  - TatsumaYakoshi/DragonWilds-Ultra, which has no sample save at HEAD
  - OogaBoogaCode/RSDWSaveEditor
  - RSDWArchive/RSDWTools
  - Elleandria
  - KevinStillman
  - BirdRa1n
  - xxmowgli
  - B1GM4NT1NGS
  - WyrmViceHack
- **haithemobeidi**: `scripts/structure_research/{A..E}.sav` contain the CachedCharacterStates class name but no embedded character JSON.
- **Web**: searching for "DeathQuest_Beat" OR "SealsBroken" found no posted save JSON.
- **Logs** (`Saved\Logs\*.log`): they do **not** record quest variables, quest-state changes or beats. Quest-related content in them is limited to:
  - `LogCommonConversationRuntime: ClientUpdateConversation:` dialogue lines, with timestamps.
  - Rare `SetQuestObjective()` warnings, only for missing objective text (e.g. `DR_SQ2_FindMasters_NoInfo`).
  - `LoadStateFromJson() : Unknown Actor Class in ActorsInteractedWith entry` for `BP_Seal_Switchable_C` and `BP_NPC_Seal_NecromanticFocus_C`. This means the character JSON's ActorsInteractedWith holds seal actors.
  - The Imaru timeline in `RSDragonwilds-backup-2026.11.22-07.22.26.log` (2026-11-21), which shows the order of play but not the variable values:
    - 19:43: crime verdict dialogue
    - 19:46–19:47: shrine repaired
    - 19:54:56: last curse cleansed
    - 19:55:00: "Your soul resonates with Imaru's grief. You are ready to bring the fight to her."
    - 20:30:34: "Unleash the curse … and face Imaru?"
    - 20:31–20:57: Imaru combat
    - 21:02:18: "Imaru the devourer is dead…"
