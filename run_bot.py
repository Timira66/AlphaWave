#!/usr/bin/env python3
"""Run ONLY the Telegram bot (no GUI). Token must be set in config.json."""

import logging
from core.config import CONFIG


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    CONFIG.load()
    from bot.telegram_bot import run_forever
    run_forever()


if __name__ == "__main__":
    main()
