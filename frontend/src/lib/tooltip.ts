// The one floating tooltip (#tooltip in web/index.html), shared with
// web/app.js while both exist.
import { h } from "./dom";

const tipEl = (): HTMLElement | null => document.getElementById("tooltip");

export function showTip(evt: { clientX: number; clientY: number }, nodes: Node[]): void {
  const tip = tipEl();
  if (!tip) return;
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
export function hideTip(): void { const tip = tipEl(); if (tip) tip.hidden = true; }
export function placeTipBelow(el: Element, nodes: Node[]): void {
  const r = el.getBoundingClientRect();
  showTip({ clientX: r.left, clientY: r.bottom }, nodes);
}
export const tipRow = (value: string, label: string, color?: string | null): HTMLElement =>
  h("div", { class: "t-row" }, color ? h("span", { class: "t-key", style: `background:var(${color})` }) : null,
    h("strong", { text: value }), h("span", { text: label }));
