@echo off
title Notion Calendar API Setup
setlocal enabledelayedexpansion

:: Change to desktop directory
cd /d "%USERPROFILE%\Desktop"

:: Create EM folder if it doesn't exist
if not exist "EM" mkdir "EM"
cd "EM"

:: Delete existing files if they exist
echo Checking for existing files...
if exist "main.py" del "main.py"
if exist "requirements.txt" del "requirements.txt"
if exist ".env" del ".env"
if exist "index.html" del "index.html"
if exist "manifest.json" del "manifest.json"
if exist "sw.js" del "sw.js"
if exist "run.bat" del "run.bat"

:: Download all required files
echo Downloading required files...
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/main.py' -OutFile 'main.py'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/requirements.txt' -OutFile 'requirements.txt'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/.env.example' -OutFile '.env'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/index.html' -OutFile 'index.html'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/manifest.json' -OutFile 'manifest.json'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/sw.js' -OutFile 'sw.js'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/run.bat' -OutFile 'run.bat'"

:: Create virtual environment
echo Creating virtual environment...
python -m venv .venv

:: Install dependencies
echo Installing dependencies...
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install fastapi uvicorn[standard] google-api-python-client google-auth-oauthlib google-auth python-dotenv requests pydantic

echo Setup complete. Files downloaded to Desktop\EM folder.
echo Run run.bat to start the application.
pause