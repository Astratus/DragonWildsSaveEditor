## What and why

<!-- What does this change, and why? Link the issue it fixes, e.g. "Fixes #12". -->

## How was it tested?

<!-- Tests added or updated; for save-writing changes, the round-trip selftest on a copy; any in-game testing (game version, what you checked). -->

## Checklist

- [ ] `python -m unittest discover tests` passes.
- [ ] Tests were added or updated for the change.
- [ ] Save writes keep the game's exact formatting and leave `Backup`, `HistoricCorruption`, `SaveCount` and `meta_data.char_guid` untouched.
- [ ] No personal data: no real saves, backups, character or world names, or paths containing a user name.
- [ ] `CHANGELOG.md` (Unreleased) and the docs are updated if users will notice the change.

### Quest checkpoint changes only

- [ ] The line stays linear and revert-only.
- [ ] Every value is traced to a quest-flow write or confirmed on the wiki, with reasoning in `evidence` and anything inferred in `inference`.
- [ ] The rating follows `rating_rule`, and a "high" checkpoint has an `inference` field.
- [ ] `tests/test_questline.py` covers the checkpoint.
