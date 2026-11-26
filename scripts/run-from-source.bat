@echo off
rem Starts Dragonwilds Save Editor from a source checkout (no console window).
rem Needs Python 3.9+ with tkinter. Prefers the repo's .venv, then the py launcher, then pythonw.
rem Any arguments (e.g. a save path) are passed on to the editor.
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m dragonwilds_save_editor %*
    exit /b 0
)
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m dragonwilds_save_editor %*
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw -m dragonwilds_save_editor %*
    exit /b 0
)
echo.
echo Dragonwilds Save Editor needs Python 3.9 or newer (with tkinter).
echo Neither "pyw" nor "pythonw" was found on PATH.
echo Install Python from https://www.python.org/downloads/ (keep the "py launcher" option),
echo or run:  winget install Python.Python.3.12
echo.
pause
exit /b 1
