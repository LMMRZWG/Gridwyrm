@echo off
REM ==========================================================================
REM  Builds gridwyrm.pyw into a single standalone Gridwyrm.exe
REM
REM  You normally do NOT need this. Publishing a release on GitHub builds the
REM  exe automatically on a Windows runner and attaches it to that release.
REM  Use this only when you want a build on your own machine straight away.
REM
REM  Put it beside gridwyrm.pyw and icon.ico, then double-click it.
REM ==========================================================================

title Build Gridwyrm
cd /d "%~dp0"

echo.
echo  Building Gridwyrm.exe
echo  ---------------------
echo.

if not exist gridwyrm.pyw goto nosource

where python >nul 2>&1
if errorlevel 1 goto nopython

echo  [1/4] Running the tests...
if exist test_gridwyrm.py (
  python -m unittest discover -q
  if errorlevel 1 goto testsfailed
  echo        all passed
) else (
  echo        test_gridwyrm.py not found, skipping
)

echo  [2/4] Installing PyInstaller (skipped if already present)...
python -m pip install --upgrade --quiet pyinstaller
if errorlevel 1 goto nopyinstaller

set ICONOPT=
if exist icon.ico set ICONOPT=--icon icon.ico
if exist icon.ico (echo        using icon.ico) else (echo        no icon.ico found, building without one)

echo  [3/4] Packaging...
python -m PyInstaller --onefile --windowed --noupx --clean --noconfirm --name Gridwyrm %ICONOPT% gridwyrm.pyw
if errorlevel 1 goto failed

echo  [4/4] Tidying up...
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
echo  gridwyrm.pyw was not found in this folder.
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

:testsfailed
echo.
echo  A test failed, so nothing was built. The output above says which one.
echo  Build anyway by deleting test_gridwyrm.py from this folder, though it is
echo  usually the test that is right.
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
