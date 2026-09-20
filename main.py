#!/usr/bin/env python3
"""
AlphaWave — main entry point.

Usage:
  python main.py               # GUI server (+ bot auto-start if configured)
  python main.py --no-browser  # don't open a browser window
  python main.py --bot-only    # only the Telegram bot
  python main.py --port 9000   # custom port
"""

import argparse
import logging
import sys
import threading
import time
import webbrowser

from core.config import CONFIG, BASE_DIR


def ensure_dirs():
    import os
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)


def maybe_start_bot(controller):
    token = (CONFIG.get("telegram", "bot_token") or "").strip()
    auto = CONFIG.get("telegram", "auto_start", default=False)
    if token and auto:
        from bot.telegram_bot import start_bot_thread
        ok, msg = start_bot_thread(controller)
        logging.info("Telegram bot auto-start: %s", msg)
    elif not token:
        logging.info("Telegram bot token not configured (Bot tab in GUI to set up).")


def main():
    parser = argparse.ArgumentParser(description="AlphaWave terminal")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--bot-only", action="store_true")
    parser.add_argument("--gui-only", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ensure_dirs()
    CONFIG.load()  # creates config.json with defaults (keys pre-filled) on first run

    if args.bot_only:
        from bot.telegram_bot import run_forever
        run_forever()
        return

    # import server AFTER config load
    from gui import server

    if not args.gui_only:
        maybe_start_bot(server.BOT_CONTROLLER)

    host = args.host or CONFIG.get("gui", "host", default="127.0.0.1")
    port = args.port or CONFIG.get("gui", "port", default=8787)
    url = f"http://{host}:{port}"

    open_browser = (not args.no_browser) and CONFIG.get("gui", "open_browser", default=True)
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print("=" * 64)
    print("  ALPHAWAVE — Binance Futures AI Signal Terminal")
    print(f"  GUI:      {url}")
    print("  Mode:     PUBLIC market data only · NO Binance keys · NO orders")
    print("  AI chain: Groq(4) -> OpenRouter(3 free) -> Ollama(2) -> Local(free)")
    print("  Leverage: recommended 10x-20x (>20x only for extreme-confidence setups)")
    print("  Stop:     Ctrl+C")
    print("=" * 64)
    try:
        server.run_server(host=host, port=port)
    except KeyboardInterrupt:
        print("\nShutting down…")


if __name__ == "__main__":
    main()
