@echo off
REM Setup Script for Notion Google Calendar API
REM Run this once to set up your development environment

title Notion Calendar API - Setup

cd /d "D:\MyProjects\My API"

echo ============================================================
echo NOTION GOOGLE CALENDAR API SETUP
echo ============================================================

REM Create virtual environment
echo 1. Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo Error: Failed to create virtual environment
    pause
    exit /b 1
)
echo Virtual environment created successfully.

REM Activate virtual environment
echo 2. Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install dependencies
echo 3. Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies
    pause
    exit /b 1
)
echo Dependencies installed successfully.

REM Create .env file if it doesn't exist
echo 4. Setting up environment configuration...
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env"
        echo Created .env file from template
        echo Please edit .env with your Notion credentials
    ) else (
        echo Creating basic .env file...
        echo # Notion API Configuration > .env
        echo NOTION_TOKEN=your_notion_integration_token_here >> .env
        echo DATABASE_ID=your_notion_database_id_here >> .env
        echo. >> .env
        echo # Google Calendar Configuration >> .env
        echo GOOGLE_CALENDAR_ID=primary >> .env
        echo GOOGLE_CREDENTIALS_FILE=credentials.json >> .env
        echo GOOGLE_TOKEN_FILE=token.json >> .env
        echo Please edit .env with your actual credentials
    )
) else (
    echo .env file already exists
)

echo.
echo ============================================================
echo SETUP COMPLETE
echo ============================================================
echo Next steps:
echo 1. Edit .env file with your Notion credentials
echo 2. Download credentials.json from Google Cloud Console
echo 3. Run start.bat to start the application
echo.
pause