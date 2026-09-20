"""
AlphaWave Accuracy Engine v2.

Four concrete upgrades that materially raise signal quality:

1. WALK-FORWARD ADAPTIVE WEIGHTS  — every strategy engine is replayed on
   recent history of the same symbol/timeframe; engines that actually
   predicted the next candles correctly get heavier voting weight, engines
   that failed get down-weighted. Weights are cached (15 min).

2. REALIZED-OUTCOME LEARNING     — signals in the journal are followed up:
   did price reach TP or SL first? Per-strategy win/loss stats are stored in
   data/strategy_stats.json and blended into the weights, so the engine
   keeps learning from its own live record.

3. MULTI-TIMEFRAME (HTF) GATE    — a signal may only run with the higher
   timeframe bias, unless the counter-trend confluence is extremely strong.
   Counter-trend signals with weak confidence are converted to NO TRADE.

4. MARKET QUALITY GATES          — dead markets (tiny ATR), chaotic markets
   (huge ATR), illiquid books and wide spreads are refused outright; stale
   triggers and extreme funding apply confidence penalties.
"""

import json
import os
import time
import threading
import logging

import numpy as np
import pandas as pd

from .config import CONFIG, DATA_DIR
from . import binance_client as bc
from . import indicators as ind
from . import strategies as st

log = logging.getLogger("accuracy")

STATS_PATH = os.path.join(DATA_DIR, "strategy_stats.json")
_lock = threading.Lock()
_wf_cache = {}          # (symbol, interval) -> (ts, weights_dict)
WF_TTL = 900            # 15 min

HTF_MAP = {"1m": "5m", "3m": "15m", "5m": "15m", "15m": "1h", "30m": "2h",
           "1h": "4h", "2h": "8h", "4h": "1d", "6h": "1d", "8h": "1d",
           "12h": "1d", "1d": "1d"}

FEE_THR = 0.0006        # ~taker fee both sides


# ------------------------------------------------------------------ storage

def _load_stats() -> dict:
    try:
        with open(STATS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"strategies": {}, "evaluated": []}


def _save_stats(d: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with _lock:
        tmp = STATS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, STATS_PATH)


# ------------------------------------------------- 1) walk-forward weights

def walkforward_weights(symbol: str, interval: str, lookback: int = 260,
                        step: int = 14, horizon: int = 8, force: bool = False) -> dict:
    """Replay the 8 engines over recent history; weight = f(hit-rate)."""
    key = (symbol, interval)
    now = time.time()
    if not force:
        hit = _wf_cache.get(key)
        if hit and now - hit[0] < WF_TTL:
            return hit[1]
    weights = {name: 1.0 for name in st.STRATEGIES}
    try:
        df_full = bc.klines(symbol, interval, 500)
        if len(df_full) < lookback + horizon + 40:
            _wf_cache[key] = (now, weights)
            return weights
        hits = {name: [0, 0] for name in st.STRATEGIES}  # [correct, total]
        for start in range(lookback, len(df_full) - horizon + 1, step):
            df = df_full.iloc[:start]
            try:
                a = ind.build_analysis(df)
                votes = st.run_strategies(df, a)
            except Exception:
                continue
            fut = float(df_full["close"].iloc[start + horizon - 1]) / \
                float(df_full["close"].iloc[start - 1]) - 1.0
            thr = max(a["atr_pct"] / 100.0 * 0.35, FEE_THR)
            for v in votes:
                if v["direction"] == "NEUTRAL" or v["strength"] < 25:
                    continue
                pred = 1.0 if v["direction"] == "LONG" else -1.0
                hits[v["name"]][1] += 1
                if pred * fut > thr:
                    hits[v["name"]][0] += 1
        for name, (ok, tot) in hits.items():
            if tot >= 4:
                rate = ok / tot
                weights[name] = round(min(max(0.45 + 1.3 * rate, 0.4), 2.0), 2)
        _wf_cache[key] = (now, weights)
    except Exception as e:
        log.warning("walkforward failed %s %s: %s", symbol, interval, e)
    return weights


# ------------------------------------------------- 2) realized outcomes

def refresh_outcomes(max_signals: int = 40, horizon_candles: int = 60) -> dict:
    """Follow up journal signals: TP or SL first? Update per-strategy stats."""
    from . import signal_engine
    stats = _load_stats()
    evaluated = set(stats.get("evaluated", []))
    strat = stats.setdefault("strategies", {})
    changed = False
    done_keys = []
    for sig in signal_engine.journal_list(200)[:max_signals]:
        sig_id = f"{sig.get('generated_at')}|{sig.get('coin')}|{sig.get('timeframe')}"
        if sig_id in evaluated or sig.get("side") not in ("LONG", "SHORT"):
            continue
        entry, sl, tp = sig.get("entry_price"), sig.get("stop_loss"), sig.get("take_profit")
        if not entry or not sl or not tp:
            continue
        try:
            ts = pd.Timestamp(sig["generated_at"])
            now = pd.Timestamp.now(tz="UTC")
            if (now - ts).total_seconds() < 300:
                continue  # too young
            df = bc.klines(sig["coin"], sig["timeframe"], horizon_candles + 5)
            iv_ms = {"1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000,
                     "30m": 1800000, "1h": 3600000, "2h": 7200000, "4h": 14400000,
                     "6h": 21600000, "8h": 28800000, "12h": 43200000,
                     "1d": 86400000}.get(sig["timeframe"], 900000)
            start_ms = int(ts.timestamp() * 1000)
            after = df[df.index >= start_ms]
            if len(after) < 3:
                continue  # not enough candles elapsed yet
            result = None
            for _t, r in after.iterrows():
                if sig["side"] == "LONG":
                    if r["low"] <= sl:
                        result = "loss"
                        break
                    if r["high"] >= tp:
                        result = "win"
                        break
                else:
                    if r["high"] >= sl:
                        result = "loss"
                        break
                    if r["low"] <= tp:
                        result = "win"
                        break
            if result is None:
                if len(after) >= horizon_candles:
                    # expired: judge by direction vs entry
                    last = float(after["close"].iloc[-1])
                    good = (last > entry) if sig["side"] == "LONG" else (last < entry)
                    result = "win" if good else "loss"
                else:
                    continue  # still open
            agreeing = [v["strategy"] for v in sig.get("strategy_breakdown", [])
                        if v.get("direction") == sig["side"]]
            display_to_name = {d: n for n, d in st.DISPLAY_NAMES.items()}
            for disp in agreeing:
                nm = display_to_name.get(disp, disp)
                rec = strat.setdefault(nm, {"wins": 0, "losses": 0})
                rec["wins" if result == "win" else "losses"] += 1
            changed = True
            done_keys.append(sig_id)
        except Exception as e:
            log.debug("outcome eval skip %s: %s", sig_id, e)
            continue
    if done_keys:
        evaluated.update(done_keys)
        stats["evaluated"] = list(evaluated)[-2000:]
    if changed or done_keys:
        _save_stats(stats)
    return stats


def outcome_weights() -> dict:
    stats = _load_stats()
    out = {}
    for name, rec in stats.get("strategies", {}).items():
        tot = rec.get("wins", 0) + rec.get("losses", 0)
        if tot >= 4:
            rate = rec["wins"] / tot
            out[name] = round(min(max(0.6 + 0.9 * rate, 0.5), 1.8), 2)
    return out


def blended_weights(symbol: str, interval: str) -> dict:
    wf = walkforward_weights(symbol, interval)
    ow = outcome_weights()
    final = {}
    for name in st.STRATEGIES:
        final[name] = round(min(max(wf.get(name, 1.0) * ow.get(name, 1.0), 0.3), 2.2), 2)
    return final


# ------------------------------------------------- 3) HTF gate

def htf_bias(symbol: str, interval: str) -> dict:
    htf = HTF_MAP.get(interval, "1d")
    if htf == interval:
        htf = "1d" if interval != "1d" else "1d"
    try:
        df = bc.klines(symbol, htf, 250)
        a = ind.build_analysis(df)
        trend = a["trend"]
        st_dir = a["st_dir"]
        adx_v = a["adx_val"]
        if trend == "UP" and st_dir == 1:
            bias = "LONG"
        elif trend == "DOWN" and st_dir == -1:
            bias = "SHORT"
        else:
            bias = "NEUTRAL"
        return {"timeframe": htf, "bias": bias, "trend": trend,
                "supertrend": "UP" if st_dir == 1 else "DOWN",
                "adx": round(float(adx_v), 1), "price": a["price"]}
    except Exception as e:
        return {"timeframe": htf, "bias": "NEUTRAL", "trend": "RANGE",
                "supertrend": "?", "adx": 0.0, "error": str(e)[:80]}


# ------------------------------------------------- 4) quality gates

def quality_gates(df: pd.DataFrame, a: dict, snap: dict) -> dict:
    """Hard refusals + soft penalties. Returns {hard:[...], soft:[...]}."""
    hard, soft = [], []
    atr_pct = a["atr_pct"]
    if atr_pct < 0.04:
        hard.append(f"DEAD MARKET: ATR {atr_pct:.3f}%/candle - no tradable movement")
    if atr_pct > 4.0:
        hard.append(f"CHAOTIC MARKET: ATR {atr_pct:.2f}%/candle - uncontrollable risk")
    qv = float(snap.get("quote_volume_24h", 0) or 0)
    if qv < 1_500_000:
        hard.append(f"ILLIQUID: 24h volume ${qv/1e6:.1f}M < $1.5M")
    # spread check (one lightweight call, tolerant of failure)
    try:
        sym = snap.get("symbol")
        if sym:
            d = bc.depth(sym, 5)
            bid = float(d["bids"][0][0])
            ask = float(d["asks"][0][0])
            spread_pct = (ask - bid) / ((ask + bid) / 2) * 100
            if spread_pct > 0.10:
                hard.append(f"WIDE SPREAD: {spread_pct:.3f}% > 0.10%")
            elif spread_pct > 0.04:
                soft.append(f"spread {spread_pct:.3f}% slightly wide")
    except Exception:
        pass
    fr = float(snap.get("funding_rate", 0) or 0)
    if abs(fr) > 0.0008:
        soft.append(f"EXTREME FUNDING {fr*100:.4f}% - crowded positioning, expect squeezes")
    adx_v = a["adx_val"]
    if adx_v < 14 and a["trend"] != "RANGE":
        soft.append(f"weak trend strength (ADX {adx_v:.0f})")
    return {"hard": hard, "soft": soft}


def trigger_age(a: dict, max_fresh: int = 6) -> int:
    """Candles since the most recent strategy event (freshness of trigger)."""
    ev = a.get("events", [])
    n = len(a.get("cvd", [])) or 0
    if not ev:
        return 999
    return max(0, n - 1 - ev[-1]["pos"])


# ------------------------------------------------------------ snapshot API

def snapshot(symbol: str, interval: str) -> dict:
    """For /accuracy command & GUI: current learned weights + stats."""
    stats = _load_stats()
    wf = walkforward_weights(symbol, interval)
    ow = outcome_weights()
    rows = []
    for name, disp in st.DISPLAY_NAMES.items():
        rec = stats.get("strategies", {}).get(name, {})
        tot = rec.get("wins", 0) + rec.get("losses", 0)
        rows.append({
            "engine": disp,
            "walkforward_weight": wf.get(name, 1.0),
            "live_record_weight": ow.get(name, 1.0),
            "blended_weight": round(wf.get(name, 1.0) * ow.get(name, 1.0), 2),
            "live_wins": rec.get("wins", 0),
            "live_losses": rec.get("losses", 0),
            "live_winrate_pct": round(rec["wins"] / tot * 100, 1) if tot else None,
        })
    return {"symbol": symbol, "interval": interval, "engines": rows,
            "evaluated_signals": len(stats.get("evaluated", []))}
