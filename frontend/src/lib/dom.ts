// Small DOM builders for the charts, which draw SVG imperatively inside a
// React component (ChartSlot), as web/app.js's h() and s() did. Text always
// goes in through textContent.
const SVG_NS = "http://www.w3.org/2000/svg";
export type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>;
export type Child = Node | string | number | null | undefined | false | Child[];

function setAttrs(el: Element, attrs?: Attrs): void {
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") el.textContent = String(v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}
function add(el: Element, children: Child[]): void {
  for (const c of (children as unknown[]).flat(Infinity as 1) as Child[]) {
    if (c === null || c === undefined || c === false) continue;
    el.append(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : (c as Node));
  }
}
export function h(tag: string, attrs?: Attrs, ...children: Child[]): HTMLElement {
  const el = document.createElement(tag); setAttrs(el, attrs); add(el, children); return el;
}
export function s(tag: string, attrs?: Attrs, ...children: Child[]): SVGElement {
  const el = document.createElementNS(SVG_NS, tag) as SVGElement; setAttrs(el, attrs); add(el, children); return el;
}
