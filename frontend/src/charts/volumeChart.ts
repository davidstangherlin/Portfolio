// Daily volume as thin bars on the same time axis and margins as lineChart
// (so it lines up under the price chart), with a 3-month average line.
import { h, s } from "../lib/dom";
import { fmt, longDate, sum, toDate } from "../lib/format";
import { hideTip, showTip, tipRow } from "../lib/tooltip";
import { legend } from "./legend";
import { CHART_RIGHT_AHEAD, type Point } from "./lineChart";
import { niceTicks } from "./ticks";

const VOLUME_AVG_DAYS = 63;  // about three months of trading days

export function volumeChart({ points, height = 120, width = 640, label, until = null }:
  { points: Point[]; height?: number; width?: number; label: string; until?: number | null }): HTMLElement {
  // `until`: the price chart's year ahead, so the bars stay lined up under it
  const W = width, H = height, m = { l: 52, r: until ? CHART_RIGHT_AHEAD : 14, t: 8, b: 20 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const xs = points.map((p) => toDate(p[0]).getTime());
  const x0 = xs[0], x1 = until || (xs[xs.length - 1] === x0 ? x0 + 1 : xs[xs.length - 1]);
  const avg = points.map((_, i) => {
    const from = Math.max(0, i - VOLUME_AVG_DAYS + 1), win = points.slice(from, i + 1);
    return win.length >= 20 ? sum(win.map((q) => q[1])) / win.length : null;
  });
  const { hi, ticks } = niceTicks(0, Math.max(1, ...points.map((p) => p[1])));
  const X = (t: number) => m.l + ((t - x0) / (x1 - x0)) * pw;
  const Y = (v: number) => m.t + ph - (v / hi) * ph;
  const bw = Math.max(1, Math.min(6, pw / points.length - 1));
  const shares = (v: number) => new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart volume-chart", role: "img", "aria-label": label });
  for (const t of ticks.filter((t) => t > 0)) {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: "grid-line" }));
    svg.append(s("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end", text: shares(t) }));
  }
  svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), class: "base-line" }));
  points.forEach((p, i) => svg.append(s("rect", { x: X(xs[i]) - bw / 2, y: Y(p[1]), width: bw, height: Math.max(0.5, Y(0) - Y(p[1])),
    class: avg[i] && p[1] > 2 * (avg[i] as number) ? "vol-bar heavy" : "vol-bar" })));
  const line = avg.map((a, i) => (a === null ? null : `${X(xs[i]).toFixed(1)},${Y(a).toFixed(1)}`)).filter(Boolean);
  if (line.length > 1) svg.append(s("path", { d: "M" + line.join("L"), fill: "none", stroke: "var(--s2)", "stroke-width": 2, class: "series series-1" }));
  const cross = s("line", { y1: m.t, y2: m.t + ph, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
  svg.append(cross);
  const hit = s("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" });
  hit.addEventListener("pointermove", (ev) => {
    const e = ev as PointerEvent;
    const box = svg.getBoundingClientRect();
    const t = x0 + ((((e.clientX - box.left) / box.width) * W - m.l) / pw) * (x1 - x0);
    let i = 0, best = Infinity;
    xs.forEach((x, k) => { const dd = Math.abs(x - t); if (dd < best) { best = dd; i = k; } });
    cross.setAttribute("x1", String(X(xs[i]))); cross.setAttribute("x2", String(X(xs[i]))); cross.setAttribute("visibility", "visible");
    const a = avg[i];
    showTip(e, [h("div", { class: "t-head", text: longDate(points[i][0]) }), tipRow(`${fmt(points[i][1], 0)} shares`, "Volume", "--s1"),
      a ? tipRow(`${shares(a)} (${fmt(points[i][1] / a, 1)}x)`, "3-month average", "--s2") : null].filter((x): x is HTMLElement => x !== null));
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(hit);
  return h("div", {}, legend([{ name: "Volume (shares traded)", color: "--s1" }, { name: "3-month average", color: "--s2" }], false), svg);
}
