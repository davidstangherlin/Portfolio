// ASX director and substantial holder notices, one line each (noticeLine()
// in web/app.js): the company page, and later the dashboard and Coattail.
import { compact, money, NA, pct } from "../lib/format";

export interface Trade { director: string | null; direction: string; acquired: number | null; disposed: number | null; consideration: number | null; price: number | null; nature_kind: string }
export interface Notice {
  kind: string; kind_label: string; asx_code: string; in_sift?: boolean; released_at: string; pdf_url: string; headline: string;
  read_status: string; read_note?: string | null; trades: Trade[];
  holding?: { holder?: string | null; previous_pct?: number | null; present_pct?: number | null } | null;
}

export const NATURE_LABELS: Record<string, string> = { ON_MARKET: "On market", OFF_MARKET: "Off market", EXERCISE: "Options or rights", DRP: "Dividend reinvestment", ISSUE: "Issued to them", OTHER: "Other" };
export const EVENT_LABELS: Record<string, string> = { SUBSTANTIAL_NEW: "Became", SUBSTANTIAL_CHANGE: "Changed", SUBSTANTIAL_CEASE: "Ceased" };
/* ASX releases are dated in Sydney time, whatever the viewer's time zone. */
export const noticeDay = (iso: string) => new Date(iso).toLocaleDateString("en-AU", { timeZone: "Australia/Sydney", day: "numeric", month: "short" });
export const noticeWhen = (iso: string) => new Date(iso).toLocaleString("en-AU", { timeZone: "Australia/Sydney", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
export const countText = (v: number) => new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 1 }).format(Math.abs(v));
export const sharesText = (v: number | null | undefined) => (v === null || v === undefined ? NA : countText(v));

export function NoticeLink({ n, label = "Notice" }: { n: Notice; label?: string }) {
  return <a href={n.pdf_url} target="_blank" rel="noopener noreferrer" className="notice-link"
    title={`${n.headline} (the PDF on the ASX website)`} aria-label={`${n.headline}, ${n.asx_code}: open the notice on the ASX website`}>{`${label} ↗`}</a>;
}

export function tradeText(t: Trade): string {
  const units = t.direction === "SELL" ? t.disposed : t.acquired;
  if (t.direction === "NONE") return "No shares bought or sold";
  const verb = ({ BUY: "Bought", SELL: "Sold", MIXED: "Bought and sold" } as Record<string, string>)[t.direction];
  const amount = t.direction === "MIXED" ? `${sharesText(t.acquired)} and ${sharesText(t.disposed)}` : sharesText(units);
  return `${verb} ${amount} shares${t.consideration !== null ? ` for ${compact(t.consideration)}` : ""}${t.price !== null ? ` at ${money(t.price, t.price < 1 ? 3 : 2)}` : ""}`;
}
export function holdingText(n: Notice): string {
  const x = n.holding || {};
  const who = x.holder || "A holder";
  if (n.kind === "SUBSTANTIAL_NEW") return `${who} now holds ${x.present_pct === null || x.present_pct === undefined ? "5% or more" : pct(x.present_pct, 2)}`;
  if (n.kind === "SUBSTANTIAL_CEASE") return `${who} is now below 5%`;
  return x.previous_pct !== null && x.present_pct !== null && x.present_pct !== undefined
    ? `${who}: ${pct(x.previous_pct, 2)} to ${pct(x.present_pct, 2)}` : `${who} changed their holding`;
}

export function NoticeLine({ n }: { n: Notice }) {
  const unread = n.read_status !== "read" && !n.trades.length && !(n.holding && n.holding.holder);
  const what = n.kind === "DIRECTOR"
    ? (n.trades.length ? n.trades.map((t) => `${t.director || "A director"}: ${tradeText(t)}${t.nature_kind !== "OTHER" ? ` (${NATURE_LABELS[t.nature_kind].toLowerCase()})` : ""}`).join("; ") : "")
    : holdingText(n);
  return (
    <li className="notice-line">
      <div className="main"><span className={`tag sm notice-${n.kind === "DIRECTOR" ? "dir" : "sub"}`}>{n.kind_label}</span>{" "}
        {n.in_sift === false ? <span className="code">{n.asx_code}</span> : <a className="code" href={`#/company/${n.asx_code}`}>{n.asx_code}</a>}
        <div className="notice-what">{unread ? `Details not read: ${n.read_note || "open the notice"}` : what}</div></div>
      <div className="side"><span className="hint">{noticeDay(n.released_at)}</span>{" "}<NoticeLink n={n} /></div>
    </li>
  );
}
