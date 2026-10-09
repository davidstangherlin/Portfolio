---
id: etfs-presentation
title: ETFs: screener, fund pages and holdings
category: features
summary: How ETFs are shown apart from shares: the ETF screener, fund pages with performance, rank, comparison fund and index, and what each fund holds.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §26, §26.1, §26.2, §26.3
related: [etfs-collection, lics, coattail]
code: [src/etf/views.py, src/etf/profiles.py]
tables: [fund_profiles, fund_holdings]
---

## Purpose

Funds are judged differently from companies, so they get their own screener and pages, with reference points (category rank, a comparison fund, an index) instead of a valuation.

## How it works

### ETFs, Stage 2: Presenting ETFs Apart From Shares

**Purpose.** Show ETFs in Sift under their own heading, separate from shares everywhere they appear, as the user asked: *"When presenting ETFs I want that under the etf heading separated to shares"*. The user chose the separation for the menu bar, portfolios, watchlists, and the dashboard and search. ETFs are judged on fee, size, distributions and total return; they have no estimated value, suggested action or score, so nothing share-specific is shown for them.

**Where ETFs show.**
- **Menu bar:** a new **ETFs** item next to Screener. The Screener stays shares only.
- **ETF screener (`#/etfs`, `/api/etfs`):** every active ETF with category, issuer, fee, fund size, 1, 3, 5 and 10-year return, 12-month yield and spread. Sorted by fund size by default; any column sorts. Search covers code, name and the index tracked; filters for category (with counts), issuer, watchlist and held only. `#/etfs?category=&watchlist=&held=1` presets the filters.
- **ETF page (`#/etf/CODE`, `/api/etf/CODE?compare=`):**
  - Stat tiles: unit price and day move, fee (with the cost on $10,000), fund size and net flows, 12-month yield.
  - **Performance:** each period beside the category average, a reference fund and the ASX report's own figure (which includes franking credits), as a column chart and a table. The reference starts as the largest other fund in the same category (`default_reference`) and can be changed (same-category funds listed first); the choice is kept in the address. The report check note appears when Sift's 1-year return differs from the ASX report's by more than 2 points.
  - **Growth of $10,000** over 1, 3, 5 or 10 years or all history, for the ETF and the reference fund from the same start date, distributions reinvested (`growth_index`, sampled weekly). When the reference fund's history is shorter, the start moves to its first price and the chart says so.
  - **Unit price, last 12 months** with D markers on distribution ex-dates; **distributions per unit** by financial year (July to June, the current year marked as partial); **fund facts**; **fund size over time** once two months of reports are loaded.
  - ☆ Add to watchlist, the holding line, and back to the ETF screener.
  - `#/company/CODE` for an ETF code redirects to its ETF page.
- **Dashboard:** a full-width **ETFs** card: watchlist triggers met on ETFs, ETF parcels reaching the CGT discount, and the ETFs you hold or watch (held first, then the biggest move) with day move, 1-year return and yield, linking to the ETF screener. Needs attention stays shares only, and a held ETF is no longer listed as "held but not screened". A line under the portfolio figures splits the total: Shares $X (n) | ETFs $Y (n).
- **Portfolios:** each portfolio page shows **Shares** and **ETFs** under separate headings, each with its value, gain and today's change, below the combined figures. ETF lines show unit price, 1-year return and yield instead of an action. Parcels and sales tag ETF codes. Portfolio cards count companies and ETFs separately. Buying and selling an ETF works as for a share.
- **Watchlists:** each list shows **Shares** and **ETFs** under separate headings, ETFs with unit price, day move, 1-year return, yield, triggers and note. Overview cards count companies and ETFs separately.
- **Search:** ETFs are in the menu search list, labelled ETF (shares labelled Share), and open their own page.

**Watchlist triggers by type.** New `watchlist_items.yield_above` (ETFs only): met while the 12-month distribution yield is above it. Price at or below works for both. A margin of safety trigger on an ETF, or a yield trigger on a share, is refused with a plain-English message. Editing an entry shows only the triggers that apply to it.

**Backend.**
- `src/etf/views.py`: `etf_rows()` (one query: latest report row, performance, two latest closes; held units and watchlists), `category_averages()`, `default_reference()`, `weekly()`, `distributions_by_year()`, `etf_detail()`, `screener_payload()`.
- `src/etf/performance.py`: `growth_index()`, the daily value of one unit with distributions reinvested exactly as `growth()` reinvests them, so a rebased chart agrees with the returns table.
- `src/portfolio/views.py`: `security_types()`, `with_types()` (marks each line SHARE or ETF and adds the ETF figures), `sections()` (subtotals per type); `combined()`, `portfolio_summaries()` and `portfolio_detail()` return `sections`.
- `gui.py`: `/api/etfs`, `/api/etf/{code}`; `etf_panel()` for the dashboard; `companies_index()` marks each code's type; watchlist payloads judge shares on screener rows and ETFs on ETF rows (`watch_rows`) and split entries into `items` (shares) and `etfs`; UUIDs serialise as text.

**Chart colour.** The reference fund needed a third series colour. `--s3` is raspberry (#c2337a light, #e04f9a dark), checked with the dataviz validator against `--s1` and `--s2` on each theme's surface, all pairs: colour-blind separation and contrast pass in both themes. Violet failed in dark mode (too close to the blue).

**Help.** A new ETFs topic: 14 new entries (ETF screener, an ETF's page, fee (MER), fund size (FUM), bid/ask spread, net flows, total return, 12-month yield, unit price, day move, category, issuer, category average and reference fund) plus the ETF and ASX report entries moved into it. MER and FUM are new acronyms, and Total return and Trailing yield new terms, in the Word glossary. The getting around, dashboard, portfolios and watchlists guides mention ETFs. Every new column heading has hover text (`test_knowledge.py` checks each label).

**Tests.** `tests/unit/test_etf_views.py` (the growth index agrees with `growth()`, weekly sampling, financial-year distributions, category averages, default reference) and `tests/integration/test_etf_gui.py` (the ETF screener and page APIs, share and ETF codes refused or redirected, search types, the dashboard's ETF card and split totals, portfolio sections, and watchlist triggers by type). Checked in headless Chromium against a disposable database with 15 made-up ETFs and 10 or more years of prices: every page at 1280px and 390px (no sideways scroll), light and dark, the reference fund picker, growth periods, the distribution markers, search, the company-to-ETF redirect, and adding, editing and refusing watchlist triggers.

**Limits.**
- Category averages are plain averages of the ETFs in the category that have a figure, not weighted by size.
- The reference fund isn't remembered between visits; it's in the page address.
- Yields and returns are before franking and tax (IMP-029).

### Performance card and checks against the ASX report

The user found the Performance chart hard to read at a glance: it drew 1, 3 and 6-month returns (plain returns) beside 1 to 10-year returns (yearly rates) on one axis, so a 6-month 29% looked better than a 3-year 25% a year, and its "Start" bars compared funds from different start dates. IVV's "Start" showed about -3% a year beside +16% a year over 10 years, which its market can't explain.

- **Chart:** yearly rates only (1, 3, 5 and 10 years), titled as a yearly rate, so every bar is the same unit.
- **Recent:** 1, 3 and 6 months under the chart as "Recent performance, not annualised".
- **Table:** grouped "A year (yearly rate)", "Recent (not annualised)" and "Since first price (a year)", with each fund's own start date under its figure. The category average isn't given for since first price, because a category's funds start on different dates.
- **Checks** (`report_flags()` in `views.py`), marked ⚠ in the table with the reason, listed above the chart, left off the chart and out of the category average:
  - **Against the ASX report, every period.** `performance.report_checks()` measures each period to the latest report's month end and stores `[sift, asx]` per period (`etf_performance.report_checks`). A gap over 2 points is flagged; for "Equity - Australia" funds a shortfall of up to 4 points is the franking credits the ASX counts and isn't. Since first price is compared only when Sift's prices start within 31 days of the listing date. `check_return_1y` and `reported_return_1y` are still filled for `report_differences()`.
  - **Price jumps.** `performance.price_jump()` finds the latest one-day move beyond 40% (`price_jump_date`, `price_jump_percent`) that looks like a data fault: an unadjusted split or consolidation, or a currency change in the feed, which shifts the price level for good. Every period starting before it is flagged, and the nightly ETF step logs it as a warning. Not counted (2026-10-07, after 8IH, at about a cent a share, had a genuine 58% day flagged): a price under 10 cents on either side, where a few ticks are tens of percent; a move that doesn't stay (the median of the 10 closes after must also differ from the median of the 10 before by 40%), such as a one-day bad print; and a drop that a distribution paid that day explains.
  - **Nothing to chart.** When every yearly figure is blank or flagged, the card says so instead of drawing an empty chart (whose scale also printed 1%, 1%, 0%, -1%, -1%); small scales now show one decimal place.
- Help: "Checking returns against the ASX report" (`asx-report-check`).
- **Not yet fixed:** the underlying fault in a flagged history (such as IVV's) is reported, not repaired; a clean full refetch of that fund's prices is the likely repair once the log names it.

### Reference points: rank, comparison fund and index

The user asked how to read the category average and the ASX report column, and whether they were the best reference points. They weren't: a category such as Equity - Global mixes very different funds, its average changes make-up by period and is swayed by outliers, and the ASX column was the same fund again to a different date (a check, not a comparison).

- **Rank in category and the median** replace the category average (`peer_ranks()`): for each period except since first price, the fund's rank (1st is best) among the funds in its category whose figure passed its checks, out of how many, and the median. The chart draws the median. Bands (top 10%, top quarter, top half, bottom half, bottom quarter) come from `(rank - 1) / (of - 1)` and aren't shown under five funds. On a phone the median column is hidden; it stays on the chart.
- **The ASX column is now one check line** above the chart: ✓ when every period agrees with the report to its month end, otherwise the ⚠ list ([§26.1](kb:etfs-presentation)).
- **Default comparison fund** (`default_reference()`, `PREFERRED_REFERENCE`): the broad, low-cost alternative for the category, first listed that exists and isn't the fund itself: VAS, A200, IOZ, STW for Australian equity (and its strategy and sector funds); VSO, ISO for small and mid caps; VGS, IWLD, IVV for global equity (and strategy and sector funds); VGE, IEM for Asia and emerging markets; VAP or MVA, REIT or DJRE for property; VAF or IAF, VBND or VIF for bonds; IFRA or VBLD for infrastructure; VDHG or VDBA for mixed assets; AFI or ARG for Australian equity LICs. Otherwise the category's largest fund, as before. Any fund can still be chosen.
- **Against its index** (`index_comparison()`): the report's benchmark index rows are now kept (`READER_VERSION = 4`, `Report.indices`, table `asx_index_returns`), taken from the ETP list only (the LIC list repeats them laid out differently, which read a row out of line) and dropped if implausible (the report's two bond index rows carry figures such as -51% a year). The July 2026 report gives the S&P/ASX 200, Small Ordinaries, 200 A-REIT and Infrastructure accumulation indices. Funds in Equity - Australia (and its strategy and sector categories) are shown against the S&P/ASX 200, small and mid caps against the Small Ordinaries, and Australian property against the A-REIT index: fund and index both from the report to its month end and both counting franking, with the difference in points. Global funds have no index in the report, so none is shown; infrastructure isn't mapped because those funds are mostly global.
- A month loaded by reader version 3 is reloaded from its saved file on the next ETF step ([§25.2](kb:etfs-collection)), which fills `asx_index_returns`.
- Help: "Category median and rank" (was "Category average"), "Reference fund", "Against its index" (`index-comparison`), "Checking returns against the ASX report".

### What a fund holds

Each ETF and LIC page shows the fund's description under its heading (first two sentences, "more" for the rest) and a **What it holds** card after Performance.

- **Source:** Yahoo Finance's fund data (Morningstar), via yfinance's `FundsData`: description, asset mix, top 10 holdings, sector weightings, bond credit ratings, duration and maturity (`YahooClient.get_fund_profile()`, parsed by `parse_fund_profile()`; fractions become percents, zero sectors are dropped). Yahoo lists LICs as companies with no fund data, so they get the company description only. LIC holdings are in each LIC's own monthly NTA report, which has no common format; the user chose Yahoo first, with coverage to be reviewed after the first run before considering issuer feeds.
- **Feeder funds are looked through** (added 2026-10-07, after the user saw IVV's top 10 as one line, "iShares Core S&P 500 ETF 99.97%"): several ASX funds, mostly iShares international ones (IVV, IOO, IJR, IEM...), hold a US-listed fund rather than the shares. When one holding with a Yahoo symbol is 80% or more of the fund (`LOOK_THROUGH_PERCENT`), `look_through()` fetches that fund's data and uses its top 10 (each weight scaled by the feeder's share in it) and its sectors, bond ratings, duration and maturity where the feeder has none; the feeder's own description and asset mix stay. One level only. The fund looked through is stored (`look_through_symbol`, `look_through_name`, `look_through_percent`) and the card says so. A feeder stored before this (its big holding not yet looked through) is treated as never fetched, so it's corrected on the next run rather than a week later.
- **Storage:** `fund_profiles` (one row per fund: description, asset mix, `sector_weightings` and `bond_ratings` as JSONB, duration, maturity, `top10_percent`) and `fund_holdings` (top 10, replaced on each fetch). JSONB doesn't keep key order, so the page sorts sectors largest first.
- **Refresh:** weekly, a seventh of the active ETFs and LICs each night (`src/etf/profiles.py`, shared `rolling.nightly_share`), in the ETF step after prices. A fund whose fetch fails outright is retried the next night; one Yahoo has nothing for is stored empty and waits a week. `run_etfs --profiles-all` fetches every fund that's due now; `--skip-profiles` (or `--skip-prices`) leaves it out. The log reports how many profiles had holdings, which is the coverage figure to review.
- **Card:** asset mix as one stacked bar with a labelled legend (shares, bonds, cash, other); top 10 holdings with their share of the fund and the top 10's total; sectors as single-hue bars with the value beside each; for bond funds, ratings in rating order and duration and maturity. LICs and funds Yahoo has nothing for say so; before the first fetch the card says it fills in within a week.
- Help: "What a fund holds" (`fund-holdings`).

## Code map

- `src/etf/views.py`: ETF and LIC rows, ranks, comparisons
- `src/etf/profiles.py`: fund descriptions, holdings, sectors and asset mix

## Data

- `fund_profiles`: a fund's description and asset mix
- `fund_holdings`: the top holdings of each fund

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Performance differs from the ASX report: the fund page's check line compares them; small differences come from distribution timing.

## Known limits

- Fund holdings are the top holdings Yahoo publishes, not the full list.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_etf_views.py`
- `tests/unit/test_fund_profile.py`
- `tests/integration/test_etf_gui.py`
