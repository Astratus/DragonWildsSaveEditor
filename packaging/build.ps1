<#
.SYNOPSIS
    Builds the Windows release zip of Dragonwilds Save Editor.

.DESCRIPTION
    1. Creates (or reuses) a local virtual environment in .venv at the repo root.
    2. Installs the pinned PyInstaller into that venv (never globally).
    3. Runs the unit tests.
    4. Builds dist\DragonwildsSaveEditor\ with packaging\DragonwildsSaveEditor.spec.
    5. Zips it to dist\DragonwildsSaveEditor-<version>-win64.zip.
    6. Writes dist\SHA256SUMS.txt and prints the SHA256.

    Works in Windows PowerShell 5.1 and PowerShell 7. The GitHub release workflow runs this
    same script.

.PARAMETER Python
    Python 3.12 interpreter used to create .venv. Default: $env:PYTHON, then `py -3.12`,
    then `python` on PATH.

.PARAMETER SkipTests
    Don't run the unit tests (not recommended).

.PARAMETER Recreate
    Delete .venv and create it from scratch.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$SkipTests,
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Pinned build dependency. Bump it on purpose and re-test the exe when you do.
$PyInstallerVersion = '6.22.3'
$AppName = 'DragonwildsSaveEditor'

$Root = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Root '.venv'
$VenvPy = Join-Path $VenvDir 'Scripts\python.exe'
$DistDir = Join-Path $Root 'dist'
$WorkDir = Join-Path $Root 'build\pyinstaller'
$Spec = Join-Path $PSScriptRoot "$AppName.spec"

function Invoke-Native {
    # Runs a native command and stops the script if it fails (PS 5.1 doesn't do this itself).
    param([Parameter(Mandatory)][string]$Exe, [string[]]$Arguments = @())
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

function Find-Python {
    if ($Python) { return $Python }
    if ($env:PYTHON) { return $env:PYTHON }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $exe = & py -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*\WindowsApps\*') { return $cmd.Source }
    throw 'Python 3.12 not found. Install it (winget install Python.Python.3.12) or pass -Python <path>.'
}

Push-Location $Root
try {
    # --- version ------------------------------------------------------------------------
    # Single source: __version__ in dragonwilds_save_editor\__init__.py.
    $InitPy = Join-Path $Root 'dragonwilds_save_editor\__init__.py'
    $VersionLine = Select-String -Path $InitPy -Pattern '^__version__\s*=\s*[''"]([^''"]+)[''"]' | Select-Object -First 1
    if (-not $VersionLine) { throw "__version__ not found in $InitPy" }
    $Version = $VersionLine.Matches[0].Groups[1].Value
    if ($Version -notmatch '^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$') {
        throw "__version__ must look like 1.2.3 (optionally -suffix), got '$Version'"
    }
    $ZipName = "$AppName-$Version-win64.zip"
    $ZipPath = Join-Path $DistDir $ZipName
    Write-Host "Building $AppName $Version" -ForegroundColor Green

    # --- venv ---------------------------------------------------------------------------
    if ($Recreate -and (Test-Path $VenvDir)) {
        Step 'Removing old .venv'
        Remove-Item -Recurse -Force $VenvDir
    }
    if (-not (Test-Path $VenvPy)) {
        $BasePy = Find-Python
        Step "Creating .venv with $BasePy"
        Invoke-Native $BasePy @('-m', 'venv', $VenvDir)
    }
    # No double quotes inside -c: Windows PowerShell 5.1 strips them from native arguments.
    $pyver = & $VenvPy -c "import sys; print(sys.version_info[0], sys.version_info[1], sep='.')"
    if ($pyver -ne '3.12') {
        Write-Warning ".venv uses Python $pyver; releases are built and tested with 3.12. Use -Recreate -Python <3.12 path>."
    }

    Step "Installing PyInstaller $PyInstallerVersion into .venv"
    Invoke-Native $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--quiet',
                            "pyinstaller==$PyInstallerVersion")

    # --- tests --------------------------------------------------------------------------
    if ($SkipTests) {
        Write-Warning 'Skipping tests (-SkipTests).'
    } else {
        Step 'Running unit tests'
        Invoke-Native $VenvPy @('-m', 'unittest', 'discover', '-s', 'tests', '-t', '.', '-v')
    }

    # --- build --------------------------------------------------------------------------
    Step 'Building with PyInstaller'
    $OutDir = Join-Path $DistDir $AppName
    if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
    Invoke-Native $VenvPy @('-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
                            '--distpath', $DistDir, '--workpath', $WorkDir, $Spec)
    $Exe = Join-Path $OutDir "$AppName.exe"
    if (-not (Test-Path $Exe)) { throw "Build finished but $Exe is missing." }

    # --- zip ----------------------------------------------------------------------------
    # Python's zipfile is used instead of Compress-Archive, which writes backslash paths
    # on Windows PowerShell 5.1. The zip holds one top-level DragonwildsSaveEditor\ folder.
    Step "Zipping to dist\$ZipName"
    if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
    Invoke-Native $VenvPy @('-m', 'zipfile', '-c', $ZipPath, $OutDir)

    # --- checksum -----------------------------------------------------------------------
    $Hash = (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLowerInvariant()
    $SumsPath = Join-Path $DistDir 'SHA256SUMS.txt'
    # sha256sum format, LF line endings, no BOM: `sha256sum -c SHA256SUMS.txt` works.
    [IO.File]::WriteAllText($SumsPath, "$Hash  $ZipName`n", (New-Object Text.UTF8Encoding $false))

    $ExeMB = '{0:N1}' -f ((Get-Item $Exe).Length / 1MB)
    $DirMB = '{0:N1}' -f ((Get-ChildItem -Recurse -File $OutDir | Measure-Object Length -Sum).Sum / 1MB)
    $ZipMB = '{0:N1}' -f ((Get-Item $ZipPath).Length / 1MB)

    Write-Host ''
    Write-Host "Built   : $Exe ($ExeMB MB exe, $DirMB MB folder)" -ForegroundColor Green
    Write-Host "Zip     : $ZipPath ($ZipMB MB)" -ForegroundColor Green
    Write-Host "SHA256  : $Hash" -ForegroundColor Green
    Write-Host "Sums    : $SumsPath"

    # Hand values to GitHub Actions when running there.
    if ($env:GITHUB_OUTPUT) {
        Add-Content -Path $env:GITHUB_OUTPUT -Value "version=$Version"
        Add-Content -Path $env:GITHUB_OUTPUT -Value "zip=$ZipPath"
        Add-Content -Path $env:GITHUB_OUTPUT -Value "sums=$SumsPath"
        Add-Content -Path $env:GITHUB_OUTPUT -Value "sha256=$Hash"
    }
}
finally {
    Pop-Location
}
