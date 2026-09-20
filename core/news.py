"""
Fundamental news aggregator (all free, no API keys):
  - RSS feeds: CoinTelegraph, CoinDesk, Decrypt, Bitcoin Magazine
  - Fear & Greed Index (alternative.me public API)
  - Binance Futures announcements (public bapi endpoint, best-effort)
  - lightweight keyword sentiment scoring per article / per coin
"""

import re
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from .config import CONFIG

log = logging.getLogger("news")

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/126.0 Safari/537.36")}

_cache = {"items": None, "ts": 0, "fng": None, "fng_ts": 0,
          "ann": None, "ann_ts": 0}

POSITIVE = ["surge", "rally", "soar", "bull", "breakout", "adoption", "approve",
            "approval", "etf inflow", "record high", "all-time high", "ath",
            "partnership", "upgrade", "buy", "accumulate", "growth", "gain",
            "halving", "institutional", "launch", "integrat", "milestone",
            "outperform", "rebound", "recover"]
NEGATIVE = ["crash", "plunge", "dump", "bear", "hack", "exploit", "scam",
            "fraud", "lawsuit", "sue", "sec charges", "ban", "crackdown",
            "liquidation", "sell-off", "selloff", "fear", "drop", "decline",
            "outflow", "bankrupt", "insolven", "warning", "delist", "fine",
            "penalty", "attack", "stolen", "rug", "collapse", "recession"]


def sentiment_score(text: str) -> float:
    """-1 .. +1 keyword sentiment."""
    t = (text or "").lower()
    pos = sum(1 for w in POSITIVE if w in t)
    neg = sum(1 for w in NEGATIVE if w in t)
    tot = pos + neg
    return round((pos - neg) / tot, 2) if tot else 0.0


def _parse_rss(url: str, max_items: int, source: str) -> list:
    out = []
    try:
        r = requests.get(url, headers=UA, timeout=12)
        root = ET.fromstring(r.content)
        # RSS 2.0
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = re.sub(r"<[^>]+>", "", (item.findtext("description") or ""))[:400].strip()
            pub = (item.findtext("pubDate") or "").strip()
            ts = _parse_date(pub)
            if title:
                out.append({"title": title, "link": link, "summary": desc,
                            "source": source, "published": pub, "ts": ts,
                            "sentiment": sentiment_score(title + " " + desc)})
            if len(out) >= max_items:
                break
        if not out:
            # Atom
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for e in root.findall("a:entry", ns):
                title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
                link_el = e.find("a:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                summ = re.sub(r"<[^>]+>", "",
                              (e.findtext("a:summary", default="", namespaces=ns) or ""))[:400]
                pub = (e.findtext("a:updated", default="", namespaces=ns) or "").strip()
                if title:
                    out.append({"title": title, "link": link, "summary": summ,
                                "source": source, "published": pub,
                                "ts": _parse_date(pub),
                                "sentiment": sentiment_score(title + " " + summ)})
                if len(out) >= max_items:
                    break
    except Exception as e:
        log.warning("RSS %s failed: %s", url, e)
    return out


def _parse_date(s: str) -> float:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s.strip(), fmt).timestamp()
        except Exception:
            continue
    return time.time()


def fetch_news(force: bool = False, max_age: int = 600) -> list:
    """All feeds merged, newest first. Cached 10 min."""
    if not force and _cache["items"] and time.time() - _cache["ts"] < max_age:
        return _cache["items"]
    feeds = CONFIG.get("news", "rss_feeds", default=[])
    per_feed = CONFIG.get("news", "max_items_per_feed", default=25)
    items = []
    names = {"https://cointelegraph.com/rss": "CoinTelegraph",
             "https://www.coindesk.com/arc/outboundfeeds/rss/": "CoinDesk",
             "https://decrypt.co/feed": "Decrypt",
             "https://bitcoinmagazine.com/.rss/full/": "Bitcoin Magazine"}
    for url in feeds:
        items += _parse_rss(url, per_feed, names.get(url, url.split("/")[2]))
    items.sort(key=lambda i: -(i.get("ts") or 0))
    _cache["items"], _cache["ts"] = items, time.time()
    return items


def news_for_coin(coin: str = None, limit: int = 30) -> dict:
    """Filter news for a coin (BTC, ETH, SOL...). Without coin -> general feed."""
    items = fetch_news()
    coin = (coin or "").upper().replace("USDT", "").replace("/", "")
    if coin:
        kw = {coin, coin.lower()}
        alias = {"BTC": {"bitcoin"}, "ETH": {"ethereum", "ether"},
                 "SOL": {"solana"}, "BNB": {"binance coin", "bnb chain"},
                 "XRP": {"ripple"}, "DOGE": {"dogecoin", "doge"},
                 "ADA": {"cardano"}, "AVAX": {"avalanche"},
                 "LINK": {"chainlink"}, "DOT": {"polkadot"}}
        kw |= alias.get(coin, set())
        filtered = [i for i in items
                    if any(k in i["title"].lower() or k in i["summary"].lower() for k in kw)]
    else:
        filtered = items
    filtered = filtered[:limit]
    avg_sent = round(sum(i["sentiment"] for i in filtered) / len(filtered), 2) if filtered else 0.0
    return {"coin": coin or "GENERAL", "count": len(filtered),
            "avg_sentiment": avg_sent, "items": filtered}


def fear_greed() -> dict:
    """alternative.me crypto fear & greed index (free)."""
    if _cache["fng"] and time.time() - _cache["fng_ts"] < 900:
        return _cache["fng"]
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=2", headers=UA, timeout=10)
        d = r.json()["data"]
        cur = d[0]
        out = {"value": int(cur["value"]), "label": cur["value_classification"],
               "prev_value": int(d[1]["value"]) if len(d) > 1 else None,
               "ts": int(cur.get("timestamp", time.time()))}
        zone = ("EXTREME FEAR - historically accumulation territory" if out["value"] <= 25 else
                "FEAR" if out["value"] <= 45 else
                "NEUTRAL" if out["value"] <= 55 else
                "GREED" if out["value"] <= 75 else
                "EXTREME GREED - caution, historically distribution territory")
        out["interpretation"] = zone
        _cache["fng"], _cache["fng_ts"] = out, time.time()
        return out
    except Exception as e:
        return {"value": None, "label": "unavailable", "error": str(e)[:120]}


def binance_announcements(limit: int = 15) -> list:
    """Binance futures/new listings announcements (public, best-effort)."""
    if _cache["ann"] and time.time() - _cache["ann_ts"] < 600:
        return _cache["ann"]
    url = ("https://www.binance.com/bapi/apex/v1/public/apex/cms/article/list/query"
           "?type=1&pageNo=1&pageSize=" + str(limit))
    try:
        r = requests.get(url, headers=UA, timeout=10)
        d = r.json()
        arts = d.get("data", {}).get("articles", []) or []
        out = [{"title": a.get("title"), "code": a.get("code"),
                "ts": a.get("releaseDate")} for a in arts]
        _cache["ann"], _cache["ann_ts"] = out, time.time()
        return out
    except Exception as e:
        log.warning("binance announcements failed: %s", e)
        return []
