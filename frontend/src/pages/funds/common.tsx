// ETFs (§26) and LICs (§27), each under its own heading. Neither is judged
// on estimated value: ETFs on fee, size, distributions and total return;
// LICs (listed investment companies and trusts) the same, plus the share
// price against net tangible assets (NTA). One set of pages serves both,
// set up by FUNDS[kind] (as in web/app.js).
import type { ReactNode } from "react";
import { WatchStar } from "../../components/bits";
import { compact, fmt, NA, signClass, signedPct, toDate } from "../../lib/format";

export type Kind = "ETF" | "LIC";
export interface FundConfig {
  kind: Kind; path: string; list: string; api: string; noun: string; nouns: string; price: string; per: string;
  payout: string; payouts: string; size: string; help: string; intro: string; sort: { key: string; dir: "asc" | "desc" };
}
export const FUNDS: Record<Kind, FundConfig> = {
  ETF: { kind: "ETF", path: "etf", list: "#/etfs", api: "etf", noun: "ETF", nouns: "ETFs", price: "Unit price", per: "unit",
    payout: "Distribution", payouts: "Distributions", size: "Fund size", help: "etf",
    intro: "Exchange traded funds, kept apart from shares: judged on fee, size, distributions and total return rather than estimated value.",
    sort: { key: "fum_aud", dir: "desc" } },
  LIC: { kind: "LIC", path: "lic", list: "#/lics", api: "lic", noun: "LIC", nouns: "LICs", price: "Share price", per: "share",
    payout: "Dividend", payouts: "Dividends", size: "Market cap", help: "lic",
    intro: "Listed investment companies and trusts, kept apart from shares and ETFs: judged on the share price against net tangible assets (NTA), fee, dividends and total return.",
    sort: { key: "premium_now", dir: "asc" } },
};
export const fundHref = (kind: Kind, code: string) => `#/${FUNDS[kind].path}/${code}`;
export const fundSize = (v: number | null | undefined) => compact(v);
export const monthName = (iso: string) => toDate(iso).toLocaleDateString("en-AU", { month: "long", year: "numeric" });
/* Premium (+) or discount (-) to NTA: shown with its sign, not coloured as good or bad. */
export const premText = (v: number | null | undefined) => (v === null || v === undefined ? NA : v < 0 ? `${fmt(-v, 1)}% discount` : v > 0 ? `${fmt(v, 1)}% premium` : "at NTA");

export const KindTag = ({ kind }: { kind: string }) => <span className="tag sm etf-tag">{kind}</span>;
export const RetCell = ({ v, cls = "" }: { v: number | null | undefined; cls?: string }) =>
  <td className={`num ${cls} ${signClass(v) || ""}`.trim()}>{signedPct(v)}</td>;
export const PremCell = ({ v, cls = "" }: { v: number | null | undefined; cls?: string }) =>
  <td className={`num ${cls}`.trim()}><span className="long">{premText(v)}</span><span className="short">{signedPct(v)}</span></td>;

export interface FundRow {
  asx_code: string; company_name: string | null; category: string; issuer: string | null; product_type: string | null; held: unknown; watchlists: string[];
  benchmark?: string | null; [key: string]: unknown;
}
export function NameCell({ r, kind, star = true }: { r: FundRow; kind: Kind; star?: boolean }) {
  return (
    <td><span className="code">{r.asx_code}</span>{star ? <WatchStar lists={r.watchlists} /> : null}
      {r.held !== null && r.held !== false ? <span className="held-tag">HELD</span> : null}
      {kind === "LIC" && r.product_type === "LIT" ? <KindTag kind="LIT" /> : null}<div className="name">{r.company_name || ""}</div></td>
  );
}

/* A table row that opens a page, like ClickableRow but to any address. */
export function RowTo({ href, children }: { href: string; children: ReactNode }) {
  const open = () => { location.hash = href; };
  return <tr tabIndex={0} onClick={open} onKeyDown={(e) => { if (e.key === "Enter") open(); }}>{children}</tr>;
}
