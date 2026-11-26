# Regicide (Nw3wiUaB8siRIN2bStWJmw, SW_MainQuest) checkpoints: GROUP late

The flows are present in build 1.0.2.0: `Content/Gameplay/Quests/ScornedWilderness/QF_SW_MainQuest.json`, plus `Quest_SW_MainQuest.json` and `ST_SW_MainQuest.json`. The wiki says the quest was released on 15 Sep 2026 in the 1.0 Release update, so it is not unreleased. No real save has a Regicide record beyond state 0, so every record below is built only from flow writes. Dumps are in `(working file, not included)` and `(working file, not included)`.

## Whole write set (every quest write in QF_SW_MainQuest)
- GiveQuest: UmSLink, and again (a no-op) at the Zilyana intro.
- Objectives:
  - AccessSW (UmSLink)
  - SpeakZilyana (gate)
  - ReturnToZilyana (intro)
  - DefeatKuldra (the raid-start choice "Dragontail Vines")
  - BringHead (entry DefeatKuldra)
- Bools: GateIntroGiven (gate) and IntroDone (intro). No ints.
- Locations:
  - SW_Door: true at UmSLink, false at the gate.
  - ZilyanaNPC: true at the gate. Nothing ever sets it false.
- CompleteQuest, in Zilyana's dialogue: takes ITEM_Resources_Kuldra (Kuldra's Head, 4vL1iUE8hFPCUjy34QVYpg), gives ITEM_Consumable_KuldraPack_Unique, and gives the recipe RECIPE_Armour_T8_Cape_Dragonslayer (yPxVHUt4c8xZInC2YuTobg).

## How it starts
ILH completes in QF_UmS_MQ_Icthlarin (Mirror entry). The completing node takes Fuzan's head, gives the UmS pack and the shield recipe, runs CompleteQuest, and sets DT_QuestBeat 6. It then links in the same conversation to `MQ_ScornedWilderness.UmSLink`, which runs GiveQuest, sets objective AccessSW and sets SW_Door=true. QuestCatchupConfigs re-runs UmSLink whenever UmS is Complete and SW is Ungiven. So there is no stable "given but not started" boundary; this is the same pattern as WH to BKF. "BringHead" refers to **Kuldra's** head, which you get after the fight. It is not an earlier boss's head. Fuzan's head is consumed at the ILH hand-in.

## Kuldra fight
- The raid is entered through Zilyana's "I'm ready" option. "Dragontail Vines" is shown while WorldProgress.Teleporter.SW.Checkpoint4 is 0. The other options are later raid checkpoints.
- The head drops from loot row SW_Raid_Kuldra on BP_DragonKuldra_Character. It drops 100% of the time, is auto-added to inventory, and goes to every player who dealt damage. Lougrim's Staff drops the same way.
- The DT_Progression_Quests row KuldraHead (ItemsPickedUp) fires entry DefeatKuldra, which sets objective BringHead.
- The arena resets the raid world-progress tags (Checkpoint1-4 set to 0, ResetPending set to 1).
- Kuldra has no ai_boss_* InternalName, so DefeatedBossesInternalNames is not a gate. The raid can be repeated, so no world edits are needed.
- Unresolved: the arena has `KuldraOneOffQuestBoolName = "KuldraEverKilled"`, which GrantRewards checks with TestQuestBoolFromController. The code that sets it, and which quest it belongs to, are not visible in the dump.

## Checkpoints
1. rg_access_sw: **very high**
   - Record: state 1, objective AccessSW, no bools, SW_Door=true.
2. rg_speak_zilyana: **high**
   - Record: GateIntroGiven, SW_Door=false, ZilyanaNPC=true.
   - Using the gate again rewrites exactly the same values.
   - Inferred: whether the PH_ScornedWildernessIntro hook is added to PlayerHooksTriggered.
3. rg_prepare_raid: **very high**
   - Record: GateIntroGiven and IntroDone, objective ReturnToZilyana.
   - inventory_remove strips Kuldra's Head (also on checkpoints 1-2, since Zilyana completes the quest on the first talk after her intro if it is held).
   - The DefeatKuldra objective is cosmetic, so it is folded into this checkpoint.
4. rg_bring_head: **high**
   - Record: objective BringHead, plus 1x Kuldra's Head in the inventory.
   - The hand-in only checks the inventory, so a live Kuldra is not needed.
   - Inferred: KuldraEverKilled may also be on the real record. It is safe either way.

## Complete (not offered)
- Record: state 2, objective BringHead, bools as in checkpoint 4. ZilyanaNPC stays true.
- Leaves: the head is removed, and the player has the Regicide pack (likely NfsDG0_3S4YQdcCD8_PjKA) and the cape recipe.
- No post-game flag or world unlock is written.
- Repeat kills: each head is traded for ITEM_Consumable_KuldraPack (likely the Queenslayer's pack).
- Lougrim's Staff: taking it to the Garou elder unlocks the LougrimMemorialShrine building.
- SW Complete changes Icthlarin's and the Garou elder's dialogue.
