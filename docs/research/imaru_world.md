# Imaru checkpoint vs world state (evidence line: world/spawn)

Dump: RSDWArchive 1.0.2.0, `1.0.2.0/json/RSDragonwilds/Content/Gameplay/...` (abbreviated `G/`). Blueprint JSON has no Kismet bytecode, so graph logic is read from function names, local-variable names and CDO defaults. Tags: [C] confirmed, [I] inferred, [U] unknown.
World files: copied to `(working file, not included)` and `(working copy, not included)` and read from there only.

## Bottom line
- The gate to fight Imaru is on the **character**: three curse-fragment key items in the inventory. The world does not gate it. Both worlds already hold the "door closed, CanSpawnImaru=0" state that exists before any unleash. That is also the state the game returns to after a kill. **No world edit is needed.**
- The checkpoint needs two things: (a) DeathQuest_Beat=5, so the seals hand back the keys, or the 3 keys in the inventory; (b) the Imaru head removed from `Progress.ItemsPickedUp`, so the quest credit fires again. Item (b) is the real risk.

## 1. Spawning chain
| Step | Evidence | Tag |
|---|---|---|
| The lair door conversation `QuestFlow.Entry.DeathQuestMain.ImarusLair` checks **only** for the items `ITEM_Resources_SealBreakKey_Fall`, `_Fort` and `_Vil` in the player's inventory (QFR_PlayerHasItemAmount ×3). If any is missing, it shows "The door refuses to open…". There is no quest-int or bool check. | `G/Quests/FH_Quests/DeathQuest_Fellhollow/QF_DeathQuest_Beat5.json` (ConversationEntryPointNode_13, QFT_Blank_C_11/13/16/17) | C |
| On "Unleash the curse!", it takes the 3 keys (QFT_TakeItemFromPlayer 1-3), then `QFT_SetSwitchPosition` sets participant `QuestFlow.Participant.ImaruLairTeleportDoor` to 1. | same file | C |
| The door is a `SwitchBase` subclass, `BP_Seal_Switchable` (CDO `PendingSealTag=WorldProgress.Imaru.PendingSealDoor` and `CanSpawnImaruTag=WorldProgress.Imaru.CanSpawnImaru`; functions OnPendingSeal (a WorldProgressValueChanged listener), CanInteract, TeleportToNamedLocation, "Tower world location"). It drives the world tags and teleports the player into the tower. | `G/Quests/FH_Quests/DeathQuest_Fellhollow/BP_Seal_Switchable.json` | C for the fields; I for the exact writes (the setter is probably a native `SwitchableWorldProgressValueSetter` placed in the level, `G/World/Mechanisms/BP_SwitchableWorldProgressValueSetter.json`) |
| `BP_DragonImaru_SpawnTrigger` (OverlapSwitch). `CanActorActivateSwitch` = parent && `GetWorldProgressValue(CanSpawnImaru)` > x, through the Greater_DoubleDouble local. It also listens through OnCanSpawnImaruValueChange. | `G/AI/DragonImaru/Misc/BP_DragonImaru_SpawnTrigger.json` | C (condition names); I (threshold 0) |
| `BP_DragonImaru_SpawnPoint` (AISpawnPoint): AIClass is BP_AI_DragonImaru_Character and `bRequiresActivation=true`, so the trigger switch activates it. | `G/AI/DragonImaru/Misc/BP_DragonImaru_SpawnPoint.json` | C fields; I wiring |
| `WorldEvent.Dragon.Imaru` is only the EventGroup of world hook `wh_imarufellhollowentryflyover` (a cosmetic flyover), **not** the fight. | `G/World/WorldHooks/VelgarFlyover/WH_FellhollowFlyover.json` | C |
| `DefeatedBossesInternalNames` / `ai_boss_imaru` (InternalName in `G/AI/DragonImaru/BP_AI_DragonImaru_Data.json`) is not referenced by any spawn asset found. The Velgar rematch works with `ai_boss_velgar` still in the list, and community guides say Imaru can be re-fought in the same world. | grep of the dump | I: does not block the spawn |
| The NecromanticFocus seals read the **local player's** quest state (GetLocalPlayerQuestState), so their visuals are per player. | `BP_NPC_Seal_NecromanticFocus.json` | C |

**Per-player vs per-world:** the boss actor, the door and the tags are per world. Access to the fight (the keys) and the quest credit are per character.

## 2. Quest credit
- Loot row `DragonImaru` gives `ITEM_Resources_Imaru_Head` at 100%, with `bOneInstancePerPlayerOnlyVisibleToThem`, `bAutoAddToInventory` and `bOnlyForPlayersThatInflictedDamage` set [C, `G/Items/LootDropTables/DT_LootDropTable.json`].
- Progression row `ImaruHead` (ItemsPickedUp: Imaru's Head) triggers conversation `QuestFlow.Entry.DeathQuestMain.RecievedImaruHead` [C, `G/Progress/DT_Progression_Quests.json`, `DT_Composite_Progression.json`].
- `RecievedImaruHead`: if the quest is Given, HasRecievedImaruHead is false and **DeathQuest_Beat==5**, it sets the objective ReturnToDeath, ImaruDefeated=true and HasRecievedImaruHead=true. It does not change the beat; the beat is already 5 [C, QF_DeathQuest_Beat5.json entry 0].
- At Death (DeathBeat5Entry), ImaruDefeated=true plus the head in the inventory leads to taking the head and giving the reward pack and the Imaru shield recipe, then CompleteQuest [C].
- The rematch uses the same kill, loot and pickup path, so it credits the quest the same way. The one catch is the pickup progression (see the risk below).
- **Risk [U, important]:** the character's `GameProgress.Progress.ItemsPickedUp` already holds the head's PersistenceID `ALQSs0j7loBVpum0CaDH2w`. If the ImaruHead unlock fires only on a *first* pickup, it will not fire again. Fix: remove that ID in the checkpoint (character-side edit, low risk). Fallback: after the re-kill, with the head in the inventory, set ImaruDefeated=true on the character, then talk to Death.

## Seals and keys (character side) [C, QF_DeathQuest_Beat4.json]
- Breaking each seal gives that seal's key, sets <Seal>SealBroken=true and adds 1 to SealsBroken. At SealsBroken ≥3 it sets the objective ChallangeImaru and DeathQuest_Beat=5.
- With Beat==5, interacting with a seal again **gives back its key if the player lacks it** (QFT_Blank_C_14/12/16 → GiveItemToPlayer 7/4/8). This is the in-game "re-collect curse fragments" rematch.
- Current character: Beat 5, QuestState 2, no keys and no head in the inventory. All 3 key IDs and the head ID are in ItemsPickedUp; Imaru `m-XQ-02XemFtY-isjM0PGg` is in KilledOnceAIs (not involved in the spawn) [C].

## 3. Per-world prediction (character = seals broken, Beat 5, ImaruDefeated/HasRecievedImaruHead false)
| World | State [C, scratch copies] | Spawns? | Credit? |
|---|---|---|---|
| **World A** | CanSpawnImaru and PendingSealDoor value bytes `00 00 00 00`, SpawnTrigger SwitchPosition 0, BP_Seal_Switchable 0, ai_boss_imaru listed. This matches the state before an unleash; the kill reset it. | **Yes**, once the 3 keys are in the inventory, from the seals or the checkpoint. Confidence medium-high. | **Yes**, if the head pickup re-triggers. Medium; depends on the ItemsPickedUp fix. |
| **World B** | Empty WorldProgressManager (tags default 0); the trigger is not saved yet (defaults). | **Yes**, same conditions. Medium-high. | Same as above. |

**Minimal world edit: none.** Flipping CanSpawnImaru or the trigger byte would skip the door. It is a size-preserving float or uint8 change, but it is useless, because the door already sets them, and risky, because it leaves a world spawn that is out of sync. Removing `ai_boss_imaru` is a list edit that changes sizes (Ooga cannot edit type 64). It is high risk and unnecessary [I].

## 4. Simpler routes
1. Make the character checkpoint (Beat 5, SealsBroken 3, three bools true, ImaruDefeated and HasRecievedImaruHead false, QuestState Given, objective ChallangeImaru), remove the head ID from ItemsPickedUp, and **optionally add the 3 key items**. Otherwise, touch each seal again in-game to get the keys back. Then go to the lair door and choose "Unleash", in either world.
2. Neither a fresh world nor World B is needed; World A works.
3. A world reset is not needed.
