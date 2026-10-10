// Line chart with a crosshair tooltip (lineChart() in web/app.js).
// series: [{name, color, points: [[iso, value]]}]. `markers` are ex-dividend
// dates on the first line. `ahead` ({price, volatility}, a fraction a year)
// adds the likely range for the next 12 months, two years in three, after
// the last point (docs/kb/features/statistics.md).
import { h, s } from "../lib/dom";
import { dayMonth, longDate, money, monthYear, plural, toDate } from "../lib/format";
import { hideTip, placeTipBelow, showTip, tipRow } from "../lib/tooltip";
import { legend, type LegendExtra } from "./legend";
import { niceTicks } from "./ticks";

export type Point = [string, number];
export interface Series { name: string; color: string; points: Point[] }
export interface DividendMarker { ex_date: string; date: string; amount: number; per?: string | null; abnormal?: boolean; kind?: string | null }
export interface Ahead { price: number; volatility: number }

export const YEAR_MS = 365 * 86400000;
export const CHART_RIGHT_AHEAD = 58;  // room for the range's end labels; volumeChart matches it

export function aheadRange(ahead: Ahead, t0: number) {  // weekly points, so the range's curve near today stays smooth
  return Array.from({ length: 53 }, (_, k) => {
    const spread = ahead.volatility * Math.sqrt(k / 52);
    return { t: t0 + (k * YEAR_MS) / 52, months: Math.round((k * 12) / 52), lo: ahead.price * Math.exp(-spread), hi: ahead.price * Math.exp(spread) };
  });
}
export const pastYears = (y: number): string => (y >= 2.5 ? "3 years" : y >= 1.5 ? "2 years" : "year");

/* Ex-dividend dates on the price chart: each lands on the first trading day
   on or after it (ex-dates can fall on a non-trading day). */
export function dividendMarkers(prices: Point[], dividends: Omit<DividendMarker, "date">[]): DividendMarker[] {
  return dividends.map((dv) => {
    const at = prices.find((p) => p[0] >= dv.ex_date) || prices[prices.length - 1];
    return { ...dv, date: at[0] };
  }).filter((dv) => dv.ex_date >= prices[0][0]);
}
export const dividendText = (dv: { amount: number; per?: string | null; abnormal?: boolean }): string =>
  `${money(dv.amount, 3)} per ${dv.per || "share"}${dv.abnormal ? ", one-off (excluded from dividend figures)" : ""}`;
export const markerKind = (mk: { kind?: string | null }): string => mk.kind || "Dividend";

export interface LineChartOptions {
  series: Series[]; yFmt: (v: number) => string; height?: number; zeroLine?: boolean; label: string; width?: number;
  markers?: DividendMarker[]; ahead?: Ahead | null;
}

export function lineChart({ series, yFmt, height = 220, zeroLine = false, label, width = 640, markers = [], ahead = null }: LineChartOptions): HTMLElement {
  const W = width, H = height, m = { l: 52, r: ahead ? CHART_RIGHT_AHEAD : 14, t: 10, b: 24 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const base = series[0].points;
  const xs = base.map((p) => toDate(p[0]).getTime());
  const lastT = xs[xs.length - 1];
  const fan = ahead ? aheadRange(ahead, lastT) : null;
  const x0 = xs[0], x1 = fan ? lastT + YEAR_MS : lastT === x0 ? x0 + 1 : lastT;
  const values = series.flatMap((sr) => sr.points.map((p) => p[1]));
  if (fan) values.push(fan[52].lo, fan[52].hi);
  if (zeroLine) values.push(0);
  const { lo, hi, ticks } = niceTicks(Math.min(...values), Math.max(...values));
  const X = (t: number) => m.l + ((t - x0) / (x1 - x0)) * pw;
  const Y = (v: number) => m.t + ph - ((v - lo) / (hi - lo)) * ph;

  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", role: "img", "aria-label": label });
  for (const t of ticks) {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 && zeroLine ? "zero-line" : "grid-line" }));
    svg.append(s("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end", text: yFmt(t) }));
  }
  if (fan && ahead) {
    // Past and year ahead: start, middle, Today, middle, end (start, Today, end when narrow).
    const at = W < 520 ? [x0, lastT, x1] : [x0, (x0 + lastT) / 2, lastT, (lastT + x1) / 2, x1];
    at.forEach((t, k) => svg.append(s("text", { x: X(t), y: H - 6, "text-anchor": k === 0 ? "start" : k === at.length - 1 ? "end" : "middle",
      class: t === lastT ? "strong" : null, text: t === lastT ? "Today" : monthYear(new Date(t).toISOString().slice(0, 10)) })));
    const edge = (side: "lo" | "hi") => fan.map((f) => `${X(f.t).toFixed(1)},${Y(f[side]).toFixed(1)}`);
    svg.append(s("polygon", { points: [...edge("hi"), ...edge("lo").reverse()].join(" "), class: "ahead-band" }));
    svg.append(s("polyline", { points: edge("hi").join(" "), class: "ahead-edge" }));
    svg.append(s("polyline", { points: edge("lo").join(" "), class: "ahead-edge" }));
    svg.append(s("line", { x1: X(lastT), x2: X(x1), y1: Y(ahead.price), y2: Y(ahead.price), class: "ahead-mid" }));
    svg.append(s("line", { x1: X(lastT), x2: X(lastT), y1: m.t, y2: m.t + ph, class: "ahead-today" }));
    ([[fan[52].hi, true], [ahead.price, false], [fan[52].lo, true]] as [number, boolean][]).forEach(([v, strong]) =>
      svg.append(s("text", { x: W - m.r + 6, y: Y(v) + 4, class: strong ? "strong" : null, text: yFmt(v) })));
  } else {
    const nLabels = Math.min(5, base.length);
    for (let k = 0; k < nLabels; k++) {
      const idx = Math.round((k * (base.length - 1)) / Math.max(1, nLabels - 1));
      svg.append(s("text", { x: X(xs[idx]), y: H - 6, "text-anchor": k === 0 ? "start" : k === nLabels - 1 ? "end" : "middle",
        text: base.length > 60 ? monthYear(base[idx][0]) : dayMonth(base[idx][0]) }));
    }
  }
  const lookups = series.map((sr) => new Map(sr.points.map((p) => [p[0], p[1]])));
  series.forEach((sr, k) => {
    if (!sr.points.length) return;
    const d = sr.points.map((p, i) => `${i ? "L" : "M"}${X(toDate(p[0]).getTime()).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    svg.append(s("path", { d, fill: "none", stroke: `var(${sr.color})`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
      class: `series series-${k}` }));  // series-1 and on are dashed with the chart_patterns preference
    const last = sr.points[sr.points.length - 1];
    svg.append(s("circle", { cx: X(toDate(last[0]).getTime()), cy: Y(last[1]), r: 4, fill: `var(${sr.color})`, stroke: "var(--surface)", "stroke-width": 2 }));
  });
  const cross = s("line", { y1: m.t, y2: m.t + ph, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
  svg.append(cross);
  const hit = s("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" });
  hit.addEventListener("pointermove", (ev) => {
    const e = ev as PointerEvent;
    const box = svg.getBoundingClientRect();
    const t = x0 + ((((e.clientX - box.left) / box.width) * W - m.l) / pw) * (x1 - x0);
    if (fan && t > lastT) {
      const k = Math.max(1, Math.min(52, Math.round(((t - lastT) / YEAR_MS) * 52))), f = fan[k];
      cross.setAttribute("x1", String(X(f.t))); cross.setAttribute("x2", String(X(f.t))); cross.setAttribute("visibility", "visible");
      showTip(e, [h("div", { class: "t-head", text: `${longDate(new Date(f.t).toISOString().slice(0, 10))}, ${k < 9 ? plural(k, "week") : plural(f.months, "month")} ahead` }),
        h("div", { text: `Likely ${yFmt(f.lo)} to ${yFmt(f.hi)}` }), h("div", { class: "t-note", text: "Two years in three" })]);
      return;
    }
    let i = 0, best = Infinity;
    xs.forEach((x, k) => { const dd = Math.abs(x - t); if (dd < best) { best = dd; i = k; } });
    const iso = base[i][0];
    cross.setAttribute("x1", String(X(xs[i]))); cross.setAttribute("x2", String(X(xs[i]))); cross.setAttribute("visibility", "visible");
    showTip(e, [h("div", { class: "t-head", text: longDate(iso) }),
      ...series.map((sr, k) => lookups[k].has(iso) ? tipRow(yFmt(lookups[k].get(iso) as number), sr.name, sr.color) : null).filter((x): x is HTMLElement => x !== null),
      ...markers.filter((mk) => mk.date === iso).map((mk) => h("div", { class: "t-row" }, h("span", { class: "dkey sm", text: "D" }), h("span", { text: `${markerKind(mk)} ${dividendText(mk)}` })))]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(hit);
  // Dividend markers sit on the first series' line, above the hover layer so they can be hovered themselves.
  for (const mk of markers) {
    if (!lookups[0].has(mk.date)) continue;
    const cx = X(toDate(mk.date).getTime()), cy = Y(lookups[0].get(mk.date) as number);
    const g = s("g", { class: `div-marker${mk.abnormal ? " abnormal" : ""}`, tabindex: 0,
      "aria-label": `${markerKind(mk)}, ex-date ${longDate(mk.ex_date)}: ${dividendText(mk)}` },
      s("circle", { cx, cy, r: 13, fill: "transparent" }),
      s("circle", { class: "dot", cx, cy, r: 8 }),
      s("text", { x: cx, y: cy + 3.5, "text-anchor": "middle", text: "D" }));
    const nodes = () => [h("div", { class: "t-title", text: markerKind(mk) }), h("div", { text: `Ex-${markerKind(mk).toLowerCase()} date ${longDate(mk.ex_date)}` }), h("div", { text: dividendText(mk) })];
    g.addEventListener("pointermove", (e) => showTip(e as PointerEvent, nodes()));
    g.addEventListener("pointerleave", hideTip);
    g.addEventListener("focus", () => placeTipBelow(g, nodes()));
    g.addEventListener("blur", hideTip);
    svg.append(g);
  }
  const extras: LegendExtra[] = markers.length ? [{ symbol: "D", name: `${markerKind(markers[0])} (ex-${markerKind(markers[0]).toLowerCase()} date)` }] : [];
  if (fan) extras.push({ band: true, name: "Likely range for the year ahead (two years in three)" });
  if (markers.some((mk) => mk.abnormal)) extras.push({ symbol: "D", name: "One-off, excluded from dividend figures", outline: true });
  return h("div", {}, legend(series, false, extras), svg);
}
