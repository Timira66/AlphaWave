"""
Binance USD-M Futures PUBLIC market-data client.

No API key / secret is used anywhere - only public endpoints:
  https://fapi.binance.com/fapi/v1/...
  https://fapi.binance.com/futures/data/...

This module never signs requests and never places orders.
"""

import time
import threading
import logging
from typing import Optional

import requests
import pandas as pd

log = logging.getLogger("binance")

BASE_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
]

# A browser-like UA avoids edge/proxy filtering on some networks.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
}

INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]

KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
                 "close_time", "quote_volume", "trades",
                 "taker_buy_base", "taker_buy_quote", "ignore"]


class TTLCache:
    def __init__(self):
        self._d = {}
        self._lock = threading.Lock()

    def get(self, key, ttl):
        with self._lock:
            item = self._d.get(key)
            if item and item[0] > time.time():
                return item[1]
            return None

    def set(self, key, value, ttl):
        with self._lock:
            self._d[key] = (time.time() + ttl, value)

    def clear(self):
        with self._lock:
            self._d.clear()


_cache = TTLCache()


class BinanceError(Exception):
    pass


def _request(path: str, params: dict = None, timeout: float = 12.0,
             retries: int = 3, cache_ttl: float = 0):
    key = (path, tuple(sorted((params or {}).items())))
    if cache_ttl:
        hit = _cache.get(key, cache_ttl)
        if hit is not None:
            return hit

    last_err = None
    for attempt in range(retries):
        base = BASE_URLS[attempt % len(BASE_URLS)]
        try:
            r = requests.get(base + path, params=params or {},
                             headers=HEADERS, timeout=timeout)
            if r.status_code == 429 or r.status_code == 418:
                last_err = BinanceError(f"rate limited ({r.status_code})")
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                last_err = BinanceError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(0.5 * (attempt + 1))
                continue
            data = r.json()
            if cache_ttl:
                _cache.set(key, data, cache_ttl)
            return data
        except Exception as e:  # network hiccup -> retry next mirror
            last_err = e
            time.sleep(0.6 * (attempt + 1))
    raise BinanceError(f"Binance request failed: {path} -> {last_err}")


# ---------------------------------------------------------------- endpoints

def ping() -> bool:
    try:
        _request("/fapi/v1/ping", timeout=8, retries=2)
        return True
    except Exception:
        return False


def server_time() -> int:
    return int(_request("/fapi/v1/time", cache_ttl=30)["serverTime"])


def exchange_info() -> dict:
    return _request("/fapi/v1/exchangeInfo", cache_ttl=3600)


def usdt_perp_symbols() -> list:
    """All TRADING USDT-margined perpetual symbols."""
    info = exchange_info()
    out = []
    for s in info.get("symbols", []):
        if (s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"):
            out.append(s["symbol"])
    return sorted(out)


def ticker_24h(symbol: Optional[str] = None) -> list:
    """24h rolling stats. Without symbol -> every market (one request)."""
    params = {"symbol": symbol} if symbol else {}
    data = _request("/fapi/v1/ticker/24hr", params=params, cache_ttl=8)
    return [data] if symbol else data


def premium_index(symbol: Optional[str] = None) -> list:
    """Mark price + funding rate. Without symbol -> all (one request)."""
    params = {"symbol": symbol} if symbol else {}
    data = _request("/fapi/v1/premiumIndex", params=params, cache_ttl=8)
    return [data] if symbol else data


def klines(symbol: str, interval: str = "15m", limit: int = 300) -> pd.DataFrame:
    """OHLCV candles as a DataFrame indexed by open time (ms)."""
    if interval not in INTERVALS:
        interval = "15m"
    limit = max(5, min(int(limit), 1500))
    data = _request("/fapi/v1/klines",
                    params={"symbol": symbol, "interval": interval, "limit": limit},
                    cache_ttl=4 if interval in ("1m", "3m") else 10)
    df = pd.DataFrame(data, columns=KLINE_COLUMNS)
    for c in KLINE_COLUMNS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce").astype("int64")
    df = df.set_index("open_time")
    df.index.name = "time"
    return df


def open_interest(symbol: str) -> dict:
    return _request("/fapi/v1/openInterest", params={"symbol": symbol}, cache_ttl=10)


def open_interest_hist(symbol: str, period: str = "1h", limit: int = 48) -> list:
    return _request("/futures/data/openInterestHist",
                    params={"symbol": symbol, "period": period, "limit": limit},
                    cache_ttl=60)


def long_short_ratio(symbol: str, period: str = "1h", limit: int = 24) -> list:
    """Top trader long/short ratio (accounts)."""
    return _request("/futures/data/topLongShortAccountRatio",
                    params={"symbol": symbol, "period": period, "limit": limit},
                    cache_ttl=60)


def taker_long_short_ratio(symbol: str, period: str = "1h", limit: int = 24) -> list:
    """Global taker buy/sell volume ratio."""
    return _request("/futures/data/takerlongshortRatio",
                    params={"symbol": symbol, "period": period, "limit": limit},
                    cache_ttl=60)


def depth(symbol: str, limit: int = 100) -> dict:
    return _request("/fapi/v1/depth",
                    params={"symbol": symbol, "limit": min(limit, 1000)}, cache_ttl=3)


def recent_trades(symbol: str, limit: int = 200) -> list:
    return _request("/fapi/v1/trades",
                    params={"symbol": symbol, "limit": min(limit, 1000)}, cache_ttl=3)


def agg_trades(symbol: str, limit: int = 500) -> list:
    return _request("/fapi/v1/aggTrades",
                    params={"symbol": symbol, "limit": min(limit, 1000)}, cache_ttl=3)


def mark_price_klines(symbol: str, interval: str = "15m", limit: int = 300) -> pd.DataFrame:
    data = _request("/fapi/v1/markPriceKlines",
                    params={"symbol": symbol, "interval": interval, "limit": limit},
                    cache_ttl=10)
    cols = ["open_time", "open", "high", "low", "close", "ignore1",
            "close_time", "ignore2", "ignore3", "ignore4", "ignore5", "ignore6"]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce").astype("int64")
    return df.set_index("open_time")


# ------------------------------------------------------------- convenience

def normalize_symbol(user_input: str) -> Optional[str]:
    """'btc' / 'BTCUSDT' / 'btc usdt' -> 'BTCUSDT' (or None)."""
    if not user_input:
        return None
    s = user_input.strip().upper().replace("/", "").replace("-", "").replace(" ", "")
    if s in usdt_perp_symbols():
        return s
    if not s.endswith("USDT"):
        s = s + "USDT"
    return s if s in usdt_perp_symbols() else None


def quick_price(symbol: str) -> dict:
    """Live snapshot used inside signals: mark price, funding, 24h change."""
    t24 = ticker_24h(symbol)[0] if isinstance(ticker_24h(symbol), list) else ticker_24h(symbol)
    prem = premium_index(symbol)
    prem = prem[0] if isinstance(prem, list) else prem
    return {
        "symbol": symbol,
        "last_price": float(t24.get("lastPrice", 0) or 0),
        "mark_price": float(prem.get("markPrice", 0) or 0),
        "index_price": float(prem.get("indexPrice", 0) or 0),
        "funding_rate": float(prem.get("lastFundingRate", 0) or 0),
        "next_funding_time": int(prem.get("nextFundingTime", 0) or 0),
        "change_24h_pct": float(t24.get("priceChangePercent", 0) or 0),
        "high_24h": float(t24.get("highPrice", 0) or 0),
        "low_24h": float(t24.get("lowPrice", 0) or 0),
        "quote_volume_24h": float(t24.get("quoteVolume", 0) or 0),
        "trades_24h": int(float(t24.get("count", 0) or 0)),
    }
