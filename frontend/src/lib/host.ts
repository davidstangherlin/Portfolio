// What the current app (web/app.js) shares with React while both exist
// (ADR-018). app.js sets window.SiftHost before any React page or card
// mounts; once React owns the shell, these move into React itself.
export interface HelpEntry { id: string; title: string }
export interface KnowledgeEntry {
  id: string; title: string; category: string; definition?: string; hover?: string; body?: string[];
  abbreviation?: string; full?: string; aliases?: string[]; labels?: string[];
  related?: string[]; links?: { text: string; href: string }[];
}
export interface Knowledge { categories: { id: string; name: string }[]; entries: KnowledgeEntry[] }
export interface Settings {
  theme: string; compact: boolean; wrap_text: boolean; help_tips: boolean; reduce_motion: boolean;
  chart_patterns: boolean; chart_tables: boolean; show_hover_buttons: boolean; keyboard_shortcuts: boolean;
  start_page: string; search_scope: string; rows_shown: number;
}
export interface SiftHost {
  helpEntry(id: string): HelpEntry | null;
  openHelp(id: string): void;
  isAdmin(): boolean;
  knowledge(): Knowledge;
  /* A label's hover explanation with the live thresholds filled in, or null. */
  fieldHelp(label: string): string | null;
  fillThresholds(text: string): string;
  settings(): Settings;
  /* The page a detail page's back link returns to. */
  previousPage(): string | null;
  noteVersion(res: Response): void;
  /* The live value-test thresholds (margin of safety, ROE, debt/equity, yield). */
  thresholds(): Thresholds;
  /* The estimated value's explanation for a valuation method (DCF or DDM). */
  estimatedValueHelp(method: string | null): string | null;
  /* An ETF's or LIC's page address, if the code is a fund rather than a share. */
  fundHref(code: string): string | null;
  /* After adding to or removing from a watchlist: refresh the menus and cached lists. */
  afterChange(): void;
}
export interface Thresholds { margin_of_safety: number; roe: number; debt_to_equity: number; yield: number }

declare global {
  interface Window { SiftHost?: SiftHost }
}

const DEFAULT_SETTINGS: Settings = {
  theme: "dark", compact: false, wrap_text: false, help_tips: true, reduce_motion: false, chart_patterns: false,
  chart_tables: false, show_hover_buttons: false, keyboard_shortcuts: true, start_page: "dashboard", search_scope: "auto", rows_shown: 100,
};
const fallback: SiftHost = {
  helpEntry: () => null, openHelp: () => undefined, isAdmin: () => false,
  knowledge: () => ({ categories: [], entries: [] }), fieldHelp: () => null, fillThresholds: (t) => t,
  settings: () => DEFAULT_SETTINGS, previousPage: () => null, noteVersion: () => undefined,
  thresholds: () => ({ margin_of_safety: 20, roe: 12, debt_to_equity: 0.8, yield: 4.5 }),
  estimatedValueHelp: () => null, fundHref: () => null, afterChange: () => undefined,
};
export const host = (): SiftHost => window.SiftHost ?? fallback;
