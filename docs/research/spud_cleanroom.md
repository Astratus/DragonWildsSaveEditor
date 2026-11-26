# spud.py clean-room log

`dragonwilds_save_editor/spud.py` (developed as `dw_spud.py`) and `tests/test_spud.py` were
written from scratch on 2026-11-25 so the
world-save reader/writer can be redistributed under MIT. This log records what was and
was not used.

## Sources read
- sinbad/SPUD (MIT), `Source/SPUD/Public/SpudData.h` on GitHub: chunk header, FSpudPropertyDef,
  storage type codes, PROP offsets + data, NOBJ/SPWN/KILL/LEVL fields. Only the format
  description was used.
- Project prose notes (the maintainer's own research): `world_save_survey.md`,
  `lodestones.md`, `player_hooks.md`, `world_quest_stubs.json`, and a grep of
  a private findings log. Prose only. These describe other tools in words; none of their code was read.
- `save.py` (the project's own module): `game_is_running` and `snapshot_game_saves` signatures.
- The first 30 lines of `tests/test_questline.py`, for the project's unittest conventions.
- The real saves, read-only. They were copied to a private temp dir and hex-dumped and
  probed with throwaway scripts: `World A.sav`, `World B.sav`, both game `.backup`
  files, and an older full-snapshot copy of `World A.sav`.

## Not opened
- the earlier ported world module (`dw_world.py`, released as `world.py`), `lodestones.py`, `tests/test_dw_world.py`, `tests/test_lodestones.py`,
  `tests/_helpers.py`.
- Any scratch folder used by earlier work sessions. Work files went to a fresh temp folder instead.
- Any backup copy of a .py file.
- The OogaBoogaCode/RSDWSaveEditor and haithemobeidi/RSDragonWilds-WorldEditor repos, and
  any other third-party Dragonwilds tool.

## Format facts verified on the real files
- SAVE length = file size - 8. All IFF lengths are payload-only.
- Container headers:
  - INFO: 48+ bytes, then CINF.
  - GLOB: FString level name, then META, GOBS, GLAI.
  - LEVL: FString name + 8 version bytes.
  - NOBJ: u32 ClassID, FString name, u32 0, 8 version bytes.
  - SPWN: u32 ClassID, 16-byte GUID, 48 bytes of doubles, u8, 8 version bytes, u32 n, n x u32.
  - CDVE: 1 byte (0x00) + CDEF, or empty (classes without a definition).
- Leaves:
  - KILL: FString name.
  - GLAI: an LVNI chunk (u32 n + level names), then (FString actor name, u32 level index) pairs. It holds no byte offsets.
- CDEF: FString class name, **u16** count, then {u32 PropertyID, u32 PrefixID, u16 type}.
- PROP: u32 n, n offsets, u32 data length, data. The offsets are contiguous, start at 0 and
  are in CDEF order (true for every object in all files).
- Type 40 values are u32 ClassID + a PROP-shaped block, or FFFFFFFF for none.
- Type 64 values have no length prefix:
  - TSet/TMap: u32 0 + u32 n + elements.
  - TArray: u32 n + elements.
  - Structs inside use UE5.4+ tagged properties: name, FPropertyTypeName tree (FString + u32
    param count), u32 size, u8 flags (0x08 binary struct, 0x10 bool true), value, "None".

## Integration (2026-11-26)
- The callers (`lodestones.py`, `dragonwilds_save_editor/gui/context.py`, `dragonwilds_save_editor/gui/world_tab.py`, `dragonwilds_save_editor/gui/app.py`) and the
  old tests (`tests/test_dw_world.py`, `tests/test_lodestones.py`, `tests/test_world_focus.py`) were
  adapted to spud. `dw_world.py` was NOT opened during this; it was deleted unread (and `world.py`
  and `tests/test_world.py` were removed from the release).
- Added to spud during integration: `WorldFile.original` and `WorldFile.changed_on_disk()`.
- The old behavioural tests were re-expressed against spud in `tests/test_world_edits.py`.
