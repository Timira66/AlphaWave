"""
Technical indicator library + market-event detector.

Everything is computed with pandas/numpy on Binance futures klines.
`build_analysis(df)` returns one dict with every indicator series the GUI,
the strategies, the chart markers and the AI prompts share.
"""

import numpy as np
import pandas as pd

EPS = 1e-12


# ------------------------------------------------------------ basic helpers

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=1).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    ru = up.ewm(alpha=1 / n, adjust=False, min_periods=1).mean()
    rd = dn.ewm(alpha=1 / n, adjust=False, min_periods=1).mean()
    rs = ru / (rd + EPS)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    m = ema(close, fast) - ema(close, slow)
    sig = ema(m, signal)
    return m, sig, m - sig


def bollinger(close: pd.Series, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=1).std().fillna(0)
    return mid + k * sd, mid, mid - k * sd, (2 * k * sd) / (mid + EPS)  # bandwidth


def atr(df: pd.DataFrame, n=14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=1).mean()


def adx(df: pd.DataFrame, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(alpha=1 / n, adjust=False, min_periods=1).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / (atr_ + EPS)
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / (atr_ + EPS)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + EPS)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=1).mean(), pdi, mdi


def stochastic(df: pd.DataFrame, k=14, d=3):
    lo = df["low"].rolling(k, min_periods=1).min()
    hi = df["high"].rolling(k, min_periods=1).max()
    kv = 100 * (df["close"] - lo) / (hi - lo + EPS)
    return kv, kv.rolling(d, min_periods=1).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    return (tp * df["volume"]).cumsum() / cum_v


def supertrend(df: pd.DataFrame, n=10, mult=3.0):
    hl2 = (df["high"] + df["low"]) / 2
    a = atr(df, n)
    ub, lb = hl2 + mult * a, hl2 - mult * a
    st = pd.Series(np.nan, index=df.index)
    trend = pd.Series(1, index=df.index)
    fub, flb = ub.copy(), lb.copy()
    for i in range(1, len(df)):
        fub.iloc[i] = ub.iloc[i] if (ub.iloc[i] < fub.iloc[i - 1] or
                                     df["close"].iloc[i - 1] > fub.iloc[i - 1]) else fub.iloc[i - 1]
        flb.iloc[i] = lb.iloc[i] if (lb.iloc[i] > flb.iloc[i - 1] or
                                     df["close"].iloc[i - 1] < flb.iloc[i - 1]) else flb.iloc[i - 1]
        if trend.iloc[i - 1] == 1:
            trend.iloc[i] = -1 if df["close"].iloc[i] < flb.iloc[i] else 1
        else:
            trend.iloc[i] = 1 if df["close"].iloc[i] > fub.iloc[i] else -1
        st.iloc[i] = flb.iloc[i] if trend.iloc[i] == 1 else fub.iloc[i]
    st.iloc[0] = flb.iloc[0]
    return st, trend


def ichimoku(df: pd.DataFrame):
    h, l, c = df["high"], df["low"], df["close"]
    tenkan = (h.rolling(9, min_periods=1).max() + l.rolling(9, min_periods=1).min()) / 2
    kijun = (h.rolling(26, min_periods=1).max() + l.rolling(26, min_periods=1).min()) / 2
    senkou_a = ((tenkan + kijun) / 2)
    senkou_b = (h.rolling(52, min_periods=1).max() + l.rolling(52, min_periods=1).min()) / 2
    chikou = c
    return tenkan, kijun, senkou_a, senkou_b, chikou


def donchian(df: pd.DataFrame, n=20):
    return df["high"].rolling(n, min_periods=1).max(), df["low"].rolling(n, min_periods=1).min()


def mfi(df: pd.DataFrame, n=14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n, min_periods=1).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n, min_periods=1).sum()
    return 100 - 100 / (1 + pos / (neg + EPS))


def williams_r(df: pd.DataFrame, n=14) -> pd.Series:
    hh = df["high"].rolling(n, min_periods=1).max()
    ll = df["low"].rolling(n, min_periods=1).min()
    return -100 * (hh - df["close"]) / (hh - ll + EPS)


def roc(close: pd.Series, n=12) -> pd.Series:
    return 100 * (close - close.shift(n)) / (close.shift(n) + EPS)


# ---------------------------------------------------- extra world-class TA

def wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n, min_periods=1).apply(lambda x: np.dot(x, w[-len(x):]) / w[-len(x):].sum(), raw=True)


def hma(s: pd.Series, n=9) -> pd.Series:
    """Hull Moving Average - fast & smooth."""
    half = max(n // 2, 1)
    sq = max(int(round(n ** 0.5)), 1)
    return wma(2 * wma(s, half) - wma(s, n), sq)


def psar(df: pd.DataFrame, af0=0.02, af_max=0.2) -> pd.Series:
    """Parabolic SAR (Wilder)."""
    h, l = df["high"].values, df["low"].values
    n = len(df)
    out = np.empty(n)
    if n < 3:
        return pd.Series(h, index=df.index)
    trend, af, ep = 1, af0, h[0]
    out[0] = l[0]
    for i in range(1, n):
        p = out[i - 1] + af * (ep - out[i - 1])
        if trend == 1:
            p = min(p, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if h[i] > ep:
                ep, af = h[i], min(af + af0, af_max)
            if l[i] < p:
                trend, p, ep, af = -1, ep, l[i], af0
        else:
            p = max(p, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if l[i] < ep:
                ep, af = l[i], min(af + af0, af_max)
            if h[i] > p:
                trend, p, ep, af = 1, ep, h[i], af0
        out[i] = p
    return pd.Series(out, index=df.index)


def keltner(df: pd.DataFrame, n=20, mult=2.0):
    mid = ema(df["close"], n)
    band = atr(df, n) * mult
    return mid + band, mid, mid - band


def stochrsi(close: pd.Series, n=14, k=3) -> pd.Series:
    r = rsi(close, n)
    lo = r.rolling(n, min_periods=1).min()
    hi = r.rolling(n, min_periods=1).max()
    return (100 * (r - lo) / (hi - lo + EPS)).rolling(k, min_periods=1).mean()


def cci(df: pd.DataFrame, n=20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = sma(tp, n)
    md = tp.rolling(n, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - ma) / (0.015 * md + EPS)


def daily_pivots(df: pd.DataFrame) -> pd.DataFrame:
    """Classic floor pivots from the PREVIOUS daily bar, stepped onto candles."""
    try:
        idx = pd.to_datetime(df.index, unit="ms")
        tmp = pd.DataFrame({"high": df["high"].values, "low": df["low"].values,
                            "close": df["close"].values}, index=idx)
        d = tmp.resample("1D").agg({"high": "max", "low": "min", "close": "last"})
        ph, pl, pc = d["high"].shift(1), d["low"].shift(1), d["close"].shift(1)
        P = (ph + pl + pc) / 3
        out = pd.DataFrame({
            "P": P, "R1": 2 * P - pl, "S1": 2 * P - ph,
            "R2": P + (ph - pl), "S2": P - (ph - pl)})
        # version-safe epoch-ms for day starts (pandas 2.x and 3.x)
        day_ms = d.index.astype("datetime64[ms]").astype("int64").to_numpy()
        pos = np.searchsorted(day_ms, df.index.to_numpy(), side="right") - 1
        arr = np.where(pos[:, None] >= 0,
                       out.to_numpy()[np.clip(pos, 0, None)], np.nan)
        return pd.DataFrame(arr, index=df.index, columns=out.columns)
    except Exception:
        return pd.DataFrame(index=df.index)


# ------------------------------------------------- order-flow style metrics

def taker_delta(df: pd.DataFrame) -> pd.Series:
    """Per-candle taker buy/sell imbalance from kline taker-buy volume."""
    return df["taker_buy_base"] - (df["volume"] - df["taker_buy_base"])


def cvd(df: pd.DataFrame) -> pd.Series:
    """Cumulative volume delta."""
    return taker_delta(df).cumsum()


def cvd_slope(cvd_series: pd.Series, n=10) -> pd.Series:
    x = np.arange(n)
    def _slope(win):
        if len(win) < 2:
            return 0.0
        w = win[-n:]
        xx = np.arange(len(w))
        return float(np.polyfit(xx, w.values, 1)[0])
    return cvd_series.rolling(n, min_periods=2).apply(_slope, raw=False)


# ------------------------------------------------------- swings and zigzag

def swing_points(df: pd.DataFrame, left=3, right=3):
    """Fractal swing highs/lows. Returns lists of (index_pos, price)."""
    highs, lows = [], []
    h = df["high"].values
    l = df["low"].values
    n = len(df)
    for i in range(left, n - right):
        if h[i] == max(h[i - left:i + right + 1]):
            highs.append((i, float(h[i])))
        if l[i] == min(l[i - left:i + right + 1]):
            lows.append((i, float(l[i])))
    return highs, lows


def zigzag(df: pd.DataFrame, pct=3.0):
    """Zigzag pivot list [(pos, price, 'H'|'L'), ...] filtered by pct move."""
    piv = []
    n = len(df)
    if n < 5:
        return piv
    last_pivot_price = float(df["close"].iloc[0])
    last_pivot_pos = 0
    direction = 0  # 1 up, -1 down, 0 unknown
    ext_price = last_pivot_price
    ext_pos = 0
    for i in range(1, n):
        price = float(df["close"].iloc[i])
        if direction >= 0:
            if price > ext_price:
                ext_price, ext_pos = price, i
            if ext_price > EPS and (ext_price - price) / ext_price * 100 >= pct:
                piv.append((ext_pos, ext_price, "H"))
                direction = -1
                ext_price, ext_pos = price, i
        if direction <= 0:
            if price < ext_price:
                ext_price, ext_pos = price, i
            if ext_price > EPS and (price - ext_price) / ext_price * 100 >= pct:
                piv.append((ext_pos, ext_price, "L"))
                direction = 1
                ext_price, ext_pos = price, i
        if direction == 0 and abs(price - last_pivot_price) / (last_pivot_price + EPS) * 100 >= pct:
            direction = 1 if price > last_pivot_price else -1
    return piv


def fib_levels(low: float, high: float) -> dict:
    diff = high - low
    return {
        "0.0": high, "0.236": high - 0.236 * diff, "0.382": high - 0.382 * diff,
        "0.5": high - 0.5 * diff, "0.618": high - 0.618 * diff,
        "0.705": high - 0.705 * diff, "0.79": high - 0.79 * diff, "1.0": low,
        "1.272": high + 0.272 * diff, "1.618": high + 0.618 * diff,
    }


# ------------------------------------------------------- fair value gaps

def find_fvgs(df: pd.DataFrame, lookback=60) -> list:
    """3-candle imbalance gaps: [{type:'bull'|'bear', top, bottom, pos}]"""
    gaps = []
    n = len(df)
    start = max(2, n - lookback)
    h = df["high"].values
    l = df["low"].values
    for i in range(start, n):
        if l[i] > h[i - 2]:          # bullish FVG (gap up)
            gaps.append({"type": "bull", "top": float(l[i]), "bottom": float(h[i - 2]),
                         "pos": i, "time": int(df.index[i]), "filled": False})
        if h[i] < l[i - 2]:          # bearish FVG (gap down)
            gaps.append({"type": "bear", "top": float(l[i - 2]), "bottom": float(h[i]),
                         "pos": i, "time": int(df.index[i]), "filled": False})
    # mark filled gaps
    for g in gaps:
        after = df.iloc[g["pos"] + 1:]
        if g["type"] == "bull" and len(after) and after["low"].min() <= g["bottom"]:
            g["filled"] = True
        if g["type"] == "bear" and len(after) and after["high"].max() >= g["top"]:
            g["filled"] = True
    return gaps


def find_order_blocks(df: pd.DataFrame, lookback=80) -> list:
    """Last opposing candle before a strong displacement move."""
    obs = []
    n = len(df)
    start = max(3, n - lookback)
    a = atr(df, 14).values
    c = df["close"].values
    for i in range(start, n - 1):
        move = c[i + 1] - c[i]
        if a[i] > EPS and abs(move) > 1.8 * a[i]:
            if move > 0 and c[i] < df["open"].values[i]:
                obs.append({"type": "bull", "pos": i, "time": int(df.index[i]),
                            "top": float(df["high"].values[i]),
                            "bottom": float(df["low"].values[i])})
            elif move < 0 and c[i] > df["open"].values[i]:
                obs.append({"type": "bear", "pos": i, "time": int(df.index[i]),
                            "top": float(df["high"].values[i]),
                            "bottom": float(df["low"].values[i])})
    return obs[-6:]


# ------------------------------------------------------ master analysis

def build_analysis(df: pd.DataFrame) -> dict:
    """Compute all indicators on a kline DataFrame -> single analysis dict."""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    out = {}

    out["ema9"] = ema(close, 9)
    out["ema20"] = ema(close, 20)
    out["ema21"] = ema(close, 21)
    out["ema50"] = ema(close, 50)
    out["ema100"] = ema(close, 100)
    out["ema200"] = ema(close, 200)
    out["sma50"] = sma(close, 50)
    out["sma200"] = sma(close, 200)
    out["rsi"] = rsi(close, 14)
    out["rsi7"] = rsi(close, 7)
    m, s, h = macd(close)
    out["macd"], out["macd_signal"], out["macd_hist"] = m, s, h
    ub, mb, lb, bw = bollinger(close)
    out["bb_upper"], out["bb_mid"], out["bb_lower"], out["bb_width"] = ub, mb, lb, bw
    out["atr"] = atr(df, 14)
    adx_, pdi, mdi = adx(df)
    out["adx"], out["pdi"], out["mdi"] = adx_, pdi, mdi
    k_, d_ = stochastic(df)
    out["stoch_k"], out["stoch_d"] = k_, d_
    out["obv"] = obv(df)
    out["vwap"] = vwap(df)
    st, stt = supertrend(df)
    out["supertrend"], out["supertrend_dir"] = st, stt
    tk, kj, sa, sb, ck = ichimoku(df)
    out["tenkan"], out["kijun"], out["senkou_a"], out["senkou_b"], out["chikou"] = tk, kj, sa, sb, ck
    du, dl = donchian(df, 20)
    out["donchian_upper"], out["donchian_lower"] = du, dl
    out["mfi"] = mfi(df)
    out["willr"] = williams_r(df)
    out["roc"] = roc(close)
    out["delta"] = taker_delta(df)
    out["cvd"] = cvd(df)
    out["cvd_slope"] = cvd_slope(out["cvd"], 10)
    out["vol_sma20"] = sma(vol, 20)
    # extended indicator set (world-class pack)
    out["hma9"] = hma(close, 9)
    out["psar"] = psar(df)
    ku, km, kl = keltner(df)
    out["kc_upper"], out["kc_mid"], out["kc_lower"] = ku, km, kl
    out["stochrsi"] = stochrsi(close)
    out["cci"] = cci(df)
    piv = daily_pivots(df)
    for col in ("P", "R1", "S1", "R2", "S2"):
        out["piv_" + col] = piv[col] if col in piv.columns else pd.Series(np.nan, index=df.index)

    # scalars for prompts / logic ---------------------------------------
    last = -1
    price = float(close.iloc[last])
    out["price"] = price
    out["trend"] = (
        "UP" if price > out["ema50"].iloc[last] > out["ema200"].iloc[last] else
        "DOWN" if price < out["ema50"].iloc[last] < out["ema200"].iloc[last] else "RANGE"
    )
    out["adx_val"] = float(out["adx"].iloc[last])
    out["rsi_val"] = float(out["rsi"].iloc[last])
    out["atr_val"] = float(out["atr"].iloc[last])
    out["atr_pct"] = out["atr_val"] / (price + EPS) * 100
    out["cvd_slope_val"] = float(out["cvd_slope"].iloc[last])
    out["macd_hist_val"] = float(out["macd_hist"].iloc[last])
    out["st_dir"] = int(out["supertrend_dir"].iloc[last])
    out["bb_pos"] = float((price - lb.iloc[last]) / (ub.iloc[last] - lb.iloc[last] + EPS))
    out["fvgs"] = find_fvgs(df)
    out["order_blocks"] = find_order_blocks(df)
    hi_, lo_ = swing_points(df, 3, 3)
    out["swing_highs"], out["swing_lows"] = hi_, lo_
    out["zigzag"] = zigzag(df, pct=max(0.55, out["atr_pct"] * 1.6))
    rng = df.tail(120)
    out["range_high"] = float(rng["high"].max())
    out["range_low"] = float(rng["low"].min())
    out["fibs"] = fib_levels(out["range_low"], out["range_high"])
    out["events"] = detect_events(df, out)
    return out


# ------------------------------------------------------- event detector
# Buy/sell "highlight" events used for chart markers and strategy votes.

def detect_events(df: pd.DataFrame, a: dict = None) -> list:
    a = a or build_analysis_core_only(df)
    events = []
    n = len(df)
    if n < 30:
        return events
    close = df["close"]
    times = df.index.astype("int64").tolist()

    def add(pos, side, kind, label, price):
        if 0 <= pos < n:
            events.append({"pos": int(pos), "time": int(times[pos]), "side": side,
                           "type": kind, "label": label, "price": float(price)})

    start = max(5, n - 120)
    for i in range(start, n):
        # EMA 9/21 crosses
        e9, e21 = a["ema9"].iloc[i], a["ema21"].iloc[i]
        p9, p21 = a["ema9"].iloc[i - 1], a["ema21"].iloc[i - 1]
        if p9 <= p21 and e9 > e21:
            add(i, "buy", "ema_cross", "EMA9x21 ↑", close.iloc[i])
        elif p9 >= p21 and e9 < e21:
            add(i, "sell", "ema_cross", "EMA9x21 ↓", close.iloc[i])
        # MACD cross
        mh, pmh = a["macd_hist"].iloc[i], a["macd_hist"].iloc[i - 1]
        if pmh <= 0 < mh:
            add(i, "buy", "macd_cross", "MACD ↑", close.iloc[i])
        elif pmh >= 0 > mh:
            add(i, "sell", "macd_cross", "MACD ↓", close.iloc[i])
        # SuperTrend flip
        sd, psd = a["supertrend_dir"].iloc[i], a["supertrend_dir"].iloc[i - 1]
        if psd == -1 and sd == 1:
            add(i, "buy", "supertrend", "ST flip ↑", close.iloc[i])
        elif psd == 1 and sd == -1:
            add(i, "sell", "supertrend", "ST flip ↓", close.iloc[i])
        # RSI extremes turning back
        r_, pr_ = a["rsi"].iloc[i], a["rsi"].iloc[i - 1]
        if pr_ < 30 <= r_:
            add(i, "buy", "rsi", "RSI exit OS", close.iloc[i])
        elif pr_ > 70 >= r_:
            add(i, "sell", "rsi", "RSI exit OB", close.iloc[i])
        # Bollinger band rejection
        if df["low"].iloc[i] <= a["bb_lower"].iloc[i] and close.iloc[i] > a["bb_lower"].iloc[i]:
            add(i, "buy", "bb", "BB lower reject", close.iloc[i])
        if df["high"].iloc[i] >= a["bb_upper"].iloc[i] and close.iloc[i] < a["bb_upper"].iloc[i]:
            add(i, "sell", "bb", "BB upper reject", close.iloc[i])
        # Donchian breakout
        if i > 20 and close.iloc[i] > a["donchian_upper"].iloc[i - 1]:
            add(i, "buy", "breakout", "20-high break", close.iloc[i])
        if i > 20 and close.iloc[i] < a["donchian_lower"].iloc[i - 1]:
            add(i, "sell", "breakout", "20-low break", close.iloc[i])
        # Volume spike
        vs = a["vol_sma20"].iloc[i]
        if vs > 0 and df["volume"].iloc[i] > 2.2 * vs:
            side = "buy" if a["delta"].iloc[i] > 0 else "sell"
            add(i, side, "volume_spike", "Vol spike", close.iloc[i])
        # Liquidity sweep (wick takes prior swing then closes back inside)
        if i > 10:
            prior_hi = df["high"].iloc[i - 10:i].max()
            prior_lo = df["low"].iloc[i - 10:i].min()
            if df["high"].iloc[i] > prior_hi and close.iloc[i] < prior_hi:
                add(i, "sell", "sweep", "Buy-side sweep", close.iloc[i])
            if df["low"].iloc[i] < prior_lo and close.iloc[i] > prior_lo:
                add(i, "buy", "sweep", "Sell-side sweep", close.iloc[i])

    # Structure events: BOS / CHoCH from swings
    sh, sl = a.get("swing_highs", []), a.get("swing_lows", [])
    for j in range(1, len(sh)):
        (p0, v0), (p1, v1) = sh[j - 1], sh[j]
        if v1 > v0 and p1 >= start:
            add(p1, "buy", "bos", "BOS ↑ HH", v1)
    for j in range(1, len(sl)):
        (p0, v0), (p1, v1) = sl[j - 1], sl[j]
        if v1 < v0 and p1 >= start:
            add(p1, "sell", "bos", "BOS ↓ LL", v1)

    events.sort(key=lambda e: e["pos"])
    return events


def build_analysis_core_only(df: pd.DataFrame) -> dict:
    """Light version used internally to avoid recursion (no events)."""
    a = {}
    close = df["close"]
    a["ema9"] = ema(close, 9)
    a["ema21"] = ema(close, 21)
    a["ema50"] = ema(close, 50)
    a["ema200"] = ema(close, 200)
    a["rsi"] = rsi(close, 14)
    m, s, h = macd(close)
    a["macd"], a["macd_signal"], a["macd_hist"] = m, s, h
    ub, mb, lb, bw = bollinger(close)
    a["bb_upper"], a["bb_mid"], a["bb_lower"], a["bb_width"] = ub, mb, lb, bw
    a["atr"] = atr(df)
    a["vol_sma20"] = sma(df["volume"], 20)
    a["delta"] = taker_delta(df)
    a["cvd"] = cvd(df)
    st, stt = supertrend(df)
    a["supertrend"], a["supertrend_dir"] = st, stt
    du, dl = donchian(df, 20)
    a["donchian_upper"], a["donchian_lower"] = du, dl
    a["swing_highs"], a["swing_lows"] = swing_points(df, 3, 3)
    return a


def last_val(series_or_df, key=None, default=0.0) -> float:
    try:
        s = series_or_df if key is None else series_or_df[key]
        v = s.iloc[-1]
        return float(v) if pd.notna(v) else default
    except Exception:
        return default
