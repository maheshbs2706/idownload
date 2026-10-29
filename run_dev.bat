@echo off
setlocal
cd /d "%~dp0"
title iDownload - dev

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

rem reinstall only when requirements.txt changes
set "STAMP=.venv\.requirements.stamp"
fc /b requirements.txt "%STAMP%" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
    copy /y requirements.txt "%STAMP%" >nul
)

if not exist "assets\icon.ico" ".venv\Scripts\python.exe" tools\make_icon.py

echo Starting iDownload...
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Something went wrong. See the messages above.
pause
exit /b 1
