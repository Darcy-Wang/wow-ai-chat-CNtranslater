@echo off
setlocal
title WoW Chat AI Translator
cd /d "%~dp0"
set "WCT_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "WCT_PYTHON=%~dp0.venv\Scripts\python.exe"
"%WCT_PYTHON%" run.py
if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with error.
    pause
)
