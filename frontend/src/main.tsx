// Sift's React islands (docs/kb/decisions/adr-018-react-typescript-pages.md).
// web/app.js calls SiftUI.mount(name, element, props) to put a component on
// a page it built (or to draw a whole page), and SiftUI.sweep() after each page change so islands on
// pages that have gone are unmounted.
import type { ComponentType } from "react";
import { createRoot, type Root } from "react-dom/client";
import { invalidate } from "./lib/cache";
import { FinancialHealthCard } from "./islands/FinancialHealthCard";
import { CompanyPage } from "./pages/company/CompanyPage";
import { FundPage } from "./pages/funds/FundPage";
import { FundsPage } from "./pages/funds/FundsPage";
import { HelpPage } from "./pages/HelpPage";
import { ScreenerPage } from "./pages/ScreenerPage";
import { TrackRecordPage } from "./pages/TrackRecordPage";

// Cards mounted with island() and whole pages mounted with reactPage() in web/app.js.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ISLANDS: Record<string, ComponentType<any>> = { CompanyPage, FinancialHealthCard, FundPage, FundsPage, HelpPage, ScreenerPage, TrackRecordPage };
const mounted = new Set<{ el: Element; root: Root; name: string }>();

function mount(name: string, el: Element, props: Record<string, unknown> = {}): boolean {
  const Component = ISLANDS[name];
  if (!Component) return false;
  const root = createRoot(el);
  root.render(<Component {...props} />);
  mounted.add({ el, root, name });
  return true;
}

/* Give a mounted page new props without remounting it (the same page with
   a different address, such as a fund compared with another). */
function update(el: Element, props: Record<string, unknown> = {}): boolean {
  for (const m of mounted) {
    if (m.el !== el) continue;
    const Component = ISLANDS[m.name];
    m.root.render(<Component {...props} />);
    return true;
  }
  return false;
}

function sweep(): void {
  for (const m of mounted) {
    if (!m.el.isConnected) { m.root.unmount(); mounted.delete(m); }
  }
}

declare global {
  interface Window { SiftUI?: { mount: typeof mount; update: typeof update; sweep: typeof sweep; invalidate: typeof invalidate; islands: string[] } }
}
window.SiftUI = { mount, update, sweep, invalidate, islands: Object.keys(ISLANDS) };
