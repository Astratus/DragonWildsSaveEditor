# Wiki check of checkpoint inferences

Source: dragonwilds.runescape.wiki (MediaWiki API), read on 2026-11-24. Wiki text is paraphrased here, not quoted (the wiki is CC BY-NC-SA); see each URL. Raw wikitext was in `(working file, not included)`. JSON: `(working file, not included)`.

**Is the wiki current?** The wiki has pages for "Eye on Ashenfall - 1.0.2" (10 Nov 2026) and "1.0.2.2 is live!" (18 Nov 2026, build CL261625). The quest, boss and region pages used here were last edited between 16 Oct and 23 Nov 2026 (ILH 23 Nov, Velgar and Fight Cave 19 Nov, BKF 2 Nov). So the wiki reflects the 1.0.2.x line and matches build 1.0.2.0. The 1.0.2 notes contain no changes to the main-quest steps.

| checkpoint | inference | verdict | what the wiki says (paraphrased) | URL |
|---|---|---|---|---|
| ds_investigate_castle | What triggers CastlePieceFound | PARTIAL | Walkthrough: Cathan's Journal sits at the top of the castle by a loot chest; reading it sends the player to the Whispering Swamp. Names the in-game action, not the variable. | /w/Dragon_Slayer |
| ds_investigate_castle | Whether the trigger can fire again after a revert (first-time gate); the HasAntiDragShieldRecipe side flow | NOT ON WIKI | – | – |
| ds_ready_challenge_velgar | Velgar can be summoned again with a new horn | CONFIRMED | Velgar's infobox: he respawns for each new challenge-horn instance. | /w/Velgar |
| ds_ready_challenge_velgar | The head drops again | CONFIRMED | Velgar's Head is a guaranteed drop; after Dragon Slayer, extra heads can be traded to the Wise Old Man for a cosmetic reward. | /w/Velgar%27s_Head |
| ds_ready_challenge_velgar | The "defeated" list doesn't block the summon | PARTIAL | Patch 0.10.1 note: once defeated, Velgar stops his random ambient attacks; the defeated state affects only that. The horn rematch still works. | /w/Velgar |
| ds_ready_challenge_velgar | Removing the head from ItemsPickedUp; QuestTrackedMain; FoundDragonTooth | NOT ON WIKI | – (the md shows the result is the same either way) | – |
| wh_given | Level trigger volumes (search the structure, Fellhollow teleport) fire again | PARTIAL | A short intro cutscene plays on first entry to Fellhollow, and first arrival grants permanent Fellhollow access in all worlds (one-time, account-wide effects). Nothing says the quest triggers depend on them. | /w/Withering_Heights |
| bkf_speak_doric | The WOM-before-Doric path exists in normal play | CONFIRMED | Walkthrough order: the Wise Old Man points the player to Doric, who is dispelling a barrier in the Nexus; the player then meets Doric there. | /w/Black_Knight%27s_Fortress |
| bkf_speak_doric | WOM_Optional_1-4 left out | NOT ON WIKI | – (dialogue-only, so it plays the same either way) | – |
| bkf_step6_return_stone | GateOpen/FixedDreamstone absent vs false | NOT ON WIKI | – (the mid md shows it is safe either way; already re-rated very high) | – |
| bkf_step6_return_stone | The barrier drops only after the repair | CONFIRMED | Walkthrough: the barrier comes down after the stone is repaired, and the dropped barrier leads into The Bastion. | /w/Black_Knight%27s_Fortress |
| bkf_titan_defeated | The Titan can be fought again | CONFIRMED | Infobox: the Titan respawns via the symbol in the room; after the first kill the arena centre becomes a Titan Seal usable after about a minute for a rematch. | /w/Black_Knight_Titan |
| bkf_titan_defeated | Broken Titan's Wrath drops on every kill | CONFIRMED | Broken Titan's Wrath is a guaranteed drop, stays a quest item after the quest, and later drops go to the quest tab automatically. | /w/Broken_Titan%27s_Wrath |
| bkf_titan_defeated | ItemsPickedUp entry; the repeat fire is idempotent | NOT ON WIKI | – | – |
| bkf_complete | Not a separate resting state; rewards not reproduced | PARTIAL | The ILH walkthrough starts right after the Titan fight and talking to Avisk, by returning to The Bastion's door to the Umbral Sands. (ILH follows immediately.) The rewards gap is structural. | /w/Icthlarin%27s_Little_Helper |
| ilh_given | The Bastion door is open after BKF | CONFIRMED | Umbral Sands page: completing Black Knight's Fortress opens the Bastion door to the Umbral Sands. | /w/Umbral_Sands |
| ilh_given | Fuzan's Head and the Radiant Heart can be obtained again | CONFIRMED | After the quest, extra Fuzan's Heads can be traded to Icthlarin for a cosmetic reward. The Radiant Heart page describes it as a tally of repeat red-dragon kills as they respawn. | /w/Fuzan%27s_Head, /w/The_Radiant_Heart |
| ilh_given | Removing the pickups from ItemsPickedUp is needed for re-credit | NOT ON WIKI | – (harmless either way) | – |
| ilh_speak_garou_elder | Overheard/SpokeToGarouAllyIntro/FirstGarouInCave_Target are optional | PARTIAL | Shangruuh is described as the first NPC the player talks to, on arrival, to start ILH. This supports the full-path record but does not say whether he can be skipped; no flow reads these flags after Beat 3. | /w/Shangruuh_-_Alcarrid_Envoy |
| ilh_ready_fuzan | Final values of TribeB.*Favour and MirageBeast.* | NOT ON WIKI | – (not shown to be safe either way) | – |
| ilh_ready_fuzan | All 9 tasks are gating | CONFIRMED | Each clan has three tasks that must be completed to obtain its lens. | /w/Icthlarin%27s_Little_Helper |
| ilh_ready_fuzan | The Fight Cave trial must be cleared before Fuzan | CONFIRMED | Fight Cave: clearing all ten trial waves unlocks the path to Fuzan's Lair; during the quest only the Trials of Fuzan option exists, and the full activity unlocks afterwards. (Gameplay only; the variable name is not on the wiki.) | /w/Fight_Cave |
| ilh_ready_fuzan | Lenses are consumed by the mirrors | NOT ON WIKI | – | /w/Mirror_Lens |
| rg_speak_zilyana | The gate requires DS, WH, BKF and ILH | CONFIRMED | Dragon Gate: entering the Scorned Wilderness requires all four primary quests (DS, WH, BKF, ILH) to be complete. | /w/Dragon_Gate |
| rg_speak_zilyana | PH_ScornedWildernessIntro hook | PARTIAL | Regicide walkthrough: choosing to travel into the Scorned Wilderness plays a narrative trailer. (The hook itself is save-internal and non-blocking.) | /w/Regicide |
| rg_bring_head | The raid can be repeated and the head drops each run | CONFIRMED | The reward pack can be earned repeatedly by handing Kuldra's Head to Zilyana after each raid run; each completed run restarts in Dragontail Vines. | /w/Queenslayer%27s_Reward_Pack, /w/Regicide |
| rg_bring_head | KuldraEverKilled | NOT ON WIKI | – (safe either way) | – |
| rg_bring_head | "Dragontail Vines" is a dialogue option | PARTIAL | Talking to Zilyana starts or resumes a raid run, which begins in Dragontail Vines. (The option's label is not given.) | /w/Scorned_Wilderness |

## Suggested ratings

| checkpoint | was | suggested |
|---|---|---|
| ds_investigate_castle | med | med |
| ds_ready_challenge_velgar | high | **very high** |
| wh_given | high | high |
| bkf_speak_doric | high | **very high** |
| bkf_step6_return_stone | high (re-rated very high in mid) | very high |
| bkf_titan_defeated | high | **very high** |
| bkf_complete | med | med (duplicate of ilh_given) |
| ilh_given | high | **very high** |
| ilh_speak_garou_elder | high | **very high** (the PARTIAL point is shown to be safe either way) |
| ilh_ready_fuzan | med | high (the gate and the task set are confirmed; the order-dependent bools are still untraced) |
| rg_speak_zilyana | high | **very high** |
| rg_bring_head | high | **very high** |
