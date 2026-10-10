// A stand-in for web/app.js's window.SiftHost in component tests.
import type { Knowledge, SiftHost } from "../lib/host";

export function fakeHost(over: Partial<SiftHost> = {}, knowledge: Knowledge = { categories: [], entries: [] }): SiftHost {
  const host: SiftHost = {
    helpEntry: (id) => { const e = knowledge.entries.find((x) => x.id === id); return e ? { id: e.id, title: e.title } : null; },
    openHelp: () => undefined, isAdmin: () => false, knowledge: () => knowledge,
    fieldHelp: () => null, fillThresholds: (t) => t.replace("{margin_of_safety}", "20"),
    settings: () => ({ theme: "dark", compact: false, wrap_text: false, help_tips: true, reduce_motion: false, chart_patterns: false,
      chart_tables: false, show_hover_buttons: false, keyboard_shortcuts: true, start_page: "dashboard", search_scope: "auto", rows_shown: 100 }),
    previousPage: () => null, noteVersion: () => undefined,
    thresholds: () => ({ margin_of_safety: 20, roe: 12, debt_to_equity: 0.8, yield: 4.5 }),
    estimatedValueHelp: () => null, fundHref: () => null, afterChange: () => undefined, setThresholds: () => undefined, ...over,
  };
  window.SiftHost = host;
  return host;
}
