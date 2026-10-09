---
id: etfs-collection
title: ETFs and LICs: collecting the data
category: features
summary: How the ASX's monthly investment products report, prices and distributions are collected for every ETF and LIC, and how Sift calculates their returns.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §25
related: [etfs-presentation, lics, data-sources]
code: [src/etf/asx_report.py, src/etf/prices.py, src/etf/performance.py, src/etf/run_etfs.py]
tables: [etf_monthly, etf_performance, asx_report_loads, asx_index_returns]
---

## Purpose

ETFs and LICs are collected beside shares but never valued or scored as companies; their facts come from the ASX's own monthly report and their returns are calculated by Sift.

## How it works

**Purpose.** Bring every ASX exchange traded fund into the database alongside the shares: which ETFs exist and their fund facts each month, their daily prices and distributions with full history, and their performance over 1 month to 10 years. Stage 1 of four agreed with the user: (1) collect, (2) an ETF screener, page per ETF, watchlists and portfolio pricing, (3) AMIT cost base adjustments in the CGT records, (4) look-through value for Australian share ETFs. Stages 2 to 4 are not built yet.

**Model.**
- `companies.security_type` is `SHARE` (default) or `ETF` (checked by the database). ETFs live in `companies` so they share `daily_prices`, `dividend_payments`, watchlist entries and holdings with shares. The ticker is the code plus `.AX`; trading and statement currency AUD.
- `etf_monthly`: one row per ETF per report month, kept for good: fund name, issuer, product type, category and sub-category, benchmark, MER, fund size, net flows, average spread, value traded, distribution yield and frequency, listing date, the report's own 1, 3 and 6-month and 1, 3, 5 and 10-year and since-inception returns, the source file, and `raw` (every column of the row as written, so nothing the ASX publishes is lost if a heading isn't recognised). Percents are whole-number percents (0.07 = 0.07%), money in AUD.
- `etf_performance`: one row per ETF, recalculated nightly: Sift's own total returns for the same periods, distributions in the last 12 months and the trailing yield, the first price date, and the check against the report (below).

**The ETF list: the ASX Investment Products report (`src/etf/asx_report.py`).**
- **Source.** The ASX's monthly report, a spreadsheet published by about the seventh business day of the next month, listing every exchange traded product.
- **Getting it (`ensure_latest`).** Each night, until last month's report is loaded: the newest spreadsheet in `data/asx_reports/` (gitignored) newer than what's loaded, so a file saved by hand is used first; otherwise the report page is read for its spreadsheet links and the newest one downloaded; if the page can't be read, the expected addresses for the last two months are tried (the PDFs live under `/content/dam/asx/issuers/asx-investment-products-reports/<year>/pdf/`; the spreadsheet folder is assumed alongside). Downloads use `curl_cffi` (installed with yfinance) with a browser fingerprint. Once last month's report is loaded, no request is made until the next month. Not available yet is logged as INFO until the 15th, then as a WARNING; neither turns the dashboard's run status red.
- **Reading it.** The layout isn't a published format, so nothing depends on fixed rows or columns. ETP sheets are picked by name (LIC, LIT, mFund, A-REIT and infrastructure sheets skipped). The heading row is the first with an ASX code column; a group heading above (a merged "Performance" over "1 Month", "1 Year") is carried into each column's label, and a sub-heading row below is picked up too. A column's own heading decides its field; a bare period ("1 Year") or an unrecognised heading takes its meaning from the group heading, so "1 Year" under Flows is a flow and under Performance a return. Percents come from the cell's percent format; a column that isn't percent-formatted with every value at or below a fraction limit (0.05 for fees and spreads, 0.3 for yields, 1.5 for returns) is multiplied by 100. Money is scaled by its label ($m, $b, $000), and a fund size column with no unit but a median under $100,000 is read as millions. Rows need a code written in capitals (so Total and Average rows drop out) and a product type that isn't an LIC, LIT or mFund.
- **Loading it (`load_report`).** Every ETP becomes or stays an ETF (a code already known as a share is reclassified, with a WARNING), and gets that month's `etf_monthly` row; re-loading a month replaces it. When the report is the newest loaded, active ETFs it no longer lists are marked inactive (their history stays) and returning ones reactivated.
- **Checking a file.** `python -m src.etf.run_etfs --inspect FILE` prints each sheet's heading row, every column's label and the field it was matched to, notes on scaling, fields not found and three sample rows, without loading anything. `--report FILE [--month YYYY-MM]` loads a file by hand.

**25.1 The real report (July 2026, supplied by the user).** `asx-investment-products-july-2026-abs.xlsx` has six sheets: Spotlight ETPs (summary), Spotlight ETPs Issuers, **Spotlight ETP List** (the one read), Spotlight LIC List, Spotlight A-REITS List and Spotlight Infra List. The list starts in column B under seven blank rows, a title row and a group row (IRESS Watchlist, Activity, Prices, Returns), with headings on row 10: ASX Code, Type, Issuer, Fund Name, MER (% p.a), FUM ($m), FUM change, Funds inflow/outflow ($m), 12-month flows, CHESS FUM and flows, Transacted value ($), volume, trades, monthly liquidity %, % Spread, Last ($), Historical distribution yield, and 1-month, 1-year, 3-year and 5-year total returns (no 10-year). What the reader does with it:
- **Categories** are section rows between the funds (Equity - Australia, Equity - Global Strategy, Fixed Income - Australia Dollar, Cash, Crypto Assets and so on, 20 in all), not a column; a row with a single piece of text sets the category for the funds below it.
- **Types** are ETF, Active, Complex and SP, shown as ETF, Active ETF, Complex ETF and Structured product. The last section, Australian Indices, lists benchmark indices with type Index: these are left out.
- **"^"** in column A marks a fund that invests in other ASX ETFs; it's kept (`raw["Invests in other ETFs"]`) and shown on the ETF's page.
- **Units:** MER is a percent (0.07); spread, yield and returns are plain fractions (0.0737 for 7.37%); FUM and flows are in $m; transacted value in dollars. Fractions are now detected on the median value, with all the return columns judged together, so a fund's 115% year (there is one) can't stop the scaling.
- **Returns** are from Bloomberg with dividends reinvested gross, that is including franking credits, so for franked Australian funds the ASX's figures run above Sift's cash-only returns. The ETF's page shows both side by side (an "ASX report" column), and the check note says so.
- **Footnotes** after the list are single-cell rows after the last fund and change nothing.
- Result: 457 ETPs (274 ETF, 130 Active, 47 Complex, 6 Structured product), 27 investing in other ETFs. VAS reads as $26.2 billion, 0.07% fee, 2.93% yield, 6.71% 1-year and 9.06% 5-year return. A replica of the layout (`build_asx_2026` in `tests/unit/_etf_report.py`) keeps this tested without committing the ASX's file.

**25.2 Loading a month again when the reader improves.** The nightly step only fetches a *newer* month, so a month loaded before the reader learnt something new (LICs, [§27](kb:lics)) would have stayed without it until the next report. `asx_report_loads` records which reader version (`READER_VERSION`, now 3) loaded each month; `ensure_latest()` first calls `reload_if_outdated()`, which loads the newest month again from its file in `data/asx_reports/` if an older reader loaded it (or if it was loaded before versions were recorded). Without the file it logs a WARNING saying to save it there or run `--report`. Found when the user reported "LICs are missing" after loading the July report before the LIC update.

**Every saved month is loaded (`load_folder`).** The user keeps each month's file (January to August 2026, named like `asx-investment-products-aug-2026-abs.xlsx`, July as `july`). The nightly step now loads every report in the folder that isn't loaded yet (or was loaded by an older reader), oldest first, before looking for a newer one online, so fund size and NTA history start with eight months rather than one. Only the newest month loaded changes which funds exist, their type and names, and which are active: an older month adds its rows for history, and a fund only it lists is added as inactive. Excel lock files (`~$...`) are ignored and a file that can't be read is logged and skipped.

**Prices and distributions (`src/etf/prices.py`).** One Yahoo request per active ETF brings closes, splits and distributions. An ETF with no stored prices gets its full history (the one-off backfill behind the 10-year returns); after that, the last month. Distributions go into `dividend_payments` with none held out as abnormal (a fund's year-end distribution of gains is part of its return, unlike a company's one-off). Prices are written a thousand rows per statement.

**Prices are now stored as traded, for shares too.** yfinance's default (`auto_adjust=True`) scales every earlier close down by each later dividend. Fetched a month at a time, that left the stored history with a step at each ex-date (the month before it scaled down, everything older not), and a total return built from such closes plus distributions would count distributions twice. `YahooClient.get_price_history()` now asks for `auto_adjust=False`: closes are split-adjusted only. The track record was unaffected in practice (its start price is the snapshot price and its end price is fetched within days of the horizon, both effectively unadjusted), but charts, the 52-week range and the 200-day average carried the steps. Existing share history keeps them until refetched (IMP-031).

**Splits (`fetch_bars`, shares and ETFs).** A split changes every earlier split-adjusted close. When a fetch includes a split and the stored close before it no longer matches the fetched one (more than 1% apart), the stored prices are deleted and the full history refetched; for an ETF its distributions are replaced too. The check means it happens once, not every night the split stays in the month's window.

**Performance (`src/etf/performance.py`).**
- **Total return:** one unit bought at the close on the start date (the last close on or before it), each distribution reinvested at the close on its ex-date (or the next close, if the ex-date has none), valued at the end date's close.
- **Periods:** 1, 3 and 6 months and 1 year as they are; 3, 5 and 10 years as a yearly rate over their nominal years; since first price as a yearly rate over its actual length once it's over a year. No figure without a close within 10 days of the period's start and end, so a fund younger than the period shows nothing rather than a shorter period's return.
- **Trailing yield:** distributions with ex-dates in the 12 months to the latest close (the one exactly 12 months ago excluded), divided by that close.
- **As at:** the latest ETF price date.
- **Check against the ASX:** each ETF's 1-year return measured at its latest report's month end, stored beside the report's figure. The nightly log lists ETFs more than 2 points apart: usually a distribution Yahoo missed, a bad price, or the report working its figure out another way (for example from net asset value).

**Kept apart from shares.** `run_valuation` values only `SHARE`s. The `asx_value_screener` view adds `security_type = 'SHARE'`, so ETFs stay out of the screener, menu search, company pages, signals, the track record's average and what-if scenarios, all of which read the view. The menu's latest price date counts shares only. Portfolio pages already value any parcel with a price, so ETF parcels are valued once ETF prices are loaded (stage 2 adds their own figures).

**Nightly step 1b ([§16](kb:nightly-run)).** `python -m src.etf.run_etfs`: the report if due, then prices and distributions (0.5 seconds between ETFs), then performance. A report failure is logged and the prices still run. The first night fetches about 400 full histories (an estimated 10 to 15 minutes, once); after that a few minutes.

**Tests.**
- `tests/unit/test_asx_report.py`: month from a name or title cell, page links, heading matching, group headings, both layouts, fraction and $m scaling, skipped sheets and rows, the download fallbacks and the local folder. It reads spreadsheets built in two plausible layouts by `tests/unit/_etf_report.py`.
- `tests/unit/test_etf_performance.py`: reinvestment, ex-dates without a close, stale periods, annualising, young funds and the trailing yield.
- `tests/unit/test_yahoo_prices.py`: closes as traded, with splits and distributions.
- `tests/integration/test_etfs.py`: loading, re-loading, retiring and reclassifying; the monthly check that doesn't touch the network once loaded; ETFs out of valuation and the view; the security type check; the backfill, monthly fetch and one-off split refetch for an ETF and a share; and performance with the report check.

**Limits.**
- The ASX site is blocked from the build environment, so the automatic download is untested; the reader was checked against the real July 2026 report the user supplied ([§25.1](kb:etfs-collection)).
- Yahoo's ETF distributions are occasionally late or missing; the report check is there to catch it.
- Performance is before tax and ignores franking and brokerage, like the track record (IMP-029).

## Code map

- `src/etf/asx_report.py`: downloads and reads the ASX report
- `src/etf/prices.py`: prices and distributions
- `src/etf/performance.py`: total returns from 1 month to 10 years
- `src/etf/run_etfs.py`: the nightly step

## Data

- `etf_monthly`: the ASX report's facts per fund per month
- `etf_performance`: Sift's calculated returns
- `asx_report_loads`: which monthly reports have been loaded
- `asx_index_returns`: index returns from the report

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Last month's ETF facts missing: the report may not be out yet; see [ETF report won't load](kb:rb-asx-report).

## Known limits

- LIC NTA is monthly (IMP-033).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_asx_report.py`
- `tests/unit/test_etf_performance.py`
- `tests/unit/test_etf_checks.py`
- `tests/integration/test_etfs.py`
