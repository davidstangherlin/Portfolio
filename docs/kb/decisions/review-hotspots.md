---
id: review-hotspots
title: Review hotspots: where an outside reviewer adds most value
category: decisions
summary: The parts of the valuation and ingestion code most worth a second opinion from an outside reviewer or a new developer, and why.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §14
related: [valuation-models, ingestion, trends-markers]
code: [src/valuation/, src/ingestion/yahoo_client.py]
---

## Summary

Hand this to anyone reviewing Sift's logic (a contractor, an accountant, another model). Each point names the code and the question worth asking.

If handing this document plus the source to another model for review, the highest-value areas to interrogate are:

1. **`src/valuation/dividends.py`**, confirm the franking credit formula and the percentage-to-fraction conversion are correct against the current ATO methodology
2. **`src/valuation/dcf.py`**, confirm the two-stage DCF mechanics (particularly the terminal value formula and the point at which it's discounted back) match standard practice
3. **`src/valuation/engine.py`, `_estimate_shares_outstanding()`**, this single derived value cascades into four other metrics; worth an opinion on whether deriving it from `market_cap / price` is more or less reliable than the NPAT/EPS fallback
4. **`src/ingestion/yahoo_client.py`, `get_annual_fundamentals()`**, field-name mapping was fixed on 2026-10-01 after live data revealed a naming mismatch (see [§10.6](kb:testing-and-validation)); a second opinion on whether the corrected PascalCase labels are complete/robust (and whether the fallback chains, e.g. `StockholdersEquity` vs `CommonStockEquity`, pick the right one in edge cases) would be valuable
5. **Upsert/coalesce strategy in `fundamentals_ingestion.py`**, worth confirming the "never let a NULL fetch overwrite good data" design is the right call versus simply always taking the latest fetch
6. **`src/valuation/engine.py`, `_average_free_cash_flow()`**, a straightforward simple mean over 3 years ([§8.4](kb:valuation-models)); worth a second opinion on whether a recency-weighted average or outlier-trimming would be more defensible than an unweighted mean, particularly for cyclical or recently-restructured companies (SUN's own FY2023 debt collapse, likely a bank-arm divestment, is exactly this kind of structural break a simple mean doesn't account for)
7. **`src/valuation/ddm.py` and the sector routing in `engine.py`'s `compute_metrics()`** (added 2026-10-02, [§8.3](kb:valuation-models)/[§8.4](kb:valuation-models)), two deliberate simplifications worth a second opinion: (a) `_SECTOR_AWARE_SECTORS` is an exact-string match against yfinance's two GICS-like sector labels (`"Financial Services"`, `"Real Estate"`) with no fuzzy matching or fallback if Yahoo's labelling is inconsistent for a given company; (b) the DDM reuses the same `--growth-rate`/`--discount-rate`/`--terminal-growth-rate`/`--stage1-years` CLI inputs as the DCF path rather than exposing a second set of dividend-specific assumptions, so a single `run_valuation --all` invocation applies one global growth-rate assumption to both FCF growth (DCF sectors) and dividend growth (Financial Services/Real Estate), a reasonable simplification given the project's existing "one global assumption set" design, but worth checking whether a lower default growth rate specifically for sustained dividend growth (DDM's own default is 5% vs DCF's 8%, used only when the caller doesn't override) is adequate, or whether real-world bank/REIT dividend growth is better modelled with its own CLI-exposed default
8. **`src/valuation/engine.py`'s `_fundamentals_trend()`** (added 2026-10-02, [§8.6](kb:trends-markers)), a deliberately simple two-endpoint (latest vs oldest fetched FY report) heuristic on ROE and revenue direction, with fixed thresholds (2pp ROE, 5% revenue). Worth a second opinion on: whether two fixed thresholds are well-calibrated across very different company sizes/sectors (a 2pp ROE swing may be noise for a volatile miner but meaningful for a stable bank), whether a monotonic multi-point check across all fetched years (not just the two endpoints) would catch a mid-window dip/recovery that the current endpoint-only comparison misses, and whether `trap_risk`'s binary composite (`mos_ok AND fundamentals_trend == 'DECLINING'`) is the right combination logic versus, say, a severity-weighted score
