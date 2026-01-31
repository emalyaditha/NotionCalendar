@echo off
title Notion Calendar API Setup
echo Downloading required files...
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/main.py' -OutFile 'main.py'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/requirements.txt' -OutFile 'requirements.txt'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/.env.example' -OutFile '.env'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/index.html' -OutFile 'index.html'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/manifest.json' -OutFile 'manifest.json'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/emalyaditha/NotionCalendar/main/sw.js' -OutFile 'sw.js'"

echo Creating virtual environment...
python -m venv .venv

echo Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt

echo Setup complete. Run run.bat to start the application.
pause