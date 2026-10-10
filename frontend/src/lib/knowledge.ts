// Searching Sift's help (web/knowledge.json), as searchKnowledge() in web/app.js.
import type { KnowledgeEntry } from "./host";

const entryText = (e: KnowledgeEntry) => [e.title, e.abbreviation, e.full, ...(e.aliases || []), ...(e.labels || []), e.definition, e.hover, ...(e.body || [])]
  .filter(Boolean).join(" ").toLowerCase();

/* Ranked matches: title first, then names and aliases, then anywhere in the text. Every word must appear. */
export function searchKnowledge(entries: KnowledgeEntry[], q: string): KnowledgeEntry[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const full = q.trim().toLowerCase();
  const scored: [number, KnowledgeEntry][] = [];
  for (const e of entries) {
    const text = entryText(e);
    if (!words.every((w) => text.includes(w))) continue;
    const names = [e.title, e.abbreviation, e.full, ...(e.aliases || [])].filter((x): x is string => Boolean(x)).map((x) => x.toLowerCase());
    const score = names.some((n) => n === full) ? 0 : e.title.toLowerCase().startsWith(full) ? 1
      : names.some((n) => n.includes(full)) ? 2 : (e.definition || "").toLowerCase().includes(full) ? 3 : 4;
    scored.push([score, e]);
  }
  return scored.sort((a, b) => a[0] - b[0] || a[1].title.localeCompare(b[1].title)).map(([, e]) => e);
}
