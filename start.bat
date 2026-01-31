@echo off
REM Quick Start Script for Notion Google Calendar API
REM Simple version - assumes environment is already set up

title Notion Calendar API - Quick Start

cd /d "D:\MyProjects\My API"

echo Starting Notion Google Calendar API...
echo Server: http://localhost:8002
echo Docs: http://localhost:8002/docs
echo Press CTRL+C to stop

call .venv\Scripts\activate.bat
python main.py