# Releasing

Releases are Windows zips built by PyInstaller and published as GitHub Releases by
`.github/workflows/release.yml` when a `v*` tag is pushed. Everything is driven by one script,
`packaging/build.ps1`, which you can run locally and which CI runs too.

| File | Purpose |
| --- | --- |
| `dragonwilds_save_editor/__init__.py` | `__version__`, e.g. `0.1.0`. The tag must be `v` + this. It also sets the exe's version resource. This is the single source of the version; `pyproject.toml` reads it. |
| `CHANGELOG.md` | Release notes. The `## [x.y.z]` section becomes the GitHub release body. |
| `packaging/build.ps1` | venv, pinned PyInstaller, tests, build, zip, SHA256. |
| `packaging/DragonwildsSaveEditor.spec` | PyInstaller spec: windowed, one-folder, `dragonwilds_save_editor/data/` bundled, version info from the package version. |
| `packaging/release_notes.py` | Extracts a CHANGELOG section; checks the tag matches the package version. |
| `packaging/build_catalog.py` | Regenerates (or `--check`s / `--verify`s) the bundled item catalog in `dragonwilds_save_editor/data/catalog/`. |
| `.github/workflows/ci.yml` | Unit tests and the bundled-catalog check on every push and pull request. |
| `.github/workflows/release.yml` | Tag push: tests, build, GitHub Release with the zip and `SHA256SUMS.txt`. |

## Why a zipped one-folder build, not `--onefile`

The release is `DragonwildsSaveEditor-<version>-win64.zip`, which holds a `DragonwildsSaveEditor\`
folder with `DragonwildsSaveEditor.exe` and an `_internal\` folder (Python runtime, Tcl/Tk, `data\`).

- **Fewer antivirus false positives.** A `--onefile` exe is a small loader that unpacks a
  compressed archive to `%TEMP%` and runs code from there. Malware packers behave the same way, so
  heuristic scanners flag onefile PyInstaller builds far more often. A one-folder build is plain
  files on disk. UPX compression is off for the same reason.
- **Faster start.** Nothing is unpacked on each launch.
- **Easier to inspect.** Users and scanners can see every file, and `data\` is readable.

The cost is that users must extract the whole zip and keep the folder together.

## Building locally

Needs Windows and Python 3.12 (`winget install Python.Python.3.12`).

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# options: -Python C:\path\to\python.exe   -SkipTests   -Recreate (rebuild .venv)
```

The script:

1. creates `.venv\` at the repo root (git-ignored) and installs the pinned PyInstaller there,
   never globally;
2. runs `python -m unittest discover -s tests -t . -v`;
3. builds `dist\DragonwildsSaveEditor\`;
4. zips it to `dist\DragonwildsSaveEditor-<version>-win64.zip`;
5. writes `dist\SHA256SUMS.txt` and prints the SHA256.

`.venv/`, `build/` and `dist/` must stay in `.gitignore`.

To bump PyInstaller, change `$PyInstallerVersion` in `build.ps1`, rebuild and run through the
zip test below.

## Cutting a release

1. Make sure `main` is green in CI.
2. Bump `__version__` in `dragonwilds_save_editor/__init__.py` (semver: `0.1.1` for fixes, `0.2.0` for features, `1.0.0` once in-game
   testing is solid).
3. In `CHANGELOG.md`, move the `[Unreleased]` entries into a new `## [x.y.z] - YYYY-MM-DD`
   section and update the link references at the bottom. The release fails if this section is
   missing or empty.
4. Optionally build locally (`packaging\build.ps1`) and test the zip (below).
5. Commit, tag and push:

   ```powershell
   git add dragonwilds_save_editor/__init__.py CHANGELOG.md
   git commit -m "Release v0.1.1"
   git tag -a v0.1.1 -m "v0.1.1"
   git push origin main
   git push origin v0.1.1
   ```

6. Watch the **Release** workflow under the repo's Actions tab (or `gh run watch`). It checks that
   the tag matches the package version, runs the tests, builds, creates a **draft** release with
   `gh`, uploads the zip and `SHA256SUMS.txt`, and then publishes it.

**Pre-releases:** any `0.x` version, or any version with a suffix such as `1.0.0-rc.1`, is
published as a GitHub pre-release. In-game testing is limited, so 0.1.0 is a pre-release. A plain
`1.0.0` or later becomes a normal release.

**Releases are immutable.** The repository uses GitHub immutable releases: once a release is
published, its tag and assets can't be changed or re-uploaded. **A broken release** therefore
needs a new version number (for example 0.1.1 after 0.1.0): fix the problem, bump `__version__`,
add a CHANGELOG section and release again. Don't try to re-upload assets to an existing release.

## After a game patch: regenerate the item catalog

The bundled item catalog (`dragonwilds_save_editor/data/catalog/`) is generated from an installed
copy of the game; `build_info.json` records the game version. After a game patch, on a machine
with the patched game installed (the game folder is only read):

1. Build into a scratch folder: `python -m dragonwilds_save_editor.catalog build --game-dir
   "<install>" --out build\cat-new`. If the self-check reports a low "fully decoded" share,
   re-infer the class schemas with `python -m dragonwilds_save_editor.gamedata.infer --game-dir
   "<install>"`, review the diff of `data/gamedata/schemas.json`, and update the field positions
   in `gamedata/derive.py` if an index used there moved (details in
   [development.md](development.md#item-catalog)).
2. Compare with the committed catalog: `python -m dragonwilds_save_editor.catalog compare --new
   build\cat-new`; check new and removed IDs and changed names. If the reader or a derivation
   rule had to change, bump `catalog.GENERATOR_VERSION`.
3. Regenerate: `python packaging\build_catalog.py --game-dir "<install>"` (self-checks and
   verifies the result).
4. Verify the map and lodestone data: `python -m dragonwilds_save_editor.gamedata.world
   --game-dir "<install>"` must report no problems. If it reports a difference, fix the data
   file and record it in its `install_check`.
5. Run the tests, also with `DW_TEST_GAME_DIR="<install>"`. Update the counts in
   `docs/research/catalog_build.md` and the CHANGELOG, and commit the three files in
   `data/catalog/` (and `data/gamedata/schemas.json`, if it changed) together.

Without a game patch, `python packaging\build_catalog.py --check --game-dir "<install>"` must
report "Up to date"; CI runs `--verify` (no game install needed) on every push.

## Testing the zip

Use a clean folder, not the repo, so nothing from the source tree is picked up.

1. Check the hash: `Get-FileHash DragonwildsSaveEditor-<version>-win64.zip` must match
   `SHA256SUMS.txt`.
2. Extract it, e.g. to `%TEMP%\dwtest`, and run `DragonwildsSaveEditor\DragonwildsSaveEditor.exe`.
3. Check that:
   - no console window appears;
   - the window title or About box shows the right version, and in Explorer,
     *Properties > Details* shows the file and product version;
   - on first start (empty `LOCALAPPDATA`) no dialog appears and nothing is downloaded: the
     Add Items tab lists about 1,600 items and Help > About says "Item catalog: bundled
     (from game version ...)" and "Works entirely offline: no network connections". Quest,
     map, lodestone and catalog data load from the bundled `data\`;
   - Help > Update item catalog shows the detected game folder (or "not found" and a folder
     picker) and, run against an installed game, ends with "Item catalog updated";
   - opening a save works. **Test on a copy of a save**, not the live one: copy a
     `SaveCharacters\*.json` to a scratch folder and use *Open*. Edit, save and check that a
     backup was written to `%LOCALAPPDATA%\DragonwildsSaveEditor`, not next to the exe;
   - the app also starts from a read-only location, e.g. a copy under `C:\Program Files`.
4. If you can, test once on a PC (or Windows Sandbox) without Python installed.

A quick start-up check from PowerShell, without touching any real save (it points
`LOCALAPPDATA` at an empty folder):

```powershell
$env:LOCALAPPDATA = "$env:TEMP\dw-empty"; mkdir $env:LOCALAPPDATA -Force | Out-Null
$p = Start-Process .\DragonwildsSaveEditor\DragonwildsSaveEditor.exe -PassThru
Start-Sleep 5; if ($p.HasExited) { "exited early: $($p.ExitCode)" } else { "OK"; Stop-Process $p }
```

## SmartScreen, antivirus and the unsigned exe

The exe is **not code-signed**. Put this in the README and the release notes:

> Windows may show "Windows protected your PC" (SmartScreen) the first time you run
> DragonwildsSaveEditor.exe, because the exe is not code-signed and is new. Click **More info >
> Run anyway**. You can verify the download by comparing its SHA256 with `SHA256SUMS.txt` on the
> release page: `Get-FileHash .\DragonwildsSaveEditor-<version>-win64.zip`. You can also run the
> editor from source with Python 3.12 instead (`python -m dragonwilds_save_editor`).

- SmartScreen goes by download reputation. An unsigned exe warns until enough people have run it,
  and each new version starts from zero.
- Some antivirus products flag PyInstaller builds. If one does, check the hash, upload the zip to
  VirusTotal and report the false positive to the vendor (Microsoft:
  <https://www.microsoft.com/wdsi/filesubmission>). Don't tell users to turn off their antivirus.
- Things that help: one-folder rather than onefile, no UPX, a version resource (all done here),
  and only ever building in CI from tagged source.
- Never publish an exe built on an untrusted machine. Release assets should come from the
  workflow.

## Code signing (optional, later)

Signing removes the "unknown publisher" warning and builds SmartScreen reputation per publisher
rather than per file.

- **Microsoft's Azure Trusted Signing** service: a low-cost subscription with identity
  validation and no hardware token. It has a GitHub Action (`azure/trusted-signing-action`).
  This is the most practical option for a small open-source project if you're eligible.
- **SignPath Foundation**: free signing for qualifying open-source projects, run from CI.
- **OV/EV certificates** from a CA: they now require a hardware token or cloud HSM, so they are
  awkward to use in CI.

To add signing, sign `dist\DragonwildsSaveEditor\DragonwildsSaveEditor.exe` after PyInstaller and
**before** zipping, i.e. between the build and zip steps in `build.ps1` (or as a workflow step
with the zip step moved after it). Timestamp the signature (`/tr <timestamp url> /td sha256`) so
it stays valid after the certificate expires. Keep certificates and credentials in GitHub
encrypted secrets or an environment with required reviewers, never in the repo.

## Repository setup (one-time)

The repository already exists at `Astratus/DragonWildsSaveEditor`. Before making it public or cutting the first release, check these settings:

1. **Nothing personal is tracked.** `.gitignore` covers `.venv/`, `build/`, `dist/`, `__pycache__/`, `backups/`, save files (`*.sav`, `*.backup`, `*.verbackup`, `*.pyedit.bak`, top-level `*.json`). Run `git ls-files` and make sure no save, backup or snapshot is listed, and search the history too.
2. **Workflow permissions.** If the Release workflow fails with a 403 when creating the release, go to *Settings > Actions > General > Workflow permissions* and allow **Read and write permissions**. The workflow also requests `contents: write` itself.
3. **Private vulnerability reporting** is deliberately off: this is an offline save editor, and `SECURITY.md` asks for ordinary issues.
4. **Visibility.** Make the repository public under *Settings > General > Danger Zone*. The CI badge in the README only renders for public repositories.

### First tag

The first tag must match the package version (`0.1.0`):

```powershell
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
gh run watch         # follow the Release workflow
gh release view v0.1.0 --web
```

The release appears as a pre-release with `DragonwildsSaveEditor-0.1.0-win64.zip` and `SHA256SUMS.txt` attached.
