# map_points.json: sources, method, unknowns (AI-oriented)

`map_points.json` catalogs the map fog bits, the six areas and how each is gated, every Sanguine Urn (the save's `ShrinesUnlocked`) and every kebbit burrow. It is data for the GUI; nothing here edits a save.

## Install check (2026-11-26, game 1.0.2.2)

`python -m dragonwilds_save_editor.gamedata.world` re-reads the same facts from an installed copy of the game (read only; layouts in [gamedata_provenance.md](gamedata_provenance.md#world-level-map-and-lodestone-verification)) and compares them with `map_points.json`. Result, also recorded in the file's `install_check`:

- **Confirmed from the install:** one `BP_MapRegion_C` per RegionID 1-31 in `/Game/Maps/World/L_World` (no region 0), every `region_name` and `area`; all 21 Sanguine Urn IDs (landmark category 6, display name "Sanguine Urn") and all 19 kebbit-burrow IDs (category 8, `Agility.KebbitBurrow.Region.<area>` tag matching the JSON area), none missing and none extra; their locations match the table below within 1 unit (the table rounds to integers); all burrows have needs-discovery = true and a 1,000-unit discover distance.
- **Not confirmed from the install** (still from the RSDWArchive research below): the sub-region part of urn and burrow names (map texture and region splines), and the areas' quest gating (quest flows and wiki).
- No disagreement was found; no value was changed.

## Sources
- The datamine is RSDWArchive build 1.0.2.0. Paths below are relative to `json/RSDragonwilds/Content/`.
  - `Maps/World/L_World.json`: the 31 `BP_MapRegion_C` actors (RegionID, RegionName, MapRegionTag, QuestConversationEntryTag, BoundarySpline) and `GameplayObjectRegistry.Landmarks` (558 entries).
  - `Art/UI/Map/T_WorldMapRegions.png`: the region-index texture. R channel = round(ID*255/31). Map bounds are X -12000..408000 and Y -118550..301450, with u = X and v = Y.
  - Quest flows: `QF_DR_MainQuest_Entry`, `QF_DR_Main_Cathan`, the WH `QF_DeathQuest_Beat1/2`, the ILH StartQuest, and `MQ_ScornedWilderness.UmSLink` (see `checkpoints_ilh.md`, `checkpoints_late.md`, `main_quest_map.md`).
- Wiki (dragonwilds.runescape.wiki, paraphrased): the Sanguine Urn page (21 urns, +10 max health each), the Kebbit burrow page (19 burrows as of 1.0), and the Fellhollow, Dowdun Reach, Umbral Sands and Scorned Wilderness pages for access requirements.

## Method
1. **Fog bits.** Bit N = RegionID N. This comes from earlier work and is confirmed by game logs ("Revealing map region [The Approach] (Region 16)" and so on). Bit 0 has no region but is always set, so keep it.
2. **Points.** All `Landmarks` entries with Category HealthShrine (21) and KebbitBurrow (19) were taken. Their `InternalName` is the 32-hex ID stored in the save. Counts match the wiki: 21 urns and 19 burrows.
3. **Sub-region.** Each point was looked up in the region texture and also tested point-in-polygon against every region's boundary spline.
   - The two methods agree for all 37 on-texture points.
   - The 3 Scorned Wilderness urns lie in a separate coordinate block (around X -750000, Y 710000), off the texture. The spline test puts them in region 31, the raid zone.
   - For each burrow, the area also matches its `Agility.KebbitBurrow.Region.*` GameplayTag.
4. **Confidence.**
   - Points within 2000 uu (20 m) of their sub-region's border are rated "high", because the sub-region is slightly uncertain. The area is still certain.
   - The Scorned Wilderness urns are rated "high".
   - Everything else is rated "very high".
5. **Names.**
   - Urns have no individual in-game names (all are "Sanguine Urn"), and burrows have none.
   - Names are therefore "<type> - <sub-region>". A nearby named NPC or landmark is added when one is within about 100 m. Otherwise a #n index is added, ordered by world X.
6. **Save check.** Every ID in the save's ShrinesUnlocked (15), KebbitBurrowsFound (8) and KebbitBurrowsActivated (6) is in the catalog. None are missing.

## Important corrections to earlier assumptions
- `ShrinesUnlocked` are **Sanguine Urns** (health shrines, `ST_HealthShrine` "Sanguine Urn"). They are **not fast-travel shrines**. Each one permanently adds +10 max health. Removing one from the list probably lowers max health and makes the urn usable again (inferred).
- Kebbit burrows are Agility shortcuts with `bNeedsToBeDiscovered`, DiscoverDistance 1000 uu.
  - The Agility levels required are 27 for Brynmoor and Ghornfell, 42 for Fellhollow, 55 for Dowdun Reach and 67 for Umbral Sands.
  - In the save, `KebbitBurrowsActivated` is not a subset of `KebbitBurrowsFound`: three activated IDs are not in Found. Treat the two lists as independent.
- There are no kebbit burrows in Scorned Wilderness.

## Wiki vs datamine sub-region differences (datamine used)
- The wiki puts 3 urns in Bramblemead Valley and 3 in Whispering Swamp. The datamine puts 4 in Bramblemead and 2 in Whispering. 13C2DCA1 is about 11 m from the Bramblemead/Whispering border, so it is probably the disputed one.
- The wiki puts one Fellhollow urn in Silverthorn Keep. The datamine puts 5D81E4DB in Lake of Lost Souls, about 29 m inside that region and 57 m from Silverthorn.
- The wiki puts one Umbral urn in Manafem Plains. The datamine puts D934D328 in Dunes of Uzzer.
- The wiki gives Scorned Wilderness sub-zones as "Fragments of Ghornfell" (2 urns) and "Cataclysm Keep" (1). These are not map regions; the game has only Rasthin's Rest (30) and Scorned Wilderness (31). It is unknown which urn is in which sub-zone.

## Area gating (gated_by_quest = main quest ID from main_questline.json)
- **Brynmoor**: null.
- **Ghornfell**: null (med). No door was found. Entering Fractured Plains just advances Dragon Slayer.
- **Fellhollow**: Withering Heights (high).
  - The wiki says Dragon Slayer must be complete and WH started.
  - The WH Beat1 flow sets the objective `UnlockGate`. The door's own check was not traced.
- **Dowdun Reach**: Black Knight's Fortress, DR_Main_Objective_0 (high). The gatehouse flow (`EnterDRDoor`) is traced:
  - If the prerequisite quest (Withering Heights, by the message name `DoorToDowdun_NotFinishedWitheringH`) is not complete, the gatehouse refuses entry.
  - Otherwise it gives BKF if it hasn't been given yet, then teleports the player in.
  - So **WH Complete** is the hard requirement, and the door itself auto-gives BKF.
  - Not traced: which quest the outer HasQuestState node checks. The dump does not show that node's quest asset; WH is inferred from the message key.
- **Umbral Sands**: Icthlarin's Little Helper, `EnterUmS` (high).
  - ILH is given when BKF completes. The Umbral door in The Bastion leads in.
  - Not traced: the door's own condition.
- **Scorned Wilderness**: Regicide, `AccessSW` (high).
  - Regicide is given at the ILH hand-in (UmSLink). The Dragon Gate is in north-west Fractured Plains.
  - Not traced: the gate's own condition.

## Unknowns
- No world-side state for urns or burrows was examined. The wiki notes a 0.12.1.4 fix where "a burrow dug in one world couldn't be dug in another", which suggests a world-side dig state might also exist.
- The POI GUIDs in the world save's PoiDiscoverySystemActor (see `world_save_survey.md`) are a different ID space and are not mapped here.
- 6 agility courses also exist as landmarks (IDs DY92hUu0..., T8AD905F..., ey1IZEnv..., jRj_gkpc..., _bdK2EOl..., ozOAhU5o...). They are not in the JSON because the schema doesn't cover them.

## Point table (region = fog bit; x, y, z in Unreal units; flags = state in this save as of 2026-11-25)
| id | name | region | x, y, z | conf | flags |
|---|---|---|---|---|---|
| 37A73D4548E5AA4DE2E7E8900F9236F7 | Kebbit burrow - Bramblemead Valley #1 | 2 | 18133, 146984, 3277 | very high | found activated |
| 7713063049A18FDA3FBF958E154A34C9 | Kebbit burrow - Bramblemead Valley #2 | 2 | 28046, 152369, -489 | very high | found activated |
| DB621D2A40316F7B97255696742C2AA1 | Sanguine Urn - Bramblemead Valley #1 | 2 | 51232, 153631, 620 | very high | unlocked |
| 824A3798412A1067890E86A2AEB609FF | Sanguine Urn - Bramblemead Valley (near the Wise Old Man) | 2 | 52124, 172224, -3855 | very high | unlocked |
| 0581A4424DCFE38990160EB3EF0178DF | Kebbit burrow - Bramblemead Valley #3 | 2 | 75796, 187241, 658 | very high | activated |
| 13C2DCA14ADFC8C4A882FC9E92624D37 | Sanguine Urn - Bramblemead Valley #3 | 2 | 76151, 150385, -3192 | high | unlocked |
| 0C3D67174C0A1B0FC3FF9C9CA3FF8B32 | Kebbit burrow - Bramblemead Valley (near Bilegut) | 2 | 78069, 149134, -3526 | high | found |
| 7DE4A84C4997053BD7171089B408AE13 | Sanguine Urn - Bramblemead Valley (near Wormelbow) | 2 | 82653, 173184, 309 | very high | unlocked |
| ABB5944041C18CAAC148EF8EB84CE0B7 | Sanguine Urn - Whispering Swamp (near the Saradomin statue) | 3 | 41590, 131700, -1031 | very high | unlocked |
| 485514AA4D440FC3EBF331B6F5128ECE | Sanguine Urn - Whispering Swamp #2 | 3 | 74399, 142354, -1565 | very high | unlocked |
| BAEAE3C3442F6EA066DA9E9A167C18E7 | Kebbit burrow - Fractured Plains #1 | 4 | 74037, 122081, 5513 | very high | activated |
| EC9B242D41CCBBCFB4D96687923F2056 | Kebbit burrow - Fractured Plains #2 | 4 | 77262, 81798, -1690 | very high | found |
| DCF55CC14E4019584B5B03AB1D1ECC75 | Sanguine Urn - Fractured Plains | 4 | 124802, 104131, 495 | very high | unlocked |
| 4D76564C46D67E541E309392F38D735D | Kebbit burrow - Fractured Plains #3 | 4 | 127982, 97737, 2049 | very high |  |
| FFFC3EC542BE3EC01D043ABBD6DE12BD | Sanguine Urn - Stormtouched Highlands | 5 | 13599, 73449, 15304 | very high | unlocked |
| 0A9739A740CFAC41147A8988CAFEF502 | Kebbit burrow - Stormtouched Highlands (near Lougrim's Shrine) | 5 | 44306, 78707, 4167 | very high |  |
| 13A95FDF40A30E7465E66C96CAA63778 | Sanguine Urn - Bloodblight Swamp (near Doctor Fenkenstrain's lab) | 6 | 124799, 157954, 850 | very high | unlocked |
| 1174BD3D4D08B273B65F499342BBFC3F | Kebbit burrow - Bloodblight Swamp (near Doctor Fenkenstrain's lab) | 6 | 127427, 160668, -1545 | very high |  |
| B29665A34A76BC52049B31AAD16CD3C4 | Kebbit burrow - Bleakfields Valley | 7 | 107850, -48924, -5209 | very high | found |
| 774770F44B8DB02A050E9388A2C749D9 | Kebbit burrow - Hope's Fall | 8 | 134795, -79647, -6758 | very high | activated |
| 186B64E241A3790BE54292A84653E981 | Sanguine Urn - Hope's Fall | 8 | 151032, -62753, -7240 | high | unlocked |
| 5D81E4DB41E190FF887E26B70012DCB6 | Sanguine Urn - Lake of Lost Souls (near Leonard The Bound) | 9 | 185162, -15880, -8914 | very high | unlocked |
| F094A6504328FA64FF4B0B8F0529E063 | Kebbit burrow - Coalridge Pass | 10 | 202849, -47424, -7112 | high | found |
| 0A642E58410CF6656DDECA9A39966D3E | Kebbit burrow - Witchwillow Range | 13 | 83556, -14846, -5222 | very high | found |
| BA041CF14868F751575411B22EFE218A | Sanguine Urn - Emberwood | 14 | 32025, -46994, -6440 | very high | unlocked |
| EDB3BF37460645E5CCBFAC9444293910 | Kebbit burrow - The Menagerie | 19 | 185303, 65445, 2286 | very high | activated |
| FBA02FCB4F0443D2E48EBAA3ABDC5FE2 | Sanguine Urn - The Menagerie | 19 | 194483, 63727, 4814 | very high | unlocked |
| 7F08EB5E423CA1F87DDC9C909EA0B3A8 | Sanguine Urn - The Garrison | 20 | 241210, 10909, -2637 | very high | unlocked |
| 804AED6240B09B374F6FEFB3A165FC09 | Kebbit burrow - The Pastures | 22 | 260294, 28045, -986 | very high | found |
| F57EA8C8495F0671B12659A84D4D1239 | Sanguine Urn - The Grand Hall | 25 | 235466, 43987, 462 | very high | unlocked |
| F5CF21AB4C362B5BF82F449AFEEB58A2 | Kebbit burrow - Alcarrid Oasis | 26 | 220912, 112802, 1194 | very high |  |
| 30D8FACB490D76F52996A58311D5B528 | Sanguine Urn - Alcarrid Oasis | 26 | 295248, 164835, 2703 | very high |  |
| D934D328425EF220C8050A82599895A8 | Sanguine Urn - Dunes of Uzzer | 27 | 336636, 131080, 4943 | very high |  |
| A79537B44A3E9B51248460B7F8C93F0B | Kebbit burrow - Dunes of Uzzer #1 | 27 | 356880, 140297, 2088 | very high |  |
| 7676442649467CAEFA301090628769B3 | Kebbit burrow - Dunes of Uzzer #2 | 27 | 368112, 43383, 2630 | very high |  |
| 8E9BBE764A12FCEE6F4C17BA867DD85F | Kebbit burrow - Manafem Plains | 28 | 258240, 247770, -3200 | very high |  |
| 00BD25DE45F90484B177FDA9F0AC392E | Sanguine Urn - The Burning Spire | 29 | 288487, 198441, -2216 | very high |  |
| 189437844E5DD62D0458C9A415C5F5E2 | Sanguine Urn - Scorned Wilderness raid #1 | 31 | -778507, 703792, 20100 | high |  |
| C5AFB2F3441D61ABE1DC7AACF61FC7E7 | Sanguine Urn - Scorned Wilderness raid #2 | 31 | -743560, 722041, 8989 | high |  |
| 93BA5CA64D045F23573ACBAC89221B83 | Sanguine Urn - Scorned Wilderness raid #3 | 31 | -717931, 708355, 11268 | high |  |

Rebuild: the extraction scripts (registry dump, spline check, nearest-point lookup, build) were working files and are not included. To redo the work, re-run the same steps on L_World.json from RSDWArchive.
