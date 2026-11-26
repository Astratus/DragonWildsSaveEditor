# Security policy

## Supported versions

Only the latest release gets fixes. The project is in 0.x pre-release, so please update before reporting.

## Reporting a vulnerability

This is an offline save editor, so please report security problems as an ordinary [issue](https://github.com/Astratus/DragonWildsSaveEditor/issues). If you think the details could be abused before a fix is out, say so in the issue without the details and a maintainer will follow up.

Include what you found, how to reproduce it and which version you used. Don't attach real save files; describe the problem or share a minimal, anonymised example. You can expect an acknowledgement within a week. This is a volunteer project, so fixes may take longer.

## What counts

Examples of things we want to hear about:

- a crafted save file that makes the editor run code, or write outside the save, backup or `%LOCALAPPDATA%\DragonwildsSaveEditor` folders;
- a release asset that doesn't match the source or the published SHA256, or that you believe was tampered with;
- the editor leaking personal data (for example writing save contents somewhere unexpected).
- crafted or tampered catalog data (the bundled catalog, or one built with **Update item catalog**) or crafted game files that make the editor run code or write outside its catalog folder;
- the editor writing to, renaming or locking anything in the game's installation folder, or making any network connection.

**The editor makes no network connections at all.** There are no downloads, update checks, telemetry, analytics, accounts or sign-in; it works fully offline, including on first run, because the item catalog is bundled. **Help > Update item catalog** (or `dwsave catalog build`) rebuilds the catalog from your own installed game: it only reads the game's files (opened read-only, never written, renamed or locked), reads the game's own log in `%LOCALAPPDATA%\RSDragonwilds\Saved\Logs` only to find the installation folder, and writes the result to `%LOCALAPPDATA%\DragonwildsSaveEditor\catalog`. It does not read the game's executable or the running game's memory. The package imports no networking module; a unit test (`tests/test_gamedata.py`, `NoNetworkTests`) checks this. The only exception is the About box: its "Full credits" and "Project page" buttons open your web browser, and only when you click them. Saves are read and written only on your PC, with backups. It has no multiplayer features. Save corruption, game bugs and antivirus false positives on the unsigned exe are ordinary bugs: please report them through [Issues](https://github.com/Astratus/DragonWildsSaveEditor/issues).

## Verifying downloads

Every release includes `SHA256SUMS.txt`. Compare it with:

```powershell
Get-FileHash .\DragonwildsSaveEditor-<version>-win64.zip
```

Release assets are built only by the project's GitHub Actions workflow from tagged source.
