# AlphaWave — Binance Futures AI Signal Terminal

A complete **Python desktop-style terminal** for Binance USDT-M **futures analysis & AI signal generation**, with:

* a **graphical desktop-style app** (dark trading UI served locally, opens in your browser)
* a **Telegram bot** that mirrors **every** feature of the app
* **19 strategy engines**: your 8 requested methods — `Order Flow`, `Niyowew (neural wave)`, `MNSR`, `SMC`, `ICT (2022)`, `Eliyat Vew (Elliott Wave)`, `SK (sniper)`, `Y-KOF (confluence)` — plus 10 more: `Ichimoku Cloud`, `Keltner/TTM Squeeze`, `Candlestick Patterns`, `Wyckoff Structure`, `Floor Pivot Points`, `ADX/DI Trend Power`, `Stochastic Extremes`, `OBV Volume Divergence`, `Golden Pocket Fib`, `Funding Contrarian` — and the advanced free **`NeuroQuant ML`** engine (on-device logistic regression that trains on the coin's own candles and reports out-of-sample accuracy)
* **7 live chart styles**: candles, hollow candles, OHLC bars, line, area, baseline, Heikin-Ashi — with a 4-second LIVE tick (last candle moves up/down in real time + flashing price ticker)
* an **AI chain**: Groq (4 models) → OpenRouter (3+ free models) → Ollama (2 local models) → custom endpoint → **built-in free local engine** (signals NEVER fail, even with zero tokens)
* **30 trading/analysis tools** available in the GUI and the Telegram bot
* **random-coin funnel**: best ≤1000 → top 100 → top 10 → best 1 → full signal

> ⚠️ **This is NOT an auto-trading tool.** It never places orders, never connects
> with trading permissions, and **uses NO Binance API key/secret** — only public
> market-data endpoints. It is an analysis & education terminal.

---

## Features

### Markets
* All Binance USDT-M perpetual contracts (live table: price, 24h %, volume, funding, trades)
* Live candlestick chart with indicators you can toggle: EMA 9/20/50/100/200, Hull MA, Bollinger,
  Keltner, VWAP, SuperTrend, Parabolic SAR, Ichimoku (Tenkan/Kijun/Senkou), daily Pivot Points
  and Fib levels as price lines; sub-panes: RSI, MACD, Stochastic, Stoch-RSI, CCI, Williams %R,
  MFI, ADX+DI, OBV, ROC, ATR, CVD. The chart library is bundled locally (no CDN dependency),
  and a 4-second LIVE tick moves the last candle + flashes the price ticker up/down.
* **Buy/Sell highlights (▲▼)** on the chart from strategy events: EMA/MACD crosses,
  SuperTrend flips, RSI extremes, BB rejections, Donchian breakouts, volume spikes,
  liquidity sweeps, BOS structure breaks
* SMC zones panel: unfilled Fair Value Gaps & order blocks
* 10-second auto-refresh "watch mode"

### Signals (what every signal contains)
| Field | Meaning |
|---|---|
| coin | e.g. BTCUSDT |
| live market price | last traded price at generation time |
| side | LONG / SHORT / NO TRADE |
| entry price | market or pullback entry (FVG / structure based) |
| stop loss | structure/ATR based invalidation |
| take profit | main TP + 3-level TP ladder with R multiples |
| confidence | weighted engine agreement (0–97%) |
| risk : reward | reward/risk of entry→TP vs entry→SL |
| **recommended leverage** | **10x–20x** standard band; **>20x (max 30x) ONLY** for extreme-quality setups (conf ≥85% + ≥6/8 engines + R:R ≥2 + contained volatility); includes estimated liquidation distance |
| **reason** | exact strategies + techniques + logic that produced the call |
| ai_provider / model | which AI wrote/refined it (`local free engine` if none) |

### Accuracy Engine v2 (how AlphaWave keeps getting sharper)
1. **Walk-forward adaptive weights** — all 8 engines are replayed on the recent
   history of the *same coin & timeframe*; engines that actually predicted the
   next candles vote heavier, failing engines get muted (cached 15 min).
2. **Realized-outcome learning** — every journal signal is followed up
   (did price tag TP or SL first?) and per-engine win/loss records in
   `data/strategy_stats.json` blend into the weights. The bot learns from its
   own live track record. Inspect with `/accuracy` or the GUI "Load learned
   weights" button.
3. **Higher-timeframe gate** — a signal must agree with the HTF bias
   (e.g. 1h for a 15m signal); counter-trend calls need ≥70% raw confluence or
   they are converted to NO TRADE; aligned calls get a confidence bonus.
4. **Market quality gates** — dead markets (ATR% < 0.04), chaotic markets
   (ATR% > 4), illiquid books (< $1.5M/24h), spreads > 0.10% are refused
   outright; extreme funding and stale triggers penalize confidence.

### Leverage policy (built-in risk guard)Every signal carries a **recommended leverage**:
* **STANDARD tier** — always between **10x and 20x**, scaled by confidence and
  de-rated when the coin is volatile (high ATR%).
* **EXTREME tier (>20x, capped 30x)** — issued **only** for extremely high-quality
  opportunities: confidence ≥ 85%, at least 6 of 8 strategy engines agreeing,
  R:R ≥ 2.0 and ATR% ≤ 1.0 per candle. Anything less is hard-capped at 20x.
* Each signal also shows the estimated isolated-margin liquidation distance for
  the recommended leverage. Tune thresholds in `config.json → trading.leverage`.

### Random coin funnel (`/random` or GUI)
`best 1000 (by volume, min-liquidity filtered)` → **top 100** (liquidity + tradable-range score)
→ **top 10** (1h trend/RSI/ADX/volume deep scan) → **best 1** (full 8-engine confluence) → signal.

### AI provider chain (auto-failover, token-safe)
1. **Groq** — 4 verified models: `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `openai/gpt-oss-20b`, `groq/compound-mini`
2. **OpenRouter** — 3 verified free models: `deepseek/deepseek-v4-flash-0731:free`, `nvidia/nemotron-3-super-120b-a12b:free`, `liquid/lfm-2.6b…2.6b:free` + 4 backup free models
3. **Ollama** — 2 local models (free & unlimited, runs on your PC)
4. **Custom** — any OpenAI-compatible endpoint (Google AI Studio free key, LM Studio…)
5. **Local engine** — deterministic rule-based analyst. **Always works. Always free.**

Keys rotate round-robin; failed models enter cooldown and are retried later; prompts are
compact to save tokens; on any JSON parse/validation error the chain falls through to the
local engine, so **a signal is always produced**.

### 30 tools (GUI "Tools" tab + Telegram)
Multi-TF trend scanner, S/R levels, Fibonacci+OTE, order flow/CVD, funding, open interest,
long/short ratio, liquidity zones, Fear & Greed, market breadth, top movers, volume spikes,
breakout/squeeze, RSI divergence, MACD, SuperTrend, EMA ribbon, Ichimoku, VWAP deviation,
position-size calculator, R:R calculator, liquidation estimator, funding cost, correlation,
volatility rank, news sentiment, BTC/ETH dominance, signal journal, mini backtester.

### Telegram bot — personal interface for EVERY user
**Multi-user access control:** run the bot in `open` mode (anyone) or `whitelist` mode
where up to **100 Telegram IDs by default** (raise `max_users` anytime) get access.
Manage it two ways:
* **GUI → Bot tab → Access Control panel** — add/remove IDs with notes, bulk-import
  pasted ID lists, set admins, switch mode, watch the live `x/100` counter.
* **From Telegram (admins only)** — `/allow <id> [note]`, `/revoke <id>`, `/users`,
  `/accessmode open|whitelist`. Locked-out users send `/request` and admins get an
  **Approve button** right in Telegram.

Any Telegram account that presses /start gets **its own private interface**:
a personal dashboard message with buttons (Signal / Random / Chart / Analyze /
News / Tools / AI / Status) bound to **that user's active coin & timeframe**.
* **Type any coin name** (e.g. `SOL`, `eth`, `DOGEUSDT`) → it becomes your
  active coin for every button and tool. `/coin SOL` works too.
* Every command accepts a coin: `/signal SOL 1h`, `/chart DOGE 15m`,
  `/analyze XRP 4h`, `/trend LINK` … nothing is locked to BTC.
* Sessions are stored per user id (`data/user_sessions.json`) — users never
  interfere with each other; watchlists are per chat as well.
* 44 commands with an auto-installed menu, plus the 30-tool button menu.

Everything above from Telegram: `/signal`, `/random`, `/analyze`, `/chart` (PNG with
markers), `/news`, `/menu` (button menu for all 30 tools), watchlist with confluence alerts,
AI control (`/aimode`, `/aistatus`, `/aitest`), calculators, journal, backtest — 42 commands
with an auto-installed command menu.

---

## Quick start

**Windows:** double-click `install.bat` (or run it) — it creates the venv, installs
dependencies and starts the app.
**Linux / macOS:** `chmod +x install.sh && ./install.sh`

Manual way:

```bash
cd AlphaWave
python -m venv venv
venv\Scripts\activate        # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python main.py               # opens http://127.0.0.1:8787
```

**Full step-by-step setup in Sinhala: `SETUP_GUIDE_SI.md`** (සිංහල සෙටප් ගයිඩ් එක).

## Project layout

```
AlphaWave/
├── main.py                  # entry point (GUI + optional bot)
├── run_bot.py               # Telegram bot only
├── requirements.txt
├── config.json              # keys/models/settings (auto-created; NEVER commit it)
├── SETUP_GUIDE_SI.md        # Sinhala setup guide
├── core/
│   ├── binance_client.py    # public futures REST (no keys!)
│   ├── indicators.py        # TA library + event detector (chart marks)
│   ├── strategies.py        # 8 engines + confluence combiner
│   ├── signal_engine.py     # signal builder + random funnel + journal
│   ├── ai_router.py         # provider chain, rotation, cooldowns
│   ├── local_ai.py          # free built-in fallback analyst
│   ├── news.py              # RSS + Fear&Greed + sentiment
│   ├── tools.py             # 30 tools
│   └── charting.py          # PNG chart renderer (Telegram)
├── gui/                     # Flask + single-page dark trading UI
│   ├── server.py
│   ├── templates/index.html
│   └── static/{css/style.css, js/app.js}
└── bot/telegram_bot.py      # full-control Telegram bot
```

## Security notes
* `config.json` contains your AI keys → **keep it private** (`.gitignore` included).
  The keys you supplied were shared in plain text; consider regenerating them.
* No Binance credentials exist anywhere in this project by design.
* The app only reads public data; trading stays in your own hands.
