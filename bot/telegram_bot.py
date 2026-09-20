"""
Telegram bot — full remote control of AlphaWave.

Everything the GUI can do is available here:
  signals (chosen coin + random funnel), analysis, charts, news, all 30
  tools, AI provider control/status, watchlist with confluence alerts.

Runs in its own thread with its own asyncio loop so the Flask GUI can
start/stop it at runtime (Bot tab) or main.py can auto-start it.
"""

import asyncio
import html
import io
import json
import logging
import os
import threading
import time
from datetime import datetime

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

from core.config import CONFIG, DATA_DIR
from core import binance_client as bc
from core import signal_engine
from core import tools as tools_mod
from core import news as news_mod
from core import ai_router
from core import charting
from core import strategies as st
from core import accuracy

log = logging.getLogger("bot")

WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlist.json")
SESSIONS_PATH = os.path.join(DATA_DIR, "user_sessions.json")
_sess_lock = threading.Lock()

TF_CYCLE = ["5m", "15m", "30m", "1h", "4h"]


# ------------------------------------------------------- per-user sessions
# Every Telegram user gets a private interface state: their own active coin,
# timeframe and input mode. Multiple users use the bot simultaneously and
# never interfere with each other.

def get_session(user_id: int) -> dict:
    with _sess_lock:
        try:
            with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
                all_s = json.load(f)
        except Exception:
            all_s = {}
        s = all_s.get(str(user_id))
        if not s:
            s = {"coin": "BTCUSDT", "interval": "15m", "waiting_coin": False}
        return s


def save_session(user_id: int, sess: dict):
    with _sess_lock:
        try:
            with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
                all_s = json.load(f)
        except Exception:
            all_s = {}
        all_s[str(user_id)] = sess
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SESSIONS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(all_s, f)
        os.replace(tmp, SESSIONS_PATH)

COMMANDS = [
    ("start", "Welcome & overview"),
    ("help", "Full command list"),
    ("menu", "30-feature button menu"),
    ("signal", "AI signal: /signal BTC 15m"),
    ("random", "Best-of funnel 1000-100-10-1: /random 15m"),
    ("analyze", "8-strategy analysis: /analyze ETH 1h"),
    ("chart", "Chart PNG + marks: /chart SOL 15m"),
    ("price", "Live price/funding: /price BTC"),
    ("news", "News + sentiment: /news BTC"),
    ("fear", "Fear & Greed index"),
    ("funding", "Funding detail: /funding BTC"),
    ("oi", "Open interest: /oi BTC"),
    ("ls", "Long/short ratios: /ls BTC"),
    ("trend", "Multi-TF trend: /trend BTC"),
    ("sr", "Support/resistance: /sr BTC"),
    ("fib", "Fibonacci + OTE: /fib BTC"),
    ("flow", "Order flow/CVD: /flow BTC"),
    ("liq", "Liquidity zones: /liq BTC"),
    ("breadth", "Market breadth regime"),
    ("movers", "Top gainers & losers"),
    ("spikes", "Volume spikes: /spikes BTC"),
    ("breakout", "Breakout/squeeze: /breakout BTC"),
    ("divergence", "RSI divergence: /divergence BTC"),
    ("macd", "MACD state: /macd BTC"),
    ("supertrend", "SuperTrend: /supertrend BTC"),
    ("ribbon", "EMA ribbon: /ribbon BTC"),
    ("ichimoku", "Ichimoku cloud: /ichimoku BTC"),
    ("vwap", "VWAP deviation: /vwap BTC"),
    ("size", "Position size: /size 60000 58500"),
    ("rr", "Risk/reward: /rr 60000 58500 64500"),
    ("liqprice", "Liq. price est: /liqprice 60000 10 long"),
    ("fundcost", "Funding cost: /fundcost BTC 1000 long"),
    ("corr", "Correlation vs BTC/ETH: /corr SOL"),
    ("volrank", "Volatility ranking"),
    ("dominance", "BTC/ETH futures dominance"),
    ("journal", "Signal history: /journal 10"),
    ("backtest", "Mini backtest: /backtest BTC 1h"),
    ("aimode", "Switch AI: /aimode assist|full|off"),
    ("aistatus", "AI provider health"),
    ("aitest", "Test provider: /aitest groq"),
    ("coin", "YOUR active coin: /coin SOL (or just type the name)"),
    ("request", "Request access (whitelist mode)"),
    ("allow", "Admin: allow a Telegram ID"),
    ("revoke", "Admin: revoke a Telegram ID"),
    ("users", "Admin: list allowed users (x/100)"),
    ("accessmode", "Admin: open | whitelist"),
    ("accuracy", "Learned engine weights & win records"),
    ("watch", "Watchlist: /watch add|del|list BTC"),
    ("status", "App & bot health"),
]

THREAD_STATE = {"thread": None, "stop_event": None, "loop": None}

BOT_LOGS = []
_logs_lock = threading.Lock()


def bot_log(msg):
    with _logs_lock:
        BOT_LOGS.append({"ts": int(time.time()), "msg": str(msg)[:300]})
        if len(BOT_LOGS) > 150:
            del BOT_LOGS[:len(BOT_LOGS) - 150]


def get_bot_logs(limit: int = 80) -> list:
    with _logs_lock:
        return list(BOT_LOGS)[-limit:]


# ---------------------------------------------------------------- helpers

def esc(x) -> str:
    return html.escape(str(x if x is not None else "—"))


def fnum(x):
    try:
        n = float(x)
        if abs(n) >= 1000:
            return f"{n:,.2f}"
        if abs(n) >= 1:
            return f"{n:.4f}"
        return f"{n:.6g}"
    except Exception:
        return str(x)


def allowed(update: Update) -> bool:
    """Multi-user access: 'open' = anyone, 'whitelist' = listed IDs (+admins)."""
    mode = CONFIG.get("telegram", "access_mode", default="open")
    if mode != "whitelist":
        return True
    uid = update.effective_user.id
    ids = CONFIG.get("telegram", "allowed_user_ids", default=[]) or []
    if uid in ids:
        return True
    admins = CONFIG.get("telegram", "admin_user_ids", default=[]) or []
    return uid in admins


def is_admin(update: Update) -> bool:
    admins = CONFIG.get("telegram", "admin_user_ids", default=[]) or []
    return update.effective_user.id in admins


def access_add_user(uid: int, note: str = "", via: str = "") -> tuple:
    """Add a user to the whitelist. Returns (ok, message)."""
    ids = list(CONFIG.get("telegram", "allowed_user_ids", default=[]) or [])
    maxu = int(CONFIG.get("telegram", "max_users", default=100) or 100)
    if uid in ids:
        return True, "already allowed"
    if len(ids) >= maxu:
        return False, f"user limit reached ({maxu}). Raise max_users in the GUI Bot tab or revoke someone."
    ids.append(int(uid))
    meta = dict(CONFIG.get("telegram", "user_meta", default={}) or {})
    meta[str(uid)] = {"note": note or via, "added_at": int(time.time())}
    CONFIG.set("telegram", "allowed_user_ids", ids)
    CONFIG.set("telegram", "user_meta", meta)
    bot_log(f"access: +{uid} ({note or via}) total={len(ids)}")
    return True, f"added {uid} ({len(ids)}/{maxu})"


def access_remove_user(uid: int) -> tuple:
    ids = list(CONFIG.get("telegram", "allowed_user_ids", default=[]) or [])
    if uid not in ids:
        return False, "not in whitelist"
    ids.remove(int(uid))
    meta = dict(CONFIG.get("telegram", "user_meta", default={}) or {})
    meta.pop(str(uid), None)
    CONFIG.set("telegram", "allowed_user_ids", ids)
    CONFIG.set("telegram", "user_meta", meta)
    bot_log(f"access: -{uid} total={len(ids)}")
    return True, f"revoked {uid} ({len(ids)} left)"


async def deny(update: Update):
    await update.effective_message.reply_text(
        "⛔ <b>Access denied</b> — this AlphaWave bot runs in WHITELIST mode.\n"
        f"Your Telegram ID: <code>{update.effective_user.id}</code>\n"
        "Send /request and an admin will approve you, or ask the owner to add "
        "your ID in the GUI (Bot tab → Access Control).",
        parse_mode=ParseMode.HTML)


async def send_long_msg(message, text: str):
    """Telegram 4096-char safe chunked send to a specific Message."""
    text = text or "—"
    for i in range(0, len(text), 3800):
        await message.reply_text(text[i:i + 3800],
                                 parse_mode=ParseMode.HTML,
                                 disable_web_page_preview=True)


async def send_long(update: Update, text: str):
    await send_long_msg(update.effective_message, text)


def fmt_dict(d: dict, depth=0) -> str:
    """Pretty text for tool results."""
    lines = []
    pad = "  " * depth
    for k, v in d.items():
        if k in ("tool", "display", "elapsed_sec"):
            continue
        if isinstance(v, dict):
            lines.append(f"{pad}<b>{esc(k)}</b>:")
            lines.append(fmt_dict(v, depth + 1))
        elif isinstance(v, list):
            if not v:
                lines.append(f"{pad}{esc(k)}: []")
                continue
            if isinstance(v[0], dict):
                lines.append(f"{pad}<b>{esc(k)}</b>:")
                for i, it in enumerate(v[:15]):
                    inline = " · ".join(f"{esc(kk)}={esc(fnum(vv)) if isinstance(vv, (int, float)) else esc(str(vv)[:120])}"
                                        for kk, vv in it.items() if not isinstance(vv, (dict, list)))
                    lines.append(f"{pad} [{i}] {inline}")
                if len(v) > 15:
                    lines.append(f"{pad} … +{len(v)-15} more")
            else:
                vals = ", ".join(esc(fnum(x)) if isinstance(x, (int, float)) else esc(str(x)[:60]) for x in v[:25])
                lines.append(f"{pad}{esc(k)}: {vals}")
        else:
            val = fnum(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
            lines.append(f"{pad}<b>{esc(k)}</b>: {esc(val)}")
    return "\n".join(lines)


async def run_tool_reply(update: Update, name: str, args):
    needs_sym = tools_mod.TOOL_MAP[name][2]
    symbol = args[0] if args else (
        get_session(update.effective_user.id)["coin"] if needs_sym else None)
    params = dict(p.split("=", 1) for p in args[1:] if "=" in p)
    d = await asyncio.get_running_loop().run_in_executor(
        None, lambda: tools_mod.run_tool(name, symbol, **params))
    title = d.get("display", name)
    body = fmt_dict(d)
    await send_long(update, f"🧰 <b>{esc(title)}</b>\n{'-'*30}\n{body}")


def fmt_signal(s: dict) -> str:
    side = s.get("side", "?")
    icon = "🟢" if side == "LONG" else "🔴" if side == "SHORT" else "⚪"
    tps = "\n".join(f"  • {esc(t['name'])}: <b>{fnum(t['price'])}</b> ({t['r']}R)"
                    for t in s.get("take_profit_levels", []))
    ai = s.get("ai_provider") or "local free engine"
    if s.get("ai_model"):
        ai += " · " + str(s["ai_model"])
    lev = s.get("recommended_leverage")
    lev_line = ""
    if lev:
        tier = esc(s.get("leverage_tier", ""))
        lev_line = (f"<b>Recommended leverage:</b> <code>{lev}x</code> ({tier})\n"
                    f"<b>Est. liquidation distance:</b> ~{fnum(s.get('est_liquidation_distance_pct'))}% (isolated)\n")
    return (
        f"🌊 {icon} <b>ALPHAWAVE SIGNAL — {esc(s['coin'])}</b> [{esc(s.get('timeframe',''))}]\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Side:</b> {icon} {esc(side)}\n"
        f"<b>Live price:</b> <code>{fnum(s.get('live_price'))}</code>\n"
        f"<b>Entry:</b> <code>{fnum(s.get('entry_price'))}</code>\n"
        f"<b>Stop loss:</b> <code>{fnum(s.get('stop_loss'))}</code>\n"
        f"<b>Take profit:</b> <code>{fnum(s.get('take_profit'))}</code>\n"
        + (f"<b>TP ladder:</b>\n{tps}\n" if tps else "")
        + f"<b>R:R:</b> {fnum(s.get('risk_reward'))} · <b>Confidence:</b> {fnum(s.get('confidence'))}%\n"
        + lev_line
        + f"<b>AI:</b> {esc(ai)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📜 <b>Reason (strategy · technique · logic):</b>\n{esc(s.get('reason',''))}\n"
        + (f"⚙ <b>Leverage logic:</b> {esc(s.get('leverage_reason',''))}\n" if s.get("leverage_reason") else "")
        + f"⚠️ {esc(s.get('disclaimer',''))}"
    )


# ------------------------------------------------------------- commands

# -------------------- personal per-user interface (dashboard) -------------

def dashboard_kb(sess: dict) -> InlineKeyboardMarkup:
    coin, tf = sess["coin"], sess["interval"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚡ SIGNAL {coin} · {tf}", callback_data="dash:signal"),
         InlineKeyboardButton("🎲 RANDOM FUNNEL", callback_data="dash:random")],
        [InlineKeyboardButton("📈 CHART", callback_data="dash:chart"),
         InlineKeyboardButton("🔬 ANALYZE", callback_data="dash:analyze"),
         InlineKeyboardButton("📰 NEWS", callback_data="dash:news")],
        [InlineKeyboardButton(f"🪙 COIN: {coin}", callback_data="set:coin"),
         InlineKeyboardButton(f"⏱ TF: {tf}", callback_data="set:tf")],
        [InlineKeyboardButton("🧰 30 TOOLS", callback_data="dash:tools"),
         InlineKeyboardButton("🤖 AI", callback_data="dash:ai"),
         InlineKeyboardButton("🩺 STATUS", callback_data="dash:status")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="dash:refresh"),
         InlineKeyboardButton("❓ HELP", callback_data="dash:help")],
    ])


async def dashboard_text(sess: dict, note: str = None) -> str:
    coin, tf = sess["coin"], sess["interval"]
    lines = ["🌊 <b>ALPHAWAVE — your personal trading terminal</b>"]
    if note:
        lines.append(f"✅ {esc(note)}")
    try:
        p = bc.quick_price(coin)
        lines.append(
            f"\n🪙 Active coin: <b>{esc(coin)}</b> · ⏱ {esc(tf)}\n"
            f"💲 Price <code>{fnum(p['last_price'])}</code> · 24h {fnum(p['change_24h_pct'])}%\n"
            f"📊 Vol ${fnum(p['quote_volume_24h']/1e6)}M · Funding {fnum(p['funding_rate']*100)}%")
    except Exception:
        lines.append(f"\n🪙 Active coin: <b>{esc(coin)}</b> · ⏱ {esc(tf)} (price unavailable)")
    lines.append(
        "\n💡 <b>How to use:</b>\n"
        "• Tap the buttons below — everything works for YOUR active coin\n"
        "• Or <b>type any coin name</b> (e.g. <code>SOL</code>, <code>ETHUSDT</code>) to switch\n"
        "• Or type commands with a coin: <code>/signal SOL 1h</code>, <code>/chart DOGE 15m</code>\n"
        "• Every feature accepts any coin — you are not limited to BTC")
    return "\n".join(lines)


async def send_dashboard(update: Update, note: str = None, reply: bool = True):
    sess = get_session(update.effective_user.id)
    txt = await dashboard_text(sess, note)
    if reply:
        await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML,
                                                  reply_markup=dashboard_kb(sess))
    else:
        await update.effective_message.edit_text(txt, parse_mode=ParseMode.HTML,
                                                 reply_markup=dashboard_kb(sess))


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    sess = get_session(update.effective_user.id)
    txt = await dashboard_text(sess, "Welcome! Your personal AlphaWave interface is ready.")
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML,
                                              reply_markup=dashboard_kb(sess))


async def cmd_coin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/coin SOL — set your personal active coin."""
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    sess = get_session(update.effective_user.id)
    if not args:
        sess["waiting_coin"] = True
        save_session(update.effective_user.id, sess)
        return await update.effective_message.reply_text(
            "🪙 Type the coin name now (e.g. <code>SOL</code>, <code>eth</code>, <code>DOGEUSDT</code>):",
            parse_mode=ParseMode.HTML)
    sym = bc.normalize_symbol(args[0])
    if not sym:
        return await update.effective_message.reply_text(
            f"❌ Unknown futures coin: {esc(args[0])}. Examples: BTC, ETH, SOL, DOGE…")
    sess["coin"], sess["waiting_coin"] = sym, False
    save_session(update.effective_user.id, sess)
    await send_dashboard(update, note=f"Active coin set to {sym} for YOUR interface.")


async def cmd_accuracy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/accuracy [coin] [tf] — show learned engine weights & live win records."""
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    sess = get_session(update.effective_user.id)
    sym = bc.normalize_symbol(args[0]) if args else sess["coin"]
    tf = args[1] if len(args) > 1 else sess["interval"]
    msg = await update.effective_message.reply_text("🧠 computing learned weights (walk-forward replay)…")
    d = await asyncio.get_running_loop().run_in_executor(
        None, accuracy.snapshot, sym or "BTCUSDT", tf)
    lines = [f"🧠 <b>Accuracy Engine v2 — {esc(d['symbol'])} {esc(d['interval'])}</b>",
             f"Evaluated live signals so far: {d['evaluated_signals']}", "━" * 26]
    for r in d["engines"]:
        wr = f"{r['live_winrate_pct']}%" if r["live_winrate_pct"] is not None else "n/a"
        lines.append(f"• <b>{esc(r['engine'])}</b>: weight x{r['blended_weight']} "
                     f"(walk-fwd x{r['walkforward_weight']} · live x{r['live_record_weight']}) "
                     f"· live record {r['live_wins']}W/{r['live_losses']}L ({wr})")
    lines.append("━" * 26)
    lines.append("Weights auto-update: engines that predict this coin/timeframe well get "
                 "stronger votes; failing engines get muted. Live TP/SL outcomes feed back in.")
    await send_long(update, "\n".join(lines))
    await msg.delete()


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Free typing: a coin name switches the user's personal active coin."""
    if not allowed(update):
        return await deny(update)
    txt = (update.effective_message.text or "").strip()
    if not txt:
        return
    uid = update.effective_user.id
    sess = get_session(uid)
    low = txt.lower()
    if low in ("menu", "dashboard", "home"):
        return await send_dashboard(update)
    sym = bc.normalize_symbol(txt)
    if sess.get("waiting_coin"):
        if sym:
            sess["coin"], sess["waiting_coin"] = sym, False
            save_session(uid, sess)
            return await send_dashboard(update, note=f"Active coin → {sym}")
        return await update.effective_message.reply_text(
            "❌ Not a Binance USDT-M futures coin. Try: BTC, ETH, SOL, XRP, DOGE …")
    if sym:
        sess["coin"] = sym
        save_session(uid, sess)
        return await send_dashboard(update, note=f"Active coin → {sym} (all buttons now use it)")
    await update.effective_message.reply_text(
        "🤖 Type a <b>coin name</b> to switch your active coin (e.g. <code>SOL</code>), "
        "or use /signal COIN, /chart COIN, /menu, /help.", parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    lines = "\n".join(f"/{c} — {esc(d)}" for c, d in COMMANDS)
    await send_long(update, f"📖 <b>All commands</b>\n\n{lines}")


def tool_menu_page(page: int):
    tools = tools_mod.tool_list()
    per = 10
    pages = (len(tools) + per - 1) // per
    page = max(0, min(page, pages - 1))
    rows = []
    chunk = tools[page * per:(page + 1) * per]
    for t in chunk:
        rows.append([InlineKeyboardButton(f"{t['id']:02d}. {t['display'][:34]}",
                                          callback_data=f"tool:{t['name']}")])
    quick = [
        InlineKeyboardButton("⚡ Signal (BTC 15m)", callback_data="quick:signal"),
        InlineKeyboardButton("🎲 Random funnel", callback_data="quick:random"),
    ]
    chart_news = [
        InlineKeyboardButton("📈 Chart (BTC 15m)", callback_data="quick:chart"),
        InlineKeyboardButton("📰 News", callback_data="quick:news"),
    ]
    nav = [InlineKeyboardButton(f"📄 Page {page+1}/{pages}", callback_data="noop")]
    if page > 0:
        nav.insert(0, InlineKeyboardButton("⬅️", callback_data=f"page:{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"page:{page+1}"))
    kb = [quick, chart_news] + rows + [nav]
    return InlineKeyboardMarkup(kb)


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    await update.effective_message.reply_text(
        "🧰 <b>30 Trading Tools</b> — tap to run (uses default BTCUSDT unless asked)",
        parse_mode=ParseMode.HTML, reply_markup=tool_menu_page(0))


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not allowed(update):
        return
    uid = update.effective_user.id
    data = q.data or ""

    # ---------- access approval (admins) ----------
    if data.startswith("access:approve:"):
        if not is_admin(update):
            await q.answer("Admins only", show_alert=True)
            return
        uid = int(data.split(":")[2])
        ok, msg = access_add_user(uid, note="approved via Telegram", via="approved")
        await q.answer(msg)
        try:
            await q.edit_message_text(f"{'✅' if ok else '❌'} {esc(msg)}",
                                      parse_mode=ParseMode.HTML)
        except Exception:
            pass
        if ok:
            try:
                await ctx.bot.send_message(
                    uid, "✅ <b>Your AlphaWave access is approved!</b>\nSend /start to open your personal terminal.",
                    parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return

    # ---------- pagination of the 30-tool menu ----------
    if data.startswith("page:"):
        await q.edit_message_text("🧰 <b>30 Trading Tools</b> — tap to run on YOUR active coin",
                                  parse_mode=ParseMode.HTML,
                                  reply_markup=tool_menu_page(int(data.split(":")[1])))
        return

    # ---------- run one of the 30 tools ----------
    if data.startswith("tool:"):
        name = data.split(":", 1)[1]
        needs = tools_mod.TOOL_MAP[name][2]
        symbol = get_session(uid)["coin"] if needs else None
        await q.edit_message_text(f"⏳ running <b>{esc(tools_mod.TOOL_MAP[name][0])}</b>"
                                  + (f" on {esc(symbol)}…" if symbol else "…"),
                                  parse_mode=ParseMode.HTML)
        d = await asyncio.get_running_loop().run_in_executor(
            None, tools_mod.run_tool, name, symbol)
        await send_long_msg(q.message, f"🧰 <b>{esc(d.get('display', name))}</b>\n{'-'*28}\n{fmt_dict(d)}")
        sess = get_session(uid)
        txt = await dashboard_text(sess)
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=dashboard_kb(sess))
        return

    # ---------- personal interface settings ----------
    if data.startswith("set:"):
        sess = get_session(uid)
        what = data.split(":")[1]
        if what == "coin":
            sess["waiting_coin"] = True
            save_session(uid, sess)
            await q.edit_message_text(
                "🪙 <b>Type the coin name now</b> (e.g. <code>SOL</code>, <code>eth</code>, "
                "<code>DOGEUSDT</code>) — it becomes YOUR active coin for every feature.",
                parse_mode=ParseMode.HTML)
            return
        if what == "tf":
            cur = sess["interval"]
            i = TF_CYCLE.index(cur) if cur in TF_CYCLE else 1
            sess["interval"] = TF_CYCLE[(i + 1) % len(TF_CYCLE)]
            save_session(uid, sess)
            txt = await dashboard_text(sess, f"Timeframe → {sess['interval']}")
            await q.edit_message_text(txt, parse_mode=ParseMode.HTML,
                                      reply_markup=dashboard_kb(sess))
            return

    # ---------- personal dashboard actions ----------
    if data.startswith("dash:"):
        act = data.split(":")[1]
        sess = get_session(uid)
        coin, tf = sess["coin"], sess["interval"]
        loop = asyncio.get_running_loop()

        async def restore(note=None):
            txt = await dashboard_text(sess, note)
            try:
                await q.edit_message_text(txt, parse_mode=ParseMode.HTML,
                                          reply_markup=dashboard_kb(sess))
            except Exception:
                pass

        if act == "refresh":
            return await restore("Refreshed")
        if act == "help":
            lines = "\n".join(f"/{c} — {esc(d)}" for c, d in COMMANDS)
            await send_long_msg(q.message, f"📖 <b>All commands</b>\n\n{lines}")
            return await restore()
        if act == "tools":
            await q.edit_message_text("🧰 <b>30 Trading Tools</b> — tap to run on YOUR active coin",
                                      parse_mode=ParseMode.HTML,
                                      reply_markup=tool_menu_page(0))
            return
        if act == "signal":
            await q.edit_message_text(f"⏳ Generating <b>{esc(coin)}</b> {esc(tf)} signal "
                                      "(8 engines + Accuracy Engine v2 + AI chain)…",
                                      parse_mode=ParseMode.HTML)
            try:
                sig = await loop.run_in_executor(None, signal_engine.generate_signal, coin, tf)
                await send_long_msg(q.message, fmt_signal(sig))
            except Exception as e:
                await send_long_msg(q.message, f"❌ {esc(str(e)[:250])}")
            return await restore()
        if act == "random":
            m = await q.message.reply_text("🎲 <b>Random-coin funnel started</b> ⏳…",
                                           parse_mode=ParseMode.HTML)
            await run_random_flow(m, tf, q.message)
            return await restore("Funnel finished")
        if act == "chart":
            await q.edit_message_text(f"🎨 rendering {esc(coin)} {esc(tf)} chart…",
                                      parse_mode=ParseMode.HTML)
            try:
                png = await loop.run_in_executor(
                    None, lambda: charting.render_chart_png(coin, tf, 150))
                await q.message.reply_photo(
                    photo=io.BytesIO(png),
                    caption=f"📈 <b>{esc(coin)}</b> {esc(tf)} · ▲▼ strategy events · EMA20/50+VWAP · RSI",
                    parse_mode=ParseMode.HTML)
            except Exception as e:
                await send_long_msg(q.message, f"❌ chart: {esc(str(e)[:200])}")
            return await restore()
        if act == "analyze":
            await q.edit_message_text(f"🔬 analyzing {esc(coin)} {esc(tf)} with all 19 engines…",
                                      parse_mode=ParseMode.HTML)
            try:
                def work():
                    c = signal_engine.get_market_context(coin, tf)
                    v = st.run_strategies(c["df"], c["analysis"])
                    return v, st.combine_votes(v), c
                votes, combo, c = await loop.run_in_executor(None, work)
                lines = [f"🔬 <b>{esc(coin)} {esc(tf)}</b> — full analysis",
                         f"Price <code>{fnum(c['snapshot']['last_price'])}</code> · "
                         f"trend {esc(c['analysis']['trend'])} · RSI {fnum(c['analysis']['rsi_val'])} · "
                         f"ADX {fnum(c['analysis']['adx_val'])}", "━" * 20]
                for v in votes:
                    ic = "🟢" if v["direction"] == "LONG" else "🔴" if v["direction"] == "SHORT" else "⚪"
                    lines.append(f"{ic} <b>{esc(v['display'])}</b> (w{v.get('weight',1):.2f}) → "
                                 f"{esc(v['direction'])} {fnum(v['strength'])}%")
                    lines.append(f"   {esc(v['reason'][:240])}")
                lines.append("━" * 20)
                lines.append(f"⚖ <b>{esc(combo['side'])}</b> · {combo['n_agree']}/{combo['n_total']} agree · "
                             f"conf {fnum(combo['confidence'])}%")
                await send_long_msg(q.message, "\n".join(lines))
            except Exception as e:
                await send_long_msg(q.message, f"❌ {esc(str(e)[:200])}")
            return await restore()
        if act == "news":
            d = await loop.run_in_executor(None, news_mod.news_for_coin,
                                           coin.replace("USDT", ""), 10)
            lines = [f"📰 <b>News — {esc(d['coin'])}</b> · sentiment {d['avg_sentiment']:+.2f}"]
            for n in d["items"][:10]:
                tag = "🟢" if n["sentiment"] > 0.15 else "🔴" if n["sentiment"] < -0.15 else "⚪"
                lines.append(f"{tag} <a href=\"{esc(n['link'])}\">{esc(n['title'][:120])}</a>")
            await send_long_msg(q.message, "\n".join(lines))
            return await restore()
        if act == "ai":
            h = ai_router.health_snapshot()
            lines = ["🤖 <b>AI chain health</b>"]
            for pr in h["providers"]:
                lines.append(f"• <b>{esc(pr['name'].upper())}</b>: "
                             + ("✔" if pr["enabled"] else "✘")
                             + f" · {pr['keys_configured']} key(s)")
            lines.append("• <b>LOCAL ENGINE</b>: ✔ always free fallback")
            await send_long_msg(q.message, "\n".join(lines))
            return await restore()
        if act == "status":
            ok = bc.ping()
            await send_long_msg(q.message,
                f"🩺 Binance API {'✔ online' if ok else '✘ down'} · AI mode "
                f"{esc(CONFIG.get('ai','mode',default='assist'))} · your coin {esc(coin)} {esc(tf)} · "
                "analysis only, no orders.")
            return await restore()
    # quick: legacy menu shortcuts
    if data.startswith("quick:"):
        what = data.split(":")[1]
        sess = get_session(uid)
        if what == "signal":
            await cmd_signal(update, ctx)
        elif what == "chart":
            await cmd_chart(update, ctx)
        elif what == "random":
            await cmd_random(update, ctx)
        elif what == "news":
            await cmd_news(update, ctx)
        return


async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    sess = get_session(update.effective_user.id)
    symbol = args[0] if args else sess["coin"]
    interval = args[1] if len(args) > 1 else sess["interval"]
    msg = await update.effective_message.reply_text(
        f"⏳ Generating AI signal for <b>{esc(symbol.upper())}</b> …\n"
        "(8 engines + AI chain — usually 5–25 s)", parse_mode=ParseMode.HTML)
    loop = asyncio.get_running_loop()
    try:
        sig = await loop.run_in_executor(None, signal_engine.generate_signal, symbol, interval)
    except Exception as e:
        await msg.edit_text(f"❌ Signal failed: {esc(str(e)[:300])}", parse_mode=ParseMode.HTML)
        return
    try:
        await msg.edit_text(fmt_signal(sig), parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
    except Exception:
        await update.effective_message.reply_text(fmt_signal(sig), parse_mode=ParseMode.HTML)


async def run_random_flow(msg, interval: str, chat_message):
    """Funnel progress editor; final signal is replied to chat_message."""
    loop = asyncio.get_running_loop()
    job_id = await loop.run_in_executor(None, lambda: signal_engine.start_random_job(interval))
    last_stage, seen = -1, 0
    result = None
    t0 = time.time()
    while time.time() - t0 < 300:
        await asyncio.sleep(2.0)
        j = await loop.run_in_executor(None, signal_engine.get_job, job_id)
        if not j:
            break
        msgs = j.get("messages", [])
        if len(msgs) > seen or j.get("stage") != last_stage:
            seen = len(msgs)
            last_stage = j.get("stage", last_stage)
            tail = "\n".join("› " + esc(m) for m in msgs[-6:])
            try:
                await msg.edit_text(f"🎲 <b>Funnel running…</b> (stage {last_stage})\n{tail}",
                                    parse_mode=ParseMode.HTML)
            except Exception:
                pass
        if j.get("status") in ("done", "failed"):
            result = j
            break
    if not result:
        await msg.edit_text("❌ Funnel timed out.", parse_mode=ParseMode.HTML)
        return
    if result.get("status") != "done" or not (result.get("result") or {}).get("signal"):
        err = result.get("error") or (result.get("result") or {}).get("error") or "unknown"
        await msg.edit_text(f"❌ Funnel failed: {esc(str(err)[:300])}", parse_mode=ParseMode.HTML)
        return
    res = result["result"]
    stages = res.get("stages", [])
    summary = []
    for stg in stages:
        coins = stg.get("sample") or [c.get("symbol") for c in stg.get("coins", []) if isinstance(c, dict)]
        head = f"<b>Stage {stg['stage']}</b>: {esc(stg.get('name',''))} ({stg.get('count', len(coins))})"
        if coins:
            head += "\n  " + ", ".join(esc(c) for c in coins[:12])
            if len(coins) > 12:
                head += " …"
        summary.append(head)
    await msg.edit_text(f"🏆 <b>Best coin: {esc(res.get('best_coin'))}</b> · {esc(str(res.get('elapsed_sec')))}s\n\n"
                        + "\n\n".join(summary), parse_mode=ParseMode.HTML)
    await send_long_msg(chat_message, fmt_signal(res["signal"]))


async def cmd_random(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    interval = args[0] if args else None
    msg = await update.effective_message.reply_text(
        "🎲 <b>Random-coin funnel started</b>\nbest 1000 → 100 → 10 → 1 → signal\n⏳ stage 0…",
        parse_mode=ParseMode.HTML)
    await run_random_flow(msg, interval, update.effective_message)


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    sess = get_session(update.effective_user.id)
    symbol = bc.normalize_symbol(args[0]) if args else sess["coin"]
    interval = args[1] if len(args) > 1 else None
    if not symbol:
        return await update.effective_message.reply_text(f"Unknown symbol: {esc(args[0])}")
    interval = interval or CONFIG.get("trading", "default_interval", default="15m")

    def work():
        ctxd = signal_engine.get_market_context(symbol, interval)
        votes = st.run_strategies(ctxd["df"], ctxd["analysis"])
        combo = st.combine_votes(votes)
        return votes, combo, ctxd

    msg = await update.effective_message.reply_text(f"⏳ Analyzing {symbol} {interval} with all 19 engines…")
    try:
        votes, combo, ctxd = await asyncio.get_running_loop().run_in_executor(None, work)
    except Exception as e:
        return await msg.edit_text(f"❌ {esc(str(e)[:200])}")
    snap = ctxd["snapshot"]
    lines = [f"🔬 <b>{esc(symbol)} {esc(interval)} — full analysis</b>",
             f"Price <code>{fnum(snap['last_price'])}</code> · 24h {fnum(snap['change_24h_pct'])}% · "
             f"Funding {fnum(snap['funding_rate']*100)}% · Vol ${fnum(snap['quote_volume_24h']/1e6)}M",
             f"Trend: {esc(ctxd['analysis']['trend'])} · RSI {fnum(ctxd['analysis']['rsi_val'])} · "
             f"ADX {fnum(ctxd['analysis']['adx_val'])} · ATR% {fnum(ctxd['analysis']['atr_pct'])}",
             "━" * 22]
    for v in votes:
        icon = "🟢" if v["direction"] == "LONG" else "🔴" if v["direction"] == "SHORT" else "⚪"
        lines.append(f"{icon} <b>{esc(v['display'])}</b> → {esc(v['direction'])} ({fnum(v['strength'])}%)")
        lines.append(f"   {esc(v['reason'][:300])}")
    lines.append("━" * 22)
    lines.append(f"⚖ Confluence: <b>{esc(combo['side'])}</b> · {combo['n_agree']}/{combo['n_total']} agree · "
                 f"conf {fnum(combo['confidence'])}% · net {combo['net_score']:+.0f}")
    await send_long(update, "\n".join(lines))
    await msg.delete()


async def cmd_chart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    sess = get_session(update.effective_user.id)
    symbol = bc.normalize_symbol(args[0] if args else sess["coin"])
    interval = args[1] if len(args) > 1 else sess["interval"]
    if not symbol:
        return await update.effective_message.reply_text(f"Unknown symbol: {esc(args[0] if args else '')}")
    msg = await update.effective_message.reply_text(f"🎨 rendering {symbol} {interval} chart…")
    try:
        png = await asyncio.get_running_loop().run_in_executor(
            None, lambda: charting.render_chart_png(symbol, interval, 150))
        await update.effective_message.reply_photo(
            photo=io.BytesIO(png),
            caption=f"📈 <b>{esc(symbol)}</b> {esc(interval)} · ▲▼ = strategy buy/sell events · EMA20/50 + VWAP · RSI",
            parse_mode=ParseMode.HTML)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ chart failed: {esc(str(e)[:200])}")


async def cmd_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    symbol = bc.normalize_symbol(args[0] if args else "BTC")
    if not symbol:
        return await update.effective_message.reply_text(f"Unknown symbol: {esc(args[0] if args else '')}")
    p = bc.quick_price(symbol)
    await update.effective_message.reply_text(
        f"💲 <b>{esc(symbol)}</b>\n"
        f"Last: <code>{fnum(p['last_price'])}</code> · Mark: <code>{fnum(p['mark_price'])}</code>\n"
        f"24h: {fnum(p['change_24h_pct'])}% · H <code>{fnum(p['high_24h'])}</code> / L <code>{fnum(p['low_24h'])}</code>\n"
        f"Volume: ${fnum(p['quote_volume_24h']/1e6)}M · Trades: {fnum(p['trades_24h'])}\n"
        f"Funding: {fnum(p['funding_rate']*100)}%", parse_mode=ParseMode.HTML)


async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    coin = args[0].upper().replace("USDT", "") if args else None
    msg = await update.effective_message.reply_text("📰 fetching news…")
    d = await asyncio.get_running_loop().run_in_executor(None, news_mod.news_for_coin, coin, 12)
    fng = news_mod.fear_greed()
    lines = [f"📰 <b>News — {esc(d['coin'])}</b> · avg sentiment <b>{d['avg_sentiment']:+.2f}</b>",
             f"😨 Fear&Greed: <b>{fng.get('value', '?')}</b> ({esc(fng.get('label',''))})", "━" * 22]
    for n in d["items"][:12]:
        s = n["sentiment"]
        tag = "🟢" if s > 0.15 else "🔴" if s < -0.15 else "⚪"
        lines.append(f"{tag} <a href=\"{esc(n['link'])}\">{esc(n['title'][:140])}</a>")
        lines.append(f"    <i>{esc(n['source'])}</i> · {esc(n['published'][:22])}")
    if not d["items"]:
        lines.append("No matching news found.")
    await send_long(update, "\n".join(lines))
    await msg.delete()


async def cmd_fear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    f = news_mod.fear_greed()
    await update.effective_message.reply_text(
        f"😨 <b>Crypto Fear & Greed Index</b>\nValue: <b>{f.get('value','?')}</b> ({esc(f.get('label',''))})\n"
        f"Previous: {f.get('prev_value','?')}\n{esc(f.get('interpretation',''))}",
        parse_mode=ParseMode.HTML)


async def cmd_aimode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    if args and args[0] in ("assist", "full", "off"):
        CONFIG.set("ai", "mode", args[0])
        await update.effective_message.reply_text(f"🤖 AI mode → <b>{esc(args[0])}</b>", parse_mode=ParseMode.HTML)
    else:
        cur = CONFIG.get("ai", "mode", default="assist")
        await update.effective_message.reply_text(
            f"🤖 Current AI mode: <b>{esc(cur)}</b>\nUsage: /aimode assist|full|off", parse_mode=ParseMode.HTML)


async def cmd_aistatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    h = ai_router.health_snapshot()
    lines = ["🤖 <b>AI provider health</b>"]
    for p in h["providers"]:
        state = "✔ enabled" if p["enabled"] else "✘ disabled"
        lines.append(f"\n<b>{esc(p['name'].upper())}</b> — {state} · {p['keys_configured']} key(s)")
        for m in p["models"][:8]:
            stt = ("⏸ cooldown %ss" % m["cooldown_left_sec"]) if m["cooling_down"] else (f"✔ ok×{m['ok_calls']}" if m["ok_calls"] else "· idle")
            fails = f" ✘{m['fails']}" if m["fails"] else ""
            lines.append(f"  <code>{esc(m['id'])}</code> {stt}{fails}")
    lines.append("\n<b>LOCAL ENGINE</b> — ✔ always on, always free (final fallback)")
    await send_long(update, "\n".join(lines))


async def cmd_aitest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    prov = (ctx.args or ["groq"])[0]
    msg = await update.effective_message.reply_text(f"🔌 testing {esc(prov)}…")
    d = await asyncio.get_running_loop().run_in_executor(None, ai_router.quick_test, prov)
    ok = "✔" if d["ok"] else "✘"
    await msg.edit_text(f"{ok} <b>{esc(prov)}</b>: model={esc(d.get('model'))} err={esc(d.get('error'))} ({d.get('elapsed')}s)",
                        parse_mode=ParseMode.HTML)


REQUESTS_PATH = os.path.join(DATA_DIR, "access_requests.json")


def _save_request(uid: int, name: str):
    try:
        with open(REQUESTS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d[str(uid)] = {"name": name, "ts": int(time.time())}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REQUESTS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f)


async def cmd_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Any locked-out user can request access; admins get an Approve button."""
    uid = update.effective_user.id
    if allowed(update):
        return await update.effective_message.reply_text("✔ You already have access. Send /start")
    name = update.effective_user.full_name or str(uid)
    _save_request(uid, name)
    admins = CONFIG.get("telegram", "admin_user_ids", default=[]) or []
    if not admins:
        return await update.effective_message.reply_text(
            "📨 Request recorded, but no admin IDs are configured yet.\n"
            "Ask the owner to add your ID in the GUI (Bot tab → Access Control) "
            "or set telegram.admin_user_ids in config.json.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        f"✅ Approve {uid}", callback_data=f"access:approve:{uid}")]])
    for admin_id in admins[:10]:
        try:
            await ctx.bot.send_message(
                admin_id,
                f"🔐 <b>Access request</b>\nUser: {esc(name)}\nID: <code>{uid}</code>",
                parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
    await update.effective_message.reply_text(
        f"📨 Request sent to {min(len(admins), 10)} admin(s). "
        "You will be able to /start once approved.")


async def cmd_allow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/allow <telegram_id> [note] — admin only."""
    if not is_admin(update):
        return await update.effective_message.reply_text("⛔ Admins only (telegram.admin_user_ids).")
    args = ctx.args or []
    if not args:
        return await update.effective_message.reply_text("Usage: /allow <telegram_id> [note]")
    try:
        uid = int(args[0])
    except ValueError:
        return await update.effective_message.reply_text("ID must be numeric.")
    ok, msg = access_add_user(uid, note=" ".join(args[1:]), via="by admin")
    await update.effective_message.reply_text(("✅ " if ok else "❌ ") + esc(msg),
                                              parse_mode=ParseMode.HTML)


async def cmd_revoke(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/revoke <telegram_id> — admin only."""
    if not is_admin(update):
        return await update.effective_message.reply_text("⛔ Admins only (telegram.admin_user_ids).")
    args = ctx.args or []
    if not args:
        return await update.effective_message.reply_text("Usage: /revoke <telegram_id>")
    ok, msg = access_remove_user(int(args[0]))
    await update.effective_message.reply_text(("✅ " if ok else "❌ ") + esc(msg),
                                              parse_mode=ParseMode.HTML)


async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/users — admin only: list the whitelist."""
    if not is_admin(update):
        return await update.effective_message.reply_text("⛔ Admins only (telegram.admin_user_ids).")
    ids = CONFIG.get("telegram", "allowed_user_ids", default=[]) or []
    meta = CONFIG.get("telegram", "user_meta", default={}) or {}
    maxu = CONFIG.get("telegram", "max_users", default=100)
    mode = CONFIG.get("telegram", "access_mode", default="open")
    lines = [f"👥 <b>Access</b> — mode: <b>{esc(mode)}</b> · {len(ids)}/{maxu} users"]
    for i, uid in enumerate(ids[:60], 1):
        m = meta.get(str(uid), {})
        when = time.strftime("%Y-%m-%d", time.localtime(m.get("added_at", 0))) if m.get("added_at") else "-"
        lines.append(f"{i}. <code>{uid}</code> {esc(m.get('note',''))} <i>({when})</i>")
    if len(ids) > 60:
        lines.append(f"… +{len(ids)-60} more (see GUI Bot tab)")
    await send_long(update, "\n".join(lines))


async def cmd_accessmode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/accessmode open|whitelist — admin only."""
    if not is_admin(update):
        return await update.effective_message.reply_text("⛔ Admins only (telegram.admin_user_ids).")
    args = ctx.args or []
    if args and args[0] in ("open", "whitelist"):
        CONFIG.set("telegram", "access_mode", args[0])
        bot_log(f"access mode -> {args[0]}")
        await update.effective_message.reply_text(
            f"🔐 Access mode → <b>{esc(args[0])}</b>" +
            (" (only whitelisted IDs + admins)" if args[0] == "whitelist" else " (anyone can use)"),
            parse_mode=ParseMode.HTML)
    else:
        cur = CONFIG.get("telegram", "access_mode", default="open")
        await update.effective_message.reply_text(
            f"Current mode: <b>{esc(cur)}</b>. Usage: /accessmode open|whitelist",
            parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    ok = bc.ping()
    sig_n = len(signal_engine.journal_list(999))
    await update.effective_message.reply_text(
        f"🩺 <b>System status</b>\nBinance public API: {'✔ online' if ok else '✘ unreachable'}\n"
        f"AI mode: {esc(CONFIG.get('ai','mode',default='assist'))}\n"
        f"Signals generated (journal): {sig_n}\n"
        f"Bot: running · analysis only, no orders, no Binance keys.",
        parse_mode=ParseMode.HTML)


# --------------------------------------------------------- watchlist

def _load_watchlist(chat_id: int) -> list:
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get(str(chat_id), [])
    except Exception:
        return []


def _save_watchlist(chat_id: int, coins: list):
    data = {}
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data[str(chat_id)] = coins
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    chat_id = update.effective_chat.id
    wl = _load_watchlist(chat_id)
    if not args or args[0] == "list":
        txt = ", ".join(wl) if wl else "(empty)"
        return await update.effective_message.reply_text(
            f"👀 Watchlist: {esc(txt)}\nAlerts: strong confluence (≥70%) every ~3 min scan.\n"
            "Usage: /watch add BTC · /watch del BTC", parse_mode=ParseMode.HTML)
    action, coin = args[0].lower(), (args[1] if len(args) > 1 else "").upper()
    sym = bc.normalize_symbol(coin) if coin else None
    if action == "add" and sym:
        if sym not in wl:
            wl.append(sym)
            _save_watchlist(chat_id, wl)
        await update.effective_message.reply_text(f"✔ watching {esc(sym)}: {esc(', '.join(wl))}",
                                                  parse_mode=ParseMode.HTML)
    elif action == "del":
        wl = [w for w in wl if w != sym and w != coin]
        _save_watchlist(chat_id, wl)
        await update.effective_message.reply_text(f"✔ removed. watching: {esc(', '.join(wl) or '(empty)')}",
                                                  parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text("Usage: /watch add|del|list [COIN]")


async def watch_alert_task(app: Application):
    """Background loop: scan every watchlist coin; alert on strong confluence."""
    last_alert = {}
    while True:
        await asyncio.sleep(180)
        try:
            try:
                with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                    wls = json.load(f)
            except Exception:
                continue
            for chat_id, coins in wls.items():
                for sym in coins[:8]:
                    key = (chat_id, sym)
                    if time.time() - last_alert.get(key, 0) < 1800:
                        continue
                    try:
                        ctxd = await asyncio.get_running_loop().run_in_executor(
                            None, signal_engine.get_market_context, sym, None)
                        votes = st.run_strategies(ctxd["df"], ctxd["analysis"])
                        combo = st.combine_votes(votes)
                        if combo["side"] != "NEUTRAL" and combo["confidence"] >= 70 and combo["n_agree"] >= 4:
                            last_alert[key] = time.time()
                            await app.bot.send_message(
                                int(chat_id),
                                f"🚨 <b>WATCH ALERT {esc(sym)}</b> ({esc(ctxd['interval'])})\n"
                                f"{combo['side']} · conf {combo['confidence']:.0f}% · {combo['n_agree']}/{combo['n_total']} engines\n"
                                f"Run /signal {esc(sym)} for full levels.",
                                parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
        except Exception as e:
            log.warning("watch task error: %s", e)


# ------------------------------------------------------------- generic tools

def _tool_cmd(tool_name):
    async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not allowed(update):
            return await deny(update)
        await run_tool_reply(update, tool_name, ctx.args or [])
    return handler


TOOL_COMMANDS = {
    "trend": "trend_scanner", "sr": "support_resistance", "fib": "fibonacci",
    "flow": "orderflow_delta", "funding": "funding_rate", "oi": "open_interest",
    "ls": "long_short_ratio", "liq": "liquidation_zones", "breadth": "market_breadth",
    "movers": "top_movers", "spikes": "volume_spikes", "breakout": "breakout_detector",
    "divergence": "rsi_divergence", "macd": "macd_signals", "supertrend": "supertrend_status",
    "ribbon": "ema_ribbon", "ichimoku": "ichimoku_status", "vwap": "vwap_deviation",
    "size": "position_size", "rr": "risk_reward", "liqprice": "liquidation_price",
    "fundcost": "funding_cost", "corr": "correlation", "volrank": "volatility_rank",
    "dominance": "dominance_snapshot", "journal": "signal_journal", "backtest": "mini_backtest",
}


async def cmd_size(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/size <entry> <sl> [balance] [risk%] — position size calculator."""
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    if len(args) < 2:
        return await update.effective_message.reply_text("Usage: /size <entry> <stop_loss> [balance] [risk%] [leverage]\nExample: /size 60000 58500 1000 1 10")
    params = {"entry": args[0], "stop_loss": args[1]}
    if len(args) > 2:
        params["balance"] = args[2]
    if len(args) > 3:
        params["risk_pct"] = args[3]
    if len(args) > 4:
        params["leverage"] = args[4]
    symbol = "BTCUSDT"
    d = tools_mod.run_tool("position_size", symbol, **params)
    await send_long(update, f"🧮 <b>Position size</b>\n{fmt_dict(d)}")


async def cmd_rr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/rr <entry> <sl> <tp>"""
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    if len(args) < 3:
        return await update.effective_message.reply_text("Usage: /rr <entry> <stop_loss> <take_profit>")
    d = tools_mod.run_tool("risk_reward", None, entry=args[0], stop_loss=args[1], take_profit=args[2])
    await send_long(update, f"⚖ <b>Risk / Reward</b>\n{fmt_dict(d)}")


async def cmd_liqprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/liqprice <entry> <leverage> <long|short>"""
    if not allowed(update):
        return await deny(update)
    args = ctx.args or []
    if len(args) < 3:
        return await update.effective_message.reply_text("Usage: /liqprice <entry> <leverage> <long|short>")
    d = tools_mod.run_tool("liquidation_price", None, entry=args[0], leverage=args[1], side=args[2])
    await send_long(update, f"💥 <b>Liquidation estimate</b>\n{fmt_dict(d)}")


# ------------------------------------------------------------- runner

def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("random", cmd_random))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("fear", cmd_fear))
    app.add_handler(CommandHandler("aimode", cmd_aimode))
    app.add_handler(CommandHandler("aistatus", cmd_aistatus))
    app.add_handler(CommandHandler("aitest", cmd_aitest))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("coin", cmd_coin))
    app.add_handler(CommandHandler("request", cmd_request))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("accessmode", cmd_accessmode))
    app.add_handler(CommandHandler("accuracy", cmd_accuracy))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CommandHandler("size", cmd_size))
    app.add_handler(CommandHandler("rr", cmd_rr))
    app.add_handler(CommandHandler("liqprice", cmd_liqprice))
    for cmd_name, tool_name in TOOL_COMMANDS.items():
        app.add_handler(CommandHandler(cmd_name, _tool_cmd(tool_name)))
    return app


async def _run_polling(token: str, stop_event: threading.Event, controller: dict):
    """Poll with auto-reconnect and human-readable error classification."""
    retries = 0
    while not stop_event.is_set():
        app = build_application(token)
        try:
            await app.initialize()
            await app.start()
            await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
            me = await app.bot.get_me()
            controller["status"] = "running"
            controller["detail"] = f"@{me.username}"
            bot_log(f"bot @{me.username} connected - polling started")
            await app.updater.start_polling(drop_pending_updates=True,
                                            allowed_updates=Update.ALL_TYPES)
            watcher = asyncio.create_task(watch_alert_task(app))
            retries = 0
            while not stop_event.is_set():
                await asyncio.sleep(0.5)
            watcher.cancel()
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            controller["status"] = "stopped"
            controller["detail"] = ""
            bot_log("bot stopped by user")
            return
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:220]}"
            bot_log("ERROR " + err)
            try:
                await app.shutdown()
            except Exception:
                pass
            low = err.lower()
            if ("unauthorized" in low or "invalid token" in low or "invalidtoken" in low
                    or "401" in low or "rejected by the server" in low):
                controller["status"] = "error"
                controller["detail"] = ("Invalid bot token (Telegram 401). Create a fresh token with "
                                        "@BotFather (/newbot or /token) and save it in the Bot tab.")
                return
            if "conflict" in low or "409" in low:
                controller["status"] = "error"
                controller["detail"] = ("Telegram 409 Conflict: another process is already polling with "
                                        "this token (GUI bot AND run_bot.py? or an old crashed instance). "
                                        "Stop the other instance / delete webhook, then Start again.")
                return
            if "getupdates" in low and ("cancelled" in low or "timeout" in low):
                continue  # transient polling hiccup, retry immediately
            retries += 1
            if retries > 6:
                controller["status"] = "error"
                controller["detail"] = err + " — gave up after 6 retries (see Bot logs panel)"
                return
            controller["status"] = f"reconnecting {retries}/6"
            controller["detail"] = err
            bot_log(f"reconnect {retries}/6 in {min(30, 2*retries+2)}s")
            await asyncio.sleep(min(30, 2 * retries + 2))


def start_bot_thread(controller: dict):
    """Start the bot in a background thread. Returns (ok, message)."""
    token = (CONFIG.get("telegram", "bot_token") or "").strip()
    if not token:
        return False, "No bot_token in config. Create a bot with @BotFather and save the token in the Bot tab."
    # liveness: if a previous thread died, don't stay stuck in "running"
    thr = THREAD_STATE.get("thread")
    if controller.get("running") and thr is not None and thr.is_alive():
        return False, "Bot already running."
    if controller.get("running"):
        controller["running"] = False
    bot_log("start requested")
    stop_event = threading.Event()
    controller["running"] = True
    controller["status"] = "starting"
    controller["detail"] = ""

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        THREAD_STATE.update({"thread": threading.current_thread(),
                             "stop_event": stop_event, "loop": loop})
        try:
            loop.run_until_complete(_run_polling(token, stop_event, controller))
        finally:
            controller["running"] = False
            try:
                loop.close()
            except Exception:
                pass

    t = threading.Thread(target=runner, daemon=True, name="telegram-bot")
    THREAD_STATE["thread"] = t
    t.start()
    return True, "Bot thread starting…"


def stop_bot_thread(controller: dict):
    if THREAD_STATE.get("stop_event"):
        THREAD_STATE["stop_event"].set()
        controller["running"] = False
        controller["status"] = "stopped"
        controller["detail"] = "stopping…"
        return True, "Stop requested."
    return False, "Bot not running."


def run_forever():
    """Standalone entry (run_bot.py)."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    token = (CONFIG.get("telegram", "bot_token") or "").strip()
    if not token:
        print("ERROR: telegram.bot_token is empty. Create a bot with @BotFather,")
        print("       then paste the token into config.json (telegram.bot_token).")
        return
    controller = {"running": True, "status": "starting", "detail": ""}
    ok, msg = start_bot_thread(controller)
    print(msg)
    if not ok:
        return
    try:
        while True:
            time.sleep(1)
            if controller.get("status") == "error":
                print("BOT ERROR:", controller.get("detail"))
                break
    except KeyboardInterrupt:
        stop_bot_thread(controller)
        print("Bot stopped.")
