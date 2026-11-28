# Contributing

Thanks for helping. Bug reports, in-game test results and evidence about the [known unknowns](docs/SCOPE.md#known-unknowns) are as valuable as code.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting a bug

Open a [bug report](https://github.com/Astratus/DragonWildsSaveEditor/issues/new/choose) and include:

- the editor version (window title or About box) and how you run it (release zip or source);
- the game version or patch, if you know it;
- what you did, what you expected and what happened;
- the error message or the startup log from `%LOCALAPPDATA%\DragonwildsSaveEditor\logs\`, if there is one.

**Protect your privacy.** Save files and logs can contain personal information:

- **Don't attach save files** unless a maintainer asks for one, and never in a public issue without checking it first. A character save contains your character name and GUIDs; a world save also caches **other players' characters**.
- If a save is really needed, share the smallest excerpt that shows the problem, with names replaced and GUIDs you don't need removed.
- Check pasted paths and logs for your Windows user name (`C:\Users\<you>\...`) and replace it.

If something went wrong with your save, restore a backup first (see the [README](README.md#restoring-a-backup)), then report it.

Security problems should not go in a public issue; see [SECURITY.md](SECURITY.md).

## Suggesting a feature

Open a [feature request](https://github.com/Astratus/DragonWildsSaveEditor/issues/new/choose). Please read [docs/SCOPE.md](docs/SCOPE.md) first: some things are left out on purpose, such as forward quest jumps, arbitrary quest-step editing, world switches and events, and anything for multiplayer.

## Pull requests

Pull requests are welcome, whether you wrote the code yourself or with AI. Either way, the same rules apply: the change must pass the tests and follow the ground rules below, and the maintainer reviews and tests each one before it is merged. You don't need to say how the code was written, but you are responsible for it, so make sure you understand and have tested what you submit.

1. Fork the repository and create a branch from `main`.
2. Set up as described in [docs/development.md](docs/development.md).
3. Keep each pull request focused on one change.
4. Make sure all tests pass:

   ```powershell
   python -m unittest discover tests
   ```

5. Add or update tests for what you changed. Changes to the save writer must keep the byte-exact round trip (`selftest`) passing.
6. Update `CHANGELOG.md` under **Unreleased** if users will notice the change, and update the docs if behaviour changes.
7. Fill in the pull request template.

Ground rules for code:

- Standard library only at runtime. Build and development tools are fine.
- Keep the game's exact file formatting, and never change `Backup`, `HistoricCorruption`, `SaveCount` or `meta_data.char_guid`.
- Back up before every write, verify after it, and refuse to write while the game is running.
- **Never commit personal data:** no real saves, backups, snapshots, character or world names, or paths containing a user name. Test fixtures must be synthetic (see [docs/development.md](docs/development.md#tests)).

## Quest checkpoints

The main questline is deliberately **one linear line of checkpoints**, and the editor can only **revert** to them. Pull requests that add forward jumps, non-linear or arbitrary step editing, or switch and event editing will not be accepted.

A new or changed checkpoint needs evidence:

- **Every value must be traced.** Each quest-record value (state, objective, ints, bools) and each marker and item change must be traced to a write in the datamined quest flows, or confirmed on the official wiki.
- **No conflict with real saves.** Ideally, compare against a real save sitting at that exact step.
- **Write it down.** Put your reasoning in the checkpoint's `evidence` field and anything you inferred rather than traced in `inference`. Add your notes to [docs/research/](docs/research/README.md) if they are substantial.
- **Rate it honestly** using `rating_rule` in the data file:
  - **very high**: everything traced or wiki-confirmed, nothing conflicting;
  - **high**: exactly one untraced detail that is safe either way. A high checkpoint **must** have an `inference` field, because the editor shows it in a second confirmation;
  - **med / low**: disabled in the editor.

  Don't raise a rating unless every record-level value is traced or confirmed.
- **Test it.** Add or update a case in `tests/test_questline.py` so the checkpoint is applied to a copy and lands exactly.

Wiki text is CC BY-NC-SA 3.0, so paraphrase it and link the page instead of quoting it in bundled data.

The full rating table and what applying a checkpoint does are in [docs/development.md](docs/development.md#quest-checkpoints).

## Licence

By contributing, you agree that your contribution is released under the project's [MIT licence](LICENSE). Only contribute code and data you have the right to share; don't copy from projects without a compatible licence (see [docs/LICENSING.md](docs/LICENSING.md)).
