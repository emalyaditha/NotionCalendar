@echo off
REM Notion Google Calendar Sync API - Startup Script
REM Created: 2026-01-31
REM Purpose: Automate the startup of the Notion-Google Calendar synchronization API

title Notion Calendar API

echo ============================================================
echo NOTION GOOGLE CALENDAR SYNC API STARTUP
echo ============================================================
echo Application: Notion Database API
echo Version: 1.0.0
echo Status: Initializing...
echo ------------------------------------------------------------

REM Change to the project directory
cd /d "D:\MyProjects\My API"

REM Check if virtual environment exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    echo Virtual environment created.
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Failed to activate virtual environment
    pause
    exit /b 1
)

REM Check if requirements are installed
echo Checking dependencies...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Error: Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Check if .env file exists
if not exist ".env" (
    echo Warning: .env file not found
    echo Please create .env file with your Notion credentials
    echo Copy .env.example to .env and update the values
    echo.
    pause
    exit /b 1
)

REM Check if Google credentials exist
if not exist "credentials.json" (
    echo Warning: Google credentials file not found
    echo Please download credentials.json from Google Cloud Console
    echo.
)

echo ------------------------------------------------------------
echo Starting application...
echo Server will be available at: http://localhost:8002
echo Documentation: http://localhost:8002/docs
echo Press CTRL+C to stop the server
echo ============================================================

REM Run the application
python main.py

echo.
echo Application stopped.
pause