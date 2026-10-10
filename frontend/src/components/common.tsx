// Pieces the company, fund and list pages share (web/app.js equivalents named).
import type { ReactNode } from "react";
import { host } from "../lib/host";
import { useFieldHelp } from "./FieldHelp";
import { HelpLink } from "./HelpLink";

/* Valuation status from margin of safety, using the live value-test threshold (valuationStatus()). */
export function valuationStatus(mos: number | null | undefined): { cls: string; label: string } {
  if (mos === null || mos === undefined) return { cls: "none", label: "No estimate" };
  if (mos > host().thresholds().margin_of_safety) return { cls: "under", label: "Undervalued" };
  if (mos >= 0) return { cls: "fair", label: "Fair value" };
  return { cls: "over", label: "Overvalued" };
}
export function ValuationPill({ mos, large = false }: { mos: number | null | undefined; large?: boolean }) {
  const st = valuationStatus(mos);
  return <span className={`pill ${st.cls}${large ? " lg" : ""}`}>{st.label}</span>;
}

/* One headline figure: label (with its explanation), value, small note (statTile()). */
export function StatTile({ label, value, cls, note }: { label: string; value: string; cls?: string | null; note?: string | null }) {
  const { props, info } = useFieldHelp(label);
  const labelCls = ["stat-label", (props as { className?: string }).className].filter(Boolean).join(" ");
  return (
    <div className="stat">
      <div {...props} className={labelCls} tabIndex={0}>{label}{info}</div>
      <div className={`stat-value ${cls || ""}`.trim()}>{value}</div>
      {note ? <div className="stat-note">{note}</div> : null}
    </div>
  );
}

/* A term with its explanation on hover, as withHelp(h(tag, {tabindex: 0, text}), label). */
export function Explained({ as = "span", label, className }: { as?: "span" | "dt" | "div"; label: string; className?: string }) {
  const { props, info } = useFieldHelp(label);
  const Tag = as;
  const cls = [className, (props as { className?: string }).className].filter(Boolean).join(" ") || undefined;
  return <Tag {...props} className={cls} tabIndex={0}>{label}{info}</Tag>;
}

/* Text followed by its help link (withHelpLink()). */
export function WithHelpLink({ text, id }: { text: ReactNode; id?: string | null }) {
  return <>{text}{" "}{id ? <HelpLink id={id} /> : null}</>;
}

/* A shorted share can still be bought, with care: an amber caution beside the action (cautionTag()). */
const CAUTION_WORDS: Record<string, string> = { HIGH: "Heavily shorted", ELEVATED: "Shorted" };
export function CautionTag({ level, iconOnly = false, held = false }: { level?: string | null; iconOnly?: boolean; held?: boolean }) {
  if (!level) return null;
  const words = `Caution: ${CAUTION_WORDS[level].toLowerCase()}, expect bigger price swings` +
    (held ? ". Not a reason to sell on its own: open the company for what it means." : "");
  return (
    <span className={`caution-tag${level === "HIGH" ? " high" : ""}`} title={words} aria-label={words} role="img">
      <span aria-hidden="true">!</span>{iconOnly ? null : <span>{CAUTION_WORDS[level]}</span>}
    </span>
  );
}

const BACK_LABELS: [RegExp, string][] = [[/^#\/?$/, "Dashboard"], [/^#\/screener/, "ASX Stocks"], [/^#\/etfs/, "ETFs"], [/^#\/etf\//, "ETF"], [/^#\/lics/, "LICs"], [/^#\/lic\//, "LIC"], [/^#\/portfolios/, "Portfolios"], [/^#\/portfolio\//, "Portfolio"],
  [/^#\/track-record/, "Track record"], [/^#\/coattail/, "Coattail"], [/^#\/watchlists/, "Watchlists"], [/^#\/watchlist\//, "Watchlist"], [/^#\/help/, "Help"]];
/* "← ASX Stocks": back to the list the page was opened from (backLink()). */
export function BackLink({ fallback = "#/screener" }: { fallback?: string }) {
  const target = host().previousPage() || fallback;
  const label = (BACK_LABELS.find(([re]) => re.test(target)) || [null, "ASX Stocks"])[1];
  return <a className="back" href={target}>{`← ${label}`}</a>;
}

/* A pass, fail or no-data checklist (checklist()). */
export function PassList({ items }: { items: { label: string; passed: boolean | null }[] }) {
  return (
    <ul className="checklist">
      {items.map((ch, i) => {
        const [cls, mark] = ch.passed === true ? ["pass", "✓"] : ch.passed === false ? ["fail", "✕"] : ["na", "–"];
        return <li key={i}><span className={`mark ${cls}`} aria-hidden="true">{mark}</span><span>{ch.label + (ch.passed === null ? " (no data)" : "")}</span></li>;
      })}
    </ul>
  );
}

/* "Key: value" pairs as a definition list. */
export function KV({ rows, help = false }: { rows: [string, string][]; help?: boolean }) {
  return <dl className="kv">{rows.flatMap(([k, v]) => [help ? <Explained key={`t-${k}`} as="dt" label={k} /> : <dt key={`t-${k}`}>{k}</dt>, <dd key={`d-${k}`}>{v}</dd>])}</dl>;
}

