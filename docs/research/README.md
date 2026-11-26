# Research notes

These notes are the evidence behind the main-quest checkpoints in `main_questline.json`, behind what the editor knows about world saves, and behind the map, lodestone and item-catalog data. They were written while the checkpoints were being built (November 2026, against game build 1.0.2.0) and are kept so that every checkpoint value can be traced back to its source. The item catalog and the map and lodestone IDs were later rebuilt or verified from an installed copy of the game (1.0.2.2); see [catalog_build.md](catalog_build.md) and [gamedata_provenance.md](gamedata_provenance.md).

They are **working notes, not user documentation.** They are terse, use internal quest variable names, and assume you know the save format ([../save-format.md](../save-format.md)) and the checkpoint rules ([../development.md](../development.md#quest-checkpoints)). For a plain explanation of what the Main Quest tab does, read [../SCOPE.md](../SCOPE.md#the-main-questline-linear-revert-only).

## Sources

- **Quest flows:** the `QF_*` quest-flow graphs, `Quest_*` and `ST_*` assets and `DT_Progression_Quests` from the RSDWArchive data dump of build 1.0.2.0. A checkpoint value counts as *traced* when a write node in these flows sets it.
- **Real saves:** a small set of genuine character saves (the maintainer's "reference save" and its older copies, a guest character cached in a world, and a public Early Access sample), used to confirm that checkpoint records match states the game actually writes. All names have been replaced.
- **World saves:** two of the maintainer's worlds, called **World A** (large, Velgar and Imaru defeated) and **World B** (small, nearly empty). They were only ever read from copies.
- **The [RuneScape: Dragonwilds Wiki](https://dragonwilds.runescape.wiki/):** walkthroughs and boss pages, used to confirm inferences. Wiki text is paraphrased with a link, never quoted (the wiki is CC BY-NC-SA 3.0).

Labels used throughout: **[C]** confirmed (by a source or a read-only decode of a real save), **[I]** inferred, **[U]** unknown.

Where a note says "(working file, not included)", it refers to a flow dump, script or copy that was used during the research but is not part of this repository, either because it was temporary or because it contained personal data. Machine-readable `checkpoints_*.json` files mentioned in the notes are likewise not shipped; the checkpoints that came out of them are in `main_questline.json`.

## Index

| Note | What it covers |
|---|---|
| [main_quest_map.md](main_quest_map.md) | The starting point: the wiki's main-quest steps mapped to character-save variables (quest IDs, states, objectives, ints and bools) using the reference save. Its machine-readable form is `main_quests.json`. |
| [quest_samples.md](quest_samples.md) | The genuine quest records collected from real saves, which every checkpoint is checked against. |
| [checkpoints_early.md](checkpoints_early.md) | First Steps through Dragon Slayer. Explains why the tutorial quests get no checkpoints, and derives the Dragon Slayer ones. |
| [checkpoints_flow.md](checkpoints_flow.md) | Withering Heights and Black Knight's Fortress checkpoints derived from their quest-flow graphs, including the item-pickup triggers and quest catch-up configs. |
| [checkpoints_mid.md](checkpoints_mid.md) | The middle of the line: Withering Heights before Imaru and Black Knight's Fortress steps 2, 3, 4, 6, 8 and 9, with ratings. |
| [checkpoints_ilh.md](checkpoints_ilh.md) | Icthlarin's Little Helper, built purely from flow writes because no real save reaches it. |
| [checkpoints_late.md](checkpoints_late.md) | Regicide, the last main quest, also built purely from flow writes. |
| [imaru_world.md](imaru_world.md) | Why the "ready to challenge Imaru" checkpoint needs no world edit: the lair door checks the Curse Fragments in the inventory, and quest credit comes from picking up Imaru's Head. |
| [wiki_inference_check.md](wiki_inference_check.md) | Each checkpoint inference checked against the wiki, with a verdict (confirmed, partial, not on wiki) and a paraphrase. |
| [world_save_survey.md](world_save_survey.md) | A survey of the world-save (`.sav`, SPUD) format and of what quest-related state lives in world files. It backs `world_quest_stubs.json` and the experimental World tab. |
| [player_hooks.md](player_hooks.md) | How one-time player hooks (region-intro cutscenes) are recorded in the character save, and which ones each checkpoint's `hooks_remove` clears so a later region intro plays again. |
| [map_points.md](map_points.md) | How `map_points.json` was built: fog-of-war region bits, the six map areas and their quest gates, Sanguine Urns and kebbit burrows. Backs the Map tab. |
| [lodestones.md](lodestones.md) | Where lodestone state lives in a world save, the four fixed world lodestones in `lodestones.json`, and what the experimental activate/remove edits change. |
| [catalog_build.md](catalog_build.md) | How the bundled item and unlock-name catalog (and the optional user-side update) is built from an installed copy of the game: assets used, decoding and fallbacks, the self-check, derivation rules, and the cross-check against the earlier dump-based catalog. |
| [gamedata_provenance.md](gamedata_provenance.md) | Provenance of the read-only game-data reader (`gamedata/`): the format sources (CUE4Parse as a reference, no code), what was verified against the game's bytes, how the native class schemas were inferred, and the world-level layouts used to verify the map and lodestone data. |
| [spud_cleanroom.md](spud_cleanroom.md) | The clean-room log for `spud.py`, the world-save reader: what was read, what was deliberately not opened, and the format facts verified on real files. |

## Using these notes

If you want to add or re-rate a checkpoint, start from the relevant note, follow its references to the flow assets in the RSDWArchive dump, and record your own evidence the same way. The rules a new checkpoint must meet are in [CONTRIBUTING.md](../../CONTRIBUTING.md#quest-checkpoints).
