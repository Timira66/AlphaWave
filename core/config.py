"""
Configuration management for AlphaWave.

Loads / saves config.json. On first run a default config is created with the
AI provider keys and model lists pre-filled.

NOTE: No Binance API key / secret is required or used anywhere in this
project. All Binance data comes from PUBLIC market-data endpoints.
This tool NEVER places orders (not an auto-trading tool).
"""

import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")

_lock = threading.Lock()

DEFAULT_CONFIG = {
    # ------------------------------------------------------------------ AI
    "ai": {
        # Provider chain order. The router walks this list; the built-in
        # local engine is ALWAYS the final fallback (100% free, no tokens).
        "provider_order": ["groq", "openrouter", "ollama", "custom", "local"],
        # 'off' | 'assist' (TA decides, AI writes the reasoning) | 'full'
        "mode": "assist",
        "request_timeout_sec": 40,
        "model_cooldown_sec": 90,
        "groq": {
            "enabled": True,
            "keys": [
                "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"
            ],
            # 4 verified working Groq models (tested 2026-09-18)
            "models": [
                {"id": "openai/gpt-oss-120b",  "reasoning": True},
                {"id": "qwen/qwen3.8-27b",     "reasoning": True},
                {"id": "openai/gpt-oss-20b",   "reasoning": True},
                {"id": "groq/compound-mini",   "reasoning": False}
            ]
        },
        "openrouter": {
            "enabled": True,
            "keys": [
                "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"
            ],
            # 3 verified working FREE OpenRouter models (tested 2026-09-18)
            "models": [
                {"id": "deepseek/deepseek-v4-flash-0731:free", "reasoning": False},
                {"id": "nvidia/nemotron-3-super-120b-a12b:free", "reasoning": False},
                {"id": "liquid/lfm-2.5-2.6b:free", "reasoning": False}
            ],
            # backup free models tried when the primaries are rate limited
            "backup_models": [
                {"id": "z-ai/glm-5.2:free", "reasoning": False},
                {"id": "qwen/qwen3.8-27b:free", "reasoning": False},
                {"id": "google/gemma-4-31b-it:free", "reasoning": False},
                {"id": "google/gemma-4-26b-a4b-it:free", "reasoning": False}
            ]
        },
        "ollama": {
            # Ollama runs locally -> completely free, unlimited tokens.
            # Install: https://ollama.com  then: ollama pull <model>
            "enabled": True,
            "base_url": "http://localhost:11434",
            "keys": ["", ""],  # two optional key slots (most setups need none)
            "models": [
                {"id": "llama3.1:8b", "reasoning": False},
                {"id": "qwen2.5:7b-instruct", "reasoning": False}
            ]
        },
        "custom": {
            # Any OpenAI-compatible endpoint (LM Studio, Google AI Studio free
            # key, DeepInfra free tier, vLLM ...). Example for Google Gemini
            # free tier:
            #   base_url: https://generativelanguage.googleapis.com/v1beta/openai
            #   model:    gemini-2.0-flash
            "enabled": False,
            "base_url": "",
            "keys": [""],
            "models": [{"id": "", "reasoning": False}]
        },
        "local": {
            # Built-in rule-based engine. Always available, always free.
            "enabled": True
        }
    },

    # ------------------------------------------------------------- Trading
    "trading": {
        "default_interval": "15m",
        "klines_limit": 300,
        "risk_percent": 1.0,          # % of account risked per trade (calculator)
        "account_balance_usdt": 1000, # used by the position-size calculator
        "max_spread_pct": 0.05,
        "min_quote_volume_24h": 2_000_000,
        "strategies": ["orderflow", "niyowew", "msnr", "smc", "ict2022", "elliott",
                       "sk", "ykof", "ichimoku", "keltner", "candles", "wyckoff",
                       "pivots", "adxdi", "stochx", "obvdiv", "goldfib", "fundrev",
                       "neuroquant"],
        # Leverage recommendation policy:
        #   STANDARD tier  -> always inside [min, max]  (10x .. 20x)
        #   EXTREME tier   -> allowed above 20x (up to extreme_max) ONLY when a
        #                     signal is an extremely high-quality opportunity:
        #                     confidence >= extreme_min_confidence AND
        #                     agreeing engines >= extreme_min_agree AND
        #                     R:R >= extreme_min_rr AND volatility is contained.
        "leverage": {
            "min": 10,
            "max": 20,
            "extreme_max": 30,
            "extreme_min_confidence": 85,
            "extreme_min_agree": 6,
            "extreme_min_rr": 2.0,
            "max_atr_pct_for_extreme": 1.0
        }
    },

    # -------------------------------------------------------------- Random
    "random_funnel": {
        "stage1_max": 1000,   # universe cap  (best 1000)
        "stage2_top": 100,    # -> best 100
        "stage3_top": 10,     # -> best 10
        "stage4_top": 1       # -> best 1 -> signal
    },

    # ------------------------------------------------------------ Telegram
    "telegram": {
        "enabled": False,
        "bot_token": "",           # create a bot with @BotFather and paste token
        # "open"     = anyone may use the bot
        # "whitelist"= only IDs in allowed_user_ids (multi-user, default cap 100)
        "access_mode": "open",
        "allowed_user_ids": [],
        "user_meta": {},           # {"<id>": {"note":..., "added_at":...}}
        "admin_user_ids": [],      # IDs that may /allow //revoke from Telegram
        "max_users": 100,
        "auto_start": False
    },

    # ----------------------------------------------------------------- GUI
    "gui": {
        "host": "127.0.0.1",
        "port": 8787,
        "open_browser": True
    },

    # ---------------------------------------------------------------- News
    "news": {
        "rss_feeds": [
            "https://cointelegraph.com/rss",
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://decrypt.co/feed",
            "https://cryptopotato.com/feed/"
        ],
        "max_items_per_feed": 25
    }
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (base is mutated & returned)."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    """Thread-safe JSON-backed configuration."""

    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.data = {}
        self.load()

    def load(self):
        with _lock:
            cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        user_cfg = json.load(f)
                    _deep_merge(cfg, user_cfg)
                except Exception:
                    pass
            # auto-migrate: enable any strategy engines added by updates
            known = list(DEFAULT_CONFIG["trading"]["strategies"])
            cur = cfg.get("trading", {}).get("strategies", [])
            if set(known) - set(cur):
                cfg["trading"]["strategies"] = known
            # auto-migrate: telegram multi-user access fields
            tg = cfg.setdefault("telegram", {})
            if "access_mode" not in tg:
                tg["access_mode"] = "whitelist" if tg.get("allowed_user_ids") else "open"
            tg.setdefault("admin_user_ids", [])
            tg.setdefault("max_users", 100)
            tg.setdefault("user_meta", {})
            self.data = cfg
            os.makedirs(DATA_DIR, exist_ok=True)
        return self.data

    def save(self):
        with _lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    # convenience -------------------------------------------------------
    def get(self, *keys, default=None):
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys_and_value):
        *keys, value = keys_and_value
        node = self.data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save()


CONFIG = Config()
