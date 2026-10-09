---
id: ingestion
title: Ingestion: prices, annual reports and dividends
category: features
summary: How Sift downloads prices, annual statements, dividends and company profiles from Yahoo Finance each night, and keeps one bad ticker from spoiling the run.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2026-11-09
source: AS_BUILT §7, §28
related: [data-sources, nightly-run, valuation-models, adr-003-yahoo-data-source]
code: [src/ingestion/yahoo_client.py, src/ingestion/price_ingestion.py, src/ingestion/fundamentals_ingestion.py, src/ingestion/dividend_history.py, src/ingestion/currency.py, src/ingestion/common.py, src/ingestion/rolling.py, src/ingestion/run_ingestion.py]
tables: [companies, daily_prices, financial_reports, dividend_payments]
---

> Migrated from the early as-built record (October 2026). Parts of How it works describe the command line as first built; the review due in November checks it against today's code (IMP-037).

## Purpose

Ingestion is the only place market data enters Sift. It fetches daily prices, annual financial statements, dividend payments and company descriptions for every ticker in the nightly ticker file, converts statements into the share price's currency, and stores them so valuation can run on consistent inputs.

## How it works

### Ingestion Layer (`src/ingestion/`)

### `yahoo_client.py`, External I/O Boundary

All Yahoo Finance / `yfinance` calls are isolated in this one module. Nothing else in the codebase talks to the network directly.

- `to_yahoo_symbol(asx_code)`, appends `.AX` if not already present
- `YahooClient.get_profile()`, company name / sector / industry / country (used when creating a new `Company` row, and once per existing company to backfill `country`)
- `YahooClient.get_price_history(period)`, daily close/volume/market-cap bars; market cap is derived as `close_price × sharesOutstanding` (from `yfinance`'s `.info`) since Yahoo's history endpoint doesn't return market cap directly
- `YahooClient.get_annual_fundamentals(max_years)`, pulls income statement, balance sheet, and cash flow statement (annual frequency), maps Yahoo's field names onto our schema's columns
- `YahooClient.get_fx_history(from, to, start, end)`, daily exchange-rate closes (e.g. `USDAUD=X`) for currency conversion ([§7.7](kb:ingestion)); `get_profile()` also returns `trading_currency` (`info["currency"]`) and `financial_currency` (`info["financialCurrency"]`)
- `YahooClient.get_dividend_payments()`, every per-share dividend payment from `ticker.dividends` (ex-date, amount), raw. Financial-year matching and abnormal-distribution exclusion happen in `dividend_history.py` ([§7.6](kb:ingestion)). Replaced `get_dividends_per_share(fiscal_year)`, which summed by calendar year (2026-10-05)

**Every method here is defensive**: wrapped in `try/except Exception`, logs and returns `None`/`[]`/`{}` rather than raising, because Yahoo's field availability is inconsistent across companies and changes without notice. This was a deliberate design decision, not an oversight, see [§8.2](kb:valuation-models).

**Field mapping is best-effort.** Example: `free_cash_flow` is read directly from Yahoo if present, otherwise derived as `Operating Cash Flow + Capital Expenditure` (Yahoo reports capex as an already-negative outflow). `total_debt` falls back to `Long Term Debt + Current Debt` if Yahoo's consolidated `Total Debt` field is absent.

**Not sourced from Yahoo at all:** franking percentage, corporate tax rate. Yahoo has no concept of Australian franking credits. These are defaulted in `fundamentals_ingestion.py` (see below), using Yahoo's reported `country` to set foreign-domiciled companies to 0% franked (added 2026-10-05).

### `common.py`, `get_or_create_company()`

Looks up a `Company` by `asx_code`; if absent, creates one using `YahooClient.get_profile()` data (falling back to the bare ASX code as the company name if the profile fetch fails). Called by both ingestion modules before fetching prices/fundamentals, **this means a `Company` row can exist with no price or financial data at all**, if the network call for profile succeeded (or even failed with a fallback name) but the subsequent price/fundamentals call failed. This was observed directly during testing (see [§10.2](kb:testing-and-validation)) and is handled correctly downstream by `engine.py` (skips companies with incomplete data rather than erroring).

**`ensure_country()` (added 2026-10-05):** backfills `companies.country` for rows created before the column existed. Called from fundamentals ingestion only (not prices-only runs), it costs one profile request per company, once; a company Yahoo reports no country for stays `NULL` and is retried next run.

### `price_ingestion.py`

`ingest_daily_prices(session, asx_codes, period, delay_seconds)`, for each ticker: get-or-create the company, fetch the price history, and `INSERT ... ON CONFLICT (company_id, price_date) DO UPDATE` each bar. On conflict, `close_price`, `volume`, and `market_cap` are all overwritten with the new fetch's values (no coalescing, a price is a fact-for-that-day, so the newest fetch should always win).

**Per-ticker isolation (added 2026-10-02):** each ticker's processing is wrapped in its own `try/except`, an unexpected failure (network blip, malformed response, DB error) is logged via `logger.exception` (full traceback) and `session.rollback()`'s that ticker's partial work, then the loop continues to the next ticker rather than aborting the whole run. This matters once `asx_codes` is large: hitting at least one edge-case ticker over a few hundred is likely, and losing the rest of the batch to one bad ticker would be a costly failure mode. Validated directly: a simulated crash on ticker 2-of-4 was caught and logged, the batch continued to tickers 3 and 4, and the database ended up with exactly the 3 successful companies and no orphaned/partial row for the failed one (the `session.rollback()` cleanly undoes that ticker's `get_or_create_company()` flush too).

`delay_seconds` sleeps between tickers to reduce the chance of Yahoo's informal rate limiting on a large batch (there's no officially documented limit to tune against, this is a precaution, not a guarantee).

### `fundamentals_ingestion.py`

`ingest_fundamentals(session, asx_codes, max_years, delay_seconds)`, same get-or-create pattern, per-ticker isolation, and delay pacing as `price_ingestion.py` above, then `INSERT ... ON CONFLICT (company_id, fiscal_year, period_type) DO UPDATE`.

**Important design decision:** on conflict, most numeric columns use `COALESCE(excluded.col, financial_reports.col)`, i.e. **a `NULL` from a fresh fetch never overwrites a previously-stored value**. This guards against a partial/flaky Yahoo response silently wiping out previously good historical data on a re-run. `franking_percentage` and `corporate_tax_rate` are the exception: they are resolved to explicit defaults (`100.0` / `30.0`) in Python *before* the insert if Yahoo doesn't supply them (which it never does), so they are never `NULL` going in and the coalesce question doesn't arise for them.

**Franking by domicile (added 2026-10-05, IMP-002):** `franking_percentage_for()` sets 0% for any company whose `country` is known and isn't Australia (NZ, US, Irish and other foreign listings pay no Australian franking credits), otherwise the 100% default. For foreign companies the on-conflict update also writes `franking_percentage`, so years stored at the old 100% default are corrected on the next run. Australian rows are deliberately left alone on update so a hand-corrected partial franking figure survives re-ingestion.

### `run_ingestion.py`, CLI

```
python -m src.ingestion.run_ingestion (--tickers BHP CBA CSL | --tickers-file watchlist.txt | both) [--period 1y] [--prices-only | --fundamentals-only] [--max-years N] [--delay SECONDS]
```

**`--tickers-file`** (added 2026-10-02) reads ASX codes from a plain text file, one or more per line, whitespace- or comma-separated, blank lines and `#`-comments ignored. This exists specifically for large watchlists (e.g. a full index's constituents) where typing hundreds of codes on the command line isn't practical. `--tickers` and `--tickers-file` can be combined; the combined list is deduplicated case-insensitively, preserving first-seen order. Validated directly against a sample file mixing comma-separated, whitespace-separated, commented, and duplicate (differently-cased) entries, all parsed and deduplicated correctly.

**`--delay`** (added 2026-10-02), see [§7.3](kb:ingestion).

### `dividend_history.py`, ordinary dividends per financial year (added 2026-10-05)

Pure functions that turn the raw payment list into `financial_reports.dividends_per_share` and the new `abnormal_distributions_per_share`. Found on Tower (TWR), whose 519% payout ratio was real arithmetic on bad input.

- **Abnormal distributions.** For each payment, the "typical annual dividend" is the median of the trailing-twelve-month totals at every other payment within three years of it. A payment more than `ABNORMAL_DISTRIBUTION_MULTIPLE` (2) times that is abnormal: excluded from `dividends_per_share` and summed into `abnormal_distributions_per_share`. Needs at least 2 comparable payments, otherwise nothing is excluded. Using annual totals rather than individual payments means an uneven split (a 2c interim and a 10c final) is not mistaken for a one-off. Tower's A$1.0777 capital return (1 in 10 shares cancelled, recorded by Yahoo against every share) is about ten times its usual year and is excluded; its 15c final dividend is not.
- **Financial-year matching.** A financial year takes ex-dates in the twelve months ending `FY_DIVIDEND_LAG_MONTHS` (4) after its balance date: the interim paid during the year plus the final paid after it, for June, September and December year-ends alike; quarterly payers still total twelve months. If that window hasn't closed, it falls back to the twelve months to today.
- **Zero versus missing.** A company with any dividend history that paid nothing in a year now gets 0, not NULL. Because `dividends_per_share` is in `_COALESCE_ON_UPDATE`, a NULL would have kept a stale stored figure; a 0 overwrites it. NULL now means no dividend history at all.
- **Scope of the correction.** Applied on the next fundamentals ingestion to every year Yahoo returns (the latest four). An older stored fifth year keeps its calendar-year figure; it only feeds `dividend_trend`'s oldest point.
- **Surfaced, not silent.** The web GUI's dividend card states any excluded amount and lists it in its data table.

### `currency.py`, statements in the share price's currency (added 2026-10-05, IMP-025)

- **The problem.** Yahoo returns each company's statements in its reporting currency (`info["financialCurrency"]`): USD for most large miners, NZD for NZ listings. Prices are in the trading currency (`info["currency"]`, AUD on the ASX). Nothing converted between them, so a US-dollar EPS or free cash flow was set against an Australian-dollar price.
- **Where it's fixed.** At ingestion, so everything downstream (engine, view, screener, GUI) works in one currency without change. `ensure_profile()` (`common.py`, replacing `ensure_country()`) backfills `companies.trading_currency` and `financial_currency` once per company; a profile without a statements currency means statements in the trading currency. `fundamentals_ingestion.convert_to_trading_currency()` fetches the daily exchange-rate history once per company (`YahooClient.get_fx_history()`, e.g. `USDAUD=X`) and `currency.apply_conversion()` multiplies every statement field (`MONETARY_FIELDS`: revenue through net tangible assets, including EPS) by the rate on each report's own balance date: the last close on or before it, no more than 10 days old (balance dates often fall on weekends).
- **Not converted.** `dividends_per_share` and `abnormal_distributions_per_share`: Yahoo's dividend feed is already per share in the trading currency.
- **Recorded.** `financial_reports.reporting_currency` and `fx_rate` say what was done (rate 1 for same-currency companies). The GUI's Key ratios panel shows it.
- **Failure is loud, not silent.** No usable rate raises `CurrencyConversionError`; per-ticker isolation logs it and skips that company's fundamentals for the run, rather than storing figures in the wrong currency.
- **Currencies with no direct pair (added 2026-10-07, IMP-036).** Yahoo has no `PGKAUD=X`, so the three ASX companies reporting in Papua New Guinea kina (BFL, KSL, SST) failed every night. `get_fx_history()` now tries the direct pair, then chains through the US dollar: kina to USD (`PGKUSD=X`, else the inverse of `USDPGK=X`, else the inverse of `PGK=X`, Yahoo's USD-to-kina quote), times USD to AUD (`currency.cross_rates()`, each date taking the second leg's latest rate on or before it). yfinance's own "possibly delisted" errors are silenced while probing, since a missing symbol is expected.
- **When there's still no rate.** The company's stored statements stay as they were, `companies.statements_issue` records why, and the company isn't stamped as fetched, so it's retried every night. While the flag is set the engine sets `data_confidence` to `LOW`, which is a red flag, so the company can't be a BUY (at most INVESTIGATE). The company page shows a note saying the latest statements couldn't be stored. A successful fetch clears the flag. The company and its profile are committed before the statements are processed, so a new company is kept even when its statements fail.
- **Scope.** Applied on the next fundamentals ingestion to the four years Yahoo returns. An older stored fifth year stays unconverted; only its dividend (already in AUD) is used, by `dividend_trend`.
- **Residual effect.** Each year converts at its own rate, so `fundamentals_trend`'s revenue change is in AUD and includes currency movements. ROE, ROIC, cash conversion and debt/equity are ratios within one year and unaffected.

### Company Descriptions

Each company page shows what the company does, under the sector, industry and country line.

- **Source.** Yahoo Finance's business summary (`longBusinessSummary`), read with the rest of the company profile and stored in `companies.business_summary`.
- **When it's filled.** A new company gets it when it's first added. Existing companies get it on the next nightly run: `ensure_profile()` fetches the profile once for any company without one, the same way country and currencies were backfilled. `NULL` means not fetched yet; `''` means Yahoo has none, so it isn't asked for again every night. A failed fetch leaves it `NULL` to retry.
- **What's shown.** The first two sentences (`short_summary()` in `gui.py`, `SUMMARY_SENTENCES = 2`), with **more** to read Yahoo's full text and **less** to fold it again. Full stops after common abbreviations (Ltd., Pty., Inc., Mt., e.g., U.S.) don't count as sentence ends. A summary of two sentences or fewer is shown whole with no link. No summary, no paragraph.
- **Scope.** Shares only. ETF and LIC pages are unchanged.

## Code map

- `src/ingestion/yahoo_client.py`: the only module that talks to Yahoo Finance (through yfinance); maps Yahoo's field names to Sift's
- `src/ingestion/price_ingestion.py`: daily prices, upserted per company
- `src/ingestion/fundamentals_ingestion.py`: annual statements; a blank fetch never overwrites a stored figure
- `src/ingestion/dividend_history.py`: ordinary dividends per financial year, one-offs held out
- `src/ingestion/currency.py`: statements converted into the trading currency at each balance date's rate
- `src/ingestion/common.py`: get_or_create_company() and company descriptions
- `src/ingestion/rolling.py`: the weekly refresh rule: a seventh of the shares each night
- `src/ingestion/run_ingestion.py`: the command the nightly job runs

## Data

- `companies`: one row per ASX code, with sector, currency and when statements were last fetched
- `daily_prices`: one close per company per day
- `financial_reports`: one row per company per financial year
- `dividend_payments`: every payment with its ex-date; abnormal (one-off) ones flagged

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Every ticker returns nothing, with 'Cookie/crumb fetch failed' in the log: Yahoo can't be reached from this machine. See [Nightly run failed](kb:rb-nightly-run-failed).
- ROE, debt to equity or margin of safety suddenly blank for many companies: Yahoo renamed its fields. See [Yahoo fields changed](kb:rb-yahoo-fields).
- One company's figures look wildly off: check its reporting currency (`companies.financial_currency`) and its rows in `financial_reports`.

## Known limits

- Yahoo Finance is unofficial and changes without notice (IMP-004).
- Shares outstanding is derived from market value and price, not stored (IMP-003).
- Franking defaults to 100% for Australian payers, 0% for foreign ones; partly franked payers need a manual correction (IMP-002).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_yahoo_prices.py`
- `tests/unit/test_currency.py`
- `tests/unit/test_fx_routes.py`
- `tests/unit/test_dividend_history.py`
- `tests/unit/test_rolling.py`
- `tests/unit/test_company_summary.py`
- `tests/integration/test_ingestion.py`
