@echo off
REM Stop Script for Notion Google Calendar API
REM Stops all running Python processes

title Notion Calendar API - Stop

echo Stopping Notion Google Calendar API...

REM Kill all Python processes
taskkill /f /im python.exe /t >nul 2>&1
if errorlevel 1 (
    echo No Python processes found or already stopped
) else (
    echo Python processes terminated
)

echo Application stopped.
timeout /t 2 >nul