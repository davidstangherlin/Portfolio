// Column chart, one baseline at zero, 4px rounded data-ends.
import { h, s } from "../lib/dom";
import { host } from "../lib/host";
import { hideTip, showTip, tipRow } from "../lib/tooltip";
import { legend } from "./legend";
import { niceTicks } from "./ticks";

export function barPath(x: number, w: number, yBase: number, yVal: number, r = 4): string {
  const hgt = Math.abs(yBase - yVal);
  r = Math.min(r, w / 2, hgt);
  if (yVal <= yBase) { // positive: round the top
    return `M${x},${yBase}V${yVal + r}Q${x},${yVal} ${x + r},${yVal}H${x + w - r}Q${x + w},${yVal} ${x + w},${yVal + r}V${yBase}Z`;
  }
  return `M${x},${yBase}V${yVal - r}Q${x},${yVal} ${x + r},${yVal}H${x + w - r}Q${x + w},${yVal} ${x + w},${yVal - r}V${yBase}Z`;
}

let hatchCount = 0;
export interface ColumnSeries { name: string; color: string; values: (number | null | undefined)[] }

export function columnChart({ categories, series, yFmt, height = 220, label, width = 640 }:
  { categories: string[]; series: ColumnSeries[]; yFmt: (v: number) => string; height?: number; label: string; width?: number }): HTMLElement {
  const W = width, H = height, m = { l: 56, r: 10, t: 10, b: 26 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const values = series.flatMap((sr) => sr.values.filter((v): v is number => v !== null && v !== undefined));
  const { lo, hi, ticks } = niceTicks(Math.min(0, ...values), Math.max(0, ...values));
  const Y = (v: number) => m.t + ph - ((v - lo) / (hi - lo)) * ph;
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
    if (!host().settings().chart_patterns || si === 0) return `var(${sr.color})`;
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
      const over = (e: Event) => { bar.setAttribute("fill-opacity", "0.75"); showTip(e as PointerEvent, [h("div", { class: "t-head", text: cat }), tipRow(yFmt(v), sr.name, sr.color)]); };
      hitArea.addEventListener("pointermove", over);
      hitArea.addEventListener("pointerleave", () => { bar.removeAttribute("fill-opacity"); hideTip(); });
      svg.append(bar, hitArea);
    });
  });
  return h("div", {}, legend(series, true), svg);
}
