// Field explanations for elements the charts draw themselves (SVG labels),
// as bindHelp() and svgLabelHelp() in web/app.js.
import { h, s } from "./dom";
import { hideTip, placeTipBelow, showTip } from "./tooltip";

export const helpNodes = (label: string, text: string) => (): Node[] =>
  [h("div", { class: "t-title", text: label }), h("div", { text })];

export function bindHelp(el: Element, nodes: () => Node[]): void {
  el.addEventListener("pointermove", (e) => { if ((e as PointerEvent).pointerType !== "touch") showTip(e as PointerEvent, nodes()); });
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => placeTipBelow(el, nodes()));
  el.addEventListener("blur", hideTip);
}

/* A label drawn inside an SVG chart, with its "i" for touch screens as an
   SVG circle at (ix, iy). */
export function svgLabelHelp(textEl: SVGElement, label: string, text: string | null | undefined, ix: number, iy: number): SVGElement {
  if (!text) return textEl;
  const nodes = helpNodes(label, text);
  textEl.classList.add("has-help");
  const g = s("g", { tabindex: 0, "aria-label": `${label}: ${text}` }, textEl);
  bindHelp(g, nodes);
  const info = s("g", { class: "info-svg", role: "button", "aria-label": `What is ${label}?` },
    s("circle", { cx: ix, cy: iy, r: 7.5 }), s("text", { x: ix, y: iy + 3.5, "text-anchor": "middle", text: "i" }));
  info.addEventListener("click", (e) => { e.stopPropagation(); placeTipBelow(info, nodes()); });
  g.append(info);
  return g;
}
