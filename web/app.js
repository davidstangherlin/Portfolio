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
let PAGE_SIZE = 100;  // rows before "Show more": the rows_shown preference (§35)
/* Who Sift is acting for and their Preferences (§35), filled from /api/me as the page starts. */
const SETTING_DEFAULTS = { theme: "dark", compact: false, wrap_text: false, help_tips: true, reduce_motion: false,
  chart_patterns: false, chart_tables: false, show_hover_buttons: false, keyboard_shortcuts: true,
  start_page: "dashboard", search_scope: "auto", rows_shown: 100 };
const me = { user: null, by: null, settings: { ...SETTING_DEFAULTS } };

const state = {
  q: "", sector: "", actions: new Set(), passing: false, held: false, watchlist: "",
  sort: { key: "action", dir: "asc" }, shown: PAGE_SIZE,
};
const cache = { screener: null, thresholds: null, status: null, portfolios: null, adminSettings: null };

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
/* Field explanations and the Help page share one source, web/knowledge.json
   (also the Word glossary's source). {placeholders} take the live thresholds. */
const KNOWLEDGE = { categories: [], entries: [] };
const FIELD_HELP = {};            // UI label -> (thresholds) => text
const ESTIMATED_VALUE_HELP = {};  // valuation method -> (thresholds) => text
function fillThresholds(text, t = thresholds()) {
  return text.replace(/\{(margin_of_safety|roe|debt_to_equity|yield)\}/g, (_, k) => (k === "debt_to_equity" ? fmt(t[k], 2) : String(t[k])));
}
const knowledgeReady = fetch("/static/knowledge.json", { headers: { Accept: "application/json" } })
  .then((res) => (res.ok ? res.json() : Promise.reject(new Error(res.status))))
  .then((kb) => {
    Object.assign(KNOWLEDGE, kb);
    for (const e of kb.entries) {
      for (const label of e.labels || []) FIELD_HELP[label] = (t) => fillThresholds(e.hover || e.definition, t);
      if (e.id === "dcf" || e.id === "ddm") ESTIMATED_VALUE_HELP[e.id.toUpperCase()] = (t) => fillThresholds(e.hover, t);
    }
  })
  .catch(() => { /* pages still work; explanations and Help are missing until a reload */ });

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
document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".info, .info-svg")) hideTip(); });

/* ---------- data ---------- */
/* Every response carries the version of Sift's page files. If it changes
   while this tab is open (after a git pull), the page reloads itself on
   the next click, so it never runs old code against a new server. */
let siftVersion = null, siftUpdated = false;
function noteVersion(res) {
  const v = res.headers.get("X-Sift-Version");
  if (!v) return;
  if (siftVersion === null) siftVersion = v;
  else if (v !== siftVersion) siftUpdated = true;
}
async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  noteVersion(res);
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
    extras.map((x) => h("span", {}, x.band ? h("span", { class: "key band", "aria-hidden": "true" })
      : h("span", { class: `dkey${x.outline ? " outline" : ""}`, "aria-hidden": "true", text: x.symbol }), x.name)));
}

function tableView(headers, rows) {
  return h("details", { class: "table-view", open: me.settings.chart_tables }, h("summary", { text: "Show data table" }),
    h("div", { class: "table-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, headers.map((x, i) => h("th", { class: i ? "num" : null, text: x })))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((v, i) => h("td", { class: i ? "num" : null, text: v }))))))));
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
let hatchCount = 0;
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
  // Preferences, "Patterns as well as colours": the second series and on are hatched (§35).
  const fills = series.map((sr, si) => {
    if (!me.settings.chart_patterns || si === 0) return `var(${sr.color})`;
    const id = `hatch-${++hatchCount}`;
    svg.append(s("defs", {}, s("pattern", { id, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: `rotate(${si === 1 ? 45 : 135})` },
      s("rect", { width: 6, height: 6, fill: `var(${sr.color})`, "fill-opacity": 0.3 }),
      s("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: `var(${sr.color})`, "stroke-width": 3 }))));
    return `url(#${id})`;
  });
  categories.forEach((cat, ci) => {
    const gx = m.l + band * ci + (band - groupW) / 2;
    svg.append(s("text", { x: m.l + band * ci + band / 2, y: H - 8, "text-anchor": "middle", text: cat }));
    series.forEach((sr, si) => {
      const v = sr.values[ci];
      if (v === null || v === undefined) return;
      const x = gx + si * (barW + gap);
      const bar = s("path", { d: barPath(x, barW, Y(0), Y(v)), fill: fills[si] });
      const hitArea = s("rect", { x: x - gap, y: m.t, width: barW + gap * 2, height: ph, fill: "transparent" });
      const over = (e) => { bar.setAttribute("fill-opacity", 0.75); showTip(e, [h("div", { class: "t-head", text: cat }), tipRow(yFmt(v), sr.name, sr.color)]); };
      hitArea.addEventListener("pointermove", over);
      hitArea.addEventListener("pointerleave", () => { bar.removeAttribute("fill-opacity"); hideTip(); });
      svg.append(bar, hitArea);
    });
  });
  return h("div", {}, legend(series, true), svg);
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
/* A star after the code for companies on a watchlist, naming the lists. */
const watchStar = (lists) => (lists && lists.length
  ? h("span", { class: "watch-star", title: `On watchlist: ${lists.join(", ")}`, "aria-label": `On watchlist ${lists.join(", ")}`, text: "★" }) : null);

/* One headline figure: label (with its explanation), value, small note. */
function statTile(label, valueText, cls, note) {
  return h("div", { class: "stat" },
    withHelp(h("div", { class: "stat-label", tabindex: 0, text: label }), label),
    h("div", { class: `stat-value ${cls || ""}`.trim(), text: valueText }),
    note ? h("div", { class: "stat-note", text: note }) : null);
}

function card(title, hint, ...children) {
  return h("section", { class: "card" }, h("h2", { text: title }), hint ? h("p", { class: "hint", text: hint }) : null, children);
}

/* ---------- short selling (ASIC, docs/kb/features/volume-and-short-selling.md) ---------- */
/* A shorted share can still be bought, with care: an amber caution beside
   the action, never a change to it (src/screening/short_caution.py). */
const CAUTION_WORDS = { HIGH: "Heavily shorted", ELEVATED: "Shorted" };
function cautionTag(level, iconOnly = false, held = false) {
  if (!level) return null;
  const words = `Caution: ${CAUTION_WORDS[level].toLowerCase()}, expect bigger price swings` +
    (held ? ". Not a reason to sell on its own: open the company for what it means." : "");
  return h("span", { class: `caution-tag${level === "HIGH" ? " high" : ""}`, title: words, "aria-label": words, role: "img" },
    h("span", { "aria-hidden": "true", text: "!" }), iconOnly ? null : h("span", { text: CAUTION_WORDS[level] }));
}

/* Coattail, Most shorted: the bearish side of the smart money. */
async function renderShorts() {
  app.replaceChildren(pageHead("Coattail", "Most shorted"), coattailTabs("shorts"), h("p", { class: "loading", text: "Loading..." }));
  const d = await getJSON("/api/coattail/shorts");
  const company = (r) => r.in_sift ? nameCell(r, "SHARE") : h("td", {}, h("span", { class: "code", text: r.asx_code }), h("div", { class: "name", text: r.company_name || "" }));
  const table = (rows, none) => rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
    h("thead", {}, h("tr", {}, [["Company"], ["Sector", "opt"], ["% short", "num"], ["Change, a month", "num"], ["Shares short", "num opt"]].map(([t, cl]) => h("th", { scope: "col", class: cl || null, text: t })))),
    h("tbody", {}, rows.map((r) => {
      const cells = [company(r), h("td", { class: "opt", text: r.sector || "" }), h("td", { class: "num strong" }, pct(r.short_percent, 2), cautionTag(r.caution, true)),
        h("td", { class: `num ${signClass(r.change_points) === "pos" ? "neg" : signClass(r.change_points) === "neg" ? "pos" : ""}`.trim(),
          text: r.change_points === null ? NA : `${r.change_points > 0 ? "+" : ""}${fmt(r.change_points, 2)} pts` }),
        h("td", { class: "num opt", text: fmt(r.short_positions, 0) })];
      return r.in_sift ? rowTo(`#/company/${r.asx_code}`, ...cells) : h("tr", {}, cells);
    }))))
    : h("p", { class: "empty", text: none });
  const empty = d.as_of ? "None." : "No ASIC reports loaded yet: they arrive with the nightly run (Short Positions step).";
  app.replaceChildren(pageHead("Coattail", "Most shorted"), COATTAIL_NOTE(), coattailTabs("shorts"),
    h("p", { class: "hint page-note" }, d.as_of ? `ASIC's short position report of ${longDate(d.as_of)}, ASX shares only. ` : "", helpLink("short-selling")),
    h("div", { class: "cards" },
      (() => { const c = card("Most shorted", "The largest share of the company sold short.", table(d.most, empty)); c.classList.add("wide"); return c; })(),
      (() => { const c = card("Shorts rising fastest", "The biggest rise in % sold short over about a month.", table(d.rising, empty)); c.classList.add("wide"); return c; })()));
  window.scrollTo(0, 0);
}

/* ---------- page furniture ---------- */
function pageHead(title, sub, ...extra) {
  return h("div", { class: "page-head" }, h("h1", { text: title }), sub ? h("span", { class: "sub", text: sub }) : null, extra);
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
function closeSettings() {  // the avatar menu (§35)
  document.getElementById("user-menu").hidden = true;
  document.getElementById("user-btn").setAttribute("aria-expanded", "false");
}
/* Everything that pops up from the menu bar, e.g. after moving to another page. */
function closeMenus() {
  closeDropdowns();
  closeSettings();
  nav.classList.remove("open");
  menuBtn.setAttribute("aria-expanded", "false");
}
/* Pages that sit under a menu heading: ASX Stocks, ETFs and LICs are under Screener. */
const NAV_GROUPS = { screener: "screener", etfs: "screener", lics: "screener" };
function markCurrent(page) {
  if (page === "etf") page = "etfs";
  if (page === "lic") page = "lics";
  const group = NAV_GROUPS[page] || page;
  for (const a of nav.querySelectorAll(":scope > a, .dd-menu a[data-nav]")) {
    if (a.dataset.nav === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  for (const dd of nav.querySelectorAll(".dd")) dd.classList.toggle("current", dd.dataset.nav === group);
  const help = document.getElementById("help-btn");
  if (page === "help") help.setAttribute("aria-current", "page"); else help.removeAttribute("aria-current");
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
  else lines.push(`Last nightly run${run.started ? " " + dateTime(run.started) : ""} did not finish. See logs\\${run.file}. A log that simply stops was usually ended from outside: the task stopped when the PC stopped being idle, its window was closed, or the PC slept (README, Daily Automation, has the right Task Scheduler settings).`);
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
  try {
    cache.status = await getJSON("/api/status");
    paintChip(cache.status);
  } catch (e) { /* chip stays hidden */ }
}

/* Find a company: type a code or part of a name, pick from the list or press Enter. */
function goTerm(e) { location.hash = `#/help/${e.id}`; }
function findCompany(q) {
  const up = q.trim().toUpperCase();
  const list = cache.companies || [];
  if (!up) return null;
  return list.find((c) => c.code === up) || list.find((c) => c.code.startsWith(up)) ||
    list.find((c) => (c.name || "").toUpperCase().includes(up)) || null;
}
/* ---------- search scope (§32): everything, or this page ---------- */
const PAGE_LABELS = { dashboard: "Dashboard", screener: "ASX Stocks", etfs: "ETFs", etf: "this ETF", lics: "LICs", lic: "this LIC",
  company: "this company", "track-record": "Track record", coattail: "Coattail", help: "Help", admin: "Admin",
  watchlists: "Watchlists", portfolios: "Portfolios", search: "Search results", profile: "Profile", preferences: "Preferences",
  kb: "Developer knowledge base" };
const searchScope = { page: "dashboard", mode: "all" };
/* The dashboard and the results page search everything by default; every other page, itself.
   Admins also have the developer knowledge base, the default on its own pages (§36). */
const canSearchKb = () => !!(me.user && me.user.admin);
function setSearchPage(page) {
  searchScope.page = page;
  const pref = me.settings.search_scope;  // Preferences, User experience (§35)
  if (page === "kb" && canSearchKb() && pref !== "all") searchScope.mode = "devkb";
  else searchScope.mode = pref === "all" || pref === "page" ? pref : page === "dashboard" || page === "search" ? "all" : "page";
  paintSearchScope();
}
function paintSearchScope() {
  const input = document.getElementById("nav-search-input"), btn = document.getElementById("search-scope");
  if (!input || !btn) return;
  const all = searchScope.mode === "all", kb = searchScope.mode === "devkb";
  const label = kb ? "the developer knowledge base" : PAGE_LABELS[searchScope.page] || "this page";
  input.placeholder = matchMedia("(max-width: 480px)").matches ? "Search" : all ? "Search everything" : kb ? "Search developer articles" : `Search ${label}`;
  input.setAttribute("aria-label", all ? "Search everything in Sift" : `Search ${label}`);
  btn.title = all ? "Searching everything. Click to choose where to search." : `Searching ${label}. Click to choose where to search.`;
  btn.setAttribute("aria-label", `Search scope: ${all ? "everything" : label}`);
  btn.classList.toggle("page", !all);
}
function initSearchScope() {
  const btn = document.getElementById("search-scope"), menu = document.getElementById("search-scope-menu");
  const pick = (mode) => { searchScope.mode = mode; paintSearchScope(); menu.hidden = true; btn.setAttribute("aria-expanded", "false"); document.getElementById("nav-search-input").focus(); };
  const draw = () => {
    const label = PAGE_LABELS[searchScope.page] || "this page";
    const choices = [["all", "Everything"], ["page", `This page: ${label}`]];
    if (canSearchKb()) choices.push(["devkb", "Developer knowledge base (admins)"]);
    menu.replaceChildren(...choices.map(([mode, title]) =>
      h("button", { type: "button", role: "menuitemradio", "aria-checked": String(searchScope.mode === mode), onclick: () => pick(mode) },
        h("span", { class: "scope-tick", "aria-hidden": "true", text: searchScope.mode === mode ? "✓" : "" }),
        h("span", { class: "scope-title", text: title }))));
  };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = menu.hidden;
    if (open) draw();
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
  });
  menu.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.focus(); } });
}

/* This page: a page with a search box (the lists, Help) gets the words in
   it; any other page highlights the words where they appear, Enter again
   for the next. */
const findState = { q: "", hits: [], i: -1 };
function clearFind() {
  for (const m of app.querySelectorAll("mark.find-hit")) m.replaceWith(document.createTextNode(m.textContent));
  app.normalize();
  Object.assign(findState, { q: "", hits: [], i: -1 });
}
function thisPageSearch(q) {
  const box = app.querySelector(".tf-search, .page-search");
  if (box) {
    box.value = q;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.scrollIntoView({ block: "center" });
    return;
  }
  findInPage(q);
}
function findInPage(q) {
  const form = document.getElementById("nav-search");
  if (q && q.toLowerCase() === findState.q && findState.hits.length) {
    findState.hits[findState.i]?.classList.remove("current");
    findState.i = (findState.i + 1) % findState.hits.length;
  } else {
    clearFind();
    if (!q) return;
    const needle = q.toLowerCase(), walker = document.createTreeWalker(app, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement.closest("script, style, input, textarea, select, svg, .find-skip") || !n.nodeValue.toLowerCase().includes(needle)
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      let rest = node;
      for (let at = rest.nodeValue.toLowerCase().indexOf(needle); at >= 0; at = rest.nodeValue.toLowerCase().indexOf(needle)) {
        const hit = rest.splitText(at);
        rest = hit.splitText(needle.length);
        const mark = h("mark", { class: "find-hit", text: hit.nodeValue });
        hit.replaceWith(mark);
        findState.hits.push(mark);
      }
    }
    Object.assign(findState, { q: needle, i: 0 });
  }
  if (!findState.hits.length) {  // not on this page: look everywhere instead
    const input = document.getElementById("nav-search-input");
    input.value = ""; input.blur();
    cache.flash = `"${q}" isn't on that page, so these are results from everywhere.`;
    location.hash = `#/search?q=${encodeURIComponent(q)}`;
    return;
  }
  const cur = findState.hits[findState.i];
  cur.classList.add("current");
  cur.scrollIntoView({ block: "center" });
  placeTipBelow(form, [h("div", { text: `${findState.i + 1} of ${plural(findState.hits.length, "match", "matches")} on this page. Enter for the next.` })]);
  setTimeout(hideTip, 2200);
}

function initSearch() {
  const form = document.getElementById("nav-search"), input = document.getElementById("nav-search-input");
  initSearchScope();
  const go = (c) => { input.value = ""; input.blur(); closeMenus(); location.hash = FUNDS[c.type] ? fundHref(c.type, c.code) : `#/company/${c.code}`; };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (searchScope.mode === "page") { thisPageSearch(q); return; }
    if (searchScope.mode === "devkb") {
      if (q) { input.value = ""; input.blur(); closeMenus(); location.hash = `#/search?q=${encodeURIComponent(q)}&scope=devkb`; }
      return;
    }
    const exactCode = (cache.companies || []).find((x) => x.code === q.toUpperCase());
    if (exactCode) { go(exactCode); return; }
    if (q) { input.value = ""; input.blur(); closeMenus(); location.hash = `#/search?q=${encodeURIComponent(q)}`; return; }
    const term = exactCode ? null : findTerm(q);
    const c = exactCode || (term ? null : findCompany(q));
    const clear = () => { input.value = ""; input.blur(); closeMenus(); };
    if (term) { clear(); goTerm(term); return; }
    if (c) { go(c); return; }
    if (q && searchKnowledge(q).length) { clear(); location.hash = `#/help?q=${encodeURIComponent(q)}`; return; }
    form.classList.add("no-match");
    placeTipBelow(form, [h("div", { text: q ? `No company, ETF, LIC or help topic matches "${q}".` : "Type an ASX code, part of a company or ETF name, or a term such as franking." })]);
    setTimeout(() => { form.classList.remove("no-match"); hideTip(); }, 1800);
  });
  input.addEventListener("input", (e) => {
    // Picking from the list fills in the exact code; typing goes through Enter.
    if (e.inputType && e.inputType !== "insertReplacementText") return;
    const c = (cache.companies || []).find((x) => x.code === input.value.trim().toUpperCase());
    if (c) { go(c); return; }
    const term = KNOWLEDGE.entries.find((x) => x.title === input.value.trim());
    if (term) { input.value = ""; input.blur(); closeMenus(); goTerm(term); }
  });
  getJSON("/api/companies").then((list) => {
    cache.companies = list;
    knowledgeReady.then(() => document.getElementById("company-list").replaceChildren(
      ...list.map((c) => h("option", { value: c.code, label: `${FUNDS[c.type] ? c.type : "Share"}: ${c.name || c.code}` })),
      ...KNOWLEDGE.entries.map((e) => h("option", { value: e.title, label: "Help" }))));
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
  document.getElementById("user-btn").addEventListener("click", () => closeDropdowns());
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
        withHelp(h("th", { class: [i === 2 ? "center" : "", i === 0 || i === 3 ? "opt2" : ""].join(" ").trim() || null, tabindex: 0, text: x }), x)))),
      h("tbody", {}, d.top.map((r) => clickableRow(r.asx_code,
        h("td", { class: "opt2" }, wheel(r.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }), h("span", { class: "score-total", text: sum(r.scores) })),
        h("td", {}, h("span", { class: "code", text: r.asx_code }), h("div", { class: "name", text: r.company_name || "" })),
        h("td", { class: `center tabular ${signClass(r.margin_of_safety_percent) || ""}`.trim(), text: pct(r.margin_of_safety_percent, 0) }),
        h("td", { class: "opt2" }, valuationPill(r.margin_of_safety_percent)),
        h("td", {}, badge(r.action))))))) : h("p", { class: "empty", text: "No BUY or INVESTIGATE signals today." }),
    foot);
  c.classList.add("wide");
  return c;
}

/* Biggest movers on the last trading day, by percentage: 5 each way for
   screener shares (with their score wheel), ETFs and LICs. Rows open the
   company or fund. `d` is the dashboard payload, for the wheel's axes. */
function moversCard(m, d) {
  const groups = [["Shares in the screener", m.shares, (c) => `#/company/${c}`, "SHARE"],
    ["ETFs", m.etfs, (c) => fundHref("ETF", c), "ETF"], ["LICs", m.lics, (c) => fundHref("LIC", c), "LIC"]].filter(([, x]) => x && x.as_of);
  if (!groups.length) {
    return card("Biggest movers", null, h("p", { class: "empty", text: "Appears once Sift has two closing prices to compare." }));
  }
  const day = groups[0][1].as_of;
  const price = (v) => money(v, v !== null && v !== undefined && v < 1 ? 3 : 2);
  const side = (title, rows, href, kind, none) => {
    const share = kind === "SHARE";
    return h("div", { class: "table-wrap" }, h("table", { class: "grid compact movers" },
      h("thead", {}, h("tr", {}, share ? withHelp(h("th", { tabindex: 0, text: "Score" }), "Score") : null, h("th", { text: title }),
        h("th", { class: "num opt2", text: "Close" }), h("th", { class: "num", text: "Day move" }))),
      h("tbody", {}, rows.length ? rows.map((r) => rowTo(href(r.asx_code),
        share ? h("td", { class: "mover-score" }, r.scores ? [wheel(r.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }),
          h("span", { class: "score-total", text: sum(r.scores) })] : null) : null,
        nameCell(r, kind), h("td", { class: "num opt2 tabular", text: price(r.price) }), retCell(r.change_percent, "tabular")))
        : h("tr", {}, h("td", { colspan: share ? 4 : 3, class: "hint", text: none })))));
  };
  const c = card("Biggest movers", `Percentage change from the previous close to the close on ${longDate(day)}. ★ watchlist, HELD in a portfolio.`,
    groups.map(([label, x, href, kind]) => h("div", { class: "movers-group" },
      h("h3", { class: "sub-head" }, label, h("span", { class: "hint", text: ` · ranked from ${fmt(x.traded, 0)}${x.as_of !== day ? `, to ${longDate(x.as_of)}` : ""}` })),
      h("div", { class: "movers-cols" },
        side("Biggest rises", x.up, href, kind, "Nothing rose."),
        side("Biggest falls", x.down, href, kind, "Nothing fell.")))));
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
    ? [h("p", { class: "hint", text: `Recording since ${longDate(t.first_date)}: ${plural(t.days_recorded, "night")}, ${plural(t.signals_recorded, "signal")}.` }),
      t.headline ? h("ul", { class: "verdict rules compact" }, verdictLine(t.headline, t.headline.horizon_months)) : null,
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
    pf.holdings.length ? sectionLine(pf.sections) : null,
    ...dashboardLayout(d, [
      { id: "attention", title: "Needs attention", build: () => attentionCard(d) },
      { id: "changes", title: "What changed", build: () => changesCard(d) },
      { id: "movers", title: "Biggest movers", build: () => (d.movers ? moversCard(d.movers, d) : null) },
      { id: "top", title: "Top opportunities", build: () => topCard(d) },
      { id: "etfs", title: "ETFs", build: () => fundDashCard("ETF", d.etfs) },
      { id: "lics", title: "LICs", build: () => fundDashCard("LIC", d.lics) },
      { id: "portfolios", title: "Portfolios", build: () => (pf.portfolios.length > 1 ? portfoliosCard(pf.portfolios) : null) },
      { id: "actions", title: "Today's suggested actions", build: () => actionsCard(d) },
      { id: "tracking", title: "Track record", build: () => trackingCard(d.tracking) },
      { id: "notices", title: "Director and holder notices", build: () => noticesDashCard(d.notices || []) },
    ]),
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
function afterChange() { cache.screener = null; if (window.SiftUI) window.SiftUI.invalidate(); loadPortfolioMenu(); loadWatchlistMenu(); }

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

function holdingsText(p) {
  const s = p.sections;
  const etfs = s && s.ETF ? s.ETF.holdings : 0, lics = s && s.LIC ? s.LIC.holdings : 0, shares = p.holdings - etfs - lics;
  const parts = [shares ? `${fmt(shares, 0)} ${shares === 1 ? "company" : "companies"}` : null, etfs ? plural(etfs, "ETF") : null,
    lics ? plural(lics, "LIC") : null].filter(Boolean);
  return `${parts.join(" and ")}, ${plural(p.open_parcels, "parcel")}`;
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
      h("dt", { text: "Holdings" }), h("dd", { text: holdingsText(p) })));
  return c;
}

async function renderPortfolios(query) {
  app.replaceChildren(h("p", { class: "loading", text: "Loading portfolios..." }));
  const d = await getJSON("/api/portfolios");
  const active = d.portfolios.filter((p) => !p.archived), archived = d.portfolios.filter((p) => p.archived);
  const wantNew = new URLSearchParams(query || "").get("new") === "1";
  app.replaceChildren(...[
    pageHead("Portfolios", active.length ? `${plural(active.length, "active portfolio")}` : null,
      h("a", { class: "btn", href: "#/portfolios/import", text: "Import from a broker" })),
    active.length ? h("div", { class: "cards" }, active.map(portfolioCard)) : h("p", { class: "empty", text: "No portfolios yet. Create one below, then record your first buy." }),
    archived.length ? h("details", { class: "archived" }, h("summary", {}, h("span", { class: "twisty", "aria-hidden": "true" }), `Archived (${archived.length})`),
      h("div", { class: "cards" }, archived.map(portfolioCard))) : null,
    h("div", { class: "cards", style: "margin-top:16px" }, newPortfolioCard(d.tax_types, wantNew)),
  ].filter(Boolean));
  if (!wantNew) window.scrollTo(0, 0);
}

/* ---------- importing a broker's export (docs/kb/features/broker-import.md) ---------- */
const IMPORT_FIELDS = [["code", "ASX code"], ["side", "Buy or sell"], ["units", "Units"], ["price", "Price"], ["avg_cost", "Average cost"],
  ["total_cost", "Total cost"], ["date", "Date"], ["brokerage", "Brokerage"], ["details", "Details (B 100 BHP @ 45.00)"],
  ["debit", "Debit"], ["credit", "Credit"], ["market", "Market"], ["currency", "Currency"]];
const IMPORT_STATUS = { new: ["Ready", "under"], duplicate: ["Already in Sift", "none"], check: ["Check the code", "fair"], skip: ["Skipped", "none"] };

async function renderImport() {
  app.replaceChildren(pageHead("Import from a broker", null), h("p", { class: "loading", text: "Loading..." }));
  const pf = await getJSON("/api/portfolios");
  const portfolios = pf.portfolios.filter((p) => !p.archived);
  const st = { filename: null, content: null, broker: "", kind: "", mapping: {}, holdings_date: todayIso(), portfolio_id: portfolios.length ? portfolios[0].portfolio_id : "", d: null };
  const msg = formMessage(), out = h("div");
  const brokerSel = h("select", { "aria-label": "Broker", onchange: () => { st.broker = brokerSel.value; if (st.content) load(); } },
    h("option", { value: "", text: "Work it out from the file" }));
  const file = h("input", { type: "file", accept: ".csv,.txt,.xlsx,.xlsm", "aria-label": "Your broker's export" });
  file.addEventListener("change", () => {
    const f = file.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => { st.filename = f.name; st.content = String(reader.result).split(",")[1] || ""; st.mapping = {}; st.kind = ""; load(); };
    reader.readAsDataURL(f);
  });

  async function load() {
    showMessage(msg, "Reading the file...", true);
    try {
      st.d = await send("POST", "/api/portfolios/import/preview", { filename: st.filename, content: st.content, broker: st.broker || null,
        kind: st.kind || null, mapping: st.mapping, holdings_date: st.holdings_date, portfolio_id: st.portfolio_id || null });
      msg.textContent = "";
      if (brokerSel.options.length === 1) brokerSel.append(...st.d.brokers.map((b) => h("option", { value: b.broker_id, text: b.name })));
      brokerSel.value = st.broker || "";
      draw();
    } catch (err) { showMessage(msg, err.message, false); out.replaceChildren(); }
  }

  function draw() {
    const d = st.d;
    const ticks = new Map(d.lines.map((l) => [l.row, l.include]));
    const kindSeg = h("div", { class: "segmented", role: "group", "aria-label": "What the file holds" },
      [["trades", "Trade history"], ["holdings", "Holdings now"]].map(([k, t]) => h("button", { type: "button", "aria-pressed": String(d.kind === k), text: t,
        onclick: () => { st.kind = k; load(); } })));
    const when = d.kind === "holdings" ? h("label", { class: "field" }, h("span", { class: "field-label", text: "Bought on" }),
      h("input", { type: "date", value: d.holdings_date, max: todayIso(), onchange: (e) => { st.holdings_date = e.target.value; load(); } }),
      h("span", { class: "field-hint", text: "A holdings file has no buy dates. Use your earliest buy date if you know it; you can edit each parcel later. It decides when the CGT discount applies." })) : null;
    const cols = h("div", { class: "import-map" }, IMPORT_FIELDS.filter(([f]) => d.kind === "trades" ? !["avg_cost", "total_cost"].includes(f) : !["side", "date", "brokerage", "details", "debit", "credit"].includes(f)).map(([f, label]) =>
      h("label", { class: "field" }, h("span", { class: "field-label", text: label }),
        h("select", { onchange: (e) => { st.mapping[f] = e.target.value === "" ? "" : Number(e.target.value); load(); } },
          h("option", { value: "", text: "Not in this file", selected: d.mapping[f] === undefined }),
          d.headings.map((hd, i) => h("option", { value: i, text: hd, selected: d.mapping[f] === i }))))));
    const newName = h("input", { maxlength: 60, placeholder: "e.g. CommSec", value: "", "aria-label": "New portfolio name" });
    const taxSel = h("select", { "aria-label": "Tax type" }, pf.tax_types.map((t) => h("option", { value: t.tax_type, text: t.label })));
    const dest = h("select", { "aria-label": "Import into", onchange: (e) => { st.portfolio_id = e.target.value === "new" ? "" : e.target.value; newBox.hidden = e.target.value !== "new"; load(); } },
      portfolios.map((p) => h("option", { value: p.portfolio_id, text: p.name, selected: p.portfolio_id === st.portfolio_id })),
      h("option", { value: "new", text: "A new portfolio...", selected: !st.portfolio_id }));
    const newBox = h("div", { class: "import-new", hidden: !!st.portfolio_id }, newName, taxSel);
    const c = d.counts;
    const rows = d.lines.map((l) => {
      const [label, pill] = IMPORT_STATUS[l.status];
      const box = h("input", { type: "checkbox", checked: l.include, disabled: l.status === "skip" || l.status === "duplicate", "aria-label": `Import row ${l.row}`,
        onchange: (e) => ticks.set(l.row, e.target.checked) });
      return h("tr", { class: "static" }, h("td", {}, box), h("td", { class: "num opt", text: l.row }), h("td", { text: l.date ? longDate(l.date) : "" }),
        h("td", { class: "strong", text: l.code || "" }), h("td", { class: "opt", text: l.side === "SELL" ? "Sell" : l.side === "BUY" ? "Buy" : "" }),
        h("td", { class: "num", text: l.units === null ? "" : fmt(l.units, 0) }), h("td", { class: "num", text: l.price === null ? "" : money(l.price, 3) }),
        h("td", { class: "num opt", text: l.brokerage ? money(l.brokerage) : "" }),
        h("td", { title: l.reason || "" }, h("span", { class: `pill ${pill}`, text: label }), l.reason ? h("div", { class: "sub-text import-reason", text: l.reason }) : null));
    });
    const go = h("button", { type: "button", class: "btn primary", text: "Import ticked lines", onclick: async () => {
      if (!st.portfolio_id && !newName.value.trim()) { showMessage(msg2, "Name the new portfolio first.", false); return; }
      try {
        const r = await send("POST", "/api/portfolios/import", { filename: st.filename, content: st.content, broker: st.broker || d.broker, kind: d.kind,
          mapping: d.mapping, holdings_date: d.holdings_date, portfolio_id: st.portfolio_id || null, new_portfolio: st.portfolio_id ? null : newName.value,
          tax_type: taxSel.value, rows: [...ticks].filter(([, on]) => on).map(([row]) => row) });
        afterChange();
        out.replaceChildren(card("Imported", null,
          h("p", {}, `${plural(r.bought, "buy", "buys")} and ${plural(r.sold, "sale")} added to ${r.portfolio}.`),
          r.problems.length ? [h("p", { class: "error", text: `${plural(r.problems.length, "line")} couldn't be added:` }),
            h("ul", {}, r.problems.map((p) => h("li", { text: `Row ${p.row} (${p.code}): ${p.reason}` })))] : null,
          h("p", {}, h("a", { class: "btn primary", href: `#/portfolio/${r.portfolio_id}`, text: "Open the portfolio" }))));
        window.scrollTo(0, 0);
      } catch (err) { showMessage(msg2, err.message, false); }
    } });
    const msg2 = formMessage();
    out.replaceChildren(h("div", { class: "cards" },
      card("2. Check what was found", `${d.filename}: ${d.broker !== "other" ? `looks like ${d.brokers.find((b) => b.broker_id === d.broker).name}. ` : ""}${plural(c.new, "line")} ready${c.check ? `, ${c.check} to check` : ""}${c.duplicate ? `, ${c.duplicate} already in Sift` : ""}${c.skip ? `, ${c.skip} skipped` : ""}.`,
        kindSeg, when,
        d.missing.length ? h("p", { class: "error", text: `Choose the ${d.missing.join(" and ")} column below.` }) : null,
        h("details", { class: "import-cols", open: d.missing.length > 0 }, h("summary", { text: "Columns" }), cols)),
      card("3. Where to put them", null, h("label", { class: "field" }, h("span", { class: "field-label", text: "Import into" }), dest), newBox,
        h("p", { class: "hint", text: "Lines already in that portfolio (same code, date, units and price) are left out, so importing the same file twice adds nothing." }))),
      h("div", { class: "table-wrap" }, h("table", { class: "grid compact import-lines" },
        h("thead", {}, h("tr", {}, [["", null], ["Row", "num opt"], ["Date"], ["Code"], ["Side", "opt"], ["Units", "num"], ["Price", "num"], ["Brokerage", "num opt"], ["Status"]]
          .map(([t, cl]) => h("th", { scope: "col", class: cl || null, text: t })))),
        h("tbody", {}, rows))),
      h("div", { class: "form-actions" }, go, msg2));
  }

  app.replaceChildren(pageHead("Import from a broker", "Your broker's export into one of your portfolios"),
    h("p", { class: "hint page-note" }, "Download your trade history (best: exact dates for capital gains tax) or your current holdings from your broker as CSV or Excel, then choose the file. Nothing is saved until you press Import. ", helpLink("broker-import")),
    h("div", { class: "cards" }, card("1. Choose the file", "From CommSec, Sharesies, CMC Invest, nabtrade, ANZ, Moomoo, Tiger, Interactive Brokers, eToro, Selfwealth, Stake, Superhero or a spreadsheet of your own. Only ASX shares come in; other markets are listed and skipped.",
      h("label", { class: "field" }, h("span", { class: "field-label", text: "Your broker's export" }), file),
      h("label", { class: "field" }, h("span", { class: "field-label", text: "Broker" }), brokerSel), msg)),
    out);
  window.scrollTo(0, 0);
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
    const code = h("input", { name: "asx_code", list: "company-list", maxlength: 6, autocomplete: "off", placeholder: "e.g. BHP or VAS", style: "text-transform:uppercase" });
    const method = h("select", { name: "method" }, ["PURCHASE", "DRP", "BONUS", "TRANSFER", "OTHER"].map((m) =>
      h("option", { value: m, text: { PURCHASE: "Purchase", DRP: "Dividend reinvestment (DRP)", BONUS: "Bonus issue", TRANSFER: "Transfer in", OTHER: "Other" }[m] })));
    return [field("Company or ETF", code), field("Units", num("units")), field("Price per share or unit", num("price", "$")),
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
    return [field("Company or ETF", code), field("Units", num("units")), field("Price per share or unit", num("price", "$")),
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
      h("td", {}, r.action ? badge(r.action) : h("span", { class: "hint", text: "not screened" }), cautionTag(r.short_caution, true, true)),
      h("td", { class: "opt", text: r.next_discount_date ? longDate(r.next_discount_date) : "eligible now" }))))));
}

function rowButton(label, cls, onClick) {
  return h("button", { type: "button", class: `btn small ${cls}`, text: label, onclick: (e) => { e.stopPropagation(); onClick(); } });
}

function fundTag(d, code) {
  return (d.etf_codes || []).includes(code) ? kindTag("ETF") : (d.lic_codes || []).includes(code) ? kindTag("LIC") : null;
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
        h("td", {}, h("span", { class: "code", text: p.asx_code }), fundTag(d, p.asx_code), p.method !== "PURCHASE" ? h("span", { class: "tag muted sm", text: p.method }) : null),
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
        h("td", {}, h("span", { class: "code", text: s.asx_code }), fundTag(d, s.asx_code)),
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
    d.positions.length ? h("div", { style: "margin-top:16px" }, holdingsSections(d.positions, d.sections, `portfolio:${d.portfolio.portfolio_id}`)) : null,
    h("div", { class: "cards dash", style: "margin-top:16px" }, tradeCard(d, reload), settingsCard(d, reload),
      parcelsCard(d, reload, notice), salesCard(d, reload, notice), cgtCard(d)),
  ].filter(Boolean));
  if (note) notice.scrollIntoView({ block: "nearest" }); else window.scrollTo(0, 0);
}

/* ---------- Coattail: following the smart money (§31) ---------- */
const coattailState = { hideIndex: false, months: 12, sort: "held" };
/* Who's investing order: each key's figure, largest first; ties by value held, then name. */
const HOLDER_SORTS = [["held", "Companies held", (g) => g.positions.length], ["adding", "Adding", (g) => g.adding],
  ["cutting", "Cutting", (g) => g.cutting], ["value", "Value held", (g) => g.value]];
const COATTAIL_MONTHS = [[3, "Reported in the last 3 months"], [6, "Last 6 months"], [12, "Last 12 months"], [0, "Any time"]];
let coattailData = null;
const countText = (v) => new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 1 }).format(Math.abs(v));
const sharesText = (v) => (v === null || v === undefined ? NA : countText(v));
const sharesChange = (v) => (v === null || v === undefined ? NA : v === 0 ? "no change" : `${v > 0 ? "+" : "-"}${countText(v)}`);

/* The holdings that pass the page's filters. */
function coattailHoldings(d) {
  const st = coattailState;
  const cutoff = st.months ? monthsBefore(new Date().toISOString().slice(0, 10), st.months) : null;
  return d.holdings.filter((m) => (!st.hideIndex || !m.index_fund) && (!cutoff || (m.date_reported && m.date_reported >= cutoff)));
}
/* One entry per manager: for each company, its largest listed holding (the
   institution line usually includes its own funds, so lines aren't added
   up), whether that holding grew or shrank, its value now, and the average
   score wheel of the companies held. */
function coattailManagers(d, holdings) {
  const map = new Map();
  for (const m of holdings) {
    const g = map.get(m.manager_id) || { id: m.manager_id, name: m.manager, byCode: new Map() };
    const lines = g.byCode.get(m.asx_code) || [];
    lines.push(m);
    g.byCode.set(m.asx_code, lines);
    map.set(m.manager_id, g);
  }
  return [...map.values()].map((g) => {
    const positions = [...g.byCode].map(([code, lines]) => {
      lines.sort((a, b) => (b.shares ?? -1) - (a.shares ?? -1));
      const main = lines[0], c = d.companies[code];
      return { code, company: c, main, others: lines.slice(1), value: main.shares !== null && c.price ? main.shares * c.price : null };
    }).sort((a, b) => (b.value ?? -1) - (a.value ?? -1) || a.code.localeCompare(b.code));
    const avg = d.axes.map((_, i) => positions.reduce((t, p) => t + p.company.scores[i], 0) / positions.length);
    return { ...g, positions, avg,
      adding: positions.filter((p) => p.main.shares_change > 0).length,
      cutting: positions.filter((p) => p.main.shares_change < 0).length,
      value: positions.reduce((t, p) => t + (p.value || 0), 0) };
  }).sort((a, b) => b.positions.length - a.positions.length || b.value - a.value || a.name.localeCompare(b.name));
}

/* A score wheel with small axis labels, for the holder cards. */
function cardWheel(scores, axes, max, size = 116) {
  const n = axes.length, c = size / 2, R = size * 0.33;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const pt = (i, f) => [c + R * f * Math.cos(angle(i)), c + R * f * Math.sin(angle(i))];
  const poly = (f) => axes.map((_, i) => pt(i, f).join(",")).join(" ");
  const left = size * 0.36, right = size * 0.22;  // room for MOMENTUM on the left and PERF. on the right
  const svg = s("svg", { viewBox: `${-left} 0 ${size + left + right} ${size}`, width: size + left + right, height: size, class: "card-wheel", role: "img",
    "aria-label": "Average score of the companies held: " + axes.map((a, i) => `${a} ${fmt(scores[i], 1)} of ${max}`).join(", ") });
  for (const f of [1 / 3, 2 / 3, 1]) svg.append(s("polygon", { points: poly(f), fill: "none", stroke: "var(--grid)", "stroke-width": 1 }));
  svg.append(s("polygon", { points: scores.map((v, i) => pt(i, Math.max(v, 0.15) / max).join(",")).join(" "),
    fill: "var(--s1)", "fill-opacity": 0.35, stroke: "var(--s1)", "stroke-width": 1.5, "stroke-linejoin": "round" }));
  axes.forEach((a, i) => {
    const [x, y] = pt(i, 1.32), cos = Math.cos(angle(i));
    svg.append(s("text", { x, y: y + 3, "text-anchor": Math.abs(cos) < 0.2 ? "middle" : cos > 0 ? "start" : "end", class: "card-wheel-label",
      text: (a === "Performance" ? "Perf." : a).toUpperCase() }));
  });
  return svg;
}
const firstWords = (name) => name.split(/\s+/).slice(0, 2).join(" ");
const hueOf = (name) => [...name].reduce((t, ch) => (t * 31 + ch.charCodeAt(0)) % 360, 7);

function holderCard(g, d) {
  const extra = g.positions.length - 3;
  return h("a", { class: "holder-card", href: `#/coattail/${g.id}`, style: `--hc-hue: ${hueOf(g.name)}` },
    h("div", { class: "hc-band", "aria-hidden": "true" }, h("span", { class: "hc-title", text: firstWords(g.name) })),
    h("div", { class: "hc-body" }, h("div", {}, h("h3", { class: "hc-name", text: g.name }),
      h("div", { class: "hc-value", title: "Its listed holdings in screener companies, at today's prices", text: `${compact(g.value)} held` })),
      cardWheel(g.avg, d.axes, d.checks_per_axis)),
    h("div", { class: "hc-foot" },
      g.positions.slice(0, 3).map((p) => h("span", { class: "hc-code", text: p.code })),
      h("span", { class: "hc-count", text: extra > 0 ? `+${plural(extra, "company", "companies")}` : plural(g.positions.length, "company", "companies") }),
      g.adding ? h("span", { class: "hc-pill add", text: `${g.adding} adding` }) : null,
      g.cutting ? h("span", { class: "hc-pill cut", text: `${g.cutting} cutting` }) : null));
}

function coattailControls(onChange) {
  const st = coattailState;
  const months = h("select", { "aria-label": "Reported", onchange: (e) => { st.months = Number(e.target.value); onChange(); } },
    COATTAIL_MONTHS.map(([v, t]) => h("option", { value: v, selected: v === st.months, text: t })));
  // Why hiding them helps, on hover and the "i" (web/knowledge.json, index-funds-coattail).
  const hideIndex = withHelp(h("label", {}, h("input", { type: "checkbox", checked: st.hideIndex,
    onchange: (e) => { st.hideIndex = e.target.checked; onChange(); } }), "Hide index funds"), "Hide index funds");
  return [months, hideIndex];
}

/* ---------- ASX notices: director trades and substantial holders (docs/kb/features/coattail.md) ---------- */
const NATURE_LABELS = { ON_MARKET: "On market", OFF_MARKET: "Off market", EXERCISE: "Options or rights", DRP: "Dividend reinvestment", ISSUE: "Issued to them", OTHER: "Other" };
const EVENT_LABELS = { SUBSTANTIAL_NEW: "Became", SUBSTANTIAL_CHANGE: "Changed", SUBSTANTIAL_CEASE: "Ceased" };
const noticeState = { days: 30, show: "all", onMarket: false, mine: false, q: "" };
/* ASX releases are dated in Sydney time, whatever the viewer's time zone. */
const noticeDay = (iso) => new Date(iso).toLocaleDateString("en-AU", { timeZone: "Australia/Sydney", day: "numeric", month: "short" });
const noticeWhen = (iso) => new Date(iso).toLocaleString("en-AU", { timeZone: "Australia/Sydney", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const noticeLink = (n, label = "Notice") => h("a", { href: n.pdf_url, target: "_blank", rel: "noopener noreferrer", class: "notice-link",
  title: `${n.headline} (the PDF on the ASX website)`, "aria-label": `${n.headline}, ${n.asx_code}: open the notice on the ASX website`, text: `${label} ↗` });

function tradeText(t) {
  const units = t.direction === "SELL" ? t.disposed : t.acquired;
  if (t.direction === "NONE") return "No shares bought or sold";
  const verb = { BUY: "Bought", SELL: "Sold", MIXED: "Bought and sold" }[t.direction];
  const amount = t.direction === "MIXED" ? `${sharesText(t.acquired)} and ${sharesText(t.disposed)}` : sharesText(units);
  return `${verb} ${amount} shares${t.consideration !== null ? ` for ${compact(t.consideration)}` : ""}${t.price !== null ? ` at ${money(t.price, t.price < 1 ? 3 : 2)}` : ""}`;
}
function holdingText(n) {
  const x = n.holding || {};
  const who = x.holder || "A holder";
  if (n.kind === "SUBSTANTIAL_NEW") return `${who} now holds ${x.present_pct === null || x.present_pct === undefined ? "5% or more" : pct(x.present_pct, 2)}`;
  if (n.kind === "SUBSTANTIAL_CEASE") return `${who} is now below 5%`;
  return x.previous_pct !== null && x.present_pct !== null && x.present_pct !== undefined
    ? `${who}: ${pct(x.previous_pct, 2)} to ${pct(x.present_pct, 2)}` : `${who} changed their holding`;
}
/* What happened to the holding, without the holder's name: "6.12% to 7.15%". */
function holdingChange(n) {
  const x = n.holding || {};
  if (n.kind === "SUBSTANTIAL_NEW") return `${EVENT_LABELS[n.kind]} a holder${x.present_pct !== null && x.present_pct !== undefined ? ` at ${pct(x.present_pct, 2)}` : ""}`;
  if (n.kind === "SUBSTANTIAL_CEASE") return "Now below 5%";
  return x.previous_pct !== null && x.present_pct !== null && x.present_pct !== undefined ? `${pct(x.previous_pct, 2)} to ${pct(x.present_pct, 2)}` : "Changed";
}
/* One line per notice, for the company page and the dashboard. */
function noticeLine(n) {
  const unread = n.read_status !== "read" && !n.trades.length && !(n.holding && n.holding.holder);
  const what = n.kind === "DIRECTOR"
    ? (n.trades.length ? n.trades.map((t) => `${t.director || "A director"}: ${tradeText(t)}${t.nature_kind !== "OTHER" ? ` (${NATURE_LABELS[t.nature_kind].toLowerCase()})` : ""}`).join("; ") : "")
    : holdingText(n);
  return h("li", { class: "notice-line" },
    h("div", { class: "main" }, h("span", { class: `tag sm notice-${n.kind === "DIRECTOR" ? "dir" : "sub"}`, text: n.kind_label }), " ",
      n.in_sift === false ? h("span", { class: "code", text: n.asx_code }) : h("a", { class: "code", href: `#/company/${n.asx_code}`, text: n.asx_code }),
      h("div", { class: "notice-what", text: unread ? `Details not read: ${n.read_note || "open the notice"}` : what })),
    h("div", { class: "side" }, h("span", { class: "hint", text: noticeDay(n.released_at) }), " ", noticeLink(n)));
}
function noticesDashCard(list) {
  return card("Director and holder notices", "On the companies you hold or watch, from ASX in the last week.",
    list.length ? h("ul", { class: "items notice-list" }, list.slice(0, 8).map(noticeLine)) : h("p", { class: "hint", text: "None on your companies this week." }),
    h("div", { class: "more-links" }, h("a", { class: "more-link", href: "#/coattail?tab=directors", text: "All director trades" }),
      h("a", { class: "more-link", href: "#/coattail?tab=substantial", text: "All substantial holders" })));
}

function coattailTabs(current) {
  return h("div", { class: "tabs", role: "navigation", "aria-label": "Coattail" },
    [["funds", "#/coattail", "Big funds"], ["directors", "#/coattail?tab=directors", "Director trades"], ["substantial", "#/coattail?tab=substantial", "Substantial holders"],
     ["shorts", "#/coattail?tab=shorts", "Most shorted"]]
      .map(([id, href, label]) => h("a", { href, class: "tab", "aria-current": id === current ? "page" : null, text: label })));
}
const COATTAIL_NOTE = () => h("p", { class: "hint page-note" }, "Coattail investing means watching what big, well-researched investors buy and sell, and using their moves as a lead for your own research. ", helpLink("coattail"));

async function renderNotices(group) {
  app.replaceChildren(pageHead("Coattail", group === "directors" ? "Director trades" : "Substantial holders"), coattailTabs(group), h("p", { class: "loading", text: "Loading notices..." }));
  const st = noticeState;
  const d = await getJSON(`/api/coattail/notices?group=${group}&days=${st.days}`);
  const dirs = group === "directors";
  const body = h("div"), count = h("span", { class: "count" });
  const shows = dirs ? [["all", "All trades"], ["BUY", "Bought"], ["SELL", "Sold"]]
    : [["all", "All notices"], ["SUBSTANTIAL_NEW", "Became a holder"], ["SUBSTANTIAL_CHANGE", "Changed"], ["SUBSTANTIAL_CEASE", "Ceased"], ["raised", "Raised"], ["cut", "Cut"]];
  if (!shows.some(([v]) => v === st.show)) st.show = "all";
  const period = h("select", { "aria-label": "Period", onchange: (e) => { st.days = Number(e.target.value); renderNotices(group); } },
    [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"], [365, "Last year"]].map(([v, t]) => h("option", { value: v, selected: v === st.days, text: t })));
  const show = h("select", { "aria-label": "Show", onchange: (e) => { st.show = e.target.value; draw(); } },
    shows.map(([v, t]) => h("option", { value: v, selected: v === st.show, text: t })));
  const search = h("input", { type: "search", placeholder: dirs ? "Search companies or directors" : "Search companies or holders", value: st.q, "aria-label": "Search notices",
    oninput: (e) => { st.q = e.target.value; draw(); } });
  // Their hovers come from web/knowledge.json (director-trades, substantial-holders).
  const box = (label, key) => withHelp(h("label", {}, h("input", { type: "checkbox", checked: st[key], onchange: (e) => { st[key] = e.target.checked; draw(); } }), label), label);
  const onMarket = dirs ? box("On market only", "onMarket") : null;
  const mine = box("Yours only", "mine");

  const words = (n) => [n.asx_code, n.company_name, n.headline, ...(n.trades || []).map((t) => t.director), n.holding && n.holding.holder].filter(Boolean).join(" ").toLowerCase();
  function keep(n) {
    if (st.mine && !n.held && !n.watchlists.length) return false;
    if (st.q && !words(n).includes(st.q.trim().toLowerCase())) return false;
    if (dirs) {
      const trades = n.trades.filter((t) => (!st.onMarket || t.nature_kind === "ON_MARKET") && (st.show === "all" || t.direction === st.show || t.direction === "MIXED"));
      return st.onMarket || st.show !== "all" ? trades.length > 0 : true;
    }
    const change = n.holding ? n.holding.change_pts : null;
    if (st.show === "raised") return change > 0 || n.kind === "SUBSTANTIAL_NEW";
    if (st.show === "cut") return change < 0 || n.kind === "SUBSTANTIAL_CEASE";
    return st.show === "all" || n.kind === st.show;
  }
  const company = (n) => n.in_sift ? nameCell(n, "SHARE") : h("td", {}, h("span", { class: "code", text: n.asx_code }), h("div", { class: "name", text: n.company_name || "Not in Sift's screener" }));
  const row = (n, cells) => (n.in_sift ? rowTo(`#/company/${n.asx_code}`, ...cells) : h("tr", {}, cells));
  const unread = (n) => h("span", { class: "hint", text: `Not read: ${n.read_note || "open the notice"}` });

  function directorRows(list) {
    const out = [];
    for (const n of list) {
      const trades = n.trades.length ? n.trades : [null];
      trades.forEach((t, i) => out.push(row(n, [
        h("td", { class: "opt", text: i ? "" : noticeDay(n.released_at), title: noticeWhen(n.released_at) }),
        i ? h("td") : company(n),
        h("td", { class: "opt" }, t ? h("div", { text: t.director || NA }) : unread(n), t && t.change_date ? h("div", { class: "sub-text", text: `Traded ${longDate(t.change_date)}` }) : null),
        h("td", {}, t ? h("div", { class: "phone-only strong", text: t.director || NA }) : h("div", { class: "phone-only" }, unread(n)),
          h("div", { class: t ? `trade-${t.direction.toLowerCase()}` : null, text: t ? tradeText(t) : "" }),
          t ? h("div", { class: "sub-text phone-only", text: `${NATURE_LABELS[t.nature_kind]}, ${noticeDay(n.released_at)}` }) : null,
          i ? null : h("div", { class: "phone-only" }, noticeLink(n))),
        h("td", { class: "opt" }, t ? h("span", { class: `tag sm nature-${t.nature_kind.toLowerCase()}`, title: t.nature || "", text: NATURE_LABELS[t.nature_kind] }) : null),
        h("td", { class: "num opt" }, i ? null : noticeLink(n)),
      ])));
    }
    return out;
  }
  function holderRows(list) {
    return list.map((n) => {
      const x = n.holding || {};
      const who = x.holder ? (x.manager_id ? h("a", { href: `#/coattail/${x.manager_id}`, text: x.holder, onclick: (e) => e.stopPropagation() }) : x.holder) : unread(n);
      return row(n, [
        h("td", { class: "opt", text: noticeDay(n.released_at), title: noticeWhen(n.released_at) }),
        company(n),
        h("td", {}, h("div", {}, who), h("div", { class: "sub-text phone-only", text: `${holdingChange(n)}, ${noticeDay(n.released_at)}` }),
          h("div", { class: "phone-only" }, noticeLink(n))),
        h("td", { class: "opt" }, h("span", { class: `tag sm event-${n.kind.toLowerCase()}`, text: EVENT_LABELS[n.kind] })),
        h("td", { class: "num opt", text: x.previous_pct !== null && x.previous_pct !== undefined ? pct(x.previous_pct, 2) : "" }),
        h("td", { class: "num opt", text: n.kind === "SUBSTANTIAL_CEASE" ? "Under 5%" : pct(x.present_pct, 2) }),
        h("td", { class: `num opt ${signClass(x.change_pts) || ""}`.trim(), text: x.change_pts !== null && x.change_pts !== undefined ? `${x.change_pts > 0 ? "+" : ""}${fmt(x.change_pts, 2)} pts` : "" }),
        h("td", { class: "num opt" }, noticeLink(n)),
      ]);
    });
  }
  function draw() {
    const list = d.rows.filter(keep);
    const heads = dirs ? [["Date", "opt"], ["Company"], ["Director", "opt"], ["Trade"], ["Type", "opt"], ["", "num opt"]]
      : [["Date", "opt"], ["Company"], ["Holder"], ["Event", "opt"], ["Before", "num opt"], ["After", "num opt"], ["Change", "num opt"], ["", "num opt"]];
    count.textContent = list.length === d.rows.length ? plural(d.rows.length, "notice") : `${list.length} of ${plural(d.rows.length, "notice")}`;
    body.replaceChildren(list.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid notices-table" },
      h("thead", {}, h("tr", {}, heads.map(([t, cls]) => h("th", { scope: "col", class: cls || null, text: t })))),
      h("tbody", {}, dirs ? directorRows(list) : holderRows(list))))
      : h("p", { class: "empty", text: d.rows.length ? "No notices match these filters." : `No ${dirs ? "director trades" : "substantial holder notices"} in this period.` }));
  }
  const side = (title, rows, none) => h("div", {}, h("h3", { class: "sub-head", text: title }), rows.length ? h("ul", { class: "items notice-movers" }, rows.map((x) => h("li", {},
    h("div", { class: "main" }, x.in_sift ? h("a", { class: "code", href: `#/company/${x.asx_code}`, text: x.asx_code }) : h("span", { class: "code", text: x.asx_code }),
      h("div", { class: "name", text: x.company_name || "" })),
    h("div", { class: "side" }, h("span", { class: `tabular ${x.net > 0 ? "pos" : "neg"}`, text: compact(Math.abs(x.net)) }),
      h("div", { class: "hint", text: plural(x.net > 0 ? x.buyers : x.sellers, "director") })))))
    : h("p", { class: "hint", text: none }));
  const sm = d.summary;
  const summary = dirs
    ? card("Directors trading on market", `Net dollars bought or sold on market by each company's directors, ${st.days === 365 ? "over the last year" : `in the last ${st.days} days`}.`,
      h("div", { class: "movers-cols" }, side("Buying", sm.buying, "No on-market buying in this period."), side("Selling", sm.selling, "No on-market selling in this period.")))
    : card("Substantial holders", `Notices from holders of 5% or more, ${st.days === 365 ? "over the last year" : `in the last ${st.days} days`}.`,
      h("div", { class: "stats" }, statTile("Became a holder", String(sm.became), null, "crossed 5%"), statTile("Raised", String(sm.raised), "pos", "holding up"),
        statTile("Cut", String(sm.cut), "neg", "holding down"), statTile("Ceased", String(sm.ceased), null, "fell below 5%")));
  summary.classList.add("wide");
  const status = d.status.latest
    ? `From ASX's announcement lists, loaded each night; latest notice ${noticeWhen(d.status.latest)}.${d.status.unread ? ` ${plural(d.status.unread, "notice", "notices")} couldn't be fully read: open the notice for its details.` : ""}${d.capped ? " Showing the newest 1,000." : ""}`
    : "No notices loaded yet. They arrive with the nightly run (the ASX Notices step).";
  app.replaceChildren(pageHead("Coattail", dirs ? "Director trades" : "Substantial holders"), COATTAIL_NOTE(), coattailTabs(group),
    h("div", { class: "cards" }, summary),
    h("div", { class: "controls" }, period, show, search, onMarket, mine, count),
    body, h("p", { class: "hint coverage" }, status, " ", helpLink(dirs ? "director-trades" : "substantial-holders")));
  draw();
  window.scrollTo(0, 0);
}

async function renderCoattail(query) {
  const tab = new URLSearchParams(query || "").get("tab");
  if (tab === "directors" || tab === "substantial") return renderNotices(tab);
  if (tab === "shorts") return renderShorts();
  app.replaceChildren(h("p", { class: "loading", text: "Loading Coattail..." }));
  const d = coattailData = await getJSON("/api/coattail");
  const st = coattailState;
  const summary = h("div"), grid = h("div", { class: "holder-grid" }), count = h("span", { class: "count" });
  /* Who's investing filters like the other lists (web/tablefilter.js): search,
     and conditions on any of these. Search also finds the companies held. */
  const HOLDER_FIELDS = {
    name: { label: "Holder", type: "text", get: (g) => g.name },
    held: { label: "Companies held", type: "num", get: (g) => g.positions.length },
    adding: { label: "Adding", type: "num", get: (g) => g.adding },
    cutting: { label: "Cutting", type: "num", get: (g) => g.cutting },
    value: { label: "Value held", type: "num", get: (g) => g.value, text: (g) => compact(g.value) },
    codes: { label: "Holds", type: "text", get: (g) => g.positions.map((p) => p.code).join(", ") },
  };
  let currentGroups = [];
  const tf = tableFilter("coattail-holders", HOLDER_FIELDS, () => currentGroups, () => refresh(),
    { placeholder: "Search holders or companies", extraSearch: (g) => g.positions.map((p) => p.company.company_name || "").join(" ") });

  /* Click an Adding or Cutting number for the managers behind it, in a row
     opened under the company; click it again to close. */
  function whoRow(x, which) {
    const list = which === "adding" ? x.adders : x.cutters;
    return h("tr", { class: "who-row" }, h("td", { colspan: 5 },
      h("div", { class: "who-title", text: `${which === "adding" ? "Adding to" : "Cutting"} ${x.code}: ${plural(list.length, "manager")}` }),
      h("ul", { class: "who-list" }, list.map(({ g, p }) => h("li", {},
        h("a", { href: `#/coattail/${g.id}`, text: g.name }),
        h("span", { class: `who-change ${signClass(p.main.shares_change) || ""}`.trim(), title: p.main.percent_change === null ? "" : `${signedPct(p.main.percent_change)} since the previous report`,
          text: p.main.new ? "new holding" : `${sharesChange(p.main.shares_change)} shares` }),
        h("span", { class: "hint", text: ` via ${p.main.holder}${p.main.date_reported ? `, reported ${longDate(p.main.date_reported)}` : ""}` }))))));
  }
  const countCell = (x, which, row) => {
    const n = x[which];
    const td = h("td", { class: `center tabular ${which === "adding" ? "pos" : "neg"}` });
    if (!n) { td.textContent = "0"; return td; }
    const btn = h("button", { type: "button", class: "count-btn", "aria-expanded": "false", text: String(n),
      title: `Show the ${plural(n, "manager")} ${which === "adding" ? "adding to" : "cutting"} ${x.code}`,
      "aria-label": `${plural(n, "manager")} ${which} ${x.code}: show them` });
    const toggle = (e) => {
      e.stopPropagation();
      const tr = row(), open = tr.nextElementSibling && tr.nextElementSibling.classList.contains("who-row") ? tr.nextElementSibling : null;
      const same = open && open.dataset.which === which;
      if (open) open.remove();
      for (const b of tr.querySelectorAll(".count-btn")) b.setAttribute("aria-expanded", "false");
      if (same) return;
      const who = whoRow(x, which);
      who.dataset.which = which;
      tr.after(who);
      btn.setAttribute("aria-expanded", "true");
    };
    btn.addEventListener("click", toggle);
    btn.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } else e.stopPropagation(); });
    td.append(btn);
    return td;
  };
  const side = (title, rows, none) => h("div", { class: "table-wrap" }, h("table", { class: "grid compact movers" },
    h("thead", {}, h("tr", {}, h("th", { text: "Score" }), h("th", { text: title }), h("th", { class: "center", text: "Adding" }),
      h("th", { class: "center", text: "Cutting" }), withHelp(h("th", { class: "opt2", tabindex: 0, text: "Recommendation" }), "Action"))),
    h("tbody", {}, rows.length ? rows.map((x) => {
      let tr = null;
      tr = rowTo(`#/company/${x.code}`,
        h("td", { class: "mover-score" }, wheel(x.company.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }),
          h("span", { class: "score-total", text: sum(x.company.scores) })),
        nameCell(x.company, "SHARE"), countCell(x, "adding", () => tr), countCell(x, "cutting", () => tr),
        h("td", { class: "opt2" }, badge(x.company.action)));
      return tr;
    }) : h("tr", {}, h("td", { colspan: 5, class: "hint", text: none })))));
  function refresh() {
    const groups = coattailManagers(d, coattailHoldings(d));
    const by = new Map();
    for (const g of groups) for (const p of g.positions) {
      const t = by.get(p.code) || { code: p.code, company: p.company, adding: 0, cutting: 0, adders: [], cutters: [] };
      if (p.main.shares_change > 0) { t.adding++; t.adders.push({ g, p }); } else if (p.main.shares_change < 0) { t.cutting++; t.cutters.push({ g, p }); }
      by.set(p.code, t);
    }
    const list = [...by.values()].map((x) => ({ ...x, net: x.adding - x.cutting }));
    summary.replaceChildren(h("div", { class: "movers-cols" },
      side("Most added to", list.filter((x) => x.net > 0).sort((a, b) => b.net - a.net || b.adding - a.adding || a.code.localeCompare(b.code)).slice(0, 10),
        "No company has more managers adding than cutting."),
      side("Most cut", list.filter((x) => x.net < 0).sort((a, b) => a.net - b.net || b.cutting - a.cutting || a.code.localeCompare(b.code)).slice(0, 10),
        "No company has more managers cutting than adding.")));
    currentGroups = groups;
    const key = (HOLDER_SORTS.find(([k]) => k === st.sort) || HOLDER_SORTS[0])[2];
    groups.sort((a, b) => key(b) - key(a) || b.value - a.value || a.name.localeCompare(b.name));
    for (const btn of sortSeg.children) btn.setAttribute("aria-pressed", btn.dataset.sort === st.sort);
    const shown = tf.apply(groups);
    grid.replaceChildren(...(shown.length ? shown.map((g) => holderCard(g, d)) : [h("p", { class: "empty", text: "No holders match these filters." })]));
    count.textContent = tf.active() ? `${shown.length} of ${plural(groups.length, "holder")}` : plural(groups.length, "holder");
  }
  const sortSeg = h("div", { class: "segmented holder-sort", role: "group", "aria-label": "Sort holders by" },
    HOLDER_SORTS.map(([k, label]) => h("button", { type: "button", "data-sort": k, "aria-pressed": String(k === st.sort), text: label,
      onclick: () => { st.sort = k; refresh(); } })));
  const intro = card("Where the funds are going", `For each screener company, how many fund managers added to or cut their holding since their previous report: click a number to see who. Recommendation is Sift's own suggested action for the company, to compare with what the managers are doing. From Yahoo Finance's top holder lists, refreshed weekly${d.as_of ? `; latest report ${longDate(d.as_of)}` : ""}.`, summary);
  intro.classList.add("wide");
  const next = card("Coming next", null, h("ul", { class: "plain-list" },
    h("li", { text: "Famous US investors' portfolios, such as Berkshire Hathaway's and Bridgewater's, from their quarterly 13F filings." })));
  next.classList.add("wide");
  app.replaceChildren(
    pageHead("Coattail", `Following the smart money in ${plural(d.screened, "screener company", "screener companies")}`),
    COATTAIL_NOTE(), coattailTabs("funds"),
    h("div", { class: "controls" }, ...coattailControls(refresh)),
    ...(d.holdings.length ? [h("div", { class: "cards" }, intro),
      h("div", { class: "section-head" },
        h("h2", { class: "section-title" }, "Who's investing ", h("span", { class: "hint", text: "Click a holder to see every screener company it holds." })),
        h("div", { class: "holder-sort-wrap" }, h("span", { class: "hint", text: "Sort by" }), sortSeg)),
      h("div", { class: "controls tf-controls" }, tf.search, tf.toggle, count), tf.chips, tf.builder,
      h("p", { class: "hint coverage" }, `Holder lists cover ${fmt(d.with_holders, 0)} of ${plural(d.screened, "screener company", "screener companies")}. Yahoo lists each company's top 10 funds and top 10 institutions, so a manager outside a company's top 10 isn't shown for it.`,
        d.fetched < d.screened ? ` ${plural(d.screened - d.fetched, "company hasn't", "companies haven't")} been fetched yet; the weekly refresh fetches a seventh each night.` : "", " ", helpLink("holder-moves")),
      grid]
      : [h("p", { class: "empty", text: "No holder lists yet. They arrive with the weekly analyst and holder refresh." })]),
    h("div", { class: "cards coattail-next" }, next));
  refresh();
  window.scrollTo(0, 0);
}

async function renderCoattailHolder(id) {
  if (!coattailData) {
    app.replaceChildren(h("p", { class: "loading", text: "Loading holder..." }));
    coattailData = await getJSON("/api/coattail");
  }
  const d = coattailData;
  const body = h("div");
  function draw() {
    const g = coattailManagers(d, coattailHoldings(d)).find((x) => x.id === id);
    const all = coattailManagers(d, d.holdings).find((x) => x.id === id);
    const hidden = all ? all.positions.length - (g ? g.positions.length : 0) : 0;
    const showAll = hidden ? h("p", { class: "hint" }, `${plural(hidden, "more company is", "more companies are")} hidden by the filters above. `,
      h("button", { type: "button", class: "btn small", text: "Show all", onclick: () => { Object.assign(coattailState, { hideIndex: false, months: 0 }); draw(); syncControls(); } })) : null;
    if (!g) {
      body.replaceChildren(...[h("p", { class: "empty", text: "No holdings for this holder under the current filters." }), showAll].filter(Boolean));
      return;
    }
    const heads = [["Score", "opt2"], ["Company"], ["Held through", "opt"], ["Shares", "num"], ["Change", "num"], ["% held", "num opt2"], ["Value now", "num"], ["Reported", "num opt"], ["Recommendation", "opt2"]];
    const table = h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, heads.map(([t, cls]) => withHelp(h("th", { class: cls || null, tabindex: 0, text: t }), ({ Change: "Holder change", Recommendation: "Action" })[t] || t)))),
      h("tbody", {}, g.positions.map((p) => rowTo(`#/company/${p.code}`,
        h("td", { class: "opt2" }, wheel(p.company.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }), h("span", { class: "score-total", text: sum(p.company.scores) })),
        nameCell(p.company, "SHARE"),
        h("td", { class: "opt" }, h("div", { class: "holder-name", text: p.main.holder }),
          h("div", { class: "name" }, p.main.kind === "FUND" ? "Fund" : "Institution", p.main.index_fund ? h("span", { class: "tag sm", text: "Index", title: "An index fund or ETF: it buys and sells to match its index (Hide index funds leaves these out)" }) : null,
            p.others.length ? h("span", { class: "also", title: p.others.map((o) => `${o.holder}: ${sharesText(o.shares)} shares`).join("\n"), text: ` +${plural(p.others.length, "more fund")}` }) : null)),
        h("td", { class: "num tabular", text: sharesText(p.main.shares) }),
        h("td", { class: `num tabular ${signClass(p.main.shares_change) || ""}`.trim(), title: p.main.percent_change === null ? "" : `${signedPct(p.main.percent_change)} since the previous report`,
          text: p.main.new ? "New" : sharesChange(p.main.shares_change) }),
        h("td", { class: "num opt2", text: pct(p.main.percent_held, 2) }),
        h("td", { class: "num tabular", text: p.value === null ? NA : compact(p.value) }),
        h("td", { class: "num opt", text: p.main.date_reported ? longDate(p.main.date_reported) : NA }),
        h("td", { class: "opt2" }, badge(p.company.action))))));
    body.replaceChildren(
      h("div", { class: "holder-head" },
        h("div", { class: "hc-band hc-band-lg", style: `--hc-hue: ${hueOf(g.name)}`, "aria-hidden": "true" }, h("span", { class: "hc-title", text: firstWords(g.name) })),
        h("div", { class: "holder-facts" },
          h("p", {}, `Holds ${plural(g.positions.length, "screener company", "screener companies")}, worth ${compact(g.value)} at today's prices.`),
          h("p", {}, `Since their previous reports: adding to ${g.adding}, cutting ${g.cutting}.`),
          h("p", { class: "hint", text: "The wheel is the average score of the companies it holds." })),
        cardWheel(g.avg, d.axes, d.checks_per_axis, 150)),
      ...(showAll ? [showAll] : []),
      (() => {
        const c = card("Holdings", "Each company once, through the manager's largest listed holding in it; hover +1 more fund for the others. Change is shares bought (+) or sold (-) since that holder's previous report; hover it for the percentage.",
          h("div", { class: "table-wrap" }, table));
        c.classList.add("wide");
        return h("div", { class: "cards" }, c);
      })());
  }
  const name = (d.holdings.find((m) => m.manager_id === id) || {}).manager || "Holder";
  const controls = h("div", { class: "controls" }, ...coattailControls(draw));
  const syncControls = () => controls.replaceChildren(...coattailControls(draw));
  app.replaceChildren(
    h("a", { class: "back", href: "#/coattail", text: "← Coattail" }),
    pageHead(name, "Fund manager"),
    controls,
    body);
  draw();
  window.scrollTo(0, 0);
}

/* ---------- search results (§32): tick boxes down the left ---------- */
const FACET_TITLES = { type: "Type", sector: "Sector or category", recommendation: "Recommendation", mine: "Mine", topic: "Knowledge articles" };
const FACET_GROUPS = Object.keys(FACET_TITLES);
const FACET_SHOWN = 8;  // boxes per group before "Show more"
/* Search learning (§32): the search being looked at (logged once, its id
   reused while only tick boxes change), clicks on results, and thumbs. */
const searchLog = { q: null, queryId: null };
function searchClick(queryId, docId, position) {
  if (!queryId) return;
  fetch("/api/search/click", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json", "X-Sift": "1" },
    body: JSON.stringify({ query_id: queryId, doc_id: docId, position }) }).catch(() => { /* learning only: never in the way */ });
}
const thumbIcon = (down) => s("svg", { viewBox: "0 0 24 24", width: 16, height: 16, "aria-hidden": "true", class: down ? "thumb-down" : null },
  s("path", { d: "M7 10v11H3V10h4zm2 11h8.6a2 2 0 0 0 2-1.6l1.3-7A2 2 0 0 0 18.9 10H14V5.5A2.5 2.5 0 0 0 11.5 3L9 10v11z",
    fill: "currentColor", "fill-opacity": "0", stroke: "currentColor", "stroke-width": 1.6, "stroke-linejoin": "round" }));
function thumbs(norm, r) {
  const wrap = h("div", { class: "thumbs", role: "group", "aria-label": `Was ${r.title} a good result?` });
  const paint = () => {
    for (const b of wrap.children) b.setAttribute("aria-pressed", String(Number(b.dataset.vote) === r.vote));
  };
  const btn = (vote, label) => h("button", { type: "button", class: "thumb", "data-vote": vote, title: label, "aria-label": `${label}: ${r.title}`,
    onclick: async () => {
      const next = r.vote === vote ? 0 : vote;
      try { await send("POST", "/api/search/feedback", { norm, doc_id: r.doc_id, vote: next }); r.vote = next; paint(); }
      catch (err) { placeTipBelow(wrap, [h("div", { text: err.message })]); setTimeout(hideTip, 2000); }
    } }, thumbIcon(vote < 0));
  wrap.append(btn(1, "Good result"), btn(-1, "Not what I wanted"));
  paint();
  return wrap;
}

/* A snippet from the server, with its matched words between \u0002 and \u0003, as text and <mark>s. */
function snippetNodes(s) {
  return (s || "").split(/(\u0002[^\u0003]*\u0003)/).filter(Boolean).map((part) =>
    part.startsWith("\u0002") ? h("mark", { text: part.slice(1, -1) }) : document.createTextNode(part));
}
async function renderSearch(query) {
  const params = new URLSearchParams(query);
  const q = params.get("q") || "";
  const kb = params.get("scope") === "devkb";  // the developer knowledge base, admins only (§36)
  const fresh = (text) => { const p = new URLSearchParams(); p.set("q", text); if (kb) p.set("scope", "devkb"); return p; };
  const go = (p) => { location.hash = `#/search?${p.toString()}`; };
  const box = h("input", { type: "search", class: "search-big", value: q,
    placeholder: kb ? "Search the developer knowledge base" : "Search shares, ETFs, LICs, fund managers, your lists, help and settings",
    "aria-label": kb ? "Search the developer knowledge base" : "Search everything in Sift" });
  const scopeNote = kb ? h("p", { class: "hint scope-note" }, "Searching the developer knowledge base only. ",
    h("a", { href: `#/search?q=${encodeURIComponent(q)}`, text: "Search everything instead" })) : null;
  const headSub = kb ? "Developer knowledge base" : "Everything in Sift";
  const form = h("form", { class: "search-form", role: "search" }, box, h("button", { type: "submit", class: "btn primary", text: "Search" }));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    go(fresh(box.value.trim()));
  });
  if (!q.trim()) {
    app.replaceChildren(...[pageHead("Search", headSub), form, scopeNote,
      h("p", { class: "hint", text: "Type an ASX code, a company, ETF, LIC or fund manager, one of your watchlists or portfolios, a term such as franking, or a setting such as discount rate." })].filter(Boolean));
    box.focus();
    return;
  }
  app.replaceChildren(...[pageHead("Search", `Searching for "${q}"...`), form, scopeNote].filter(Boolean));
  const api = new URLSearchParams(); api.set("q", q);
  if (kb) api.set("scope", "devkb");
  for (const g of FACET_GROUPS) for (const v of params.getAll(g)) api.append(g, v);
  if (searchLog.q === q && searchLog.queryId) api.set("query_id", searchLog.queryId); else api.set("log", "1");
  const d = await getJSON(`/api/search?${api.toString()}`);
  if (d.query_id) Object.assign(searchLog, { q, queryId: d.query_id });
  const ticked = FACET_GROUPS.reduce((n, g) => n + params.getAll(g).length, 0);
  const toggle = (g, v, on) => {
    const p = new URLSearchParams(params);
    const keep = p.getAll(g).filter((x) => x !== v);
    p.delete(g); for (const x of keep) p.append(g, x);
    if (on) p.append(g, v);
    go(p);
  };
  const facets = h("aside", { class: "facets", "aria-label": "Filter the results" },
    h("div", { class: "facets-head" }, h("span", { text: "Filter" }),
      ticked ? h("button", { type: "button", class: "link-btn", text: "Clear all", onclick: () => go(fresh(q)) }) : null),
    d.facets.map((f) => {
      const boxes = f.boxes.map((b, i) => h("label", { class: "facet-box", hidden: i >= FACET_SHOWN && !b.ticked },
        h("input", { type: "checkbox", checked: b.ticked, onchange: (e) => toggle(f.group, b.value, e.target.checked) }),
        h("span", { class: "facet-value", text: b.value }), h("span", { class: "facet-count", text: fmt(b.count, 0) })));
      const hidden = boxes.filter((x) => x.hidden).length;
      const more = hidden ? h("button", { type: "button", class: "link-btn facet-more", text: `Show ${hidden} more`,
        onclick: () => { for (const x of boxes) x.hidden = false; more.remove(); } }) : null;
      return h("fieldset", { class: "facet" }, h("legend", { text: FACET_TITLES[f.group] || f.group }), boxes, more);
    }));
  const filtersBtn = h("button", { type: "button", class: "btn small facets-toggle", "aria-expanded": "false", text: ticked ? `Filters (${ticked})` : "Filters",
    onclick: () => { const open = !facets.classList.contains("open"); facets.classList.toggle("open", open); filtersBtn.setAttribute("aria-expanded", String(open)); } });
  const results = d.results.length ? h("ol", { class: "results" }, d.results.map((r, i) => h("li", { class: "result-row" },
    h("a", { class: "result", href: r.url, onclick: () => searchClick(d.query_id, r.doc_id, i + 1) },
      h("div", { class: "result-top" }, h("span", { class: `tag sm result-type t-${r.kind}`, text: r.type.replace(/s$/, "") }),
        r.code ? h("span", { class: "code", text: r.code }) : null, h("span", { class: "result-title", text: r.title }),
        r.recommendation ? badge(r.recommendation) : null,
        r.mine.filter((m) => m !== "My lists").map((m) => h("span", { class: "tag sm mine-tag", text: m === "Held" ? "HELD" : "★ Watchlist" }))),
      r.subtitle ? h("div", { class: "result-sub", text: r.subtitle }) : null,
      r.snippet && r.snippet.replace(/[\u0002\u0003]/g, "") !== r.subtitle ? h("div", { class: "result-snippet" }, snippetNodes(r.snippet)) : null),
    thumbs(d.norm, r))))
    : h("p", { class: "empty" }, ticked ? "Nothing matches with these filters. " : `Nothing in Sift matches "${q}". `,
      ticked ? h("button", { type: "button", class: "link-btn", text: "Clear the filters", onclick: () => go(fresh(q)) })
        : "Try fewer or shorter words, or an ASX code.");
  const sub = `${plural(d.total, "result")} for "${q}"${d.total > d.results.length ? `, showing the best ${d.results.length}` : ""}`;
  const flash = cache.flash ? h("p", { class: "hint search-flash", text: cache.flash }) : null;
  cache.flash = null;
  app.replaceChildren(...[pageHead("Search", sub), form, scopeNote, flash,
    h("div", { class: "search-layout" }, d.facets.length ? [filtersBtn, facets] : null, h("section", { class: "search-results" }, results))].filter(Boolean));
  window.scrollTo(0, 0);
}

/* Admin, Search tab (§32): the index, meaning-based search, what people
   search for, and synonyms. */
async function renderAdminSearch() {
  app.replaceChildren(pageHead("Model and rules", "Search"), adminTabs("search"), h("p", { class: "loading", text: "Loading..." }));
  const index = searchIndexCard();
  index.classList.add("wide");
  const cards = h("div", { class: "cards" }, index, aiSearchCard(), synonymsCard(), searchInsightsCard());
  app.replaceChildren(pageHead("Model and rules", "Search: how it's built and how it's used"), adminTabs("search"), cards);
  window.scrollTo(0, 0);
}
function aiSearchCard() {
  const body = h("div", {}, h("p", { class: "loading", text: "Loading..." }));
  getJSON("/api/admin/search").then((s) => {
    const a = s.ai;
    body.replaceChildren(
      h("p", {}, h("span", { class: `tag sm ${a.on ? "ai-on" : "ai-off"}`, text: a.on ? "ON" : "OFF" }), " ",
        a.on ? `Using ${a.model}: ${fmt(a.embedded, 0)} of ${fmt(a.rows, 0)} rows embedded.` : "Search matches words; meaning-based matching is ready but switched off."),
      a.on ? null : h("p", { class: "hint" }, "To switch it on (a small model that runs inside Sift; nothing leaves this PC): ", a.how, "."));
  }).catch((err) => body.replaceChildren(h("p", { class: "error", text: err.message })));
  return card("Meaning-based search (AI)", "Finds results by meaning as well as words, e.g. \"companies hurt by high interest rates\". Each item's text is embedded once and only again when it changes.", body);
}
function searchInsightsCard() {
  const body = h("div", {}, h("p", { class: "loading", text: "Loading..." }));
  const days = h("select", { "aria-label": "Period", class: "inline-select", onchange: () => load() },
    [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"], [365, "Last year"]].map(([v, t]) => h("option", { value: v, selected: v === 30, text: t })));
  const list = (title, rows, cols, none) => [h("h3", { class: "sub-head", text: title }),
    rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, cols.map(([t, , num]) => h("th", { class: num ? "num" : null, text: t })))),
      h("tbody", {}, rows.map((r) => h("tr", {}, cols.map(([, get, num]) => h("td", { class: num ? "num" : null }, get(r))))))))
      : h("p", { class: "hint", text: none })];
  const searchLink = (q) => h("a", { href: `#/search?q=${encodeURIComponent(q)}`, text: q });
  function load() {
    getJSON(`/api/admin/search/insights?days=${days.value}`).then((d) => {
      const t = d.totals;
      body.replaceChildren(
        h("p", {}, `${plural(t.searches, "search", "searches")}, ${plural(t.nothing, "found nothing", "found nothing")}, ${plural(t.clicks, "result opened", "results opened")}${t.impersonated ? `, ${plural(t.impersonated, "made while impersonating", "made while impersonating")}` : ""}.`),
        ...list("Top searches", d.top, [["Search", (r) => searchLink(r.norm)], ["Times", (r) => fmt(r.searches, 0), true],
          ["Results", (r) => fmt(r.results, 0), true], ["Opened a result", (r) => `${fmt(r.clicked / r.searches * 100, 0)}%`, true]], "No searches yet."),
        ...list("Searches that found nothing", d.nothing, [["Search", (r) => searchLink(r.norm)], ["Times", (r) => fmt(r.searches, 0), true],
          ["Last", (r) => longDate(r.last.slice(0, 10))]], "None: every search found something."),
        h("p", { class: "hint", text: "Fix these with a synonym below, or by adding the missing thing to Sift." }),
        ...list("Results marked not what was wanted", d.disliked, [["Search", (r) => searchLink(r.norm)], ["Result", (r) => r.title || r.doc_id],
          ["Net votes", (r) => fmt(r.net, 0), true]], "None."),
        ...list("By person", d.people, [["Person", (r) => r.person], ["Searches", (r) => fmt(r.searches, 0), true],
          ["Found nothing", (r) => `${fmt(r.nothing / r.searches * 100, 0)}%`, true],
          ["Opened a result", (r) => `${fmt(r.clicked / r.searches * 100, 0)}%`, true], ["Last", (r) => when(r.last)]], "No searches yet."),
        h("p", { class: "hint", text: "Searches an admin made while impersonating are left out of the person's figures." }));
    }).catch((err) => body.replaceChildren(h("p", { class: "error", text: err.message })));
  }
  load();
  const c = card("Search insights", "What's searched for, what's found and what's opened. Opened and liked results rise for the same search; disliked ones sink.",
    h("div", { class: "controls" }, days), body);
  c.classList.add("wide");
  return c;
}
function synonymsCard() {
  const listEl = h("div"), msg = formMessage();
  const input = h("input", { type: "text", placeholder: "e.g. cba, commonwealth bank", "aria-label": "Terms that mean the same, separated by commas", class: "syn-input" });
  const draw = (groups) => listEl.replaceChildren(groups.length ? h("ul", { class: "syn-list" }, groups.map((g) => h("li", {},
    h("span", { text: g.terms.join(" = ") }),
    h("button", { type: "button", class: "icon-x", "aria-label": `Remove ${g.terms.join(", ")}`, text: "✕", onclick: async () => {
      try { draw((await send("DELETE", `/api/admin/search/synonyms/${g.synonym_id}`)).synonyms); } catch (err) { showMessage(msg, err.message, false); }
    } }))))
    : h("p", { class: "hint", text: "No synonyms yet." }));
  const form = h("form", { class: "syn-form" }, input, h("button", { type: "submit", class: "btn", text: "Add" }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { const d = await send("POST", "/api/admin/search/synonyms", { terms: input.value }); input.value = ""; draw(d.synonyms); showMessage(msg, `Added: ${d.added.terms.join(" = ")}.`, true); }
    catch (err) { showMessage(msg, err.message, false); }
  });
  getJSON("/api/admin/search/synonyms").then((d) => draw(d.synonyms)).catch((err) => showMessage(msg, err.message, false));
  return card("Synonyms", "Terms that mean the same to a searcher. Searching any one finds the others, e.g. cba = commonwealth bank, super = superannuation. Separate the terms with commas.",
    form, msg, listEl);
}

/* Admin: the search index's state, and a button to rebuild it now. */
function searchIndexCard() {
  const body = h("div", {}, h("p", { class: "loading", text: "Loading..." }));
  const msg = formMessage();
  const AREA_LABELS = { market: "Shares, ETFs and LICs", coattail: "Fund managers", personal: "Your watchlists and portfolios", help: "Help articles", pages: "Pages and settings" };
  const draw = (s) => body.replaceChildren(
    h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, ["Area", "Items", "Last rebuilt", "By", "Took"].map((t, i) => h("th", { class: i === 1 || i === 4 ? "num" : null, text: t })))),
      h("tbody", {}, s.areas.map((a) => h("tr", {}, h("td", { text: AREA_LABELS[a.area] || a.area }), h("td", { class: "num", text: fmt(a.items, 0) }),
        h("td", { text: a.last ? new Date(a.last.finished_at).toLocaleString("en-AU", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "never" }),
        h("td", { text: a.last ? a.last.trigger : NA }), h("td", { class: "num", text: a.last ? `${fmt(a.last.seconds, 2)}s` : NA })))))),
    h("p", { class: "hint", text: s.typo_tolerance ? "Typo tolerance is on (pg_trgm)." : "Typo tolerance is off: the database doesn't allow the pg_trgm extension, so search matches whole and partial words only." }));
  const btn = h("button", { type: "button", class: "btn", text: "Rebuild search index", onclick: async () => {
    btn.disabled = true; btn.textContent = "Rebuilding...";
    try { const s = await send("POST", "/api/admin/search/reindex", {}); draw(s); showMessage(msg, `Rebuilt: ${Object.entries(s.rebuilt).map(([a, n]) => `${n} ${a}`).join(", ")}.`, true); }
    catch (err) { showMessage(msg, err.message, false); }
    btn.disabled = false; btn.textContent = "Rebuild search index";
  } });
  getJSON("/api/admin/search").then(draw).catch((err) => body.replaceChildren(h("p", { class: "error", text: err.message })));
  return card("Search index", "Rebuilt after each nightly run, your own lists the moment you save them, and help and pages when Sift starts. Rebuild now after loading data by hand.",
    body, h("div", { class: "form-actions" }, btn, msg), h("p", { class: "hint" }, "Or from PowerShell: ", h("code", { text: ".venv\\Scripts\\python.exe -m src.search.reindex" }), " ", helpLink("sift-search")));
}

/* ---------- track record (the page itself is React: frontend/src/pages/TrackRecordPage.tsx) ---------- */
/* The dashboard's Track record card still uses these; they move with the dashboard (IMP-084). */
const horizonText = (m) => (m === 1 ? "1 month" : `${m} months`);
const points = (v) => `${fmt(Math.abs(v), 1)} point${Math.abs(v) === 1 ? "" : "s"}`;
const signedPct = (v, dp = 1) => signed(v, (x) => fmt(x, dp) + "%");

function verdictPill(t) {
  const [cls, icon] = t.intended === true ? ["good", "✓"] : t.intended === false ? ["bad", "✕"]
    : t.kind === "NEEDS_MORE" ? ["wait", "…"] : t.kind === "UNCLEAR" ? ["wait", "~"] : ["wait", "–"];
  return h("span", { class: `vpill ${cls}` }, h("span", { "aria-hidden": "true", text: icon }), t.label);
}
function verdictLine(a, months) {
  const beat = a.avg_excess >= 0, t = a.test;
  const rate = a.beat_rate === null ? null : beat ? a.beat_rate : 100 - a.beat_rate;
  const luck = t.kind === "NEEDS_MORE" ? ` Too early to tell: Sift needs ${fmt(t.min_calls, 0)} calls and has ${fmt(a.signals, 0)}.`
    : t.kind === "UNCLEAR" ? ` That could easily be luck: ${t.luck}.` : ` That's unlikely to be luck: ${t.luck}.`;
  return h("li", { class: "rule-row" },
    h("div", { class: "rule-head" }, badge(a.action), verdictPill(t)),
    h("div", { class: "rule-body" },
      h("p", { class: "verdict-text" },
        `${a.action} calls ${beat ? "beat" : "trailed"} the average screened share by ${points(a.avg_excess)} over ${horizonText(months)}` +
        (rate === null ? "." : `; ${fmt(rate, 0)}% of ${fmt(a.signals, 0)} ${beat ? "beat" : "trailed"} it.`) + luck)));
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
  const create = card("New watchlist", "Companies, ETFs and LICs to follow without owning them. Add them here or with ☆ Add to watchlist on any company, ETF or LIC page.", form);
  app.replaceChildren(...[
    pageHead("Watchlists", d.watchlists.length ? plural(d.watchlists.length, "watchlist") : null),
    d.watchlists.length ? h("div", { class: "cards" }, d.watchlists.map((w) => h("a", { class: "card pf-card", href: watchlistHref(w) },
      h("div", { class: "pf-head" }, h("h2", { text: w.name })),
      h("p", { class: "hint", text: w.companies || w.etfs || w.lics ? [w.companies ? plural(w.companies, "company", "companies") : null, w.etfs ? plural(w.etfs, "ETF") : null,
        w.lics ? plural(w.lics, "LIC") : null].filter(Boolean).join(", ") : "Nothing on it yet" }),
      w.triggered ? h("span", { class: "tag", text: `${plural(w.triggered, "trigger")} met` }) : null)))
      : h("p", { class: "empty", text: "No watchlists yet. Create one below." }),
    h("div", { class: "cards", style: "margin-top:16px" }, create),
  ].filter(Boolean));
  if (wantNew) setTimeout(() => { create.scrollIntoView({ block: "center" }); name.focus(); }, 0); else window.scrollTo(0, 0);
}

/* Watchlist and portfolio tables as filter fields (web/tablefilter.js). */
const codeField = (label) => ({ label, type: "text", get: (r) => r.asx_code, text: (r) => `${r.asx_code} ${r.company_name || ""}` });
const numField = (label, key, show) => ({ label, type: "num", get: (r) => r[key], text: (r) => show(r[key]) });
const triggersField = { label: "Triggers", type: "text",
  get: (r) => (r.triggers && r.triggers.length ? (r.triggers.some((t) => t.met) ? "Met" : "Not met") : null),
  text: (r) => (r.triggers || []).map((t) => `${t.label} ${t.met ? "met" : "not met"}`).join("; ") };
const noteField = { label: "Note", type: "text", get: (r) => r.note };
const WATCH_SHARE_FIELDS = {
  score: { label: "Score", type: "num", get: (r) => (r.scores ? sum(r.scores) : null) },
  asx_code: codeField("Company"),
  price: numField("Price", "price", (v) => money(v)),
  margin_of_safety_percent: numField("Margin of safety", "margin_of_safety_percent", (v) => pct(v, 0)),
  valuation: { label: "Valuation", type: "text", get: (r) => valuationStatus(r.margin_of_safety_percent).label },
  action: { label: "Action", type: "text", get: (r) => r.action },
  triggers: triggersField, note: noteField,
};
const fundWatchFields = (kind) => ({
  asx_code: codeField(FUNDS[kind].noun),
  price: numField(FUNDS[kind].price, "price", (v) => money(v)),
  day_change_percent: numField("Day move", "day_change_percent", signedPct),
  [kind === "LIC" ? "premium_now" : "return_1y"]: kind === "LIC" ? numField("Premium/discount to NTA", "premium_now", premText) : numField("1-year return", "return_1y", signedPct),
  distribution_yield_12m: numField("Yield (12 months)", "distribution_yield_12m", (v) => pct(v, 1)),
  triggers: triggersField, note: noteField,
});
function fundWatchFiltered(kind, d, items, editing, remove) {
  const fields = fundWatchFields(kind);
  return filterableTable(`watch:${d.watchlist_id}:${kind}`, fields, [...Object.keys(fields), null], items,
    (rows) => fundWatchTable(kind, rows, editing, remove));
}
const discountField = { label: "CGT discount from", type: "text", get: (r) => (r.next_discount_date ? longDate(r.next_discount_date) : "eligible now") };
const holdingFields = (kind) => {
  const money0 = (v) => money(v, 0), signedMoney = (v) => signed(v, money0);
  const base = {
    asx_code: codeField(kind === "SHARE" ? "Company" : FUNDS[kind].noun),
    units: numField("Units", "units", (v) => fmt(v, 0)),
    cost_base: numField("Cost base", "cost_base", money0),
    price: numField(kind === "SHARE" ? "Price" : FUNDS[kind].price, "price", (v) => money(v)),
    value: numField("Value", "value", money0),
    gain: numField("Gain", "gain", signedMoney),
    day_change: numField("Today", "day_change", signedMoney),
  };
  if (kind === "SHARE") return { ...base, action: { label: "Action", type: "text", get: (r) => r.action }, next_discount_date: discountField };
  return { ...base,
    [kind === "LIC" ? "premium_now" : "return_1y"]: kind === "LIC" ? numField("Premium/discount to NTA", "premium_now", premText) : numField("1-year return", "return_1y", signedPct),
    distribution_yield_12m: numField("Yield (12 months)", "distribution_yield_12m", (v) => pct(v, 1)), next_discount_date: discountField };
};

async function renderWatchlist(id, note) {
  if (!note) app.replaceChildren(h("p", { class: "loading", text: "Loading watchlist..." }));
  const d = await getJSON(`/api/watchlists/${encodeURIComponent(id)}`);
  const reload = (text) => renderWatchlist(id, text);
  const notice = formMessage();
  if (note) showMessage(notice, note, true);

  // Add or edit an entry: the same form, since saving a company already on the list updates it.
  const code = h("input", { name: "asx_code", list: "company-list", maxlength: 6, autocomplete: "off", placeholder: "BHP or VAS", style: "text-transform:uppercase" });
  const noteIn = h("input", { name: "note", maxlength: 500, autocomplete: "off", placeholder: "Why you're watching it" });
  const mos = h("input", { name: "mos_above", inputmode: "decimal", autocomplete: "off", placeholder: "e.g. 25" });
  const dy = h("input", { name: "yield_above", inputmode: "decimal", autocomplete: "off", placeholder: "e.g. 5" });
  const disc = h("input", { name: "nta_discount_above", inputmode: "decimal", autocomplete: "off", placeholder: "e.g. 10" });
  const price = h("input", { name: "price_below", inputmode: "decimal", autocomplete: "off", placeholder: "e.g. 38.50" });
  const shortIn = h("input", { name: "short_above", inputmode: "decimal", autocomplete: "off", placeholder: "e.g. 5" });
  const submit = h("button", { class: "btn primary", type: "submit", text: "Add to watchlist" });
  const cancel = h("button", { class: "btn", type: "button", text: "Cancel", hidden: true });
  const formMsg = formMessage();
  const mosField = field("Trigger: margin of safety above (%)", mos, "Shares only. Met while the share is at least this far below estimated value.");
  const dyField = field("Trigger: yield above (%)", dy, "ETFs and LICs. Met while the 12-month yield is above this.");
  const discField = field("Trigger: discount to NTA of at least (%)", disc, "LICs only. Met while the price is at least this far below the last NTA.");
  const shortField = field("Trigger: short interest above (%)", shortIn, "Shares only. Met while more than this % of the company's shares are reported sold short (ASIC, a few days behind).");
  const form = h("form", { class: "form-grid", novalidate: true },
    field("Company, ETF or LIC", code), field("Note", noteIn), mosField, dyField, discField,
    field("Trigger: price at or below ($)", price, "Met while the latest close is at or under this price."), shortField,
    h("div", { class: "form-actions" }, submit, cancel), formMsg);
  const formCard = card("Add a company, ETF or LIC", "Triggers are optional; leave them blank to just follow it.", form);
  const editing = (e) => {
    code.value = e.asx_code; code.readOnly = true; noteIn.value = e.note || "";
    mos.value = e.mos_above ?? ""; dy.value = e.yield_above ?? ""; disc.value = e.nta_discount_above ?? ""; price.value = e.price_below ?? "";
    shortIn.value = e.short_above ?? ""; shortField.hidden = e.security_type !== "SHARE";
    mosField.hidden = e.security_type !== "SHARE"; dyField.hidden = e.security_type === "SHARE"; discField.hidden = e.security_type !== "LIC";
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
      await send("PUT", `/api/watchlists/${d.watchlist_id}/items/${encodeURIComponent(c)}`,
        { note: noteIn.value, mos_above: mosField.hidden ? "" : mos.value, yield_above: dyField.hidden ? "" : dy.value,
          nta_discount_above: discField.hidden ? "" : disc.value, price_below: price.value, short_above: shortField.hidden ? "" : shortIn.value });
      afterChange();
      await reload(code.readOnly ? `Saved ${c}.` : `Added ${c}.`);
    } catch (err) { showMessage(formMsg, err.message, false); }
  });

  const remove = async (e) => {
    try { await send("DELETE", `/api/watchlists/${d.watchlist_id}/items/${e.asx_code}`); afterChange(); await reload(`Removed ${e.asx_code}.`); }
    catch (err) { showMessage(notice, err.message, false); }
  };
  const heads = ["Score", "Company", "Price", "Margin of safety", "Valuation", "Action", "Triggers", "Note", ""];
  const shareTable = (items) => h("div", { class: "table-wrap" }, h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, heads.map((x, i) => {
      const cls = [i === 2 || i === 3 ? "num" : "", i === 0 ? "opt3" : "", i === 4 ? "opt4" : "", i === 2 || i === 7 ? "opt" : ""].join(" ").trim() || null;
      return FIELD_HELP[x] ? withHelp(h("th", { class: cls, tabindex: 0, text: x }), x) : h("th", { class: cls, text: x });
    }))),
    h("tbody", {}, items.map((e) => clickableRow(e.asx_code,
      h("td", { class: "opt3" }, e.scores ? [wheel(e.scores, d.axes, d.checks_per_axis, { size: 34, labels: false }), h("span", { class: "score-total", text: sum(e.scores) })] : null),
      h("td", {}, h("span", { class: "code", text: e.asx_code }), e.held ? h("span", { class: "held-tag", text: "HELD" }) : null, h("div", { class: "name", text: e.company_name || "" })),
      h("td", { class: "num opt", text: money(e.price) }),
      h("td", { class: `num ${signClass(e.margin_of_safety_percent) || ""}`.trim(), text: pct(e.margin_of_safety_percent, 0) }),
      h("td", { class: "opt4" }, valuationPill(e.margin_of_safety_percent)),
      h("td", {}, e.action ? badge(e.action) : h("span", { class: "hint", text: "not valued" })),
      h("td", {}, triggerList(e.triggers)),
      h("td", { class: "opt" }, h("div", { class: "name note-cell", title: e.note || "", text: e.note || "" })),
      h("td", { class: "act" }, rowButton("Edit", "", () => editing(e)), " ", rowButton("Remove", "danger", () => remove(e))))))));
  const table = d.items.length ? filterableTable(`watch:${d.watchlist_id}:SHARE`, WATCH_SHARE_FIELDS,
    ["score", "asx_code", "price", "margin_of_safety_percent", "valuation", "action", "triggers", "note", null], d.items, shareTable) : null;

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
  const lics = d.lics || [];
  const met = [...d.items, ...d.etfs, ...lics].filter((e) => e.triggered).length;
  const counts = [d.items.length ? plural(d.items.length, "company", "companies") : null, d.etfs.length ? plural(d.etfs.length, "ETF") : null,
    lics.length ? plural(lics.length, "LIC") : null].filter(Boolean);
  const both = d.etfs.length || lics.length;
  app.replaceChildren(...[
    h("a", { class: "back", href: "#/watchlists", text: "← Watchlists" }),
    pageHead(d.name, counts.length ? `${counts.join(", ")}${met ? `, ${plural(met, "trigger")} met` : ""}` : null),
    notice,
    table ? [both ? sectionHead("Shares") : null, table] : null,
    d.etfs.length ? [sectionHead("ETFs"), fundWatchFiltered("ETF", d, d.etfs, editing, remove)] : null,
    lics.length ? [sectionHead("LICs"), fundWatchFiltered("LIC", d, lics, editing, remove)] : null,
    !table && !d.etfs.length && !lics.length ? h("p", { class: "empty", text: "Nothing on this list yet. Add a company, ETF or LIC below, or use ☆ Add to watchlist on its page." }) : null,
    h("div", { class: "cards dash", style: "margin-top:16px" }, formCard, card("Settings", null, settings)),
  ].flat().filter(Boolean));
  if (note) notice.scrollIntoView({ block: "nearest" }); else window.scrollTo(0, 0);
}

/* ---------- ETFs (§26) and LICs (§27): each under its own heading ---------- */
/* Neither is judged on estimated value. ETFs: fee, size, distributions and
   total return. LICs (listed investment companies and trusts): the same,
   plus the share price against net tangible assets (NTA). One set of
   screens serves both, set up by FUNDS[kind]. */
const FUNDS = {
  ETF: { kind: "ETF", path: "etf", list: "#/etfs", api: "etf", noun: "ETF", nouns: "ETFs", price: "Unit price", per: "unit",
    payout: "Distribution", payouts: "Distributions", size: "Fund size", help: "etf",
    intro: "Exchange traded funds, kept apart from shares: judged on fee, size, distributions and total return rather than estimated value.",
    sort: { key: "fum_aud", dir: "desc" } },
  LIC: { kind: "LIC", path: "lic", list: "#/lics", api: "lic", noun: "LIC", nouns: "LICs", price: "Share price", per: "share",
    payout: "Dividend", payouts: "Dividends", size: "Market cap", help: "lic",
    intro: "Listed investment companies and trusts, kept apart from shares and ETFs: judged on the share price against net tangible assets (NTA), fee, dividends and total return.",
    sort: { key: "premium_now", dir: "asc" } },
};
const fundHref = (kind, code) => `#/${FUNDS[kind].path}/${code}`;
const kindTag = (kind) => h("span", { class: "tag sm etf-tag", text: kind });
/* A table row that opens a page, like clickableRow but to any address. */
function rowTo(href, ...cells) {
  const open = () => { location.hash = href; };
  return h("tr", { tabindex: 0, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } }, cells);
}
const retCell = (v, cls = "") => h("td", { class: `num ${cls} ${signClass(v) || ""}`.trim(), text: signedPct(v) });
/* Premium (+) or discount (-) to NTA: shown with its sign, not coloured as good or bad. */
const premText = (v) => (v === null || v === undefined ? NA : v < 0 ? `${fmt(-v, 1)}% discount` : v > 0 ? `${fmt(v, 1)}% premium` : "at NTA");
const premCell = (v, cls = "") => h("td", { class: `num ${cls}`.trim() },
  h("span", { class: "long", text: premText(v) }), h("span", { class: "short", text: signedPct(v) }));
const nameCell = (r, kind, star = true) => h("td", {}, h("span", { class: "code", text: r.asx_code }), star ? watchStar(r.watchlists) : null,
  r.held !== null && r.held !== false ? h("span", { class: "held-tag", text: "HELD" }) : null,
  kind === "LIC" && r.product_type === "LIT" ? kindTag("LIT") : null, h("div", { class: "name", text: r.company_name || "" }));
function monthsBefore(iso, months) {
  const d = toDate(iso); d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10);
}

/* ---------- ETFs and LICs on the dashboard, in portfolios and in watchlists ---------- */
function fundDashCard(kind, x) {
  const F = FUNDS[kind];
  if (!x || !x.count) {
    return card(F.nouns, null, h("p", { class: "empty" }, `No ${F.nouns} loaded yet. They arrive with the ASX's monthly report. `,
      h("a", { href: "#/help/asx-etf-report", text: "How" }), "."));
  }
  const items = [
    ...x.triggered.map((t) => h("li", {}, h("div", { class: "main" },
      h("a", { class: "row-link", href: fundHref(kind, t.asx_code) }, h("span", { class: "code", text: t.asx_code })),
      h("span", { class: "watch-star", "aria-hidden": "true", text: "★" }), h("span", { text: t.triggers.map((y) => y.label).join("; ") }),
      h("span", { class: "detail" }, "Watchlist trigger met on ", h("a", { href: `#/watchlist/${t.watchlist_id}`, text: t.watchlist }), t.note ? `. Note: ${t.note}` : "")))),
    ...x.cgt_soon.map((c) => h("li", {}, h("div", { class: "main" },
      h("a", { class: "row-link", href: fundHref(kind, c.asx_code) }, h("span", { class: "code", text: c.asx_code })),
      h("span", { text: `CGT discount from ${longDate(c.date)}` }),
      h("span", { class: "detail", text: `${fmt(c.units, 0)} ${kind === "LIC" ? "shares" : "units"}, ${plural(c.days, "day")} away.` })))),
  ];
  const heads = kind === "LIC" ? ["LIC", "Day move", "Premium/discount to NTA", "1-year return"] : ["ETF", "Day move", "1-year return", "Yield (12 months)"];
  const table = x.followed.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
    h("thead", {}, h("tr", {}, heads.map((t, i) =>
      withHelp(h("th", { class: [i ? "num" : "", i === 3 ? "opt2" : ""].join(" ").trim() || null, tabindex: 0, text: t }), t)))),
    h("tbody", {}, x.followed.map((r) => rowTo(fundHref(kind, r.asx_code),
      nameCell({ ...r, held: r.held ? true : null }, kind),
      retCell(r.day_change_percent),
      kind === "LIC" ? premCell(r.premium_now) : retCell(r.return_1y),
      kind === "LIC" ? retCell(r.return_1y, "opt2") : h("td", { class: "num opt2", text: pct(r.distribution_yield_12m, 1) })))))) : null;
  const v = x.value;
  const c = card(F.nouns, v.holdings ? `Your ${F.nouns}: ${money(v.value, 0)}, ${signed(v.day_change, (n) => money(n, 0))} today.` : `${plural(x.count, F.noun)} followed. Hold or watch some to see them here.`,
    items.length ? h("ul", { class: "items" }, items) : null,
    table || (v.holdings ? null : h("p", { class: "empty", text: `Add ${F.nouns} to a watchlist, or record a buy in a portfolio, and they appear here.` })),
    x.more ? h("p", { class: "card-foot", text: `and ${x.more} more.` }) : null,
    h("p", { class: "card-foot" }, h("a", { href: F.list, text: `${F.noun} screener →` })));
  c.classList.add("wide");
  return c;
}
const etfDashCard = (x) => fundDashCard("ETF", x);

/* "Shares $X (3) | ETFs $Y (2) | LICs $Z (1)" under a portfolio's figures. */
function sectionLine(sections) {
  if (!sections || !["ETF", "LIC"].some((k) => sections[k] && sections[k].holdings)) return null;
  const part = (label, s) => `${label} ${money(s.value, 0)} (${plural(s.holdings, "holding")})`;
  const parts = [["Shares", "SHARE"], ["ETFs", "ETF"], ["LICs", "LIC"]].filter(([, k]) => sections[k] && sections[k].holdings)
    .map(([label, k]) => part(label, sections[k]));
  return h("p", { class: "hint section-line", text: parts.join("  |  ") });
}

function sectionHead(title, s) {
  return h("div", { class: "section-head" }, h("h2", { text: title }),
    s && s.holdings ? h("span", { class: "sub", text: `${money(s.value, 0)} | gain ${signed(s.gain, (v) => money(v, 0))}${s.day_change !== null ? ` | today ${signed(s.day_change, (v) => money(v, 0))}` : ""}` }) : null);
}

function fundHoldingsTable(kind, lines) {
  const F = FUNDS[kind];
  const heads = [F.noun, "Units", "Cost base", F.price, "Value", "Gain", "Today", kind === "LIC" ? "Premium/discount to NTA" : "1-year return", "Yield (12 months)", "CGT discount from"];
  const numeric = new Set([1, 2, 3, 4, 5, 6, 7, 8]), optional = new Set([2, 3, 6, 8, 9]);
  return h("div", { class: "table-wrap" }, h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, heads.map((x, i) => withHelp(h("th", { class: [numeric.has(i) ? "num" : "", optional.has(i) ? "opt" : ""].join(" ").trim() || null, tabindex: 0, text: x }), x)))),
    h("tbody", {}, lines.map((r) => rowTo(fundHref(kind, r.asx_code),
      h("td", {}, h("span", { class: "code", text: r.asx_code }), h("div", { class: "name", text: r.company_name || "" })),
      h("td", { class: "num", text: fmt(r.units, 0) }),
      h("td", { class: "num opt", text: money(r.cost_base, 0) }),
      h("td", { class: "num opt", text: money(r.price) }),
      h("td", { class: "num", text: money(r.value, 0) }),
      h("td", { class: `num ${signClass(r.gain) || ""}`.trim(), text: signed(r.gain, (v) => money(v, 0)) }),
      h("td", { class: `num opt ${signClass(r.day_change) || ""}`.trim(), text: signed(r.day_change, (v) => money(v, 0)) }),
      kind === "LIC" ? premCell(r.premium_now) : retCell(r.return_1y),
      h("td", { class: "num opt", text: pct(r.distribution_yield_12m, 1) }),
      h("td", { class: "opt", text: r.next_discount_date ? longDate(r.next_discount_date) : "eligible now" }))))));
}

/* Shares, then ETFs, then LICs, each under its own heading with a subtotal. */
function holdingsSections(lines, sections, filterKey) {
  const of = (kind) => lines.filter((l) => (l.security_type || "SHARE") === kind);
  const shares = of("SHARE"), etfs = of("ETF"), lics = of("LIC");
  const table = (kind, rows, render) => {
    if (!filterKey) return render(rows);
    const fields = holdingFields(kind);
    return filterableTable(`${filterKey}:${kind}`, fields, Object.keys(fields), rows, render);
  };
  return h("div", { class: "holdings-sections" },
    shares.length ? [sectionHead("Shares", sections && sections.SHARE), table("SHARE", shares, holdingsTable)] : null,
    etfs.length ? [sectionHead("ETFs", sections && sections.ETF), table("ETF", etfs, (r) => fundHoldingsTable("ETF", r))] : null,
    lics.length ? [sectionHead("LICs", sections && sections.LIC), table("LIC", lics, (r) => fundHoldingsTable("LIC", r))] : null);
}

function fundWatchTable(kind, items, editing, remove) {
  const F = FUNDS[kind];
  const heads = [F.noun, F.price, "Day move", kind === "LIC" ? "Premium/discount to NTA" : "1-year return", "Yield (12 months)", "Triggers", "Note", ""];
  return h("div", { class: "table-wrap" }, h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, heads.map((x, i) => {
      const cls = [i >= 1 && i <= 4 ? "num" : "", i === 2 || i === 6 ? "opt4" : ""].join(" ").trim() || null;
      return FIELD_HELP[x] ? withHelp(h("th", { class: cls, tabindex: 0, text: x }), x) : h("th", { class: cls, text: x });
    }))),
    h("tbody", {}, items.map((e) => rowTo(fundHref(kind, e.asx_code),
      h("td", {}, h("span", { class: "code", text: e.asx_code }), e.held ? h("span", { class: "held-tag", text: "HELD" }) : null, h("div", { class: "name", text: e.company_name || "" })),
      h("td", { class: "num", text: money(e.price) }),
      retCell(e.day_change_percent, "opt4"),
      kind === "LIC" ? premCell(e.premium_now) : retCell(e.return_1y),
      h("td", { class: "num", text: pct(e.distribution_yield_12m, 1) }),
      h("td", {}, triggerList(e.triggers)),
      h("td", { class: "opt4" }, h("div", { class: "name note-cell", title: e.note || "", text: e.note || "" })),
      h("td", { class: "act" }, rowButton("Edit", "", () => editing(e)), " ", rowButton("Remove", "danger", () => remove(e))))))));
}

/* ---------- help (the page itself is React: frontend/src/pages/HelpPage.tsx) ---------- */
/* The menu search's term lookups (web/knowledge.json). */
const entryText = (e) => [e.title, e.abbreviation, e.full, ...(e.aliases || []), ...(e.labels || []), e.definition, e.hover, ...(e.body || [])]
  .filter(Boolean).join(" ").toLowerCase();

/* Ranked matches: title first, then names and aliases, then anywhere in the text. Every word must appear. */
function searchKnowledge(q) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const full = q.trim().toLowerCase();
  const scored = [];
  for (const e of KNOWLEDGE.entries) {
    const text = entryText(e);
    if (!words.every((w) => text.includes(w))) continue;
    const names = [e.title, e.abbreviation, e.full, ...(e.aliases || [])].filter(Boolean).map((x) => x.toLowerCase());
    const score = names.some((n) => n === full) ? 0 : e.title.toLowerCase().startsWith(full) ? 1
      : names.some((n) => n.includes(full)) ? 2 : (e.definition || "").toLowerCase().includes(full) ? 3 : 4;
    scored.push([score, e]);
  }
  return scored.sort((a, b) => a[0] - b[0] || a[1].title.localeCompare(b[1].title)).map(([, e]) => e);
}
const knowledgeEntry = (id) => KNOWLEDGE.entries.find((e) => e.id === id);
/* An exact term name typed in the menu search (title, abbreviation or alias). */
function findTerm(q) {
  const s = q.trim().toLowerCase();
  if (!s || !KNOWLEDGE.entries) return null;
  const hit = (names) => KNOWLEDGE.entries.find((e) => names(e).some((n) => n && n.toLowerCase() === s));
  return hit((e) => [e.title, e.abbreviation, e.full]) || hit((e) => e.aliases || []) || null;
}

/* ---------- admin console: model and rules, what-if scenarios, workings ---------- */
/* A small "?" that opens the Help entry for a concept. */
function helpLink(id) {
  const e = id && KNOWLEDGE.entries.find((x) => x.id === id);
  if (!e) return null;
  // Opens in a new tab, so the page you were reading (a scenario being
  // edited, a filtered screener) stays as it was.
  const href = `#/help/${id}`;
  return h("a", { class: "help-link", href, target: "_blank", rel: "noopener",
    title: `Help: ${e.title} (opens in a new tab)`, "aria-label": `Help: ${e.title}, opens in a new tab`, text: "?",
    onclick: (ev) => {
      // Opened here rather than left to the link, so nothing around it can
      // turn it into a same-tab jump. Ctrl or middle click still work as usual.
      ev.stopPropagation();
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button !== 0) return;
      ev.preventDefault();
      window.open(new URL(href, location.href).href, "_blank", "noopener");
    } });
}
const withHelpLink = (text, id) => [text, " ", helpLink(id)];

/* ---------- React islands (ADR-018: docs/kb/decisions/adr-018-react-typescript-pages.md) ---------- */
/* What the React components (frontend/, built to web/dist/sift-ui.js) borrow
   from this app while both exist. */
window.SiftHost = {
  helpEntry: (id) => { const e = knowledgeEntry(id); return e ? { id: e.id, title: e.title } : null; },
  openHelp: (id) => window.open(new URL(`#/help/${id}`, location.href).href, "_blank", "noopener"),
  isAdmin: () => Boolean(me && me.user && me.user.admin),
  knowledge: () => KNOWLEDGE,
  fieldHelp: (label) => (FIELD_HELP[label] ? FIELD_HELP[label](thresholds()) : null),
  fillThresholds: (text) => fillThresholds(text),
  settings: () => me.settings,
  previousPage: () => previousPage,
  noteVersion: (res) => noteVersion(res),
  thresholds: () => thresholds(),
  estimatedValueHelp: (method) => (ESTIMATED_VALUE_HELP[method] ? ESTIMATED_VALUE_HELP[method](thresholds()) : null),
  fundHref: (code) => { const f = (cache.companies || []).find((x) => x.code === code && FUNDS[x.type]); return f ? fundHref(f.type, code) : null; },
  afterChange: () => afterChange(),
  setThresholds: (t) => { cache.thresholds = t; },
};
/* A React component as one more card on a page this file built. The wrapper
   takes no space of its own (display: contents), so the card sits in the
   grid like any other. Islands on a page that has gone are unmounted by
   SiftUI.sweep() after each route change. */
/* A whole page built in React: replaces the page and mounts it (the router
   sweeps away the previous page's islands afterwards). With `keep`, the same
   page already on screen gets the new props instead, staying where it is
   (a fund compared with another). */
function reactPage(name, props, keep = false) {
  const current = app.firstElementChild;
  if (keep && current && current.dataset.page === name && app.children.length === 1 && window.SiftUI && window.SiftUI.update(current, props)) return Promise.resolve();
  const el = h("div", { class: "island", "data-page": name });
  app.replaceChildren(el);
  if (!(window.SiftUI && window.SiftUI.mount(name, el, props))) {
    el.append(h("p", { class: "error", text: "This page didn't load. Refresh the page; if it stays, the page files need rebuilding (frontend/README.md)." }));
  }
  return Promise.resolve();
}
function island(name, props, title) {
  const el = h("div", { class: "island", "data-island": name });
  if (!(window.SiftUI && window.SiftUI.mount(name, el, props))) {
    el.append(card(title || name, "This card didn't load. Refresh the page; if it stays, the page files need rebuilding (frontend/README.md)."));
  }
  return el;
}

/* A setting's number as the console shows it: rates and percents with %, ratios bare. */
function settingText(meta, value) {
  if (value === null || value === undefined || value === "") return NA;
  const v = Number(value);
  if (meta.unit === "rate" || meta.unit === "%") return `${fmt(v, v % 1 ? (Math.abs(v * 10) % 1 ? 2 : 1) : 0)}%`;
  if (meta.unit === "years") return plural(v, "year");
  if (meta.unit === "points") return `${fmt(v, v % 1 ? 1 : 0)} points`;
  if (meta.unit === "days") return plural(v, "day");
  if (meta.unit === "calls") return plural(v, "call");
  return fmt(v, v % 1 ? (Math.abs(v * 10) % 1 ? 2 : 1) : 0);
}

function adminTabs(current) {
  return h("div", { class: "tabs", role: "navigation", "aria-label": "Admin" },
    [["settings", "#/admin", "Settings and formulas"], ["scenarios", "#/admin/scenarios", "What-if scenarios"], ["search", "#/admin/search", "Search"], ["users", "#/admin/users", "Users"], ["kb", "#/admin/kb", "Developer"]].map(([id, href, label]) =>
      h("a", { href, class: "tab", "aria-current": id === current ? "page" : null, text: label })));
}

const PIPELINE = [
  ["Prices and annual reports are downloaded each night", "data-chip"],
  ["Estimated value: a discounted cash flow model for most companies", "dcf"],
  ["or a dividend discount model for banks, insurers and REITs", "ddm"],
  ["Margin of safety: how far the price sits below estimated value", "margin-of-safety"],
  ["Ratios: ROE, debt to equity, yields, P/E, P/B and the Graham Number", "roe"],
  ["The four value tests", "four-value-tests"],
  ["Markers: earnings quality, price signal, dividend and fundamentals trends, momentum", "earnings-quality"],
  ["Red flags", "red-flag"],
  ["The suggested action and its reason", "suggested-action"],
  ["The score wheel: 30 checks across five spokes", "score-wheel"],
  ["Recorded each night and scored later for the track record", "track-record-scoring"],
];

async function renderAdmin() {
  app.replaceChildren(h("p", { class: "loading", text: "Loading settings..." }));
  const d = await getJSON("/api/admin/settings");
  cache.adminSettings = d;
  const pipeline = card("How a result is made", "Open any company and choose Show workings to see these steps with its own numbers.",
    h("ol", { class: "pipeline" }, PIPELINE.map(([text, id]) => h("li", {}, withHelpLink(text, id)))));
  pipeline.classList.add("wide");
  const groups = d.groups.map((g) => {
    const c = card(g.name, null, h("div", { class: "table-wrap" }, h("table", { class: "grid compact settings-table" },
      h("thead", {}, h("tr", {}, ["Setting", "Live value", "Allowed", "Formula", "Used in"].map((x, i) =>
        h("th", { class: [i === 1 ? "num" : "", i === 2 ? "opt" : "", i === 4 ? "opt4" : ""].join(" ").trim() || null, text: x })))),
      h("tbody", {}, d.settings.filter((sx) => sx.group === g.id).map((sx) => h("tr", { class: "static" },
        h("td", {}, withHelpLink(sx.label, sx.help_id)),
        h("td", { class: "num strong", text: settingText(sx, sx.live) }),
        h("td", { class: "opt hint", text: `${settingText(sx, sx.minimum)} to ${settingText(sx, sx.maximum)}` }),
        h("td", { class: "formula", text: sx.formula }),
        h("td", { class: "opt4 hint", text: sx.used_in })))))),
      g.id === "statistics" ? statisticsMethods(d.statistics_methods) : null);
    c.classList.add("wide");
    return c;
  });
  app.replaceChildren(pageHead("Model and rules", "Every setting behind Sift's results"), adminTabs("settings"),
    h("div", { class: "cards" }, pipeline, ...groups,
      card("Trying other values", null, h("p", { class: "hint" }, "Change these in a ",
        h("a", { href: "#/admin/scenarios", text: "what-if scenario" }), " to see what would change. The live settings stay as they are. ", helpLink("scenario"))),
      rulesVersionsCard()));
  window.scrollTo(0, 0);
}

/* The statistics' fixed methods, under its two settings: fixed so a result
   can't be tuned until a rule "passes" (ADR-017). */
function statisticsMethods(methods) {
  if (!methods || !methods.length) return null;
  return [h("p", { class: "mini-head stats-methods-head", text: "Fixed by design" }),
    h("p", { class: "hint", text: "These aren't settings, so no one can adjust the method until a rule looks better. They don't change any company's action, so they're not in what-if scenarios." }),
    h("dl", { class: "kv stats-methods" }, methods.flatMap((m) => [h("dt", { text: m.name }), h("dd", {}, h("span", { class: "strong", text: m.value }), h("span", { class: "hint", text: ` ${m.why}` }))])),
    h("p", { class: "hint" }, "The theory behind each, with references: ", h("a", { href: "#/help/statistics-theory", text: "The theory behind Sift's statistics" }),
      " (Help) and the developer article ", h("a", { href: "#/admin/kb/statistics", text: "Statistics" }), ".")];
}

/* Each set of screening rules the track record judges separately, with what
   changed. People see one track record; admins can open each version's own. */
function rulesVersionsCard() {
  const body = h("div", {}, h("p", { class: "loading", text: "Loading..." }));
  getJSON("/api/admin/rules-versions").then((d) => body.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "grid rules-versions" },
    h("thead", {}, h("tr", {}, [["Version"], ["In use from", "opt"], ["What changed"], ["Calls recorded", "num opt"], ["", "num"]].map(([t, c]) => h("th", { scope: "col", class: c || null, text: t })))),
    h("tbody", {}, d.versions.map((v) => h("tr", { class: "static" },
      h("td", {}, h("div", { class: "strong", text: v.label }), v.current ? h("span", { class: "tag sm", text: "In use" }) : null,
        h("div", { class: "sub-text phone-only", text: `From ${longDate(v.in_use_from)}` })),
      h("td", { class: "opt", text: longDate(v.in_use_from) }),
      h("td", {}, h("div", { class: "strong", text: v.title }), v.changes ? h("div", { class: "sub-text", text: v.changes }) : null),
      h("td", { class: "num opt", title: v.first_night ? `${longDate(v.first_night)} to ${longDate(v.last_night)}` : "",
        text: v.calls ? `${fmt(v.calls, 0)} over ${plural(v.nights, "night")}` : "None yet" }),
      h("td", { class: "num" }, h("a", { href: `#/track-record?version=${encodeURIComponent(v.version)}`, text: "Track record" })))))))))
    .catch((err) => body.replaceChildren(h("p", { class: "error", text: err.message })));
  const c = card("Rules versions", "Each time the screening rules change (thresholds, actions, scores or valuation models), Sift starts a new version, so the track record judges each set of rules on its own results. People see one track record of every version; open a version's own here.", body);
  c.classList.add("wide");
  return c;
}

async function renderScenarios() {
  app.replaceChildren(h("p", { class: "loading", text: "Loading scenarios..." }));
  const d = await getJSON("/api/admin/scenarios");
  const list = d.scenarios.length ? h("div", { class: "cards" }, d.scenarios.map((x) => h("a", { class: "card pf-card", href: `#/admin/scenario/${x.scenario_id}` },
    h("div", { class: "pf-head" }, h("h2", { text: x.name })),
    h("p", { class: "hint", text: x.changes ? plural(x.changes, "setting changed", "settings changed") : "No changes from live yet" }),
    x.notes ? h("p", { class: "hint", text: x.notes }) : null)))
    : h("p", { class: "empty", text: "No scenarios yet. A scenario is a set of changed settings you can run against today's data without changing anything live." });
  app.replaceChildren(pageHead("What-if scenarios", null), adminTabs("scenarios"),
    h("p", {}, h("a", { class: "btn primary", href: "#/admin/scenario/new", text: "New scenario" }), " ", helpLink("scenario")),
    list);
  window.scrollTo(0, 0);
}

function arrowPair(a, b, format) {
  const same = format(a) === format(b);
  return same ? h("span", { text: format(b) }) : h("span", { class: "pair" }, h("span", { class: "was", text: format(a) }), " → ", h("strong", { text: format(b) }));
}

function resultTable(items, axesNote) {
  return h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
    h("thead", {}, h("tr", {}, ["Company", "Action", "Valuation", "Estimated value", "Margin of safety", "Score"].map((x, i) =>
      h("th", { class: [i >= 3 ? "num" : "", i === 2 || i === 5 ? "opt" : ""].join(" ").trim() || null, text: x })))),
    h("tbody", {}, items.map((it) => clickableRow(it.asx_code,
      h("td", {}, h("span", { class: "code", text: it.asx_code }), watchStar(it.watchlists), it.held ? h("span", { class: "held-tag", text: "HELD" }) : null,
        h("div", { class: "name", text: it.company_name || "" })),
      h("td", {}, it.live_action === it.action ? badge(it.action) : h("span", { class: "pair" }, badge(it.live_action), h("span", { class: "arrow", text: "→" }), badge(it.action))),
      h("td", { class: "opt" }, arrowPair(it.live_status, it.status, (x) => x || NA)),
      h("td", { class: "num" }, arrowPair(it.live_value, it.value, (x) => money(x))),
      h("td", { class: "num" }, arrowPair(it.live_mos, it.mos, (x) => pct(x, 0))),
      h("td", { class: "num opt" }, arrowPair(it.live_score, it.score, (x) => String(x))))))));
}

function scenarioResults(r, metaByKey) {
  const out = [];
  const changes = r.changes.length
    ? h("ul", { class: "items" }, r.changes.map((c) => h("li", {}, h("div", { class: "main" }, withHelpLink(c.label, c.help_id)),
      h("div", { class: "side" }, h("span", { class: "was", text: settingText(metaByKey[c.key], c.live) }), " → ", h("strong", { text: settingText(metaByKey[c.key], c.scenario) })))))
    : h("p", { class: "empty", text: "No settings changed: these are the live results, recalculated." });
  out.push(card("What this scenario changes", null, changes));
  const s = r.summary;
  const buy = r.counts.find((c) => c.action === "BUY") || { live: 0, scenario: 0 };
  const tile = (label, a, b, f, help) => h("div", { class: "stat" },
    h("div", { class: "stat-label" }, label, " ", helpLink(help)), h("div", { class: "stat-value" }, arrowPair(a, b, f)));
  const strip = h("div", { class: "stats" },
    tile("BUY signals", buy.live, buy.scenario, String, "suggested-action"),
    tile("Median margin of safety", s.median_mos[0], s.median_mos[1], (x) => pct(x, 0), "margin-of-safety"),
    tile("Average score", s.average_score[0], s.average_score[1], (x) => fmt(x, 1), "score-wheel"),
    tile("Companies valued", s.valued[0], s.valued[1], String, "estimated-value"));
  const counts = card("Suggested actions", `Across ${plural(r.companies, "company", "companies")}, live against this scenario.`,
    h("div", { class: "table-wrap" }, h("table", { class: "grid compact" },
      h("thead", {}, h("tr", {}, ["Action", "Live", "Scenario", "Change"].map((x, i) => h("th", { class: i ? "num" : null, text: x })))),
      h("tbody", {}, r.counts.map((c) => h("tr", { class: "static" }, h("td", {}, badge(c.action)), h("td", { class: "num", text: c.live }),
        h("td", { class: "num", text: c.scenario }),
        h("td", { class: `num ${signClass(c.scenario - c.live) || ""}`.trim(), text: signed(c.scenario - c.live, String) })))))),
    h("p", { class: "card-foot" }, helpLink("suggested-action"), " What each action means"));
  const moves = card("Moves between actions", null, r.moves.length
    ? h("ul", { class: "items" }, r.moves.map((m) => h("li", {}, h("div", { class: "main" }, badge(m.from), h("span", { class: "arrow", text: "→" }), badge(m.to)),
      h("div", { class: "side", text: plural(m.companies, "company", "companies") }))))
    : h("p", { class: "empty", text: "No company changes action." }));
  const bins = r.distribution.map((b) => b.low === null ? `under ${fmt(b.high, 0)}%` : b.high === null ? `${fmt(b.low, 0)}% up` : `${fmt(b.low, 0)} to ${fmt(b.high, 0)}%`);
  const dist = card("Spread of margins of safety", "How many companies fall in each band, live against this scenario.",
    chartSlot((w) => columnChart({ categories: bins, yFmt: (v) => fmt(v, 0), label: "Companies by margin of safety band, live and scenario", width: w,
      series: [{ name: "Live", color: "--s1", values: r.distribution.map((b) => b.live) }, { name: "Scenario", color: "--s2", values: r.distribution.map((b) => b.scenario) }] })),
    tableView(["Margin of safety", "Live", "Scenario"], r.distribution.map((b, i) => [bins[i], String(b.live), String(b.scenario)])));
  dist.classList.add("wide");
  const MAX = 100;
  const changed = card("Companies that change", r.changed.length ? `${plural(r.changed.length, "company", "companies")} change action or valuation status, better moves first.` : null,
    r.changed.length ? resultTable(r.changed.slice(0, MAX)) : h("p", { class: "empty", text: "No company changes action or valuation status." }),
    r.changed.length > MAX ? h("p", { class: "card-foot", text: `and ${r.changed.length - MAX} more.` }) : null);
  changed.classList.add("wide");
  const mine = card("Your holdings and watchlists", "Every company you hold or watch, live against this scenario.",
    r.mine.length ? resultTable(r.mine) : h("p", { class: "empty", text: "You don't hold or watch any screened company." }));
  mine.classList.add("wide");
  out.push(counts, moves, dist, changed, mine);
  return [strip, h("div", { class: "cards", style: "margin-top:16px" }, out)];
}

async function renderScenario(id) {
  app.replaceChildren(h("p", { class: "loading", text: "Loading scenario..." }));
  const meta = cache.adminSettings || (cache.adminSettings = await getJSON("/api/admin/settings"));
  const metaByKey = Object.fromEntries(meta.settings.map((x) => [x.key, x]));
  const saved = id ? await getJSON(`/api/admin/scenarios/${encodeURIComponent(id)}`) : { name: "", notes: "", overrides: {} };
  const name = h("input", { name: "name", value: saved.name, maxlength: 60, placeholder: "e.g. Cautious: 10% discount", autocomplete: "off" });
  const notes = h("input", { name: "notes", value: saved.notes || "", maxlength: 1000, placeholder: "What you're testing", autocomplete: "off" });
  const inputs = {};
  const groups = meta.groups.filter((g) => g.what_if !== false).map((g) => h("details", { class: "axis-block", open: meta.settings.some((x) => x.group === g.id && saved.overrides[x.key] !== undefined) || g.id === "valuation" },
    h("summary", {}, h("span", { class: "twisty", "aria-hidden": "true" }), h("span", { class: "axis-name", text: g.name })),
    h("div", { class: "setting-rows" }, meta.settings.filter((x) => x.group === g.id).map((x) => {
      const input = h("input", { inputmode: "decimal", autocomplete: "off", value: saved.overrides[x.key] ?? "",
        placeholder: String(Number(x.live)), "aria-label": x.label });
      const mark = () => input.classList.toggle("changed", input.value.trim() !== "" && Number(input.value) !== Number(x.live));
      input.addEventListener("input", mark); mark();
      inputs[x.key] = input;
      const unit = x.unit === "rate" || x.unit === "%" ? "%" : x.unit === "x" ? "x" : x.unit === "years" ? "years" : x.unit === "points" ? "points" : x.unit === "days" ? "days" : "";
      return h("label", { class: "setting-row" },
        h("span", { class: "setting-name" }, withHelpLink(x.label, x.help_id)),
        h("span", { class: "setting-input" }, input, h("span", { class: "unit", text: unit })),
        h("span", { class: "setting-live", text: `live ${settingText(x, x.live)}` }));
    }))));
  const overrides = () => Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value.trim()]).filter(([, v]) => v !== ""));
  const msg = formMessage();
  const results = h("div", { class: "scenario-results" });
  const run = async () => {
    results.replaceChildren(h("p", { class: "loading", text: "Running against today's data..." }));
    try {
      const r = await send("POST", "/api/admin/run", { overrides: overrides() });
      results.replaceChildren(...scenarioResults(r, metaByKey));
      drawSlots();
    } catch (err) { results.replaceChildren(); showMessage(msg, err.message, false); }
  };
  const save = async () => {
    try {
      const body = { name: name.value, notes: notes.value, overrides: overrides() };
      const x = id ? await send("PUT", `/api/admin/scenarios/${id}`, body) : await send("POST", "/api/admin/scenarios", body);
      if (!id) { cache.flash = `Saved ${x.name}.`; location.hash = `#/admin/scenario/${x.scenario_id}`; return; }
      showMessage(msg, `Saved ${x.name}.`, true);
    } catch (err) { showMessage(msg, err.message, false); }
  };
  const remove = async () => {
    if (!confirm(`Delete the scenario ${saved.name}? This can't be undone. Nothing live is affected.`)) return;
    try { await send("DELETE", `/api/admin/scenarios/${id}`); location.hash = "#/admin/scenarios"; }
    catch (err) { showMessage(msg, err.message, false); }
  };
  const reset = () => { Object.values(inputs).forEach((el) => { el.value = ""; el.classList.remove("changed"); }); results.replaceChildren(); };
  const editor = card("Settings to try", "Leave a box blank to keep its live value. Rates are in percent. Nothing live changes, whatever you try here.",
    h("div", { class: "form-grid" }, field("Name", name), field("Notes", notes)),
    h("div", { class: "scenario-groups" }, groups),
    h("div", { class: "form-actions", style: "margin-top:12px" },
      h("button", { class: "btn primary", type: "button", text: "Run against today's data", onclick: run }),
      h("button", { class: "btn", type: "button", text: "Save", onclick: save }),
      h("button", { class: "btn", type: "button", text: "Reset to live", onclick: reset }),
      id ? h("button", { class: "btn danger", type: "button", text: "Delete", onclick: remove }) : null),
    msg);
  editor.classList.add("wide");
  app.replaceChildren(h("a", { class: "back", href: "#/admin/scenarios", text: "← Scenarios" }),
    pageHead(id ? saved.name : "New scenario", "What-if against today's data", helpLink("scenario")),
    adminTabs("scenarios"), h("div", { class: "cards" }, editor), results);
  if (cache.flash) { showMessage(msg, cache.flash, true); cache.flash = null; }
  window.scrollTo(0, 0);
  if (id) run();
}

/* ---------- printing (Print or save as PDF, avatar menu; also Ctrl+P) ----------
   A4 landscape (style.css, @media print). Printed in the light theme whatever
   the screen uses, with a heading naming the page and the date; charts are
   redrawn in print colours and back again afterwards. */
let printedTheme = null;
window.addEventListener("beforeprint", () => {
  const root = document.documentElement;
  printedTheme = root.getAttribute("data-theme");
  root.setAttribute("data-theme", "light");
  const title = (document.querySelector("#app h1") || {}).textContent || "Sift";
  const sub = (document.querySelector("#app .page-head .sub") || {}).textContent || "";
  document.getElementById("print-head")?.remove();
  app.before(h("div", { id: "print-head", class: "print-head", text:
    `Sift  |  ${title}${sub ? `: ${sub}` : ""}  |  printed ${new Date().toLocaleString("en-AU", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}` }));
  slots.forEach((sl) => { delete sl.el.dataset.w; });
  drawSlots();
});
window.addEventListener("afterprint", () => {
  if (printedTheme) document.documentElement.setAttribute("data-theme", printedTheme);
  document.getElementById("print-head")?.remove();
  slots.forEach((sl) => { delete sl.el.dataset.w; });
  drawSlots();
});

/* ---------- you: avatar menu, preferences, shortcuts, impersonation (§35) ---------- */
const THEME_KEY = "sift-theme";  // kept in the browser too, so the page opens in the right theme before Sift answers
function applyTheme(choice) {
  if (choice !== "light") choice = "dark";  // two themes, dark unless light is chosen (§35)
  document.documentElement.setAttribute("data-theme", choice);
  try { localStorage.setItem(THEME_KEY, choice); } catch (e) { /* not kept; still applied */ }
  slots.forEach((sl) => { delete sl.el.dataset.w; }); // charts pick up the new colours on redraw
  drawSlots();
}
/* Settings show as classes on the page (style.css "Preferences"), so every page follows them without being redrawn. */
const SETTING_CLASSES = { compact: "pref-compact", wrap_text: "pref-wrap", reduce_motion: "pref-reduce-motion",
  chart_patterns: "pref-patterns", show_hover_buttons: "pref-hover-buttons" };
function applySettings(settings) {
  const before = me.settings;
  me.settings = { ...SETTING_DEFAULTS, ...settings };
  const root = document.documentElement;
  for (const [key, cls] of Object.entries(SETTING_CLASSES)) root.classList.toggle(cls, !!me.settings[key]);
  root.classList.toggle("pref-no-tips", !me.settings.help_tips);
  PAGE_SIZE = me.settings.rows_shown;
  if (before.theme !== me.settings.theme || !root.dataset.themeApplied) { root.dataset.themeApplied = "1"; applyTheme(me.settings.theme); }
  if (before.chart_patterns !== me.settings.chart_patterns) { slots.forEach((sl) => { delete sl.el.dataset.w; }); drawSlots(); }
  setSearchPage(searchScope.page);
}
/* Applied at once, then saved to the account. If the save fails the change
   stays in this page (and, for the theme, this browser) and a quiet note says
   so on the Preferences page: never a popup (§35). `revert` puts it back instead. */
async function saveSettings(changes, { revert = false } = {}) {
  const before = me.settings;
  applySettings({ ...before, ...changes });
  try {
    applySettings((await send("PUT", "/api/me/settings", changes)).settings);
    prefNotice("");
  } catch (err) {
    if (revert) applySettings(before);
    prefNotice(`Not saved to your account (${err.message}); it applies in this browser for now.`);
    throw err;
  }
}
function prefNotice(text) {
  const el = document.getElementById("pref-msg");
  if (el) showMessage(el, text, false);
}
const initials = (name) => (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
function paintMe() {
  const u = me.user;
  if (!u) return;
  for (const id of ["user-avatar", "user-avatar-lg"]) document.getElementById(id).textContent = initials(u.display_name);
  document.getElementById("user-name").textContent = u.display_name;
  document.getElementById("user-role").textContent = u.admin ? "Admin" : "Member";
  document.getElementById("user-btn").setAttribute("aria-label", `${u.display_name}: profile and preferences`);
  // Admin links show only to an admin who isn't impersonating anyone (Sift closes the console meanwhile).
  document.querySelector(".user-admin").hidden = !u.admin;
  const banner = document.getElementById("imp-banner");
  banner.hidden = !me.by;
  document.documentElement.classList.toggle("impersonating", !!me.by);
  if (me.by) {
    banner.replaceChildren(h("span", {}, "You're impersonating ", h("strong", { text: u.display_name }), ` (${u.email}). Everything you see and change is as them.`),
      h("button", { type: "button", class: "btn small", text: "End impersonation", onclick: endImpersonation }));
  }
}
const meReady = getJSON("/api/me").then((m) => {
  me.user = m; me.by = m.impersonated_by;
  applySettings(m.settings);
  paintMe();
  // Before Preferences the theme lived only in this browser: carry it over once, if the account hasn't chosen one.
  let local = null;
  try { local = localStorage.getItem(THEME_KEY); } catch (e) { /* no storage */ }
  if (!me.by && !(m.settings_chosen || []).includes("theme") && local === "light" && m.settings.theme !== "light") {
    saveSettings({ theme: "light" }).catch(() => {});
  }
}).catch(() => { /* Sift still works with the defaults */ });
async function endImpersonation() {
  try { await send("DELETE", "/api/impersonation"); } finally { location.hash = "#/"; location.reload(); }
}

(function initUserMenu() {
  const btn = document.getElementById("user-btn"), menu = document.getElementById("user-menu");
  const items = () => [...menu.querySelectorAll("[role=menuitem]")].filter((x) => x.offsetParent !== null);
  const setOpen = (open, focusFirst = false) => {
    menu.hidden = !open; btn.setAttribute("aria-expanded", open);
    if (open && focusFirst) items()[0]?.focus();
  };
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden, e.detail === 0); });
  menu.addEventListener("click", (e) => { e.stopPropagation(); if (e.target.closest("[role=menuitem]")) setOpen(false); });
  menu.addEventListener("keydown", (e) => {
    const list = items(), i = list.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      list[(i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length]?.focus();
    }
  });
  document.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { setOpen(false); btn.focus(); } });
  document.getElementById("shortcuts-open").addEventListener("click", openShortcuts);
  document.getElementById("print-page").addEventListener("click", () => { setOpen(false); setTimeout(() => window.print(), 50); });
  document.getElementById("impersonate-open").addEventListener("click", openImpersonate);
  try { const t = localStorage.getItem(THEME_KEY); if (t) applyTheme(t); } catch (e) { /* follow the system */ }
})();

/* Keyboard shortcuts: "/" to search, "g" then a letter to go somewhere, "?" for the list. */
const GO_KEYS = [["d", "#/", "Dashboard"], ["s", "#/screener", "ASX Stocks"], ["e", "#/etfs", "ETFs"], ["l", "#/lics", "LICs"],
  ["w", "#/watchlists", "Watchlists"], ["p", "#/portfolios", "Portfolios"], ["t", "#/track-record", "Track record"],
  ["c", "#/coattail", "Coattail"], ["h", "#/help", "Help"], ["f", "#/preferences", "Preferences"]];
function modal(id, title, ...body) {
  const dlg = document.getElementById(id);
  dlg.replaceChildren(h("div", { class: "modal-head" }, h("h2", { id: `${id.split("-")[0]}-title`, text: title }),
    h("button", { type: "button", class: "icon-x", "aria-label": "Close", text: "✕", onclick: () => dlg.close() })), ...body.flat().filter(Boolean));
  if (!dlg.open) dlg.showModal();
  dlg.onclick = (e) => { if (e.target === dlg) dlg.close(); };  // a click on the backdrop closes it
  return dlg;
}
function openShortcuts() {
  const kbd = (...keys) => h("span", { class: "keys" }, keys.map((k) => h("kbd", { text: k })));
  modal("shortcuts-dialog", "Keyboard shortcuts",
    me.settings.keyboard_shortcuts ? null : h("p", { class: "form-msg bad", text: "Shortcuts are off. Turn them on in Preferences, Accessibility." }),
    h("table", { class: "grid shortcuts" }, h("tbody", {},
      h("tr", {}, h("td", {}, kbd("/")), h("td", { text: "Search" })),
      h("tr", {}, h("td", {}, kbd("?")), h("td", { text: "Show these shortcuts" })),
      h("tr", {}, h("td", {}, kbd("Esc")), h("td", { text: "Close a menu or this window" })),
      GO_KEYS.map(([k, , label]) => h("tr", {}, h("td", {}, kbd("g", k)), h("td", { text: `Go to ${label}` }))))));
}
(function initShortcuts() {
  let goPending = 0;
  document.addEventListener("keydown", (e) => {
    if (!me.settings.keyboard_shortcuts || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable], dialog")) return;
    if (goPending && Date.now() - goPending < 1500) {
      goPending = 0;
      const go = GO_KEYS.find(([k]) => k === e.key.toLowerCase());
      if (go) { e.preventDefault(); location.hash = go[1]; }
      return;
    }
    if (e.key === "/") { e.preventDefault(); document.getElementById("nav-search-input").focus(); }
    else if (e.key === "?") { e.preventDefault(); openShortcuts(); }
    else if (e.key === "g") goPending = Date.now();
  });
})();

async function openImpersonate() {
  const msg = h("p", { class: "form-msg", role: "status" });
  const pick = h("select", { id: "imp-user", "aria-label": "Person to impersonate" }, h("option", { value: "", text: "Loading..." }));
  const start = h("button", { type: "submit", class: "btn primary", text: "Start impersonating", disabled: true });
  const form = h("form", { class: "imp-form", onsubmit: async (e) => {
    e.preventDefault();
    if (!pick.value) return;
    start.disabled = true;
    try { await send("POST", "/api/admin/impersonate", { user_id: pick.value }); location.hash = "#/"; location.reload(); }
    catch (err) { showMessage(msg, err.message, false); start.disabled = false; }
  } }, h("label", { class: "field" }, h("span", { class: "field-label", text: "Act as" }), pick), start, msg);
  modal("impersonate-dialog", "Impersonate user",
    h("p", { class: "sub-text", text: "See and use Sift exactly as this person does, to help them or check what they see. Anything you change is saved as them. A banner shows until you end it; it ends by itself after 8 hours, and every session is logged in Admin, Users." }),
    form);
  try {
    const d = await getJSON("/api/admin/users");
    const members = d.users.filter((u) => u.role === "member" && u.status === "active");
    pick.replaceChildren(members.length ? h("option", { value: "", text: "Choose a person" }) : h("option", { value: "", text: "No members yet: add one in Admin, Users" }),
      ...members.map((u) => h("option", { value: u.user_id, text: `${u.display_name} (${u.email})` })));
    pick.onchange = () => { start.disabled = !pick.value; };
  } catch (err) { showMessage(msg, err.message, false); }
}

/* ---------- Profile and Preferences pages ---------- */
async function renderProfile() {
  app.replaceChildren(pageHead("Profile", null), h("p", { class: "loading", text: "Loading..." }));
  await meReady;
  const u = await getJSON("/api/me");
  const msg = h("p", { class: "form-msg", role: "status" });
  const name = h("input", { id: "profile-name", value: u.display_name, maxlength: 80, autocomplete: "name" });
  const form = h("form", { class: "form-grid", onsubmit: async (e) => {
    e.preventDefault();
    try {
      const out = await send("PATCH", "/api/me", { display_name: name.value });
      me.user = { ...me.user, display_name: out.display_name }; paintMe();
      name.value = out.display_name;
      showMessage(msg, "Saved", true);
    } catch (err) { showMessage(msg, err.message, false); }
  } },
    h("label", { class: "field" }, h("span", { class: "field-label", text: "Display name" }), name,
      h("span", { class: "field-hint", text: "How Sift greets you and how admins see you." })),
    h("label", { class: "field" }, h("span", { class: "field-label", text: "Email" }), h("input", { value: u.email, readonly: true, "aria-readonly": "true" }),
      h("span", { class: "field-hint", text: "Changes with sign-in, coming in a later release." })),
    h("div", { class: "form-actions" }, h("button", { type: "submit", class: "btn primary", text: "Save" })), msg);
  const facts = h("dl", { class: "facts" },
    h("dt", { text: "Role" }), h("dd", { text: u.admin ? "Admin: manages Sift's settings and accounts" : "Member" }),
    u.impersonated_by ? [h("dt", { text: "Impersonated by" }), h("dd", { text: u.impersonated_by.display_name })] : null,
    u.previous_session ? [h("dt", { text: "Previous visit" }), h("dd", { text: `${when(u.previous_session.started_at)}${u.previous_session.client ? `, ${u.previous_session.client}` : ""}` })] : null);
  const links = h("ul", { class: "related-links" },
    h("li", {}, h("a", { href: "#/preferences", text: "Preferences" })),
    h("li", {}, h("a", { href: "#/profile", text: "Keyboard shortcuts", onclick: (e) => { e.preventDefault(); openShortcuts(); } })),
    u.admin ? h("li", {}, h("a", { href: "#/admin/users", text: "Users" })) : null);
  app.replaceChildren(pageHead("Profile", u.display_name),
    h("div", { class: "cards" },
      h("div", { class: "card profile-card" },
        h("div", { class: "profile-top" }, h("span", { class: "avatar xl", "aria-hidden": "true", text: initials(u.display_name) }),
          h("div", {}, h("div", { class: "user-name", text: u.display_name }), h("div", { class: "user-role", text: u.admin ? "Admin" : "Member" }))),
        form),
      h("div", { class: "card" }, h("h2", { text: "Account" }), facts, h("h3", { class: "related-head", text: "Related links" }), links)));
  window.scrollTo(0, 0);
}

/* Each preference: section, key, title, help, and its control (a switch unless `choices`). */
const PREFS = [
  ["display", "compact", "Use compact spacing", "Tighter cards and table rows, so more fits on the screen."],
  ["display", "wrap_text", "Wrap long text in tables", "Long company and fund names wrap onto a second line instead of being cut off."],
  ["display", "help_tips", "Show help tips", "The small \"i\" beside terms that explains them."],
  ["accessibility", "reduce_motion", "Reduce motion", "Turns off animations and smooth scrolling."],
  ["accessibility", "chart_patterns", "Patterns as well as colours in charts", "Dashed lines and hatched bars, so series can be told apart without colour."],
  ["accessibility", "chart_tables", "Show charts' data tables", "Opens the data table under every chart."],
  ["accessibility", "show_hover_buttons", "Show all buttons without hovering", "Buttons that normally appear when you point at something are always shown."],
  ["accessibility", "keyboard_shortcuts", "Enable keyboard shortcuts", "\"/\" to search, \"g\" then a letter to go somewhere, \"?\" for the list.", true],
  ["experience", "start_page", "Start page", "The page Sift opens on.", null,
    [["dashboard", "Dashboard"], ["screener", "ASX Stocks"], ["etfs", "ETFs"], ["lics", "LICs"], ["watchlists", "Watchlists"],
     ["portfolios", "Portfolios"], ["track-record", "Track record"], ["coattail", "Coattail"]]],
  ["experience", "search_scope", "Search box searches", "What the search box at the top looks through until you change it with ▾.", null,
    [["auto", "Everything on the dashboard, the page itself elsewhere"], ["all", "Everything, on every page"], ["page", "The page you're on"]]],
  ["experience", "rows_shown", "Rows shown in long tables", "How many rows the screener, ETF and LIC lists show before \"Show more\".", null,
    [[50, "50"], [100, "100"], [250, "250"]]],
];
const PREF_SECTIONS = [["display", "Display", "M3 5h18v12H3zM8 21h8M12 17v4"], ["theme", "Theme", "M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2s-1-1.5-1-2.5 1-1.5 2-1.5h2a4 4 0 0 0 4-4c0-4.5-4-8-9-8zM7.5 11.5h0M10 7.5h0M15 7.5h0"],
  ["accessibility", "Accessibility", "M12 3.5a1.5 1.5 0 1 0 0 .01M5 8.5l7 1.5 7-1.5M12 10v5M9 21l3-6 3 6"], ["experience", "User experience", "M4 4l7 17 2.5-7.5L21 11z"]];
/* Each theme's tile: its own colours as thick stripes, on white (light) or black (dark).
   The colours come from style.css (--sw-light-*, --sw-dark-*), kept beside each theme's tokens. */
const THEMES = [["dark", "Dark", "Black pages, light text. The default"], ["light", "Light", "White pages, dark text"]];
const THEME_STRIPES = 7;

function prefSwitch(key, label) {
  const on = !!me.settings[key];
  const sw = h("button", { type: "button", role: "switch", class: "switch", "aria-checked": String(on), "aria-label": label });
  sw.addEventListener("click", async () => {
    const value = sw.getAttribute("aria-checked") !== "true";
    sw.setAttribute("aria-checked", String(value));
    try { await saveSettings({ [key]: value }); } catch (err) { /* noted on the page; the switch keeps its new position */ }
  });
  return sw;
}
function prefChoice(key, label, choices) {
  const sel = h("select", { "aria-label": label, onchange: async (e) => {
    const raw = e.target.value, value = typeof choices[0][0] === "number" ? Number(raw) : raw;
    try { await saveSettings({ [key]: value }); } catch (err) { /* noted on the page */ }
  } }, choices.map(([v, text]) => h("option", { value: v, text, selected: me.settings[key] === v })));
  return sel;
}
function prefCard([, key, title, help, , choices]) {
  return h("div", { class: `card pref-card${choices ? " pref-choice" : ""}`, "data-pref": key },
    h("div", { class: "pref-text" }, h("div", { class: "pref-title", text: title }), h("div", { class: "pref-help", text: help })),
    choices ? prefChoice(key, title, choices) : prefSwitch(key, title));
}
function themeCards() {
  return h("div", { class: "theme-cards", role: "radiogroup", "aria-label": "Theme" }, THEMES.map(([value, label, note]) => {
    const card = h("button", { type: "button", role: "radio", class: `theme-card theme-${value}`, "aria-checked": String(me.settings.theme === value),
      onclick: async () => {
        for (const c of card.parentNode.children) c.setAttribute("aria-checked", String(c === card));
        try { await saveSettings({ theme: value }); } catch (err) { /* the theme stays switched; noted on the page */ }
      } },
      h("span", { class: "theme-swatch", "aria-hidden": "true" },
        Array.from({ length: THEME_STRIPES }, (_, i) => h("span", { class: "theme-stripe", style: `background:var(--sw-${value}-${i + 1})` }))),
      h("span", { class: "theme-label" }, h("span", { class: "theme-name", text: label }), h("span", { class: "theme-note", text: note }),
        h("span", { class: "theme-tick", "aria-hidden": "true", text: "✓" })));
    return card;
  }));
}
async function renderPreferences(section) {
  await meReady;
  const current = PREF_SECTIONS.some(([id]) => id === section) ? section : "display";
  const pane = h("div", { class: "pref-pane" });
  const search = h("input", { type: "search", class: "pref-search", placeholder: "Search preferences", "aria-label": "Search preferences" });
  const nav = h("nav", { class: "pref-nav", "aria-label": "Preference sections" },
    search,
    PREF_SECTIONS.map(([id, label, d]) => h("a", { href: `#/preferences/${id}`, class: "pref-link", "aria-current": id === current ? "page" : null },
      s("svg", { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" }, s("path", { d })),
      label)));
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    if (q) {
      const hits = PREFS.filter((p) => `${p[2]} ${p[3]}`.toLowerCase().includes(q));
      const theme = "theme light dark mode colour color".includes(q);
      pane.replaceChildren(...[h("h2", { text: `Matching "${search.value.trim()}"` }),
        theme ? themeCards() : null,
        hits.length ? h("div", { class: "pref-grid" }, hits.map(prefCard)) : theme ? null : h("p", { class: "sub-text", text: "No preference matches." })].filter(Boolean));
      return;
    }
    const label = PREF_SECTIONS.find(([id]) => id === current)[1];
    pane.replaceChildren(h("h2", { text: label }),
      current === "theme" ? themeCards() : h("div", { class: "pref-grid" }, PREFS.filter((p) => p[0] === current).map(prefCard)));
  };
  search.addEventListener("input", paint);
  paint();
  const reset = h("button", { type: "button", class: "btn", text: "Reset all to defaults", onclick: async () => {
    if (!confirm("Put every preference back to Sift's default?")) return;
    try { applySettings((await send("DELETE", "/api/me/settings")).settings); paint(); prefNotice(""); } catch (err) { prefNotice(err.message); }
  } });
  app.replaceChildren(pageHead("Preferences", "Saved to your account, so they follow you to any browser", reset),
    h("p", { class: "form-msg", id: "pref-msg", role: "status" }),
    h("div", { class: "pref-layout" }, nav, pane));
}

/* ---------- Admin: Users (§35) ---------- */
/* ---------- Admin: developer knowledge base (§36) ---------- */
const REVIEW_PILL = { ok: ["under", "Reviewed"], due: ["fair", "Review due"], overdue: ["over", "Review overdue"] };
const kbDate = (iso) => iso ? longDate(String(iso).slice(0, 10)) : "";
function reviewPill(a) {
  if (a.generated) return h("span", { class: "pill none", text: "Generated" });
  const [cls, text] = REVIEW_PILL[a.review] || REVIEW_PILL.ok;
  return h("span", { class: `pill ${cls}`, text: a.status === "draft" ? "Draft" : a.status === "retired" ? "Retired" : text });
}
function kbItem(a) {
  return h("li", { class: "kb-item", "data-text": `${a.title} ${a.summary} ${a.id}`.toLowerCase() },
    h("div", { class: "kb-item-head" }, h("a", { href: `#/admin/kb/${a.id}`, text: a.title }), reviewPill(a)),
    h("div", { class: "sub-text", text: a.summary }),
    a.generated ? null : h("div", { class: "kb-meta-line", text: `v${a.version} · ${a.owner} · reviewed ${kbDate(a.reviewed)} · next ${kbDate(a.next_review)}` }));
}
async function renderKb() {
  app.replaceChildren(pageHead("Developer knowledge base", null), adminTabs("kb"), h("p", { class: "loading", text: "Loading..." }));
  const d = await getJSON("/api/admin/kb");
  const filter = h("input", { type: "search", class: "pref-search kb-filter page-search", placeholder: "Filter articles", "aria-label": "Filter articles" });
  const reviewList = (items, cls) => h("ul", { class: "kb-review-list" }, items.map((a) => h("li", {},
    h("a", { href: `#/admin/kb/${a.id}`, text: a.title }), h("span", { class: `pill ${cls}`, text: kbDate(a.next_review) }))));
  const r = d.reviews, reg = d.register;
  const top = h("div", { class: "cards kb-top" },
    h("div", { class: "card" }, h("h2", { text: "Reviews" }),
      h("p", { class: "sub-text", text: `${r.total} articles${r.drafts ? `, ${r.drafts} in draft` : ""}. Each has a next review date; overdue and due within 30 days show here.` }),
      r.overdue.length ? [h("h3", { class: "related-head", text: `Overdue (${r.overdue.length})` }), reviewList(r.overdue, "over")] : null,
      r.due.length ? [h("h3", { class: "related-head", text: `Due soon (${r.due.length})` }), reviewList(r.due, "fair")] : null,
      !r.overdue.length && !r.due.length ? h("p", { class: "form-msg ok", text: "Every article is within its review date." }) : null),
    h("div", { class: "card" }, h("h2", { text: "Improvement register" }),
      h("p", { class: "kb-big" }, h("strong", { text: String(reg.open) }), " open", reg.p1 ? h("span", { class: "pill over", text: `${reg.p1} P1` }) : null),
      h("p", { class: "sub-text", text: `${reg.by_type.issue} known issues, ${reg.by_type.debt} technical debt, ${reg.by_type.idea} ideas, ${reg.by_type.risk} risks.` }),
      h("a", { href: "#/admin/kb/register", class: "btn", text: "Open the register" })),
    h("div", { class: "card" }, h("h2", { text: `Sift ${d.version}` }),
      h("p", { class: "sub-text", text: `Released ${kbDate(d.released)}.` }),
      d.latest_release ? h("p", {}, h("a", { href: `#/admin/kb/${d.latest_release.id}`, text: d.latest_release.title })) : null,
      h("p", {}, h("a", { href: "#/admin/kb/kb-guide", text: "How this knowledge base works" }))));
  const sections = d.categories.map((c) => {
    const items = d.articles.filter((a) => a.category === c.id).sort((a, b) => (a.generated ? 1 : 0) - (b.generated ? 1 : 0) || a.title.localeCompare(b.title));
    if (!items.length) return null;
    return h("section", { class: "card wide kb-section", "data-cat": c.id }, h("h2", { text: `${c.name} (${items.length})` }), h("ul", { class: "kb-list" }, items.map(kbItem)));
  }).filter(Boolean);
  const empty = h("p", { class: "sub-text", text: "No article matches.", hidden: true });
  filter.addEventListener("input", () => {
    const q = filter.value.trim().toLowerCase();
    let shown = 0;
    for (const sec of sections) {
      let n = 0;
      for (const li of sec.querySelectorAll(".kb-item")) { const ok = !q || li.dataset.text.includes(q); li.hidden = !ok; n += ok; }
      sec.hidden = !n; shown += n;
    }
    empty.hidden = shown > 0;
  });
  app.replaceChildren(pageHead("Developer knowledge base", `How Sift is designed and how it works: admins only`), adminTabs("kb"),
    top, h("div", { class: "kb-filter-row" }, filter), empty, h("div", { class: "cards" }, sections));
  window.scrollTo(0, 0);
}
async function renderKbArticle(id, query) {
  app.replaceChildren(pageHead("Developer knowledge base", null), adminTabs("kb"), h("p", { class: "loading", text: "Loading..." }));
  const a = await getJSON(`/api/admin/kb/${id}`);
  const body = h("div", { class: "kb-article" });
  body.innerHTML = a.html;  // rendered server-side from Markdown with every text escaped (src/devkb/markdown.py)
  const fact = (label, value) => value ? [h("dt", { text: label }), h("dd", {}, value)] : null;
  const meta = a.generated
    ? h("dl", { class: "facts" }, fact("Kind", "Generated from Sift each time it's opened, so it's always current"))
    : h("dl", { class: "facts" },
      fact("Version", `v${a.version}`), fact("Status", a.status[0].toUpperCase() + a.status.slice(1)),
      fact("Owner", a.owner), fact("Published", kbDate(a.published)), fact("Last reviewed", kbDate(a.reviewed)),
      fact("Next review", h("span", {}, kbDate(a.next_review), " ", reviewPill(a))),
      fact("Release", a.release), fact("Decision", a.decision_status), fact("Source", a.source),
      a.code.length ? fact("Code", h("ul", { class: "kb-paths" }, a.code.map((c) => h("li", {}, h("code", { text: c }))))) : null,
      a.tables.length ? fact("Tables", h("ul", { class: "kb-paths" }, a.tables.map((t) => h("li", {}, h("a", { href: `#/admin/kb/ref-data-dictionary?section=${t}` }, h("code", { text: t })))))) : null,
      fact("File", h("code", { text: a.path })));
  const links = (title, items) => items.length ? [h("h3", { class: "related-head", text: title }),
    h("ul", { class: "related-links" }, items.map((x) => h("li", {}, h("a", { href: `#/admin/kb/${x.id}`, text: x.title }))))] : null;
  const toc = a.toc.filter((t) => t.level <= 3);
  const aside = h("aside", { class: "kb-aside" },
    h("div", { class: "card" }, h("h2", { text: "About this article" }), meta, links("Related", a.related), links("Referenced by", a.backlinks)),
    toc.length > 2 ? h("nav", { class: "card kb-toc", "aria-label": "On this page" }, h("h2", { text: "On this page" }),
      h("ul", {}, toc.map((t) => h("li", { class: `toc-${t.level}` }, h("a", { href: `#/admin/kb/${a.id}?section=${t.id}`, text: t.text }))))) : null);
  const crumbs = h("p", { class: "kb-crumbs" }, h("a", { href: "#/admin/kb", text: "Developer knowledge base" }), " › ",
    a.category_name || (a.generated ? "Generated reference" : a.category));
  app.replaceChildren(pageHead(a.title, null), adminTabs("kb"), crumbs, h("p", { class: "kb-summary", text: a.summary }),
    h("div", { class: "kb-layout" }, h("article", { class: "card kb-body" }, body), aside));
  const section = new URLSearchParams(query || "").get("section");
  const target = section && document.getElementById(section);
  if (target) target.scrollIntoView({ block: "start" }); else window.scrollTo(0, 0);
}
async function renderKbRegister(query) {
  app.replaceChildren(pageHead("Improvement register", null), adminTabs("kb"), h("p", { class: "loading", text: "Loading..." }));
  const d = await getJSON("/api/admin/kb/register");
  const asked = new URLSearchParams(query || "").get("q") || "";
  const state = { q: asked, type: "", priority: "", status: asked ? "" : "live" };
  const pick = (key, label, options) => h("select", { "aria-label": label, onchange: (e) => { state[key] = e.target.value; paint(); } },
    options.map(([v, t]) => h("option", { value: v, text: t, selected: state[key] === v })));
  const tbody = h("tbody", {});
  const count = h("span", { class: "sub-text" });
  const closed = new Set(["done", "wont", "by-design"]);
  const pillFor = { P1: "over", P2: "fair", P3: "none", P4: "none" };
  function paint() {
    const q = state.q.toLowerCase();
    const rows = d.items.filter((i) => (!state.type || i.type === state.type) && (!state.priority || i.priority === state.priority)
      && (state.status === "" || (state.status === "live" ? !closed.has(i.status) : i.status === state.status))
      && (!q || `${i.id} ${i.title} ${i.impact} ${i.notes}`.toLowerCase().includes(q)))
      .sort((a, b) => a.priority.localeCompare(b.priority) || a.id.localeCompare(b.id));
    count.textContent = `${rows.length} of ${d.items.length}`;
    tbody.replaceChildren(...rows.map((i) => h("tr", {},
      h("td", { class: "strong kb-reg-id", text: i.id }),
      h("td", { class: "kb-reg-title" }, h("div", { class: "strong", text: i.title }), h("div", { class: "sub-text", text: i.impact }),
        i.notes ? h("details", {}, h("summary", { text: "Notes" }), h("p", { text: i.notes })) : null,
        i.article_titles.length ? h("div", { class: "kb-meta-line" }, i.article_titles.map((x, k) => [k ? ", " : "", h("a", { href: `#/admin/kb/${x.id}`, text: x.title })])) : null),
      h("td", { class: "opt", text: d.types[i.type] }),
      h("td", {}, h("span", { class: `pill ${pillFor[i.priority]}`, text: i.priority })),
      h("td", { text: d.statuses[i.status] }),
      h("td", { class: "opt", text: kbDate(i.updated) }))));
  }
  const search = h("input", { type: "search", class: "pref-search page-search", placeholder: "Search the register", "aria-label": "Search the register", value: state.q,
    oninput: (e) => { state.q = e.target.value; paint(); } });
  paint();
  app.replaceChildren(pageHead("Improvement register", "Known issues, technical debt, ideas and risks"), adminTabs("kb"),
    h("p", { class: "kb-crumbs" }, h("a", { href: "#/admin/kb", text: "Developer knowledge base" }), " › Improvement register"),
    h("div", { class: "card wide" },
      h("div", { class: "kb-reg-filters" }, search,
        pick("type", "Type", [["", "All types"], ...Object.entries(d.types)]),
        pick("priority", "Priority", [["", "All priorities"], ...Object.entries(d.priorities)]),
        pick("status", "Status", [["live", "Not closed"], ["", "All statuses"], ...Object.entries(d.statuses)]), count),
      h("p", { class: "sub-text", text: "Edited in docs/kb/improvements.json (in git). Closed means done, won't do or by design." }),
      h("div", { class: "table-wrap" }, h("table", { class: "grid kb-register" },
        h("thead", {}, h("tr", {}, ["ID", "Item", "Type", "Priority", "Status", "Updated"].map((x, i) => h("th", { scope: "col", class: i === 2 || i === 5 ? "opt" : null, text: x })))),
        tbody))));
  window.scrollTo(0, 0);
}

const when = (iso) => new Date(iso).toLocaleString("en-AU", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
/* A session's length in words: "Under a minute", "25 min", "1 hr 40 min". */
function minutesText(m) {
  m = Math.max(0, Math.round(Number(m) || 0));
  if (m < 1) return "Under a minute";
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} hr${m % 60 ? ` ${m % 60} min` : ""}`;
}
async function renderAdminUsers() {
  app.replaceChildren(pageHead("Model and rules", "Users"), adminTabs("users"), h("p", { class: "loading", text: "Loading..." }));
  const d = await getJSON("/api/admin/users");
  const msg = h("p", { class: "form-msg", role: "status" });
  const act = async (fn) => { try { await fn(); renderAdminUsers(); } catch (err) { showMessage(msg, err.message, false); } };
  const rows = d.users.map((u) => {
    const self = u.user_id === d.me, active = u.status === "active";
    return h("tr", {},
      h("td", {}, h("div", { class: "strong", text: u.display_name }), h("div", { class: "sub-text", text: u.email }),
        h("div", { class: "sub-text phone-only", text: `${u.role === "admin" ? "Admin" : "Member"}, ${active ? "active" : "disabled"}` }),
        h("div", { class: "sub-text phone-only", text: `Last login ${u.last_login_at ? when(u.last_login_at) : "never"}` })),
      h("td", { class: "opt", text: u.role === "admin" ? "Admin" : "Member" }),
      h("td", { class: "opt" }, h("span", { class: `pill ${active ? "under" : "none"}`, text: active ? "Active" : "Disabled" })),
      h("td", { class: "opt", text: u.last_login_at ? when(u.last_login_at) : "Never" }),
      h("td", { class: "opt", text: u.last_seen_at ? when(u.last_seen_at) : "Never" }),
      h("td", { class: "num opt", text: fmt(u.sessions || 0, 0) }),
      h("td", { class: "num opt", text: u.sessions ? minutesText(u.avg_minutes) : "" }),
      h("td", { class: "num opt", text: `${u.portfolios} / ${u.watchlists}` }),
      h("td", { class: "user-actions" },
        u.role === "member" && active ? h("button", { type: "button", class: "btn small", text: "Impersonate",
          onclick: () => act(async () => { await send("POST", "/api/admin/impersonate", { user_id: u.user_id }); location.hash = "#/"; location.reload(); }) }) : null,
        self ? null : h("button", { type: "button", class: "btn small", text: u.role === "admin" ? "Make member" : "Make admin",
          onclick: () => act(() => send("PATCH", `/api/admin/users/${u.user_id}`, { role: u.role === "admin" ? "member" : "admin" })) }),
        self ? h("span", { class: "sub-text", text: "You" }) : h("button", { type: "button", class: `btn small${active ? " danger" : ""}`, text: active ? "Disable" : "Enable",
          onclick: () => act(() => send("PATCH", `/api/admin/users/${u.user_id}`, { status: active ? "disabled" : "active" })) })));
  });
  const email = h("input", { type: "email", required: true, placeholder: "name@example.com", autocomplete: "off" });
  const name = h("input", { maxlength: 80, placeholder: "Sam Citizen" });
  const role = h("select", {}, h("option", { value: "member", text: "Member" }), h("option", { value: "admin", text: "Admin" }));
  const add = h("form", { class: "form-grid", onsubmit: (e) => { e.preventDefault(); act(() => send("POST", "/api/admin/users", { email: email.value, display_name: name.value, role: role.value })); } },
    h("label", { class: "field" }, h("span", { class: "field-label", text: "Email" }), email),
    h("label", { class: "field" }, h("span", { class: "field-label", text: "Display name" }), name),
    h("label", { class: "field" }, h("span", { class: "field-label", text: "Role" }), role),
    h("div", { class: "form-actions" }, h("button", { type: "submit", class: "btn primary", text: "Add account" })));
  const log = d.log.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, ["Admin", "Impersonated", "Started", "Ended"].map((x) => h("th", { scope: "col", text: x })))),
    h("tbody", {}, d.log.map((x) => h("tr", {}, h("td", { text: x.admin }), h("td", { text: x.target }),
      h("td", { text: when(x.started_at) }),
      h("td", { text: x.ended_at ? `${when(x.ended_at)} (${x.ended_how})` : "Still on" }))))))
    : h("p", { class: "sub-text", text: "Nobody has been impersonated yet." });
  const sessions = d.sessions.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, ["Person", "Started", "Length", "Browser"].map((x, i) => h("th", { scope: "col", class: [null, null, "num opt", "opt"][i], text: x })))),
    h("tbody", {}, d.sessions.map((x) => {
      const length = x.active ? `${minutesText(x.minutes)}, still on` : minutesText(x.minutes);
      return h("tr", {}, h("td", { text: x.display_name }),
      h("td", {}, when(x.started_at), h("div", { class: "sub-text phone-only", text: length }), x.client ? h("div", { class: "sub-text phone-only", text: x.client }) : null),
      h("td", { class: "num opt", text: length }),
      h("td", { class: "opt", text: x.client || "" }));
    }))))
    : h("p", { class: "sub-text", text: "No sessions yet." });
  app.replaceChildren(pageHead("Model and rules", "Users"), adminTabs("users"),
    h("div", { class: "cards" },
      h("div", { class: "card wide" }, h("h2", { text: "Accounts" }), msg,
        h("div", { class: "table-wrap" }, h("table", { class: "grid users-table" },
          h("thead", {}, h("tr", {}, ["Person", "Role", "Status", "Last login", "Last seen", `Sessions (${d.activity_days} days)`, "Average session", "Portfolios / watchlists", ""].map((x, i) =>
            h("th", { scope: "col", class: [null, "opt", "opt", "opt", "opt", "num opt", "num opt", "num opt", null][i], text: x })))),
          h("tbody", {}, rows)))),
      h("div", { class: "card wide" }, h("h2", { text: "Add an account" }),
        h("p", { class: "sub-text", text: "For testers. Until sign-in arrives, an account can be used only through Impersonate." }), add),
      h("div", { class: "card wide" }, h("h2", { text: "Impersonation log" }),
        h("p", { class: "sub-text", text: `Every session: who, as whom, and how it ended. A session ends by itself after ${d.expires_hours} hours.` }), log),
      h("div", { class: "card wide" }, h("h2", { text: "Sessions" }),
        h("p", { class: "sub-text", text: `When each person used Sift, newest first. A session starts with their first request and ends after ${d.idle_minutes} minutes without one; its length runs from the first request to the last. Until sign-in arrives a session is a spell of use, not a log-on. Kept for a year.` }), sessions)));
  window.scrollTo(0, 0);
}

/* ---------- routing ---------- */
const ROUTES = [
  [/^#\/company\/([A-Za-z0-9.]+)$/, "company", (m) => reactPage("CompanyPage", { code: m[1].toUpperCase() })],
  [/^#\/screener(?:\?(.*))?$/, "screener", (m) => reactPage("ScreenerPage", { query: m[1] })],
  [/^#\/etfs(?:\?(.*))?$/, "etfs", (m) => reactPage("FundsPage", { kind: "ETF", query: m[1] })],
  [/^#\/etf\/([A-Za-z0-9.]+)(?:\?(.*))?$/, "etf", (m) => reactPage("FundPage", { kind: "ETF", code: m[1].toUpperCase(), query: m[2] }, m[2] !== undefined)],
  [/^#\/lics(?:\?(.*))?$/, "lics", (m) => reactPage("FundsPage", { kind: "LIC", query: m[1] })],
  [/^#\/lic\/([A-Za-z0-9.]+)(?:\?(.*))?$/, "lic", (m) => reactPage("FundPage", { kind: "LIC", code: m[1].toUpperCase(), query: m[2] }, m[2] !== undefined)],
  [/^#\/track-record(?:\?(.*))?$/, "track-record", (m) => reactPage("TrackRecordPage", { version: new URLSearchParams(m[1] || "").get("version") || "" })],
  [/^#\/coattail(?:\?(.*))?$/, "coattail", (m) => renderCoattail(m[1])],
  [/^#\/coattail\/([a-z0-9-]+)$/, "coattail", (m) => renderCoattailHolder(m[1])],
  [/^#\/help(?:\?(.*))?$/, "help", (m) => reactPage("HelpPage", { query: m[1] })],
  [/^#\/admin$/, "admin", () => renderAdmin()],
  [/^#\/admin\/scenarios$/, "admin", () => renderScenarios()],
  [/^#\/admin\/search$/, "admin", () => renderAdminSearch()],
  [/^#\/admin\/users$/, "admin", () => renderAdminUsers()],
  [/^#\/admin\/kb$/, "kb", () => renderKb()],
  [/^#\/admin\/kb\/register(?:\?(.*))?$/, "kb", (m) => renderKbRegister(m[1])],
  [/^#\/admin\/kb\/([a-z0-9-]+)(?:\?(.*))?$/, "kb", (m) => renderKbArticle(m[1], m[2])],
  [/^#\/profile$/, "profile", () => renderProfile()],
  [/^#\/preferences(?:\/([a-z]+))?$/, "preferences", (m) => renderPreferences(m[1])],
  [/^#\/admin\/scenario\/new$/, "admin", () => renderScenario(null)],
  [/^#\/admin\/scenario\/([0-9a-f-]{36})$/, "admin", (m) => renderScenario(m[1])],
  [/^#\/help\/([a-z0-9-]+)$/, "help", (m) => reactPage("HelpPage", { focusId: m[1] })],
  [/^#\/watchlists(?:\?(.*))?$/, "watchlists", (m) => renderWatchlists(m[1])],
  [/^#\/watchlist\/([0-9a-f-]{36})$/, "watchlists", (m) => renderWatchlist(m[1])],
  [/^#\/portfolios\/import$/, "portfolios", () => renderImport()],
  [/^#\/portfolios(?:\?(.*))?$/, "portfolios", (m) => renderPortfolios(m[1])],
  [/^#\/portfolio\/([0-9a-f-]{36})$/, "portfolios", (m) => renderPortfolio(m[1])],
  [/^#\/search(?:\?(.*))?$/, "search", (m) => renderSearch(m[1] || "")],
  [/^(#\/?)?$/, "dashboard", () => renderDashboard()],
];
let previousPage = null;
let currentHash = null;
function route() {
  if (siftUpdated) { location.reload(); return; }
  hideTip();
  closeMenus();
  slots.length = 0;
  const hash = location.hash;
  let found = ROUTES.find(([re]) => re.test(hash));
  if (!found) { location.replace("#/"); return; }
  const [re, page, render] = found;
  const detail = (h_) => h_ && (h_.startsWith("#/company/") || h_.startsWith("#/etf/") || h_.startsWith("#/lic/"));
  if (["company", "etf", "lic"].includes(page) && currentHash && !detail(currentHash)) previousPage = currentHash;
  currentHash = hash;
  markCurrent(page);
  Object.assign(findState, { q: "", hits: [], i: -1 });
  setSearchPage(page);
  render(hash.match(re)).catch((err) => app.replaceChildren(h("p", { class: "error", text: `Could not load: ${err.message}` })))
    .finally(() => window.SiftUI && window.SiftUI.sweep());
}
window.addEventListener("hashchange", route);
initNav();
/* First load: open on the start page chosen in Preferences, unless a page was asked for. */
Promise.all([knowledgeReady, meReady]).then(() => {
  const start = me.settings.start_page;
  if ((!location.hash || location.hash === "#" || location.hash === "#/") && start && start !== "dashboard") location.replace(`#/${start}`);
  else route();
});
