---
id: valuation-models
title: Valuation models: DCF, DDM, Graham Number and yield
category: features
summary: How each company's estimated value, margin of safety, ratios and franking-adjusted yield are calculated, and why banks, insurers and REITs use a dividend model.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2026-11-09
source: AS_BUILT §8.1, §8.2, §8.3, §8.4, §8.5
related: [trends-markers, screener-actions, admin-console, adr-004-dcf-ddm-by-sector, ref-settings]
code: [src/valuation/engine.py, src/valuation/dcf.py, src/valuation/ddm.py, src/valuation/graham.py, src/valuation/dividends.py, src/valuation/run_valuation.py, src/settings.py]
tables: [valuation_metrics]
---

> Migrated from the early as-built record (October 2026). Parts of How it works describe the command line as first built; the review due in November checks it against today's code (IMP-037).

## Purpose

Valuation turns stored statements and prices into an estimated value per share and the ratios the value tests use. It is the core of Sift's judgement, so every formula is deterministic, documented and covered by tests pinned to real figures.

## How it works

### `dividends.py`, Grossed-Up Dividend Yield

Implements the ATO franking credit formula:

```
franking_credit = DPS × franking_fraction × (tax_rate_fraction / (1 − tax_rate_fraction))
gross_dividend  = DPS + franking_credit
grossed_up_yield = (gross_dividend / price) × 100
```

**Design note for reviewers:** `financial_reports.franking_percentage` and `corporate_tax_rate` are stored as **whole-number percentages** (`100.0`, `30.0`) per the schema. The formula as originally specified requires **fractions** (`1.0`, `0.30`), feeding whole numbers directly into the formula as given produces a mathematically broken result (`1 − 30` is negative). `dividend_yields()` performs the `/100` conversion before calling `gross_dividend()`. This is the single most important formula detail to check if yields ever look wildly wrong.

**`payout_ratio` companion metric (added 2026-10-02, in `engine.py` not `dividends.py`, see [§8.4](kb:valuation-models)).** A high grossed-up yield on its own can't distinguish a genuinely strong, sustainable dividend from a one-off special distribution. Found in practice at 500-ticker scale: Tower Limited (TWR) showed a 106.85% grossed-up yield driven by a single `FY` where `dividends_per_share` ($1.1930) was 519% of that year's `eps` ($0.2300), three prior years all showed normal 12-82% payout ratios, making FY2025 a clear outlier consistent with a special dividend or capital return, not ordinary income. `payout_ratio = (dividends_per_share / eps) * 100` is now stored alongside the yield and surfaced in `screen_asx.py`'s output with a `>150%` warning (the user explicitly chose "flag, don't hide" over nulling the yield out or leaving it unaddressed). Same `NUMERIC(6,2)` overflow risk as `margin_of_safety_percent` (near-zero/negative EPS against a real dividend), guarded with the same "return `None` past a sanity threshold" pattern rather than crashing.

### `graham.py`, Graham Number

```
Graham Number = sqrt(22.5 × EPS × BVPS)
```

`book_value_per_share()` computes `BVPS = total_equity / shares_outstanding`. Returns `None` (not zero, not an exception) whenever EPS or BVPS is `≤ 0`, since Graham's method is explicitly undefined for loss-making or negative-equity companies.

### `dcf.py` / `ddm.py`, Two-Stage DCF and Dividend Discount Model

**`dcf.py`, Two-Stage DCF** (used for most sectors):
- **Stage 1:** grows the latest `free_cash_flow` at `growth_rate` for `stage1_years` (default 5), discounting each year at `discount_rate`
- **Stage 2:** Gordon Growth terminal value on the final stage-1 FCF, grown at `terminal_growth_rate` in perpetuity, discounted back `stage1_years` periods
- **Equity value** = PV(stage 1) + PV(terminal) + cash − total debt
- **Intrinsic value per share** = equity value / shares outstanding

Defaults: `growth_rate = 8%`, `discount_rate = 9%` (task spec's 8–10% baseline, midpoint chosen), `terminal_growth_rate = 2.5%`, `stage1_years = 5`. All four are CLI flags on `run_valuation.py`, nothing is hardcoded without an override path.

**Validity guard:** raises `ValueError` if `discount_rate ≤ terminal_growth_rate` (the perpetuity formula diverges otherwise).

**Sanity guard on `margin_of_safety_percent()`** (added 2026-10-02, IMP-012): returns `None` rather than a wild, DB-overflowing percentage when `dcf_intrinsic_value` is implausibly small relative to price. Found in practice at 500-ticker scale, a micro-cap produced a −128,521.87% "margin of safety," which crashed the entire valuation run until this guard (and the per-company isolation below) were added.

**`ddm.py`, Two-Stage Dividend Discount Model** (added 2026-10-02, IMP-008; used only for Financial Services / Real Estate, see [§8.4](kb:valuation-models) for the sector routing logic):
- Same two-stage mechanics as `dcf.py` (stage-1 explicit growth for `stage1_years`, then a Gordon Growth terminal value), substituted onto `dividends_per_share` instead of `free_cash_flow`:
  `PV(stage1) = Σ D·(1+g)^t / (1+r)^t`, terminal value on the final stage-1 dividend, discounted back the same way.
- **Intrinsic value per share** = PV(stage 1) + PV(terminal), directly a per-share figure, with **no separate cash/debt netting and no `shares_outstanding` input**: dividends are already paid out of post-tax, post-financing earnings, so there's nothing left to add back or net off, and this path doesn't carry the shares-outstanding estimation risk flagged in IMP-003.
- Defaults: `growth_rate = 5%` (dividend growth is typically steadier/lower than FCF growth, a deliberate difference from `dcf.py`'s 8% default), `discount_rate = 9%`, `terminal_growth_rate = 2.5%`, `stage1_years = 5`. Reuses the same `--growth-rate`/`--discount-rate`/`--terminal-growth-rate`/`--stage1-years` CLI flags as the DCF path (see [§14](kb:review-hotspots) for the deliberate simplification this represents, one global assumption set, not a second set of per-sector CLI flags).
- **Why dividends instead of FCF for these sectors:** banks, insurers and REITs routinely report negative or highly volatile "free cash flow" under the standard operating-CF-minus-capex definition, because loan book movements, policy reserve movements and property revaluations dominate it rather than the kind of reinvestment capex the DCF model assumes (confirmed in practice, see [§10.6](kb:testing-and-validation)'s note on CBA). Dividends are the natural analogue: these are dividend-driven business models almost by definition, and typically pay out a high, relatively stable share of earnings.
- Same multi-year averaging as the DCF's FCF base: `_average_dividend_per_share()` in `engine.py` uses the mean `dividends_per_share` across the same `fcf_average_years` window, for the same single-year-volatility reasons documented in [§8.4](kb:valuation-models) for the DCF (and consistent with the `payout_ratio` warning in [§8.1](kb:valuation-models) for a special-dividend year).
- Returns `None` if the base dividend is `≤ 0` (a non-dividend-paying financial/REIT correctly gets no DDM intrinsic value rather than a fabricated one), same "skip rather than fabricate" philosophy used everywhere else in this codebase.

### `engine.py`, Orchestration

For each company: pulls the latest `daily_prices` row and the last `fcf_average_years` (default 3) `financial_reports` rows (`period_type = 'FY'` only, half-year reports are stored but not currently used in valuation), computes every `valuation_metrics` column, and upserts via `INSERT ... ON CONFLICT (company_id, as_of_date) DO UPDATE`.

**Sector-aware DCF-vs-DDM routing** (added 2026-10-02, IMP-008, resolved): `compute_metrics()` checks `company.sector` against `_SECTOR_AWARE_SECTORS = {"Financial Services", "Real Estate"}` (spelled exactly as yfinance's `.info["sector"]` returns them for ASX companies) and picks the model accordingly, `ddm.two_stage_ddm()` for those two sectors, `dcf.two_stage_dcf()` for everything else. Both write into the same `dcf_intrinsic_value` column (no schema duplication), with a new `valuation_method` column (`'DCF'` / `'DDM'` / `NULL`) recording which one actually ran, so the screener and any downstream review can tell the two kinds of number apart rather than treating every `dcf_intrinsic_value` identically. `margin_of_safety_percent()` is computed identically either way, it only needs an intrinsic value and a price, not which model produced the intrinsic value.

**`growth_rate` defaults per-model when not explicitly set on the CLI.** `compute_metrics()`'s `growth_rate` parameter defaults to `None`, not a fixed value: when `None`, it resolves to `ddm.DEFAULT_GROWTH_RATE` (5%) for sector-aware companies or `dcf.DEFAULT_GROWTH_RATE` (8%) otherwise, reflecting that sustained dividend growth is typically a more conservative assumption than FCF growth. Passing an explicit `--growth-rate` on `run_valuation.py` overrides this and applies uniformly to whichever model runs for a given company, same as before. `discount_rate`, `terminal_growth_rate` and `stage1_years` are shared across both models unconditionally (no per-sector default), only the stage-1 growth assumption was judged to need a different starting point by sector; see [§14](kb:review-hotspots), item 7 for the design trade-off this represents.

**Why this was needed, the CBA finding ([§10.6](kb:testing-and-validation)), generalised.** The first live run already showed CBA getting a `NULL` margin of safety because its `free_cash_flow` wasn't meaningfully positive under the standard DCF definition, correctly skipped rather than fabricated, but it meant **every** Financial Services and Real Estate company would silently never get a margin-of-safety figure, a real coverage gap for a value screener (banks, insurers and REITs are a meaningful slice of the ASX). The fix doesn't change the "don't fabricate" philosophy, it changes which input the model is built on for these sectors, since dividends (not FCF) are the value driver that actually behaves sensibly for them.

**Validated with synthetic data** (not live, since this needs a specific sector/FCF combination that's awkward to guarantee from a live sample): seeded a synthetic bank (Financial Services sector, `free_cash_flow` negative in every one of 4 years, realistic for a bank's loan-book-dominated operating cash flow, but a real, growing 4-year dividend history) against a disposable PostgreSQL instance alongside a synthetic miner (ordinary sector, positive FCF, as a control). Confirmed: the bank correctly got `valuation_method = 'DDM'` with a real, non-`NULL` margin of safety (37.26% in the test data) where the old code would have left it `NULL`; the miner correctly got `valuation_method = 'DCF'`, completely unaffected by the change. Both appeared correctly in `screen_asx.py`'s output, with the new `valuation_method` column distinguishing them.

**Per-company isolation and incremental commits** (added 2026-10-02, IMP-013): `run_valuation()` now commits after each company rather than once at the end, and wraps each company in its own try/except. Before this fix, a single company's unhandled exception anywhere in the batch would lose every other company's already-computed work too, since nothing had been committed yet, this is exactly what happened on the first 500-ticker run, before the margin-of-safety guard above existed. Matches the ingestion layer's existing per-ticker isolation pattern ([§7.3](kb:ingestion)).

**Generic column-overflow guard on every field, not just margin_of_safety_percent/payout_ratio** (added 2026-10-02, IMP-015): `upsert_valuation_metric()` now runs every field through `_clamp_to_column_precision()` immediately before the insert, nulling (and logging) any value whose magnitude would overflow its target `NUMERIC` column, derived directly from the column definitions in `db/schema.sql`, rather than crashing. This exists because the failure mode turned out not to be isolated to the two fields first found: at 500-ticker scale, `BRN`'s `roic` hit 10,129.90% (over `NUMERIC(6,2)`'s 9999.99 limit) and `WHI`'s `pb_ratio` hit ~203 million (over `NUMERIC(10,2)`'s ~100 million limit) with `roe` simultaneously at 134,600%, both crashed their company's entire valuation row despite the crash-isolation fix (#13) correctly containing the damage to just those two companies. The margin_of_safety_percent/payout_ratio guards ([§8.3](kb:valuation-models), [§8.1](kb:valuation-models)) keep their tighter, business-meaningful 5000% sanity threshold and are unaffected by this change; this is an additional, purely mechanical backstop covering every other field. Validated by replaying both companies' exact failing payloads from their crash tracebacks against a live PostgreSQL instance: both now upsert successfully, with only the pathological field nulled and every other valid field (e.g. BRN's `pe_ratio`, `pb_ratio`, `roe`) preserved.

**`upsert_valuation_metric()` returns the post-clamp metrics, and callers use that return value** (added 2026-10-02, same-day follow-up). Caught directly in the user's own live run: the re-run after the guard above landed still printed `WHI: ... ROE=134600% ...` in `run_valuation.py`'s console summary, even though the database correctly stored `NULL` for that field, because `run_valuation_for_company()` was returning the pre-clamp `metrics` dict it already had, not the clamped one `upsert_valuation_metric()` computed internally and discarded. Not a data bug (the database was always correct), but a real console-vs-database inconsistency that could mislead anyone reading terminal output without cross-checking the DB. Fixed by having `upsert_valuation_metric()` return the clamped dict and `run_valuation_for_company()` return *that*, so `results` (and therefore every logger line, and any future caller) is guaranteed to match what's actually stored. Validated end-to-end: a company engineered to overflow `roe` now shows `None` in both the returned dict and a direct database query, where it previously showed the raw overflowing value in one and `NULL` in the other.

**Shares outstanding** is not a schema column. It is derived as `market_cap / close_price` from the latest price row, falling back to `net_profit_after_tax / eps` if market cap is unavailable. This value feeds BVPS (→ Graham Number), FCF-per-share (→ price-to-FCF), and the DCF's per-share conversion, **it is the single most consequential derived value in the entire valuation layer**, worth prioritising in any design review.

**DCF free cash flow base is a multi-year average, not just the latest year** (added 2026-10-02, after the SUN finding below). `gather_inputs()` fetches the last `fcf_average_years` `FY` reports (default 3) and `compute_metrics()` uses the simple mean of their `free_cash_flow` values as the DCF's starting point, gracefully averaging over however many years actually have a value (1, 2, or 3+), and returning `None` only if none do. **Every other metric** (ROE, D/E, P/E, P/B, EV/EBIT, dividend yield, Graham Number) still uses only the single latest `FY` report, this is a point-in-time ratio snapshot in every case *except* the DCF, which specifically needed smoothing.

**Why this exists, the SUN case study.** Live-testing against Suncorp Group (SUN) surfaced the problem directly: its reported `free_cash_flow` across FY2023–FY2026 was $742M / $2,497M / $2,550M / $1,585M, a 3.4x swing across 4 years. With the original single-year-only DCF base (the latest year, $1,585M), the computed margin of safety swung from **+34.45% to −9.84%** depending only on which growth/discount-rate scenario was tested (8%/9% vs 3%/11%), the entire conclusion was an artefact of which year happened to be "latest," not a robust read on value. Averaging over 3 years (→ a $2,210.67M base) produces a materially more defensible number. This is logged as resolved against IMP-004's residual risk ([§11](#/admin/kb/register)) and is the direct fix for what's now issue #9.

`--fcf-average-years 1` on the CLI reproduces the old single-year behaviour exactly, for anyone who wants to compare or who has a specific reason to weight only the most recent year.

**`current_ratio` is hardcoded to `None`**, the schema has no current-assets/current-liabilities split (only `total_assets`/`total_liabilities`), so a genuine current ratio cannot be derived. This is a deliberate "don't fabricate a number" decision, not a bug.

A company with no price row or no `FY` financial report is skipped entirely (logged as a warning), never valued with partial/garbage inputs.

### `run_valuation.py`, CLI

```
python -m src.valuation.run_valuation (--all | --tickers BHP CBA) [--growth-rate D] [--discount-rate D] [--terminal-growth-rate D] [--stage1-years N] [--fcf-average-years N] [--trend-days N]
```

## Code map

- `src/valuation/engine.py`: orchestration: picks DCF or DDM by sector, computes every metric, clamps values that would overflow
- `src/valuation/dcf.py`: two-stage discounted cash flow
- `src/valuation/ddm.py`: two-stage dividend discount model
- `src/valuation/graham.py`: Graham Number
- `src/valuation/dividends.py`: grossed-up (franked) dividend yield
- `src/valuation/run_valuation.py`: the command the nightly job runs
- `src/settings.py`: the live settings the models use

## Data

- `valuation_metrics`: one row per company per valuation date: estimated value, method, ratios, trends, markers

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Margin of safety blank for a company with data: free cash flow (DCF) or dividends (DDM) aren't positive across the averaging years. Check `valuation_metrics.valuation_method`; blank means neither model could run, by design.
- A bank, insurer or REIT has no value: check `companies.sector` is spelt exactly 'Financial Services' or 'Real Estate'.
- A figure is blank and the log says it was clamped: the value would have overflowed its column; the inputs are usually a bad share count (IMP-003).

## Known limits

- One global set of growth and discount assumptions for every company.
- The DCF base is a simple 3-year mean, which a structural break distorts.
- Settings change only in code; what-if scenarios try alternatives without touching live values.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_dcf.py`
- `tests/unit/test_ddm.py`
- `tests/unit/test_graham.py`
- `tests/unit/test_dividends.py`
- `tests/unit/test_franking.py`
- `tests/unit/test_engine.py`
- `tests/integration/test_valuation_pipeline.py`
