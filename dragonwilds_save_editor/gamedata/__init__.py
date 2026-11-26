"""Read-only access to an installed copy of RuneScape: Dragonwilds (stdlib only).

The game ships its assets in Unreal Engine 5.6 IoStore containers (.utoc/.ucas), unencrypted
and uncompressed, plus one pak for config files. This package reads them with seeks and never
writes, renames or locks anything in the game folder. It does not attach to or read the running
game, does not read the game executable and uses no mapping (.usmap) file.

Modules:
  iostore      .utoc/.ucas and .pak containers
  zen          cooked package headers (names, imports, exports)
  uprops       unversioned property headers and primitive values (FString, FName, FText, ...)
  decode       decoding an export with a byte-level schema
  schemas      the inferred schemas of the game's native classes (data/gamedata/schemas.json)
  stringtable  the game's display-name tables
  game         GameData: package lookup over the containers, class chains
  derive       the item / unlock-name catalog from the installed game
  install      finding the installation folder
  infer        development tool: re-infer schemas.json after a game patch

Format knowledge and its sources: docs/research/gamedata_provenance.md.
"""
