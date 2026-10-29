@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title iDownload - build

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not installed or not on PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :fail
)
set "PY=.venv\Scripts\python.exe"

echo Installing dependencies...
%PY% -m pip install -q --upgrade pip
%PY% -m pip install -q -r requirements.txt -r requirements-build.txt || goto :fail

for /f %%v in ('%PY% tools\bump_version.py show') do set "CUR=%%v"
echo.
echo ================================================
echo   Current version: %CUR%
echo ================================================
echo   [1] Major   (breaking / big release)
echo   [2] Minor   (new features)
echo   [3] Patch   (bug fixes)
echo   [4] Custom  (type your own, e.g. 2.0.0-beta)
echo   [5] Keep current version
echo.
choice /c 12345 /n /m "Choose version bump [1-5]: "
set "SEL=%errorlevel%"

if "%SEL%"=="1" %PY% tools\bump_version.py major >nul
if "%SEL%"=="2" %PY% tools\bump_version.py minor >nul
if "%SEL%"=="3" %PY% tools\bump_version.py patch >nul
if "%SEL%"=="4" (
    set /p "CUSTOM=Enter version: "
    %PY% tools\bump_version.py set "!CUSTOM!" >nul || goto :fail
)
if "%SEL%"=="5" %PY% tools\bump_version.py sync

for /f %%v in ('%PY% tools\bump_version.py show') do set "VER=%%v"
echo.
echo Building iDownload %VER% ...

%PY% tools\make_icon.py >nul

rem bundle ffmpeg so the exe stays standalone (needed to merge video+audio / make mp3)
set "FFARG="
for /f "delims=" %%f in ('where ffmpeg 2^>nul') do if not defined FFARG set "FFARG=--add-binary ""%%f;."""
if not defined FFARG echo WARNING: ffmpeg not found on PATH - the exe will not be able to merge HD video or make MP3s.

rem bundle Node.js: yt-dlp needs a JavaScript runtime to unlock YouTube formats (adds ~80 MB)
for /f "delims=" %%n in ('where node 2^>nul') do if not defined FFARG2 set "FFARG2=--add-binary ""%%n;."""
if not defined FFARG2 echo WARNING: node.exe not found on PATH - YouTube downloads in the exe will need Node.js or Deno installed.

%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name iDownload ^
    --icon assets\icon.ico ^
    --add-data "assets\icon.ico;assets" ^
    --add-data "assets\hero.png;assets" ^
    --version-file version_info.txt ^
    --collect-all customtkinter ^
    --collect-submodules yt_dlp ^
    --collect-all gdown ^
    --collect-all webview ^
    --collect-all yt_dlp_ejs ^
    %FFARG% %FFARG2% ^
    app.py || goto :fail

copy /y "dist\iDownload.exe" "dist\iDownload-v%VER%.exe" >nul
del "dist\iDownload.exe" >nul 2>nul

echo.
echo ================================================
echo   Built: dist\iDownload-v%VER%.exe
echo ================================================
explorer dist
pause
exit /b 0

:fail
echo.
echo Build failed. See the messages above.
pause
exit /b 1
