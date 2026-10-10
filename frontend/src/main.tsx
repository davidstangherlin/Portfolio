// Sift's React islands (docs/kb/decisions/adr-018-react-typescript-pages.md).
// web/app.js calls SiftUI.mount(name, element, props) to put a component on
// a page it built, and SiftUI.sweep() after each page change so islands on
// pages that have gone are unmounted.
import type { ComponentType } from "react";
import { createRoot, type Root } from "react-dom/client";
import { FinancialHealthCard } from "./islands/FinancialHealthCard";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ISLANDS: Record<string, ComponentType<any>> = { FinancialHealthCard };
const mounted = new Set<{ el: Element; root: Root }>();

function mount(name: string, el: Element, props: Record<string, unknown> = {}): boolean {
  const Component = ISLANDS[name];
  if (!Component) return false;
  const root = createRoot(el);
  root.render(<Component {...props} />);
  mounted.add({ el, root });
  return true;
}

function sweep(): void {
  for (const m of mounted) {
    if (!m.el.isConnected) { m.root.unmount(); mounted.delete(m); }
  }
}

declare global {
  interface Window { SiftUI?: { mount: typeof mount; sweep: typeof sweep; islands: string[] } }
}
window.SiftUI = { mount, sweep, islands: Object.keys(ISLANDS) };
