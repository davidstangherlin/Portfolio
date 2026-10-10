// The legend above a chart: only for two or more series (or extra symbols).
import { h } from "../lib/dom";

export interface LegendItem { name: string; color: string }
export interface LegendExtra { name: string; symbol?: string; band?: boolean; outline?: boolean }

export function legend(series: LegendItem[], rect = false, extras: LegendExtra[] = []): HTMLElement | null {
  if (series.length < 2 && !extras.length) return null;
  return h("div", { class: "legend" },
    series.map((sr) => h("span", {}, h("span", { class: `key${rect ? " rect" : ""}`, style: `background:var(${sr.color})` }), sr.name)),
    extras.map((x) => h("span", {}, x.band ? h("span", { class: "key band", "aria-hidden": "true" })
      : h("span", { class: `dkey${x.outline ? " outline" : ""}`, "aria-hidden": "true", text: x.symbol }), x.name)));
}
