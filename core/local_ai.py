"""
Built-in LOCAL AI engine - the free, token-less fallback.

It is a deterministic rule-based "analyst": it reads the same indicator and
strategy data a cloud LLM would receive and writes the signal JSON itself.
This guarantees the app ALWAYS produces signals even when:
  - every API key is exhausted / rate limited
  - there is no AI connectivity at all
  - the user wants zero-cost operation forever
"""

from . import strategies as st


def local_signal_reason(symbol: str, combo: dict, votes: list, snap: dict,
                        extras: dict = None) -> str:
    """Compose a rich strategy/technique/logic explanation locally."""
    extras = extras or {}
    parts = []
    agreeing = [v for v in votes if v["direction"] == combo["side"]]
    top = sorted(agreeing, key=lambda v: -v["strength"])[:3]
    for v in top:
        w = v.get("weight", 1.0)
        parts.append(f"[{v['display']} -> {v['direction']} {v['strength']:.0f}% "
                     f"(learned weight x{w:.2f})] {v['reason']}")
    opposed = [v for v in votes if v["direction"] not in (combo["side"], "NEUTRAL")]
    if opposed:
        parts.append("Counter-view noted: " + "; ".join(
            f"{v['display']} sees {v['direction']}" for v in opposed[:2]))
    htf = extras.get("htf")
    if htf:
        aligned = "ALIGNED" if extras.get("htf_aligned") else "COUNTER-TREND (penalized)"
        parts.append(f"HIGHER-TIMEFRAME CHECK ({htf.get('timeframe')}): bias {htf.get('bias')} "
                     f"(trend {htf.get('trend')}, SuperTrend {htf.get('supertrend')}, "
                     f"ADX {htf.get('adx')}) -> {aligned}")
    gates = extras.get("gates") or {}
    if gates.get("soft"):
        parts.append("Risk notes: " + "; ".join(gates["soft"]))
    parts.append(
        f"Market context: trend={snap.get('trend')}, RSI={snap.get('rsi_val', 0):.1f}, "
        f"ADX={snap.get('adx_val', 0):.1f}, ATR%={snap.get('atr_pct', 0):.2f}, "
        f"CVD slope={snap.get('cvd_slope_val', 0):+.1f}, funding={snap.get('funding_rate', 0)*100:.4f}%")
    return " | ".join(parts)


def build_local_signal(symbol: str, interval: str, price: float, side: str,
                       entry: float, sl: float, tp: float, combo: dict,
                       votes: list, snap: dict, confidence: float) -> dict:
    """Signal dict produced entirely locally (same schema as AI-enhanced)."""
    return {
        "coin": symbol,
        "timeframe": interval,
        "side": side,
        "live_price": round(price, 8),
        "entry_price": round(entry, 8),
        "stop_loss": round(sl, 8),
        "take_profit": round(tp, 8),
        "take_profit_levels": [],
        "confidence": round(confidence, 1),
        "risk_reward": round(abs(tp - entry) / max(abs(entry - sl), 1e-12), 2),
        "reason": local_signal_reason(symbol, combo, votes, snap),
        "strategy_breakdown": [
            {"strategy": v["display"], "direction": v["direction"],
             "strength": v["strength"], "reason": v["reason"]} for v in votes
        ],
        "ai_provider": "local-engine (built-in free)",
        "ai_model": "rule-based-confluence-v1",
        "disclaimer": "Not financial advice. Analysis tool only - no orders are placed.",
    }
