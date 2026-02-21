@echo off
title Notion Calendar API
pushd "%~dp0"
echo Starting Notion Calendar Sync...
.\.venv\Scripts\python.exe main.py
if %errorlevel% neq 0 (
    echo.
    echo Application crashed with error code %errorlevel%
    pause
)
popd