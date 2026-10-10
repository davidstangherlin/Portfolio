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
}

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
};
export const host = (): SiftHost => window.SiftHost ?? fallback;
