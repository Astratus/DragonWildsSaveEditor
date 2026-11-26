# Dragonwilds main questline: wiki steps mapped to character-save variables

Save analysed: `the reference save` (v86, SaveCount 1322). The `.backup` quest data is identical. The `.83.verbackup` (SaveCount 295) is the older comparison.
Machine-readable copy: `main_quests.json` (same folder).

## Sources

- Wiki (story steps, NPCs, rewards):
  - https://dragonwilds.runescape.wiki/w/List_of_quests
  - https://dragonwilds.runescape.wiki/w/Quests
  - https://dragonwilds.runescape.wiki/w/Dragon_Slayer
  - https://dragonwilds.runescape.wiki/w/Withering_Heights
  - https://dragonwilds.runescape.wiki/w/Black_Knight%27s_Fortress
  - https://dragonwilds.runescape.wiki/w/Transcript:Black_Knight%27s_Fortress
  - https://dragonwilds.runescape.wiki/w/Titan%27s_wrath
  - https://dragonwilds.runescape.wiki/w/Icthlarin%27s_Little_Helper
  - https://dragonwilds.runescape.wiki/w/Regicide
- Datamine of game files v1.0.2.0 (variable names and values, objective keys, quest-flow graphs). This is the authoritative source for the variable mapping:
  - RSDWArchive QuestData.json: https://raw.githubusercontent.com/RSDWArchive/RSDWArchive/main/website/tools/QuestData/QuestData.json
  - BKF flow graphs: https://github.com/RSDWArchive/RSDWArchive/tree/main/1.0.2.0/json/RSDragonwilds/Plugins/GameFeatures/DowdunReach/Content/Gameplay/Quests/Main (`QF_DR_MainQuest_*.json`, `QF_DR_Main_Cathan.json`)
  - Objective text table: same folder, `ST_DR_Main.json`
- Broader search, per the coordinator's request:
  - GitHub repos found via the API: https://api.github.com/search/repositories?q=dragonwilds+save
  - GitHub code search needs authentication. `gh` is not installed and the unauthenticated API was rate-limited, so `QuestBeat`, `QuestBools` and similar terms could not be code-searched.
  - Web search found no Reddit, Steam or Nexus page that documents QuestBeat values.
  - The only public manual quest-edit guide found is https://www.gamepressure.com/newsroom/how-to-fix-missing-wise-old-man-bug-in-runescape-dragonwilds/z27d52. It covers Dragon Slayer only: set QuestState 1, QuestObjective "Find and hunt a deer", and add the bool WOMTempleHidden=true.
  - RSDWTools' quest editor (local copy in `(working file, not included)`) can only mark a whole quest complete (QuestState 2), or delete its row and QuestLocations entries. It has no per-step editing.
  - The other editors (Elleandria, KevinStillman, haithemobeidi, TatsumaYakoshi, Nikolaj-I-M, MyNameIsGlooboo) are inventory, skill or world editors. No quest-step logic was found in the local copies.
  - Caution: two "Save Backup Manager" repos (WyrmViceHack, Mightystream) have identical boilerplate descriptions and ship packaged releases. Treat them as untrusted.

### Mechanics confirmed from the flow graphs

- `QFT_ModifyQuestInt` with no `ModifierOperator` **sets** the value. `EQuestIntModifyOperator::ADD` adds; it is used for `Shard_Amount`.
- `TestQuestInt` with no TestValue tests for **0**.
- A bool that has never been set is simply absent, which reads as false.
- `QFT_UpdateQuestLocation` writes `QuestLocations[{QuestLocationId, QuestLocationsState}]`. `Revealed:true` gives true; no Revealed gives false.
- `QuestObjective` holds the objective **key**. For BKF that is e.g. `DR_Main_Objective_5`. Older quests use the dev text directly as the key, e.g. Dragon Slayer.

## 1. Main questline order (9 primary quests)

Order is from https://dragonwilds.runescape.wiki/w/List_of_quests. IDs and internal names are from QuestData.json.

| # | Quest | QuestId | internal | Current QuestState | v83 QuestState |
|---|---|---|---|---|---|
| 1 | First Steps | luaLQEzPXjx9_ICiz5zkNg (+AmuXOU…, v9LCTE…, 7i8X40…) | ftue_fs2 | 2 | 2 |
| 2 | Getting Started | xa8o60AbJZ23FymQeiH3bg | ftue_rtftj | 2 | 2 |
| 3 | Ratcatcher | SDcUrkVqRiTKKEyzEh5DWw (+4lW6rU…) | ftue_rc | 2 | 2 |
| 4 | Rune Mysteries | TgVnb0NCLvmEVRed59IgsQ (+zrqqFU…, EWRW7U…) | ftue_rm_prt1 | 2 | 2 |
| 5 | Dragon Slayer | yrRZnkmro-IvH_OmZ3f-5A | dragon_slayer | 2 | 1 (QuestBeat 2) |
| 6 | Withering Heights | uftGB0es-CGrvXyPoxW31w | DeathQuestMain | 2 | 0 |
| 7 | **Black Knight's Fortress** | 3MpWS0mD8A6yFVmjVAA2Qg | Quest_DR_Black_Knight_Fortress | **1** | 0 |
| 8 | Icthlarin's Little Helper | kPtTW0exXrqw2BqELR_bFA | UmS_MainQuest | 0 | (absent) |
| 9 | Regicide | Nw3wiUaB8siRIN2bStWJmw | SW_MainQuest | 0 | (absent) |

`import.js` also maps kPtTW0… to `t-fuzan-trials`. The datamine says it is ILH. Fix the slug map.

## 2. Black Knight's Fortress: the reference player's current quest

Wiki: https://dragonwilds.runescape.wiki/w/Black_Knight%27s_Fortress

- **NPCs:** Death, Cathan, the Wise Old Man, Doric, the Dreaming Stone (Avisk), Spittletoe and Snotpit, Valerius, Offalfoot, and the Black Knight Titan (Lord Rasmodel).
- **Key items:** 13x Shard of the Dreaming Stone (`hJyKREoYCuSo8E20uZBB9g`), Glass Owl, Unusual Trout, Maple Toastie and its recipe, and Broken Titan's Wrath (`B_9Rt0HRTRhbZfSgUrQNTg`, dropped by the Titan).
- **Rewards:** the BKF reward pack (Tome of the Titan and Titan's Wrath) and the Titan's Wrath recipe (https://dragonwilds.runescape.wiki/w/Titan%27s_wrath, `PzF6r0v9aps3QVSoWKGy0A`). Completion auto-starts ILH.

Objective text comes from `ST_DR_Main.json`. The flow logic comes from the QF files listed under Sources.

| Step | Objective key → text | QuestBeat | Bools/ints set by this step | QuestLocations | Flow file | Conf. |
|---|---|---|---|---|---|---|
| 0 | `DR_Main_Objective_-1` "Speak To Death" | (absent=0) | GivenQuestOnLogin | | QF_DR_Main_ProvideQuestOnStart | high |
| 1 | `DR_Main_Objective_0` "Speak to Cathan at the eastern gates in Fellhollow" | 0 | RecievedDRQuestFromDeath | DR_MQ_Cathan=true | QF_DR_MainQuest_Entry / QF_Death_PostQuestDialogue | high |
| 2 | `DR_Main_Objective_1` "Speak to the Wise Old Man In Dowdun Reach" | **1** (set on region entry or talking to Cathan) | EnteredDRCathanCheck | DR_MQ_Cathan=false, DR_MQ_OldMan_Target=true | QF_DR_MainQuest_Entry, QF_DR_Main_Cathan | high |
| 3 | `DR_Main_Objective_2` "Speak to Doric in Dowdun Reach" | 1 | SpokenToOldMan (WOM_Optional_1-4 = optional chat) | DR_MQ_OldMan_Target=false, DR_MQ_Doric=true | QF_DR_MainQuest_OldMan | high |
| 4 | `DR_Main_Objective_3` "Investigate the Dreaming Stone" | 1 | SpokenToDoric (LearnedAboutInfernalFragments comes from Doric's chat) | DR_MQ_Doric=false, DR_MQ_DreamingStone=true | QF_DR_MainQuest_Doric | high |
| 5 | `DR_Main_Objective_4`…`_4_12` "Collect the Shards…: k/13" | **2** (set on the first stone talk) | SpokenToDreamstone; each shard sets Fragment_N=true and Shard_Amount +1; Fragments_LessThan5/10/13 track progress | DR_MQ_DreamingStone=false; DR_MQ_Fragment_N=true, then false when collected | QF_DR_MainQuest_Dreamstone, QF_DR_MainQuest_Fragments, side NPC flows | high |
| 6 | `DR_Main_Objective_4_13` "Return to the Dreaming Stone" | 2 | Fragments_All=true, LessThan*=false, Shard_Amount=13 | DR_MQ_DreamingStone=true | QF_DR_MainQuest_Fragments (CheckAmount) | high |
| **7 (current)** | `DR_Main_Objective_5` **"Defeat the Gatekeeper"** | **3** | Stone takes 13 shards; sets GateOpen and FixedDreamstone; CanEnterBastion is set on first use of the Bastion barrier | DR_GateKeeper=true, DR_MQ_DreamingStone=false | QF_DR_MainQuest_Dreamstone; barrier in QF_DR_MainQuest_Gatekeeper | high |
| 8 | `DR_Main_Objective_6` "Return to the Dreaming Stone" | **4** | GatekeeperDefeated (the Titan drops Broken Titan's Wrath) | DR_GateKeeper=false, DR_MQ_DreamingStone=true | QF_DR_MainQuest_Gatekeeper (GatekeeperDead) | high |
| 9 | (complete) | 4 | Requires Broken Titan's Wrath in inventory. Gives the reward pack and the Titan's Wrath recipe. QuestState=2. Starts ILH. | DR_MQ_DreamingStone=false | QF_DR_MainQuest_Dreamstone | high |

Notes:

- `Shard_Amount==13` (the quest int) is what unlocks the repair dialogue. Inventory shards are only removed by the repair (`TakeItemAmountFromPlayer 13`), not checked.
- A guard exists: if the beat is still 0 when you talk to Doric, the Fragments flow sets `QuestBeat=-1` with objective `DR_Main_Objective_4_-1` "Speak to Doric about the shards".

### Current BKF save values

v83 had the quest at QuestState 0 with no variables.

- **Ints:** QuestBeat=3, Shard_Amount=13.
- **Bools set true:** GivenQuestOnLogin, RecievedDRQuestFromDeath, EnteredDRCathanCheck, SpokenToDoric, LearnedAboutInfernalFragments, SpokenToOldMan, WOM_Optional_1-4, Library_Book1-3, Library_Puzzle_Complete, Fragment_1..13, SpokenToDreamstone, SpokenToFishingGoblin, SpokenToMage, TakenGlassOwl, PlayerGivenFragmentMage, FishingGoblinShardGiven, SpokenToChef, PlayerGivenFragment_Chef, Fragments_All, GateOpen, FixedDreamstone.
- **Bools set false:** Library_Book4, Fragments_LessThan5/10/13.
- **Absent:** CanEnterBastion, GatekeeperDefeated.
- **Inventory and unlocks:**
  - No Broken Titan's Wrath has ever been picked up (it is not in ItemsPickedUp).
  - The Titan's Wrath recipe is not unlocked.
  - No shards are currently in the inventory.

**Position:** step 7. The stone is repaired and the barrier is down, but the reference player has never gone through the Bastion barrier and the Titan is alive.

## 3. Dragon Slayer (complete)

Wiki: https://dragonwilds.runescape.wiki/w/Dragon_Slayer

Beat setters come from QuestData.json (flows QF_DragonSlayer_Beat1-5). The objective strings are the dev text itself.

| Wiki step | QuestBeat | QuestObjective (save) | Bools | Conf. |
|---|---|---|---|---|
| Build shelter, claim bed roll | 1 | "Claim a bed" → "Return to the Wise old man after claimed bed" | HasBed | med |
| Hunt deer for antlers (Tome of Construction Vol 1) | 1 | "Find and hunt a deer" | HasCompletedHuntDeerStep, CompletedBeat1 | med |
| Investigate Keep of Blue Flames | 2 | "Investigate the castle" (**v83 save is here**) | VaultGoblinVisible, HasChoseTellMeAbtAdventurer | high |
| Vault (Spitfoot), return to WOM, venture into Ghornfell (reward pack Beat2) | 2→3 | "Locate cathan in the vault" / "Return to the Wise old man" / "Venture into Ghornfell" | KnowVelgar, HasCastleRecipePiece, LearnedAboutDragonkin, HasAntiDragShieldRecipe, HasSpokeToGolbin, HasSwampRecipePiece, CompletedBeat2, HasEnteredGhornfell | med |
| Cathan's ghost at Velgar's Rise, craft challenge horn | 3→4 | "Look for evidence of Cathan at the tower" / "Craft the summon horn" | GhostCathanVisible, HasSummonHornRecipe, FoundBloodWoodSap, FoundDragonTooth, CompletedBeat3 | med |
| Challenge and kill Velgar | 4→5 | "Challenge Velgar" | CompletedBeat4, HasEverRecievedDragonHead | med |
| Return head to WOM (reward pack Beat5) | 5 | "Return to the Wise old man after killing velgar" (**current**) | QuestState 2 | high |

## 4. Withering Heights (complete)

Wiki: https://dragonwilds.runescape.wiki/w/Withering_Heights

- **Beat int:** `DeathQuest_Beat`. Current values: 5, SealsBroken 3, StandStoneInt 2, objective "ReturnToDeath".
- **Beats:**
  - 1-2: TalkToWomNEGF, SearchTheStructure, SpeakToPostiePete, UnlockGate
  - 3: FindACleansingPool
  - 4: InvestigateStandingStones
  - 4-5: BreakTheThreeSeals → ChallangeImaru
  - 5: ReturnToDeath, then complete
- **Rewards:** Withering Heights reward pack and the dragoncurse shield recipe.
- **Confidence:** med.

## 5. ILH and Regicide (not started)

ILH: https://dragonwilds.runescape.wiki/w/Icthlarin%27s_Little_Helper

- Beat int `DT_QuestBeat`, 1-6.
- Objectives: EnterUmS, LookForLife, SpeakToIcthlarin, FirstGarouEarnReputation.*, FindThreeKeys, FindLastKey, RepairTheMirrors, FightFuzan, SpeakToGarouElder.

Regicide: https://dragonwilds.runescape.wiki/w/Regicide

- Objectives: BringHead, AccessSW, SpeakZilyana, DefeatKuldra, ReturnToZilyana.

Both are low confidence, because the reference player has no data for them yet.

## 6. Reverting Black Knight's Fortress

In every case, keep QuestState=1 and leave `QuestTrackedMain = 3MpWS0mD8A6yFVmjVAA2Qg` as it is.

### Back 1 step: "Return to the Dreaming Stone (13/13)" (confidence high)

| Field | Current | New |
|---|---|---|
| QuestInts.QuestBeat | 3 | **2** |
| QuestInts.Shard_Amount | 13 | 13 (keep) |
| QuestObjective | DR_Main_Objective_5 | **DR_Main_Objective_4_13** |
| QuestBools.GateOpen | true | **false** |
| QuestBools.FixedDreamstone | true | **false** |
| QuestLocations DR_GateKeeper | true | **false** |
| QuestLocations DR_MQ_DreamingStone | false | **true** |
| Inventory | no shards | optional: add 13x Shard of the Dreaming Stone `hJyKREoYCuSo8E20uZBB9g` in a quest slot (104+). The repair takes them back. |

Talking to the stone again replays Avisk's reveal and re-runs the repair, which sets GateOpen, FixedDreamstone and QuestBeat 3.

### Back 2 steps: "Investigate the Dreaming Stone" (confidence med)

Apply everything in Back 1, plus:

- QuestBeat → **1**
- QuestObjective → **DR_Main_Objective_3**
- **SpokenToDreamstone → false**

Keep Fragment_1..13, Fragments_All and Shard_Amount=13.

What happens in game:

- The first stone talk plays the "no shards" intro and sets QuestBeat 2.
- No fragment markers appear, because all Fragment_N are true.
- The objective may keep showing "Investigate the Dreaming Stone" until you talk to the stone again. That second talk triggers the 13/13 repair.

A full replay of the shard hunt is possible: Fragment_N=false, Shard_Amount=0, Fragments_All=false, the DR_MQ_Fragment_N locations set true, and the NPC bools reset. It is **not recommended** (low confidence): world-side shard sources may not respawn.

## 7. Side effects

**Known:**

- No BKF reward items or recipes have been granted yet. The reward pack and the Titan's Wrath recipe only come at completion, so reverting removes nothing from the inventory or unlocks.
- The 13 shards were consumed by the repair. Re-adding 13 is optional, and the repair removes them again.
- Earlier step items stay where they are: the Maple Toastie recipe from Snotpit, ItemsPickedUp history, and journal entries (`GameProgress.Journal.UnlockedEntries`). None of these gate BKF progression in the flows.
- Completing BKF requires Broken Titan's Wrath in the inventory. It only drops from the Titan.
- The Bastion barrier teleporter checks `GateOpen`, then sets `CanEnterBastion`. CanEnterBastion is absent now, so it needs no change.

**Unknown or world-side:**

- **The world save (SPUD binary):** Titan alive or dead, the Nexus barrier visual, library door, levers, vines, slain shardbound demons, NPC positions. The character save cannot change any of these.
- **Barrier visual:** whether it re-appears after GateOpen=false depends on world or actor logic that was not inspected. The barrier interaction itself is gated on the character bool, which is good news.
- **Since the Titan was never killed,** a 1- or 2-step revert should not desync any world boss state.
- **Co-op:** quest state is per character, but the world is shared.
- **Edit procedure:** edit only with the game closed, back up the Saved folder, and watch for Steam Cloud overwriting the edit (see [../save-format.md](../save-format.md)).
