@echo off
title AlphaWave - Installer & Launcher
cd /d "%~dp0"

echo ============================================================
echo   ALPHAWAVE - Binance Futures AI Signal Terminal
echo   [1/3] Creating Python virtual environment...
echo ============================================================
python --version >nul 2>&1 || (
  echo ERROR: Python not found. Install Python 3.10+ from python.org
  echo and tick "Add Python to PATH" during installation.
  pause
  exit /b 1
)
if not exist venv python -m venv venv
call venv\Scripts\activate.bat

echo [2/3] Installing dependencies (first run only, takes a minute)...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

echo [3/3] Starting AlphaWave GUI ...  (browser opens at http://127.0.0.1:8787)
echo       Stop anytime with Ctrl+C
echo ============================================================
python main.py
pause
