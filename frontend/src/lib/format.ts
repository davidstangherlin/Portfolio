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
