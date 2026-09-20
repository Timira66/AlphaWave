"""
Trading strategy engines.

Eight methods requested by the user, each implemented as an independent
analysis engine that votes LONG / SHORT / NEUTRAL with a strength (0-100)
and a detailed human-readable REASON explaining exactly which technique
and logic produced the vote.

  1. orderflow  - Order Flow (taker delta, CVD slope, absorption, imbalance)
  2. niyowew    - "Niyowew" neural-wave engine (adaptive cycle + momentum
                  ensemble, a lightweight statistical 'neural' wave model)
  3. msnr       - MNSR multi-level Support & Resistance reaction trading
  4. smc        - Smart Money Concepts (BOS/CHoCH, order blocks, FVG, sweeps)
  5. ict2022    - ICT 2022 model (MSS + displacement -> FVG entry, OTE,
                  liquidity draw targets)
  6. elliott    - "Eliyat Vew" Elliott Wave (zigzag impulse/correction count)
  7. sk         - SK sniper entries (liquidity sweep + reclaim, extreme RSI)
  8. ykof       - Y-KOF composite confluence (trend+momentum+volatility+
                  volume+orderflow multi-factor score)

A vote: {"name", "display", "direction": "LONG|SHORT|NEUTRAL",
         "strength": 0..100, "reason": str, "entry_hint", "sl_hint", "tp_hint"}
"""

import math
import numpy as np
import pandas as pd

from . import indicators as ind

EPS = 1e-12


def _vote(name, display, direction, strength, reason,
          entry_hint=None, sl_hint=None, tp_hint=None):
    return {
        "name": name,
        "display": display,
        "direction": direction,
        "strength": max(0, min(100, round(strength, 1))),
        "reason": reason,
        "entry_hint": entry_hint,
        "sl_hint": sl_hint,
        "tp_hint": tp_hint,
    }


def _neutral(name, display, reason):
    return _vote(name, display, "NEUTRAL", 0, reason)


def _dir(strength_signed):
    if strength_signed > 0:
        return "LONG", abs(strength_signed)
    if strength_signed < 0:
        return "SHORT", abs(strength_signed)
    return "NEUTRAL", 0.0


# =====================================================================
# 1. ORDER FLOW
# =====================================================================

def strategy_orderflow(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "orderflow", "Order Flow"
    delta = a["delta"]
    cvd_s = a["cvd"]
    price = a["price"]
    atr_v = a["atr_val"]

    d_now = float(delta.iloc[-1])
    d_prev5 = float(delta.tail(6).iloc[:-1].sum())
    cvd_slope = float(a["cvd_slope_val"])
    vol = float(df["volume"].iloc[-1])
    vol_avg = float(a["vol_sma20"].iloc[-1]) + EPS
    vol_ratio = vol / vol_avg

    # CVD / price divergence over last 20 candles
    cvd20 = cvd_s.tail(20)
    price20 = df["close"].tail(20)
    cvd_up = float(cvd20.iloc[-1] - cvd20.iloc[0])
    price_up = float(price20.iloc[-1] - price20.iloc[0])

    score = 0.0
    reasons = []

    if cvd_slope > 0:
        score += min(30, 12 + abs(cvd_slope) / (vol_avg + EPS) * 40)
        reasons.append("CVD slope rising (aggressive taker buying)")
    elif cvd_slope < 0:
        score -= min(30, 12 + abs(cvd_slope) / (vol_avg + EPS) * 40)
        reasons.append("CVD slope falling (aggressive taker selling)")

    if d_now > 0 and d_prev5 > 0:
        score += 15
        reasons.append("6 consecutive-candle positive taker delta")
    elif d_now < 0 and d_prev5 < 0:
        score -= 15
        reasons.append("6 consecutive-candle negative taker delta")

    # absorption: price flat/down but delta strongly positive -> buying absorbed
    if cvd_up > 0 and price_up < 0 and abs(price_up) < 0.35 * atr_v:
        score -= 18
        reasons.append("BEARISH ABSORPTION: CVD up while price stalls -> sellers absorbing")
    if cvd_up < 0 and price_up > 0 and abs(price_up) < 0.35 * atr_v:
        score += 18
        reasons.append("BULLISH ABSORPTION: CVD down while price holds -> buyers absorbing")

    if vol_ratio > 1.6:
        boost = 10 * min(vol_ratio, 3)
        score += boost if d_now > 0 else -boost
        reasons.append(f"Volume surge {vol_ratio:.1f}x avg confirms delta direction")

    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "Order flow balanced: taker delta and CVD show no aggression either way.")

    entry = price
    sl = price - 1.4 * atr_v * (1 if direction == "LONG" else -1)
    tp = price + 2.2 * atr_v * (1 if direction == "LONG" else -1)
    return _vote(name, disp, direction, strength,
                 "Order Flow engine: " + "; ".join(reasons) +
                 f". Net score {score:+.0f}/100 -> {direction} bias.",
                 entry, sl, tp)


# =====================================================================
# 2. NIYOWEW - neural wave engine
# =====================================================================

def strategy_niyowew(df: pd.DataFrame, a: dict) -> dict:
    """Adaptive 'neural wave' engine: detrended price cycle detection via
    autocorrelation + weighted momentum ensemble. Statistically finds the
    dominant wave period, trades with the wave phase."""
    name, disp = "niyowew", "Niyowew (Neural Wave)"
    close = df["close"].values.astype(float)
    n = len(close)
    if n < 80:
        return _neutral(name, disp, "Not enough candles for cycle detection.")

    x = close[-160:]
    trend = pd.Series(x).rolling(40, min_periods=1).mean().values
    det = x - trend
    det = (det - det.mean()) / (det.std() + EPS)

    # autocorrelation to find dominant cycle
    best_lag, best_ac = 0, 0.0
    for lag in range(8, min(70, len(det) // 2)):
        ac = float(np.corrcoef(det[:-lag], det[lag:])[0, 1])
        if ac > best_ac:
            best_ac, best_lag = ac, lag

    phase_score = 0.0
    wave_txt = "no clean cycle"
    if best_ac > 0.3 and best_lag > 0:
        # position inside the dominant cycle
        seg = det[-best_lag:]
        pos_in_cycle = (seg[-1] - seg.min()) / (seg.max() - seg.min() + EPS)
        rising = det[-1] > det[-3]
        if pos_in_cycle < 0.35 and rising:
            phase_score = 55 * best_ac + 15
            wave_txt = (f"dominant wave period ~{best_lag} candles (autocorr {best_ac:.2f}); "
                        f"price at {pos_in_cycle*100:.0f}% of cycle trough zone and turning up")
        elif pos_in_cycle > 0.65 and not rising:
            phase_score = -(55 * best_ac + 15)
            wave_txt = (f"dominant wave period ~{best_lag} candles (autocorr {best_ac:.2f}); "
                        f"price at {pos_in_cycle*100:.0f}% of cycle crest zone and turning down")
        else:
            wave_txt = (f"dominant wave period ~{best_lag} candles; wave position "
                        f"{pos_in_cycle*100:.0f}% -> no extreme trigger yet")

    # momentum ensemble (weighted 'neurons')
    mom = 0.0
    r1 = float(a["roc"].iloc[-1]) if "roc" in a else 0.0
    w = [(r1, 0.3), (float(a["rsi_val"]) - 50, 0.4), (float(a["macd_hist_val"]) / (a["atr_val"] + EPS) * 30, 0.3)]
    for v, wt in w:
        mom += np.clip(v, -50, 50) * wt
    total = phase_score * 0.6 + np.clip(mom, -45, 45) * 0.4

    direction, strength = _dir(total)
    if direction == "NEUTRAL":
        return _neutral(name, disp, f"Niyowew: {wave_txt}; momentum ensemble neutral ({total:+.1f}).")

    price = a["price"]
    atr_v = a["atr_val"]
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 f"Niyowew neural-wave engine: {wave_txt}; momentum ensemble {mom:+.1f} "
                 f"(ROC/RSI/MACD neurons) -> combined {total:+.1f} = {direction}.",
                 price, price - sign * 1.6 * atr_v, price + sign * 2.4 * atr_v)


# =====================================================================
# 3. MNSR - multi-level support & resistance
# =====================================================================

def _cluster_levels(levels, tol_pct=0.35):
    """Cluster nearby prices; return [(price, touches)] strongest first."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters = []
    cur = [levels[0]]
    for lv in levels[1:]:
        if (lv - cur[-1]) / (cur[-1] + EPS) * 100 <= tol_pct:
            cur.append(lv)
        else:
            clusters.append(cur)
            cur = [lv]
    clusters.append(cur)
    out = [(float(np.mean(c)), len(c)) for c in clusters]
    out.sort(key=lambda t: -t[1])
    return out


def strategy_msnr(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "msnr", "MNSR (Support/Resistance)"
    price = a["price"]
    atr_v = a["atr_val"]

    highs = [v for _, v in a["swing_highs"][-25:]]
    lows = [v for _, v in a["swing_lows"][-25:]]
    highs += [a["range_high"]]
    lows += [a["range_low"]]
    res = _cluster_levels(highs)
    sup = _cluster_levels(lows)

    nearest_res = next((p for p, t in res if p > price * 1.0005), None)
    nearest_sup = next((p for p, t in sorted(sup, key=lambda x: -x[0]) if p < price * 0.9995), None)
    if nearest_res is None:
        nearest_res = price * 1.02
    if nearest_sup is None:
        nearest_sup = price * 0.98

    dist_res = (nearest_res - price) / (atr_v + EPS)
    dist_sup = (price - nearest_sup) / (atr_v + EPS)

    last = df.iloc[-1]
    body_lo, body_hi = min(last["open"], last["close"]), max(last["open"], last["close"])

    score = 0.0
    reasons = []
    # bounce off support
    if dist_sup < 1.2 and last["low"] <= nearest_sup * 1.002 and body_lo > nearest_sup * 0.998:
        score += 55
        reasons.append(f"price reacting at SUPPORT {nearest_sup:.6g} (wick rejected, body closed above)")
    # rejection at resistance
    if dist_res < 1.2 and last["high"] >= nearest_res * 0.998 and body_hi < nearest_res * 1.002:
        score -= 55
        reasons.append(f"price rejecting at RESISTANCE {nearest_res:.6g} (wick failed, body closed below)")
    # breakout continuation
    if price > nearest_res * 1.001:
        score += 30
        reasons.append(f"breakout ABOVE resistance {nearest_res:.6g} -> resistance-flip support")
    if price < nearest_sup * 0.999:
        score -= 30
        reasons.append(f"breakdown BELOW support {nearest_sup:.6g} -> support-flip resistance")

    # room-to-move asymmetry
    if dist_sup < 1.0 and dist_res > 3.0:
        score += 12
        reasons.append("asymmetric R:R - support close below, resistance far above")
    if dist_res < 1.0 and dist_sup > 3.0:
        score -= 12
        reasons.append("asymmetric R:R - resistance close above, support far below")

    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp,
                        f"MNSR: price mid-range between S {nearest_sup:.6g} / R {nearest_res:.6g}; no reaction yet.")
    sign = 1 if direction == "LONG" else -1
    sl = (nearest_sup - 0.5 * atr_v) if direction == "LONG" else (nearest_res + 0.5 * atr_v)
    tp = (nearest_res + 0.3 * atr_v) if direction == "LONG" else (nearest_sup - 0.3 * atr_v)
    if (tp - price) * sign <= 0:
        tp = price + sign * 2.2 * atr_v
    return _vote(name, disp, direction, strength,
                 "MNSR engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, sl, tp)


# =====================================================================
# 4. SMC - Smart Money Concepts
# =====================================================================

def strategy_smc(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "smc", "SMC (Smart Money Concepts)"
    price = a["price"]
    atr_v = a["atr_val"]

    sh = a["swing_highs"][-6:]
    sl = a["swing_lows"][-6:]
    hh = len(sh) >= 2 and sh[-1][1] > sh[-2][1]
    hl = len(sl) >= 2 and sl[-1][1] > sl[-2][1]
    lh = len(sh) >= 2 and sh[-1][1] < sh[-2][1]
    ll = len(sl) >= 2 and sl[-1][1] < sl[-2][1]

    structure = "ranging"
    struct_score = 0.0
    if hh and hl:
        structure, struct_score = "bullish (HH+HL)", 35
    elif lh and ll:
        structure, struct_score = "bearish (LH+LL)", -35
    elif hh and ll:
        structure, struct_score = "expanding/volatile", 0
    elif hl and lh:
        structure, struct_score = "contracting", 0

    reasons = [f"market structure {structure}"]
    score = struct_score

    # CHoCH detection: break of last swing against structure
    if sh and price > sh[-1][1]:
        score += 20
        reasons.append(f"BOS/CHoCH up: close broke swing high {sh[-1][1]:.6g}")
    if sl and price < sl[-1][1]:
        score -= 20
        reasons.append(f"BOS/CHoCH down: close broke swing low {sl[-1][1]:.6g}")

    # unmitigated order blocks
    obs = [ob for ob in a["order_blocks"] if ob["pos"] > len(df) - 40]
    bull_ob = next((ob for ob in reversed(obs) if ob["type"] == "bull"
                    and ob["bottom"] <= price <= ob["top"] * 1.01), None)
    bear_ob = next((ob for ob in reversed(obs) if ob["type"] == "bear"
                    and ob["bottom"] * 0.99 <= price <= ob["top"]), None)
    if bull_ob:
        score += 22
        reasons.append(f"price mitigating a BULLISH ORDER BLOCK [{bull_ob['bottom']:.6g}-{bull_ob['top']:.6g}]")
    if bear_ob:
        score -= 22
        reasons.append(f"price mitigating a BEARISH ORDER BLOCK [{bear_ob['bottom']:.6g}-{bear_ob['top']:.6g}]")

    # unfilled FVG magnets
    open_gaps = [g for g in a["fvgs"] if not g["filled"]]
    bull_gaps = [g for g in open_gaps[-8:] if g["type"] == "bull" and g["top"] <= price]
    bear_gaps = [g for g in open_gaps[-8:] if g["type"] == "bear" and g["bottom"] >= price]
    if bull_gaps:
        score += 12
        g = bull_gaps[-1]
        reasons.append(f"unfilled BULLISH FVG below [{g['bottom']:.6g}-{g['top']:.6g}] acts as support magnet")
    if bear_gaps:
        score -= 12
        g = bear_gaps[-1]
        reasons.append(f"unfilled BEARISH FVG above [{g['bottom']:.6g}-{g['top']:.6g}] acts as resistance magnet")

    # liquidity sweep of equal highs/lows then reclaim
    events = a.get("events", [])
    recent_sweeps = [e for e in events if e["type"] == "sweep" and e["pos"] >= len(df) - 6]
    for sw in recent_sweeps:
        if sw["side"] == "buy":
            score += 15
            reasons.append("sell-side liquidity swept and reclaimed (stop-hunt long)")
        else:
            score -= 15
            reasons.append("buy-side liquidity swept and rejected (stop-hunt short)")

    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "SMC: " + "; ".join(reasons) + " -> conflicting, stand aside.")
    sign = 1 if direction == "LONG" else -1
    if direction == "LONG" and bull_ob:
        sl = bull_ob["bottom"] - 0.2 * atr_v
    elif direction == "SHORT" and bear_ob:
        sl = bear_ob["top"] + 0.2 * atr_v
    else:
        sl = price - sign * 1.5 * atr_v
    tp = price + sign * max(2.2 * atr_v, abs(price - sl) * 2)
    return _vote(name, disp, direction, strength,
                 "SMC engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, sl, tp)


# =====================================================================
# 5. ICT (2022 model)
# =====================================================================

def strategy_ict2022(df: pd.DataFrame, a: dict) -> dict:
    """ICT 2022: liquidity raid -> Market Structure Shift with displacement
    -> entry on the FVG created by displacement -> target opposite
    liquidity pool. OTE = 62%-79% fib of the displacement leg."""
    name, disp = "ict2022", "ICT (2022 Model)"
    price = a["price"]
    atr_v = a["atr_val"]
    n = len(df)
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    reasons = []
    score = 0.0
    entry_hint = price
    sl_hint = None
    tp_hint = None

    look = 25
    if n > look + 5:
        seg_hi = high[-look:].max()
        seg_lo = low[-look:].min()
        swept_hi = high[-6:].max() >= seg_hi * 0.999
        swept_lo = low[-6:].min() <= seg_lo * 1.001

        # displacement candle: > 1.7 ATR body in last 8 candles
        disp_idx = None
        disp_dir = 0
        for i in range(n - 8, n):
            body = close[i] - df["open"].values[i]
            if abs(body) > 1.7 * atr_v:
                disp_idx, disp_dir = i, (1 if body > 0 else -1)

        if swept_hi and disp_dir == -1:
            score -= 60
            reasons.append(f"buy-side liquidity above {seg_hi:.6g} raided, then bearish DISPLACEMENT -> MSS down (ICT 2022 setup)")
            sl_hint = high[-6:].max() + 0.25 * atr_v
            tp_hint = seg_lo
        elif swept_lo and disp_dir == 1:
            score += 60
            reasons.append(f"sell-side liquidity below {seg_lo:.6g} raided, then bullish DISPLACEMENT -> MSS up (ICT 2022 setup)")
            sl_hint = low[-6:].min() - 0.25 * atr_v
            tp_hint = seg_hi

        # FVG entry from the displacement leg
        gaps = [g for g in a["fvgs"] if not g["filled"] and g["pos"] >= n - 10]
        if score > 0:
            bull_fvg = next((g for g in reversed(gaps) if g["type"] == "bull"), None)
            if bull_fvg:
                entry_hint = (bull_fvg["top"] + bull_fvg["bottom"]) / 2
                score += 12
                reasons.append(f"entry on bullish FVG [{bull_fvg['bottom']:.6g}-{bull_fvg['top']:.6g}]")
        elif score < 0:
            bear_fvg = next((g for g in reversed(gaps) if g["type"] == "bear"), None)
            if bear_fvg:
                entry_hint = (bear_fvg["top"] + bear_fvg["bottom"]) / 2
                score -= 12
                reasons.append(f"entry on bearish FVG [{bear_fvg['bottom']:.6g}-{bear_fvg['top']:.6g}]")

        # OTE zone check (62-79% retrace of last impulse leg)
        zz = a.get("zigzag", [])
        if len(zz) >= 2 and score != 0:
            (p0, v0, t0), (p1, v1, t1) = zz[-2], zz[-1]
            leg_hi, leg_lo = max(v0, v1), min(v0, v1)
            ote_hi = leg_hi - 0.618 * (leg_hi - leg_lo)
            ote_lo = leg_hi - 0.79 * (leg_hi - leg_lo)
            if score > 0 and t1 == "L" and ote_lo <= price <= ote_hi * 1.005:
                score += 10
                reasons.append("price inside OTE (62-79%) premium/discount zone of the impulse leg")
            if score < 0 and t1 == "H" and ote_lo * 0.995 <= price <= ote_hi:
                score += 0  # short from OTE is a bonus
                score -= 10
                reasons.append("price inside OTE zone after up-leg -> short premium")

    if score == 0:
        return _neutral(name, disp,
                        "ICT 2022: no completed liquidity-raid + MSS displacement sequence on this timeframe yet.")

    direction, strength = _dir(score)
    sign = 1 if direction == "LONG" else -1
    if sl_hint is None:
        sl_hint = price - sign * 1.5 * atr_v
    if tp_hint is None or (tp_hint - entry_hint) * sign <= 0:
        tp_hint = entry_hint + sign * 2.5 * atr_v
    return _vote(name, disp, direction, strength,
                 "ICT-2022 engine: " + "; ".join(reasons) + f" -> {direction}.",
                 entry_hint, sl_hint, tp_hint)


# =====================================================================
# 6. ELLIOTT WAVE ("Eliyat Vew")
# =====================================================================

def strategy_elliott(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "elliott", "Eliyat Vew (Elliott Wave)"
    zz = a.get("zigzag", [])
    price = a["price"]
    atr_v = a["atr_val"]
    if len(zz) < 5:
        return _neutral(name, disp, "Elliott: zigzag has fewer than 5 pivots - wave count unreliable here.")

    pts = zz[-7:]
    seq = [t for _, _, t in pts]
    vals = [v for _, v, _ in pts]

    # count impulse legs in the latest direction
    last_dir = 1 if vals[-1] > vals[-2] else -1
    wave_no = 0
    for i in range(len(vals) - 1, 0, -1):
        leg = vals[i] - vals[i - 1]
        if (leg > 0) == (last_dir > 0):
            wave_no += 1
        else:
            break

    # wave-2/4 corrective depth check (should not fully retrace wave-1/3)
    reasons = []
    score = 0.0
    label = f"counting with trend, leg #{wave_no}"

    if last_dir > 0:
        if wave_no in (1, 2):
            score = 45
            label = f"early impulse (wave {wave_no} up)"
            reasons.append("early-stage bullish impulse - wave 3 acceleration expected")
        elif wave_no == 3:
            score = 60
            label = "wave 3 up (strongest)"
            reasons.append("wave-3 territory: strongest and longest impulse leg - trend continuation")
        elif wave_no == 4:
            score = 15
            label = "wave 4 correction up-side finishing"
            reasons.append("shallow wave-4 correction; small long for wave-5 push only")
        else:
            score = -35
            label = f"wave {wave_no} - extended/late (5th or beyond)"
            reasons.append("late-stage impulse, exhaustion risk - wave 5 top / ABC reversal zone")
        # wave 2 depth invalidation
        if len(vals) >= 4 and vals[-2] < min(vals[-4:-2]) and score > 0:
            score = -20
            reasons.append("INVALIDATION: last pullback exceeded prior low - count reset, bearish")
    else:
        if wave_no in (1, 2):
            score = -45
            label = f"early impulse (wave {wave_no} down)"
            reasons.append("early-stage bearish impulse - wave 3 down expected")
        elif wave_no == 3:
            score = -60
            label = "wave 3 down (strongest)"
            reasons.append("wave-3 down: strongest leg of the decline - continuation")
        elif wave_no == 4:
            score = -15
            label = "wave 4 bounce finishing"
            reasons.append("weak corrective bounce; short for wave-5 leg down")
        else:
            score = 35
            label = f"wave {wave_no} - extended/late (5th or beyond)"
            reasons.append("late-stage decline, seller exhaustion - wave 5 low / ABC bounce zone")
        if len(vals) >= 4 and vals[-2] > max(vals[-4:-2]) and score < 0:
            score = 20
            reasons.append("INVALIDATION: last bounce exceeded prior high - count reset, bullish")

    # momentum agreement filter
    if score > 0 and a["rsi_val"] > 78:
        score -= 20
        reasons.append("RSI extreme - reduce long exposure")
    if score < 0 and a["rsi_val"] < 22:
        score += 20
        reasons.append("RSI extreme - reduce short exposure")

    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, f"Elliott: {label}; no tradable edge.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 f"Elliott Wave engine: {label}; " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.8 * atr_v, price + sign * 3.0 * atr_v)


# =====================================================================
# 7. SK - sniper entries (sweep + reclaim)
# =====================================================================

def strategy_sk(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "sk", "SK (Sniper Key)"
    price = a["price"]
    atr_v = a["atr_val"]
    rsi_v = a["rsi_val"]
    events = a.get("events", [])
    n = len(df)

    sweeps = [e for e in events if e["type"] == "sweep" and e["pos"] >= n - 5]
    st_flips = [e for e in events if e["type"] == "supertrend" and e["pos"] >= n - 3]
    rsi_ext = [e for e in events if e["type"] == "rsi" and e["pos"] >= n - 3]

    score = 0.0
    reasons = []
    for s in sweeps:
        if s["side"] == "buy":
            score += 45
            reasons.append(f"sniper long: sell-side liquidity sweep at {s['price']:.6g} then reclaim")
        else:
            score -= 45
            reasons.append(f"sniper short: buy-side liquidity sweep at {s['price']:.6g} then rejection")
    for f in st_flips:
        score += 18 if f["side"] == "buy" else -18
        reasons.append("SuperTrend flip confirms sniper entry timing")
    for r in rsi_ext:
        score += 15 if r["side"] == "buy" else -15
        reasons.append("RSI exiting extreme confirms reversal trigger")

    # extreme RSI + BB tag combo (no sweep needed, half weight)
    if not sweeps:
        if rsi_v < 25 and a["bb_pos"] < 0.05:
            score += 30
            reasons.append(f"oversold extreme (RSI {rsi_v:.0f}) tagged below lower Bollinger - mean-reversion sniper long")
        elif rsi_v > 75 and a["bb_pos"] > 0.95:
            score -= 30
            reasons.append(f"overbought extreme (RSI {rsi_v:.0f}) tagged above upper Bollinger - mean-reversion sniper short")

    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "SK: no fresh liquidity sweep / extreme-reading trigger - sniper stays flat.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "SK sniper engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 0.9 * atr_v, price + sign * 2.0 * atr_v)


# =====================================================================
# 8. Y-KOF composite confluence
# =====================================================================

def strategy_ykof(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "ykof", "Y-KOF (Confluence Key)"
    price = a["price"]
    atr_v = a["atr_val"]

    factors = []  # (weight, score -1..1, description)

    # trend factor
    t = a.get("trend", "RANGE")
    factors.append((0.25, {"UP": 1, "DOWN": -1, "RANGE": 0}[t], f"trend={t} (EMA50/200 stack)"))
    # ADX strength gate
    adx_v = a["adx_val"]
    trend_sign = 1 if t == "UP" else -1 if t == "DOWN" else 0
    factors.append((0.10, trend_sign * min(adx_v / 40, 1), f"ADX={adx_v:.0f}"))
    # momentum
    r_ = a["rsi_val"]
    mom = np.clip((r_ - 50) / 30, -1, 1) if 30 <= r_ <= 70 else (-1 if r_ > 70 else 1)
    factors.append((0.20, mom, f"RSI={r_:.0f}"))
    mh = float(a["macd_hist_val"])
    factors.append((0.15, np.clip(mh / (0.5 * atr_v + EPS), -1, 1), "MACD histogram"))
    # order flow
    cs = float(a["cvd_slope_val"])
    vol_avg = float(a["vol_sma20"].iloc[-1]) + EPS
    factors.append((0.20, np.clip(cs / (0.15 * vol_avg + EPS), -1, 1), "CVD slope"))
    # mean-reversion / location
    bb_pos = a["bb_pos"]
    factors.append((0.10, np.clip((0.5 - bb_pos) * 2, -1, 1), f"BB position={bb_pos:.2f}"))

    total = sum(w * s for w, s, _ in factors)  # -1..1
    score = total * 85
    direction, strength = _dir(score)

    detail = ", ".join(f"{d} [{s:+.2f}x{w}]" for w, s, d in factors)
    if direction == "NEUTRAL":
        return _neutral(name, disp, f"Y-KOF factors offsetting (net {total:+.2f}): {detail}")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 f"Y-KOF weighted confluence {total:+.2f}: {detail} -> {direction}.",
                 price, price - sign * 1.5 * atr_v, price + sign * 2.5 * atr_v)




# =====================================================================
# 9. ICHIMOKU CLOUD
# =====================================================================

def strategy_ichimoku(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "ichimoku", "Ichimoku Cloud"
    price = a["price"]
    atr_v = a["atr_val"]
    tk, kj = float(a["tenkan"].iloc[-1]), float(a["kijun"].iloc[-1])
    sa, sb = float(a["senkou_a"].iloc[-1]), float(a["senkou_b"].iloc[-1])
    top, bot = max(sa, sb), min(sa, sb)
    tkc, kjc = float(a["tenkan"].iloc[-2]), float(a["kijun"].iloc[-2])
    score = 0.0
    reasons = []
    if price > top:
        score += 35
        reasons.append(f"price above the cloud ({bot:.6g}-{top:.6g}) - bullish regime")
    elif price < bot:
        score -= 35
        reasons.append(f"price below the cloud ({bot:.6g}-{top:.6g}) - bearish regime")
    else:
        reasons.append("price inside the cloud - no-trade zone")
    if tkc <= kjc and tk > kj:
        score += 25
        reasons.append("fresh bullish TK cross (Tenkan over Kijun)")
    elif tkc >= kjc and tk < kj:
        score -= 25
        reasons.append("fresh bearish TK cross (Tenkan under Kijun)")
    elif tk > kj:
        score += 10
        reasons.append("Tenkan above Kijun")
    elif tk < kj:
        score -= 10
        reasons.append("Tenkan below Kijun")
    if sa > sb:
        score += 10
        reasons.append("future cloud bullish (Senkou A > B)")
    elif sb > sa:
        score -= 10
        reasons.append("future cloud bearish (Senkou B > A)")
    chikou = float(df["close"].iloc[-26]) if len(df) >= 26 else price
    if price > chikou:
        score += 10
        reasons.append("Chikou span free above price of 26 periods ago")
    elif price < chikou:
        score -= 10
        reasons.append("Chikou span blocked below old price")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "Ichimoku: " + "; ".join(reasons) + " -> conflicting.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "Ichimoku engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.6 * atr_v, price + sign * 2.6 * atr_v)


# =====================================================================
# 10. KELTNER / TTM SQUEEZE
# =====================================================================

def _keltner(df: pd.DataFrame, n=20, mult=2.0):
    mid = ind.ema(df["close"], n)
    rng = ind.atr(df, n) * mult
    return mid + rng, mid, mid - rng


def strategy_keltner(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "keltner", "Keltner / TTM Squeeze"
    price = a["price"]
    atr_v = a["atr_val"]
    ku, km, kl = _keltner(df)
    squeeze_now = bool(a["bb_upper"].iloc[-1] < ku.iloc[-1] and a["bb_lower"].iloc[-1] > kl.iloc[-1])
    squeeze_prev = bool(a["bb_upper"].iloc[-4] < ku.iloc[-4] and a["bb_lower"].iloc[-4] > kl.iloc[-4])
    score = 0.0
    reasons = []
    if squeeze_prev and not squeeze_now:
        if price > km.iloc[-1]:
            score += 60
            reasons.append("TTM SQUEEZE FIRED upward: Bollinger escaped Keltner channel, price broke above KC mid")
        elif price < km.iloc[-1]:
            score -= 60
            reasons.append("TTM SQUEEZE FIRED downward: Bollinger escaped Keltner channel, price broke below KC mid")
    elif squeeze_now:
        return _neutral(name, disp, "Keltner: squeeze ON (volatility coiling) - wait for the fire direction.")
    else:
        slope = float(km.iloc[-1] - km.iloc[-6])
        if price > ku.iloc[-1]:
            score += 30
            reasons.append("riding above upper Keltner band - strong markup")
        elif price < kl.iloc[-1]:
            score -= 30
            reasons.append("riding below lower Keltner band - strong markdown")
        elif slope > 0:
            score += 18
            reasons.append("KC mid rising - intrabar trend up")
        elif slope < 0:
            score -= 18
            reasons.append("KC mid falling - intrabar trend down")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "Keltner: no squeeze fire, flat channel.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "Keltner/TTM engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.3 * atr_v, price + sign * 2.4 * atr_v)


# =====================================================================
# 11. CANDLESTICK PATTERNS
# =====================================================================

def _candle_patterns(df: pd.DataFrame) -> list:
    """Return [(side, label)] for patterns on the last 3 candles."""
    out = []
    if len(df) < 4:
        return out
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    rng3 = max(h[-3:] .max() - l[-3:].min(), 1e-12)
    for i in (-1, -2):
        body = abs(c[i] - o[i])
        full = max(h[i] - l[i], 1e-12)
        up_wick = h[i] - max(o[i], c[i])
        dn_wick = min(o[i], c[i]) - l[i]
        if body <= 0.1 * full:
            out.append(("neutral", f"doji at candle {i} (indecision)"))
        if dn_wick >= 2 * body and up_wick <= 0.3 * body and l[i] <= df["low"].values[-20:].min() * 1.002:
            out.append(("buy", f"hammer / pin bar at candle {i} (long lower wick at lows)"))
        if up_wick >= 2 * body and dn_wick <= 0.3 * body and h[i] >= df["high"].values[-20:].max() * 0.998:
            out.append(("sell", f"shooting star at candle {i} (long upper wick at highs)"))
    # engulfing
    b1, b0 = abs(c[-2] - o[-2]), abs(c[-1] - o[-1])
    if c[-2] < o[-2] and c[-1] > o[-1] and c[-1] >= o[-2] and o[-1] <= c[-2] and b0 > b1:
        out.append(("buy", "bullish engulfing"))
    if c[-2] > o[-2] and c[-1] < o[-1] and c[-1] <= o[-2] and o[-1] >= c[-2] and b0 > b1:
        out.append(("sell", "bearish engulfing"))
    # three soldiers / crows
    if all(c[j] > o[j] for j in (-3, -2, -1)) and c[-1] > c[-2] > c[-3]:
        out.append(("buy", "three white soldiers"))
    if all(c[j] < o[j] for j in (-3, -2, -1)) and c[-1] < c[-2] < c[-3]:
        out.append(("sell", "three black crows"))
    # morning / evening star
    if c[-3] < o[-3] and abs(c[-2] - o[-2]) < 0.3 * abs(c[-3] - o[-3]) and c[-1] > o[-1] and c[-1] > (o[-3] + c[-3]) / 2:
        out.append(("buy", "morning star"))
    if c[-3] > o[-3] and abs(c[-2] - o[-2]) < 0.3 * abs(c[-3] - o[-3]) and c[-1] < o[-1] and c[-1] < (o[-3] + c[-3]) / 2:
        out.append(("sell", "evening star"))
    _ = rng3
    return out


def strategy_candles(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "candles", "Candlestick Patterns"
    price = a["price"]
    atr_v = a["atr_val"]
    pats = _candle_patterns(df)
    score = 0.0
    reasons = []
    for side, label in pats:
        if side == "buy":
            score += 30
            reasons.append(label)
        elif side == "sell":
            score -= 30
            reasons.append(label)
    if not reasons:
        return _neutral(name, disp, "Candlesticks: no actionable pattern on the last candles.")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "Candlesticks: mixed patterns (" + "; ".join(reasons) + ").")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "Candlestick engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.2 * atr_v, price + sign * 2.2 * atr_v)


# =====================================================================
# 12. WYCKOFF STRUCTURE
# =====================================================================

def strategy_wyckoff(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "wyckoff", "Wyckoff Structure"
    price = a["price"]
    atr_v = a["atr_val"]
    n = len(df)
    if n < 100:
        return _neutral(name, disp, "Wyckoff: not enough history for a range study.")
    w = df.iloc[-100:-1]
    rh, rl = float(w["high"].max()), float(w["low"].min())
    width = (rh - rl) / (price + EPS) * 100
    score = 0.0
    reasons = []
    in_range = rl <= price <= rh
    if not in_range or width < 1.5:
        if price > rh:
            score += 45
            reasons.append(f"Wyckoff MARKUP: price left the 100-candle range upward ({rh:.6g}) - sign of strength")
        elif price < rl:
            score -= 45
            reasons.append(f"Wyckoff MARKDOWN: price left the range downward ({rl:.6g}) - sign of weakness")
        else:
            return _neutral(name, disp, f"Wyckoff: range too narrow ({width:.1f}%) to classify.")
    else:
        # spring / upthrust inside last 12 candles
        recent = df.iloc[-12:]
        vol_avg = float(a["vol_sma20"].iloc[-1]) + EPS
        spr = recent[(recent["low"] < rl * 1.001) & (recent["close"] > rl)]
        upt = recent[(recent["high"] > rh * 0.999) & (recent["close"] < rh)]
        if len(spr):
            i = spr.index[-1]
            v = float(df.loc[i, "volume"])
            score += 55 + (10 if v > 1.3 * vol_avg else 0)
            reasons.append(f"SPRING: wash below range low {rl:.6g} reclaimed on "
                           f"{'high' if v > 1.3*vol_avg else 'normal'} volume - accumulation (Wyckoff test)")
        if len(upt):
            i = upt.index[-1]
            v = float(df.loc[i, "volume"])
            score -= 55 + (10 if v > 1.3 * vol_avg else 0)
            reasons.append(f"UPTHRUST: poke above range high {rh:.6g} rejected on "
                           f"{'high' if v > 1.3*vol_avg else 'normal'} volume - distribution")
        # effort vs result: volume on up vs down candles inside range
        rw = df.iloc[-60:]
        upv = float(rw[rw["close"] >= rw["open"]]["volume"].sum())
        dnv = float(rw[rw["close"] < rw["open"]]["volume"].sum()) + EPS
        if upv / dnv > 1.15:
            score += 18
            reasons.append(f"effort/result: up-candle volume {upv/dnv:.2f}x down-candle volume -> accumulation bias")
        elif upv / dnv < 0.87:
            score -= 18
            reasons.append(f"effort/result: down-candle volume dominates ({upv/dnv:.2f}) -> distribution bias")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "Wyckoff: range balanced, no spring/upthrust yet.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "Wyckoff engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.5 * atr_v, price + sign * 2.8 * atr_v)


# =====================================================================
# 13. FLOOR PIVOT POINTS
# =====================================================================

def strategy_pivots(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "pivots", "Floor Pivot Points"
    price = a["price"]
    atr_v = a["atr_val"]
    try:
        idx = pd.to_datetime(df.index, unit="ms")
        daily = pd.DataFrame({"high": df["high"].values, "low": df["low"].values,
                              "close": df["close"].values}, index=idx).resample("1D").agg(
            {"high": "max", "low": "min", "close": "last"}).dropna()
        if len(daily) < 2:
            raise ValueError("need 2 daily bars")
        ph, pl, pc = float(daily["high"].iloc[-2]), float(daily["low"].iloc[-2]), float(daily["close"].iloc[-2])
    except Exception:
        return _neutral(name, disp, "Pivots: daily aggregation unavailable on this timeframe.")
    P = (ph + pl + pc) / 3
    R1, S1 = 2 * P - pl, 2 * P - ph
    R2, S2 = P + (ph - pl), P - (ph - pl)
    R3, S3 = ph + 2 * (P - pl), pl - 2 * (ph - P)
    last = df.iloc[-1]
    score = 0.0
    reasons = [f"daily pivots P={P:.6g} R1={R1:.6g} R2={R2:.6g} S1={S1:.6g} S2={S2:.6g}"]
    lv = float(last["close"])
    for lvl, tag in ((S1, "S1"), (S2, "S2"), (S3, "S3")):
        if abs(lv - lvl) < 0.35 * atr_v and last["low"] <= lvl and max(last["open"], last["close"]) > lvl:
            score += 45
            reasons.append(f"bounce holding above {tag} ({lvl:.6g})")
    for lvl, tag in ((R1, "R1"), (R2, "R2"), (R3, "R3")):
        if abs(lv - lvl) < 0.35 * atr_v and last["high"] >= lvl and min(last["open"], last["close"]) < lvl:
            score -= 45
            reasons.append(f"rejection under {tag} ({lvl:.6g})")
    if score == 0:
        if lv > P:
            score += 15
            reasons.append("trading above the daily pivot - intraday bulls in control")
        else:
            score -= 15
            reasons.append("trading below the daily pivot - intraday bears in control")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "Pivots: " + "; ".join(reasons) + " -> no reaction yet.")
    sign = 1 if direction == "LONG" else -1
    target = R1 if direction == "LONG" else S1
    return _vote(name, disp, direction, strength,
                 "Pivot engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.2 * atr_v, target)


# =====================================================================
# 14. ADX / DI TREND POWER
# =====================================================================

def strategy_adxdi(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "adxdi", "ADX/DI Trend Power"
    price = a["price"]
    atr_v = a["atr_val"]
    adx_v = a["adx_val"]
    pdi, mdi = float(a["pdi"].iloc[-1]), float(a["mdi"].iloc[-1])
    pdi_p, mdi_p = float(a["pdi"].iloc[-3]), float(a["mdi"].iloc[-3])
    score = 0.0
    reasons = [f"ADX {adx_v:.0f}"]
    if adx_v < 18:
        return _neutral(name, disp, f"ADX/DI: ADX {adx_v:.0f} < 18 - trend too weak to trade.")
    if pdi > mdi:
        score += min(adx_v * 1.4, 60)
        reasons.append(f"+DI {pdi:.0f} above -DI {mdi:.0f} in a strong trend")
    else:
        score -= min(adx_v * 1.4, 60)
        reasons.append(f"-DI {mdi:.0f} above +DI {pdi:.0f} in a strong trend")
    if pdi_p <= mdi_p and pdi > mdi:
        score += 15
        reasons.append("fresh +DI cross up")
    elif pdi_p >= mdi_p and pdi < mdi:
        score -= 15
        reasons.append("fresh -DI cross down")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "ADX/DI: balanced.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "ADX/DI engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.6 * atr_v, price + sign * 2.8 * atr_v)


# =====================================================================
# 15. STOCHASTIC EXTREMES
# =====================================================================

def strategy_stochx(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "stochx", "Stochastic Extremes"
    price = a["price"]
    atr_v = a["atr_val"]
    k, d = float(a["stoch_k"].iloc[-1]), float(a["stoch_d"].iloc[-1])
    kp, dp = float(a["stoch_k"].iloc[-2]), float(a["stoch_d"].iloc[-2])
    score = 0.0
    reasons = []
    if kp < 20 and k >= 20 and k > d:
        score += 55
        reasons.append(f"%K crossed up out of oversold (<20) over %D - reversal trigger (K={k:.0f})")
    elif kp > 80 and k <= 80 and k < d:
        score -= 55
        reasons.append(f"%K crossed down out of overbought (>80) under %D - reversal trigger (K={k:.0f})")
    elif k < 15:
        score += 20
        reasons.append(f"deep oversold %K={k:.0f} - spring loaded for a bounce")
    elif k > 85:
        score -= 20
        reasons.append(f"deep overbought %K={k:.0f} - stretched for a pullback")
    else:
        slope = k - kp
        score += 12 if (slope > 0 and k > d) else -12 if (slope < 0 and k < d) else 0
        if score:
            reasons.append(f"stochastic momentum {'up' if score > 0 else 'down'} mid-range")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, f"Stochastic: K={k:.0f} D={d:.0f} mid-range, no edge.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "Stochastic engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.1 * atr_v, price + sign * 2.0 * atr_v)


# =====================================================================
# 16. OBV VOLUME DIVERGENCE
# =====================================================================

def strategy_obvdiv(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "obvdiv", "OBV Volume Divergence"
    price = a["price"]
    atr_v = a["atr_val"]
    obv_s = a["obv"].tail(30)
    px = df["close"].tail(30)
    obv_slope = float(np.polyfit(np.arange(len(obv_s)), obv_s.values, 1)[0])
    px_slope = float(np.polyfit(np.arange(len(px)), px.values, 1)[0])
    obv_ema = ind.ema(a["obv"], 20)
    score = 0.0
    reasons = []
    vol_avg = float(a["vol_sma20"].iloc[-1]) + EPS
    norm = obv_slope / vol_avg
    if norm > 0.15 and px_slope <= 0:
        score += 55
        reasons.append("BULLISH DIVERGENCE: OBV climbing while price flat/down - smart money accumulating")
    elif norm < -0.15 and px_slope >= 0:
        score -= 55
        reasons.append("BEARISH DIVERGENCE: OBV falling while price flat/up - smart money distributing")
    elif norm > 0.15:
        score += 25
        reasons.append("OBV confirming the up-move (volume-backed)")
    elif norm < -0.15:
        score -= 25
        reasons.append("OBV confirming the down-move (volume-backed)")
    if float(a["obv"].iloc[-1]) > float(obv_ema.iloc[-1]) and float(a["obv"].iloc[-6]) <= float(obv_ema.iloc[-6]):
        score += 12
        reasons.append("OBV reclaimed its 20-EMA")
    elif float(a["obv"].iloc[-1]) < float(obv_ema.iloc[-1]) and float(a["obv"].iloc[-6]) >= float(obv_ema.iloc[-6]):
        score -= 12
        reasons.append("OBV lost its 20-EMA")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "OBV: volume and price in balance.")
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "OBV engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.4 * atr_v, price + sign * 2.4 * atr_v)


# =====================================================================
# 17. GOLDEN POCKET FIB
# =====================================================================

def strategy_goldfib(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "goldfib", "Golden Pocket Fib"
    price = a["price"]
    atr_v = a["atr_val"]
    zz = a.get("zigzag", [])
    if len(zz) < 2:
        return _neutral(name, disp, "Golden Pocket: no swing leg to measure.")
    (p0, v0, t0), (p1, v1, t1) = zz[-2], zz[-1]
    leg_hi, leg_lo = max(v0, v1), min(v0, v1)
    diff = leg_hi - leg_lo + EPS
    gp_hi = leg_hi - 0.618 * diff
    gp_lo = leg_hi - 0.79 * diff
    last = df.iloc[-1]
    reasons = [f"last impulse {t0}->{t1} leg {leg_lo:.6g}-{leg_hi:.6g}; golden pocket {gp_lo:.6g}-{gp_hi:.6g}"]
    score = 0.0
    if gp_lo * 0.998 <= price <= gp_hi * 1.002:
        body = max(last["open"], last["close"])
        if t1 == "L" and last["low"] <= gp_hi and body > gp_lo:
            score += 60
            reasons.append("price sitting in the golden pocket of a DOWN-leg with rejection wick - classic reversal long zone")
        elif t1 == "H" and last["high"] >= gp_lo and body < gp_hi:
            score -= 60
            reasons.append("price sitting in the golden pocket of an UP-leg with rejection wick - classic reversal short zone")
        else:
            score += 25 if t1 == "L" else -25
            reasons.append("inside golden pocket, awaiting rejection confirmation")
    else:
        return _neutral(name, disp, "Golden Pocket: " + "; ".join(reasons) + " -> price outside the pocket.")
    direction, strength = _dir(score)
    if direction == "NEUTRAL":
        return _neutral(name, disp, "Golden Pocket: " + "; ".join(reasons))
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "Golden Pocket engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.0 * atr_v, price + sign * 2.6 * atr_v)


# =====================================================================
# 18. FUNDING CONTRARIAN
# =====================================================================

def strategy_fundrev(df: pd.DataFrame, a: dict) -> dict:
    name, disp = "fundrev", "Funding Contrarian"
    fr = a.get("funding_rate")
    if fr is None:
        return _neutral(name, disp, "Funding data not available in this context.")
    price = a["price"]
    atr_v = a["atr_val"]
    frp = float(fr) * 100
    reasons = [f"current funding {frp:+.4f}%"]
    score = 0.0
    if frp > 0.03:
        score -= min(30 + frp * 300, 70)
        reasons.append(f"EXTREME POSITIVE funding {frp:.4f}% - longs overcrowded & paying heavily; "
                       "squeeze risk against them (contrarian short bias)")
    elif frp < -0.03:
        score += min(30 + abs(frp) * 300, 70)
        reasons.append(f"EXTREME NEGATIVE funding {frp:.4f}% - shorts overcrowded & paying heavily; "
                       "squeeze risk against them (contrarian long bias)")
    elif frp > 0.01:
        score -= 10
        reasons.append("mildly positive funding - slight long crowding")
    elif frp < -0.01:
        score += 10
        reasons.append("mildly negative funding - slight short crowding")
    else:
        return _neutral(name, disp, "Funding: neutral (" + f"{frp:+.4f}%" + ") - no contrarian edge.")
    direction, strength = _dir(score)
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 "Funding engine: " + "; ".join(reasons) + f" -> {direction}.",
                 price, price - sign * 1.5 * atr_v, price + sign * 2.2 * atr_v)


# =====================================================================
# 19. NEUROQUANT ML  (advanced free self-learning engine)
# =====================================================================

def strategy_neuroquant(df: pd.DataFrame, a: dict) -> dict:
    """Free on-device ML engine: online logistic regression trained on the
    coin's own recent candles (walk-forward). No cloud, no tokens, no libs
    beyond numpy. Reports out-of-sample accuracy in its reason."""
    name, disp = "neuroquant", "NeuroQuant ML (free)"
    price = a["price"]
    atr_v = a["atr_val"]
    n = len(df)
    if n < 180:
        return _neutral(name, disp, "NeuroQuant: not enough candles to train.")
    close = df["close"].values.astype(float)
    feat = np.column_stack([
        (a["rsi"].values - 50) / 25.0,
        a["macd_hist"].values / (a["atr"].values + EPS),
        (a["bb_upper"].values - close) / (a["bb_upper"].values - a["bb_lower"].values + EPS) - 0.5,
        a["delta"].values / (df["volume"].values + EPS),
        np.clip(a["cvd_slope"].values / (a["vol_sma20"].values + EPS), -3, 3),
        np.clip(a["roc"].values / 5.0, -3, 3),
        (close - a["ema20"].values) / (a["atr"].values + EPS),
        (close - a["ema50"].values) / (a["atr"].values + EPS),
        (a["stoch_k"].values - 50) / 25.0,
        np.sign(a["supertrend_dir"].values),
    ])
    H = 6  # horizon candles
    fwd = np.zeros(n)
    fwd[:-H] = (close[H:] - close[:-H]) / (close[:-H] + EPS)
    thr = max(a["atr_pct"] / 100.0 * 0.35, 0.0006)
    y = np.where(fwd > thr, 1.0, np.where(fwd < -thr, -1.0, 0.0))
    mask = y != 0
    X = feat[mask]
    Y = y[mask]
    if len(Y) < 60:
        return _neutral(name, disp, "NeuroQuant: too few labelled samples.")
    X = np.clip(np.nan_to_num(X), -5, 5)
    Xb = np.hstack([X, np.ones((len(X), 1))])          # bias term
    split = max(int(len(Y) * 0.7), 30)
    w = np.zeros(Xb.shape[1])

    def train(Xt, Yt, iters=120, lr=0.08):
        wv = np.zeros(Xt.shape[1])
        for _ in range(iters):
            p = 1 / (1 + np.exp(-np.clip(Xt @ wv, -30, 30)))
            g = Xt.T @ (p - (Yt > 0).astype(float)) / len(Yt) + 0.01 * wv
            wv -= lr * g
        return wv

    w_train = train(Xb[:split], Y[:split])             # out-of-sample check
    p_test = 1 / (1 + np.exp(-np.clip(Xb[split:] @ w_train, -30, 30)))
    acc = float(((p_test > 0.5) == (Y[split:] > 0)).mean())
    w = train(Xb, Y)                                   # full-history model
    p_now = float(1 / (1 + np.exp(-np.clip(Xb[-1] @ w, -30, 30))))
    if acc < 0.52 or len(Y) - split < 15:
        return _neutral(name, disp,
                        f"NeuroQuant: out-of-sample accuracy {acc*100:.0f}% < 52% - model refuses to trade this regime.")
    direction = "LONG" if p_now > 0.5 else "SHORT"
    strength = min(90.0, (acc - 0.5) * 300 + abs(p_now - 0.5) * 160)
    contrib = X[-1] * w[:-1]
    top = np.argsort(-np.abs(contrib))[:3]
    fnames = ["RSI", "MACDhist", "BBpos", "takerDelta", "CVDslope", "ROC",
              "vsEMA20", "vsEMA50", "Stoch", "SuperTrend"]
    detail = ", ".join(f"{fnames[i]} {contrib[i]:+.2f}" for i in top)
    sign = 1 if direction == "LONG" else -1
    return _vote(name, disp, direction, strength,
                 f"NeuroQuant ML engine (free, on-device logistic regression trained on this coin): "
                 f"out-of-sample accuracy {acc*100:.0f}% on {len(Y)-split} held-out candles, "
                 f"live probability P(up)={p_now:.2f} -> {direction}; top feature drivers: {detail}.",
                 price, price - sign * 1.4 * atr_v, price + sign * 2.4 * atr_v)



# =====================================================================
# registry
# =====================================================================

STRATEGIES = {
    "orderflow": strategy_orderflow,
    "niyowew": strategy_niyowew,
    "msnr": strategy_msnr,
    "smc": strategy_smc,
    "ict2022": strategy_ict2022,
    "elliott": strategy_elliott,
    "sk": strategy_sk,
    "ykof": strategy_ykof,
    "ichimoku": strategy_ichimoku,
    "keltner": strategy_keltner,
    "candles": strategy_candles,
    "wyckoff": strategy_wyckoff,
    "pivots": strategy_pivots,
    "adxdi": strategy_adxdi,
    "stochx": strategy_stochx,
    "obvdiv": strategy_obvdiv,
    "goldfib": strategy_goldfib,
    "fundrev": strategy_fundrev,
    "neuroquant": strategy_neuroquant,
}

STRATEGY_DISPLAY = {k: f(k, k) for k in []}  # placeholder
DISPLAY_NAMES = {
    "orderflow": "Order Flow",
    "niyowew": "Niyowew (Neural Wave)",
    "msnr": "MNSR (Support/Resistance)",
    "smc": "SMC (Smart Money Concepts)",
    "ict2022": "ICT (2022 Model)",
    "elliott": "Eliyat Vew (Elliott Wave)",
    "sk": "SK (Sniper Key)",
    "ykof": "Y-KOF (Confluence Key)",
    "ichimoku": "Ichimoku Cloud",
    "keltner": "Keltner / TTM Squeeze",
    "candles": "Candlestick Patterns",
    "wyckoff": "Wyckoff Structure",
    "pivots": "Floor Pivot Points",
    "adxdi": "ADX/DI Trend Power",
    "stochx": "Stochastic Extremes",
    "obvdiv": "OBV Volume Divergence",
    "goldfib": "Golden Pocket Fib",
    "fundrev": "Funding Contrarian",
    "neuroquant": "NeuroQuant ML (free)",
}


def run_strategies(df: pd.DataFrame, a: dict, names=None) -> list:
    """Run selected strategies, returning their votes (errors isolated)."""
    names = names or list(STRATEGIES.keys())
    votes = []
    for nm in names:
        fn = STRATEGIES.get(nm)
        if not fn:
            continue
        try:
            votes.append(fn(df, a))
        except Exception as e:
            votes.append(_neutral(nm, DISPLAY_NAMES.get(nm, nm), f"engine error: {e}"))
    return votes


def combine_votes(votes: list, min_agreement: float = 0.0) -> dict:
    """Weighted combination -> side, confidence, score, agreeing strategies."""
    signed = {"LONG": 0.0, "SHORT": 0.0}
    for v in votes:
        if v["direction"] in signed:
            signed[v["direction"]] += v["strength"]
    total = signed["LONG"] + signed["SHORT"] + EPS
    side = "LONG" if signed["LONG"] > signed["SHORT"] else "SHORT" if signed["SHORT"] > signed["LONG"] else "NEUTRAL"
    dominant = max(signed.values())
    agreement = (dominant / total * 100) if total > 0 else 0.0
    strength_factor = min(1.0, 0.45 + dominant / 250.0)
    confidence = min(97.0, agreement * strength_factor)
    agreeing = [v for v in votes if v["direction"] == side]
    net = signed["LONG"] - signed["SHORT"]
    return {
        "side": side,
        "net_score": round(float(net), 1),
        "long_score": round(float(signed["LONG"]), 1),
        "short_score": round(float(signed["SHORT"]), 1),
        "confidence": round(float(confidence), 1),
        "agreeing": [v["display"] for v in agreeing],
        "n_agree": len(agreeing),
        "n_total": len(votes),
    }
