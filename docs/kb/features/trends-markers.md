---
id: trends-markers
title: Trends and markers: momentum, value traps, quality and price signals
category: features
summary: The margin-of-safety trend, fundamentals trend, value-trap warning and the decision markers (earnings quality, price position, dividend reliability, data confidence).
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2026-11-09
source: AS_BUILT §8.6, §8.7
related: [valuation-models, screener-actions]
code: [src/valuation/engine.py, src/valuation/markers.py]
tables: [valuation_metrics]
---

> Migrated from the early as-built record (October 2026). Parts of How it works describe the command line as first built; the review due in November checks it against today's code (IMP-037).

## Purpose

A static margin of safety can't tell a newly mispriced company from a declining business that has been cheap for months. Trends and markers add that context so actions and red flags can tell them apart.

## How it works

### Trend Indicators, "Momentum Into Value" and the Value-Trap Warning

User request: *"is there another ranking to alert users to items worth looking at based on a trend? Something to help catch the next best share before others catch on? ... will be good to have a field that can populate in time to identify a potential value trap."* Two new `valuation_metrics` columns, computed independently and populating on different timelines:

**`margin_of_safety_trend`**, the change in `margin_of_safety_percent` versus the most recent `valuation_metrics` snapshot at least `trend_days` (default 30) old for the same company. `_prior_margin_of_safety()` queries for the newest row with `as_of_date <= as_of_date - trend_days`, so a gap in daily runs (machine off for a day) doesn't break it - it just uses whatever snapshot is old enough. This is the "momentum into value" signal: rising means the company is getting cheaper relative to its intrinsic value *since that earlier snapshot*, not just cheap in absolute terms - the idea being that a company newly crossing into value territory, or cheapening fastest, is more interesting to act on than one that's been statically cheap for months (often a sign something is wrong, not a sign of mispricing - see `fundamentals_trend` below). Depends on the schema's existing `UNIQUE(company_id, as_of_date)` design already accumulating one row per company per day once `scripts/daily_refresh.ps1` runs daily - no new schema mechanism was needed for the history itself, only for the two derived columns.

**Cold-start, by design, not a bug.** `margin_of_safety_trend` is `NULL` for every company until a `trend_days`-old snapshot exists - i.e. until daily automation has been running for that long. This was flagged explicitly by the user ("a field that can populate in time") and is surfaced directly: `screen_asx.py` prints a note when every row's trend is blank, rather than leaving the user to wonder whether it's broken ([§9](kb:screener-actions)).

**`fundamentals_trend`**, `'IMPROVING'` / `'STABLE'` / `'DECLINING'`, computed by `_fundamentals_trend()` from the latest vs oldest `FinancialReport` in the same `fcf_average_years`-report window already fetched for the DCF/DDM average ([§8.4](kb:valuation-models)) - no new DB query needed, and no cold-start wait, since it only needs annual report history that's typically already ingested (2+ years). Classification is a simple, explainable heuristic, consistent with this codebase's existing formula style (Graham Number, grossed-up yield): ROE change in percentage points and revenue change as a fraction, each compared against a fixed threshold (`_ROE_TREND_THRESHOLD = 2pp`, `_REVENUE_TREND_THRESHOLD = 5%`) -  `DECLINING` if either signal is clearly negative, `IMPROVING` if either is clearly positive (and neither is negative), `STABLE` otherwise, `None` if fewer than 2 distinct FY reports exist or neither signal is computable. **Not a sophisticated trend model** - a decline that started mid-window and partially recovered, or a company with only 2 FY reports, gets a trend based on just the two endpoints available; treat it as a prompt to look closer, not a verdict (documented in README.md's Known Data Model Limitations).

**Why two independent fields rather than one combined score:** `margin_of_safety_trend` is price-driven (changes daily, needs accumulated history) while `fundamentals_trend` is business-driven (changes only as new annual reports are ingested, available immediately). Conflating them into a single score would hide which kind of signal is actually driving it - keeping them separate lets the screener combine them explicitly and transparently ([§9](kb:screener-actions)'s `trap_risk` = cheap (`mos_ok`) **and** fundamentals declining; `momentum_ok` uses `margin_of_safety_trend` alone).

Both columns are appended at the **end** of the `valuation_metrics` table and the `asx_value_screener` view's `SELECT` list ([§4.4](kb:data-model)'s `CREATE OR REPLACE VIEW` append-only lesson applies here too), with idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` for pre-existing databases. `margin_of_safety_trend` is covered by the existing generic `_clamp_to_column_precision()` overflow guard ([§8.4](kb:valuation-models), IMP-015) exactly like every other `NUMERIC` column - no separate sanity cap was needed.

### Decision Markers

User request: *"are there any other markers or decision points we should add to help level me up as an investor?"* Four were chosen, each answering a question the four classic value criteria can't, and all built from data the pipeline already collects. Computed in `compute_metrics()`, stored in `valuation_metrics` (appended to the table and view per [§4.4](kb:data-model)'s append-only lesson), and deliberately simple rules - prompts to look closer, not verdicts.

| Marker | Question | Rule | Why it matters |
|---|---|---|---|
| `earnings_quality` (from `cash_conversion`) | Is reported profit turning into cash? | Operating cash flow / NPAT, summed over the `fcf_average_years` window: `STRONG` >= 100%, `ADEQUATE` >= 80%, `WEAK` below. `NULL` for loss-makers and for Financial Services/Real Estate | Accounting profit can be flattered by accruals and revaluations; persistent shortfalls between profit and cash are one of the most reliable early warnings, and P/E and ROE can't see them |
| `price_signal` (from `price_vs_200d`, `range_position_52w`) | Is the price stabilising or still falling? | `NEW LOWS` = below the 200-trading-day average **and** in the bottom 10% of the 52-week range; `DOWNTREND` = below the average; `UPTREND` = above. Needs 200 stored daily prices | Separates "cheap and basing" from "cheap and still falling" - buying the falling knife is the classic value-investing mistake. The label is derived in the screener from the two stored numbers |
| `dividend_trend` | Is the dividend dependable? | Over up to 5 FY reports: `CUT` if the latest dividend is more than 10% below last year's or below the median of the earlier years (a cut that still stands), `GROWING` if the latest is >5% above the oldest, `STEADY` otherwise, `NONE` for non-payers. Revised 2026-10-05: previously any year-on-year drop in the window counted, which flagged nearly every miner and energy producer for dividends they vary with earnings by policy | A yield is only worth what its reliability is worth. A year after a special dividend correctly reads as a cut in cash terms; `payout_ratio` flags the special year itself, and the median stops one special year from inflating the baseline |
| `data_confidence` | How much of this analysis rests on missing data? | 11 checks (price, market cap, EPS, NPAT, revenue, equity, debt, OCF, FCF, 3+ FY reports, 200+ daily prices): `HIGH` >= 90%, `MEDIUM` >= 70%, `LOW` below. Dividends aren't counted - a non-payer isn't missing data | Tells you when a signal is built on thin ground before you act on it |

**Design notes.** `gather_inputs()` now fetches up to `max(fcf_average_years, 5)` FY reports in one query and slices the first `fcf_average_years` for the DCF/DDM base and `fundamentals_trend` (unchanged behaviour), keeping the longer history for `dividend_trend`. A second query fetches the last 365 calendar days of closes for the price markers. Both new `ValuationInputs` fields default to empty lists, so the existing unit-test builders needed no change. `cash_conversion`, `price_vs_200d` and `range_position_52w` are covered by `_clamp_to_column_precision()` like every other numeric column.

**Price history prerequisite.** `scripts/daily_refresh.ps1` ingests the default `--period 1mo` of prices each day, so a database built that way holds too little history for the 200-day average until it has run for ~10 months. A one-off backfill fixes this immediately: `python -m src.ingestion.run_ingestion --tickers-file allords.txt --prices-only --period 1y --delay 0.5` (upserts, so it's safe to re-run). Until then `price_signal` is blank and `data_confidence` tops out at 10 of 11 checks, which is still `HIGH`.

## Code map

- `src/valuation/engine.py`: margin-of-safety and fundamentals trends
- `src/valuation/markers.py`: earnings quality, price signal, dividend reliability, data confidence

## Data

- `valuation_metrics`: the trend and marker columns sit beside each valuation

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Price signal or 200-day figures blank: fewer than 200 stored daily prices; backfill with a one-year price fetch (IMP-020).
- A company flagged as a value trap that looks healthy: the fundamentals trend compares only the oldest and newest report (IMP-018).

## Known limits

- The fundamentals trend is a two-endpoint heuristic with fixed thresholds (IMP-018).
- Momentum needs weeks of stored valuations before it means anything.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_markers.py`
- `tests/unit/test_engine.py`
