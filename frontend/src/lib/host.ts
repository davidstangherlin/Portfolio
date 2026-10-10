// What the current app (web/app.js) shares with React islands while both
// exist (ADR-018). app.js sets window.SiftHost before any island mounts.
export interface HelpEntry { id: string; title: string }
export interface SiftHost {
  helpEntry(id: string): HelpEntry | null;
  openHelp(id: string): void;
  isAdmin(): boolean;
}

declare global {
  interface Window { SiftHost?: SiftHost }
}

const fallback: SiftHost = { helpEntry: () => null, openHelp: () => undefined, isAdmin: () => false };
export const host = (): SiftHost => window.SiftHost ?? fallback;
