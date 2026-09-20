"""
Server-side chart rendering (matplotlib, headless 'Agg').

Produces PNG candlestick charts with indicators and BUY/SELL highlight
markers - used by the Telegram bot (/chart) and the GUI download button.
(The interactive GUI chart itself uses TradingView lightweight-charts in JS.)
"""

import io
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from datetime import datetime

from . import binance_client as bc
from . import indicators as ind

log = logging.getLogger("chart")

UP = "#26a69a"
DOWN = "#ef5350"
BG = "#131722"
FG = "#d1d4dc"
GRID = "#2a2e39"


def render_chart_png(symbol: str, interval: str = "15m", limit: int = 150,
                     overlays=("ema20", "ema50", "vwap"), show_marks: bool = True,
                     sub="rsi", width_in=13, height_in=7.5) -> bytes:
    df = bc.klines(symbol, interval, limit)
    if df.empty:
        raise ValueError("no candle data")
    a = ind.build_analysis(df)

    n_panels = 2 + (1 if sub else 0)
    fig, axes = plt.subplots(
        n_panels, 1, figsize=(width_in, height_in), dpi=110,
        gridspec_kw={"height_ratios": [5, 1.2] + ([1.2] if sub else []), "hspace": 0.06},
        sharex=True)
    ax, axv = axes[0], axes[1]
    for x in axes:
        x.set_facecolor(BG)
        x.grid(color=GRID, linewidth=0.4, alpha=0.6)
        x.tick_params(colors=FG, labelsize=8)
        for s in x.spines.values():
            s.set_color(GRID)
    fig.patch.set_facecolor(BG)

    xs = list(range(len(df)))
    times = [datetime.utcfromtimestamp(t / 1000) for t in df.index]

    # candles --------------------------------------------------------------
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    for i in xs:
        col = UP if c[i] >= o[i] else DOWN
        ax.plot([i, i], [l[i], h[i]], color=col, linewidth=0.7, zorder=2)
        body_lo, body_hi = min(o[i], c[i]), max(o[i], c[i])
        body_h = max(body_hi - body_lo, (h[i] - l[i]) * 0.002)
        ax.add_patch(Rectangle((i - 0.32, body_lo), 0.64, body_h,
                               facecolor=col, edgecolor=col, linewidth=0.5, zorder=3))

    # overlays -------------------------------------------------------------
    colors = {"ema9": "#f0b90b", "ema20": "#2962ff", "ema50": "#e040fb",
              "ema200": "#ff6d00", "vwap": "#00e5ff", "bb": "#787b86",
              "supertrend": "#ffd54f"}
    for name in overlays:
        if name == "bb":
            ax.plot(xs, a["bb_upper"], color=colors["bb"], linewidth=0.7, alpha=0.8)
            ax.plot(xs, a["bb_lower"], color=colors["bb"], linewidth=0.7, alpha=0.8)
            ax.fill_between(xs, a["bb_upper"], a["bb_lower"], color=colors["bb"], alpha=0.06)
        elif name == "supertrend":
            ax.plot(xs, a["supertrend"], color=colors[name], linewidth=1.0,
                    label="SuperTrend")
        elif name in a:
            ax.plot(xs, a[name], color=colors.get(name, "#fff"), linewidth=1.0, label=name.upper())

    # buy/sell marks ---------------------------------------------------------
    if show_marks:
        shown = 0
        for e in a["events"]:
            if e["pos"] < len(df) - 90 or shown >= 28:
                continue
            shown += 1
            if e["side"] == "buy":
                ax.scatter(e["pos"], e["price"] * 0.995, marker="^", s=55,
                           color="#00e676", zorder=5, edgecolors="black", linewidths=0.4)
            else:
                ax.scatter(e["pos"], e["price"] * 1.005, marker="v", s=55,
                           color="#ff1744", zorder=5, edgecolors="black", linewidths=0.4)

    price = float(c[-1])
    chg = (c[-1] - c[0]) / c[0] * 100
    ax.axhline(price, color="#f0b90b", linewidth=0.6, linestyle="--", alpha=0.8)
    ax.set_title(f"{symbol}  {interval}   last={price:g}   ({chg:+.2f}% over {len(df)} candles)"
                 f"   ▲/▼ = strategy buy/sell events",
                 color=FG, fontsize=11, loc="left")
    ax.tick_params(labelbottom=False)

    # volume ----------------------------------------------------------------
    vcols = [UP if c[i] >= o[i] else DOWN for i in xs]
    axv.bar(xs, df["volume"].values, color=vcols, width=0.7, alpha=0.85)
    axv.set_ylabel("Vol", color=FG, fontsize=8)

    # sub indicator -----------------------------------------------------------
    if sub == "rsi":
        axr = axes[2]
        axr.set_facecolor(BG)
        axr.grid(color=GRID, linewidth=0.4, alpha=0.6)
        axr.tick_params(colors=FG, labelsize=8)
        axr.plot(xs, a["rsi"], color="#f0b90b", linewidth=1.0)
        axr.axhline(70, color=DOWN, linewidth=0.6, linestyle="--")
        axr.axhline(30, color=UP, linewidth=0.6, linestyle="--")
        axr.set_ylim(0, 100)
        axr.set_ylabel("RSI", color=FG, fontsize=8)
    elif sub == "macd":
        axr = axes[2]
        axr.set_facecolor(BG)
        axr.grid(color=GRID, linewidth=0.4, alpha=0.6)
        axr.tick_params(colors=FG, labelsize=8)
        hist = a["macd_hist"].values
        axr.bar(xs, hist, color=[UP if v >= 0 else DOWN for v in hist], width=0.7, alpha=0.8)
        axr.plot(xs, a["macd"], color="#2962ff", linewidth=1.0)
        axr.plot(xs, a["macd_signal"], color="#ff6d00", linewidth=1.0)
        axr.set_ylabel("MACD", color=FG, fontsize=8)

    # x labels: every ~len/8 candle
    step = max(len(df) // 8, 1)
    ticks = xs[::step]
    axv.set_xticks(ticks)
    if sub:
        axes[-1].set_xticks(ticks)
        axes[-1].set_xticklabels([times[i].strftime("%m-%d %H:%M") for i in ticks],
                                 rotation=0, fontsize=7, color=FG)
        axv.set_xticklabels([])
    else:
        axv.set_xticks(ticks)
        axv.set_xticklabels([times[i].strftime("%m-%d %H:%M") for i in ticks], fontsize=7, color=FG)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
