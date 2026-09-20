/* =============== AlphaWave — frontend app =============== */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const fmt = (v, d) => {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const n = Number(v);
  if (d !== undefined) return n.toFixed(d);
  if (Math.abs(n) >= 1000) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (Math.abs(n) >= 1) return n.toFixed(4);
  return n.toPrecision(5);
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
function toast(msg, cls = "") {
  const t = document.createElement("div");
  t.className = "toast " + cls;
  t.textContent = msg;
  $("#toast-zone").appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

const state = {
  coins: [],
  chart: null, candleSeries: null, volSeries: null, overlaySeries: {},
  subChart: null, subSeries: [],
  analysis: null,
  chartTimer: null,
  strategies: [],
};

const OV_COLORS = { ema9: "#f0b90b", ema20: "#2962ff", ema50: "#e040fb", ema100: "#7c8699", ema200: "#ff6d00", vwap: "#00e5ff", supertrend: "#ffd54f", bb_upper: "#787b86", bb_lower: "#787b86", hma9: "#00e676", psar: "#ff9800", kc_upper: "#26c6da", kc_mid: "#26c6da55", kc_lower: "#26c6da", tenkan: "#2962ff", kijun: "#e040fb", senkou_a: "#16c78488", senkou_b: "#ea394388" };

/* ============================== TABS ============================== */
$$(".nav-btn").forEach(b => b.addEventListener("click", () => {
  $$(".nav-btn").forEach(x => x.classList.remove("active"));
  $$(".tab").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  const id = "tab-" + b.dataset.tab;
  $("#" + id).classList.add("active");
  loaders[b.dataset.tab] && loaders[b.dataset.tab]();
}));

function onq(sel, ev, fn) {
  const el = document.querySelector(sel);
  if (el) el.addEventListener(ev, fn);
  else console.warn("AlphaWave: missing element for listener:", sel);
}

const loaders = {
  dashboard: loadDashboard,
  markets: loadMarkets,
  signals: loadSignalTab,
  news: loadNews,
  tools: loadTools,
  ai: loadAI,
  bot: loadBotTab,
};

/* =========================== TOP BAR ============================== */
async function pollTopbar() {
  try {
    const h = await api("/api/health");
    $("#stat-binance").innerHTML = `<span class="dot ${h.binance ? "dot-green" : "dot-red"}"></span> Binance: <b>${h.binance ? "connected" : "DOWN"}</b>`;
    const bs = $("#stat-bot");
    bs.innerHTML = `<span class="dot ${h.bot.running ? "dot-green" : "dot-gray"}"></span> Bot: <b>${h.bot.running ? "running" : h.bot.status}</b>`;
  } catch (e) {
    $("#stat-binance").innerHTML = `<span class="dot dot-red"></span> API: <b>${esc(e.message)}</b>`;
  }
  try {
    const f = await api("/api/fear");
    if (f.value !== null) {
      const cls = f.value <= 25 ? "neg" : f.value >= 75 ? "pos" : "";
      $("#stat-fng").innerHTML = `Fear&amp;Greed: <b class="${cls}">${f.value} (${esc(f.label)})</b>`;
    }
  } catch (e) { /* ignore */ }
  try {
    const m = await api("/api/tools/run?name=dominance_snapshot");
    $("#stat-btc").innerHTML = `BTC: <b>${fmt(m.btc_price)}</b> <span class="${(m.btc_change_pct||0)>=0?'pos':'neg'}">${fmt(m.btc_change_pct,2)}%</span>`;
    $("#stat-eth").innerHTML = `ETH: <b>${fmt(m.eth_price)}</b> <span class="${(m.eth_change_pct||0)>=0?'pos':'neg'}">${fmt(m.eth_change_pct,2)}%</span>`;
  } catch (e) { /* ignore */ }
}
setInterval(pollTopbar, 20000);

/* =========================== DASHBOARD ============================ */
async function loadDashboard() {
  const cards = $("#dash-cards");
  cards.innerHTML = `<div class="card"><div class="c-label">Loading…</div></div>`;
  try {
    const [dom, fng, breadth, movers] = await Promise.all([
      api("/api/tools/run?name=dominance_snapshot"),
      api("/api/fear"),
      api("/api/tools/run?name=market_breadth"),
      api("/api/tools/run?name=top_movers"),
    ]);
    cards.innerHTML = `
      <div class="card"><div class="c-label">BTC Price</div><div class="c-value">${fmt(dom.btc_price)}</div>
        <div class="c-sub ${dom.btc_change_pct>=0?'pos':'neg'}">${fmt(dom.btc_change_pct,2)}% · vol-share ${dom.futures_volume_share_btc_pct}%</div></div>
      <div class="card"><div class="c-label">ETH Price</div><div class="c-value">${fmt(dom.eth_price)}</div>
        <div class="c-sub ${dom.eth_change_pct>=0?'pos':'neg'}">${fmt(dom.eth_change_pct,2)}% · vol-share ${dom.futures_volume_share_eth_pct}%</div></div>
      <div class="card"><div class="c-label">Fear & Greed</div><div class="c-value ${fng.value<=25?'neg':fng.value>=75?'pos':''}">${fng.value ?? "—"}</div>
        <div class="c-sub">${esc(fng.label || "")} ${fng.interpretation ? "· " + esc(fng.interpretation.split(" - ")[0]) : ""}</div></div>
      <div class="card"><div class="c-label">Market Breadth</div><div class="c-value">${fmt(breadth.pct_above_ema20_4h,0)}%</div>
        <div class="c-sub">${esc(breadth.regime || "")} · ${breadth.coins_scanned} coins &gt; EMA20(4h)</div></div>
      <div class="card"><div class="c-label">Futures Volume 24h</div><div class="c-value">$${fmt((dom.total_futures_volume_musd||0)/1000,1)}B</div>
        <div class="c-sub">USDT-M perpetuals</div></div>`;
    const mk = (arr) => `<tr><th>Coin</th><th>Price</th><th>24h %</th><th>Vol M$</th></tr>` + arr.map(t =>
      `<tr><td class="sym" onclick="gotoChart('${t.symbol}')">${t.symbol}</td><td>${fmt(t.price)}</td>
       <td class="${t.change_pct>=0?'pos':'neg'}">${fmt(t.change_pct,2)}%</td><td>${fmt(t.vol_musd,1)}</td></tr>`).join("");
    $("#dash-gainers").innerHTML = mk(movers.gainers || []);
    $("#dash-losers").innerHTML = mk(movers.losers || []);
  } catch (e) { cards.innerHTML = `<div class="card neg">Dashboard error: ${esc(e.message)}</div>`; }

  try {
    const h = await api("/api/signal/history?limit=6");
    $("#dash-signals").innerHTML = h.signals.length
      ? h.signals.map(sigMini).join("")
      : `<div class="muted">No signals yet — go to 🎯 AI Signals.</div>`;
  } catch (e) { /* ignore */ }
  try {
    const nw = await api("/api/news?limit=8");
    $("#dash-news").innerHTML = (nw.items || []).slice(0, 8).map(newsItem).join("") || `<div class="muted">No news loaded.</div>`;
  } catch (e) { /* ignore */ }
}

function sigMini(s) {
  const sideCls = s.side === "LONG" ? "LONG" : s.side === "SHORT" ? "SHORT" : "NOTRADE";
  return `<div class="sg-mini">
    <span class="m-coin">${esc(s.coin)}</span>
    <span class="m-side ${sideCls}">${esc(s.side)}</span>
    <span class="badge">${esc(s.timeframe || "")}</span>
    <span class="muted">entry ${fmt(s.entry_price)} · SL ${fmt(s.stop_loss)} · TP ${fmt(s.take_profit)} · conf ${fmt(s.confidence,0)}%${s.recommended_leverage ? ` · lev ${s.recommended_leverage}x` : ""}</span>
    <span class="muted">${s.generated_at ? new Date(s.generated_at).toLocaleTimeString() : ""}</span>
  </div>`;
}

function newsItem(n) {
  const cls = n.sentiment > 0.15 ? "pos" : n.sentiment < -0.15 ? "neg" : "neu";
  const word = n.sentiment > 0.15 ? "▲ positive" : n.sentiment < -0.15 ? "▼ negative" : "• neutral";
  return `<div class="news-item">
    <a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>
    <div class="news-meta"><span class="badge">${esc(n.source)}</span>
      <span class="sent ${cls}">${word} ${n.sentiment}</span>
      <span class="muted">${esc(n.published || "")}</span></div>
    ${n.summary ? `<div class="news-sum">${esc(n.summary.slice(0, 220))}</div>` : ""}
  </div>`;
}

/* ============================ MARKETS ============================= */
async function loadMarkets(force = true) {
  if (force || !state.coins.length) {
    try {
      const d = await api("/api/coins");
      state.coins = d.coins;
      $("#mk-count").textContent = `${d.count} USDT-M perpetual contracts (public data, no API key needed)`;
    } catch (e) { toast("Markets load failed: " + e.message, "err"); return; }
  }
  renderMarkets();
}

function renderMarkets() {
  const q = ($("#mk-search").value || "").toUpperCase().trim();
  const sortKey = $("#mk-sort").value;
  let rows = state.coins.filter(c => !q || c.symbol.includes(q));
  rows.sort((a, b) => {
    if (sortKey === "symbol") return a.symbol.localeCompare(b.symbol);
    return (parseFloat(b[sortKey]) || 0) - (parseFloat(a[sortKey]) || 0);
  });
  rows = rows.slice(0, 600);
  const tb = $("#mk-table tbody");
  tb.innerHTML = rows.map((c, i) => `<tr>
    <td class="muted">${i + 1}</td>
    <td class="sym" onclick="gotoChart('${c.symbol}')">${c.symbol}</td>
    <td>${fmt(c.price)}</td>
    <td class="${(parseFloat(c.change_pct)||0)>=0?'pos':'neg'}">${fmt(c.change_pct,2)}%</td>
    <td>${fmt(c.high)}</td><td>${fmt(c.low)}</td>
    <td>${fmt((parseFloat(c.volume_usd)||0)/1e6,1)}</td>
    <td class="${(parseFloat(c.funding_pct)||0)>=0?'pos':'neg'}">${fmt(c.funding_pct,4)}</td>
    <td class="muted">${fmt(c.trades,0)}</td>
    <td><button class="btn" onclick="gotoChart('${c.symbol}')">📈</button></td>
    <td><button class="btn" onclick="quickSignal('${c.symbol}')">⚡</button></td>
  </tr>`).join("");
}
onq("#mk-search", "input", () => renderMarkets());
onq("#mk-sort", "change", () => renderMarkets());
onq("#mk-refresh", "click", () => loadMarkets(true));

window.gotoChart = function (symbol) {
  $("#ch-symbol").value = symbol;
  $$(".nav-btn").forEach(x => x.classList.remove("active"));
  $$(".tab").forEach(x => x.classList.remove("active"));
  document.querySelector('[data-tab="chart"]').classList.add("active");
  $("#tab-chart").classList.add("active");
  loadChart();
};
window.quickSignal = function (symbol) {
  $("#sg-symbol").value = symbol;
  $$(".nav-btn").forEach(x => x.classList.remove("active"));
  $$(".tab").forEach(x => x.classList.remove("active"));
  document.querySelector('[data-tab="signals"]').classList.add("active");
  $("#tab-signals").classList.add("active");
  loadSignalTab();
  runSignal();
};

/* ============================== CHART ============================== */
function currentTf() { return $("#ch-tf button.on")?.dataset.tf || "15m"; }
$$("#ch-tf button").forEach(b => b.addEventListener("click", () => {
  $$("#ch-tf button").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  loadChart();
}));
onq("#ch-load", "click", loadChart);
onq("#ch-sub", "change", renderSubPane);
onq("#ch-marks", "change", renderMarks);
$$(".ov").forEach(cb => cb.addEventListener("change", () => renderOverlays()));
onq("#ch-style", "change", e => {
  state.chartStyle = e.target.value;
  if (state.analysis) buildChart(state.analysis);
});

function chartOpts(height) {
  return {
    layout: { background: { color: "#131722" }, textColor: "#d1d4dc", fontSize: 11 },
    grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
    crosshair: { mode: 0 },
    rightPriceScale: { borderColor: "#2a2e39" },
    timeScale: { borderColor: "#2a2e39", timeVisible: true, secondsVisible: false },
    height,
    autoSize: false,
  };
}

/* Heikin-Ashi transform of raw candles [[time,o,h,l,c,v],...] */
function heikinAshi(candles) {
  const out = [];
  let po = null, pc = null;
  for (const c of candles) {
    const [t, o, h, l, cl] = [c[0], c[1], c[2], c[3], c[4]];
    const hc = (o + h + l + cl) / 4;
    const ho = po === null ? (o + cl) / 2 : (po + pc) / 2;
    out.push({ time: Math.floor(t / 1000), open: ho,
               high: Math.max(h, ho, hc), low: Math.min(l, ho, hc), close: hc });
    po = ho; pc = hc;
  }
  return out;
}

function makeMainSeries(chart, style, candles) {
  const T = candles.map(c => Math.floor(c[0] / 1000));
  const close = candles.map(c => c[4]);
  const candleData = candles.map(c => ({ time: Math.floor(c[0] / 1000), open: c[1], high: c[2], low: c[3], close: c[4] }));
  const std = { upColor: "#16c784", downColor: "#ea3943", borderUpColor: "#16c784",
                borderDownColor: "#ea3943", wickUpColor: "#16c784", wickDownColor: "#ea3943" };
  if (style === "hollow") {
    const s = chart.addCandlestickSeries({ ...std, upColor: "rgba(22,199,132,0.06)",
                                           borderUpColor: "#16c784", wickUpColor: "#16c784" });
    s.setData(candleData); return s;
  }
  if (style === "bars") {
    const s = chart.addBarSeries({ upColor: "#16c784", downColor: "#ea3943", thinBars: false });
    s.setData(candleData); return s;
  }
  if (style === "line") {
    const s = chart.addLineSeries({ color: "#f0b90b", lineWidth: 2 });
    s.setData(T.map((t, i) => ({ time: t, value: close[i] }))); return s;
  }
  if (style === "area") {
    const s = chart.addAreaSeries({ lineColor: "#f0b90b", lineWidth: 2,
      topColor: "rgba(240,185,11,0.35)", bottomColor: "rgba(240,185,11,0.02)" });
    s.setData(T.map((t, i) => ({ time: t, value: close[i] }))); return s;
  }
  if (style === "baseline") {
    const s = chart.addBaselineSeries({
      baseValue: { type: "price", price: close[0] },
      topLineColor: "#16c784", topFillColor1: "rgba(22,199,132,0.28)", topFillColor2: "rgba(22,199,132,0.02)",
      bottomLineColor: "#ea3943", bottomFillColor1: "rgba(234,57,67,0.02)", bottomFillColor2: "rgba(234,57,67,0.28)",
      lineWidth: 2 });
    s.setData(T.map((t, i) => ({ time: t, value: close[i] }))); return s;
  }
  if (style === "heikin") {
    const s = chart.addCandlestickSeries(std);
    const ha = heikinAshi(candles);
    s.setData(ha);
    state.haPrev = ha[ha.length - 1];
    return s;
  }
  const s = chart.addCandlestickSeries(std);
  s.setData(candleData); return s;
}

/* fast live tick: last candle + price flash every 4 s */
async function liveTick() {
  if (!document.querySelector("#tab-chart.active")) return;
  try {
    const sym = ($("#ch-symbol").value || "").toUpperCase().trim();
    if (!sym) return;
    const d = await api(`/api/klines?symbol=${encodeURIComponent(sym)}&interval=${currentTf()}&limit=3`);
    const last = d.klines[d.klines.length - 1];
    const t = Math.floor(last[0] / 1000);
    const price = last[4];
    // LIVE badge flashes on every tick, even if the chart itself is not ready
    const elB = $("#ch-live-price"), arB = $("#ch-live-arrow");
    if (elB && state.lastTick !== undefined && price !== state.lastTick) {
      const up = price > state.lastTick;
      elB.classList.remove("flash-up", "flash-dn"); void elB.offsetWidth;
      elB.classList.add(up ? "flash-up" : "flash-dn");
      arB.textContent = up ? "▲" : "▼";
      arB.className = up ? "pos" : "neg";
      setTimeout(() => elB.classList.remove("flash-up", "flash-dn"), 900);
    }
    if (elB) { state.lastTick = price; elB.textContent = fmt(price); }
    if (!state.analysis || !state.candleSeries) return;
    const style = state.chartStyle || "candles";
    if (style === "line" || style === "area" || style === "baseline") {
      state.candleSeries.update({ time: t, value: price });
    } else if (style === "heikin") {
      const p = state.haPrev;
      const hc = (last[1] + last[2] + last[3] + last[4]) / 4;
      const ho = p ? (p.open + p.close) / 2 : (last[1] + last[4]) / 2;
      const upd = { time: t, open: ho, high: Math.max(last[2], ho, hc), low: Math.min(last[3], ho, hc), close: hc };
      state.candleSeries.update(upd); state.haPrev = upd;
    } else {
      state.candleSeries.update({ time: t, open: last[1], high: last[2], low: last[3], close: last[4] });
    }
    if (state.volSeries) state.volSeries.update({ time: t, value: last[5],
      color: last[4] >= last[1] ? "rgba(22,199,132,.35)" : "rgba(234,57,67,.35)" });
  } catch (e) { /* silent */ }
}
setInterval(liveTick, 4000);

async function loadChart() {
  const symbol = ($("#ch-symbol").value || "BTCUSDT").toUpperCase().trim();
  const tf = currentTf();
  try {
    const d = await api(`/api/analysis?symbol=${encodeURIComponent(symbol)}&interval=${tf}`);
    state.analysis = d;
    buildChart(d);
    renderChartInfo(d);
    renderVotes(d.votes, d.combo, "#ch-votes");
    renderZones(d);
    $("#ch-png").href = `/api/chart.png?symbol=${encodeURIComponent(symbol)}&interval=${tf}`;
  } catch (e) { toast("Chart load failed: " + e.message, "err"); }
}

function buildChart(d) {
  const el = $("#ch-main");
  if (state.chart) { state.chart.remove(); state.chart = null; }
  const chart = LightweightCharts.createChart(el, chartOpts(460));
  chart.applyOptions({ width: el.clientWidth });
  state.chart = chart;
  try {
    state.candleSeries = makeMainSeries(chart, state.chartStyle || "candles", d.candles);
  } catch (e) {
    console.error("chart style failed", e);
    toast("Chart style error (" + e.message + ") — falling back to Candles", "err");
    state.chartStyle = "candles";
    const sel = $("#ch-style"); if (sel) sel.value = "candles";
    state.candleSeries = makeMainSeries(chart, "candles", d.candles);
  }

  const vs = chart.addHistogramSeries({
    priceFormat: { type: "volume" }, priceScaleId: "vol",
    color: "#26a69a55",
  });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
  vs.setData(d.candles.map(c => ({
    time: Math.floor(c[0] / 1000), value: c[5],
    color: c[4] >= c[1] ? "rgba(22,199,132,.35)" : "rgba(234,57,67,.35)",
  })));
  state.volSeries = vs;

  state.overlaySeries = {};
  renderOverlays();
  renderMarks();
  buildSubChart();
  renderSubPane();
  chart.timeScale().fitContent();

  // auto refresh (watch mode)
  if (state.chartTimer) clearInterval(state.chartTimer);
  if ($("#ch-autorefresh").checked) {
    state.chartTimer = setInterval(() => {
      if (document.querySelector("#tab-chart.active")) silentRefresh();
    }, 10000);
  }
}

async function silentRefresh() {
  try {
    const symbol = ($("#ch-symbol").value || "").toUpperCase().trim();
    const d = await api(`/api/analysis?symbol=${encodeURIComponent(symbol)}&interval=${currentTf()}`);
    state.analysis = d;
    renderChartInfo(d);
    renderVotes(d.votes, d.combo, "#ch-votes");
  } catch (e) { /* silent */ }
}


function renderOverlays() {
  if (!state.chart || !state.analysis) return;
  Object.values(state.overlaySeries).forEach(s => { try { state.chart.removeSeries(s); } catch (e) {} });
  state.overlaySeries = {};
  (state.priceLines || []).forEach(pl => { try { state.candleSeries.removePriceLine(pl); } catch (e) {} });
  state.priceLines = [];
  const on = $$(".ov:checked").map(c => c.value);
  const times = state.analysis.candles.map(c => Math.floor(c[0] / 1000));
  const o = state.analysis.overlays || {};
  const addLine = (key, data, color, title, width = 1.4) => {
    if (!data) return;
    const s = state.chart.addLineSeries({ color, lineWidth: width, title, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    s.setData(times.map((t, i) => data[i] == null ? null : { time: t, value: data[i] }).filter(Boolean));
    state.overlaySeries[key] = s;
  };
  const addPriceLine = (price, color, title) => {
    if (!price || !state.candleSeries || !state.candleSeries.createPriceLine) return;
    try {
      state.priceLines.push(state.candleSeries.createPriceLine({
        price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
    } catch (e) { /* ignore */ }
  };
  for (const k of on) {
    if (k === "bb_upper") {
      addLine("bb_upper", o.bb_upper, OV_COLORS.bb_upper, "BB↑", 1);
      addLine("bb_lower", o.bb_lower, OV_COLORS.bb_lower, "BB↓", 1);
    } else if (k === "ichimoku") {
      addLine("tenkan", o.tenkan, OV_COLORS.tenkan, "TENKAN", 1);
      addLine("kijun", o.kijun, OV_COLORS.kijun, "KIJUN", 1);
      addLine("senkou_a", o.senkou_a, OV_COLORS.senkou_a, "SSA", 1);
      addLine("senkou_b", o.senkou_b, OV_COLORS.senkou_b, "SSB", 1);
    } else if (k === "kc_upper") {
      addLine("kc_upper", o.kc_upper, OV_COLORS.kc_upper, "KC↑", 1);
      addLine("kc_mid", o.kc_mid, OV_COLORS.kc_mid, "KCmid", 1);
      addLine("kc_lower", o.kc_lower, OV_COLORS.kc_lower, "KC↓", 1);
    } else if (k === "pivots") {
      const pv = (state.analysis.levels || {}).pivots || {};
      addPriceLine(pv.R2, "#ea3943", "R2"); addPriceLine(pv.R1, "#ea3943aa", "R1");
      addPriceLine(pv.P, "#f0b90b", "P");
      addPriceLine(pv.S1, "#16c784aa", "S1"); addPriceLine(pv.S2, "#16c784", "S2");
    } else if (k === "fibs") {
      const fb = (state.analysis.levels || {}).fibs || {};
      for (const [lvl, price] of Object.entries(fb)) addPriceLine(price, "#787b86aa", "fib " + lvl);
    } else addLine(k, o[k], OV_COLORS[k] || "#fff", k.toUpperCase());
  }
}

function renderMarks() {
  if (!state.candleSeries || !state.analysis) return;
  if (!$("#ch-marks").checked) { state.candleSeries.setMarkers([]); return; }
  const lastT = Math.floor(state.analysis.candles[state.analysis.candles.length - 1][0] / 1000);
  const marks = (state.analysis.events || [])
    .filter(e => Math.floor(e.time / 1000) <= lastT)
    .slice(-45)
    .map(e => ({
      time: Math.floor(e.time / 1000),
      position: e.side === "buy" ? "belowBar" : "aboveBar",
      color: e.side === "buy" ? "#00e676" : "#ff1744",
      shape: e.side === "buy" ? "arrowUp" : "arrowDown",
      text: e.label,
    }));
  marks.sort((a, b) => a.time - b.time);
  state.candleSeries.setMarkers(marks);
}

function buildSubChart() {
  const el = $("#ch-subpane");
  if (state.subChart) { state.subChart.remove(); state.subChart = null; }
  const sub = $("#ch-sub").value;
  if (sub === "none") { el.style.display = "none"; return; }
  el.style.display = "block";
  const chart = LightweightCharts.createChart(el, { ...chartOpts(130), width: el.clientWidth });
  state.subChart = chart;
}

function renderSubPane() {
  if (!state.analysis) return;
  buildSubChart();
  if (!state.subChart) return;
  const sub = $("#ch-sub").value;
  const times = state.analysis.candles.map(c => Math.floor(c[0] / 1000));
  const S = state.analysis.sub || {};
  const line = (key, color, width = 1.4) => {
    if (!S[key]) return null;
    const s = state.subChart.addLineSeries({ color, lineWidth: width, priceLineVisible: false, lastValueVisible: false });
    s.setData(times.map((t, i) => S[key][i] == null ? null : { time: t, value: S[key][i] }).filter(Boolean));
    return s;
  };
  const hline = (lv, color) => {
    const s = state.subChart.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    s.setData(times.map(t => ({ time: t, value: lv })));
  };
  if (sub === "rsi") {
    line("rsi", "#f0b90b", 1.5); hline(70, "#ea394366"); hline(50, "#2a2e39"); hline(30, "#16c78466");
  } else if (sub === "macd") {
    const h = state.subChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    h.setData(times.map((t, i) => S.macd_hist[i] == null ? null : { time: t, value: S.macd_hist[i], color: S.macd_hist[i] >= 0 ? "#16c784aa" : "#ea3943aa" }).filter(Boolean));
    line("macd", "#2962ff"); line("macd_signal", "#ff6d00");
  } else if (sub === "stoch_k") {
    line("stoch_k", "#2962ff"); line("stoch_d", "#ff6d00"); hline(80, "#ea394366"); hline(20, "#16c78466");
  } else if (sub === "stochrsi") {
    line("stochrsi", "#e040fb", 1.5); hline(80, "#ea394366"); hline(20, "#16c78466");
  } else if (sub === "cci") {
    line("cci", "#00e5ff", 1.5); hline(100, "#ea394366"); hline(0, "#2a2e39"); hline(-100, "#16c78466");
  } else if (sub === "willr") {
    line("willr", "#ff9800", 1.5); hline(-20, "#ea394366"); hline(-80, "#16c78466");
  } else if (sub === "mfi") {
    line("mfi", "#26a69a", 1.5); hline(80, "#ea394366"); hline(20, "#16c78466");
  } else if (sub === "adx") {
    line("adx", "#f0b90b", 1.8); line("pdi", "#16c784"); line("mdi", "#ea3943"); hline(25, "#2a2e39");
  } else if (sub === "obv") {
    line("obv", "#00e5ff", 1.6);
  } else if (sub === "roc") {
    line("roc", "#a855f7", 1.5); hline(0, "#2a2e39");
  } else if (sub === "atr") {
    line("atr", "#ffd54f", 1.5);
  } else if (sub === "cvd") {
    line("cvd", "#00e5ff", 1.6);
  }
  state.subChart.timeScale().fitContent();
}

function renderChartInfo(d) {
  const s = d.snapshot;
  const chg = d.candles.length > 1 ? (d.candles[d.candles.length-1][4] - d.candles[0][1]) / d.candles[0][1] * 100 : 0;
  $("#ch-info").innerHTML = `
    <span class="ci">Symbol: <b style="color:var(--yellow)">${esc(d.symbol)}</b></span>
    <span class="ci">Last: <b>${fmt(s.price)}</b></span>
    <span class="ci ${chg>=0?'pos':'neg'}">Window: <b>${fmt(chg,2)}%</b></span>
    <span class="ci">Trend: <b class="${s.trend==='UP'?'pos':s.trend==='DOWN'?'neg':''}">${s.trend}</b></span>
    <span class="ci">RSI: <b>${fmt(s.rsi,1)}</b></span>
    <span class="ci">ADX: <b>${fmt(s.adx,1)}</b></span>
    <span class="ci">ATR%: <b>${fmt(s.atr_pct,2)}</b></span>
    <span class="ci">BB pos: <b>${fmt(s.bb_pos,2)}</b></span>
    <span class="ci">SuperTrend: <b class="${s.st_dir===1?'pos':'neg'}">${s.st_dir===1?'UP':'DOWN'}</b></span>
    <span class="ci">CVD slope: <b class="${s.cvd_slope>=0?'pos':'neg'}">${fmt(s.cvd_slope,2)}</b></span>`;
}

function renderVotes(votes, combo, target) {
  const el = $(target);
  el.innerHTML = votes.map(v => {
    const color = v.direction === "LONG" ? "var(--green)" : v.direction === "SHORT" ? "var(--red)" : "#4a5568";
    return `<div class="vote-wrap"><div class="vote-row">
      <span class="vote-name">${esc(v.display)}</span>
      <span class="vote-dir ${v.direction}">${v.direction}</span>
      <div class="vote-bar"><div style="width:${v.strength}%;background:${color}"></div></div>
      <span class="muted" style="width:46px;text-align:right">${fmt(v.strength,0)}%</span>
      <div class="vote-reason">${esc(v.reason)}</div>
    </div></div>`;
  }).join("") +
  `<div class="vote-row" style="border-top:2px solid var(--border)">
     <span class="vote-name" style="color:var(--yellow)">⚖ CONFLUENCE</span>
     <span class="vote-dir ${combo.side}">${combo.side}</span>
     <div class="vote-bar"><div style="width:${combo.confidence}%;background:var(--yellow)"></div></div>
     <span class="muted">${combo.n_agree}/${combo.n_total} agree · conf ${fmt(combo.confidence,0)}% · net ${combo.net_score > 0 ? "+" : ""}${fmt(combo.net_score,0)}</span>
   </div>`;
}

function renderZones(d) {
  const zones = [];
  (d.fvgs || []).forEach(g => zones.push(
    `<div>${g.type === "bull" ? "🟩 BULL FVG" : "🟥 BEAR FVG"} [${fmt(g.bottom)} – ${fmt(g.top)}] ${g.filled ? "(filled)" : ""}</div>`));
  (d.order_blocks || []).forEach(o => zones.push(
    `<div>${o.type === "bull" ? "🟢 BULL OB" : "🔴 BEAR OB"} [${fmt(o.bottom)} – ${fmt(o.top)}]</div>`));
  $("#ch-zones").innerHTML = zones.join("") || `<div class="muted">No open FVG / recent order blocks on this timeframe.</div>`;
}

window.addEventListener("resize", () => {
  if (state.chart) state.chart.applyOptions({ width: $("#ch-main").clientWidth });
  if (state.subChart) state.subChart.applyOptions({ width: $("#ch-subpane").clientWidth });
});

/* ============================ SIGNALS ============================== */
let strategiesLoaded = false;
async function loadSignalTab() {
  if (!strategiesLoaded) {
    try {
      const d = await api("/api/strategies");
      state.strategies = d.strategies;
      $("#sg-strategies").innerHTML = `<span class="muted">Strategies:</span>` +
        d.strategies.map(s => `<label class="chk"><input type="checkbox" class="sg-strat" value="${s.name}" checked> ${esc(s.display)}</label>`).join("");
      strategiesLoaded = true;
    } catch (e) { /* ignore */ }
  }
  try {
    const h = await api("/api/signal/history?limit=20");
    $("#sg-history").innerHTML = h.signals.map(signalCard).join("") || `<div class="muted">Empty journal.</div>`;
  } catch (e) { /* ignore */ }
}

onq("#sg-run", "click", runSignal);

onq("#ac-load", "click", async () => {
  const sym = ($("#sg-symbol").value || "BTCUSDT").trim();
  const tf = $("#sg-interval").value;
  $("#ac-out").textContent = "⏳ replaying history (walk-forward)…";
  try {
    const d = await api(`/api/accuracy?symbol=${encodeURIComponent(sym)}&interval=${tf}`);
    $("#ac-out").innerHTML = d.engines.map(r =>
      `• <b>${esc(r.engine)}</b>: blended weight x${r.blended_weight} ` +
      `(walk-forward x${r.walkforward_weight} · live-record x${r.live_record_weight}) ` +
      `· live record ${r.live_wins}W/${r.live_losses}L` +
      (r.live_winrate_pct !== null ? ` (${r.live_winrate_pct}%)` : "")).join("\n") +
      `\n\nEvaluated live signals so far: ${d.evaluated_signals} — engines that win get stronger votes, engines that fail get muted.`;
  } catch (e) { $("#ac-out").innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
});

async function runSignal() {
  const symbol = ($("#sg-symbol").value || "").trim();
  if (!symbol) return toast("Enter a symbol first", "err");
  const strat = $$(".sg-strat:checked").map(c => c.value).join(",");
  const btn = $("#sg-run");
  btn.disabled = true; btn.textContent = "⏳ Analyzing… (TA + AI chain)";
  $("#sg-result").innerHTML = `<div class="panel muted">Running 19 strategy engines on live Binance data, then the AI chain (Groq → OpenRouter → Ollama → local free engine)…</div>`;
  try {
    const sig = await api("/api/signal/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, interval: $("#sg-interval").value, strategies: strat, ai_mode: $("#sg-ai").value }),
    });
    $("#sg-result").innerHTML = signalCard(sig);
    toast(`Signal ready: ${sig.coin} ${sig.side}`, sig.side === "NO TRADE" ? "" : "ok");
    loadSignalTab();
  } catch (e) {
    $("#sg-result").innerHTML = `<div class="panel neg">Error: ${esc(e.message)}</div>`;
    toast("Signal failed: " + e.message, "err");
  } finally {
    btn.disabled = false; btn.textContent = "⚡ GENERATE SIGNAL";
  }
}

function signalCard(s) {
  const sideCls = s.side === "LONG" ? "LONG" : s.side === "SHORT" ? "SHORT" : "NOTRADE";
  const tps = (s.take_profit_levels || []).map(t =>
    `<span class="sg-tp-pill">${esc(t.name)}: ${fmt(t.price)} (${t.r}R)</span>`).join("");
  const bd = (s.strategy_breakdown || []).map(v => `
    <div class="vote-row">
      <span class="vote-name">${esc(v.strategy)}</span>
      <span class="vote-dir ${v.direction}">${v.direction}</span>
      <div class="vote-bar"><div style="width:${v.strength}%;background:${v.direction==='LONG'?'var(--green)':v.direction==='SHORT'?'var(--red)':'#4a5568'}"></div></div>
      <div class="vote-reason">${esc(v.reason)}</div>
    </div>`).join("");
  const aiTag = s.ai_provider ? `${s.ai_provider}${s.ai_model ? " · " + s.ai_model : ""}` : "local free engine";
  const isExtreme = String(s.leverage_tier || "").startsWith("EXTREME");
  const levCell = s.recommended_leverage
    ? `<div class="sg-cell lev ${isExtreme ? "extreme" : ""}"><label>Leverage ${isExtreme ? "⚡" : ""}</label><b>${s.recommended_leverage}x</b></div>
       <div class="sg-cell"><label>Est. liq. distance</label><b>~${fmt(s.est_liquidation_distance_pct, 1)}%</b></div>`
    : `<div class="sg-cell lev"><label>Leverage</label><b>—</b></div>`;
  const levBadge = s.recommended_leverage
    ? `<span class="sg-ai badge ${isExtreme ? "red" : "yellow"}">${isExtreme ? "⚡ EXTREME &gt;20x setup" : " 10–20x policy"} · ${s.recommended_leverage}x</span>`
    : "";
  const htfBadge = s.htf
    ? `<span class="sg-ai badge ${s.htf_aligned === true ? "green" : s.htf_aligned === false ? "red" : ""}">🧭 HTF ${esc(s.htf.timeframe)}: ${esc(s.htf.bias)}${s.htf_aligned === true ? " ✔ aligned" : s.htf_aligned === false ? " ✘ opposed" : ""}</span>`
    : "";
  const gateNote = (s.quality_gates && (s.quality_gates.soft || []).length)
    ? `<div class="muted" style="margin:-2px 0 10px">⚠ Risk notes: ${s.quality_gates.soft.map(esc).join(" · ")}</div>` : "";
  return `<div class="signal-card ${sideCls}">
    <div class="sg-head">
      <span class="sg-coin">${esc(s.coin)}</span>
      <span class="sg-side ${sideCls}">${esc(s.side)}</span>
      <span class="sg-tf badge">${esc(s.timeframe || "")}</span>
      <span class="sg-conf badge ${s.confidence >= 65 ? "green" : s.confidence >= 45 ? "yellow" : "red"}">confidence ${fmt(s.confidence, 0)}%</span>
      ${levBadge}
      ${htfBadge}
      <span class="sg-ai badge">🤖 ${esc(aiTag)}</span>
      <span class="sg-time muted">${s.generated_at ? new Date(s.generated_at).toLocaleString() : ""} · ${fmt(s.elapsed_sec,1)}s</span>
    </div>
    <div class="sg-grid">
      <div class="sg-cell"><label>Live Market Price</label><b>${fmt(s.live_price)}</b></div>
      <div class="sg-cell"><label>Entry Price</label><b>${fmt(s.entry_price)}</b></div>
      <div class="sg-cell sl"><label>Stop Loss</label><b>${fmt(s.stop_loss)}</b></div>
      <div class="sg-cell tp"><label>Take Profit</label><b>${fmt(s.take_profit)}</b></div>
      <div class="sg-cell"><label>Risk : Reward</label><b>${fmt(s.risk_reward, 2)}</b></div>
      ${levCell}
      <div class="sg-cell"><label>SL Distance</label><b>${fmt(s.stop_distance_pct, 2)}%</b></div>
    </div>
    ${s.leverage_reason ? `<div class="muted" style="margin:-2px 0 10px">⚙ Leverage logic: ${esc(s.leverage_reason)}</div>` : ""}
    ${gateNote}
    ${tps ? `<div class="sg-tps">${tps}</div>` : ""}
    <div class="sg-reason"><b style="color:var(--yellow)">📜 Signal Reason (strategy · technique · logic):</b>\n${esc(s.reason || "")}</div>
    <details class="sg-breakdown"><summary>Full strategy breakdown (${(s.strategy_breakdown||[]).length} engines)</summary>
      <div class="sg-bd-body">${bd}</div>
      ${s.ai_errors && s.ai_errors.length ? `<div class="muted" style="margin-top:8px">AI chain notes: ${s.ai_errors.map(esc).join(" · ")}</div>` : ""}
    </details>
    <div class="muted" style="margin-top:8px">${esc(s.disclaimer || "")}</div>
  </div>`;
}

/* ========================= RANDOM FUNNEL =========================== */
onq("#rd-run", "click", async () => {
  const btn = $("#rd-run");
  btn.disabled = true;
  $("#rd-progress").innerHTML = "";
  $("#rd-stages").innerHTML = "";
  $("#rd-result").innerHTML = `<div class="panel muted">Funnel starting…</div>`;
  try {
    const { job_id } = await api("/api/signal/random/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interval: $("#rd-interval").value, ai_mode: $("#rd-ai").value }),
    });
    const feed = $("#rd-progress");
    let lastCount = 0;
    const poll = setInterval(async () => {
      let j;
      try { j = await api(`/api/signal/random/status/${job_id}`); } catch (e) { return; }
      (j.messages || []).slice(lastCount).forEach(m => {
        const div = document.createElement("div");
        div.className = "pf-line"; div.textContent = m;
        feed.appendChild(div);
      });
      lastCount = (j.messages || []).length;
      feed.scrollTop = feed.scrollHeight;
      if (j.status === "done" || j.status === "failed") {
        clearInterval(poll);
        btn.disabled = false;
        if (j.status === "done" && j.result) {
          $("#rd-stages").innerHTML = (j.result.stages || []).map(stageCard).join("");
          $("#rd-result").innerHTML = j.result.signal
            ? `<h3 style="margin:10px 0">🏆 Best coin: ${esc(j.result.best_coin)} — Signal</h3>` + signalCard(j.result.signal)
            : `<div class="panel neg">${esc(j.result.error || "No signal produced.")}</div>`;
          toast("Random funnel complete!", "ok");
          loadSignalTab();
        } else {
          $("#rd-result").innerHTML = `<div class="panel neg">Funnel failed: ${esc(j.error || "unknown")}</div>`;
        }
      }
    }, 1500);
  } catch (e) {
    btn.disabled = false;
    $("#rd-result").innerHTML = `<div class="panel neg">${esc(e.message)}</div>`;
  }
});

function stageCard(st) {
  let body = "";
  if (st.sample) body = `<div class="stage-chips">${st.sample.map(s => `<span class="chip">${esc(s)}</span>`).join("")}…</div>`;
  if (st.coins) body = `<div class="stage-chips">${st.coins.map(c =>
    `<span class="chip">${esc(c.symbol)} ${c.score !== undefined ? `<b>${fmt(c.score, 0)}</b>` : ""} ${c.side ? `(${esc(c.side)} ${fmt(c.confidence, 0)}%)` : ""}</span>`).join("")}</div>`;
  return `<div class="stage-card"><h4>Stage ${st.stage}: ${esc(st.name)} — ${st.count ?? (st.coins||[]).length} coins</h4>
    ${st.note ? `<div class="muted" style="margin-bottom:6px">${esc(st.note)}</div>` : ""}${body}</div>`;
}

/* ============================== NEWS =============================== */
onq("#nw-load", "click", loadNews);
async function loadNews() {
  const coin = ($("#nw-coin").value || "").trim();
  try {
    const d = await api(`/api/news?coin=${encodeURIComponent(coin)}&limit=40`);
    const f = d.fear_greed || {};
    $("#nw-fng-card").innerHTML = `
      <div class="card"><div class="c-label">Fear & Greed Index</div>
        <div class="c-value ${f.value<=25?'neg':f.value>=75?'pos':''}">${f.value ?? "—"}</div>
        <div class="c-sub">${esc(f.label || "")}</div></div>
      <div class="card"><div class="c-label">Interpretation</div>
        <div class="c-sub" style="font-size:12.5px;margin-top:8px">${esc(f.interpretation || "")}</div></div>
      <div class="card"><div class="c-label">Coin News Sentiment</div>
        <div class="c-value ${d.avg_sentiment>0.1?'pos':d.avg_sentiment<-0.1?'neg':''}">${fmt(d.avg_sentiment,2)}</div>
        <div class="c-sub">${d.count} articles matched (${esc(d.coin)})</div></div>`;
    $("#nw-sentiment").textContent = d.count ? `${d.coin}: avg sentiment ${d.avg_sentiment}` : "";
    $("#nw-list").innerHTML = (d.items || []).map(newsItem).join("") || `<div class="muted">No news matched.</div>`;
    $("#nw-ann").innerHTML = (d.announcements || []).map(a =>
      `<div class="news-item"><a href="https://www.binance.com/en/support/announcement/${esc(String(a.code || ''))}" target="_blank" rel="noopener">${esc(a.title || "")}</a>
       <div class="news-meta"><span class="badge">Binance</span><span class="muted">${a.ts ? new Date(a.ts).toLocaleString() : ""}</span></div></div>`).join("")
      || `<div class="muted">Announcements unavailable (endpoint blocked in some regions).</div>`;
  } catch (e) { toast("News failed: " + e.message, "err"); }
}

/* ============================== TOOLS =============================== */
let toolsLoaded = false;
async function loadTools() {
  if (toolsLoaded) return;
  try {
    const d = await api("/api/tools");
    $("#tl-grid").innerHTML = d.tools.map(t => `
      <div class="tool-card" onclick="runTool('${t.name}', ${t.needs_symbol})">
        <div class="t-id">TOOL #${t.id}</div>
        <div class="t-name">${esc(t.display)}</div>
        <div class="t-sym">${t.needs_symbol ? "needs symbol ↑" : "market-wide"}</div>
      </div>`).join("");
    toolsLoaded = true;
  } catch (e) { toast("Tools list failed: " + e.message, "err"); }
}

window.runTool = async function (name, needsSymbol) {
  const sym = ($("#tl-symbol").value || "").trim();
  $("#tl-output-panel").style.display = "block";
  $("#tl-output-title").textContent = `Running: ${name} …`;
  $("#tl-output").textContent = "⏳ working…";
  try {
    const url = `/api/tools/run?name=${encodeURIComponent(name)}${needsSymbol && sym ? `&symbol=${encodeURIComponent(sym)}` : ""}`;
    const d = await api(url);
    $("#tl-output-title").textContent = `Result: ${d.display || name}`;
    $("#tl-output").innerHTML = renderToolOutput(d);
  } catch (e) {
    $("#tl-output").innerHTML = `<span class="neg">Error: ${esc(e.message)}</span>`;
  }
  $("#tl-output-panel").scrollIntoView({ behavior: "smooth" });
};

function renderToolOutput(d) {
  if (d.error) return `<span class="neg">${esc(d.error)}</span>`;
  const rows = [];
  const walk = (obj, prefix = "") => {
    for (const [k, v] of Object.entries(obj)) {
      if (["tool", "display", "elapsed_sec"].includes(k) && !prefix) continue;
      const key = prefix ? prefix + "." + k : k;
      if (v === null || v === undefined) continue;
      if (Array.isArray(v)) {
        if (!v.length) { rows.push(`<span class="muted">${esc(key)}: []</span>`); continue; }
        if (typeof v[0] === "object") {
          rows.push(`<b style="color:var(--yellow)">${esc(key)}:</b>`);
          v.slice(0, 30).forEach((it, i) => rows.push(`  <span class="muted">[${i}]</span> ` + inlineObj(it)));
        } else rows.push(`<b>${esc(key)}:</b> ${esc(v.join(", "))}`);
      } else if (typeof v === "object") {
        rows.push(`<b style="color:var(--yellow)">${esc(key)}:</b>`);
        walk(v, key);
      } else {
        rows.push(`<b>${esc(key)}:</b> ${typeof v === "string" && v.length > 90 ? `<div class="news-sum">${esc(v)}</div>` : esc(v)}`);
      }
    }
  };
  const inlineObj = (o) => Object.entries(o).filter(([k, v]) => v !== null && typeof v !== "object")
    .map(([k, v]) => `${esc(k)}=<b>${esc(typeof v === "number" ? fmt(v) : v)}</b>`).join(" · ");
  walk(d);
  return rows.join("\n");
}

/* ================================ AI ================================ */
async function loadAI() {
  try {
    const d = await api("/api/ai/status");
    let html = "";
    for (const p of d.providers) {
      html += `<div class="prov-card">
        <div class="prov-head">
          <span class="prov-name">${esc(p.name.toUpperCase())}</span>
          <span class="badge ${p.enabled ? "green" : ""}">${p.enabled ? "enabled" : "disabled"}</span>
          <span class="badge">${p.keys_configured} key(s)</span>
          ${p.key_preview && p.key_preview.length ? `<span class="muted">${p.key_preview.map(esc).join(" · ")}</span>` : ""}
          <button class="btn" onclick="testProv('${p.name}')">🔌 Test now</button>
          <span id="prov-test-${p.name}" class="muted"></span>
        </div>
        ${p.models.map(m => `<div class="model-row">
          <span class="m-id">${esc(m.id)}</span>
          <span class="badge ${m.cooling_down ? "red" : m.ok_calls ? "green" : ""}">${m.cooling_down ? `cooldown ${m.cooldown_left_sec}s` : m.ok_calls ? `ok×${m.ok_calls}` : "idle"}</span>
          ${m.fails ? `<span class="badge red">fails: ${m.fails}</span>` : ""}
        </div>`).join("") || `<div class="muted">no models configured</div>`}
      </div>`;
    }
    html += `<div class="prov-card" style="border-color:#1d4939">
      <div class="prov-head"><span class="prov-name" style="color:var(--green)">LOCAL BUILT-IN ENGINE</span>
      <span class="badge green">always on · always free</span></div>
      <div class="muted">${esc(d.local_engine.note)} If every cloud/local AI fails or runs out of tokens, this engine completes the signal from pure technical analysis — the app NEVER stops producing signals.</div>
    </div>`;
    $("#ai-providers").innerHTML = html;
  } catch (e) { $("#ai-providers").innerHTML = `<div class="panel neg">${esc(e.message)}</div>`; }
  try {
    const cfg = await api("/api/config");
    $("#ai-mode").value = cfg.ai.mode || "assist";
  } catch (e) { /* ignore */ }
}

window.testProv = async function (prov) {
  const el = $(`#prov-test-${prov}`);
  el.textContent = "testing…";
  try {
    const d = await api("/api/ai/test", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: prov }),
    });
    el.innerHTML = d.ok
      ? `<span class="pos">✔ ${esc(d.model)} responded in ${d.elapsed}s</span>`
      : `<span class="neg">✘ ${esc(d.error || "failed")}</span>`;
  } catch (e) { el.innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
  loadAI();
};

onq("#ai-refresh", "click", loadAI);
onq("#ai-save", "click", async () => {
  try {
    await api("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ai: { mode: $("#ai-mode").value } }),
    });
    toast("AI mode saved", "ok");
  } catch (e) { toast("Save failed: " + e.message, "err"); }
});
onq("#ai-cfg-load", "click", async () => {
  const prov = $("#ai-cfg-prov").value;
  const cfg = await api("/api/config");
  $("#ai-cfg-json").value = JSON.stringify(cfg.ai[prov] || {}, null, 2);
});
onq("#ai-cfg-save", "click", async () => {
  const prov = $("#ai-cfg-prov").value;
  try {
    const parsed = JSON.parse($("#ai-cfg-json").value);
    await api("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ai: { [prov]: parsed } }),
    });
    $("#ai-cfg-msg").textContent = "✔ saved to config.json";
    loadAI();
  } catch (e) { $("#ai-cfg-msg").innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
});

/* ------------------- multi-user access control ------------------- */
async function loadAccess() {
  try {
    const d = await api("/api/access");
    $("#ac-mode").value = d.mode || "open";
    $("#ac-max").value = d.max_users || 100;
    $("#ac-admins").value = (d.admins || []).join(", ");
    $("#ac-count").textContent = `${d.count}/${d.max_users}`;
    $("#ac-count").className = "badge " + (d.count >= d.max_users ? "red" : d.count ? "green" : "yellow");
    $("#ac-table tbody").innerHTML = (d.users || []).map((u, i) => `<tr>
      <td class="muted">${i + 1}</td>
      <td class="mono-sm">${esc(u.id)}</td>
      <td>${esc(u.note || "")}</td>
      <td class="muted">${u.added_at ? new Date(u.added_at * 1000).toLocaleDateString() : "—"}</td>
      <td><button class="btn btn-danger" onclick="accessRemove(${u.id})">✕</button></td>
    </tr>`).join("") || `<tr><td colspan="5" class="muted">No users added yet. In whitelist mode only admins can use the bot until you add IDs.</td></tr>`;
  } catch (e) { toast("Access load failed: " + e.message, "err"); }
}
window.accessRemove = async function (id) {
  if (!confirm(`Revoke access for ${id}?`)) return;
  try {
    await api("/api/access", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ action: "remove", id }) });
    loadAccess();
  } catch (e) { toast(e.message, "err"); }
};
onq("#ac-refresh", "click", loadAccess);
onq("#ac-mode-save", "click", async () => {
  await api("/api/access", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "set_mode", mode: $("#ac-mode").value }) });
  toast("Access mode saved: " + $("#ac-mode").value, "ok"); loadAccess();
});
onq("#ac-max-save", "click", async () => {
  await api("/api/access", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "set_max", max_users: parseInt($("#ac-max").value) || 100 }) });
  toast("Max users saved", "ok"); loadAccess();
});
onq("#ac-admins-save", "click", async () => {
  await api("/api/access", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "set_admins", admins: $("#ac-admins").value }) });
  toast("Admins saved", "ok"); loadAccess();
});
onq("#ac-add", "click", async () => {
  const id = parseInt(($("#ac-id").value || "").trim());
  if (!id) return toast("Enter a numeric Telegram ID", "err");
  try {
    await api("/api/access", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "add", id, note: ($("#ac-note").value || "").trim() }) });
    $("#ac-id").value = ""; $("#ac-note").value = "";
    loadAccess();
  } catch (e) { toast(e.message, "err"); }
});
onq("#ac-import", "click", async () => {
  const ids = ($("#ac-bulk").value || "").split(/[\s,;]+/).map(x => parseInt(x)).filter(n => !isNaN(n));
  if (!ids.length) return toast("Paste at least one numeric ID", "err");
  try {
    const r = await fetch("/api/access", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "add_many", ids }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "import failed");
    $("#ac-bulk").value = "";
    toast(`Imported ${d.count} total users`, "ok");
    loadAccess();
  } catch (e) { toast(e.message, "err"); }
});

/* =============================== BOT ================================ */
const BOT_COMMANDS = [
  "/start — welcome + overview", "/help — full command list", "/menu — 30-feature button menu (paginated)",
  "/signal <COIN> [tf] — AI signal for a chosen coin", "/random [tf] — best-of funnel: 1000→100→10→1 → signal",
  "/analyze <COIN> [tf] — full 8-strategy analysis + votes", "/chart <COIN> [tf] — PNG chart with indicators + buy/sell marks",
  "/price <COIN> — live price + funding + 24h stats", "/news [COIN] — fundamental news + sentiment",
  "/fear — Fear & Greed index", "/funding <COIN> — funding rate details", "/oi <COIN> — open interest + change",
  "/ls <COIN> — long/short ratios", "/trend <COIN> — multi-timeframe trend scan", "/sr <COIN> — support & resistance levels",
  "/fib <COIN> — Fibonacci + OTE zones", "/flow <COIN> — order flow / CVD / delta", "/liq <COIN> — estimated liquidity zones",
  "/breadth — market breadth regime", "/movers — top gainers & losers", "/spikes <COIN> — volume spikes",
  "/breakout <COIN> — Donchian breakout + squeeze", "/divergence <COIN> — RSI divergence", "/macd <COIN> — MACD state",
  "/supertrend <COIN> — SuperTrend status", "/ribbon <COIN> — EMA ribbon alignment", "/ichimoku <COIN> — cloud status",
  "/vwap <COIN> — VWAP deviation", "/size <entry> <sl> [balance] [risk%] — position size calculator",
  "/rr <entry> <sl> <tp> — risk/reward + breakeven win rate", "/liqprice <entry> <leverage> <long|short> — liquidation estimate",
  "/fundcost <COIN> [notional] [long|short] — funding cost", "/corr <COIN> — correlation vs BTC/ETH",
  "/volrank — volatility ranking", "/dominance — BTC/ETH volume dominance",
  "/journal [n] — signal history", "/backtest <COIN> [tf] — mini strategy backtest",
  "/aimode <assist|full|off> — switch AI mode", "/aistatus — provider/model health", "/aitest <provider> — live provider test",
  "/watch add|del|list <COIN> — watchlist", "/status — app & bot health",
];

async function loadBotTab() {
  $("#bt-commands").innerHTML = BOT_COMMANDS.map(c => `<div>▸ ${esc(c)}</div>`).join("");
  refreshBotLogs();
  loadAccess();
  try {
    const d = await api("/api/bot/status");
    setBotStatus(d);
    if (d.token_configured) $("#bt-token").placeholder = "token already saved (enter to replace)";
  } catch (e) { /* ignore */ }
}

async function refreshBotLogs() {
  try {
    const d = await api("/api/bot/logs");
    $("#bt-logs").innerHTML = (d.logs || []).map(l =>
      `<div class="pf-line">${new Date(l.ts * 1000).toLocaleTimeString()} — ${esc(l.msg)}</div>`).join("")
      || `<div class="muted">No bot logs yet.</div>`;
    const el = $("#bt-logs"); el.scrollTop = el.scrollHeight;
  } catch (e) { /* ignore */ }
}
setInterval(() => { if ($("#tab-bot").classList.contains("active")) refreshBotLogs(); }, 4000);
function setBotStatus(d) {
  $("#bt-status").innerHTML = d.running
    ? `<span class="badge green">● RUNNING — ${esc(d.detail || "")}</span>`
    : `<span class="badge ${d.status === "error" ? "red" : ""}">■ ${esc(d.status)} ${esc(d.detail || "")}</span>`;
}
onq("#bt-save", "click", async () => {
  const tok = $("#bt-token").value.trim();
  if (!tok) return toast("Paste a bot token first", "err");
  await api("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ telegram: { bot_token: tok, enabled: true } }),
  });
  toast("Bot token saved", "ok");
  loadBotTab();
});
onq("#bt-start", "click", async () => {
  try {
    const d = await api("/api/bot/start", { method: "POST" });
    setBotStatus({ running: d.ok, status: d.ok ? "running" : "error", detail: d.detail });
    toast(d.ok ? "Telegram bot started ✔" : "Bot start failed: " + d.detail, d.ok ? "ok" : "err");
  } catch (e) { toast("Bot start failed: " + e.message, "err"); }
});
onq("#bt-stop", "click", async () => {
  const d = await api("/api/bot/stop", { method: "POST" });
  setBotStatus({ running: false, status: "stopped", detail: d.detail });
  toast("Bot stopped");
});

/* ============================== BOOT ================================ */
(async function boot() {
  pollTopbar();
  loadDashboard();
  await loadMarkets();
  onq("#ch-symbol", "keydown", e => { if (e.key === "Enter") loadChart(); });
  onq("#sg-symbol", "keydown", e => { if (e.key === "Enter") runSignal(); });
  onq("#nw-coin", "keydown", e => { if (e.key === "Enter") loadNews(); });
  setInterval(() => { if (state.coins.length && $("#tab-markets").classList.contains("active")) loadMarkets(true); }, 60000);
})();
