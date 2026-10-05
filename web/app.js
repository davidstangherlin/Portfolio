"use strict";
/* ASX Value Screener GUI. Plain JavaScript, no build step, no external
   libraries: every chart is drawn as inline SVG so the page works offline
   and on a phone. Data comes from gui.py's /api endpoints. */

const app = document.getElementById("app");
const tip = document.getElementById("tooltip");
const SVG_NS = "http://www.w3.org/2000/svg";

const ACTION_STATUS = {
  BUY: "good", ACCUMULATE: "good", INVESTIGATE: "warning", WATCH: "neutral", HOLD: "neutral",
  REVIEW: "serious", SELL: "critical", AVOID: "critical", IGNORE: "neutral",
};
const PAGE_SIZE = 100;

const state = {
  q: "", sector: "", actions: new Set(), passing: false, held: false, watchlist: "",
  sort: { key: "action", dir: "asc" }, shown: PAGE_SIZE,
};
const cache = { screener: null, thresholds: null, status: null, portfolios: null };

/* ---------- DOM helpers (text always via textContent) ---------- */
function setAttrs(el, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
}
function add(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
}
function h(tag, attrs, ...children) { const el = document.createElement(tag); setAttrs(el, attrs); add(el, children); return el; }
function s(tag, attrs, ...children) { const el = document.createElementNS(SVG_NS, tag); setAttrs(el, attrs); add(el, children); return el; }

/* ---------- formatting ---------- */
const NA = "n/a";
const fmt = (v, dp = 2) => (v === null || v === undefined ? NA :
  new Intl.NumberFormat("en-AU", { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(v));
const pct = (v, dp = 1) => (v === null || v === undefined ? NA : fmt(v, dp) + "%");
const money = (v, dp = 2) => (v === null || v === undefined ? NA : (v < 0 ? "-$" : "$") + fmt(Math.abs(v), dp));
function compact(v) {
  if (v === null || v === undefined) return NA;
  const body = new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 1 }).format(Math.abs(v));
  return (v < 0 ? "-$" : "$") + body;
}
const toDate = (iso) => new Date(iso + "T00:00:00");
const dayMonth = (iso) => toDate(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
const monthYear = (iso) => toDate(iso).toLocaleDateString("en-AU", { month: "short", year: "2-digit" });
const longDate = (iso) => toDate(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
const sum = (xs) => xs.reduce((a, b) => a + b, 0);

/* ---------- tooltip ---------- */
function showTip(evt, nodes) {
  tip.replaceChildren(...nodes);
  tip.hidden = false;
  const pad = 14;
  const { innerWidth: vw, innerHeight: vh } = window;
  const r = tip.getBoundingClientRect();
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + r.width > vw - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > vh - 8) y = evt.clientY - r.height - pad;
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = Math.max(8, y) + "px";
}
const hideTip = () => { tip.hidden = true; };
const tipRow = (value, label, color) =>
  h("div", { class: "t-row" }, color ? h("span", { class: "t-key", style: `background:var(${color})` }) : null,
    h("strong", { text: value }), h("span", { text: label }));

/* ---------- field explanations (hover, keyboard focus, or tap the "i") ---------- */
const DEFAULT_THRESHOLDS = { margin_of_safety: 20, roe: 12, debt_to_equity: 0.8, yield: 4.5 };
const thresholds = () => (cache.screener && cache.screener.thresholds) || cache.thresholds || DEFAULT_THRESHOLDS;
const FIELD_HELP = {
  "Score": () => "Score wheel total out of 30. Five spokes (Value, Performance, Health, Dividend, Momentum), each counting six yes/no checks. Higher is better. Open a company to see every check.",
  "Company": () => "ASX code and company name. HELD marks shares you own.",
  "Sector": () => "Industry sector from Yahoo Finance. Financial Services and Real Estate are valued with a dividend discount model; every other sector with a discounted cash flow model.",
  "Price": () => "Latest closing share price on the ASX.",
  "Margin of safety": (t) => `How far the price sits below estimated intrinsic value: (value - price) / value. Positive means cheaper than estimated value; negative means dearer. Passes the value test above ${t.margin_of_safety}%.`,
  "ROE": (t) => `Return on equity: net profit after tax / shareholders' equity. How well the company earns on its owners' money. Passes the value test above ${t.roe}%.`,
  "Debt/equity": (t) => `Total debt / shareholders' equity. Lower means less financial risk. Passes the value test below ${fmt(t.debt_to_equity, 2)}.`,
  "Yield (grossed up)": (t) => `Dividend yield including franking credits: cash dividend x (1 + franking % x 30/70) / price. Companies based outside Australia are treated as unfranked. Passes the value test above ${t.yield}%. Ordinary dividends only: a one-off payment more than twice the usual annual dividend is excluded.`,
  "Grossed-up yield": (t) => `Dividend yield including franking credits: cash dividend x (1 + franking % x 30/70) / price. Companies based outside Australia are treated as unfranked. Passes the value test above ${t.yield}%. Ordinary dividends only: a one-off payment more than twice the usual annual dividend is excluded.`,
  "Value tests": () => "The four core value tests, in order: margin of safety, ROE, debt/equity, grossed-up yield. A tick passes; a cross fails or has no data. All four must pass for an overall pass.",
  "Action": () => "Suggested next step from the rules; the reason is on the company page. Shares you don't hold: BUY, INVESTIGATE, WATCH, AVOID, IGNORE. Shares you hold: SELL, REVIEW, ACCUMULATE, HOLD. A research prompt, not financial advice.",
  "Earnings quality": () => "Operating cash flow / net profit over the last three years. STRONG at 100% or more, ADEQUATE 80% to 99%, WEAK below 80%. Profit that isn't turning into cash is a warning sign. Not assessed for banks, insurers and REITs.",
  "Price signal": () => "Price trend. UPTREND: at or above the 200-day average. DOWNTREND: below it. NEW LOWS: below it and in the bottom 10% of the 52-week range. Needs 200 days of prices.",
  "Dividend trend": () => "Over up to five years. CUT: the latest dividend is more than 10% below last year's or the earlier median. GROWING: more than 5% above the oldest. STEADY otherwise. NONE: pays no dividend. Ordinary dividends only: a one-off payment more than twice the usual annual dividend is excluded.",
  "Fundamentals trend": () => "Latest versus oldest of the last three annual reports. DECLINING: ROE down more than 2 points or revenue down more than 5%. IMPROVING: up by those amounts. STABLE otherwise. Ignores the share price.",
  "Margin of safety trend": () => "Change in margin of safety over the last 30 days, in percentage points. Positive means the share is getting cheaper relative to its estimated value. More than 5 points counts as momentum.",
  "Value-trap risk": () => "Yes when the margin of safety passes but fundamentals are DECLINING: the share looks cheap, possibly for a good reason.",
  "Data confidence": () => "How complete the inputs are, from 11 checks (price, market capitalisation, profit, revenue, equity, debt, cash flows, years of reports, days of prices). HIGH: 10 or 11. MEDIUM: 8 or 9. LOW: 7 or fewer.",
  "P/E": () => "Price-to-earnings ratio: share price / earnings per share. Lower can mean cheaper. Graham's ceiling was 15.",
  "P/B": () => "Price-to-book ratio: share price / book value (equity) per share. Graham's ceiling was 1.5.",
  "Price to free cash flow": () => "Share price / free cash flow per share, latest year. Lower means more cash generated for each dollar paid.",
  "EV/EBIT": () => "Enterprise value (market capitalisation + debt - cash) / earnings before interest and tax. Compares companies regardless of how they are funded.",
  "ROIC": () => "Return on invested capital: net profit / (debt + equity - cash). The return on all the capital the business uses, not just shareholders' money.",
  "Cash dividend yield": () => "Cash dividend / share price, before franking credits. Ordinary dividends only: a one-off payment more than twice the usual annual dividend is excluded.",
  "Payout ratio": () => "Dividend / earnings per share. Above 100% the dividend exceeds profit; above 150% it is flagged as a likely one-off. Ordinary dividends only: a one-off payment more than twice the usual annual dividend is excluded.",
  "Country": () => "Country of domicile from Yahoo Finance. Companies outside Australia are treated as paying no franking credits.",
  "Accounts currency": () => "The currency the company publishes its financial statements in. Statements in another currency (US dollars for most large miners, New Zealand dollars for NZ listings) are converted into the share price's currency at the exchange rate on each report's balance date, so earnings, book value, cash flow and every ratio built on them compare like with like. Dividends are already in the share price's currency and are not converted.",
  "Valuation": (t) => `Where the price sits against estimated value. Undervalued: margin of safety above ${t.margin_of_safety}% (passes the value test). Fair value: 0% to ${t.margin_of_safety}%. Overvalued: below 0%, so the price is above estimated value. No estimate: no valuation model could run.`,
  "Implied upside": () => "How much the price would rise to reach estimated value: (value - price) / price. Not the same as margin of safety, which divides by value: a 40% margin of safety is a 67% implied upside.",
  "Estimated value": () => "Intrinsic value per share from the company's valuation model. Hover the bar label in the chart below for the model's full assumptions.",
  "Share price": () => "Latest closing price on the ASX. The further it sits below the estimated value, the larger the margin of safety.",
  "Portfolio value": () => "Units held x latest closing price, across every open parcel recorded with portfolio.py.",
  "Today": () => "Change in the portfolio's value from the previous close to the latest close. Blank until two days of prices are stored.",
  "Unrealised gain": () => "Portfolio value less the cost base (purchase price plus brokerage) of the shares still held. Before tax; no CGT discount applied.",
  "Cost base": () => "What the shares still held cost: purchase price plus brokerage, the starting point for capital gains tax (CGT).",
  "CGT discount from": () => "The first date a sale qualifies for the capital gains tax (CGT) discount: the day after the parcel has been held for 12 months.",
  "Graham Number": () => "Benjamin Graham's ceiling on what a defensive investor should pay: the square root of 22.5 x earnings per share x book value per share. 22.5 is his maximum P/E of 15 times his maximum P/B of 1.5, so a price below it means both limits are met at once. Uses the latest annual report; blank if earnings or book value is negative. One of the score wheel's Value checks, but not used in the four value tests or the action. It ignores growth, so it understates companies with few physical assets.",
};
const ESTIMATED_VALUE_HELP = {
  DCF: "Intrinsic value per share from a two-stage discounted cash flow (DCF) model: average free cash flow over the last three years, grown at 8% a year for five years and 2.5% a year after that, discounted back at 9% a year. Cash is added and debt subtracted, then the total is divided by shares on issue. This is the figure the margin of safety and the value test use.",
  DDM: "Intrinsic value per share from a two-stage dividend discount model (DDM), used for banks, insurers and REITs because their free cash flow isn't meaningful: average dividend per share over the last three years, grown at 5% a year for five years and 2.5% a year after that, discounted back at 9% a year. This is the figure the margin of safety and the value test use.",
};

function placeTipBelow(el, nodes) {
  const r = el.getBoundingClientRect();
  showTip({ clientX: r.left, clientY: r.bottom }, nodes);
}

const helpNodes = (label, text) => () => [h("div", { class: "t-title", text: label }), h("div", { text: text(thresholds()) })];

function bindHelp(el, nodes) {
  el.addEventListener("pointermove", (e) => { if (e.pointerType !== "touch") showTip(e, nodes()); });
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => placeTipBelow(el, nodes()));
  el.addEventListener("blur", hideTip);
}

/* Adds an explanation to a heading or label: shown on mouse hover and
   keyboard focus, and via a small "i" button for touch screens. */
function withHelp(el, label, text = FIELD_HELP[label]) {
  if (!text) return el;
  const nodes = helpNodes(label, text);
  el.classList.add("has-help");
  bindHelp(el, nodes);
  const info = h("button", { type: "button", class: "info", "aria-label": `What is ${label}?`, text: "i" });
  info.addEventListener("click", (e) => { e.stopPropagation(); placeTipBelow(info, nodes()); });
  info.addEventListener("keydown", (e) => e.stopPropagation()); // Enter on the "i" shouldn't sort the column
  el.append(info);
  return el;
}

/* The same for a label drawn inside an SVG chart, where an HTML button
   can't go: the "i" for touch screens is an SVG circle at (ix, iy). */
function svgLabelHelp(textEl, label, text, ix, iy) {
  if (!text) return textEl;
  const nodes = helpNodes(label, text);
  textEl.classList.add("has-help");
  const g = s("g", { tabindex: 0, "aria-label": `${label}: ${text(thresholds())}` }, textEl);
  bindHelp(g, nodes);
  const info = s("g", { class: "info-svg", role: "button", "aria-label": `What is ${label}?` },
    s("circle", { cx: ix, cy: iy, r: 7.5 }), s("text", { x: ix, y: iy + 3.5, "text-anchor": "middle", text: "i" }));
  info.addEventListener("click", (e) => { e.stopPropagation(); placeTipBelow(info, nodes()); });
  g.append(info);
  return g;
}
document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".info, .info-svg")) hideTip(); });

/* ---------- data ---------- */
async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

/* ---------- shared pieces ---------- */
/* Valuation status from margin of safety, using the live value-test threshold. */
function valuationStatus(mos) {
  if (mos === null || mos === undefined) return { cls: "none", label: "No estimate" };
  if (mos > thresholds().margin_of_safety) return { cls: "under", label: "Undervalued" };
  if (mos >= 0) return { cls: "fair", label: "Fair value" };
  return { cls: "over", label: "Overvalued" };
}
function valuationPill(mos, large = false) {
  const st = valuationStatus(mos);
  return h("span", { class: `pill ${st.cls}${large ? " lg" : ""}`, text: st.label });
}
const signClass = (v) => (v === null || v === undefined || v === 0 ? null : v > 0 ? "pos" : "neg");
function badge(action) {
  return h("span", { class: `badge ${ACTION_STATUS[action] || "neutral"}`, text: action });
}
function ynMarks(row) {
  const tests = [["mos_ok", "Margin of safety"], ["roe_ok", "ROE"], ["de_ok", "Debt/equity"], ["yield_ok", "Yield"]];
  return h("span", { class: "tests" }, tests.map(([k, label]) => {
    const pass = row[k] === "Y";
    return h("span", { class: `yn ${pass ? "y" : "n"}`, title: `${label}: ${pass ? "pass" : "fail"}`,
      "aria-label": `${label} ${pass ? "passes" : "fails"}`, text: pass ? "✓" : "✕" });
  }));
}

/* Score wheel: five spokes, each a count of six yes/no checks. */
function wheel(scores, axes, max, { size = 300, labels = true, details = null } = {}) {
  const n = axes.length, c = size / 2, R = labels ? size * 0.34 : size / 2 - 2;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const pt = (i, frac) => [c + R * frac * Math.cos(angle(i)), c + R * frac * Math.sin(angle(i))];
  const poly = (frac) => axes.map((_, i) => pt(i, frac).join(",")).join(" ");
  const total = sum(scores);
  const padX = labels ? 80 : 0, padY = labels ? 24 : 0;
  const svg = s("svg", {
    viewBox: `${-padX} ${-padY} ${size + padX * 2} ${size + padY * 2}`, width: size + padX * 2, height: size + padY * 2,
    class: labels ? "chart wheel" : "mini-wheel", role: "img",
    "aria-label": `Score ${total} of ${max * n}: ` + axes.map((a, i) => `${a} ${scores[i]} of ${max}`).join(", "),
  });
  if (!labels) svg.append(s("title", { text: axes.map((a, i) => `${a} ${scores[i]}/${max}`).join("  |  ") }));
  for (const frac of labels ? [1 / 3, 2 / 3, 1] : [1]) {
    svg.append(s("polygon", { points: poly(frac), fill: "none", stroke: "var(--grid)", "stroke-width": 1 }));
  }
  if (labels) axes.forEach((_, i) => {
    const [x, y] = pt(i, 1);
    svg.append(s("line", { x1: c, y1: c, x2: x, y2: y, stroke: "var(--grid)", "stroke-width": 1 }));
  });
  const data = scores.map((v, i) => pt(i, Math.max(v, 0.15) / max).join(",")).join(" ");
  svg.append(s("polygon", { points: data, fill: "var(--s1)", "fill-opacity": 0.18, stroke: "var(--s1)",
    "stroke-width": labels ? 2 : 1.5, "stroke-linejoin": "round" }));
  if (!labels) return svg;

  axes.forEach((axis, i) => {
    const [dx, dy] = pt(i, scores[i] / max || 0.0001);
    svg.append(s("circle", { cx: dx, cy: dy, r: 4, fill: "var(--s1)", stroke: "var(--surface)", "stroke-width": 2 }));
    const [lx, ly] = pt(i, 1.28);
    const cos = Math.cos(angle(i));
    const anchor = Math.abs(cos) < 0.2 ? "middle" : cos > 0 ? "start" : "end";
    const g = s("g", { tabindex: 0, style: "cursor:default" },
      s("text", { x: lx, y: ly - 2, "text-anchor": anchor, style: "fill:var(--ink);font-size:13px;font-weight:600", text: axis }),
      s("text", { x: lx, y: ly + 13, "text-anchor": anchor, style: "fill:var(--ink-2);font-size:12px", text: `${scores[i]} / ${max}` }));
    if (details) {
      const nodes = () => [h("div", { class: "t-head", text: axis }),
        ...details[axis].checks.map((ch) => h("div", { text: `${ch.passed === true ? "✓" : ch.passed === false ? "✕" : "–"} ${ch.label}` }))];
      g.addEventListener("pointermove", (e) => showTip(e, nodes()));
      g.addEventListener("pointerleave", hideTip);
    }
    svg.append(g);
  });
  return svg;
}

function niceTicks(min, max, count = 4) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
  return { lo, hi, ticks };
}

function legend(series, rect = false, extras = []) {
  if (series.length < 2 && !extras.length) return null;
  return h("div", { class: "legend" },
    series.map((sr) => h("span", {}, h("span", { class: `key${rect ? " rect" : ""}`, style: `background:var(${sr.color})` }), sr.name)),
    extras.map((x) => h("span", {}, h("span", { class: `dkey${x.outline ? " outline" : ""}`, "aria-hidden": "true", text: x.symbol }), x.name)));
}

/* Ex-dividend dates on the price chart: each lands on the first trading
   day on or after it (ex-dates can fall on a non-trading day). */
function dividendMarkers(prices, dividends) {
  return dividends.map((dv) => {
    const at = prices.find((p) => p[0] >= dv.ex_date) || prices[prices.length - 1];
    return { ...dv, date: at[0] };
  }).filter((dv) => dv.ex_date >= prices[0][0]);
}
const dividendText = (dv) => `${money(dv.amount, 3)} per share${dv.abnormal ? ", one-off (excluded from dividend figures)" : ""}`;

function tableView(headers, rows) {
  return h("details", { class: "table-view" }, h("summary", { text: "Show data table" }),
    h("div", { class: "table-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, headers.map((x, i) => h("th", { class: i ? "num" : null, text: x })))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((v, i) => h("td", { class: i ? "num" : null, text: v }))))))));
}

/* Line chart with crosshair tooltip. series: [{name, color, points:[[iso, value]]}] */
function lineChart({ series, yFmt, height = 220, zeroLine = false, label, width = 640, markers = [] }) {
  const W = width, H = height, m = { l: 52, r: 14, t: 10, b: 24 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const base = series[0].points;
  const xs = base.map((p) => toDate(p[0]).getTime());
  const x0 = xs[0], x1 = xs[xs.length - 1] === x0 ? x0 + 1 : xs[xs.length - 1];
  const values = series.flatMap((sr) => sr.points.map((p) => p[1]));
  if (zeroLine) values.push(0);
  const { lo, hi, ticks } = niceTicks(Math.min(...values), Math.max(...values));
  const X = (t) => m.l + ((t - x0) / (x1 - x0)) * pw;
  const Y = (v) => m.t + ph - ((v - lo) / (hi - lo)) * ph;

  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": label });
  for (const t of ticks) {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 && zeroLine ? "zero-line" : "grid-line" }));
    svg.append(s("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end", text: yFmt(t) }));
  }
  const nLabels = Math.min(5, base.length);
  for (let k = 0; k < nLabels; k++) {
    const idx = Math.round((k * (base.length - 1)) / Math.max(1, nLabels - 1));
    svg.append(s("text", { x: X(xs[idx]), y: H - 6, "text-anchor": k === 0 ? "start" : k === nLabels - 1 ? "end" : "middle",
      text: base.length > 60 ? monthYear(base[idx][0]) : dayMonth(base[idx][0]) }));
  }
  const lookups = series.map((sr) => new Map(sr.points.map((p) => [p[0], p[1]])));
  series.forEach((sr) => {
    if (!sr.points.length) return;
    const d = sr.points.map((p, i) => `${i ? "L" : "M"}${X(toDate(p[0]).getTime()).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    svg.append(s("path", { d, fill: "none", stroke: `var(${sr.color})`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = sr.points[sr.points.length - 1];
    svg.append(s("circle", { cx: X(toDate(last[0]).getTime()), cy: Y(last[1]), r: 4, fill: `var(${sr.color})`, stroke: "var(--surface)", "stroke-width": 2 }));
  });
  const cross = s("line", { y1: m.t, y2: m.t + ph, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
  svg.append(cross);
  const hit = s("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" });
  hit.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const t = x0 + ((((e.clientX - box.left) / box.width) * W - m.l) / pw) * (x1 - x0);
    let i = 0, best = Infinity;
    xs.forEach((x, k) => { const dd = Math.abs(x - t); if (dd < best) { best = dd; i = k; } });
    const iso = base[i][0];
    cross.setAttribute("x1", X(xs[i])); cross.setAttribute("x2", X(xs[i])); cross.setAttribute("visibility", "visible");
    showTip(e, [h("div", { class: "t-head", text: longDate(iso) }),
      ...series.map((sr, k) => lookups[k].has(iso) ? tipRow(yFmt(lookups[k].get(iso)), sr.name, sr.color) : null).filter(Boolean),
      ...markers.filter((mk) => mk.date === iso).map((mk) => h("div", { class: "t-row" }, h("span", { class: "dkey sm", text: "D" }), h("span", { text: `Dividend ${dividendText(mk)}` })))]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(hit);
  // Dividend markers sit on the first series' line, above the hover layer so they can be hovered themselves.
  for (const mk of markers) {
    if (!lookups[0].has(mk.date)) continue;
    const cx = X(toDate(mk.date).getTime()), cy = Y(lookups[0].get(mk.date));
    const g = s("g", { class: `div-marker${mk.abnormal ? " abnormal" : ""}`, tabindex: 0,
      "aria-label": `Dividend, ex-date ${longDate(mk.ex_date)}: ${dividendText(mk)}` },
      s("circle", { cx, cy, r: 13, fill: "transparent" }),
      s("circle", { class: "dot", cx, cy, r: 8 }),
      s("text", { x: cx, y: cy + 3.5, "text-anchor": "middle", text: "D" }));
    const nodes = () => [h("div", { class: "t-title", text: "Dividend" }), h("div", { text: `Ex-dividend date ${longDate(mk.ex_date)}` }), h("div", { text: dividendText(mk) })];
    g.addEventListener("pointermove", (e) => showTip(e, nodes()));
    g.addEventListener("pointerleave", hideTip);
    g.addEventListener("focus", () => placeTipBelow(g, nodes()));
    g.addEventListener("blur", hideTip);
    svg.append(g);
  }
  const extras = markers.length ? [{ symbol: "D", name: "Dividend (ex-dividend date)" }] : [];
  if (markers.some((mk) => mk.abnormal)) extras.push({ symbol: "D", name: "One-off, excluded from dividend figures", outline: true });
  return h("div", {}, legend(series, false, extras), svg);
}

/* Column chart, one baseline at zero, 4px rounded data-ends. */
function barPath(x, w, yBase, yVal, r = 4) {
  const hgt = Math.abs(yBase - yVal);
  r = Math.min(r, w / 2, hgt);
  if (yVal <= yBase) { // positive: round the top
    return `M${x},${yBase}V${yVal + r}Q${x},${yVal} ${x + r},${yVal}H${x + w - r}Q${x + w},${yVal} ${x + w},${yVal + r}V${yBase}Z`;
  }
  return `M${x},${yBase}V${yVal - r}Q${x},${yVal} ${x + r},${yVal}H${x + w - r}Q${x + w},${yVal} ${x + w},${yVal - r}V${yBase}Z`;
}
function columnChart({ categories, series, yFmt, height = 220, label, width = 640 }) {
  const W = width, H = height, m = { l: 56, r: 10, t: 10, b: 26 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const values = series.flatMap((sr) => sr.values.filter((v) => v !== null && v !== undefined));
  const { lo, hi, ticks } = niceTicks(Math.min(0, ...values), Math.max(0, ...values));
  const Y = (v) => m.t + ph - ((v - lo) / (hi - lo)) * ph;
  const band = pw / categories.length;
  const n = series.length, gap = 2;
  const barW = Math.min(24, (band * 0.6 - gap * (n - 1)) / n);
  const groupW = barW * n + gap * (n - 1);

  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": label });
  for (const t of ticks) {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 ? "base-line" : "grid-line" }));
    svg.append(s("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end", text: yFmt(t) }));
  }
  categories.forEach((cat, ci) => {
    const gx = m.l + band * ci + (band - groupW) / 2;
    svg.append(s("text", { x: m.l + band * ci + band / 2, y: H - 8, "text-anchor": "middle", text: cat }));
    series.forEach((sr, si) => {
      const v = sr.values[ci];
      if (v === null || v === undefined) return;
      const x = gx + si * (barW + gap);
      const bar = s("path", { d: barPath(x, barW, Y(0), Y(v)), fill: `var(${sr.color})` });
      const hitArea = s("rect", { x: x - gap, y: m.t, width: barW + gap * 2, height: ph, fill: "transparent" });
      const over = (e) => { bar.setAttribute("fill-opacity", 0.75); showTip(e, [h("div", { class: "t-head", text: cat }), tipRow(yFmt(v), sr.name, sr.color)]); };
      hitArea.addEventListener("pointermove", over);
      hitArea.addEventListener("pointerleave", () => { bar.removeAttribute("fill-opacity"); hideTip(); });
      svg.append(bar, hitArea);
    });
  });
  return h("div", {}, legend(series, true), svg);
}

/* Horizontal bars: share price against the two value estimates. */
function valuationBars(items, width = 640) {
  const shown = items.filter((it) => it.value !== null && it.value > 0);
  const W = width, rowH = 40, labelW = 130, m = { t: 6, r: 70 };
  const H = m.t * 2 + rowH * shown.length;
  const max = Math.max(...shown.map((it) => it.value));
  const X = (v) => labelW + (v / max) * (W - labelW - m.r);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img",
    "aria-label": shown.map((it) => `${it.label} ${money(it.value)}`).join(", ") });
  svg.append(s("line", { x1: labelW, x2: labelW, y1: m.t, y2: H - m.t, class: "base-line" }));
  shown.forEach((it, i) => {
    const y = m.t + i * rowH + (rowH - 20) / 2;
    const w = X(it.value) - labelW;
    const label = s("text", { x: labelW - 10, y: y + 14, "text-anchor": "end", style: "fill:var(--ink-2);font-size:12px", text: it.label });
    svg.append(svgLabelHelp(label, it.label, it.help, 9, y + 10));
    const r = Math.min(4, w / 2);
    svg.append(s("path", { d: `M${labelW},${y}H${labelW + w - r}Q${labelW + w},${y} ${labelW + w},${y + r}V${y + 20 - r}Q${labelW + w},${y + 20} ${labelW + w - r},${y + 20}H${labelW}Z`,
      fill: it.emphasis ? "var(--s1)" : "var(--muted)" }));
    svg.append(s("text", { x: labelW + w + 8, y: y + 14, style: "fill:var(--ink);font-size:12px;font-weight:600", text: money(it.value) }));
  });
  return svg;
}

/* Charts are drawn at their real on-screen width so text stays at its
   intended size on a phone and a wide monitor alike; redrawn on resize. */
const slots = [];
function chartSlot(draw) {
  const el = h("div", { class: "chart-slot" });
  slots.push({ el, draw });
  return el;
}
function drawSlots() {
  for (const { el, draw } of slots) {
    if (!el.isConnected) continue;
    const w = Math.max(260, Math.floor(el.clientWidth));
    if (el.dataset.w === String(w)) continue;
    el.dataset.w = String(w);
    el.replaceChildren(draw(w));
  }
}
let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawSlots, 150); });

/* ---------- screener ---------- */
const COLUMNS = [
  { key: "score", label: "Score", value: (r) => sum(r.scores) },
  { key: "asx_code", label: "Company", value: (r) => r.asx_code },
  { key: "sector", label: "Sector", opt: true, opt3: true, value: (r) => r.sector },
  { key: "current_price", label: "Price", num: true, narrowHide: true, value: (r) => r.current_price },
  { key: "margin_of_safety_percent", label: "Margin of safety", num: true, value: (r) => r.margin_of_safety_percent },
  { key: "valuation", label: "Valuation", narrowHide: true, opt4: true, value: (r) => r.margin_of_safety_percent },
  { key: "roe", label: "ROE", num: true, opt: true, value: (r) => r.roe },
  { key: "debt_to_equity", label: "Debt/equity", num: true, opt: true, value: (r) => r.debt_to_equity },
  { key: "grossed_up_dividend_yield", label: "Yield (grossed up)", num: true, opt: true, value: (r) => r.grossed_up_dividend_yield },
  { key: "tests", label: "Value tests", opt: true, opt4: true, value: (r) => ["mos_ok", "roe_ok", "de_ok", "yield_ok"].filter((k) => r[k] === "Y").length },
  { key: "action", label: "Action", value: (r) => cache.screener.actions.indexOf(r.action) },
];

function filteredRows() {
  const q = state.q.trim().toLowerCase();
  return cache.screener.rows.filter((r) =>
    (!q || r.asx_code.toLowerCase().includes(q) || (r.company_name || "").toLowerCase().includes(q)) &&
    (!state.sector || r.sector === state.sector) &&
    (state.actions.size === 0 || state.actions.has(r.action)) &&
    (!state.passing || r.overall === "Y") &&
    (!state.held || r.held !== null) &&
    (!state.watchlist || (state.watchlist === "*" ? r.watchlists.length > 0 : r.watchlists.includes(state.watchlist))));
}
/* A star after the code for companies on a watchlist, naming the lists. */
const watchStar = (lists) => (lists && lists.length
  ? h("span", { class: "watch-star", title: `On watchlist: ${lists.join(", ")}`, "aria-label": `On watchlist ${lists.join(", ")}`, text: "★" }) : null);

function sortedRows(rows) {
  const col = COLUMNS.find((c) => c.key === state.sort.key);
  const dir = state.sort.dir === "asc" ? 1 : -1;
  const mos = (r) => r.margin_of_safety_percent ?? -Infinity;
  return [...rows].sort((a, b) => {
    const va = col.value(a), vb = col.value(b);
    if (va === null || va === undefined) return vb === null || vb === undefined ? mos(b) - mos(a) : 1;
    if (vb === null || vb === undefined) return -1;
    const cmp = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return cmp ? cmp * dir : mos(b) - mos(a); // ties: highest margin of safety first
  });
}

function screenerRow(r) {
  const open = () => { location.hash = `#/company/${r.asx_code}`; };
  const d = cache.screener;
  return h("tr", { tabindex: 0, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
    h("td", {}, wheel(r.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }), h("span", { class: "score-total", text: sum(r.scores) })),
    h("td", {}, h("span", { class: "code", text: r.asx_code }), watchStar(r.watchlists), r.held !== null ? h("span", { class: "held-tag", text: "HELD" }) : null,
      h("div", { class: "name", text: r.company_name || "" })),
    h("td", { class: "opt opt3", text: r.sector || NA }),
    h("td", { class: "num opt2", text: money(r.current_price) }),
    h("td", { class: `num ${signClass(r.margin_of_safety_percent) || ""}`.trim(), text: pct(r.margin_of_safety_percent, 0) }),
    h("td", { class: "opt2 opt4" }, valuationPill(r.margin_of_safety_percent)),
    h("td", { class: "num opt", text: pct(r.roe, 1) }),
    h("td", { class: "num opt", text: fmt(r.debt_to_equity, 2) }),
    h("td", { class: "num opt", text: pct(r.grossed_up_dividend_yield, 1) }),
    h("td", { class: "opt opt4" }, ynMarks(r)),
    h("td", {}, badge(r.action)));
}

async function renderScreener() {
  if (!cache.screener) {
    app.replaceChildren(h("p", { class: "loading", text: "Loading companies..." }));
    cache.screener = await getJSON("/api/screener");
  }
  const d = cache.screener;

  const chips = h("div", { class: "chips", role: "group", "aria-label": "Filter by action" });
  const tbody = h("tbody");
  const count = h("span", { class: "count" });
  const more = h("button", { class: "more", type: "button" });
  const headRow = h("tr");

  function refresh() {
    const rows = sortedRows(filteredRows());
    tbody.replaceChildren(...rows.slice(0, state.shown).map(screenerRow));
    count.textContent = `${rows.length} shown`;
    more.hidden = rows.length <= state.shown;
    more.textContent = `Show more (${rows.length - state.shown} remaining)`;
    for (const th of headRow.children) {
      th.setAttribute("aria-sort", th.dataset.sort === state.sort.key ? (state.sort.dir === "asc" ? "ascending" : "descending") : "none");
    }
    for (const chip of chips.children) chip.setAttribute("aria-pressed", state.actions.has(chip.dataset.action));
  }

  for (const action of d.actions) {
    const n = d.rows.filter((r) => r.action === action).length;
    if (!n) continue;
    chips.append(h("button", { class: "chip", type: "button", "data-action": action, onclick: () => {
      state.actions.has(action) ? state.actions.delete(action) : state.actions.add(action);
      state.shown = PAGE_SIZE; refresh();
    } }, badge(action), h("span", { class: "n", text: n })));
  }

  for (const col of COLUMNS) {
    headRow.append(withHelp(h("th", { class: [col.num ? "num" : "", col.opt ? "opt" : "", col.opt3 ? "opt3" : "", col.opt4 ? "opt4" : "", col.narrowHide ? "opt2" : ""].join(" ").trim() || null, "data-sort": col.key,
      scope: "col", tabindex: 0, text: col.label,
      onclick: () => sortBy(col), onkeydown: (e) => { if (e.key === "Enter") sortBy(col); } }), col.label));
  }
  function sortBy(col) {
    state.sort = state.sort.key === col.key
      ? { key: col.key, dir: state.sort.dir === "asc" ? "desc" : "asc" }
      : { key: col.key, dir: col.key === "action" || col.key === "asx_code" || col.key === "sector" ? "asc" : "desc" };
    refresh();
  }

  const search = h("input", { type: "search", placeholder: "Search code or company", value: state.q, "aria-label": "Search",
    oninput: (e) => { state.q = e.target.value; state.shown = PAGE_SIZE; refresh(); } });
  const sector = h("select", { "aria-label": "Sector", onchange: (e) => { state.sector = e.target.value; state.shown = PAGE_SIZE; refresh(); } },
    h("option", { value: "", text: "All sectors" }), d.sectors.map((sc) => h("option", { value: sc, selected: sc === state.sector, text: sc })));
  const toggle = (key, text) => h("label", {}, h("input", { type: "checkbox", checked: state[key],
    onchange: (e) => { state[key] = e.target.checked; state.shown = PAGE_SIZE; refresh(); } }), text);
  more.addEventListener("click", () => { state.shown += PAGE_SIZE; refresh(); });
  if (state.watchlist && state.watchlist !== "*" && !d.watchlists.some((w) => w.name === state.watchlist)) state.watchlist = "";
  const watchFilter = d.watchlists.length ? h("select", { "aria-label": "Watchlist",
    onchange: (e) => { state.watchlist = e.target.value; state.shown = PAGE_SIZE; refresh(); } },
    h("option", { value: "", text: "All companies" }), h("option", { value: "*", selected: state.watchlist === "*", text: "On any watchlist" }),
    d.watchlists.map((w) => h("option", { value: w.name, selected: w.name === state.watchlist, text: `Watchlist: ${w.name}` }))) : null;

  app.replaceChildren(
    pageHead("Screener", `${d.rows.length} companies${d.as_of ? ", valuations as at " + longDate(d.as_of) : ""}`),
    chips,
    h("div", { class: "controls" }, search, sector, watchFilter, toggle("passing", "Passes all four tests"), toggle("held", "Held only"), count),
    h("div", { class: "table-wrap" }, h("table", { class: "grid" }, h("thead", {}, headRow), tbody)),
    more);
  refresh();
}

/* ---------- company page ---------- */
function movingAverage(points, window = 200) {
  const out = [];
  let run = 0;
  points.forEach((p, i) => {
    run += p[1];
    if (i >= window) run -= points[i - window][1];
    if (i >= window - 1) out.push([p[0], run / window]);
  });
  return out;
}

/* "USD, converted to AUD at 1.5234 (30 Jun 2025)" for the latest report. */
function accountsCurrency(c, reports) {
  const latest = reports.length ? reports[reports.length - 1] : null;
  const from = (latest && latest.reporting_currency) || c.financial_currency;
  const to = c.trading_currency || "AUD";
  if (!from) return NA;
  if (from === to || !latest || !latest.fx_rate || latest.fx_rate === 1) return `${from} (no conversion needed)`;
  return `${from}, converted to ${to} at ${fmt(latest.fx_rate, 4)} (${longDate(latest.report_date)})`;
}

/* One headline figure: label (with its explanation), value, small note. */
function statTile(label, valueText, cls, note) {
  return h("div", { class: "stat" },
    withHelp(h("div", { class: "stat-label", tabindex: 0, text: label }), label),
    h("div", { class: `stat-value ${cls || ""}`.trim(), text: valueText }),
    note ? h("div", { class: "stat-note", text: note }) : null);
}

/* The four headline figures at the top of a company page. */
function summaryStrip(c, model) {
  const mos = c.margin_of_safety_percent;
  const value = c.dcf_intrinsic_value;
  const upside = value && value > 0 && c.current_price ? ((value - c.current_price) / c.current_price) * 100 : null;
  const signed = (v, dp) => (v === null || v === undefined ? NA : `${v > 0 ? "+" : ""}${fmt(v, dp)}%`);
  const tile = statTile;
  return h("div", { class: "stats" },
    tile("Share price", money(c.current_price), null, `as at ${longDate(c.as_of_date)}`),
    tile("Estimated value", value && value > 0 ? money(value) : NA, "accent", model ? `${model.method} model` : "no model could run"),
    tile("Margin of safety", signed(mos, 1), signClass(mos), valuationStatus(mos).label),
    tile("Implied upside", signed(upside, 1), signClass(upside), "price to reach estimated value"));
}
function modelNote(model) {
  if (!model) return null;
  const name = model.method === "DDM" ? "Two-stage dividend discount model (used for banks, insurers and REITs)" : "Two-stage discounted cash flow model";
  const base = model.method === "DDM" ? "average dividend per share" : "average free cash flow";
  return h("p", { class: "model-note", text:
    `${name}: ${base} over three years, grown ${fmt(model.growth_rate * 100, 0)}% a year for ${model.stage1_years} years, ` +
    `then ${fmt(model.terminal_growth_rate * 100, 1)}% a year, discounted at ${fmt(model.discount_rate * 100, 0)}% a year.` });
}

function checklist(checks) {
  return h("ul", { class: "checklist" }, checks.map((ch) => {
    const cls = ch.passed === true ? "pass" : ch.passed === false ? "fail" : "na";
    const mark = ch.passed === true ? "✓" : ch.passed === false ? "✕" : "–";
    return h("li", {}, h("span", { class: `mark ${cls}`, "aria-hidden": "true", text: mark }),
      h("span", { text: ch.label + (ch.passed === null ? " (no data)" : "") }));
  }));
}

function card(title, hint, ...children) {
  return h("section", { class: "card" }, h("h2", { text: title }), hint ? h("p", { class: "hint", text: hint }) : null, children);
}

async function renderCompany(code) {
  hideTip();
  slots.length = 0;
  app.replaceChildren(h("p", { class: "loading", text: `Loading ${code}...` }));
  let d;
  try {
    d = await getJSON(`/api/company/${encodeURIComponent(code)}`);
  } catch (err) {
    app.replaceChildren(backLink(), h("p", { class: "error", text: err.message }));
    return;
  }
  const c = d.company;
  const scores = d.axes.map((a) => d.scores[a].score);
  const total = sum(scores);

  // Valuation headline
  const mos = c.margin_of_safety_percent;
  const method = c.valuation_method === "DDM" ? "dividend discount model" : c.valuation_method === "DCF" ? "discounted cash flow model" : null;
  const valuation = card("Price against estimated value",
    method ? `Estimated value from a ${method}. Graham Number shown for reference.` : "No intrinsic value estimate could be made for this company.",
    chartSlot((w) => valuationBars([
      { label: "Share price", value: c.current_price, emphasis: true, help: FIELD_HELP["Share price"] },
      { label: "Estimated value", value: c.dcf_intrinsic_value, help: () => ESTIMATED_VALUE_HELP[c.valuation_method] },
      { label: "Graham Number", value: c.graham_number, help: FIELD_HELP["Graham Number"] },
    ], w)));

  const wheelCard = card("Score", `${total} of ${d.checks_per_axis * d.axes.length} checks passed. Hover a spoke to see its checks.`,
    chartSlot((w) => wheel(scores, d.axes, d.checks_per_axis, { size: Math.min(300, w - 160), details: d.scores })));

  // Each spoke collapses to one line that keeps its score; closed by default.
  const axisBlocks = d.axes.map((a) => h("details", { class: "axis-block" },
    h("summary", {},
      h("span", { class: "twisty", "aria-hidden": "true" }),
      h("span", { class: "axis-name", text: a }),
      h("span", { class: "axis-score", text: `${d.scores[a].score} / ${d.checks_per_axis}` })),
    checklist(d.scores[a].checks)));
  const toggleAll = h("button", { type: "button", class: "link-btn", text: "Expand all" });
  toggleAll.addEventListener("click", () => {
    const open = !axisBlocks.every((b) => b.open);
    axisBlocks.forEach((b) => { b.open = open; });
  });
  axisBlocks.forEach((b) => b.addEventListener("toggle", () => {
    toggleAll.textContent = axisBlocks.every((x) => x.open) ? "Collapse all" : "Expand all";
  }));
  const breakdown = card("Score breakdown", "Six yes/no checks per spoke. No data never counts as a pass. Click a spoke to see its checks.",
    toggleAll, axisBlocks);

  const tests = card("Four value tests", "The core screen. All four must pass for an overall pass.",
    checklist(d.tests.map((t) => ({ passed: t.passed,
      label: `${t.name}: ${t.value === null ? NA : fmt(t.value, t.unit === "%" ? 1 : 2) + t.unit} (needs ${t.rule})` }))));

  const markers = card("Quality and trend markers", null,
    h("dl", { class: "kv" },
      withHelp(h("dt", { tabindex: 0, text: "Earnings quality" }), "Earnings quality"), h("dd", { text: `${c.earnings_quality || NA}${c.cash_conversion !== null ? ` (cash flow ${fmt(c.cash_conversion, 0)}% of profit)` : ""}` }),
      withHelp(h("dt", { tabindex: 0, text: "Price signal" }), "Price signal"), h("dd", { text: `${c.price_signal || NA}${c.price_vs_200d !== null ? ` (${fmt(c.price_vs_200d, 1)}% vs 200-day average)` : ""}` }),
      withHelp(h("dt", { tabindex: 0, text: "Dividend trend" }), "Dividend trend"), h("dd", { text: c.dividend_trend || NA }),
      withHelp(h("dt", { tabindex: 0, text: "Fundamentals trend" }), "Fundamentals trend"), h("dd", { text: c.fundamentals_trend || NA }),
      withHelp(h("dt", { tabindex: 0, text: "Margin of safety trend" }), "Margin of safety trend"), h("dd", { text: c.margin_of_safety_trend === null ? "needs 30 days of history" : `${fmt(c.margin_of_safety_trend, 1)} points over 30 days` }),
      withHelp(h("dt", { tabindex: 0, text: "Value-trap risk" }), "Value-trap risk"), h("dd", { text: c.trap_risk === "Y" ? "Yes" : "No" }),
      withHelp(h("dt", { tabindex: 0, text: "Data confidence" }), "Data confidence"), h("dd", { text: c.data_confidence || NA })),
    d.flags.length ? [h("p", { class: "hint", style: "margin-top:10px", text: "Red flags" }), h("ul", { class: "flags" }, d.flags.map((f) => h("li", { text: f })))] : null);

  const ratios = card("Key ratios", null, h("dl", { class: "kv" },
    [["P/E", fmt(c.pe_ratio, 1)], ["P/B", fmt(c.pb_ratio, 2)], ["Price to free cash flow", fmt(c.price_to_fcf, 1)],
      ["EV/EBIT", fmt(c.ev_to_ebit, 1)], ["ROE", pct(c.roe)], ["ROIC", pct(c.roic)], ["Debt/equity", fmt(c.debt_to_equity, 2)],
      ["Cash dividend yield", pct(c.uncapped_dividend_yield)], ["Grossed-up yield", pct(c.grossed_up_dividend_yield)],
      ["Payout ratio", pct(c.payout_ratio, 0)], ["Country", c.country || NA], ["Accounts currency", accountsCurrency(c, d.reports)]]
      .flatMap(([k, v]) => [withHelp(h("dt", { tabindex: 0, text: k }), k), h("dd", { text: v })])));

  // Price chart
  let priceCard;
  if (d.prices.length >= 2) {
    const ma = movingAverage(d.prices);
    const series = [{ name: "Close", color: "--s1", points: d.prices }];
    if (ma.length >= 2) series.push({ name: "200-day average", color: "--s2", points: ma });
    const markers = dividendMarkers(d.prices, d.dividends || []);
    // Data table: the last 30 trading days plus every ex-dividend day in the year.
    const closeOn = new Map(d.prices.map((p) => [p[0], p[1]]));
    const divOn = new Map(markers.map((mk) => [mk.date, mk]));
    const rowDates = [...new Set([...d.prices.slice(-30).map((p) => p[0]), ...markers.map((mk) => mk.date)])].sort().reverse();
    priceCard = card("Share price, last 12 months",
      ma.length >= 2 ? null : `200-day average appears once 200 days of prices are stored (${d.prices.length} so far).`,
      chartSlot((w) => lineChart({ series, yFmt: (v) => money(v), label: `${c.asx_code} closing price`, width: w, height: 260, markers })),
      tableView(["Date", "Close", "Dividend (ex-date)"], rowDates.map((dt) => [longDate(dt), money(closeOn.get(dt)),
        divOn.has(dt) ? dividendText(divOn.get(dt)) : ""])));
  } else {
    priceCard = card("Share price, last 12 months", "Not enough price history yet.");
  }
  priceCard.classList.add("wide");

  const mosCard = d.mos_history.length >= 2
    ? card("Margin of safety over time", "The pink line is 0%, where the price equals estimated value. Above it: trading below estimated value.",
      chartSlot((w) => lineChart({ series: [{ name: "Margin of safety", color: "--s1", points: d.mos_history }], yFmt: (v) => fmt(v, 0) + "%", zeroLine: true, label: "Margin of safety history", width: w })),
      tableView(["Date", "Margin of safety"], d.mos_history.slice(-30).reverse().map((p) => [longDate(p[0]), pct(p[1])])))
    : card("Margin of safety over time", "Builds up as the nightly job records a valuation each day.");

  const fy = d.reports.map((r) => `FY${String(r.fiscal_year).slice(-2)}`);
  const finCard = d.reports.length
    ? card("Revenue and net profit", "Annual reports, oldest to newest.",
      chartSlot((w) => columnChart({ categories: fy, yFmt: compact, label: "Revenue and net profit by year", width: w, series: [
        { name: "Revenue", color: "--s1", values: d.reports.map((r) => r.revenue) },
        { name: "Net profit after tax", color: "--s2", values: d.reports.map((r) => r.net_profit_after_tax) }] })),
      tableView(["Year", "Revenue", "Net profit", "Free cash flow"], d.reports.map((r, i) => [fy[i], compact(r.revenue), compact(r.net_profit_after_tax), compact(r.free_cash_flow)])))
    : card("Revenue and net profit", "No annual reports stored.");
  const abnormal = d.reports.map((r, i) => [fy[i], r.abnormal_distributions_per_share]).filter(([, v]) => v > 0);
  const abnormalNote = abnormal.length ? h("p", { class: "hint note", text:
    `Excluded from every dividend figure: ${abnormal.map(([y, v]) => `${money(v, 3)} in ${y}`).join(", ")}. ` +
    "A one-off payment more than twice the usual annual dividend, such as a capital return or large special dividend." }) : null;
  const divCard = d.reports.some((r) => r.dividends_per_share)
    ? card("Dividends per share", "Ordinary cash dividends per financial year, before franking credits.",
      abnormalNote,
      chartSlot((w) => columnChart({ categories: fy, yFmt: (v) => money(v), label: "Dividends per share by year", width: w,
        series: [{ name: "Dividend per share", color: "--s1", values: d.reports.map((r) => r.dividends_per_share) }] })),
      tableView(["Year", "Dividend per share", "Excluded one-off"], d.reports.map((r, i) =>
        [fy[i], money(r.dividends_per_share, 3), r.abnormal_distributions_per_share ? money(r.abnormal_distributions_per_share, 3) : "none"])))
    : card("Dividends per share", "No dividends recorded.", abnormalNote);

  const held = d.position ? h("p", { class: "hint", text:
    `You hold ${fmt(d.position.units, 0)} units, cost base ${money(d.position.cost_base)}.` +
    (d.position.next_discount_date ? ` ${fmt(d.position.units_pending_discount, 0)} units qualify for the CGT discount from ${longDate(d.position.next_discount_date)}.` : "") }) : null;

  app.replaceChildren(...[
    backLink(),
    h("div", { class: "co-head" },
      h("h1", { text: c.company_name || c.asx_code }),
      h("span", { class: "ticker mono", text: c.asx_code }),
      valuationPill(mos, true),
      badge(c.action),
      watchButton(c.asx_code, d.watchlists)),
    h("p", { class: "co-sub", text: [c.sector, c.industry, c.country].filter(Boolean).join("  |  ") }),
    h("p", { class: "reason", text: c.action_reason }),
    summaryStrip(c, d.model),
    modelNote(d.model),
    held,
    watchNote(d.watchlists),
    h("div", { class: "cards" }, wheelCard, valuation, tests, breakdown, markers, ratios, priceCard, mosCard, finCard, divCard),
  ].filter(Boolean)); // native replaceChildren would print a null as "null"
  drawSlots();
  window.scrollTo(0, 0);
}

/* ---------- page furniture ---------- */
function pageHead(title, sub, ...extra) {
  return h("div", { class: "page-head" }, h("h1", { text: title }), sub ? h("span", { class: "sub", text: sub }) : null, extra);
}
const BACK_LABELS = [[/^#\/?$/, "Dashboard"], [/^#\/screener/, "Screener"], [/^#\/portfolios/, "Portfolios"], [/^#\/portfolio\//, "Portfolio"],
  [/^#\/track-record/, "Track record"], [/^#\/watchlists/, "Watchlists"], [/^#\/watchlist\//, "Watchlist"]];
function backLink() {
  const target = previousPage || "#/screener";
  const label = (BACK_LABELS.find(([re]) => re.test(target)) || [null, "Screener"])[1];
  return h("a", { class: "back", href: target, text: `← ${label}` });
}
/* A link such as #/screener?action=BUY,INVESTIGATE opens the screener with
   just that filter; a plain #/screener keeps whatever was set last. */
function presetScreener(query) {
  if (query === undefined) return;
  const params = new URLSearchParams(query);
  Object.assign(state, { q: "", sector: "", passing: false, held: params.get("held") === "1", shown: PAGE_SIZE,
    watchlist: params.get("watchlist") || "",
    actions: new Set((params.get("action") || "").split(",").filter(Boolean)) });
}
const signed = (v, fmtFn) => (v === null || v === undefined ? NA : (v > 0 ? "+" : v < 0 ? "-" : "") + fmtFn(Math.abs(v)));
const dateTime = (iso) => new Date(iso).toLocaleString("en-AU", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const timeOnly = (iso) => new Date(iso).toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" });
const plural = (n, word, many = word + "s") => `${fmt(n, 0)} ${n === 1 ? word : many}`;
function companyLink(code, name, ...extra) {
  return h("a", { class: "row-link", href: `#/company/${code}` }, h("span", { class: "code", text: code }), name ? h("span", { class: "name-inline", text: name }) : null, extra);
}
function clickableRow(code, ...cells) {
  const open = () => { location.hash = `#/company/${code}`; };
  return h("tr", { tabindex: 0, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } }, cells);
}

/* ---------- menu bar ---------- */
const nav = document.getElementById("mainnav");
const menuBtn = document.getElementById("menu-btn");
function closeDropdowns(except = null) {
  for (const dd of document.querySelectorAll(".dd")) {
    if (dd === except) continue;
    dd.querySelector(".dd-btn").setAttribute("aria-expanded", "false");
    dd.querySelector(".dd-menu").hidden = true;
  }
}
function closeSettings() {
  document.getElementById("settings").hidden = true;
  document.getElementById("settings-btn").setAttribute("aria-expanded", "false");
}
/* Everything that pops up from the menu bar, e.g. after moving to another page. */
function closeMenus() {
  closeDropdowns();
  closeSettings();
  nav.classList.remove("open");
  menuBtn.setAttribute("aria-expanded", "false");
}
function markCurrent(page) {
  for (const a of nav.querySelectorAll(":scope > a")) {
    if (a.dataset.nav === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  for (const dd of nav.querySelectorAll(".dd")) dd.classList.toggle("current", dd.dataset.nav === page);
}

/* Data-date chip: green when the latest valuations are current, amber (with
   a "!") when the nightly data is behind or the last run had problems. */
function statusLines(st) {
  const lines = [];
  lines.push(st.as_of ? `Prices and valuations as at ${longDate(st.as_of)}.` : "No valuations yet.");
  if (st.stale) lines.push(`Expected data for ${longDate(st.expected)}. Check the nightly job ran (or it was a public holiday).`);
  const run = st.last_run;
  if (!run) lines.push("No nightly run log found in the logs folder on this PC.");
  else if (run.status === "ok") lines.push(`Last nightly run ${dateTime(run.started)}, finished ${timeOnly(run.finished)} with no errors.`);
  else if (run.status === "errors") lines.push(`Last nightly run ${dateTime(run.started)}, finished ${timeOnly(run.finished)}. ${plural(run.errors, "company", "companies")} could not be updated (usually gaps in Yahoo's data). See logs\\${run.file}.`);
  else if (run.status === "crashed") lines.push(`Last nightly run ${dateTime(run.started)}: a step crashed, so some data may not have updated. See logs\\${run.file}.`);
  else if (run.status === "running") lines.push(`Nightly run in progress, started ${dateTime(run.started)}.`);
  else lines.push(`Last nightly run${run.started ? " " + dateTime(run.started) : ""} did not finish. See logs\\${run.file}.`);
  return lines;
}
function paintChip(st) {
  const chip = document.getElementById("data-chip");
  if (!st) return;
  const run = st.last_run;
  const warn = st.stale || (run && (run.status === "crashed" || run.status === "incomplete"));
  chip.classList.toggle("warn", !!warn);
  const label = st.as_of ? `Data ${dayMonth(st.as_of)}` : "No data";
  const why = st.stale ? "out of date" : warn ? "run problems" : null;
  chip.replaceChildren(h("span", {}, label, why ? h("span", { class: "long", text: `, ${why}` }) : null));
  chip.setAttribute("aria-label", statusLines(st).join(" "));
  chip.hidden = false;
}
async function loadStatus() {
  try { cache.status = await getJSON("/api/status"); paintChip(cache.status); } catch (e) { /* chip stays hidden */ }
}

/* Find a company: type a code or part of a name, pick from the list or press Enter. */
function findCompany(q) {
  const up = q.trim().toUpperCase();
  const list = cache.companies || [];
  if (!up) return null;
  return list.find((c) => c.code === up) || list.find((c) => c.code.startsWith(up)) ||
    list.find((c) => (c.name || "").toUpperCase().includes(up)) || null;
}
function initSearch() {
  const form = document.getElementById("nav-search"), input = document.getElementById("nav-search-input");
  if (window.matchMedia("(max-width: 480px)").matches) input.placeholder = "Search";
  const go = (c) => { input.value = ""; input.blur(); closeMenus(); location.hash = `#/company/${c.code}`; };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const c = findCompany(input.value);
    if (c) { go(c); return; }
    form.classList.add("no-match");
    placeTipBelow(form, [h("div", { text: input.value.trim() ? `No screened company matches "${input.value.trim()}".` : "Type an ASX code or part of a company name." })]);
    setTimeout(() => { form.classList.remove("no-match"); hideTip(); }, 1800);
  });
  input.addEventListener("input", (e) => {
    // Picking from the list fills in the exact code; typing goes through Enter.
    if (e.inputType && e.inputType !== "insertReplacementText") return;
    const c = (cache.companies || []).find((x) => x.code === input.value.trim().toUpperCase());
    if (c) go(c);
  });
  getJSON("/api/companies").then((list) => {
    cache.companies = list;
    document.getElementById("company-list").replaceChildren(...list.map((c) => h("option", { value: c.code, label: c.name || c.code })));
  }).catch(() => { /* search still works once the page reloads */ });
}

function initNav() {
  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = !nav.classList.contains("open");
    closeDropdowns();
    closeSettings();
    nav.classList.toggle("open", open);
    menuBtn.setAttribute("aria-expanded", open);
  });
  for (const dd of nav.querySelectorAll(".dd")) {
    const btn = dd.querySelector(".dd-btn"), menu = dd.querySelector(".dd-menu");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = menu.hidden;
      closeDropdowns(dd);
      closeSettings();
      menu.hidden = !open;
      btn.setAttribute("aria-expanded", open);
    });
    menu.addEventListener("click", (e) => { if (e.target.closest("a")) closeMenus(); });
  }
  nav.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => closeMenus());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });
  document.getElementById("settings-btn").addEventListener("click", () => closeDropdowns());
  const chip = document.getElementById("data-chip");
  bindHelp(chip, () => [h("div", { class: "t-title", text: "Data" }), ...statusLines(cache.status || {}).map((l) => h("div", { text: l }))]);
  initSearch();
  loadStatus();
  loadPortfolioMenu();
  loadWatchlistMenu();
}

/* ---------- dashboard ---------- */
function portfolioStrip(pf) {
  const gainPct = pf.gain !== null && pf.cost_base ? (pf.gain / pf.cost_base) * 100 : null;
  const prevValue = pf.day_change !== null && pf.value !== null ? pf.value - pf.day_change : null;
  const dayPct = prevValue ? (pf.day_change / prevValue) * 100 : null;
  const n = pf.holdings.length;
  return h("div", { class: "stats" },
    statTile("Portfolio value", money(pf.value, 0), null, `${plural(n, "holding")}${pf.unpriced.length ? `, ${pf.unpriced.length} without a price` : ""}`),
    statTile("Today", signed(pf.day_change, (v) => money(v, 0)), signClass(pf.day_change), dayPct === null ? "needs two days of prices" : signed(dayPct, (v) => fmt(v, 2) + "%")),
    statTile("Unrealised gain", signed(pf.gain, (v) => money(v, 0)), signClass(pf.gain), gainPct === null ? null : signed(gainPct, (v) => fmt(v, 1) + "%") + " on cost"),
    statTile("Cost base", money(pf.cost_base, 0), null, "purchase price plus brokerage"));
}

/* One line per active portfolio, when there's more than one. */
function portfoliosCard(list) {
  return card("Portfolios", null, h("ul", { class: "items" }, list.map((p) => h("li", {},
    h("div", { class: "main" }, h("a", { class: "row-link", href: portfolioHref(p) }, h("span", { class: "code", text: p.name })),
      h("span", { class: "detail", text: `${p.tax_type_label}, ${plural(p.holdings, "holding")}` })),
    p.holdings ? h("div", { class: "side" }, h("div", { class: "strong", text: money(p.value, 0) }),
      h("div", { class: `detail ${signClass(p.gain) || ""}`.trim(), text: `${signed(p.gain, (v) => money(v, 0))} gain` }))
      : h("div", { class: "side detail", text: "no holdings yet" })))),
    h("p", { class: "card-foot" }, h("a", { href: "#/portfolios", text: "All portfolios →" })));
}

function attentionCard(d) {
  const items = [
    ...d.attention.map((a) => h("li", {}, h("div", { class: "main" },
      companyLink(a.asx_code, null), badge(a.action), h("span", { class: "detail", text: a.action_reason })))),
    ...d.cgt_soon.map((c) => h("li", {}, h("div", { class: "main" },
      companyLink(c.asx_code, null), h("span", { text: `CGT discount from ${longDate(c.date)}` }),
      h("span", { class: "detail", text: `${fmt(c.units, 0)} units, ${plural(c.days, "day")} away. A sale before then gets no CGT discount on these units.` })))),
    d.not_screened.length ? h("li", {}, h("div", { class: "main" }, h("span", { text: `Held but not screened: ${d.not_screened.join(", ")}` }),
      h("span", { class: "detail", text: "Add them to the nightly ticker file (allords.txt) so they are valued each night." }))) : null,
    ...d.triggered.map((t) => h("li", {}, h("div", { class: "main" },
      companyLink(t.asx_code, null), h("span", { class: "watch-star", "aria-hidden": "true", text: "★" }),
      h("span", { text: t.triggers.map((x) => x.label).join("; ") }),
      h("span", { class: "detail" }, "Watchlist trigger met on ", h("a", { href: `#/watchlist/${t.watchlist_id}`, text: t.watchlist }),
        t.note ? `. Note: ${t.note}` : "")))),
  ].filter(Boolean);
  return card("Needs attention", items.length ? "Held shares flagged SELL or REVIEW, parcels reaching the CGT discount soon, and watchlist triggers met." : null,
    items.length ? h("ul", { class: "items" }, items)
      : h("p", { class: "empty", text: `Nothing needs attention: no held shares are flagged SELL or REVIEW, no parcel reaches the CGT discount in the next ${d.cgt_soon_days} days, and no watchlist trigger is met.` }));
}

const MAX_CHANGES = 12;
function changesCard(d) {
  const ch = d.changes;
  if (!ch.from_date) {
    const first = d.tracking.first_date;
    return card("What changed", null, h("p", { class: "empty", text: first
      ? `Appears after the second night of recording (first night ${longDate(first)}). Lists companies whose suggested action moved.`
      : "Appears once two nightly runs have recorded signals. Lists companies whose suggested action moved." }));
  }
  if (!ch.changes.length) {
    return card("What changed", null, h("p", { class: "empty", text: `No suggested action changed between ${longDate(ch.from_date)} and ${longDate(ch.to_date)}.` }));
  }
  const shown = ch.changes.slice(0, MAX_CHANGES);
  return card("What changed", `${longDate(ch.from_date)} to ${longDate(ch.to_date)}: suggested actions that moved, watchlist companies (★) first, then better moves first.`,
    h("ul", { class: "items" }, shown.map((c) => h("li", {},
      h("span", { class: `move ${c.direction}`, "aria-label": c.direction === "up" ? "Better" : "Worse", text: c.direction === "up" ? "▲" : "▼" }),
      h("div", { class: "main" }, companyLink(c.asx_code, null), watchStar(c.watchlists), c.held ? h("span", { class: "held-tag", text: "HELD" }) : null,
        h("span", { class: "detail", text: `${c.company_name || ""}${c.margin_of_safety_percent !== null ? `, margin of safety ${pct(c.margin_of_safety_percent, 0)}` : ""}` })),
      h("div", { class: "side" }, badge(c.previous), h("span", { class: "arrow", "aria-label": "to", text: "→" }), badge(c.action))))),
    ch.changes.length > MAX_CHANGES ? h("p", { class: "card-foot", text: `and ${ch.changes.length - MAX_CHANGES} more.` }) : null);
}

function topCard(d) {
  const counts = d.action_counts;
  const parts = ["BUY", "INVESTIGATE"].filter((a) => counts[a]).map((a) => `${counts[a]} ${a}`);
  const foot = parts.length ? h("p", { class: "card-foot" }, h("a", { href: "#/screener?action=BUY,INVESTIGATE",
    text: `See all ${parts.join(" and ")} in the screener →` })) : null;
  const c = card("Top opportunities", "Shares you don't hold: BUY first, then INVESTIGATE, highest score first.",
    d.top.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, ["Score", "Company", "Margin of safety", "Valuation", "Action"].map((x, i) =>
        withHelp(h("th", { class: [i === 2 ? "num" : "", i === 0 || i === 3 ? "opt2" : ""].join(" ").trim() || null, tabindex: 0, text: x }), x)))),
      h("tbody", {}, d.top.map((r) => clickableRow(r.asx_code,
        h("td", { class: "opt2" }, wheel(r.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }), h("span", { class: "score-total", text: sum(r.scores) })),
        h("td", {}, h("span", { class: "code", text: r.asx_code }), h("div", { class: "name", text: r.company_name || "" })),
        h("td", { class: `num ${signClass(r.margin_of_safety_percent) || ""}`.trim(), text: pct(r.margin_of_safety_percent, 0) }),
        h("td", { class: "opt2" }, valuationPill(r.margin_of_safety_percent)),
        h("td", {}, badge(r.action))))))) : h("p", { class: "empty", text: "No BUY or INVESTIGATE signals today." }),
    foot);
  c.classList.add("wide");
  return c;
}

function actionsCard(d) {
  const chips = Object.entries(d.action_counts).filter(([, n]) => n).map(([a, n]) =>
    h("a", { class: "chip", href: `#/screener?action=${a}` }, badge(a), h("span", { class: "n", text: n })));
  return card("Today's suggested actions", `Across ${plural(d.companies, "screened company", "screened companies")}. Pick one to open the screener filtered to it.`,
    h("div", { class: "action-chips" }, chips));
}

function resultsTimeline(t) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return h("ul", { class: "timeline" }, t.results_due.map((r) => {
    const days = Math.round((toDate(r.date) - today) / 86400000);
    return h("li", {}, h("span", { text: `${r.months}-month results` }),
      h("span", { text: days > 0 ? `${longDate(r.date)} (in ${plural(days, "day")})` : `from ${longDate(r.date)}` }));
  }));
}
function trackingCard(t, withLink = true) {
  const body = t.first_date
    ? [h("p", { class: "hint", text: `Recording since ${longDate(t.first_date)}: ${plural(t.days_recorded, "night")}, ${plural(t.signals_recorded, "signal")}. Rules version ${t.rules_version}.` }),
      t.headline ? h("ul", { class: "verdict" }, verdictLine(t.headline, t.headline.horizon_months)) : null,
      resultsTimeline(t)]
    : [h("p", { class: "empty", text: "Recording starts with the next nightly run. Each night Sift records every company's suggested action, valuation and score, so they can be checked later against what the share price did." })];
  return card("Track record", null, body,
    withLink ? h("p", { class: "card-foot" }, h("a", { href: "#/track-record", text: "Track record →" })) : null);
}

function statusFoot(st) {
  return h("div", { class: "dash-foot" }, statusLines(st).map((l) => h("span", { text: l })));
}

async function renderDashboard() {
  app.replaceChildren(h("p", { class: "loading", text: "Loading dashboard..." }));
  const d = await getJSON("/api/dashboard");
  cache.thresholds = d.thresholds;
  cache.status = d.status;
  paintChip(d.status);
  const today = new Date().toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const pf = d.portfolio;
  app.replaceChildren(...[
    pageHead("Dashboard", today),
    pf.holdings.length ? portfolioStrip(pf) : null,
    h("div", { class: "cards dash" }, attentionCard(d), changesCard(d), topCard(d),
      pf.portfolios.length > 1 ? portfoliosCard(pf.portfolios) : null, actionsCard(d), trackingCard(d.tracking)),
    statusFoot(d.status),
  ].filter(Boolean));
  window.scrollTo(0, 0);
}

/* ---------- portfolios (each with its own tax type) and trades ---------- */
/* Every change carries the X-Sift header: gui.py refuses changes without
   it, so another website's page can't make them with your saved password. */
async function send(method, url, body) {
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json", Accept: "application/json", "X-Sift": "1" },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}
/* After a trade, held flags and actions change: refetch the screener and the menu next time. */
function afterChange() { cache.screener = null; loadPortfolioMenu(); loadWatchlistMenu(); }

const discountText = (rate) => (rate > 0 ? `${fmt(rate * 100, rate * 100 % 1 ? 1 : 0)}% CGT discount` : "no CGT discount");
const taxTag = (p) => h("span", { class: "tag", text: `${p.tax_type_label}, ${discountText(p.discount_rate)}` });
const portfolioHref = (p) => `#/portfolio/${p.portfolio_id}`;

async function loadPortfolioMenu() {
  const slot = document.getElementById("portfolio-menu-items");
  try {
    const d = await getJSON("/api/portfolios?brief=1");
    cache.portfolios = d.portfolios;
    slot.replaceChildren(...d.portfolios.filter((p) => !p.archived).map((p) => h("a", { href: portfolioHref(p), text: p.name })));
  } catch (e) { /* the menu keeps its last list */ }
}

function field(label, input, hint) {
  return h("label", { class: "field" }, h("span", { class: "field-label", text: label }), input, hint ? h("span", { class: "field-hint", text: hint }) : null);
}
const todayIso = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
function taxSelect(types, value) {
  return h("select", { name: "tax_type" }, types.map((t) =>
    h("option", { value: t.tax_type, selected: t.tax_type === value, text: `${t.tax_type === "SMSF" ? "SMSF" : t.label} (${discountText(t.discount_rate)})` })));
}
/* A status line under a form: what happened, or what to fix. */
function formMessage() { return h("p", { class: "form-msg", role: "status", "aria-live": "polite" }); }
/* Only the latest outcome stays on screen: an earlier "Recorded" must not sit above a new error. */
function showMessage(el, text, ok) {
  for (const other of document.querySelectorAll(".form-msg")) if (other !== el) other.textContent = "";
  el.textContent = text; el.className = `form-msg ${ok ? "ok" : "bad"}`;
}

function newPortfolioCard(types, focus) {
  const name = h("input", { name: "name", maxlength: 60, required: true, placeholder: "e.g. Super fund", autocomplete: "off" });
  const tax = taxSelect(types, "INDIVIDUAL");
  const msg = formMessage();
  const form = h("form", { class: "form-grid", novalidate: true },
    field("Name", name), field("Owner's tax type", tax, "Sets the capital gains tax discount on its sales."),
    h("div", { class: "form-actions" }, h("button", { class: "btn primary", type: "submit", text: "Create portfolio" })), msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const p = await send("POST", "/api/portfolios", { name: name.value, tax_type: tax.value });
      afterChange();
      location.hash = portfolioHref(p);
    } catch (err) { showMessage(msg, err.message, false); }
  });
  const c = card("New portfolio", "One per owner or account, for example your own shares, a family trust or a self-managed super fund.", form);
  if (focus) setTimeout(() => { c.scrollIntoView({ block: "center" }); name.focus(); }, 0);
  return c;
}

function portfolioCard(p) {
  const c = h("a", { class: "card pf-card", href: portfolioHref(p) },
    h("div", { class: "pf-head" }, h("h2", { text: p.name }), p.archived ? h("span", { class: "tag muted", text: "Archived" }) : null),
    taxTag(p),
    p.archived ? h("p", { class: "hint", text: `${plural(p.sales, "sale")} kept for tax records.` })
      : !p.holdings ? h("p", { class: "hint pf-kv", text: "No holdings yet. Open it to record a buy." }) : h("dl", { class: "kv pf-kv" },
      h("dt", { text: "Value" }), h("dd", { text: money(p.value, 0) }),
      h("dt", { text: "Unrealised gain" }), h("dd", { class: signClass(p.gain), text: signed(p.gain, (v) => money(v, 0)) }),
      h("dt", { text: "Today" }), h("dd", { class: signClass(p.day_change), text: signed(p.day_change, (v) => money(v, 0)) }),
      h("dt", { text: "Holdings" }), h("dd", { text: `${fmt(p.holdings, 0)} ${p.holdings === 1 ? "company" : "companies"}, ${plural(p.open_parcels, "parcel")}` })));
  return c;
}

async function renderPortfolios(query) {
  app.replaceChildren(h("p", { class: "loading", text: "Loading portfolios..." }));
  const d = await getJSON("/api/portfolios");
  const active = d.portfolios.filter((p) => !p.archived), archived = d.portfolios.filter((p) => p.archived);
  const wantNew = new URLSearchParams(query || "").get("new") === "1";
  app.replaceChildren(...[
    pageHead("Portfolios", active.length ? `${plural(active.length, "active portfolio")}` : null),
    active.length ? h("div", { class: "cards" }, active.map(portfolioCard)) : h("p", { class: "empty", text: "No portfolios yet. Create one below, then record your first buy." }),
    archived.length ? h("details", { class: "archived" }, h("summary", {}, h("span", { class: "twisty", "aria-hidden": "true" }), `Archived (${archived.length})`),
      h("div", { class: "cards" }, archived.map(portfolioCard))) : null,
    h("div", { class: "cards", style: "margin-top:16px" }, newPortfolioCard(d.tax_types, wantNew)),
  ].filter(Boolean));
  if (!wantNew) window.scrollTo(0, 0);
}

/* Buy or sell form. Sell offers only what the portfolio holds, and which parcels go first. */
function tradeCard(d, reload) {
  const pf = d.portfolio;
  if (pf.archived) return card("Record a trade", null, h("p", { class: "empty", text: "This portfolio is archived. Unarchive it in Settings to record trades." }));
  let mode = "BUY";
  const msg = formMessage();
  const seg = h("div", { class: "segmented", role: "group", "aria-label": "Trade type" });
  const body = h("div");
  const date = () => h("input", { type: "date", name: "date", value: todayIso(), max: todayIso(), required: true });
  const num = (name, placeholder) => h("input", { name, inputmode: "decimal", autocomplete: "off", placeholder: placeholder || "" });

  function buyForm() {
    const code = h("input", { name: "asx_code", list: "company-list", maxlength: 6, autocomplete: "off", placeholder: "e.g. BHP", style: "text-transform:uppercase" });
    const method = h("select", { name: "method" }, ["PURCHASE", "DRP", "BONUS", "TRANSFER", "OTHER"].map((m) =>
      h("option", { value: m, text: { PURCHASE: "Purchase", DRP: "Dividend reinvestment (DRP)", BONUS: "Bonus issue", TRANSFER: "Transfer in", OTHER: "Other" }[m] })));
    return [field("Company", code), field("Units", num("units")), field("Price per share", num("price", "$")),
      field("Trade date", date()), field("Brokerage", num("brokerage", "$0.00"), "Adds to the cost base."), field("How acquired", method),
      field("Broker or account", h("input", { name: "broker", maxlength: 50, autocomplete: "off" })), field("Notes", h("input", { name: "notes", maxlength: 500, autocomplete: "off" }))];
  }
  function sellForm() {
    const codes = d.positions.map((p) => p.asx_code);
    const code = h("select", { name: "asx_code" }, codes.map((c) => h("option", { value: c, text: `${c} (${fmt(d.positions.find((p) => p.asx_code === c).units, 0)} units)` })));
    const order = h("select", { name: "order" });
    const fillOrder = () => {
      const parcels = d.parcels.filter((p) => p.asx_code === code.value);
      order.replaceChildren(h("option", { value: "fifo", text: "Oldest parcels first" }),
        h("option", { value: "min-tax", text: "Smallest taxable gain first" }),
        parcels.length > 1 ? parcels.map((p) => h("option", { value: `parcel:${p.holding_id}`, text: `Only parcel ${p.short_id}: ${fmt(p.units, 0)} units bought ${longDate(p.buy_date)}` })) : null);
    };
    code.addEventListener("change", fillOrder);
    fillOrder();
    return [field("Company", code), field("Units", num("units")), field("Price per share", num("price", "$")),
      field("Trade date", date()), field("Brokerage", num("brokerage", "$0.00"), "Reduces the capital proceeds."),
      field("Which parcels", order, "Smallest taxable gain counts this portfolio's CGT discount.")];
  }
  const form = h("form", { class: "form-grid", novalidate: true });
  const submit = h("button", { class: "btn primary", type: "submit" });
  function draw() {
    for (const b of seg.children) b.setAttribute("aria-pressed", b.dataset.mode === mode);
    form.replaceChildren(...(mode === "BUY" ? buyForm() : sellForm()), h("div", { class: "form-actions" }, submit), msg);
    submit.textContent = mode === "BUY" ? "Record buy" : "Record sale";
  }
  for (const [m, label] of [["BUY", "Buy"], ["SELL", "Sell"]]) {
    seg.append(h("button", { type: "button", "data-mode": m, text: label, disabled: m === "SELL" && !d.positions.length,
      onclick: () => { mode = m; msg.textContent = ""; draw(); } }));
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    if (data.order && data.order.startsWith("parcel:")) { data.parcel_id = data.order.slice(7); data.order = "fifo"; }
    submit.disabled = true;
    try {
      if (mode === "BUY") {
        const r = await send("POST", `/api/portfolios/${pf.portfolio_id}/buys`, data);
        afterChange();
        await reload(`Recorded: ${fmt(r.units, 0)} ${r.asx_code}, cost base ${money(r.cost_base)}.${pf.discount_rate > 0 ? ` CGT discount applies to sales from ${longDate(r.discount_from)}.` : ""}`);
      } else {
        const r = await send("POST", `/api/portfolios/${pf.portfolio_id}/sales`, data);
        afterChange();
        await reload(`Recorded: sold ${fmt(r.units, 0)} units from ${plural(r.parcels, "parcel")}, proceeds ${money(r.proceeds)}, ` +
          `${r.gain >= 0 ? "capital gain" : "capital loss"} ${money(Math.abs(r.gain))}` +
          `${pf.discount_rate > 0 ? ` (${fmt(r.discounted_units, 0)} units eligible for the discount)` : ""}.`);
      }
    } catch (err) { showMessage(msg, err.message, false); submit.disabled = false; }
  });
  draw();
  return card("Record a trade", null, seg, form);
}

function holdingsTable(lines) {
  const heads = ["Company", "Units", "Cost base", "Price", "Value", "Gain", "Today", "Action", "CGT discount from"];
  const numeric = new Set([1, 2, 3, 4, 5, 6]), optional = new Set([2, 3, 6, 8]);
  return h("div", { class: "table-wrap" }, h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, heads.map((x, i) => withHelp(h("th", { class: [numeric.has(i) ? "num" : "", optional.has(i) ? "opt" : ""].join(" ").trim() || null, tabindex: 0, text: x }), x)))),
    h("tbody", {}, lines.map((r) => clickableRow(r.asx_code,
      h("td", {}, h("span", { class: "code", text: r.asx_code }), h("div", { class: "name", text: r.company_name || "" })),
      h("td", { class: "num", text: fmt(r.units, 0) }),
      h("td", { class: "num opt", text: money(r.cost_base, 0) }),
      h("td", { class: "num opt", text: money(r.price) }),
      h("td", { class: "num", text: money(r.value, 0) }),
      h("td", { class: `num ${signClass(r.gain) || ""}`.trim(), text: signed(r.gain, (v) => money(v, 0)) }),
      h("td", { class: `num opt ${signClass(r.day_change) || ""}`.trim(), text: signed(r.day_change, (v) => money(v, 0)) }),
      h("td", {}, r.action ? badge(r.action) : h("span", { class: "hint", text: "not screened" })),
      h("td", { class: "opt", text: r.next_discount_date ? longDate(r.next_discount_date) : "eligible now" }))))));
}

function rowButton(label, cls, onClick) {
  return h("button", { type: "button", class: `btn small ${cls}`, text: label, onclick: (e) => { e.stopPropagation(); onClick(); } });
}

function parcelsCard(d, reload, msg) {
  const gets = d.portfolio.discount_rate > 0;
  const remove = async (p) => {
    if (!confirm(`Delete parcel ${p.short_id}: ${fmt(p.units, 0)} ${p.asx_code} bought ${longDate(p.buy_date)}?\n\nOnly for a parcel entered by mistake. This can't be undone.`)) return;
    try { await send("DELETE", `/api/parcels/${p.holding_id}`); afterChange(); await reload(`Deleted parcel ${p.short_id}.`); }
    catch (err) { showMessage(msg, err.message, false); }
  };
  const c = card("Open parcels", "Each buy is its own parcel for tax. Delete is for a parcel entered by mistake.",
    d.parcels.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, ["Company", "Parcel", "Bought", "Units", "Buy price", "Cost base", "Gain", gets ? "CGT discount from" : "CGT discount", ""].map((x, i) =>
        h("th", { class: [i >= 3 && i <= 6 ? "num" : "", [1, 4, 7].includes(i) ? "opt" : ""].join(" ").trim() || null, text: x })))),
      h("tbody", {}, d.parcels.map((p) => h("tr", { class: "static" },
        h("td", {}, h("span", { class: "code", text: p.asx_code }), p.method !== "PURCHASE" ? h("span", { class: "tag muted sm", text: p.method }) : null),
        h("td", { class: "opt mono", text: p.short_id }),
        h("td", { text: longDate(p.buy_date) }),
        h("td", { class: "num", text: fmt(p.units, 0) }),
        h("td", { class: "num opt", text: money(p.buy_price, 3) }),
        h("td", { class: "num", text: money(p.cost_base) }),
        h("td", { class: `num ${signClass(p.gain) || ""}`.trim(), text: signed(p.gain, (v) => money(v, 0)) }),
        h("td", { class: "opt", text: p.discount_from ? (p.discount_from <= todayIso() ? "eligible now" : longDate(p.discount_from)) : "n/a" }),
        h("td", { class: "act" }, rowButton("Delete", "danger", () => remove(p)))))))) : h("p", { class: "empty", text: "No open parcels." }));
  c.classList.add("wide");
  return c;
}

function salesCard(d, reload, msg) {
  const gets = d.portfolio.discount_rate > 0;
  const undo = async (s) => {
    if (!confirm(`Undo the sale of ${fmt(s.units, 0)} ${s.asx_code} on ${longDate(s.sell_date)}?\n\nThe units go back into the open parcel they came from.`)) return;
    try { await send("POST", `/api/parcels/${s.holding_id}/undo-sale`); afterChange(); await reload(`Sale undone: ${fmt(s.units, 0)} ${s.asx_code} are open again.`); }
    catch (err) { showMessage(msg, err.message, false); }
  };
  const c = card("Sales", "Every sale recorded, newest first. Undo is for a sale entered by mistake.",
    d.sales.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, ["Company", "Sold", "Units", "Proceeds", "Cost base", "Gain", "CGT discount", "Financial year", ""].map((x, i) =>
        h("th", { class: [i >= 2 && i <= 5 ? "num" : "", [3, 4, 7].includes(i) ? "opt" : "", i === 6 ? "opt2" : ""].join(" ").trim() || null, text: x })))),
      h("tbody", {}, d.sales.map((s) => h("tr", { class: "static" },
        h("td", {}, h("span", { class: "code", text: s.asx_code })),
        h("td", { text: longDate(s.sell_date) }),
        h("td", { class: "num", text: fmt(s.units, 0) }),
        h("td", { class: "num opt", text: money(s.proceeds) }),
        h("td", { class: "num opt", text: money(s.cost_base) }),
        h("td", { class: `num ${signClass(s.gain) || ""}`.trim(), text: signed(s.gain, (v) => money(v)) }),
        h("td", { class: "opt2", text: gets ? (s.discount_eligible ? "Yes" : "No") : "n/a" }),
        h("td", { class: "opt", text: s.financial_year }),
        h("td", { class: "act" }, rowButton("Undo", "", () => undo(s)))))))) : h("p", { class: "empty", text: "No sales recorded." }));
  c.classList.add("wide");
  return c;
}

function cgtCard(d) {
  const pf = d.portfolio;
  const c = card("Capital gains by financial year",
    `${pf.tax_type_label}: ${discountText(pf.discount_rate)}. Losses are set against gains that don't get the discount first.`,
    d.cgt.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, ["Financial year", "Sales", "Gains with discount", "Other gains", "Losses", "Net capital gain", "Losses carried forward"].map((x, i) =>
        h("th", { class: [i ? "num" : "", i === 1 || i === 6 ? "opt2" : ""].join(" ").trim() || null, text: x })))),
      h("tbody", {}, d.cgt.map((y) => h("tr", { class: "static" },
        h("td", { text: y.financial_year }), h("td", { class: "num opt2", text: fmt(y.sales, 0) }),
        h("td", { class: "num", text: money(y.discountable_gains) }), h("td", { class: "num", text: money(y.non_discountable_gains) }),
        h("td", { class: "num", text: money(y.capital_losses) }), h("td", { class: "num strong", text: money(y.net_capital_gain) }),
        h("td", { class: "num opt2", text: money(y.unused_losses) })))))) : h("p", { class: "empty", text: "Appears once a sale is recorded." }),
    h("p", { class: "hint", style: "margin-top:8px", text: "A record-keeping aid, not tax advice. Losses carried forward from earlier years aren't included; confirm anything you lodge with the ATO or your accountant." }));
  c.classList.add("wide");
  return c;
}

function settingsCard(d, reload) {
  const pf = d.portfolio;
  const msg = formMessage();
  const name = h("input", { name: "name", value: pf.name, maxlength: 60, autocomplete: "off" });
  const tax = taxSelect(d.tax_types, pf.tax_type);
  const save = h("form", { class: "form-grid", novalidate: true },
    field("Name", name),
    field("Owner's tax type", tax, d.sales.length ? "Changing it changes the CGT discount on the sales already recorded here." : null),
    h("div", { class: "form-actions" }, h("button", { class: "btn", type: "submit", text: "Save" })));
  save.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await send("PATCH", `/api/portfolios/${pf.portfolio_id}`, { name: name.value, tax_type: tax.value }); afterChange(); await reload("Saved."); }
    catch (err) { showMessage(msg, err.message, false); }
  });
  const open = d.parcels.length, sales = d.sales.length;
  const archive = pf.archived
    ? h("button", { class: "btn", type: "button", text: "Unarchive", onclick: async () => {
        try { await send("PATCH", `/api/portfolios/${pf.portfolio_id}`, { archived: false }); afterChange(); await reload("Unarchived."); }
        catch (err) { showMessage(msg, err.message, false); } } })
    : h("button", { class: "btn", type: "button", text: "Archive", disabled: open > 0, onclick: async () => {
        if (!confirm(`Archive ${pf.name}? It moves out of the menu and dashboard; its sales stay in the CGT report.`)) return;
        try { await send("PATCH", `/api/portfolios/${pf.portfolio_id}`, { archived: true }); afterChange(); await reload("Archived."); }
        catch (err) { showMessage(msg, err.message, false); } } });
  const del = h("button", { class: "btn danger", type: "button", text: "Delete portfolio", disabled: sales > 0, onclick: async () => {
    if (!confirm(`Delete ${pf.name}${open ? ` and its ${plural(open, "open parcel")}` : ""}? This can't be undone.`)) return;
    try { await send("DELETE", `/api/portfolios/${pf.portfolio_id}`); afterChange(); location.hash = "#/portfolios"; }
    catch (err) { showMessage(msg, err.message, false); } } });
  return card("Settings", null, save,
    h("div", { class: "danger-zone" },
      h("div", {}, archive, h("span", { class: "field-hint", text: open ? "Archive once every parcel is sold." : "Keeps the sale records for tax, out of the way." })),
      h("div", {}, del, h("span", { class: "field-hint", text: sales ? "Has sales, which are tax records: archive it instead." : "Removes it and any open parcels." }))),
    msg);
}

async function renderPortfolio(id, note) {
  if (!note) app.replaceChildren(h("p", { class: "loading", text: "Loading portfolio..." }));
  const d = await getJSON(`/api/portfolios/${encodeURIComponent(id)}`);
  const pf = d.portfolio;
  const reload = (text) => renderPortfolio(id, text);
  const notice = formMessage();
  if (note) showMessage(notice, note, true);
  const strip = d.positions.length ? portfolioStrip({ ...d.totals, holdings: d.positions }) : null;
  app.replaceChildren(...[
    h("a", { class: "back", href: "#/portfolios", text: "← Portfolios" }),
    h("div", { class: "page-head" }, h("h1", { text: pf.name }), taxTag(pf), pf.archived ? h("span", { class: "tag muted", text: "Archived" }) : null),
    notice,
    strip,
    d.positions.length ? h("div", { style: "margin-top:16px" }, holdingsTable(d.positions)) : null,
    h("div", { class: "cards dash", style: "margin-top:16px" }, tradeCard(d, reload), settingsCard(d, reload),
      parcelsCard(d, reload, notice), salesCard(d, reload, notice), cgtCard(d)),
  ].filter(Boolean));
  if (note) notice.scrollIntoView({ block: "nearest" }); else window.scrollTo(0, 0);
}

/* ---------- track record: is Sift right, what did I miss, what now ---------- */
const BULLISH = new Set(["BUY", "ACCUMULATE", "INVESTIGATE"]);
const BEARISH = new Set(["AVOID", "SELL"]);
const trackState = { horizon: null, version: "" };
const horizonText = (m) => (m === 1 ? "1 month" : `${m} months`);
const points = (v) => `${fmt(Math.abs(v), 1)} point${Math.abs(v) === 1 ? "" : "s"}`;
const signedPct = (v, dp = 1) => signed(v, (x) => fmt(x, dp) + "%");

/* One plain sentence per action, e.g. "BUY calls beat the average screened
   share by 3.2 points over 3 months; 62% of 140 did." */
function verdictLine(a, months) {
  const beat = a.avg_excess >= 0;
  const rate = a.beat_rate === null ? null : beat ? a.beat_rate : 100 - a.beat_rate;
  const intent = BULLISH.has(a.action) ? beat : BEARISH.has(a.action) ? !beat : null;
  const mark = intent === null ? ["na", "–", "Neither good nor bad for this action"] : intent ? ["pass", "✓", "As intended"] : ["fail", "✕", "The opposite of what this action intends"];
  return h("li", {},
    h("span", { class: `mark ${mark[0]}`, title: mark[2], "aria-label": mark[2], text: mark[1] }),
    h("span", { class: "verdict-text" }, badge(a.action),
      ` calls ${beat ? "beat" : "trailed"} the average screened share by ${points(a.avg_excess)} over ${horizonText(months)}` +
      (rate === null ? "." : `; ${fmt(rate, 0)}% of ${fmt(a.signals, 0)} ${beat ? "beat" : "trailed"} it.`),
      h("span", { class: `tag ${a.confidence === "solid" ? "" : "muted"} sm`, text: `Confidence: ${a.confidence}` })));
}
function orderLine(order) {
  if (order.status === "too early") return h("p", { class: "hint", text: "Order check: too early. It needs 30 monthly signals each of BUY, WATCH and AVOID." });
  return h("p", { class: `order ${order.status === "in order" ? "pos" : "neg"}`, text: order.status === "in order"
    ? "In order: BUY beat WATCH, and WATCH beat AVOID. The rules rank companies the right way round."
    : "Out of order: BUY, WATCH and AVOID don't line up best to worst. The rules need review." });
}

function verdictCard(d, months, setHorizon) {
  const v = d.verdict[months];
  const due = (d.status.results_due || []).find((r) => r.months === months);
  const seg = h("div", { class: "segmented periods", role: "group", "aria-label": "Period" }, d.horizons.map((m) =>
    h("button", { type: "button", "aria-pressed": String(m === months), text: horizonText(m), onclick: () => setHorizon(m) })));
  const body = v.actions.length
    ? [h("ul", { class: "verdict" }, v.actions.map((a) => verdictLine(a, months))), orderLine(v.order)]
    : [h("p", { class: "empty", text: !due ? "Results start once signals have been recorded for a month."
      : toDate(due.date) > new Date() ? `First ${months}-month results due ${longDate(due.date)}.`
      : d.version ? `No ${months}-month results yet for the rules of ${longDate(d.version)}: their signals aren't ${horizonText(months)} old yet.`
      : `First ${months}-month results arrive with the next nightly run.` })];
  const c = card("Is Sift accurate?", "Each company's first signal of each month, against the average total return (dividends included) of every company screened that night. Points are percentage points.", seg, body);
  c.classList.add("wide");
  return c;
}

function monthlyCard(d, months) {
  const rows = d.monthly.filter((r) => r.horizon_months === months);
  const actions = [...new Set(rows.map((r) => r.action))].sort((a, b) => d.verdict[months].actions.findIndex((x) => x.action === a) - d.verdict[months].actions.findIndex((x) => x.action === b));
  const monthsList = [...new Set(rows.map((r) => r.month))];
  const cell = (m, a) => rows.find((r) => r.month === m && r.action === a);
  const c = card(`By month, ${horizonText(months)} later`, "Average points above (+) or below (-) the average screened share, with the number of signals. Kept for good, after the daily detail is deleted.",
    rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, h("th", { text: "Signals given in" }), actions.map((a) => h("th", { class: "num", text: a })))),
      h("tbody", {}, monthsList.map((m) => h("tr", { class: "static" }, h("td", { text: toDate(m).toLocaleDateString("en-AU", { month: "long", year: "numeric" }) }),
        actions.map((a) => { const r = cell(m, a); return h("td", { class: `num ${r ? signClass(r.avg_excess) || "" : ""}`.trim(), text: r ? `${signed(r.avg_excess, (x) => fmt(x, 1))} (${r.signals})` : "" }); })))))) : h("p", { class: "empty", text: "Fills in month by month as results arrive." }));
  c.classList.add("wide");
  return c;
}

function signalTable(items, cols) {
  return h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
    h("thead", {}, h("tr", {}, cols.map((col) => h("th", { class: [col.num ? "num" : "", col.opt ? "opt" : ""].join(" ").trim() || null, text: col.label })))),
    h("tbody", {}, items.map((it) => clickableRow(it.asx_code, cols.map((col) => {
      const v = col.value(it);
      return h("td", { class: [col.num ? "num" : "", col.opt ? "opt" : "", col.cls ? col.cls(it) || "" : ""].join(" ").trim() || null }, v);
    }))))));
}
const companyCell = { label: "Company", value: (it) => [h("span", { class: "code", text: it.asx_code }), watchStar(it.watchlists), h("div", { class: "name", text: it.company_name || "" })] };

function actionableCard(d) {
  const a = d.actionable, p = d.proven, mos = d.rules.margin_of_safety;
  const hint = p.proven
    ? `Signals of the kind that has beaten the average at ${horizonText(p.horizon)}: ${p.actions.join(", ")}. Only those still more than ${fmt(mos, 0)}% below estimated value.`
    : `Nothing is proven yet (too few results), so this lists today's ${p.actions.join(", ")} signals on the rules' own terms, more than ${fmt(mos, 0)}% below estimated value.`;
  const cols = [companyCell,
    { label: "Signal", value: (it) => badge(it.action) },
    { label: "Since", opt: true, value: (it) => (it.since ? longDate(it.since) : NA) },
    { label: "Price then", num: true, opt: true, value: (it) => money(it.price_then) },
    { label: "Price now", num: true, value: (it) => money(it.price_now) },
    { label: "Margin of safety", num: true, cls: (it) => signClass(it.margin_of_safety_now), value: (it) => pct(it.margin_of_safety_now, 0) }];
  const group = (title, items, empty, extraCols = []) => [h("h3", { class: "sub-head", text: `${title} (${items.length})` }),
    items.length ? signalTable(items, cols.concat(extraCols)) : h("p", { class: "empty", text: empty })];
  const c = card("What should I look at now?", hint,
    group("New this week", a.new, "No new signals this week."),
    group("Still open", a.open, "None open."),
    group("Moved on", a.moved_on, "Nothing has moved on in the last 90 days.", [{ label: "Why", value: (it) => it.why }]));
  c.classList.add("wide");
  return c;
}

function missedCard(d) {
  const due = (d.status.results_due || [])[0];
  const empty = due && toDate(due.date) > new Date() ? `Appears once the first results arrive (${longDate(due.date)}).` : "None so far.";
  const later = { label: "Ahead of average", num: true, cls: (it) => signClass(it.excess_return), value: (it) => `${signed(it.excess_return, (x) => fmt(x, 1))} pts (${horizonText(it.horizon_months)})` };
  const c = card("What did I miss?", `BUY and INVESTIGATE calls on shares you didn't hold and didn't buy within ${d.rules.purchase_window_days} days, that beat the average by more than ${fmt(d.rules.missed_excess, 0)} points. First call per company; ★ marks your watchlists.`,
    d.missed.length ? signalTable(d.missed, [companyCell,
      { label: "Signal", value: (it) => badge(it.action) },
      { label: "Date", value: (it) => longDate(it.snapshot_date) },
      { label: "Price then", num: true, opt: true, value: (it) => money(it.price) },
      { label: "Price now", num: true, opt: true, value: (it) => money(it.price_now) },
      later,
      { label: "Still undervalued", value: (it) => (it.price_now === null ? NA : it.still_undervalued ? "Yes" : "No") }]) : h("p", { class: "empty", text: empty }),
    h("h3", { class: "sub-head", text: `Calls that saved money (${d.saved.length})` }),
    d.saved.length ? signalTable(d.saved, [companyCell,
      { label: "Signal", value: (it) => badge(it.action) },
      { label: "Date", value: (it) => longDate(it.snapshot_date) },
      { label: "Price then", num: true, opt: true, value: (it) => money(it.price) },
      { label: "Return", num: true, cls: (it) => signClass(it.total_return), value: (it) => signedPct(it.total_return) },
      later]) : h("p", { class: "empty", text: `AVOID calls on shares you didn't hold, and SELL calls on shares you did, that trailed the average by more than ${fmt(d.rules.missed_excess, 0)} points. ${empty}` }));
  c.classList.add("wide");
  return c;
}

async function renderTrackRecord() {
  app.replaceChildren(h("p", { class: "loading", text: "Loading track record..." }));
  const q = trackState.version ? `?version=${encodeURIComponent(trackState.version)}` : "";
  const d = await getJSON(`/api/track-record${q}`);
  const withData = d.horizons.filter((m) => d.verdict[m].actions.length);
  if (!trackState.horizon || !d.horizons.includes(trackState.horizon)) trackState.horizon = withData.includes(3) ? 3 : withData[0] || 1;
  const versionSelect = h("select", { "aria-label": "Rules version", class: "inline-select", onchange: (e) => { trackState.version = e.target.value; renderTrackRecord(); } },
    h("option", { value: "", text: "All rules versions" }),
    d.versions.map((v) => h("option", { value: v, selected: v === trackState.version, text: `Rules of ${longDate(v)}` })));
  const how = card("How Sift is judged", null, h("div", { class: "prose" },
    h("p", { text: "Each night Sift records what it said about every screened company. Those records are never edited, so later rule changes can't rewrite history." }),
    h("p", { text: "Each company's first signal of each month is scored after 1, 3, 6 and 12 months: its total return including dividends, minus the average for every company screened that night. A company that stops trading is scored at its last price. A BUY that beats the average was right; an AVOID that trails it was right." }),
    h("p", { text: `Confidence: too early under ${d.rules.too_early_below} signals, moderate up to ${d.rules.solid_above}, solid above that. The daily detail is kept for 14 months; the monthly results are kept for good.` })));
  const draw = () => {
    const m = trackState.horizon;
    app.replaceChildren(pageHead("Track record", "Is Sift right?", versionSelect),
      h("div", { class: "cards" },
        verdictCard(d, m, (x) => { trackState.horizon = x; draw(); }),
        actionableCard(d), missedCard(d), monthlyCard(d, m), trackingCard(d.status, false), how));
  };
  draw();
  window.scrollTo(0, 0);
}

/* ---------- watchlists: named lists to follow, with notes and triggers ---------- */
const watchlistHref = (w) => `#/watchlist/${w.watchlist_id}`;

async function loadWatchlistMenu() {
  const slot = document.getElementById("watchlist-menu-items");
  try {
    const d = await getJSON("/api/watchlists?brief=1");
    slot.replaceChildren(...d.watchlists.map((w) => h("a", { href: watchlistHref(w), text: w.name })));
  } catch (e) { /* the menu keeps its last list */ }
}

/* Each trigger with a tick when met now, or a dash when not. */
function triggerList(triggers) {
  if (!triggers || !triggers.length) return h("span", { class: "hint", text: "none" });
  return h("span", { class: "trigs" }, triggers.map((t) => h("span", { class: `trig ${t.met ? "met" : ""}`,
    "aria-label": `${t.label}: ${t.met ? "met" : "not met"}` },
    h("span", { class: "mark", "aria-hidden": "true", text: t.met ? "✓" : "–" }), t.label)));
}

/* Company page: which watchlists it's on, with a menu to change that. */
function watchNote(lists) {
  const on = lists.filter((l) => l.member);
  const el = h("p", { class: "hint watch-note", id: "watch-note" });
  if (!on.length) { el.hidden = true; return el; }
  add(el, ["On ", on.map((l, i) => [i ? ", " : "", h("a", { href: watchlistHref(l), text: l.name }),
    l.triggered ? " (trigger met)" : l.triggers && l.triggers.length ? " (triggers set)" : ""]), "."]);
  return el;
}
function watchButton(code, lists) {
  const wrap = h("div", { class: "watch-wrap" });
  const btn = h("button", { type: "button", class: "btn small watch-btn", "aria-haspopup": "true", "aria-expanded": "false" });
  const panel = h("div", { class: "watch-panel", role: "dialog", "aria-label": "Watchlists" });
  panel.hidden = true;
  const msg = formMessage();
  const paint = () => {
    const on = lists.filter((l) => l.member).length;
    btn.textContent = on ? "★ On watchlist" : "☆ Add to watchlist";
    btn.classList.toggle("on", on > 0);
    const note = document.getElementById("watch-note");
    if (note) note.replaceWith(watchNote(lists));
  };
  const draw = () => {
    const name = h("input", { maxlength: 60, placeholder: "New watchlist name", autocomplete: "off", "aria-label": "New watchlist name" });
    const create = h("form", { class: "watch-new" }, name, h("button", { type: "submit", class: "btn small", text: "Add" }));
    create.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const w = await send("POST", "/api/watchlists", { name: name.value, asx_code: code });
        lists.push({ ...w, member: true });
        afterChange(); paint(); draw();
      } catch (err) { showMessage(msg, err.message, false); }
    });
    panel.replaceChildren(h("h3", { text: "Watchlists" }),
      lists.length ? h("div", { class: "watch-options" }, lists.map((l) => {
        const box = h("input", { type: "checkbox", checked: l.member });
        box.addEventListener("change", async () => {
          try {
            if (box.checked) {
              await send("PUT", `/api/watchlists/${l.watchlist_id}/items/${code}`, {});
              Object.assign(l, { member: true, triggers: [], triggered: false, note: null });
            } else {
              const extra = l.note || (l.triggers && l.triggers.length) ? " Its note and triggers will be deleted." : "";
              if (!confirm(`Remove ${code} from ${l.name}?${extra}`)) { box.checked = true; return; }
              await send("DELETE", `/api/watchlists/${l.watchlist_id}/items/${code}`);
              l.member = false;
            }
            afterChange(); paint();
          } catch (err) { box.checked = !box.checked; showMessage(msg, err.message, false); }
        });
        return h("label", {}, box, l.name);
      })) : h("p", { class: "hint", text: "No watchlists yet. Name one to start it with this company." }),
      create, msg,
      h("p", { class: "hint", style: "margin:8px 0 0" }, "Notes and triggers: open the list from ", h("a", { href: "#/watchlists", text: "Watchlists" }), "."));
  };
  const setOpen = (open) => { panel.hidden = !open; btn.setAttribute("aria-expanded", open); };
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(panel.hidden); });
  panel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => setOpen(false));
  draw(); paint();
  add(wrap, [btn, panel]);
  return wrap;
}

async function renderWatchlists(query) {
  app.replaceChildren(h("p", { class: "loading", text: "Loading watchlists..." }));
  const d = await getJSON("/api/watchlists");
  const wantNew = new URLSearchParams(query || "").get("new") === "1";
  const name = h("input", { name: "name", maxlength: 60, placeholder: "e.g. Dividend ideas", autocomplete: "off" });
  const msg = formMessage();
  const form = h("form", { class: "form-grid", novalidate: true }, field("Name", name),
    h("div", { class: "form-actions" }, h("button", { class: "btn primary", type: "submit", text: "Create watchlist" })), msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { const w = await send("POST", "/api/watchlists", { name: name.value }); afterChange(); location.hash = watchlistHref(w); }
    catch (err) { showMessage(msg, err.message, false); }
  });
  const create = card("New watchlist", "Companies to follow without owning them. Add them here or with ☆ Add to watchlist on any company page.", form);
  app.replaceChildren(...[
    pageHead("Watchlists", d.watchlists.length ? plural(d.watchlists.length, "watchlist") : null),
    d.watchlists.length ? h("div", { class: "cards" }, d.watchlists.map((w) => h("a", { class: "card pf-card", href: watchlistHref(w) },
      h("div", { class: "pf-head" }, h("h2", { text: w.name })),
      h("p", { class: "hint", text: w.companies ? plural(w.companies, "company", "companies") : "No companies yet" }),
      w.triggered ? h("span", { class: "tag", text: `${plural(w.triggered, "trigger")} met` }) : null)))
      : h("p", { class: "empty", text: "No watchlists yet. Create one below." }),
    h("div", { class: "cards", style: "margin-top:16px" }, create),
  ].filter(Boolean));
  if (wantNew) setTimeout(() => { create.scrollIntoView({ block: "center" }); name.focus(); }, 0); else window.scrollTo(0, 0);
}

async function renderWatchlist(id, note) {
  if (!note) app.replaceChildren(h("p", { class: "loading", text: "Loading watchlist..." }));
  const d = await getJSON(`/api/watchlists/${encodeURIComponent(id)}`);
  const reload = (text) => renderWatchlist(id, text);
  const notice = formMessage();
  if (note) showMessage(notice, note, true);

  // Add or edit an entry: the same form, since saving a company already on the list updates it.
  const code = h("input", { name: "asx_code", list: "company-list", maxlength: 6, autocomplete: "off", placeholder: "BHP", style: "text-transform:uppercase" });
  const noteIn = h("input", { name: "note", maxlength: 500, autocomplete: "off", placeholder: "Why you're watching it" });
  const mos = h("input", { name: "mos_above", inputmode: "decimal", autocomplete: "off", placeholder: "e.g. 25" });
  const price = h("input", { name: "price_below", inputmode: "decimal", autocomplete: "off", placeholder: "e.g. 38.50" });
  const submit = h("button", { class: "btn primary", type: "submit", text: "Add to watchlist" });
  const cancel = h("button", { class: "btn", type: "button", text: "Cancel", hidden: true });
  const formMsg = formMessage();
  const form = h("form", { class: "form-grid", novalidate: true },
    field("Company", code), field("Note", noteIn),
    field("Trigger: margin of safety above (%)", mos, "Met while the share is at least this far below estimated value."),
    field("Trigger: price at or below ($)", price, "Met while the latest close is at or under this price."),
    h("div", { class: "form-actions" }, submit, cancel), formMsg);
  const formCard = card("Add a company", "Both triggers are optional; leave them blank to just follow the company.", form);
  const editing = (e) => {
    code.value = e.asx_code; code.readOnly = true; noteIn.value = e.note || "";
    mos.value = e.mos_above ?? ""; price.value = e.price_below ?? "";
    formCard.querySelector("h2").textContent = `Edit ${e.asx_code}`;
    submit.textContent = "Save changes"; cancel.hidden = false;
    formCard.scrollIntoView({ block: "center" }); noteIn.focus();
  };
  cancel.addEventListener("click", () => reload(null));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const c = code.value.trim().toUpperCase();
    if (!c) { showMessage(formMsg, "Enter an ASX code, such as BHP.", false); return; }
    try {
      await send("PUT", `/api/watchlists/${d.watchlist_id}/items/${encodeURIComponent(c)}`, { note: noteIn.value, mos_above: mos.value, price_below: price.value });
      afterChange();
      await reload(code.readOnly ? `Saved ${c}.` : `Added ${c}.`);
    } catch (err) { showMessage(formMsg, err.message, false); }
  });

  const remove = async (e) => {
    if (!confirm(`Remove ${e.asx_code} from ${d.name}?${e.note || e.triggers.length ? " Its note and triggers will be deleted." : ""}`)) return;
    try { await send("DELETE", `/api/watchlists/${d.watchlist_id}/items/${e.asx_code}`); afterChange(); await reload(`Removed ${e.asx_code}.`); }
    catch (err) { showMessage(notice, err.message, false); }
  };
  const heads = ["Score", "Company", "Price", "Margin of safety", "Valuation", "Action", "Triggers", "Note", ""];
  const table = d.items.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, heads.map((x, i) => {
      const cls = [i === 2 || i === 3 ? "num" : "", i === 0 ? "opt3" : "", i === 4 ? "opt4" : "", i === 2 || i === 7 ? "opt" : ""].join(" ").trim() || null;
      return FIELD_HELP[x] ? withHelp(h("th", { class: cls, tabindex: 0, text: x }), x) : h("th", { class: cls, text: x });
    }))),
    h("tbody", {}, d.items.map((e) => clickableRow(e.asx_code,
      h("td", { class: "opt3" }, e.scores ? [wheel(e.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }), h("span", { class: "score-total", text: sum(e.scores) })] : null),
      h("td", {}, h("span", { class: "code", text: e.asx_code }), e.held ? h("span", { class: "held-tag", text: "HELD" }) : null, h("div", { class: "name", text: e.company_name || "" })),
      h("td", { class: "num opt", text: money(e.price) }),
      h("td", { class: `num ${signClass(e.margin_of_safety_percent) || ""}`.trim(), text: pct(e.margin_of_safety_percent, 0) }),
      h("td", { class: "opt4" }, valuationPill(e.margin_of_safety_percent)),
      h("td", {}, e.action ? badge(e.action) : h("span", { class: "hint", text: "not valued" })),
      h("td", {}, triggerList(e.triggers)),
      h("td", { class: "opt" }, h("div", { class: "name note-cell", title: e.note || "", text: e.note || "" })),
      h("td", { class: "act" }, rowButton("Edit", "", () => editing(e)), " ", rowButton("Remove", "danger", () => remove(e)))))))) : null;

  const rename = h("input", { name: "name", value: d.name, maxlength: 60, autocomplete: "off" });
  const setMsg = formMessage();
  const settings = h("form", { class: "form-grid", novalidate: true }, field("Name", rename),
    h("div", { class: "form-actions" }, h("button", { class: "btn", type: "submit", text: "Rename" }),
      h("button", { class: "btn danger", type: "button", text: "Delete watchlist", onclick: async () => {
        if (!confirm(`Delete ${d.name}${d.items.length ? ` and its ${plural(d.items.length, "company", "companies")}, notes and triggers` : ""}? This can't be undone.`)) return;
        try { await send("DELETE", `/api/watchlists/${d.watchlist_id}`); afterChange(); location.hash = "#/watchlists"; }
        catch (err) { showMessage(setMsg, err.message, false); } } })), setMsg);
  settings.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await send("PATCH", `/api/watchlists/${d.watchlist_id}`, { name: rename.value }); afterChange(); await reload("Renamed."); }
    catch (err) { showMessage(setMsg, err.message, false); }
  });
  const met = d.items.filter((e) => e.triggered).length;
  app.replaceChildren(...[
    h("a", { class: "back", href: "#/watchlists", text: "← Watchlists" }),
    pageHead(d.name, d.items.length ? `${plural(d.items.length, "company", "companies")}${met ? `, ${plural(met, "trigger")} met` : ""}` : null),
    notice,
    table || h("p", { class: "empty", text: "No companies yet. Add one below, or use ☆ Add to watchlist on any company page." }),
    h("div", { class: "cards dash", style: "margin-top:16px" }, formCard, card("Settings", null, settings)),
  ]);
  if (note) notice.scrollIntoView({ block: "nearest" }); else window.scrollTo(0, 0);
}

/* ---------- settings: theme ---------- */
const THEME_KEY = "sift-theme";
function currentThemeChoice() {
  try { return localStorage.getItem(THEME_KEY) || "system"; } catch (e) { return "system"; }
}
function applyTheme(choice) {
  if (choice === "light" || choice === "dark") document.documentElement.setAttribute("data-theme", choice);
  else document.documentElement.removeAttribute("data-theme");
  try { choice === "system" ? localStorage.removeItem(THEME_KEY) : localStorage.setItem(THEME_KEY, choice); } catch (e) { /* not saved; still applied */ }
  for (const b of document.querySelectorAll("[data-theme-choice]")) b.setAttribute("aria-pressed", b.dataset.themeChoice === choice);
  slots.forEach((sl) => { delete sl.el.dataset.w; }); // charts pick up the new colours on redraw
  drawSlots();
}
(function initSettings() {
  const btn = document.getElementById("settings-btn"), panel = document.getElementById("settings");
  const setOpen = (open) => { panel.hidden = !open; btn.setAttribute("aria-expanded", open); };
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(panel.hidden); });
  panel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });
  for (const b of document.querySelectorAll("[data-theme-choice]")) b.addEventListener("click", () => applyTheme(b.dataset.themeChoice));
  applyTheme(currentThemeChoice());
})();

/* ---------- routing ---------- */
const ROUTES = [
  [/^#\/company\/([A-Za-z0-9.]+)$/, "company", (m) => renderCompany(m[1].toUpperCase())],
  [/^#\/screener(?:\?(.*))?$/, "screener", (m) => { presetScreener(m[1]); return renderScreener(); }],
  [/^#\/track-record$/, "track-record", () => renderTrackRecord()],
  [/^#\/watchlists(?:\?(.*))?$/, "watchlists", (m) => renderWatchlists(m[1])],
  [/^#\/watchlist\/([0-9a-f-]{36})$/, "watchlists", (m) => renderWatchlist(m[1])],
  [/^#\/portfolios(?:\?(.*))?$/, "portfolios", (m) => renderPortfolios(m[1])],
  [/^#\/portfolio\/([0-9a-f-]{36})$/, "portfolios", (m) => renderPortfolio(m[1])],
  [/^(#\/?)?$/, "dashboard", () => renderDashboard()],
];
let previousPage = null;
let currentHash = null;
function route() {
  hideTip();
  closeMenus();
  slots.length = 0;
  const hash = location.hash;
  let found = ROUTES.find(([re]) => re.test(hash));
  if (!found) { location.replace("#/"); return; }
  const [re, page, render] = found;
  if (page === "company" && currentHash && !currentHash.startsWith("#/company/")) previousPage = currentHash;
  currentHash = hash;
  markCurrent(page);
  render(hash.match(re)).catch((err) => app.replaceChildren(h("p", { class: "error", text: `Could not load: ${err.message}` })));
}
window.addEventListener("hashchange", route);
initNav();
route();
