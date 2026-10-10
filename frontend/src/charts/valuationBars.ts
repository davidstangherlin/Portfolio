// Horizontal bars: share price against the two value estimates.
import { s } from "../lib/dom";
import { money } from "../lib/format";
import { svgLabelHelp } from "../lib/helpDom";

export interface ValuationItem { label: string; value: number | null; emphasis?: boolean; help?: string | null }

export function valuationBars(items: ValuationItem[], width = 640): SVGElement {
  const shown = items.filter((it): it is ValuationItem & { value: number } => it.value !== null && it.value > 0);
  const W = width, rowH = 40, labelW = 130, m = { t: 6, r: 70 };
  const H = m.t * 2 + rowH * shown.length;
  const max = Math.max(...shown.map((it) => it.value));
  const X = (v: number) => labelW + (v / max) * (W - labelW - m.r);
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
