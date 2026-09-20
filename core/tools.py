"""
30 trading & analysis helper features.

Every tool is a plain function returning JSON-serializable data so the GUI
(Tools tab) and the Telegram bot (/tools menu) share the exact same engine.
None of these place orders - analysis only.
"""

import time
import math
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import binance_client as bc
from . import indicators as ind
from . import news as news_mod
from . import signal_engine
from .config import CONFIG

log = logging.getLogger("tools")


def _ctx(symbol, interval="15m", limit=300):
    df = bc.klines(symbol, interval, limit)
    a = ind.build_analysis(df)
    return df, a


def _f(x, n=6):
    try:
        return round(float(x), n)
    except Exception:
        return None


# ------------------------------------------------------------- 1..30 tools

def t01_trend_scanner(symbol, **kw):
    """Multi-timeframe trend scanner."""
    rows = []
    for iv in ["15m", "1h", "4h", "1d"]:
        try:
            df = bc.klines(symbol, iv, 220)
            c = df["close"]
            price = float(c.iloc[-1])
            e50 = float(ind.ema(c, 50).iloc[-1])
            e200 = float(ind.ema(c, 200).iloc[-1])
            adx_v = float(ind.adx(df, 14)[0].iloc[-1])
            trend = "UP" if price > e50 > e200 else "DOWN" if price < e50 < e200 else "RANGE"
            rows.append({"timeframe": iv, "trend": trend, "adx": _f(adx_v, 1),
                         "ema50": _f(e50), "ema200": _f(e200)})
        except Exception as e:
            rows.append({"timeframe": iv, "error": str(e)[:80]})
    aligned = all(r.get("trend") == rows[0].get("trend") for r in rows)
    return {"symbol": symbol, "rows": rows, "all_timeframes_aligned": aligned,
            "summary": f"{symbol}: " + " / ".join(f"{r['timeframe']}={r.get('trend','?')}" for r in rows)}


def t02_support_resistance(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "1h"), 400)
    price = a["price"]
    highs = [v for _, v in a["swing_highs"][-30:]] + [a["range_high"]]
    lows = [v for _, v in a["swing_lows"][-30:]] + [a["range_low"]]
    from .strategies import _cluster_levels
    res = [{"level": _f(p), "touches": t} for p, t in _cluster_levels(highs) if p > price][:6]
    sup = [{"level": _f(p), "touches": t} for p, t in _cluster_levels(lows) if p < price][:6]
    return {"symbol": symbol, "price": _f(price), "resistance": res, "support": sup}


def t03_fibonacci(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "4h"), 400)
    zz = a["zigzag"]
    if len(zz) >= 2:
        (p0, v0, t0), (p1, v1, t1) = zz[-2], zz[-1]
        hi, lo = max(v0, v1), min(v0, v1)
        direction = "UP" if v1 > v0 else "DOWN"
    else:
        hi, lo, direction = a["range_high"], a["range_low"], "RANGE"
    fibs = ind.fib_levels(lo, hi)
    return {"symbol": symbol, "swing_high": _f(hi), "swing_low": _f(lo),
            "last_leg": direction,
            "retracements": {k: _f(v) for k, v in fibs.items() if float(k) <= 1.0},
            "extensions": {k: _f(v) for k, v in fibs.items() if float(k) > 1.0},
            "ote_zone": [_f(fibs["0.79"]), _f(fibs["0.618"])],
            "price": _f(a["price"])}


def t04_orderflow_delta(symbol, **kw):
    df, a = _ctx(symbol, "5m", 200)
    delta = a["delta"]
    cvd_s = a["cvd"]
    buy_vol = float(df["taker_buy_base"].tail(20).sum())
    sell_vol = float((df["volume"] - df["taker_buy_base"]).tail(20).sum())
    ratio = buy_vol / (sell_vol + 1e-9)
    return {"symbol": symbol,
            "cvd": _f(float(cvd_s.iloc[-1]), 2),
            "cvd_slope_10": _f(float(a["cvd_slope_val"]), 3),
            "delta_last_candle": _f(float(delta.iloc[-1]), 2),
            "delta_sum_20": _f(float(delta.tail(20).sum()), 2),
            "taker_buy_sell_ratio_20x5m": _f(ratio, 3),
            "interpretation": ("aggressive buyers dominate" if ratio > 1.15 else
                               "aggressive sellers dominate" if ratio < 0.87 else
                               "balanced two-sided flow")}


def t05_funding_rate(symbol, **kw):
    prem = bc.premium_index(symbol)
    prem = prem[0] if isinstance(prem, list) else prem
    fr = float(prem.get("lastFundingRate", 0))
    nft = int(prem.get("nextFundingTime", 0))
    return {"symbol": symbol, "funding_rate_pct": _f(fr * 100, 4),
            "mark_price": _f(prem.get("markPrice")), "index_price": _f(prem.get("indexPrice")),
            "next_funding_in_min": int((nft - time.time() * 1000) / 60000) if nft else None,
            "interpretation": ("longs pay shorts (crowded long)" if fr > 0.0005 else
                               "shorts pay longs (crowded short)" if fr < -0.0005 else
                               "neutral funding")}


def t06_open_interest(symbol, **kw):
    oi = bc.open_interest(symbol)
    hist = bc.open_interest_hist(symbol, "1h", 24)
    oi_val = float(oi.get("openInterest", 0))
    change = None
    if len(hist) >= 2:
        first = float(hist[0].get("sumOpenInterestValue", hist[0].get("sumOpenInterest", 0)))
        lastv = float(hist[-1].get("sumOpenInterestValue", hist[-1].get("sumOpenInterest", 0)))
        change = (lastv - first) / (first + 1e-9) * 100
    return {"symbol": symbol, "open_interest_coins": _f(oi_val, 2),
            "oi_change_24h_pct": _f(change, 2),
            "interpretation": ("new money entering (OI rising)" if (change or 0) > 5 else
                               "positions unwinding (OI falling)" if (change or 0) < -5 else
                               "stable positioning")}


def t07_long_short_ratio(symbol, **kw):
    acc = bc.long_short_ratio(symbol, "1h", 12)
    tk = bc.taker_long_short_ratio(symbol, "1h", 12)
    top_acc = float(acc[-1]["longShortRatio"]) if acc else None
    taker = float(tk[-1]["buySellRatio"]) if tk else None
    return {"symbol": symbol, "top_trader_account_ls": _f(top_acc, 3),
            "global_taker_buy_sell": _f(taker, 3),
            "series_accounts": [{"t": x.get("timestamp"), "r": _f(x.get("longShortRatio"), 3)} for x in acc],
            "interpretation": ("retail/top accounts net long" if (top_acc or 1) > 1.3 else
                               "net short" if (top_acc or 1) < 0.77 else "balanced")}


def t08_liquidation_zones(symbol, **kw):
    """Estimated liquidity clusters (where resting stops/liquidity likely sits)."""
    df, a = _ctx(symbol, "1h", 300)
    price = a["price"]
    sh = [v for _, v in a["swing_highs"][-15:] if v > price]
    sl = [v for _, v in a["swing_lows"][-15:] if v < price]
    eq_highs = sorted(set(round(x, 6) for x in sh), reverse=True)[:4]
    eq_lows = sorted(set(round(x, 6) for x in sl))[:4]
    return {"symbol": symbol, "price": _f(price),
            "buy_side_liquidity_above": [_f(x) for x in eq_highs],
            "sell_side_liquidity_below": [_f(x) for x in eq_lows],
            "note": "Estimated pools where stop-loss liquidity clusters; price often raids these."}


def t09_fear_greed(symbol=None, **kw):
    return news_mod.fear_greed()


def t10_market_breadth(symbol=None, **kw):
    """% of the top-100 futures coins above their 20-period 4h EMA."""
    syms = sorted(bc.ticker_24h(), key=lambda t: -float(t.get("quoteVolume", 0) or 0))
    syms = [t["symbol"] for t in syms[:60]]

    def above(s):
        try:
            df = bc.klines(s, "4h", 40)
            return float(df["close"].iloc[-1]) > float(ind.ema(df["close"], 20).iloc[-1])
        except Exception:
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(above, syms))
    valid = [r for r in res if r is not None]
    pct = sum(valid) / (len(valid) or 1) * 100
    return {"coins_scanned": len(valid), "pct_above_ema20_4h": round(pct, 1),
            "regime": ("risk-on (breadth strong)" if pct > 65 else
                       "risk-off (breadth weak)" if pct < 35 else "mixed/choppy")}


def t11_top_movers(symbol=None, **kw):
    ts = bc.ticker_24h()
    valid = [t for t in ts if t.get("symbol", "").endswith("USDT")
             and float(t.get("quoteVolume", 0) or 0) > 2e6]
    valid.sort(key=lambda t: -float(t.get("priceChangePercent", 0) or 0))
    fmt = lambda t: {"symbol": t["symbol"],
                     "change_pct": _f(t.get("priceChangePercent"), 2),
                     "price": t.get("lastPrice"),
                     "vol_musd": _f(float(t.get("quoteVolume", 0)) / 1e6, 1)}
    return {"gainers": [fmt(t) for t in valid[:10]],
            "losers": [fmt(t) for t in valid[-10:][::-1]]}


def t12_volume_spikes(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "15m"), 200)
    vs = a["vol_sma20"]
    spikes = []
    for i in range(len(df) - 40, len(df)):
        if vs.iloc[i] > 0 and df["volume"].iloc[i] > 2.0 * vs.iloc[i]:
            spikes.append({"time": int(df.index[i]),
                           "volume": _f(df["volume"].iloc[i], 1),
                           "x_avg": _f(df["volume"].iloc[i] / vs.iloc[i], 2),
                           "candle": "GREEN" if df["close"].iloc[i] >= df["open"].iloc[i] else "RED",
                           "delta": _f(a["delta"].iloc[i], 1)})
    return {"symbol": symbol, "spikes": spikes,
            "summary": f"{len(spikes)} volume spike(s) in last 40 candles"}


def t13_breakout_detector(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "1h"), 200)
    price = a["price"]
    du, dl = float(a["donchian_upper"].iloc[-2]), float(a["donchian_lower"].iloc[-2])
    bw = float(a["bb_width"].iloc[-1])
    bw_avg = float(a["bb_width"].tail(100).mean())
    state = "INSIDE"
    if price > du:
        state = "BREAKOUT UP (20-candle high)"
    elif price < dl:
        state = "BREAKDOWN (20-candle low)"
    return {"symbol": symbol, "price": _f(price), "donchian_high": _f(du),
            "donchian_low": _f(dl), "state": state,
            "bb_squeeze": bool(bw < 0.75 * bw_avg),
            "bb_width": _f(bw, 4), "bb_width_avg100": _f(bw_avg, 4),
            "note": "Bollinger squeeze often precedes explosive moves."}


def t14_rsi_divergence(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "1h"), 300)
    r = a["rsi"]
    lows = a["swing_lows"][-6:]
    highs = a["swing_highs"][-6:]
    out = {"symbol": symbol, "bullish_divergence": False, "bearish_divergence": False, "detail": ""}
    if len(lows) >= 2:
        (p0, v0), (p1, v1) = lows[-2], lows[-1]
        if v1 < v0 and float(r.iloc[p1]) > float(r.iloc[p0]):
            out["bullish_divergence"] = True
            out["detail"] = f"price made LOWER LOW ({_f(v1)}) but RSI made HIGHER LOW -> bullish divergence"
    if len(highs) >= 2:
        (p0, v0), (p1, v1) = highs[-2], highs[-1]
        if v1 > v0 and float(r.iloc[p1]) < float(r.iloc[p0]):
            out["bearish_divergence"] = True
            out["detail"] = (out["detail"] + " | " if out["detail"] else "") + \
                f"price made HIGHER HIGH ({_f(v1)}) but RSI made LOWER HIGH -> bearish divergence"
    if not out["detail"]:
        out["detail"] = "no swing divergence detected in recent structure"
    out["rsi"] = _f(a["rsi_val"], 1)
    return out


def t15_macd_signals(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "1h"), 200)
    mh = a["macd_hist"]
    cross = "BULLISH CROSS" if mh.iloc[-2] <= 0 < mh.iloc[-1] else \
            "BEARISH CROSS" if mh.iloc[-2] >= 0 > mh.iloc[-1] else \
            "above zero (bullish momentum)" if mh.iloc[-1] > 0 else "below zero (bearish momentum)"
    growing = abs(float(mh.iloc[-1])) > abs(float(mh.iloc[-2]))
    return {"symbol": symbol, "macd": _f(a["macd"].iloc[-1], 6),
            "signal": _f(a["macd_signal"].iloc[-1], 6),
            "histogram": _f(mh.iloc[-1], 6), "state": cross,
            "momentum_growing": growing}


def t16_bollinger_squeeze(symbol, **kw):
    return t13_breakout_detector(symbol, **kw)


def t17_supertrend_status(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "1h"), 250)
    stv = a["supertrend"]
    dirn = int(a["supertrend_dir"].iloc[-1])
    flips = [i for i in range(len(df) - 30, len(df))
             if i > 0 and a["supertrend_dir"].iloc[i] != a["supertrend_dir"].iloc[i - 1]]
    last_flip_time = int(df.index[flips[-1]]) if flips else None
    return {"symbol": symbol, "supertrend": _f(stv.iloc[-1]),
            "direction": "UP (long bias)" if dirn == 1 else "DOWN (short bias)",
            "last_flip_time": last_flip_time,
            "flips_last_30": len(flips)}


def t18_ema_ribbon(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "1h"), 250)
    price = a["price"]
    emas = {n: float(a[f"ema{n}"].iloc[-1]) for n in [9, 20, 50, 100, 200]}
    stack_up = emas[9] > emas[20] > emas[50] > emas[200]
    stack_dn = emas[9] < emas[20] < emas[50] < emas[200]
    return {"symbol": symbol, "price": _f(price), "emas": {k: _f(v) for k, v in emas.items()},
            "alignment": "PERFECT BULL STACK" if stack_up else
                         "PERFECT BEAR STACK" if stack_dn else "MIXED",
            "price_vs_ema200_pct": _f((price - emas[200]) / emas[200] * 100, 2)}


def t19_ichimoku_status(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "4h"), 200)
    price = a["price"]
    tk, kj = float(a["tenkan"].iloc[-1]), float(a["kijun"].iloc[-1])
    sa, sb = float(a["senkou_a"].iloc[-1]), float(a["senkou_b"].iloc[-1])
    cloud_top, cloud_bot = max(sa, sb), min(sa, sb)
    pos = "ABOVE cloud (bullish)" if price > cloud_top else \
          "INSIDE cloud (indecision)" if price > cloud_bot else "BELOW cloud (bearish)"
    return {"symbol": symbol, "tenkan": _f(tk), "kijun": _f(kj),
            "cloud": [_f(cloud_bot), _f(cloud_top)], "price_position": pos,
            "tk_cross": "bullish (T>K)" if tk > kj else "bearish (T<K)"}


def t20_vwap_deviation(symbol, **kw):
    df, a = _ctx(symbol, kw.get("interval", "15m"), 200)
    price, vw = a["price"], float(a["vwap"].iloc[-1])
    dev = (price - vw) / (vw + 1e-12) * 100
    sd = float(df["close"].tail(50).std())
    return {"symbol": symbol, "vwap": _f(vw), "price": _f(price),
            "deviation_pct": _f(dev, 3),
            "interpretation": ("stretched above VWAP - reversion risk" if dev > 2 else
                               "stretched below VWAP - bounce potential" if dev < -2 else
                               "trading near VWAP (fair value)")}


def t21_position_size(symbol=None, **kw):
    """ATR-based position sizing from risk %."""
    balance = float(kw.get("balance") or CONFIG.get("trading", "account_balance_usdt", default=1000))
    risk_pct = float(kw.get("risk_pct") or CONFIG.get("trading", "risk_percent", default=1.0))
    leverage = float(kw.get("leverage", 10) or 10)
    entry = float(kw.get("entry", 0) or 0)
    sl = float(kw.get("stop_loss", 0) or 0)
    if not symbol or (entry <= 0 or sl <= 0):
        return {"error": "needs symbol + entry + stop_loss (or pass via params)",
                "formula": "qty = (balance * risk%) / |entry - SL|",
                "balance": balance, "risk_pct": risk_pct, "leverage": leverage}
    risk_usd = balance * risk_pct / 100
    dist = abs(entry - sl)
    qty = risk_usd / dist if dist else 0
    notional = qty * entry
    return {"symbol": symbol, "balance": balance, "risk_pct": risk_pct,
            "risk_usd": _f(risk_usd, 2), "entry": entry, "stop_loss": sl,
            "stop_distance_pct": _f(dist / entry * 100, 3),
            "position_qty": _f(qty, 6), "notional_usd": _f(notional, 2),
            "leverage_used": leverage,
            "margin_needed_usd": _f(notional / leverage, 2)}


def t22_risk_reward(symbol=None, **kw):
    entry = float(kw.get("entry", 0) or 0)
    sl = float(kw.get("stop_loss", 0) or 0)
    tp = float(kw.get("take_profit", 0) or 0)
    if not entry or not sl or not tp:
        return {"error": "needs entry, stop_loss, take_profit"}
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    side = "LONG" if (tp > entry) == (sl < entry) and tp > entry else "SHORT" if tp < entry else "LONG"
    rr = reward / (risk + 1e-12)
    win_rate_needed = 100 / (1 + rr)
    return {"side_implied": side, "risk": _f(risk), "reward": _f(reward),
            "risk_reward_ratio": _f(rr, 2),
            "breakeven_win_rate_pct": _f(win_rate_needed, 1),
            "verdict": "good (>=2R)" if rr >= 2 else "acceptable (>=1.5R)" if rr >= 1.5 else "poor (<1.5R)"}


def t23_liquidation_price(symbol=None, **kw):
    """Estimate liquidation price for a hypothetical isolated-margin position."""
    entry = float(kw.get("entry", 0) or 0)
    lev = float(kw.get("leverage", 10) or 10)
    side = str(kw.get("side", "long")).lower()
    mmr = 0.005  # ~0.5% maintenance margin assumption
    if not entry:
        return {"error": "needs entry price and leverage and side (long/short)"}
    if side.startswith("l"):
        liq = entry * (1 - 1 / lev + mmr)
    else:
        liq = entry * (1 + 1 / lev - mmr)
    return {"entry": entry, "leverage": lev, "side": side,
            "estimated_liquidation_price": _f(liq),
            "distance_pct": _f(abs(liq - entry) / entry * 100, 2),
            "note": "Estimate only (isolated margin, MMR~0.5%); real value depends on Binance tiers."}


def t24_funding_cost(symbol, **kw):
    prem = bc.premium_index(symbol)
    prem = prem[0] if isinstance(prem, list) else prem
    fr = float(prem.get("lastFundingRate", 0))
    notional = float(kw.get("notional", 1000) or 1000)
    side = str(kw.get("side", "long")).lower()
    pay = notional * fr * (1 if side.startswith("l") else -1)
    return {"symbol": symbol, "funding_rate_pct": _f(fr * 100, 4),
            "notional_usd": notional, "side": side,
            "cost_per_funding_usd": _f(pay, 4),
            "cost_per_day_usd": _f(pay * 3, 4),
            "note": "Positive = longs pay shorts. 3 fundings/day."}


def t25_correlation(symbol, **kw):
    """Correlation vs BTC and ETH (1h returns, 100 candles)."""
    out = {"symbol": symbol, "window": "100 x 1h returns"}
    try:
        c = bc.klines(symbol, "1h", 101)["close"].pct_change().dropna()
        for ref in ["BTCUSDT", "ETHUSDT"]:
            if ref == symbol:
                continue
            r = bc.klines(ref, "1h", 101)["close"].pct_change().dropna()
            n = min(len(c), len(r))
            out[f"corr_vs_{ref.replace('USDT','')}"] = _f(float(np.corrcoef(c.tail(n), r.tail(n))[0, 1]), 3)
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


def t26_volatility_rank(symbol=None, **kw):
    ts = bc.ticker_24h()
    valid = [t for t in ts if t.get("symbol", "").endswith("USDT")
             and float(t.get("quoteVolume", 0) or 0) > 5e6]
    def rng(t):
        hi, lo, last = (float(t.get(x, 0) or 0) for x in ("highPrice", "lowPrice", "lastPrice"))
        return (hi - lo) / (last + 1e-9) * 100
    valid.sort(key=rng, reverse=True)
    top = [{"symbol": t["symbol"], "range_24h_pct": _f(rng(t), 2)} for t in valid[:15]]
    pos = next((i for i, t in enumerate(valid) if t["symbol"] == symbol), None) if symbol else None
    return {"most_volatile_15": top,
            "your_coin_rank": (pos + 1) if pos is not None else None,
            "universe": len(valid)}


def t27_news_sentiment(symbol=None, **kw):
    coin = (symbol or "").upper().replace("USDT", "") if symbol else None
    return news_mod.news_for_coin(coin, limit=15)


def t28_dominance_snapshot(symbol=None, **kw):
    ts = {t["symbol"]: t for t in bc.ticker_24h()}
    total = sum(float(t.get("quoteVolume", 0) or 0) for t in ts.values()) or 1
    btc = float(ts.get("BTCUSDT", {}).get("quoteVolume", 0) or 0)
    eth = float(ts.get("ETHUSDT", {}).get("quoteVolume", 0) or 0)
    return {"futures_volume_share_btc_pct": _f(btc / total * 100, 1),
            "futures_volume_share_eth_pct": _f(eth / total * 100, 1),
            "btc_price": ts.get("BTCUSDT", {}).get("lastPrice"),
            "btc_change_pct": _f(ts.get("BTCUSDT", {}).get("priceChangePercent"), 2),
            "eth_price": ts.get("ETHUSDT", {}).get("lastPrice"),
            "eth_change_pct": _f(ts.get("ETHUSDT", {}).get("priceChangePercent"), 2),
            "total_futures_volume_musd": _f(total / 1e6, 0)}


def t29_signal_journal(symbol=None, **kw):
    hist = signal_engine.journal_list(int(kw.get("limit", 20)))
    if symbol:
        sym = bc.normalize_symbol(symbol)
        hist = [h for h in hist if h.get("coin") == sym]
    return {"count": len(hist), "signals": hist}


def t30_mini_backtest(symbol, **kw):
    """Simple replay: EMA9/21 cross + RSI filter on last 500 candles."""
    interval = kw.get("interval", "1h")
    df = bc.klines(symbol, interval, 500)
    if len(df) < 120:
        return {"error": "not enough candles"}
    c = df["close"]
    e9, e21 = ind.ema(c, 9), ind.ema(c, 21)
    r = ind.rsi(c, 14)
    equity = 1.0
    pos = 0
    entry_p = 0.0
    trades = 0
    wins = 0
    fee = 0.0005
    curve = []
    for i in range(30, len(df)):
        px = float(c.iloc[i])
        if pos == 0:
            if e9.iloc[i] > e21.iloc[i] and e9.iloc[i-1] <= e21.iloc[i-1] and r.iloc[i] < 70:
                pos, entry_p, trades = 1, px, trades + 1
            elif e9.iloc[i] < e21.iloc[i] and e9.iloc[i-1] >= e21.iloc[i-1] and r.iloc[i] > 30:
                pos, entry_p, trades = -1, px, trades + 1
        else:
            exit_now = (pos == 1 and e9.iloc[i] < e21.iloc[i]) or (pos == -1 and e9.iloc[i] > e21.iloc[i])
            if exit_now:
                ret = pos * (px - entry_p) / entry_p - 2 * fee
                equity *= (1 + ret)
                wins += 1 if ret > 0 else 0
                pos = 0
        if i % 10 == 0:
            curve.append({"time": int(df.index[i]), "equity": round(equity, 4)})
    if pos != 0:
        px = float(c.iloc[-1])
        ret = pos * (px - entry_p) / entry_p - 2 * fee
        equity *= (1 + ret)
        wins += 1 if ret > 0 else 0
    return {"symbol": symbol, "interval": interval, "strategy": "EMA9/21 cross + RSI filter",
            "trades": trades, "wins": wins,
            "win_rate_pct": round(wins / trades * 100, 1) if trades else 0,
            "final_equity_x": round(equity, 4),
            "net_return_pct": round((equity - 1) * 100, 2),
            "equity_curve": curve,
            "note": "Simplified educational backtest with 0.05% taker fee per side."}


# ---------------------------------------------------------------- registry

TOOLS = [
    ("trend_scanner",        "Multi-Timeframe Trend Scanner", t01_trend_scanner, True),
    ("support_resistance",   "MNSR Support & Resistance Levels", t02_support_resistance, True),
    ("fibonacci",            "Fibonacci Retracement + OTE Zones", t03_fibonacci, True),
    ("orderflow_delta",      "Order Flow / CVD / Taker Delta", t04_orderflow_delta, True),
    ("funding_rate",         "Funding Rate Monitor", t05_funding_rate, True),
    ("open_interest",        "Open Interest + 24h Change", t06_open_interest, True),
    ("long_short_ratio",     "Long/Short Ratio (top traders & takers)", t07_long_short_ratio, True),
    ("liquidation_zones",    "Estimated Liquidity / Liquidation Zones", t08_liquidation_zones, True),
    ("fear_greed",           "Crypto Fear & Greed Index", t09_fear_greed, False),
    ("market_breadth",       "Market Breadth (60 coins vs EMA20-4h)", t10_market_breadth, False),
    ("top_movers",           "Top Gainers & Losers (24h)", t11_top_movers, False),
    ("volume_spikes",        "Volume Spike Detector", t12_volume_spikes, True),
    ("breakout_detector",    "Donchian Breakout Detector", t13_breakout_detector, True),
    ("rsi_divergence",       "RSI Divergence Scanner", t14_rsi_divergence, True),
    ("macd_signals",         "MACD Cross & Momentum", t15_macd_signals, True),
    ("bollinger_squeeze",    "Bollinger Squeeze Detector", t16_bollinger_squeeze, True),
    ("supertrend_status",    "SuperTrend Status & Flips", t17_supertrend_status, True),
    ("ema_ribbon",           "EMA Ribbon Alignment (9/20/50/100/200)", t18_ema_ribbon, True),
    ("ichimoku_status",      "Ichimoku Cloud Status", t19_ichimoku_status, True),
    ("vwap_deviation",       "VWAP Deviation", t20_vwap_deviation, True),
    ("position_size",        "Position Size Calculator (risk % + ATR)", t21_position_size, True),
    ("risk_reward",          "Risk/Reward + Breakeven Win Rate", t22_risk_reward, False),
    ("liquidation_price",    "Liquidation Price Estimator", t23_liquidation_price, False),
    ("funding_cost",         "Funding Cost Calculator", t24_funding_cost, True),
    ("correlation",          "Correlation vs BTC & ETH", t25_correlation, True),
    ("volatility_rank",      "Volatility Ranking (24h ranges)", t26_volatility_rank, False),
    ("news_sentiment",       "News + Sentiment per Coin", t27_news_sentiment, False),
    ("dominance_snapshot",   "BTC/ETH Futures Volume Dominance", t28_dominance_snapshot, False),
    ("signal_journal",       "Signal History Journal", t29_signal_journal, False),
    ("mini_backtest",        "Mini Strategy Backtester", t30_mini_backtest, True),
]

TOOL_MAP = {name: (display, fn, needs_symbol) for name, display, fn, needs_symbol in TOOLS}


def tool_list() -> list:
    return [{"id": i + 1, "name": n, "display": d, "needs_symbol": ns}
            for i, (n, d, _, ns) in enumerate(TOOLS)]


def run_tool(name: str, symbol: str = None, **params) -> dict:
    if name not in TOOL_MAP:
        return {"error": f"unknown tool '{name}'. available: {', '.join(TOOL_MAP)}"}
    display, fn, needs_symbol = TOOL_MAP[name]
    sym = bc.normalize_symbol(symbol) if symbol else None
    if needs_symbol and not sym:
        return {"error": f"'{display}' needs a valid futures symbol (e.g. BTC, ETHUSDT)"}
    t0 = time.time()
    try:
        data = fn(sym, **params)
    except Exception as e:
        log.exception("tool %s failed", name)
        return {"tool": name, "error": str(e)[:300]}
    if isinstance(data, dict):
        data.setdefault("tool", name)
        data.setdefault("display", display)
        data["elapsed_sec"] = round(time.time() - t0, 2)
    return data
