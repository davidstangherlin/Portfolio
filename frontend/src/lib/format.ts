// Number and date formatting, identical to web/app.js so React and plain
// JavaScript pages read the same while Sift moves over (ADR-018).
export const NA = "n/a";
type Num = number | null | undefined;

export const fmt = (v: Num, dp = 2): string =>
  v === null || v === undefined ? NA
    : new Intl.NumberFormat("en-AU", { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(v);
export const pct = (v: Num, dp = 1): string => (v === null || v === undefined ? NA : fmt(v, dp) + "%");
export const money = (v: Num, dp = 2): string => (v === null || v === undefined ? NA : (v < 0 ? "-$" : "$") + fmt(Math.abs(v), dp));
export const signed = (v: Num, fmtFn: (x: number) => string): string =>
  v === null || v === undefined ? NA : (v > 0 ? "+" : v < 0 ? "-" : "") + fmtFn(Math.abs(v));
export const plural = (n: number, word: string, many = word + "s"): string => `${fmt(n, 0)} ${n === 1 ? word : many}`;
export const toDate = (iso: string): Date => new Date(iso + "T00:00:00");
export const longDate = (iso: string): string =>
  toDate(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
export function compact(v: Num): string {
  if (v === null || v === undefined) return NA;
  const body = new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 1 }).format(Math.abs(v));
  return (v < 0 ? "-$" : "$") + body;
}
export const dayMonth = (iso: string): string => toDate(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
export const monthYear = (iso: string): string => toDate(iso).toLocaleDateString("en-AU", { month: "short", year: "2-digit" });
export const sum = (xs: number[]): number => xs.reduce((a, b) => a + b, 0);
export const signedPct = (v: Num, dp = 1): string => signed(v, (x) => fmt(x, dp) + "%");
export const dateTime = (iso: string): string =>
  new Date(iso).toLocaleString("en-AU", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
export const timeOnly = (iso: string): string => new Date(iso).toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" });
/* "pos" or "neg" for a figure's sign, nothing for zero or no figure. */
export const signClass = (v: Num): string | undefined => (v === null || v === undefined || v === 0 ? undefined : v > 0 ? "pos" : "neg");
