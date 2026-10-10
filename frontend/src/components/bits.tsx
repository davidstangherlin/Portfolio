// Small pieces every page uses, with the same markup and classes as
// web/app.js so they share Sift's styles.
import type { KeyboardEvent, ReactNode } from "react";
import { host } from "../lib/host";

export const ACTION_STATUS: Record<string, string> = {
  BUY: "good", ACCUMULATE: "good", INVESTIGATE: "warning", WATCH: "neutral", HOLD: "neutral",
  REVIEW: "serious", SELL: "critical", AVOID: "critical", IGNORE: "neutral",
};

export function Badge({ action }: { action: string }) {
  return <span className={`badge ${ACTION_STATUS[action] || "neutral"}`}>{action}</span>;
}

export function PageHead({ title, sub, children }: { title: string; sub?: string | null; children?: ReactNode }) {
  return <div className="page-head"><h1>{title}</h1>{sub ? <span className="sub">{sub}</span> : null}{children}</div>;
}

export function Loading({ text }: { text: string }) {
  return <p className="loading">{text}</p>;
}

export function ErrorLine({ error }: { error: Error }) {
  return <p className="error">Could not load: {error.message}</p>;
}

export function WatchStar({ lists }: { lists?: string[] | null }) {
  if (!lists || !lists.length) return null;
  return <span className="watch-star" title={`On watchlist: ${lists.join(", ")}`} aria-label={`On watchlist ${lists.join(", ")}`}>★</span>;
}

/* A table row that opens a company's page on click or Enter. */
export function ClickableRow({ code, children }: { code: string; children: ReactNode }) {
  const open = () => { location.hash = `#/company/${code}`; };
  return <tr tabIndex={0} onClick={open} onKeyDown={(e: KeyboardEvent) => { if (e.key === "Enter") open(); }}>{children}</tr>;
}

/* "Show data table" under a chart: open by default with the chart_tables preference. */
export function TableView({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  return (
    <details className="table-view" open={host().settings().chart_tables || undefined}>
      <summary>Show data table</summary>
      <div className="table-wrap"><table className="grid">
        <thead><tr>{headers.map((x, i) => <th key={i} className={i ? "num" : undefined}>{x}</th>)}</tr></thead>
        <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((v, i) => <td key={i} className={i ? "num" : undefined}>{v}</td>)}</tr>)}</tbody>
      </table></div>
    </details>
  );
}

/* The legend above a chart or bar, as legend() in web/app.js: only for two or more items. */
export function Legend({ items, rect = false }: { items: { name: string; color: string }[]; rect?: boolean }) {
  if (items.length < 2) return null;
  return <div className="legend">{items.map((sr) => <span key={sr.name}><span className={`key${rect ? " rect" : ""}`} style={{ background: `var(${sr.color})` }} />{sr.name}</span>)}</div>;
}
