@echo off
REM ==========================================================================
REM  Builds gridwyrm.py into a single standalone Gridwyrm.exe
REM
REM  You normally do NOT need this. Pushing a version tag builds the exe
REM  automatically on GitHub. Use this only if you want a build on your own
REM  machine without waiting.
REM
REM  Run it on Windows, on a machine with Python installed. Double-click it.
REM ==========================================================================

title Build Gridwyrm
cd /d "%~dp0"

echo.
echo  Building Gridwyrm.exe
echo  ---------------------
echo.

if not exist gridwyrm.py goto nosource

where python >nul 2>&1
if errorlevel 1 goto nopython

echo  [1/3] Installing PyInstaller (skipped if already present)...
python -m pip install --upgrade --quiet pyinstaller
if errorlevel 1 goto nopyinstaller

set ICONOPT=
if exist icon.ico set ICONOPT=--icon icon.ico
if exist icon.ico echo  Using icon.ico

echo  [2/3] Packaging...
python -m PyInstaller --onefile --windowed --noupx --clean --noconfirm --name Gridwyrm %ICONOPT% gridwyrm.py
if errorlevel 1 goto failed

echo  [3/3] Tidying up...
if exist build rmdir /s /q build
if exist Gridwyrm.spec del /q Gridwyrm.spec

echo.
echo  Done.
echo.
echo  Your program:   dist\Gridwyrm.exe
echo.
echo  Copy that one file anywhere you like. Two things to expect the first
echo  time it runs on someone else's PC:
echo.
echo    - Windows SmartScreen may warn that the publisher is unknown, because
echo      the file is not code-signed. Choose More info, then Run anyway.
echo    - Startup takes a second or two, as a one-file build unpacks itself
echo      to a temp folder each launch.
echo.
pause
exit /b 0

:nosource
echo  gridwyrm.py was not found in this folder.
echo  Put this .bat next to it and try again.
echo.
pause
exit /b 1

:nopython
echo  Python was not found on this PC.
echo.
echo  Install it from https://www.python.org/downloads/ and be sure to tick
echo  "Add python.exe to PATH" on the first screen of the installer. Then
echo  run this script again.
echo.
pause
exit /b 1

:nopyinstaller
echo  PyInstaller could not be installed. This is usually no internet
echo  connection, or a proxy blocking pypi.org.
echo.
pause
exit /b 1

:failed
echo.
echo  Packaging failed. The messages above say why. The usual cause is an
echo  antivirus tool locking the dist folder mid-build - try excluding this
echo  folder, or run the script again.
echo.
pause
exit /b 1
