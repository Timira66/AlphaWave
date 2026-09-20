"""
Flask GUI server + REST API.

Serves the single-page desktop-style app (gui/templates/index.html) and all
JSON endpoints used by the frontend. Runs on http://127.0.0.1:8787 by default.
"""

import io
import json
import logging
import os
import threading
import time

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory, Response

from core.config import CONFIG, BASE_DIR
from core import binance_client as bc
from core import indicators as ind
from core import strategies as st
from core import tools as tools_mod
from core import news as news_mod
from core import signal_engine
from core import ai_router
from core import charting

log = logging.getLogger("gui")

_GUI_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            static_folder=os.path.join(_GUI_DIR, "static"),
            template_folder=os.path.join(_GUI_DIR, "templates"))
app.config["JSON_SORT_KEYS"] = False

# bot controller (set by main.py) ------------------------------------------
BOT_CONTROLLER = {"thread": None, "running": False, "status": "stopped", "detail": ""}


def _json_series(a: dict, keys: list, n: int):
    """Serialize indicator series for the chart."""
    out = {}
    for k in keys:
        s = a.get(k)
        if s is None:
            continue
        try:
            vals = s.tail(n).tolist()
            out[k] = [None if v != v else round(float(v), 10) for v in vals]
        except Exception:
            pass
    return out


@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "binance": bc.ping(),
        "time": int(time.time()),
        "version": "1.0.0",
        "bot": {k: BOT_CONTROLLER[k] for k in ("running", "status", "detail")},
        "mode_note": "Public market data only. No Binance keys. No order execution.",
    })


@app.route("/api/coins")
def api_coins():
    """All futures coins with 24h stats + funding (single cached call)."""
    try:
        tickers = bc.ticker_24h()
        prem = {p["symbol"]: p for p in bc.premium_index()}
        rows = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            p = prem.get(sym, {})
            rows.append({
                "symbol": sym,
                "base": sym.replace("USDT", ""),
                "price": t.get("lastPrice"),
                "change_pct": t.get("priceChangePercent"),
                "high": t.get("highPrice"),
                "low": t.get("lowPrice"),
                "volume_usd": t.get("quoteVolume"),
                "trades": t.get("count"),
                "funding_pct": float(p.get("lastFundingRate", 0) or 0) * 100,
                "mark_price": p.get("markPrice"),
            })
        rows.sort(key=lambda r: -float(r.get("volume_usd") or 0))
        return jsonify({"count": len(rows), "coins": rows})
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/klines")
def api_klines():
    symbol = bc.normalize_symbol(request.args.get("symbol", "BTCUSDT"))
    interval = request.args.get("interval", "15m")
    limit = min(int(request.args.get("limit", 300)), 1000)
    if not symbol:
        return jsonify({"error": "invalid symbol"}), 400
    try:
        df = bc.klines(symbol, interval, limit)
        data = [[int(t), float(r["open"]), float(r["high"]), float(r["low"]),
                 float(r["close"]), float(r["volume"])] for t, r in df.iterrows()]
        return jsonify({"symbol": symbol, "interval": interval, "klines": data})
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/analysis")
def api_analysis():
    """Indicators + strategy votes + buy/sell events for the chart."""
    symbol = bc.normalize_symbol(request.args.get("symbol", "BTCUSDT"))
    interval = request.args.get("interval", "15m")
    names = request.args.get("strategies", "").split(",") if request.args.get("strategies") else None
    if not symbol:
        return jsonify({"error": "invalid symbol"}), 400
    try:
        df = bc.klines(symbol, interval, 400)
        a = ind.build_analysis(df)
        try:
            a["funding_rate"] = bc.quick_price(symbol).get("funding_rate")
        except Exception:
            a["funding_rate"] = None
        votes = st.run_strategies(df, a, names)
        combo = st.combine_votes(votes)
        n = len(df)
        overlay_keys = ["ema9", "ema20", "ema50", "ema100", "ema200", "hma9",
                        "bb_upper", "bb_mid", "bb_lower", "kc_upper", "kc_mid", "kc_lower",
                        "vwap", "supertrend", "psar",
                        "tenkan", "kijun", "senkou_a", "senkou_b",
                        "piv_P", "piv_R1", "piv_R2", "piv_S1", "piv_S2"]
        sub_keys = ["rsi", "macd", "macd_signal", "macd_hist", "stoch_k", "stoch_d",
                    "stochrsi", "cci", "willr", "mfi", "adx", "pdi", "mdi",
                    "obv", "roc", "atr", "cvd"]
        levels = {}
        try:
            levels["pivots"] = {k.replace("piv_", ""): round(float(a[k].iloc[-1]), 8)
                                for k in ("piv_P", "piv_R1", "piv_R2", "piv_S1", "piv_S2")
                                if pd.notna(a[k].iloc[-1])}
        except Exception:
            levels["pivots"] = {}
        levels["fibs"] = {k: round(float(v), 8) for k, v in a.get("fibs", {}).items()}
        return jsonify({
            "symbol": symbol, "interval": interval,
            "candles": [[int(t), float(r["open"]), float(r["high"]), float(r["low"]),
                         float(r["close"]), float(r["volume"])] for t, r in df.iterrows()],
            "overlays": _json_series(a, overlay_keys, n),
            "sub": _json_series(a, sub_keys, n),
            "levels": levels,
            "events": a["events"][-80:],
            "fvgs": [g for g in a["fvgs"] if not g["filled"]][-10:],
            "order_blocks": a["order_blocks"][-6:],
            "snapshot": {"price": a["price"], "trend": a["trend"], "rsi": a["rsi_val"],
                         "adx": a["adx_val"], "atr_pct": a["atr_pct"],
                         "bb_pos": a["bb_pos"], "st_dir": a["st_dir"],
                         "cvd_slope": a["cvd_slope_val"]},
            "votes": votes,
            "combo": combo,
        })
    except Exception as e:
        log.exception("analysis failed")
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/signal/generate", methods=["GET", "POST"])
def api_signal_generate():
    args = request.json if request.is_json else request.args
    symbol = args.get("symbol", "BTCUSDT")
    interval = args.get("interval") or None
    strat = args.get("strategies") or None
    if isinstance(strat, str):
        strat = [s for s in strat.split(",") if s]
    ai_mode = args.get("ai_mode") or None
    if not bc.normalize_symbol(symbol):
        return jsonify({"error": f"Unknown futures symbol: {symbol}"}), 400
    try:
        sig = signal_engine.generate_signal(symbol, interval, strat, ai_mode)
        return jsonify(sig)
    except Exception as e:
        log.exception("signal failed")
        return jsonify({"error": str(e)[:400]}), 500


@app.route("/api/signal/random/start", methods=["POST"])
def api_signal_random_start():
    args = request.json if request.is_json else {}
    job_id = signal_engine.start_random_job(
        interval=args.get("interval"), strategy_names=args.get("strategies"),
        ai_mode=args.get("ai_mode"))
    return jsonify({"job_id": job_id})


@app.route("/api/signal/random/status/<job_id>")
def api_signal_random_status(job_id):
    j = signal_engine.get_job(job_id)
    if not j:
        return jsonify({"error": "job not found"}), 404
    return jsonify(j)


@app.route("/api/signal/history")
def api_signal_history():
    return jsonify({"signals": signal_engine.journal_list(int(request.args.get("limit", 50)))})


@app.route("/api/news")
def api_news():
    coin = request.args.get("coin") or None
    try:
        data = news_mod.news_for_coin(coin, limit=int(request.args.get("limit", 30)))
        data["fear_greed"] = news_mod.fear_greed()
        data["announcements"] = news_mod.binance_announcements(10)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/fear")
def api_fear():
    return jsonify(news_mod.fear_greed())


@app.route("/api/tools")
def api_tools_list():
    return jsonify({"tools": tools_mod.tool_list()})


@app.route("/api/tools/run")
def api_tools_run():
    name = request.args.get("name", "")
    symbol = request.args.get("symbol") or None
    params = {k: v for k, v in request.args.items() if k not in ("name", "symbol")}
    return jsonify(tools_mod.run_tool(name, symbol, **params))


@app.route("/api/ai/status")
def api_ai_status():
    return jsonify(ai_router.health_snapshot())


@app.route("/api/ai/test", methods=["POST"])
def api_ai_test():
    args = request.json if request.is_json else {}
    provider = args.get("provider", "groq")
    return jsonify(ai_router.quick_test(provider))


@app.route("/api/config", methods=["GET"])
def api_config_get():
    """Config for the settings panel (keys partially masked for display)."""
    cfg = json.loads(json.dumps(CONFIG.data))
    for prov in ("groq", "openrouter", "ollama", "custom"):
        p = cfg.get("ai", {}).get(prov, {})
        keys = p.get("keys", [])
        p["keys_masked"] = [(k[:10] + "..." + k[-4:]) if k and len(k) > 16 else k for k in keys]
    tg = cfg.get("telegram", {})
    if tg.get("bot_token"):
        tg["bot_token_masked"] = tg["bot_token"][:12] + "..."
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def api_config_set():
    """Merge a partial config update and save."""
    try:
        patch = request.json or {}
    except Exception:
        return jsonify({"error": "invalid json"}), 400
    from core.config import _deep_merge
    _deep_merge(CONFIG.data, patch)
    CONFIG.save()
    return jsonify({"ok": True})


@app.route("/api/bot/status")
def api_bot_status():
    return jsonify({k: BOT_CONTROLLER[k] for k in ("running", "status", "detail")} |
                   {"token_configured": bool(CONFIG.get("telegram", "bot_token"))})


@app.route("/api/access", methods=["GET"])
def api_access_get():
    tg = CONFIG.data.get("telegram", {}) or {}
    ids = tg.get("allowed_user_ids", []) or []
    meta = tg.get("user_meta", {}) or {}
    users = [{"id": i,
              "note": (meta.get(str(i)) or {}).get("note", ""),
              "added_at": (meta.get(str(i)) or {}).get("added_at")}
             for i in ids]
    return jsonify({
        "mode": tg.get("access_mode", "open"),
        "max_users": tg.get("max_users", 100),
        "admins": tg.get("admin_user_ids", []) or [],
        "count": len(ids),
        "users": users,
    })


@app.route("/api/access", methods=["POST"])
def api_access_post():
    a = request.json or {}
    act = a.get("action")
    tg = CONFIG.data.setdefault("telegram", {})
    ids = list(tg.get("allowed_user_ids", []) or [])
    meta = dict(tg.get("user_meta", {}) or {})
    maxu = int(tg.get("max_users", 100) or 100)

    def _add(uid, note=""):
        nonlocal ids, meta
        uid = int(uid)
        if uid in ids:
            return False
        if len(ids) >= maxu:
            return False
        ids.append(uid)
        meta[str(uid)] = {"note": note, "added_at": int(time.time())}
        return True

    if act == "set_mode":
        tg["access_mode"] = "whitelist" if a.get("mode") == "whitelist" else "open"
    elif act == "set_max":
        tg["max_users"] = max(1, min(int(a.get("max_users", 100)), 10000))
    elif act == "set_admins":
        raw = str(a.get("admins", "")).replace(",", " ").replace(";", " ").split()
        tg["admin_user_ids"] = [int(x) for x in raw if x.lstrip("-").isdigit()]
    elif act == "add":
        if not _add(a.get("id"), a.get("note", "")):
            return jsonify({"ok": False,
                            "error": f"Could not add (duplicate or limit {maxu} reached)"}), 400
    elif act == "add_many":
        added, skipped = 0, 0
        for uid in a.get("ids", []):
            try:
                added += 1 if _add(uid, a.get("note", "")) else 0
            except Exception:
                skipped += 1
            if len(ids) >= maxu:
                skipped += 1
                break
        if added == 0:
            return jsonify({"ok": False,
                            "error": f"Nothing added (duplicates or limit {maxu} reached)"}), 400
    elif act == "remove":
        uid = int(a.get("id"))
        ids = [i for i in ids if i != uid]
        meta.pop(str(uid), None)
    elif act == "clear":
        ids, meta = [], {}
    else:
        return jsonify({"error": "unknown action"}), 400

    tg["allowed_user_ids"] = ids
    tg["user_meta"] = meta
    CONFIG.save()
    return jsonify({"ok": True, "count": len(ids), "max_users": tg.get("max_users", 100)})


@app.route("/api/bot/logs")
def api_bot_logs():
    from bot.telegram_bot import get_bot_logs
    return jsonify({"logs": get_bot_logs()})


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    from bot.telegram_bot import start_bot_thread
    ok, msg = start_bot_thread(BOT_CONTROLLER)
    return jsonify({"ok": ok, "detail": msg})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    from bot.telegram_bot import stop_bot_thread
    ok, msg = stop_bot_thread(BOT_CONTROLLER)
    return jsonify({"ok": ok, "detail": msg})


@app.route("/api/chart.png")
def api_chart_png():
    symbol = bc.normalize_symbol(request.args.get("symbol", "BTCUSDT"))
    interval = request.args.get("interval", "15m")
    limit = min(int(request.args.get("limit", 150)), 500)
    sub = request.args.get("sub", "rsi")
    overlays = tuple(o for o in request.args.get("overlays", "ema20,ema50,vwap").split(",") if o)
    if not symbol:
        return jsonify({"error": "invalid symbol"}), 400
    try:
        png = charting.render_chart_png(symbol, interval, limit, overlays=overlays, sub=sub)
        return Response(png, mimetype="image/png",
                        headers={"Content-Disposition": f"inline; filename={symbol}_{interval}.png"})
    except Exception as e:
        log.exception("chart failed")
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/accuracy")
def api_accuracy():
    from core import accuracy
    symbol = bc.normalize_symbol(request.args.get("symbol", "BTCUSDT")) or "BTCUSDT"
    interval = request.args.get("interval", "15m")
    try:
        return jsonify(accuracy.snapshot(symbol, interval))
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@app.route("/api/strategies")
def api_strategies():
    return jsonify({"strategies": [
        {"name": k, "display": st.DISPLAY_NAMES.get(k, k)} for k in st.STRATEGIES]})


def run_server(host=None, port=None, use_reloader=False):
    host = host or CONFIG.get("gui", "host", default="127.0.0.1")
    port = int(port or CONFIG.get("gui", "port", default=8787))
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log.info("GUI server starting on http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=use_reloader, threaded=True)
