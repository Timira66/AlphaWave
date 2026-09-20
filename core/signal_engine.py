"""
Signal engine.

Produces complete trading signals:
    coin, live market price, side (LONG/SHORT), entry price, stop loss,
    take profit (+ TP levels), confidence, risk/reward and a detailed
    REASON describing which strategy / technique / logic generated it.

Also implements the RANDOM COIN FUNNEL:
    universe (<=1000 best by volume) -> top 100 -> top 10 -> best 1 -> signal

Signal numbers are ALWAYS computed from technical analysis; AI providers
(Groq / OpenRouter / Ollama / custom) only refine or explain. If every AI
fails, the built-in local engine finishes the signal - free of charge.
"""

import json
import os
import time
import logging
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .config import CONFIG, DATA_DIR
from . import binance_client as bc
from . import indicators as ind
from . import strategies as st
from . import ai_router
from . import accuracy
from . import local_ai

log = logging.getLogger("signal")

JOURNAL_PATH = os.path.join(DATA_DIR, "signals.json")
_journal_lock = threading.Lock()
_last_outcome_refresh = 0.0


# ------------------------------------------------------------------ journal

def journal_add(sig: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with _journal_lock:
        hist = []
        if os.path.exists(JOURNAL_PATH):
            try:
                with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
                    hist = json.load(f)
            except Exception:
                hist = []
        hist.insert(0, sig)
        hist = hist[:500]
        tmp = JOURNAL_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=1, ensure_ascii=False)
        os.replace(tmp, JOURNAL_PATH)


def journal_list(limit=50):
    if not os.path.exists(JOURNAL_PATH):
        return []
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)[:limit]
    except Exception:
        return []


# ----------------------------------------------------------- market context

def get_market_context(symbol: str, interval: str = None) -> dict:
    interval = interval or CONFIG.get("trading", "default_interval", default="15m")
    limit = CONFIG.get("trading", "klines_limit", default=300)
    df = bc.klines(symbol, interval, limit)
    if df.empty or len(df) < 60:
        raise ValueError(f"{symbol}: not enough candle data")
    a = ind.build_analysis(df)
    snap = bc.quick_price(symbol)
    a["funding_rate"] = snap.get("funding_rate")   # for the Funding Contrarian engine
    return {"symbol": symbol, "interval": interval, "df": df, "analysis": a, "snapshot": snap}


def _snapshot_for_prompt(a: dict, snap: dict) -> dict:
    return {
        "price": round(a["price"], 8),
        "trend": a.get("trend"),
        "rsi": round(a["rsi_val"], 1),
        "adx": round(a["adx_val"], 1),
        "atr": round(a["atr_val"], 8),
        "atr_pct": round(a["atr_pct"], 3),
        "macd_hist": round(a["macd_hist_val"], 8),
        "cvd_slope": round(a["cvd_slope_val"], 2),
        "bb_pos": round(a["bb_pos"], 2),
        "supertrend": "UP" if a["st_dir"] == 1 else "DOWN",
        "change_24h_pct": round(snap.get("change_24h_pct", 0), 2),
        "funding_rate_pct": round(snap.get("funding_rate", 0) * 100, 4),
        "quote_volume_24h_musd": round(snap.get("quote_volume_24h", 0) / 1e6, 1),
        "open_fvgs": len([g for g in a["fvgs"] if not g["filled"]]),
    }


# ------------------------------------------------------- levels computation

LEVERAGE_DEFAULTS = {
    "min": 10, "max": 20, "extreme_max": 30,
    "extreme_min_confidence": 85, "extreme_min_agree": 6,
    "extreme_min_rr": 2.0, "max_atr_pct_for_extreme": 1.0,
}


def compute_leverage(confidence: float, n_agree: int, n_total: int,
                     rr: float, atr_pct: float) -> dict:
    """
    AlphaWave leverage recommendation.

    STANDARD tier : leverage always kept inside [min, max]  (default 10x-20x),
                    scaled by confidence and adjusted for volatility.
    EXTREME tier  : leverage above 20x is issued ONLY for extremely
                    high-quality opportunities (very high confidence + wide
                    engine agreement + strong R:R + contained volatility),
                    capped at extreme_max (default 30x).
    """
    cfg = dict(LEVERAGE_DEFAULTS)
    cfg.update(CONFIG.get("trading", "leverage", default=None) or {})
    conf = float(confidence or 0.0)
    atr_pct = max(float(atr_pct or 0.0), 0.01)
    rr = float(rr or 0.0)
    min_l, max_l = float(cfg["min"]), float(cfg["max"])
    ext_max = float(cfg["extreme_max"])

    # base 10..20 from confidence
    base = min_l + (max_l - min_l) * min(max((conf - 45.0) / 40.0, 0.0), 1.0)
    # volatility guard: calm markets tolerate the upper part of the band,
    # choppy/volatile markets are pushed toward the lower part
    vol_factor = min(1.2, max(0.6, 0.8 / atr_pct))
    lev = min(max(base * vol_factor, min_l), max_l)
    tier = "STANDARD (10x-20x)"
    reasons = [f"confidence {conf:.0f}% sets base leverage {base:.1f}x",
               f"volatility factor x{vol_factor:.2f} (ATR {atr_pct:.2f}% per candle)"]

    extreme_ok = (conf >= float(cfg["extreme_min_confidence"])
                  and n_agree >= int(cfg["extreme_min_agree"])
                  and rr >= float(cfg["extreme_min_rr"])
                  and atr_pct <= float(cfg["max_atr_pct_for_extreme"]))
    if extreme_ok:
        span = ext_max - 20.0
        lev = 20.0 + (min(conf, 97.0) - float(cfg["extreme_min_confidence"])) / \
            max(97.0 - float(cfg["extreme_min_confidence"]), 1e-9) * span
        lev = max(lev, 21.0)
        tier = "EXTREME (>20x)"
        reasons.append(
            f"EXTREME tier unlocked: confidence {conf:.0f}% >= {cfg['extreme_min_confidence']:.0f}%, "
            f"{n_agree}/{n_total} engines agree (>= {cfg['extreme_min_agree']}), "
            f"R:R {rr:.2f} >= {cfg['extreme_min_rr']}, ATR {atr_pct:.2f}% <= "
            f"{cfg['max_atr_pct_for_extreme']}% - rare top-quality setup")
    else:
        reasons.append(
            f"hard-capped at {max_l:.0f}x: >20x is reserved for extreme-opportunity signals "
            f"(needs conf >= {cfg['extreme_min_confidence']:.0f}%, >= {cfg['extreme_min_agree']} "
            f"engines agreeing, R:R >= {cfg['extreme_min_rr']}, ATR% <= "
            f"{cfg['max_atr_pct_for_extreme']})")

    lev_i = int(round(lev))
    ceiling = int(ext_max) if extreme_ok else int(max_l)
    lev_i = min(max(lev_i, int(min_l)), ceiling)
    liq_dist = (1.0 / lev_i - 0.005) * 100.0  # isolated-margin estimate
    return {
        "leverage_x": lev_i,
        "leverage_tier": tier,
        "leverage_policy": f"{int(min_l)}x-{int(max_l)}x standard / >{int(max_l)}x extreme only",
        "leverage_reason": "; ".join(reasons),
        "est_liquidation_distance_pct": round(max(liq_dist, 0.5), 1),
    }


def compute_levels(price: float, atr_v: float, side: str, votes: list, a: dict) -> dict:
    """Entry / SL / TP from agreeing-strategy hints + ATR structure rules."""
    sign = 1 if side == "LONG" else -1
    agreeing = [v for v in votes if v["direction"] == side]

    # entry: median of hints close to price, else market price
    entries = [v["entry_hint"] for v in agreeing
               if v.get("entry_hint") and abs(v["entry_hint"] - price) / price < 0.03]
    entry = float(np.median(entries)) if entries else price

    # stop loss: strategy hints (structure based) else ATR based
    sls = [v["sl_hint"] for v in agreeing
           if v.get("sl_hint") and (v["sl_hint"] - entry) * sign < 0
           and abs(v["sl_hint"] - entry) / (atr_v + 1e-12) < 6]
    if sls:
        sl = float(np.median(sls))
        # never tighter than 0.6 ATR, never wider than 4 ATR
        sl = min(max(abs(entry - sl), 0.6 * atr_v), 4.0 * atr_v)
        sl = entry - sign * sl
    else:
        sl = entry - sign * 1.5 * atr_v

    risk = abs(entry - sl)
    tps = [v["tp_hint"] for v in agreeing
           if v.get("tp_hint") and (v["tp_hint"] - entry) * sign > 0]
    if tps:
        tp = float(np.median(tps))
        tp = entry + sign * min(max(abs(tp - entry), 1.2 * risk), 8 * risk)
    else:
        tp = entry + sign * 2.5 * risk

    tp_levels = [
        {"name": "TP1 (secure 50%)", "price": round(entry + sign * 1.2 * risk, 8), "r": 1.2},
        {"name": "TP2 (secure 30%)", "price": round(entry + sign * 1.0 * risk + sign * 1.5 * risk, 8), "r": 2.5},
        {"name": "TP3 (runner)", "price": round(tp, 8), "r": round(abs(tp - entry) / (risk + 1e-12), 2)},
    ]
    return {"entry": entry, "stop_loss": sl, "take_profit": tp,
            "take_profit_levels": tp_levels, "risk": risk}


# -------------------------------------------------------------- AI prompts

AI_PROMPT_TEMPLATE = """You are a crypto futures signal desk AI. Analyze and reply ONLY with JSON.

COIN: {symbol} (Binance USD-M perpetual) TIMEFRAME: {interval}
MARKET SNAPSHOT: {snapshot}
STRATEGY ENGINE VOTES (already computed):
{votes_txt}

TASK: Decide the best trade. Rules:
- side LONG or SHORT only; use NEUTRAL only if truly no edge.
- entry near current price or a logical pullback level.
- stop_loss beyond invalidation structure; take_profit >= 1.5x risk.
- reason must name WHICH strategy + WHICH technique/logic produced the call.
Reply EXACTLY with this JSON schema:
{{"side":"LONG|SHORT|NEUTRAL","entry_price":0.0,"stop_loss":0.0,"take_profit":0.0,"confidence":0-100,"reason":"..."}}"""


def _votes_txt(votes: list) -> str:
    lines = []
    for v in votes:
        lines.append(f"- {v['display']}: {v['direction']} strength={v['strength']:.0f} :: {v['reason'][:220]}")
    return "\n".join(lines)


def _ai_refine(mode: str, symbol: str, interval: str, snap_prompt: dict,
               votes: list, levels: dict, ta_side: str, ta_conf: float) -> dict:
    """Ask the AI chain. Returns {"used": bool, "provider", "model",
    "patched_fields": dict, "reason": str, "errors": [...]}."""
    result = {"used": False, "provider": None, "model": None,
              "patched_fields": {}, "reason": None, "errors": []}
    if mode == "off":
        return result
    prompt = AI_PROMPT_TEMPLATE.format(
        symbol=symbol, interval=interval,
        snapshot=json.dumps(snap_prompt),
        votes_txt=_votes_txt(votes))
    resp = ai_router.ask_ai(prompt)
    result["errors"] = resp["errors"]
    if not resp["ok"]:
        return result
    data = ai_router.extract_json(resp["text"])
    if not data:
        result["errors"].append("AI reply was not JSON")
        return result

    result["provider"], result["model"] = resp["provider"], resp["model"]
    price = snap_prompt["price"]
    atr_v = snap_prompt["atr"] or max(price * 0.005, 1e-9)
    patch = {}

    ai_side = str(data.get("side", "")).upper()
    if mode == "full" and ai_side in ("LONG", "SHORT"):
        patch["side"] = ai_side
    elif ai_side in ("LONG", "SHORT") and ai_side != ta_side:
        # in assist mode AI may not flip the side, but we record disagreement
        result["reason_note"] = f"AI ({resp['provider']}) suggested {ai_side}; TA confluence kept {ta_side}."

    sign = 1 if patch.get("side", ta_side) == "LONG" else -1
    entry = levels["entry"]
    for fld, key in (("entry_price", "entry_price"), ("stop_loss", "stop_loss"),
                     ("take_profit", "take_profit")):
        try:
            val = float(data.get(key, 0) or 0)
        except Exception:
            val = 0
        if val <= 0:
            continue
        # sanity clamps: within +-15% of price; correct side of entry
        if abs(val - price) / price > 0.15:
            continue
        if key == "stop_loss" and (val - entry) * sign > 0:
            continue
        if key == "take_profit" and (val - entry) * sign < 0:
            continue
        patch[key] = val
    try:
        conf = float(data.get("confidence", 0) or 0)
        if 5 <= conf <= 100:
            patch["confidence"] = round((conf + ta_conf) / 2, 1)  # blend
    except Exception:
        pass
    reason = data.get("reason")
    if isinstance(reason, str) and len(reason) > 20:
        result["reason"] = reason[:1200]
    result["used"] = bool(patch) or bool(result["reason"])
    result["patched_fields"] = patch
    return result


# ------------------------------------------------------------ main generate

def generate_signal(symbol: str, interval: str = None, strategy_names=None,
                    ai_mode: str = None, save: bool = True) -> dict:
    """Full pipeline: TA -> strategy votes -> levels -> AI refine -> signal."""
    t0 = time.time()
    symbol = bc.normalize_symbol(symbol) or symbol.upper()
    interval = interval or CONFIG.get("trading", "default_interval", default="15m")
    strategy_names = strategy_names or CONFIG.get("trading", "strategies",
                                                  default=list(st.STRATEGIES.keys()))
    ai_mode = ai_mode or CONFIG.get("ai", "mode", default="assist")

    ctx = get_market_context(symbol, interval)
    df, a, snap = ctx["df"], ctx["analysis"], ctx["snapshot"]
    snap["symbol"] = symbol
    price = snap["last_price"] or a["price"]

    # ================= AlphaWave Accuracy Engine v2 =====================
    gates = accuracy.quality_gates(df, a, snap)
    weights = accuracy.blended_weights(symbol, interval)
    htf = accuracy.htf_bias(symbol, interval)
    t_age = accuracy.trigger_age(a)

    votes = st.run_strategies(df, a, strategy_names)
    for v in votes:                      # learned per-engine voting weights
        w = float(weights.get(v["name"], 1.0))
        v["raw_strength"] = v["strength"]
        v["weight"] = w
        v["strength"] = round(min(v["strength"] * w, 100.0), 1)
    combo = st.combine_votes(votes)

    def _no_trade(reason_extra: str) -> dict:
        sig = {
            "coin": symbol, "timeframe": interval, "side": "NO TRADE",
            "live_price": round(price, 8), "entry_price": None,
            "stop_loss": None, "take_profit": None, "take_profit_levels": [],
            "confidence": 0.0, "risk_reward": None,
            "recommended_leverage": None,
            "leverage_tier": "NONE (no trade - no leverage)",
            "leverage_policy": "10x-20x standard / >20x extreme only",
            "leverage_reason": "No directional edge - AlphaWave does not suggest leverage without a trade.",
            "est_liquidation_distance_pct": None,
            "reason": reason_extra,
            "strategy_breakdown": [
                {"strategy": v["display"], "direction": v["direction"],
                 "strength": v["strength"], "weight": v.get("weight", 1.0),
                 "reason": v["reason"]} for v in votes],
            "htf": htf, "htf_aligned": None,
            "quality_gates": gates, "trigger_age_candles": t_age,
            "engine_weights": {v["display"]: v.get("weight", 1.0) for v in votes},
            "ai_provider": None, "ai_model": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_sec": round(time.time() - t0, 2),
            "disclaimer": "Not financial advice. No orders are placed by this tool.",
        }
        if save:
            journal_add(sig)
        return sig

    # hard quality gates: refuse untradeable market conditions outright
    if gates["hard"]:
        return _no_trade("ACCURACY GATE REFUSED the trade: " + "; ".join(gates["hard"]) +
                         ". Engine votes: " + "; ".join(
                             f"{v['display']}={v['direction']}" for v in votes))

    side = combo["side"]
    conf_notes = []
    htf_aligned = None
    if side != "NEUTRAL":
        htf_aligned = (htf["bias"] == side) or (htf["bias"] == "NEUTRAL")
        if not htf_aligned:
            if combo["confidence"] < 70:
                return _no_trade(
                    f"COUNTER-TREND FILTER: {interval} confluence says {side} "
                    f"(conf {combo['confidence']:.0f}%) but higher timeframe "
                    f"{htf['timeframe']} bias is {htf['bias']} (ADX {htf['adx']}). "
                    "AlphaWave only takes counter-trend trades with extreme "
                    "confluence (>=70%). Stand aside.")
            combo["confidence"] *= 0.75
            conf_notes.append(f"HTF {htf['timeframe']} opposes (-25% confidence)")
        elif htf["bias"] == side:
            combo["confidence"] = min(combo["confidence"] * 1.08, 97.0)
            conf_notes.append(f"HTF {htf['timeframe']} aligned (+8% confidence)")
        if t_age > 6:
            combo["confidence"] *= 0.85
            conf_notes.append(f"stale trigger ({t_age} candles since last event, -15%)")
        if gates["soft"]:
            combo["confidence"] *= max(0.8, 1 - 0.03 * len(gates["soft"]))
            conf_notes.append("soft risk notes: " + "; ".join(gates["soft"]))
        combo["confidence"] = round(min(max(combo["confidence"], 1), 97), 1)

    if side == "NEUTRAL":
        # fall back to strongest single vote if any real conviction exists
        strong = max(votes, key=lambda v: v["strength"], default=None)
        if strong and strong["strength"] >= 45:
            side = strong["direction"]
        else:
            sig = {
                "coin": symbol, "timeframe": interval, "side": "NO TRADE",
                "live_price": round(price, 8), "entry_price": None,
                "stop_loss": None, "take_profit": None, "take_profit_levels": [],
                "confidence": 0.0, "risk_reward": None,
                "recommended_leverage": None,
                "leverage_tier": "NONE (no trade - no leverage)",
                "leverage_policy": "10x-20x standard / >20x extreme only",
                "leverage_reason": "No directional edge - AlphaWave does not suggest leverage without a trade.",
                "est_liquidation_distance_pct": None,
                "reason": "All engines conflicting or flat: " + "; ".join(
                    f"{v['display']}={v['direction']}" for v in votes) +
                          ". Best practice: stand aside until confluence returns.",
                "strategy_breakdown": [
                    {"strategy": v["display"], "direction": v["direction"],
                     "strength": v["strength"], "reason": v["reason"]} for v in votes],
                "htf": htf, "htf_aligned": htf_aligned,
                "quality_gates": gates, "trigger_age_candles": t_age,
                "engine_weights": {v["display"]: v.get("weight", 1.0) for v in votes},
                "ai_provider": None, "ai_model": None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_sec": round(time.time() - t0, 2),
                "disclaimer": "Not financial advice. No orders are placed by this tool.",
            }
            if save:
                journal_add(sig)
            return sig

    levels = compute_levels(price, a["atr_val"], side, votes, a)
    snap_prompt = _snapshot_for_prompt(a, snap)
    snap_prompt["symbol"] = symbol

    ai = _ai_refine(ai_mode, symbol, interval, snap_prompt, votes, levels,
                    side, combo["confidence"])

    entry = ai["patched_fields"].get("entry_price", levels["entry"])
    sl = ai["patched_fields"].get("stop_loss", levels["stop_loss"])
    tp = ai["patched_fields"].get("take_profit", levels["take_profit"])
    side = ai["patched_fields"].get("side", side)
    confidence = ai["patched_fields"].get("confidence", combo["confidence"])

    # rebuild TP ladder if AI moved numbers (always monotonic in side direction)
    sign = 1 if side == "LONG" else -1
    risk = abs(entry - sl) or 1e-9
    rr = abs(tp - entry) / risk
    if rr < 1.0:  # enforce minimum sensible R:R
        tp = entry + sign * 1.5 * risk
        rr = 1.5
    tp2_dist = min(2.2 * risk, max(1.5 * risk, abs(tp - entry) * 0.66))
    tp_levels = [
        {"name": "TP1", "price": round(entry + sign * 1.2 * risk, 8), "r": 1.2},
        {"name": "TP2", "price": round(entry + sign * tp2_dist, 8), "r": round(tp2_dist / risk, 2)},
        {"name": "TP3", "price": round(tp, 8), "r": round(rr, 2)},
    ]

    # ---- leverage recommendation (10x-20x; >20x only extreme setups) ------
    lev = compute_leverage(confidence, combo["n_agree"], combo["n_total"],
                           rr, a["atr_pct"])

    # ------- REASON (strategy + technique + logic) -----------------------
    agreeing = sorted([v for v in votes if v["direction"] == side],
                      key=lambda v: -v["strength"])
    ta_reason = (
        f"{side} {symbol} {interval}: {combo['n_agree']}/{combo['n_total']} engines agree "
        f"(net score {combo['net_score']:+.0f}, learned weights applied). Primary logic -> "
        + " || ".join(f"{v['display']} (w{v.get('weight',1):.2f}): {v['reason']}" for v in agreeing[:3])
    )
    ta_reason += (f" || HTF {htf['timeframe']} bias {htf['bias']} "
                  f"({'aligned' if htf_aligned else 'opposed - confidence penalized'}, "
                  f"ADX {htf['adx']})")
    if conf_notes:
        ta_reason += " || Confidence adjustments: " + "; ".join(conf_notes)
    if ai.get("reason_note"):
        ta_reason += " [Note: " + ai["reason_note"] + "]"
    reason = ta_reason
    if ai.get("reason"):
        reason = f"{ai['reason']} -- TECHNICAL BACKUP: {ta_reason}"
    else:
        # built-in local analyst writes the headline when no cloud AI is used
        local_para = local_ai.local_signal_reason(
            symbol, combo, votes, snap_prompt,
            {"htf": htf, "htf_aligned": htf_aligned, "gates": gates})
        reason = f"ALPHAWAVE LOCAL ENGINE: {local_para} || FULL DETAIL: {ta_reason}"

    sig = {
        "coin": symbol,
        "timeframe": interval,
        "side": side,
        "live_price": round(price, 8),
        "entry_price": round(entry, 8),
        "stop_loss": round(sl, 8),
        "take_profit": round(tp, 8),
        "take_profit_levels": tp_levels,
        "confidence": round(min(max(confidence, 1), 99), 1),
        "risk_reward": round(rr, 2),
        "stop_distance_pct": round(risk / (entry + 1e-12) * 100, 3),
        "recommended_leverage": lev["leverage_x"],
        "leverage_tier": lev["leverage_tier"],
        "leverage_policy": lev["leverage_policy"],
        "leverage_reason": lev["leverage_reason"],
        "est_liquidation_distance_pct": lev["est_liquidation_distance_pct"],
        "htf": htf,
        "htf_aligned": htf_aligned,
        "quality_gates": gates,
        "trigger_age_candles": t_age,
        "engine_weights": {v["display"]: v.get("weight", 1.0) for v in votes},
        "reason": reason,
        "strategy_breakdown": [
            {"strategy": v["display"], "direction": v["direction"],
             "strength": v["strength"], "reason": v["reason"]} for v in votes],
        "market": {
            "funding_rate_pct": round(snap.get("funding_rate", 0) * 100, 4),
            "change_24h_pct": round(snap.get("change_24h_pct", 0), 2),
            "quote_volume_24h_musd": round(snap.get("quote_volume_24h", 0) / 1e6, 2),
        },
        "ai_provider": ai.get("provider") or "local-engine (built-in free)",
        "ai_model": ai.get("model") or "rule-based-confluence-v1",
        "ai_errors": ai.get("errors", [])[:3],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - t0, 2),
        "disclaimer": "Not financial advice. Analysis tool only - this app never places orders.",
    }
    # keep learning: follow up old journal signals (TP or SL first?) in background
    global _last_outcome_refresh
    if save and time.time() - _last_outcome_refresh > 600:
        _last_outcome_refresh = time.time()
        threading.Thread(target=accuracy.refresh_outcomes, daemon=True).start()
    if save:
        journal_add(sig)
    return sig


# --------------------------------------------------------- random coin flow

def _score_stage2(t: dict) -> float:
    """Rank the 1000-universe down to 100: liquidity + tradable volatility."""
    try:
        vol = float(t.get("quoteVolume", 0) or 0)
        chg = abs(float(t.get("priceChangePercent", 0) or 0))
        hi = float(t.get("highPrice", 0) or 0)
        lo = float(t.get("lowPrice", 0) or 0)
        last = float(t.get("lastPrice", 0) or 1)
        rng = (hi - lo) / last * 100 if last else 0
        liq = np.log10(max(vol, 1))
        # sweet spot: enough range to trade, not purely dead or purely chaotic
        vol_score = min(rng / 8.0, 1.0) * 10
        dead_penalty = 6 if rng < 1.0 else 0
        return liq * 6 + vol_score - dead_penalty
    except Exception:
        return -999


def _score_stage3(item: dict) -> float:
    """Rank 100 -> 10 with a fast 1h structure scan."""
    symbol = item["symbol"]
    try:
        df = bc.klines(symbol, "1h", 120)
        if len(df) < 60:
            return -999, symbol, None
        close = df["close"]
        e20 = ind.ema(close, 20).iloc[-1]
        e50 = ind.ema(close, 50).iloc[-1]
        r = ind.rsi(close, 14).iloc[-1]
        adx_v = ind.adx(df, 14)[0].iloc[-1]
        price = float(close.iloc[-1])
        vol_rel = float(df["volume"].tail(6).mean() / (df["volume"].tail(60).mean() + 1e-9))
        trend_pts = 0.0
        if price > e20 > e50:
            trend_pts = 25
        elif price < e20 < e50:
            trend_pts = 25
        elif price > e20 or price < e20:
            trend_pts = 8
        rsi_pts = 12 if 45 <= r <= 72 or 28 <= r <= 55 else 0
        adx_pts = min(float(adx_v) * 0.5, 18)
        vol_pts = min(vol_rel * 8, 15)
        return trend_pts + rsi_pts + adx_pts + vol_pts, symbol, {
            "trend_points": round(trend_pts, 1), "rsi": round(float(r), 1),
            "adx": round(float(adx_v), 1), "vol_rel": round(vol_rel, 2)}
    except Exception:
        return -999, symbol, None


def random_funnel(interval: str = None, progress_cb=None,
                  strategy_names=None, ai_mode=None) -> dict:
    """best 1000 -> best 100 -> best 10 -> best 1 -> signal."""
    t0 = time.time()
    cfg = CONFIG.get("random_funnel", default={}) or {}
    n1 = int(cfg.get("stage1_max", 1000))
    n2 = int(cfg.get("stage2_top", 100))
    n3 = int(cfg.get("stage3_top", 10))

    def prog(stage, msg, **kw):
        if progress_cb:
            try:
                progress_cb(stage, msg, **kw)
            except Exception:
                pass

    result = {"stages": [], "started_at": datetime.now(timezone.utc).isoformat()}

    # stage 1: universe ---------------------------------------------------
    prog(1, "Fetching all Binance USDT-M futures markets ...")
    symbols = set(bc.usdt_perp_symbols())
    tickers = [t for t in bc.ticker_24h() if t.get("symbol") in symbols]
    min_vol = CONFIG.get("trading", "min_quote_volume_24h", default=1_000_000)
    tickers = [t for t in tickers if float(t.get("quoteVolume", 0) or 0) >= min_vol]
    tickers.sort(key=lambda t: -float(t.get("quoteVolume", 0) or 0))
    universe = tickers[:n1]
    result["stages"].append({
        "stage": 1, "name": f"Universe (top {n1} by 24h volume)",
        "count": len(universe),
        "note": f"{len(tickers)} markets passed the ${min_vol/1e6:.0f}M min-volume filter; "
                f"kept best {len(universe)}."})
    prog(1, f"Universe ready: {len(universe)} coins", count=len(universe))

    # stage 2: -> 100 -------------------------------------------------------
    prog(2, f"Scoring {len(universe)} coins (liquidity + volatility) ...")
    scored = sorted(universe, key=_score_stage2, reverse=True)
    top100 = scored[:n2]
    result["stages"].append({
        "stage": 2, "name": f"Top {n2} (liquidity + tradable range score)",
        "count": len(top100),
        "sample": [t["symbol"] for t in top100[:15]]})
    prog(2, f"Top {len(top100)} selected", count=len(top100))

    # stage 3: -> 10 (needs klines; threaded) -------------------------------
    prog(3, f"Deep-scanning {len(top100)} coins on 1h structure (this takes ~15s) ...")
    with ThreadPoolExecutor(max_workers=10) as ex:
        scanned = list(ex.map(_score_stage3, top100))
    scanned = [(s, sym, meta) for s, sym, meta in scanned if s > -900]
    scanned.sort(key=lambda x: -x[0])
    top10 = scanned[:n3]
    result["stages"].append({
        "stage": 3, "name": f"Top {n3} (1h trend/RSI/ADX/volume scan)",
        "count": len(top10),
        "coins": [{"symbol": sym, "score": round(s, 1), "meta": meta}
                  for s, sym, meta in top10]})
    prog(3, f"Top {len(top10)} selected: " + ", ".join(sym for _, sym, _ in top10))

    if not top10:
        result["error"] = "No coins passed stage 3 (network issue?)"
        return result

    # stage 4: -> 1 (full confluence on each) -------------------------------
    prog(4, f"Running full 19-engine confluence on the final {len(top10)} ...")
    interval = interval or CONFIG.get("trading", "default_interval", default="15m")
    best, best_score = None, -1e9
    finals = []
    for _s, sym, _m in top10:
        try:
            ctx = get_market_context(sym, interval)
            votes = st.run_strategies(ctx["df"], ctx["analysis"], strategy_names)
            combo = st.combine_votes(votes)
            edge = abs(combo["net_score"]) * (combo["confidence"] / 100 + 0.3)
            finals.append({"symbol": sym, "side": combo["side"],
                           "net_score": combo["net_score"],
                           "confidence": combo["confidence"], "edge": round(edge, 1)})
            if edge > best_score and combo["side"] != "NEUTRAL":
                best_score, best = edge, sym
        except Exception as e:
            finals.append({"symbol": sym, "error": str(e)[:100]})
        prog(4, f"Analyzed {len(finals)}/{len(top10)} finalists ...")

    result["stages"].append({"stage": 4, "name": "Final confluence ranking",
                             "coins": sorted(finals, key=lambda x: -x.get("edge", -1))})
    if not best:
        result["error"] = "None of the finalists produced a directional edge right now."
        prog(4, "No directional edge found among finalists.")
        return result

    prog(4, f"BEST COIN = {best} -> generating signal ...")
    sig = generate_signal(best, interval, strategy_names=strategy_names, ai_mode=ai_mode)
    result["best_coin"] = best
    result["signal"] = sig
    result["elapsed_sec"] = round(time.time() - t0, 1)
    prog(5, "Signal ready.")
    return result


# ------------------------------------------------------------- async jobs
# Long funnels run as background jobs so GUI/bot can poll progress.

_jobs = {}
_jobs_lock = threading.Lock()


def start_random_job(interval=None, strategy_names=None, ai_mode=None) -> str:
    job_id = f"rnd_{int(time.time()*1000)}"
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "stage": 0, "messages": [],
                         "result": None, "error": None}

    def cb(stage, msg, **kw):
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j:
                j["stage"] = stage
                j["messages"].append(msg)
                if len(j["messages"]) > 40:
                    j["messages"] = j["messages"][-40:]

    def run():
        try:
            res = random_funnel(interval, cb, strategy_names, ai_mode)
            with _jobs_lock:
                j = _jobs.get(job_id)
                if j:
                    j["status"] = "done" if "signal" in res else "failed"
                    j["result"] = res
                    j["error"] = res.get("error")
        except Exception as e:
            with _jobs_lock:
                j = _jobs.get(job_id)
                if j:
                    j["status"] = "failed"
                    j["error"] = str(e)[:300]

    threading.Thread(target=run, daemon=True).start()
    return job_id


def get_job(job_id: str) -> dict:
    with _jobs_lock:
        j = _jobs.get(job_id)
        return json.loads(json.dumps(j, default=str)) if j else None
