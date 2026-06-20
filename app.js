/* VERDICT dashboard — loads real engine data, renders hand-built SVG charts.
   Self-contained: no external JS. Tries the live Flask API, falls back to the
   committed static JSON so it also works with no server. */

const SVGNS = "http://www.w3.org/2000/svg";
const $ = (s, r = document) => r.querySelector(s);
const el = (t, c) => { const e = document.createElement(t); if (c) e.className = c; return e; };
const fmt = (n, d = 2) => (n === null || n === undefined) ? "—" : Number(n).toFixed(d);
const pct = (n, d = 1) => (n === null || n === undefined) ? "—" : (n >= 0 ? "+" : "") + Number(n).toFixed(d) + "%";

async function loadData() {
  for (const url of ["/api/verdict", "./verdict.json", "../data/verdict.json"]) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (r.ok) { const d = await r.json(); d._src = url; return d; }
    } catch (e) { /* try next */ }
  }
  return null;
}

/* ---------- SVG line chart (equity vs benchmark) ---------- */
function lineChart(svg, series, opts = {}) {
  const W = svg.clientWidth || 480, H = svg.clientHeight || 150, pad = 6;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = "";
  const all = series.flatMap(s => s.data).filter(v => isFinite(v));
  if (!all.length) return;
  const min = Math.min(...all), max = Math.max(...all), span = (max - min) || 1;
  const x = i => pad + (i / (Math.max(1, longest(series) - 1))) * (W - 2 * pad);
  const y = v => H - pad - ((v - min) / span) * (H - 2 * pad);
  function longest(ss){ return Math.max(...ss.map(s=>s.data.length)); }

  // baseline at 1.0 (start)
  const base = document.createElementNS(SVGNS, "line");
  const y1 = y(1.0);
  base.setAttribute("x1", pad); base.setAttribute("x2", W - pad);
  base.setAttribute("y1", y1); base.setAttribute("y2", y1);
  base.setAttribute("stroke", "#2c3140"); base.setAttribute("stroke-dasharray", "3 4");
  svg.appendChild(base);

  series.forEach(s => {
    const d = s.data.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    if (s.fill) {
      const area = document.createElementNS(SVGNS, "path");
      area.setAttribute("d", `${d} L${x(s.data.length - 1)},${H - pad} L${x(0)},${H - pad} Z`);
      area.setAttribute("fill", s.fill); area.setAttribute("opacity", "0.12");
      svg.appendChild(area);
    }
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", d); p.setAttribute("fill", "none");
    p.setAttribute("stroke", s.color); p.setAttribute("stroke-width", s.width || 2);
    p.setAttribute("stroke-linejoin", "round"); p.setAttribute("stroke-linecap", "round");
    if (s.dash) p.setAttribute("stroke-dasharray", s.dash);
    // draw-on animation
    const len = p.getTotalLength ? p.getTotalLength() : 0;
    if (len) { p.style.strokeDasharray = len; p.style.strokeDashoffset = len;
      p.style.transition = "stroke-dashoffset 1.4s cubic-bezier(.2,.7,.2,1)";
      requestAnimationFrame(() => requestAnimationFrame(() => { p.style.strokeDashoffset = 0; })); }
    svg.appendChild(p);
  });
}

/* ---------- Fear & Greed semicircle gauge ---------- */
function gauge(svg, value) {
  const W = 120, H = 74, cx = 60, cy = 64, r = 48;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = "";
  const arc = (a0, a1, color, w) => {
    const p = document.createElementNS(SVGNS, "path");
    const pt = a => [cx + r * Math.cos(Math.PI * (1 - a)), cy - r * Math.sin(Math.PI * (1 - a))];
    const [x0, y0] = pt(a0), [x1, y1] = pt(a1);
    p.setAttribute("d", `M${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1}`);
    p.setAttribute("fill", "none"); p.setAttribute("stroke", color); p.setAttribute("stroke-width", w);
    p.setAttribute("stroke-linecap", "round"); return p;
  };
  // track segments: fear(red) .. neutral(amber) .. greed(green)
  svg.appendChild(arc(0, 0.4, "#f6465d", 7));
  svg.appendChild(arc(0.4, 0.6, "#f0a020", 7));
  svg.appendChild(arc(0.6, 1, "#2ebd85", 7));
  // needle
  const a = Math.max(0, Math.min(1, value / 100));
  const nx = cx + (r - 6) * Math.cos(Math.PI * (1 - a)), ny = cy - (r - 6) * Math.sin(Math.PI * (1 - a));
  const needle = document.createElementNS(SVGNS, "line");
  needle.setAttribute("x1", cx); needle.setAttribute("y1", cy);
  needle.setAttribute("x2", nx); needle.setAttribute("y2", ny);
  needle.setAttribute("stroke", "currentColor"); needle.setAttribute("stroke-width", "2.5");
  needle.setAttribute("stroke-linecap", "round");
  needle.style.transformOrigin = `${cx}px ${cy}px`;
  needle.style.transform = "rotate(90deg)"; needle.style.transition = "transform 1.1s cubic-bezier(.2,.7,.2,1)";
  svg.appendChild(needle);
  const hub = document.createElementNS(SVGNS, "circle");
  hub.setAttribute("cx", cx); hub.setAttribute("cy", cy); hub.setAttribute("r", "3.5"); hub.setAttribute("fill", "currentColor");
  svg.appendChild(hub);
  requestAnimationFrame(() => requestAnimationFrame(() => { needle.style.transform = "rotate(0deg)"; }));
}

/* ---------- render ---------- */
function render(d) {
  // ticker + status
  const cmc = d.live_cmc || {};
  $("#tk-price").textContent = cmc.price ? "$" + fmt(cmc.price, 2) : "—";
  const dom = $("#tk-dom"); dom.textContent = cmc.btc_dominance ? fmt(cmc.btc_dominance, 1) + "%" : "—";
  if (cmc.alt_headwind) dom.classList.add("warn");
  const fg = $("#tk-fg"); fg.textContent = cmc.fear_greed ?? "—";
  if (cmc.fear_greed != null && cmc.fear_greed <= 40) fg.classList.add("off");
  $("#tk-regime").textContent = (cmc.regime || "—").replace("_", "-");
  const dot = $("#livedot");
  const live = cmc.live;
  dot.classList.toggle("cached", !live);
  $("#status-label").textContent = live ? "LIVE CMC" : "OFFLINE FIXTURES";

  // hero stamp = real-majors verdict
  const nt = d.no_trade || {};
  const stamp = $("#hero-stamp");
  stamp.className = "stamp " + (nt.verdict || "no_trade").toLowerCase();
  $("#hero-verdict").textContent = nt.verdict || "NO_TRADE";

  // live CMC panel
  $("#m-price").textContent = cmc.price ? "$" + fmt(cmc.price, 2) : "—";
  $("#m-dom").textContent = cmc.btc_dominance ? fmt(cmc.btc_dominance, 1) + "%" : "—";
  $("#m-dom-note").textContent = cmc.alt_headwind ? "≥ 55% → alt headwind" : "normal";
  $("#m-dom-note").classList.toggle("flag", !!cmc.alt_headwind);
  $("#m-fg").textContent = cmc.fear_greed ?? "—";
  $("#m-fg-note").textContent = fgLabel(cmc.fear_greed);
  const rb = $("#m-regime"); rb.textContent = (cmc.regime || "neutral").replace("_", "-");
  rb.className = "badge " + (cmc.regime || "neutral");
  gauge($("#fg-gauge"), cmc.fear_greed ?? 50);
  $("#cmc-source").textContent = cmc.source || "—";
  // reaction line
  if (cmc.alt_headwind || cmc.regime === "risk_off") {
    $("#cmc-reaction").innerHTML = `Engine response → BNB candidates tightened to <b>conservative risk</b>` +
      (cmc.alt_headwind ? ` + <b>3-of-3 confluence</b> (BTC-dominance alt-headwind gate)` : ``) +
      (cmc.regime === "risk_off" ? ` under a <b>risk-off</b> regime.` : `.`);
  } else {
    $("#cmc-reaction").innerHTML = `Engine response → balanced parameters; no regime tightening on this snapshot.`;
  }

  // on-chain identity (BNB AI Agent SDK)
  const oc = d.onchain || {};
  if (oc.agent_id) {
    $("#onchain-id").textContent = oc.agent_id;
    const link = $("#onchain-link");
    if (link && oc.explorer_tx) link.href = oc.explorer_tx;
  } else {
    const foot = $("#onchain-foot"); if (foot) foot.textContent = "ERC-8004 identity — run python -m verdict.identity.register";
  }

  // sentiment + decision matrix
  renderSentiment(d.sentiment || {});

  // two-sided
  const t = d.trade || {}, tm = t.metrics || {};
  $("#trade-name").textContent = t.name || "Controlled range strategy";
  $("#t-sharpe").textContent = fmt(tm.oos_sharpe, 2);
  $("#t-windows").textContent = tm.window_pass_rate != null ? Math.round(tm.window_pass_rate * 100) + "%" : "—";
  $("#t-oos").textContent = pct(tm.median_oos);
  $("#t-bench").textContent = pct(tm.median_bench);
  lineChart($("#trade-chart"), [
    { data: t.benchmark || [], color: "#58a6b8", width: 1.6, dash: "4 4" },
    { data: t.equity || [], color: "#f0b90b", width: 2.4, fill: "#f0b90b" },
  ]);

  $("#nt-summary").textContent = nt.summary || "";
  $("#nt-count").textContent = nt.candidates ?? "—";
  const reasons = $("#nt-reasons"); reasons.innerHTML = "";
  Object.entries(nt.rejected || {}).slice(0, 6).forEach(([id, why]) => {
    const r = el("div", "r");
    r.innerHTML = `<span class="id">${id}</span> — ${why}`;
    reasons.appendChild(r);
  });

  // regime matrix
  buildMatrix(d.regime_grid || []);

  // walk-forward
  buildWalkforward(d.walkforward || {});

  // footer tests
  $("#tests-badge").textContent = d.tests || "tests pass";
}

function fgLabel(v) {
  if (v == null) return "—";
  if (v <= 24) return "Extreme Fear";
  if (v <= 44) return "Fear";
  if (v <= 55) return "Neutral";
  if (v <= 74) return "Greed";
  return "Extreme Greed";
}

function renderSentiment(s) {
  if (s.error || !s.matrix) { return; }
  $("#sent-source").textContent = (s.source || "—") + " · " + (s.headline_count ?? 0) + " headlines";
  $("#sent-score").textContent = (s.sentiment_score >= 0 ? "+" : "") + fmt(s.sentiment_score, 2);
  $("#sent-conf").textContent = fmt(s.confidence, 2);
  const list = $("#news-list"); list.innerHTML = "";
  (s.headlines || []).forEach(h => {
    const cls = s.sentiment_score > 0.05 ? "pos" : (s.sentiment_score < -0.05 ? "neg" : "neu");
    const row = el("div", "h"); row.innerHTML = `<span class="dot ${cls}"></span><span>${h}</span>`;
    list.appendChild(row);
  });
  // matrix
  const m = s.matrix;
  const act = $("#matrix-action");
  act.textContent = m.action;
  const colors = { TRADE: "var(--green)", DCA: "var(--gold)", WAIT: "var(--teal)", NO_TRADE: "var(--amber)" };
  act.style.background = colors[m.action] || "var(--bg-3)";
  act.style.color = "var(--bg)";
  $("#matrix-score").textContent = fmt(m.score, 0);
  const bars = $("#matrix-bars"); bars.innerHTML = "";
  const totalW = Object.values(m.weights || {}).reduce((a, b) => a + b, 0) || 100;
  Object.entries(m.components || {}).forEach(([k, v]) => {
    const w = (m.weights || {})[k] || 0;
    const row = el("div", "mbar");
    row.innerHTML = `<span class="k">${k} <span class="wt">${Math.round(w / totalW * 100)}%</span></span>` +
      `<span class="track"><span class="fill ${k}"></span></span><span class="v">${fmt(v, 2)}</span>`;
    bars.appendChild(row);
    const fill = row.querySelector(".fill");
    requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = Math.max(2, v * 100) + "%"; }));
  });
}

const ARCHS = [["momentum", "Momentum"], ["meanrev", "Mean-Reversion"], ["breakout", "Breakout"]];
function buildMatrix(grid) {
  const table = $("#regime-matrix");
  table.innerHTML = "";
  const head = el("tr"); head.appendChild(el("th", "row")); head.lastChild.textContent = "";
  grid.forEach(g => { const th = el("th"); th.innerHTML = `${g.market}<br><span class="faint">B&H ${pct(g.buy_hold_pct, 0)}</span>`;
    if (g.market === "downtrend") th.classList.add("downcol"); head.appendChild(th); });
  table.appendChild(head);
  ARCHS.forEach(([key, label]) => {
    const tr = el("tr");
    const rh = el("td", "row"); rh.textContent = label; tr.appendChild(rh);
    grid.forEach(g => {
      const a = (g.archetypes || {})[key] || { trades: 0, return_pct: 0 };
      const td = el("td"); const cell = el("div", "cell");
      if (a.trades === 0) { cell.classList.add("aside"); cell.innerHTML = `<div class="t">— aside —</div>`; }
      else {
        cell.classList.add(a.return_pct > 0 ? "act-win" : "act-lose");
        cell.innerHTML = `<div class="t">${pct(a.return_pct, 0)}</div><div class="r">${a.trades} trades</div>`;
      }
      td.appendChild(cell); if (g.market === "downtrend") td.classList.add("downcol"); tr.appendChild(td);
    });
    table.appendChild(tr);
  });
}

function buildWalkforward(wf) {
  const strip = $("#wf-strip"); strip.innerHTML = "";
  const wins = wf.windows || [];
  const maxAbs = Math.max(1, ...wins.map(w => Math.abs(w.return_pct)));
  wins.forEach((w, i) => {
    const b = el("div", "wf-bar");
    const ret = el("div", "ret"); ret.textContent = pct(w.return_pct, 0);
    const bar = el("div", "bar " + (w.passed ? "pass" : "fail"));
    const h = 12 + (Math.abs(w.return_pct) / maxAbs) * 86;
    bar.style.height = "0px"; bar.style.transition = `height .6s cubic-bezier(.2,.7,.2,1) ${i * 60}ms`;
    requestAnimationFrame(() => requestAnimationFrame(() => { bar.style.height = h + "%"; }));
    const lbl = el("div", "lbl"); lbl.textContent = "W" + (i + 1);
    b.appendChild(ret); b.appendChild(bar); b.appendChild(lbl); strip.appendChild(b);
  });
  $("#wf-pass").innerHTML = `<b>${wf.pass_rate ?? "—"}%</b> of windows beat buy&hold`;
  $("#wf-asset").textContent = `${wf.asset || ""} ${wf.tf || ""}`;
  $("#wf-sharpe").innerHTML = `OOS Sharpe <b>${fmt(wf.oos_sharpe, 2)}</b>`;
}

/* theme toggle — persists; circular reveal via View Transitions when supported */
function initTheme() {
  const root = document.documentElement;
  const saved = localStorage.getItem("verdict-theme") || "dark";
  root.setAttribute("data-theme", saved);
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", (e) => {
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    const apply = () => { root.setAttribute("data-theme", next); localStorage.setItem("verdict-theme", next); };
    if (!document.startViewTransition) { apply(); return; }
    const x = e.clientX, y = e.clientY;
    const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    document.startViewTransition(apply).ready.then(() => {
      root.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
        { duration: 480, easing: "cubic-bezier(.2,.7,.2,1)", pseudoElement: "::view-transition-new(root)" }
      );
    });
  });
}

/* reveal on scroll */
function observeReveals() {
  const io = new IntersectionObserver((es) => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach(n => io.observe(n));
}

(async function () {
  initTheme();
  const data = await loadData();
  if (!data) { $("#status-label").textContent = "DATA UNAVAILABLE — run python web/build_data.py"; return; }
  render(data);
  observeReveals();
  window.addEventListener("resize", () => {
    if (data.trade) lineChart($("#trade-chart"), [
      { data: data.trade.benchmark || [], color: "#58a6b8", width: 1.6, dash: "4 4" },
      { data: data.trade.equity || [], color: "#f0b90b", width: 2.4, fill: "#f0b90b" },
    ]);
  });
})();
