@echo off
title Litigation OS Launcher
cd /d "%~dp0"
echo.
echo ========================================
echo   Litigation OS - Starting Application
echo ========================================
echo.
echo Working directory: %cd%
echo.
python app_gui.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %errorlevel%
    echo Press any key to close...
    pause >nul
)
