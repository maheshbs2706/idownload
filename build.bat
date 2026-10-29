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

rem the PyInstaller call lives in Python so cmd can't mangle paths (bundles ffmpeg + node, renames the exe)
%PY% tools\build_exe.py || goto :fail

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
