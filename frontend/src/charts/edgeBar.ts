// Where an action's true edge most likely sits (widened for the number of
// tests, src/analytics/rules.py adjust()), against the average screened
// share at zero. Track record, "Is Sift accurate?".
import { h, s } from "../lib/dom";
import { fmt } from "../lib/format";
import { hideTip, showTip } from "../lib/tooltip";
import { niceTicks, type Ticks } from "./ticks";

export interface EdgeInput { action: string; signals: number; avg_excess: number; test: { low: number | null; high: number | null } }

export const ptsText = (v: number): string => `${v > 0 ? "+" : v < 0 ? "-" : ""}${fmt(Math.abs(v), 1)} pts`;

/* One scale for every action's bar in a period, always including zero. */
export function edgeDomain(actions: EdgeInput[]): Ticks | null {
  const tested = actions.filter((a) => a.test && a.test.low !== null);
  if (!tested.length) return null;
  const lo = Math.min(0, ...tested.map((a) => a.test.low as number)), hi = Math.max(0, ...tested.map((a) => a.test.high as number));
  return niceTicks(lo, hi, 5);
}

export function edgeBar(a: EdgeInput, domain: Ticks, width: number): SVGElement {
  const low = a.test.low as number, high = a.test.high as number;
  const W = Math.max(260, width), H = 50, m = { l: 10, r: 10 };
  const X = (v: number) => m.l + ((v - domain.lo) / (domain.hi - domain.lo)) * (W - m.l - m.r);
  const y = 18;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart edge-bar", role: "img",
    "aria-label": `${a.action}: likely true edge ${ptsText(low)} to ${ptsText(high)} against the average share` });
  for (const v of domain.ticks) {
    svg.append(s("line", { x1: X(v), x2: X(v), y1: 4, y2: 32, class: v === 0 ? "edge-zero" : "grid-line" }));
    svg.append(s("text", { x: X(v), y: H - 4, "text-anchor": "middle", class: v === 0 ? "strong" : null, text: v === 0 ? "Average" : `${v > 0 ? "+" : ""}${fmt(v, 0)} pts` }));
  }
  svg.append(s("rect", { x: X(low), y: y - 5, width: Math.max(2, X(high) - X(low)), height: 10, rx: 5, class: "edge-range" }));
  svg.append(s("circle", { cx: X(a.avg_excess), cy: y, r: 6, class: "edge-point" }));
  const hit = s("rect", { x: X(low) - 8, y: 0, width: X(high) - X(low) + 16, height: 36, fill: "transparent" });
  const tipNodes = () => [h("div", { class: "t-head", text: `${a.action}, ${fmt(a.signals, 0)} calls` }),
    h("div", { text: `Average ${ptsText(a.avg_excess)}` }), h("div", { text: `Likely true edge ${ptsText(low)} to ${ptsText(high)}` })];
  hit.addEventListener("pointermove", (e) => showTip(e as PointerEvent, tipNodes()));
  hit.addEventListener("pointerleave", hideTip);
  svg.append(hit);
  return svg;
}
