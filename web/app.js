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
  q: "", sector: "", actions: new Set(), passing: false, held: false,
  sort: { key: "action", dir: "asc" }, shown: PAGE_SIZE,
};
const cache = { screener: null };

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
const thresholds = () => (cache.screener && cache.screener.thresholds) || DEFAULT_THRESHOLDS;
const FIELD_HELP = {
  "Score": () => "Score wheel total out of 30. Five spokes (Value, Performance, Health, Dividend, Momentum), each counting six yes/no checks. Higher is better. Open a company to see every check.",
  "Company": () => "ASX code and company name. HELD marks shares you own.",
  "Sector": () => "Industry sector from Yahoo Finance. Financial Services and Real Estate are valued with a dividend discount model; every other sector with a discounted cash flow model.",
  "Price": () => "Latest closing share price on the ASX.",
  "Margin of safety": (t) => `How far the price sits below estimated intrinsic value: (value - price) / value. Positive means cheaper than estimated value; negative means dearer. Passes the value test above ${t.margin_of_safety}%.`,
  "ROE": (t) => `Return on equity: net profit after tax / shareholders' equity. How well the company earns on its owners' money. Passes the value test above ${t.roe}%.`,
  "Debt/equity": (t) => `Total debt / shareholders' equity. Lower means less financial risk. Passes the value test below ${fmt(t.debt_to_equity, 2)}.`,
  "Yield (grossed up)": (t) => `Dividend yield including franking credits: cash dividend x (1 + franking % x 30/70) / price. Companies based outside Australia are treated as unfranked. Passes the value test above ${t.yield}%.`,
  "Grossed-up yield": (t) => `Dividend yield including franking credits: cash dividend x (1 + franking % x 30/70) / price. Companies based outside Australia are treated as unfranked. Passes the value test above ${t.yield}%.`,
  "Value tests": () => "The four core value tests, in order: margin of safety, ROE, debt/equity, grossed-up yield. A tick passes; a cross fails or has no data. All four must pass for an overall pass.",
  "Action": () => "Suggested next step from the rules; the reason is on the company page. Shares you don't hold: BUY, INVESTIGATE, WATCH, AVOID, IGNORE. Shares you hold: SELL, REVIEW, ACCUMULATE, HOLD. A research prompt, not financial advice.",
  "Earnings quality": () => "Operating cash flow / net profit over the last three years. STRONG at 100% or more, ADEQUATE 80% to 99%, WEAK below 80%. Profit that isn't turning into cash is a warning sign. Not assessed for banks, insurers and REITs.",
  "Price signal": () => "Price trend. UPTREND: at or above the 200-day average. DOWNTREND: below it. NEW LOWS: below it and in the bottom 10% of the 52-week range. Needs 200 days of prices.",
  "Dividend trend": () => "Over up to five years. CUT: the latest dividend is more than 10% below last year's or the earlier median. GROWING: more than 5% above the oldest. STEADY otherwise. NONE: pays no dividend.",
  "Fundamentals trend": () => "Latest versus oldest of the last three annual reports. DECLINING: ROE down more than 2 points or revenue down more than 5%. IMPROVING: up by those amounts. STABLE otherwise. Ignores the share price.",
  "Margin of safety trend": () => "Change in margin of safety over the last 30 days, in percentage points. Positive means the share is getting cheaper relative to its estimated value. More than 5 points counts as momentum.",
  "Value-trap risk": () => "Yes when the margin of safety passes but fundamentals are DECLINING: the share looks cheap, possibly for a good reason.",
  "Data confidence": () => "How complete the inputs are, from 11 checks (price, market capitalisation, profit, revenue, equity, debt, cash flows, years of reports, days of prices). HIGH: 10 or 11. MEDIUM: 8 or 9. LOW: 7 or fewer.",
  "P/E": () => "Price-to-earnings ratio: share price / earnings per share. Lower can mean cheaper. Graham's ceiling was 15.",
  "P/B": () => "Price-to-book ratio: share price / book value (equity) per share. Graham's ceiling was 1.5.",
  "Price to free cash flow": () => "Share price / free cash flow per share, latest year. Lower means more cash generated for each dollar paid.",
  "EV/EBIT": () => "Enterprise value (market capitalisation + debt - cash) / earnings before interest and tax. Compares companies regardless of how they are funded.",
  "ROIC": () => "Return on invested capital: net profit / (debt + equity - cash). The return on all the capital the business uses, not just shareholders' money.",
  "Cash dividend yield": () => "Cash dividend / share price, before franking credits.",
  "Payout ratio": () => "Dividend / earnings per share. Above 100% the dividend exceeds profit; above 150% it is flagged as a likely one-off.",
  "Country": () => "Country of domicile from Yahoo Finance. Companies outside Australia are treated as paying no franking credits.",
};

function placeTipBelow(el, nodes) {
  const r = el.getBoundingClientRect();
  showTip({ clientX: r.left, clientY: r.bottom }, nodes);
}

/* Adds an explanation to a heading or label: shown on mouse hover and
   keyboard focus, and via a small "i" button for touch screens. */
function withHelp(el, label) {
  const help = FIELD_HELP[label];
  if (!help) return el;
  const nodes = () => [h("div", { class: "t-title", text: label }), h("div", { text: help(thresholds()) })];
  el.classList.add("has-help");
  el.addEventListener("pointermove", (e) => { if (e.pointerType !== "touch") showTip(e, nodes()); });
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => placeTipBelow(el, nodes()));
  el.addEventListener("blur", hideTip);
  const info = h("button", { type: "button", class: "info", "aria-label": `What is ${label}?`, text: "i" });
  info.addEventListener("click", (e) => { e.stopPropagation(); placeTipBelow(info, nodes()); });
  info.addEventListener("keydown", (e) => e.stopPropagation()); // Enter on the "i" shouldn't sort the column
  el.append(info);
  return el;
}
document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".info")) hideTip(); });

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

function legend(series, rect = false) {
  if (series.length < 2) return null;
  return h("div", { class: "legend" }, series.map((sr) =>
    h("span", {}, h("span", { class: `key${rect ? " rect" : ""}`, style: `background:var(${sr.color})` }), sr.name)));
}

function tableView(headers, rows) {
  return h("details", { class: "table-view" }, h("summary", { text: "Show data table" }),
    h("div", { class: "table-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, headers.map((x, i) => h("th", { class: i ? "num" : null, text: x })))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((v, i) => h("td", { class: i ? "num" : null, text: v }))))))));
}

/* Line chart with crosshair tooltip. series: [{name, color, points:[[iso, value]]}] */
function lineChart({ series, yFmt, height = 220, zeroLine = false, label, width = 640 }) {
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
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 && zeroLine ? "base-line" : "grid-line" }));
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
      ...series.map((sr, k) => lookups[k].has(iso) ? tipRow(yFmt(lookups[k].get(iso)), sr.name, sr.color) : null).filter(Boolean)]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(hit);
  return h("div", {}, legend(series), svg);
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
    svg.append(s("text", { x: labelW - 10, y: y + 14, "text-anchor": "end", style: "fill:var(--ink-2);font-size:12px", text: it.label }));
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
  { key: "sector", label: "Sector", opt: true, value: (r) => r.sector },
  { key: "current_price", label: "Price", num: true, narrowHide: true, value: (r) => r.current_price },
  { key: "margin_of_safety_percent", label: "Margin of safety", num: true, value: (r) => r.margin_of_safety_percent },
  { key: "roe", label: "ROE", num: true, opt: true, value: (r) => r.roe },
  { key: "debt_to_equity", label: "Debt/equity", num: true, opt: true, value: (r) => r.debt_to_equity },
  { key: "grossed_up_dividend_yield", label: "Yield (grossed up)", num: true, opt: true, value: (r) => r.grossed_up_dividend_yield },
  { key: "tests", label: "Value tests", opt: true, value: (r) => ["mos_ok", "roe_ok", "de_ok", "yield_ok"].filter((k) => r[k] === "Y").length },
  { key: "action", label: "Action", value: (r) => cache.screener.actions.indexOf(r.action) },
];

function filteredRows() {
  const q = state.q.trim().toLowerCase();
  return cache.screener.rows.filter((r) =>
    (!q || r.asx_code.toLowerCase().includes(q) || (r.company_name || "").toLowerCase().includes(q)) &&
    (!state.sector || r.sector === state.sector) &&
    (state.actions.size === 0 || state.actions.has(r.action)) &&
    (!state.passing || r.overall === "Y") &&
    (!state.held || r.held !== null));
}

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
    h("td", {}, h("span", { class: "code", text: r.asx_code }), r.held !== null ? h("span", { class: "held-tag", text: "HELD" }) : null,
      h("div", { class: "name", text: r.company_name || "" })),
    h("td", { class: "opt", text: r.sector || NA }),
    h("td", { class: "num opt2", text: money(r.current_price) }),
    h("td", { class: "num", text: pct(r.margin_of_safety_percent, 0) }),
    h("td", { class: "num opt", text: pct(r.roe, 1) }),
    h("td", { class: "num opt", text: fmt(r.debt_to_equity, 2) }),
    h("td", { class: "num opt", text: pct(r.grossed_up_dividend_yield, 1) }),
    h("td", { class: "opt" }, ynMarks(r)),
    h("td", {}, badge(r.action)));
}

async function renderScreener() {
  if (!cache.screener) {
    app.replaceChildren(h("p", { class: "loading", text: "Loading companies..." }));
    cache.screener = await getJSON("/api/screener");
  }
  const d = cache.screener;
  document.getElementById("asof").textContent =
    `${d.rows.length} companies${d.as_of ? ", valuations as at " + longDate(d.as_of) : ""}`;

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
    headRow.append(withHelp(h("th", { class: [col.num ? "num" : "", col.opt ? "opt" : "", col.narrowHide ? "opt2" : ""].join(" ").trim() || null, "data-sort": col.key,
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

  app.replaceChildren(
    chips,
    h("div", { class: "controls" }, search, sector, toggle("passing", "Passes all four tests"), toggle("held", "Held only"), count),
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
    app.replaceChildren(h("a", { class: "back", href: "#/", text: "← All companies" }), h("p", { class: "error", text: err.message }));
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
    mos === null ? null : h("p", { class: `headline ${mos >= 0 ? "status-good" : "status-bad"}`,
      text: mos >= 0 ? `${fmt(mos, 0)}% below estimated value` : `${fmt(-mos, 0)}% above estimated value` }),
    chartSlot((w) => valuationBars([
      { label: "Share price", value: c.current_price, emphasis: true },
      { label: "Estimated value", value: c.dcf_intrinsic_value },
      { label: "Graham Number", value: c.graham_number },
    ], w)));

  const wheelCard = card("Score", `${total} of ${d.checks_per_axis * d.axes.length} checks passed. Hover a spoke to see its checks.`,
    chartSlot((w) => wheel(scores, d.axes, d.checks_per_axis, { size: Math.min(300, w - 160), details: d.scores })));

  const breakdown = card("Score breakdown", "Six yes/no checks per spoke. No data never counts as a pass.",
    d.axes.map((a) => h("div", { class: "axis-block" },
      h("h3", {}, h("span", { text: a }), h("span", { text: `${d.scores[a].score} / ${d.checks_per_axis}` })),
      checklist(d.scores[a].checks))));

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
      ["Payout ratio", pct(c.payout_ratio, 0)], ["Country", c.country || NA]]
      .flatMap(([k, v]) => [withHelp(h("dt", { tabindex: 0, text: k }), k), h("dd", { text: v })])));

  // Price chart
  let priceCard;
  if (d.prices.length >= 2) {
    const ma = movingAverage(d.prices);
    const series = [{ name: "Close", color: "--s1", points: d.prices }];
    if (ma.length >= 2) series.push({ name: "200-day average", color: "--s2", points: ma });
    priceCard = card("Share price, last 12 months",
      ma.length >= 2 ? null : `200-day average appears once 200 days of prices are stored (${d.prices.length} so far).`,
      chartSlot((w) => lineChart({ series, yFmt: (v) => money(v), label: `${c.asx_code} closing price`, width: w, height: 260 })),
      tableView(["Date", "Close"], d.prices.slice(-30).reverse().map((p) => [longDate(p[0]), money(p[1])])));
  } else {
    priceCard = card("Share price, last 12 months", "Not enough price history yet.");
  }
  priceCard.classList.add("wide");

  const mosCard = d.mos_history.length >= 2
    ? card("Margin of safety over time", "Above zero: trading below estimated value.",
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
  const divCard = d.reports.some((r) => r.dividends_per_share)
    ? card("Dividends per share", "Cash dividends, before franking credits.",
      chartSlot((w) => columnChart({ categories: fy, yFmt: (v) => money(v), label: "Dividends per share by year", width: w,
        series: [{ name: "Dividend per share", color: "--s1", values: d.reports.map((r) => r.dividends_per_share) }] })),
      tableView(["Year", "Dividend per share"], d.reports.map((r, i) => [fy[i], money(r.dividends_per_share, 3)])))
    : card("Dividends per share", "No dividends recorded.");

  const held = d.position ? h("p", { class: "hint", text:
    `You hold ${fmt(d.position.units, 0)} units, cost base ${money(d.position.cost_base)}.` +
    (d.position.next_discount_date ? ` ${fmt(d.position.units_pending_discount, 0)} units qualify for the CGT discount from ${longDate(d.position.next_discount_date)}.` : "") }) : null;

  document.getElementById("asof").textContent = `Valuation as at ${longDate(c.as_of_date)}`;
  app.replaceChildren(...[
    h("a", { class: "back", href: "#/", text: "← All companies" }),
    h("div", { class: "co-head" },
      h("h1", { text: c.asx_code }),
      h("span", { class: "sub", text: [c.company_name, c.sector, c.industry].filter(Boolean).join("  |  ") }),
      h("span", { class: "co-price", text: money(c.current_price) }),
      badge(c.action)),
    h("p", { class: "reason", text: c.action_reason }),
    held,
    h("div", { class: "cards" }, wheelCard, valuation, tests, breakdown, markers, ratios, priceCard, mosCard, finCard, divCard),
  ].filter(Boolean)); // native replaceChildren would print a null as "null"
  drawSlots();
  window.scrollTo(0, 0);
}

/* ---------- routing ---------- */
function route() {
  hideTip();
  const m = location.hash.match(/^#\/company\/([A-Za-z0-9.]+)$/);
  const render = m ? renderCompany(m[1].toUpperCase()) : renderScreener();
  render.catch((err) => app.replaceChildren(h("p", { class: "error", text: `Could not load: ${err.message}` })));
}
window.addEventListener("hashchange", route);
route();
