# 🇱 සෙටප් ගයිඩ් — AlphaWave (සිංහලෙන්)

මෙය ඔබේ **Binance Futures AI Signal Tool** එකේ සම්පූර්ණ ස්ථාපන හා භාවිත මාර්ගෝපදේශයයි.
කේත සියල්ල English වලින් ඇත; මෙම ගයිඩ් එක පමණක් සිංහලෙනි.

> ⚠️ **වැදගත්:** මෙය **Auto Trading Tool එකක් නොවේ**. මෙය කිසිම order එකක් දමන්නේ නැත.
> Binance API Key / Secret එකක් **අවශ්‍ය නොවේ** (Public market data පමණි).
> මෙය විශ්ලේෂණ/අධ්‍යාපනික මෙවලමකි — Financial Advice නොවේ.

---

## 1️⃣ අවශ්‍ය දේවල් (Requirements)

| දෙය | අවම |
|---|---|
| Python | 3.10 හෝ ඊට අලුත් (python.org වලින් බාගන්න) |
| Internet | Binance + AI providers වෙත සම්බන්ධ වීමට |
| RAM | 2GB+ (Ollama local models සඳහා 8GB+ නිර්දේශිත) |
| OS | Windows 10/11, macOS, Linux ඕනෑම එකක් |

Python install කරද්දි **"Add Python to PATH"** checkbox එක ✔ ලකුණු කිරීම අමතක නොකරන්න.

---

## 2️⃣ ස්ථාපනය (Installation)

### 🚀 පහසුම ක්‍රමය — One-click installer
* **Windows:** `AlphaWave` folder එකේ ඇති **`install.bat`** එක double-click කරන්න
* **Linux / macOS:** terminal එකේ
  ```bash
  cd AlphaWave
  chmod +x install.sh
  ./install.sh
  ```
මෙය venv එක සාදා, dependencies install කර, app එක automa­tic start කරයි
(browser එක http://127.0.0.1:8787 වෙත විවෘත වේ).

### අතින් කරන ක්‍රමය (manual)

### පියවර 1 — Project folder එකට යන්න
`AlphaWave` folder එක ඔබේ පරිගණකයේ කොපි කරන්න (උදා: `C:\AlphaWave`),
ඉන්පසු Terminal / Command Prompt එකේ:

```bash
cd AlphaWave
```

### පියවර 2 — Virtual environment එකක් සාදන්න (නිර්දේශිත)

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```
**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```
activate වූ පසු terminal එකේ `(venv)` ලෙස පෙනේ.

### පියවර 3 — අවශ්‍ය libraries install කරන්න
```bash
pip install -r requirements.txt
```
(මෙය flask, requests, pandas, numpy, matplotlib, python-telegram-bot install කරයි.
Internet එක මන්දගාමී නම් මිනිත්තු කිහිපයක් ගත විය හැක.)

### පියවර 4 — App එක start කරන්න
```bash
python main.py
```
සාර්ථක නම් ඔබේ browser එකේ **http://127.0.0.1:8787** automa­tic විවෘත වේ.
Browser එක automa­tic නොවිවෘත වුවහොත් එම ලිපිනය අතින් ඇතුළත් කරන්න.

> 💡 Browser එක නොවිවෘත වී run වීමට: `python main.py --no-browser`
> 💡 වෙනත් port එකක: `python main.py --port 9000`
> 💡 නවත්තන්න: terminal එකේ `Ctrl + C`

**පළමු වතාවට run කළ විට** `config.json` ගොනුවක් තනිවම සෑදේ — ඔබ දුන් Groq/OpenRouter
keys සහ model ලැයිස්තුව එහි දැනටමත් ඇතුළත්ය. ✨

---

## 3️⃣ GUI එකේ කොටස් (App එක හැසිරවීම)

වම් පැත්තේ sidebar එකෙන් tab 9ක් ඇත:

1. **📊 Dashboard** — BTC/ETH මිල, Fear & Greed, market breadth, gainers/losers, අලුත්ම signals හා news.
2. **🪙 Markets** — Binance futures වල **සියලුම coins** (සෙවීම/sort කිරීම). coin එකක් click කළොත් chart එකට යයි; ⚡ බොත්තමෙන් එවලේම signal එකක්.
3. **📈 Chart** — candlestick chart එක. EMA/Bollinger/VWAP/SuperTrend overlay දැමිය හැක; RSI/MACD/Stochastic/CVD sub-panes; **▲▼ ලකුණු = buy/sell highlight events**; 10s auto-refresh (watch mode); PNG download.
4. **🎯 AI Signals** — coin එකක් තෝරා timeframe එකක් දී **⚡ GENERATE SIGNAL** ඔබන්න.
5. **🎲 Random Funnel** — හොඳම 1000 → 100 → 10 → **1** funnel එක run කර හොඳම coin එකට signal එකක් (30–90 තත්පර).
6. **📰 News** — CoinTelegraph/CoinDesk/Decrypt/CryptoPotato news + sentiment + Binance announcements + Fear & Greed.
7. **🧰 Tools** — trading/analysis **features 30**.
8. **🤖 AI Providers** — Groq/OpenRouter/Ollama/Custom/local engine තත්ත්වය, key වෙනස් කිරීම, model test කිරීම.
9. **✈️ Telegram Bot** — bot token එක දමා bot එක start/stop කිරීම.

### Signal එකක ඇතුළත් දේ
* coin නම · timeframe
* **live market price**
* **side** (LONG 🟢 / SHORT 🔴 / NO TRADE ⚪)
* **entry price**, **stop loss**, **take profit** (+ TP1/TP2/TP3 ladder)
* confidence %, risk:reward
* **recommended leverage** — සාමාන්‍ය සිග්නල් සඳහා **10x – 20x** අතර පමණක්;
  **20x ට වැඩි leverage (උපරිම 30x)** ලැබෙන්නේ **ඉතාමත් ශක්තිමත් (extreme) opportunities** වලට පමණි:
  confidence ≥ 85% + engines 8න් ≥ 6ක් එකඟ වීම + R:R ≥ 2.0 + volatility (ATR%) අඩු වීම —
  මේ සියල්ල සම්පූර්ණ වූ විට පමණක් EXTREME tier එකෙන් 20x+ leverage එකක් නිර්දේශ වේ.
  එසේ නොවන සෑම අවස්ථාවකම leverage එක 20x න් ඉහළ යන්නේ නැත.
  (මෙම සීමා `config.json → trading.leverage` වලින් ඔබට වෙනස් කළ හැක.)
* estimated liquidation distance — නිර්දේශිත leverage එකට ආසන්න liquidation දුර
* **reason** — මෙම signal එක ජනරේට් වූ **strategy එක + technique එක + logic එක** සවිස්තරව
* signal එක ලියූ AI provider/model එක (AI නැති වුවහොත් `local free engine`)

---

## 4️⃣ AI Providers සහ නොමිලේ ක්‍රම (Keys දැනටමත් ඇත)

Chain එක මෙසේයි — එකක් වැරදුණොත් ඊළඟ එකට automa­tic මාරු වේ:

1. **Groq (models 4)** — `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `openai/gpt-oss-20b`, `groq/compound-mini`
   (ඔබේ key එක මෙහි වැඩ කරන බව පරීක්ෂා කර ඇත ✔)
2. **OpenRouter (free models 3 + backups 4)** — `deepseek/deepseek-v4-flash-0731:free`,
   `nvidia/nemotron-3-super-120b-a12b:free`, `liquid/lfm-2.5-2.6b:free`
   (free tier එකේ දිනකට ~50 requests; rate-limit වුවහොත් backup models වලට මාරු වේ)
3. **Ollama (local models 2)** — `llama3.1:8b`, `qwen2.5:7b-instruct`
   → **සම්පූර්ණයෙන්ම නොමිලේ, unlimited** (ඔබේ PC එකේම run වේ):
   ```bash
   # https://ollama.com වලින් install කර, පසුව:
   ollama pull llama3.1:8b
   ollama pull qwen2.5:7b-instruct
   ```
   (Ollama ON නම් app එක automa­tic එයට සම්බන්ධ වේ — localhost:11434)
4. **Custom endpoint** — Google AI Studio වලින් **නොමිලේ** key එකක් ගෙන
   (`https://generativelanguage.googleapis.com/v1beta/openai` + model `gemini-2.0-flash`)
   හෝ LM Studio වැනි ඕනෑම OpenAI-compatible server එකක්. GUI → AI tab → custom config edit කරන්න.
5. **🟢 Built-in Local Engine** — internet/AI/tokens **කිසිවක් නැතත්** signals ලබා දෙන
   නොමිලේ rule-based engine එක. **මෙය නිසා app එක කිසිදා නතර නොවේ.**

### Tokens ඉවර වූ විට / errors ආ විට කුමක් සිදුවේද?
* key එක rate-limit (429) වුවහොත් → ඊළඟ model/provider එකට මාරු වේ
* model එක අසාර්ථක වුවහොත් → එයට කෙටි "cooldown" එකක් දී අනෙක් models වලින් වැඩ කරයි
* සියල්ල වැරදුණොත් → **local free engine** එකෙන් signal එක සම්පූර්ණ වේ
* එනම්: **signals කිසි විටෙක නතර නොවේ, සහ නොමිලේම දිගටම වැඩ කරයි** ✅

### Keys වෙනස් කිරීම
GUI → **🤖 AI Providers** tab → "Edit keys / models" → provider එක තෝරා JSON එක edit කර Save.
(හෝ `config.json` ගොනුව අතින් edit කරන්න.)

> 🔐 **ආරක්ෂාව:** ඔබ chat එකෙන් යවූ keys මෙහි ඇතුළත් කර ඇත. එම keys public වූ බැවින්
> Groq/OpenRouter dashboard වලින් **අලුත් keys සාදා මාරු කිරීම** ඉතා නුවණට හුරුය.
> `config.json` කිසිවිටෙක GitHub වැනි තැනකට upload නොකරන්න.

---

## 4️⃣⃣ Accuracy Engine v2 — සිග්නල් නිරවද්‍යතාවය ඉහළට

AlphaWave හි signal quality එක නිරන්තරයෙන් ඉගෙන ගනිමින් වැඩිදියුණු වේ:

1. **Walk-forward adaptive weights** — ඔබ signal ගන්න coin එකේ + timeframe එකේ
   මෑත ඉතිහාසය මත engines 8ම නැවත replay කර, **ඇත්තටම හරි ගිය engines වලට වැඩි
   vote බරක්** ද, වැරදුණු engines වලට අඩු බරක් ද ලබා දේ (15 min cache).
2. **Realized-outcome learning** — journal එකේ සෑම signal එකක්ම follow-up වේ
   (TP එකටද SL එකටද මුලින්ම touch වූයේ?) → engine එකක සැබෑ win/loss record එක
   `data/strategy_stats.json` හි සටහන් වී weights වලට blend වේ. එනම් bot එක
   **තමන්ගේම live ප්‍රතිඵල වලින් ඉගෙන ගනී**. `/accuracy` command එකෙන් හෝ GUI
   "Load learned weights" බොත්තමෙන් මෙය බලන්න.
3. **Higher-timeframe gate** — 15m signal එකක් නම් 1h bias එක සමඟ එකඟ විය යුතුය;
   HTF එකට විරුද්ධ (counter-trend) signal එකකට raw confidence ≥70% ක් නැත්නම් එය
   **NO TRADE** බවට පත් වේ; එකඟ නම් confidence bonus එකක් ලැබේ.
4. **Market quality gates** — මළ වෙළඳපොළ (ATR% < 0.04), අධික අස්ථිර වෙළඳපොළ
   (ATR% > 4), liquidity අඩු coins (< $1.5M/24h), spread > 0.10% → signal එකක්ම
   නොදෙයි; extreme funding / පැරණි triggers → confidence අඩු වේ.

මේ සියල්ල GUI signal card එකේ හා Telegram signal එකේ සවිස්තරව පෙනේ
(HTF badge, weights, gate notes).

---

## 5️⃣ Telegram Bot එක සම්බන්ධ කිරීම

Bot එකෙන් **app එකේ සියල්ලම** කළ හැක: signals, random funnel, analysis, charts (PNG),
news, tools 30, AI control, watchlist alerts.

### පියවර 1 — Bot token එකක් ගන්න
1. Telegram එකේ **@BotFather** වෙත message කරන්න
2. `/newbot` යවන්න → bot නමක් දෙන්න → bot username එකක් දෙන්න
3. BotFather දෙන **token** එක copy කරන්න (උදා: `7123456789:AAF...`)

### පියවර 2 — Token එක app එකට දෙන්න
GUI → **✈️ Telegram Bot** tab → token එක paste කර **Save token** → **▶ Start bot**.
(හෝ `config.json` → `telegram.bot_token`.)

### පියවර 3 — Bot එක භාවිතා කරන්න
Telegram එකේ ඔබේ bot එක open කර `/start` යවන්න. Command menu එක automa­tic install වේ.

### 🌟 නෑම user කෙනෙකුට තමන්ගේම interface එකක්!
* **Multi-User Access (IDs 100ක් දක්වා):** GUI → Bot tab → **👥 Access Control** panel එකෙන් —
  * Mode: `open` (ඕනෑම කෙනෙකුට) හෝ `whitelist` (list එකේ IDs වලට පමණක් + admins)
  * ID එකක් + note එකක් දාලා **+ Add user**, හෝ IDs ගොඩක් paste කර **⬆ Import IDs**
    (commas/spaces/new-lines ඕනෑම දෙයකින් වෙන් කර) — counter එක `x/100` ලෙස පෙනේ
  * `Max users` එක ඔබට වෙනස් කළ හැක (100 → ඕනෑම අගයක්)
  * **Admins** සකසන්න — ඔවුන්ට Telegram එකෙන්ම `/allow <id>`, `/revoke <id>`,
    `/users`, `/accessmode` commands වලින් access පාලනය කළ හැක
  * Whitelist එකේ නැති කෙනෙකුට bot එක ⛔ පෙන්වා, ඔවුන්ට **/request** යැවිය හැක —
    admins ලාට Telegram එකේම **✅ Approve** button එකක් ලැබේ
* ඕනෑම Telegram account එකකින් `/start` කළ ගමන් **එම user ගේ personal dashboard
  message එකක්** buttons සහිතව විවෘත වේ (Signal / Random / Chart / Analyze / News /
  Tools / AI / Status).
* **Coin එකක් type කරන්න** (උදා: `SOL`, `eth`, `DOGEUSDT`) → එය එම user ගේ
  **active coin** එක වේ — ඉන්පසු සියලුම buttons/tools එම coin එකටම වැඩ කරයි.
  (`/coin SOL` command එකෙන්ද හැක.)
* **සියලුම commands වලට coin නම ලියන්න පුළුවන්**: `/signal SOL 1h`,
  `/chart DOGE 15m`, `/analyze XRP 4h`, `/trend LINK`, `/sr ADA` …
  BTC විතරක් නෙවෙයි — ඕනෑම futures coin එකක්.
* User ලා අතර ව්යාකූලත්වයක් නැත: හැම කෙනෙකුගේම session එක වෙනම save වේ
  (`data/user_sessions.json`), watchlist එකද chat එකට වෙනම.

ප්‍රධාන commands:
```
/coin SOL            → ඔබේ personal active coin එක සකසන්න (හෝ නම කෙලින්ම type කරන්න)
/request             → whitelist mode එකේදී admins ලාගෙන් access ඉල්ලන්න
/allow 123456789     → (admin) user කෙනෙකුට access දෙන්න
/revoke 123456789    → (admin) user කෙනෙකුගේ access අහිමි කරන්න
/users               → (admin) whitelist එක බලන්න (x/100)
/accessmode          → (admin) open | whitelist මාරු කරන්න
/accuracy            → ඉගෙන ගත් engine weights + live win records
/signal BTC 15m      → AI signal එකක්
/random 15m          → 1000→100→10→1 funnel + signal
/analyze ETH 1h      → engines 8ේ සම්පූර්ණ විශ්ලේෂණය
/chart SOL 15m       → indicators + ▲▼ marks සහිත chart PNG එකක්
/news BTC            → fundamentals + sentiment
/menu                → tools 30ම buttons ලෙස
/watch add BTC       → watchlist (strong confluence alerts)
/price BTC  /funding BTC  /oi BTC  /ls BTC  /trend BTC  /sr BTC  /fib BTC
/flow BTC  /liq BTC  /breadth  /movers  /spikes BTC  /breakout BTC
/divergence BTC  /macd BTC  /supertrend BTC  /ribbon BTC  /ichimoku BTC
/vwap BTC  /size 60000 58500  /rr 60000 58500 64500  /liqprice 60000 10 long
/fundcost BTC 1000 long  /corr SOL  /volrank  /dominance  /journal 10
/backtest BTC 1h  /aimode assist|full|off  /aistatus  /aitest groq  /status
```

> 🔒 Bot එක ඕනෑම කෙනෙකුට භාවිතා කිරීම නවත්තන්න: GUI Bot tab එකේ
> "Allowed Telegram user IDs" වලට ඔබේ ID එක දමන්න (ඔබේ ID දැනගන්න @userinfobot).

> 💡 GUI එක නැතුව bot එක පමණක් run කිරීමට: `python run_bot.py`
> 💡 App එක start වන විටම bot එකත් start වීමට: config → `telegram.auto_start: true`

---

## 6️⃣ Trading Methods 19 (ඔබ ඉල්ලූ 8 + අලුත් 10 + Advanced ML engine 1)

Signal engine එකේ ඇතුළත් strategies 19:

| # | නම | ක්‍රමය |
|---|---|---|
| 1 | **Order Flow** | taker delta, CVD slope, absorption, volume imbalance |
| 2 | **Niyowew (Neural Wave)** | autocorrelation මගින් dominant wave cycle සොයා wave phase + momentum ensemble |
| 3 | **MNSR** | multi-level Support/Resistance clusters, bounce/rejection/breakout |
| 4 | **SMC** | market structure (HH/HL), BOS/CHoCH, order blocks, FVG, liquidity sweeps |
| 5 | **ICT (2022)** | liquidity raid → MSS + displacement → FVG entry → OTE (62–79%) → opposite liquidity |
| 6 | **Eliyat Vew (Elliott)** | zigzag wave counting (impulse/correction), wave-3 continuation, wave-5 exhaustion |
| 7 | **SK (Sniper)** | liquidity sweep + reclaim, RSI/BB extremes වල precise entries |
| 8 | **Y-KOF** | trend+ADX+RSI+MACD+CVD+BB weighted confluence score |
| 9 | **Ichimoku Cloud** | cloud position, TK cross, Senkou bias, Chikou confirmation |
| 10 | **Keltner / TTM Squeeze** | Bollinger inside Keltner = squeeze; fire direction = breakout |
| 11 | **Candlestick Patterns** | engulfing, hammer, shooting star, morning/evening star, three soldiers/crows, doji |
| 12 | **Wyckoff Structure** | accumulation/distribution ranges, SPRING / UPTHRUST, effort-vs-result volume |
| 13 | **Floor Pivot Points** | daily P/R1-R3/S1-S3 reactions සහ intraday bias |
| 14 | **ADX/DI Trend Power** | +DI/-DI crosses with ADX strength gate |
| 15 | **Stochastic Extremes** | %K/%D crosses out of overbought/oversold extremes |
| 16 | **OBV Volume Divergence** | OBV vs price divergence (smart money accumulation/distribution) |
| 17 | **Golden Pocket Fib** | 0.618–0.79 golden pocket reversal zones |
| 18 | **Funding Contrarian** | extreme funding = crowded side එකට විරුද්ධව squeeze bias |
| 19 | **NeuroQuant ML (advanced free engine)** | coin එකේම candles මත train වන on-device logistic regression ML — out-of-sample accuracy 52% ට අඩු නම් trade එකක්ම නොකරයි; cloud/tokens නැත |

සෑම signal එකකම **reason** කොටසේ මෙම engines වලින් කුමක්, කුමන technique එකෙන්, කුමන logic එකෙන්
signal එක සෑදුණේද යන්න සම්පූර්ණයෙන් ලියැවේ.

### 📈 Live chart styles 7ක් + World-class indicator pack
Chart tab එකේ style menu එකෙන්: **Candles · Hollow Candles · Bars (OHLC) · Line · Area ·
Baseline · Heikin-Ashi**. ඊට අමතරව **LIVE badge එකක්** සහිතව තත්පර 4කට වරක් අවසන්
candle එක සැබෑ වෙළඳපොළට අනුව **උඩට/පහලට ගමන් කරයි** — මිල flash වී ▲/▼ පෙන්වයි.

**Overlays:** EMA 9/20/50/100/200 · Hull MA · Bollinger · Keltner · VWAP · SuperTrend ·
Parabolic SAR · Ichimoku (Tenkan/Kijun/Senkou A/B) · **Daily Pivot Points (P/R1/R2/S1/S2)** ·
**Fibonacci levels** (price lines ලෙස).
**Sub-panes:** RSI · MACD · Stochastic · **Stoch RSI · CCI · Williams %R · MFI · ADX+DI ·
OBV · ROC · ATR** · CVD.

> 🔧 Chart library එක දැන් app එක සමඟම **locally bundle** වී ඇත (CDN/block එකක් නිසා
> chart එක load නොවීමේ දෝෂය නිවැරද කර ඇත). Style එකක් error වුවහොත් automa­tic
> Candles වෙත fallback වේ.

---

## 7️⃣ ගැටලු නිරාකරණය (Troubleshooting)

| ගැටලුව | විසඳුම |
|---|---|
| `pip` හමු නොවේ | Python install එකේ PATH check කරන්න; `python -m pip install -r requirements.txt` |
| Port 8787 busy | `python main.py --port 9000` |
| Binance data නොඑයි | firewall/VPN check; (සමහර රටවල/ISP වල fapi.binance.com block වේ — VPN එකක් උත්සාහ කරන්න) |
| Groq 403/1010 error | app එක browser-UA එකක් යවයි; ඔබේ IP block නම් ටික වේලයකින් නැවත උත්සාහ කරන්න හෝ VPN |
| OpenRouter 429 | free tier rate limit — backup models වලට මාරු වේ; නැත්නම් AI mode = `off` (local engine) |
| Ollama සම්බන්ධ නොවේ | `ollama serve` run වෙනවාදැයි බලන්න; model එක pull කර ඇත්ද (`ollama list`) |
| GUI එක update එකකට පසු විකාර ලෙස හැසිරේ / buttons වැඩ නොකරයි | Browser එකේ පැරණි cache එකක් තිබිය හැක — **Ctrl + F5** (hard refresh) කරන්න. Assets වලට version tags (`?v=3`) දමා ඇති නිසා අලුත් files automa­tic ලැබේ |
| Bot start නොවේ | GUI Bot tab එකේ **Bot logs** panel එක බලන්න — error එක එතන සඳහන් වේ: token වැරදි නම් (401) අලුත් token එකක්; "409 Conflict" නම් තව process එකක් මෙම token එකෙන් polling කරයි (run_bot.py / පැරණි instance එකක් නවත්තන්න); network නැත්නම් bot එක තනිවම reconnect උත්සාහ කරයි |
| Chart markers නොපෙනේ | "▲▼ Buy/Sell marks" checkbox ✔ ද? |
| signals.json ඉතිහාසය මකන්න | `data/signals.json` ගොනුව delete කරන්න |

---

## 8️⃣ අවසාන මතක් කිරීම්

* ✅ Binance API key/secret **අවශ්‍ය නැත** — public data පමණි
* ✅ Auto trading **නැත** — entry/SL/TP ඔබට පෙන්වයි, order දමන්නේ ඔබයි
* ✅ AI tokens නැති වුවත් **local engine** එකෙන් signals දිගටම ලැබේ
* ⚠️ Trading වල අවදානම ඔබ සතුය — මෙය financial advice නොවේ
* 🔐 `config.json` රහසිගතව තබා ගන්න

**සුබ trades! 📈🚀**
