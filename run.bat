@echo off
title Notion Calendar API
pushd "%~dp0"
call .venv\Scripts\activate.bat
python main.py
popd