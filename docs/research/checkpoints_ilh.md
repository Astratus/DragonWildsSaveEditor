# ILH (Icthlarin's Little Helper, kPtTW0exXrqw2BqELR_bFA) checkpoints, traced from the flows only

The live save has ILH at state 0 and no task rows, so every record here is built purely from flow writes (build 1.0.2.0).
- Flows: `Plugins/GameFeatures/UmbralSands/Content/Gameplay/Quests/UmS_MainQuest/QF_UmS_MQ_*.json` and `Tribe{A,B,C}_Tasks/QF_*.json`.
- Unambiguous node-by-node dumps (each node lists its outputs): `(working file, not included)`.
- Write list: `(working file, not included)`.
- Generator: `(working file, not included)`.

## Beat variable
The beat variable is **DT_QuestBeat** (always SET, never ADD). Values:
- 1 = EnterUmS
- 2 = LookForLife / SpeakToIcthlarin
- 3 = SpeakToGarouElder, then the Alcarrid reputation objectives
- 4 = FindThreeKeys / FindLastKey (tribes B and C)
- 5 = SpeakToIcthlarin → RepairTheMirrors → FightFuzan
- 6 = ReturnToIcthlarin, then complete

## Start (BKF → ILH)
- The BKF hand-in in `QF_DR_MainQuest_Dreamstone` runs CompleteQuest, then QuestBeat SET 4, then links to `UmS_MainQuest.StartQuest`.
- `QuestCatchupConfigs[2]` (DR complete, UmS ungiven) runs the same entry.
- StartQuest has no conditions. Its writes, in order:
  - GiveQuest
  - objective `EnterUmS`
  - `Bastion_DoorToUmS_Target`=true
  - DT_QuestBeat=1
- **There is no "given / not started" boundary state** like BKF's `-1`. "BKF complete, ILH state 0" is transient, because the catch-up fires on load.
- `SkipDR` is a debug entry and is ignored.

## Step list (main record writes)
1. **StartQuest** → Beat 1, `EnterUmS`, Bastion=true.
2. **TeleportedIntoUmS** → TeleportedIntoUmS=true, Bastion=false.
   - **TriggerExitCave** (Beat 1, Overheard and TriggeredReveal false) → TriggeredReveal=true, `LookForLife`, Beat 2, GarouCamp_A_Area=true.
   - Optional: the Shangruuh cave intro sets SpokeToGarouAllyIntro=true.
3. **Icthlarin.Approach** (Beat 1/2) → Overheard=true, `SpeakToIcthlarin`, Icthlarin_Mirror_Target=true, GarouCamp_A_Area / Bastion / FirstGarouInCave_Target=false.
4. **Icthlarin.Mirror**:
   - At Beat ≤1, it first sets TriggeredReveal and Beat 2.
   - At Beat 2, the intro runs: Beat 3, `SpeakToGarouElder`, CampLeader_A_Target=true, Icthlarin_Mirror_Target=false.
5. **Elder (Camp A)**, Beat 3:
   - On accept: `FirstGarouEarnReputation.NoReputation`, TribeA.Taskgiver1-3, FirstGarou.CampNPC=true, CampLeader_A=false, TribeA.SpokenToElder, HideStartNPC.
   - The tasks ADD FirstCampFavour 25/25/50.
   - FavourIncrease updates the Low/Medium/High objectives. At ≥100: SET 100, `MaxReputation`, FirstCampMaxFavourEarned.
   - The elder's TasksComplete branch: FinishedCampA, mount, `FindThreeKeys`, key A (Mirror Lens Alcarrid), Beat 4, Camp B and C reveals, the CampA pack.
6. **Tribes B and C**, Beat 4:
   - Each tribe: elder intro, then tasks, which ADD favour (B 25/50/25, C 25/50/25).
   - At max favour, the elder gives the pack, KeysFound+1 and key B or C.
   - KeyCheck: at 1 key → `FindLastKey`; at 2 keys → `SpeakToIcthlarin`, Beat 5.
7. **Icthlarin**, Beat 5 → `RepairTheMirrors`, 3 mirror targets, ReadyToRepMirrors. (`RepairedAllMirrors` is never written, so the Beat-5 completion branch is dead.)
8. **Mirrors 1-3**: each takes its key, MirrorsRepaired ADD 1 and sets Mirror_n_Repaired. At 3: CanFightFuzan, `FightFuzan`, FightFuzan location=true.
9. **Fight Caves → Fuzan**:
   - Entry gate: CanFightFuzan.
   - Spawn gate (world-side): WorldProgress.Fuzan.FightCave.StoryModeComplete / ChallengeModeComplete / ResetPending [inferred].
   - Credit: the head drops 100% and is auto-added. The FuzanHead ItemsPickedUp row fires **DefeatFuzan**, which has no guards: Beat 6, `ReturnToIcthlarin`.
10. **Icthlarin**, Beat 6: takes the head, gives the Visage / complete pack and the recipe myqnDkdJSshMLUq3sMlSLA, runs CompleteQuest, then links to Regicide.

## Task quests (t-*)
| Slug | Task | Favour |
|---|---|---|
| t-rag-and-bone | A1 | 25 |
| t-rogue-trader | A2 | 25 |
| t-mirror-crackd | A3 | 50 |
| t-saga | B1 | 25 |
| t-dig-site | B2 | 50 |
| t-mark-day | B3 | 25 |
| t-beast-sand | C1 | 25 |
| t-scaling | C2 | 50 |
| t-song-ancients | C3 | 25 |

- Each tribe's favour sums to exactly 100, so **all 9 are gating**, and all 9 are related_records.
- Before camp A they are not started; at ilh_ready_fuzan they are state 2.
- `a-room-with-a-garou` (4G_ph0…, QF_ElderGarou) is a Ghornfell side quest and **unrelated**.

## Checkpoints
| id | rating | note |
|---|---|---|
| ilh_given | high | Every variable traced. Inferred: the Bastion door world switch; removing the pickups. |
| ilh_speak_garou_elder | high | Inferred: the optional-path flags (Overheard, SpokeToGarouAllyIntro, FirstGarouInCave_Target). |
| ilh_ready_fuzan | med | The order-dependent TribeB.*Favour and MirageBeast.* bools are untraced, the task rows are taken from the write list, and the Fight Cave spawn gate is inferred. |

## World
- Neither world copy has any `WorldProgress.Fuzan.*` or `ai_boss_fuzan` data.
- Only the `US_Fuzan_NightPatrol` event name is present, so the Fight Caves are at their never-played defaults.
- No world edit is proposed.
