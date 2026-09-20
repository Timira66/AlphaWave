#!/usr/bin/env bash
# AlphaWave - one-command installer & launcher (Linux / macOS)
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  ALPHAWAVE - Binance Futures AI Signal Terminal"
echo "  [1/3] Creating Python virtual environment..."
echo "============================================================"
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.10+ first."
  exit 1
fi
if [ ! -d venv ]; then python3 -m venv venv; fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "[2/3] Installing dependencies (first run only)..."
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "[3/3] Starting AlphaWave GUI ...  (browser opens at http://127.0.0.1:8787)"
echo "      Stop anytime with Ctrl+C"
echo "============================================================"
python main.py
