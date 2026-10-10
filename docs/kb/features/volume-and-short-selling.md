---
id: volume-and-short-selling
title: Volume and short selling
category: features
summary: Daily volume bars under the price chart, and ASIC's short positions as a company card, screener column, Most shorted tab, watchlist trigger and a short-selling caution that never changes the action.
version: 1.1
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-01-10
source: AS_BUILT change log, 2026-10-10
related: [coattail, screener-actions, watchlists, adr-015-asic-short-positions, rb-short-positions]
code: [src/ingestion/short_positions.py, src/screening/short_caution.py, src/portfolio/views.py, src/screening/actions.py, gui.py, web/app.js, web/style.css]
tables: [short_positions, daily_prices, watchlist_items]
---

## Purpose

Show how much of a share traded each day, and whether professional investors are betting against it (asked for 2026-10-10: "I also want the share volume from the day and want to chart that ... How do i see if a company is shorted?"). Heavily shorted shares are volatile: people can buy them, but with caution, so Sift shows a caution beside the action rather than changing it. Market depth (the buyers and sellers waiting) was left out: it needs a paid live feed (help article `market-depth`).

## How it works

**Volume.** `daily_prices.volume` (shares traded, from the nightly price load) goes to the company page as `volumes`. `volumeChart()` draws one bar a day under the price chart on the same time axis, with the 63-day (three-month) average as a line; a day over twice that average is drawn darker. The price card's data table gains a Volume column.

**Short positions** (`src/ingestion/short_positions.py`). ASIC publishes one file a day, `RR{yyyymmdd}-001-SSDailyAggShortPos.csv`, about four business days after the day it covers, listing every product's reported short positions, shares on issue and percentage. The nightly step Short Positions first loads any ASIC files saved by hand in `data/ASIC` (kept out of git) whose day isn't loaded, then fetches every weekday in the last 14 days not yet loaded (a missing file is a holiday or not published yet, tried again next night). `--file` loads one saved file and `--folder` every file in `data/ASIC` (or a folder named). `parse()` reads tab or comma files in UTF-16 or UTF-8 and finds its columns by heading words, working out the percentage when that column is missing. `save()` replaces the day and prunes anything older than two years.

**The short-selling caution** (`src/screening/short_caution.py`). It uses the measures professional short-interest services report, plus the trend:

- short interest % = shares sold short / shares on issue
- days to cover = shares sold short / average daily volume over the 20 trading days to the report (how many days of normal trading short sellers would need to buy back)
- change = the move in short interest over about a month

| Level | Trigger (settings in brackets) |
|---|---|
| HIGH | 10% or more sold short (`short_warning`), or 5% or more (`short_caution`) with 10 or more days to cover (`days_to_cover_high`) |
| ELEVATED | 5% or more sold short, or 2% or more (`SHORT_FLOOR`) with 5 or more days to cover (`days_to_cover_caution`) or a rise of 2 points or more in a month (`RISE_POINTS`) |

Most ASX shares have under 1% sold short, so 5% is among the most shorted. Days to cover only counts from 2% short, as a thinly traded share shows many days on a tiny short, and days to cover alone never makes HIGH. The screener view `asx_value_screener` carries `short_percent`, `days_to_cover` and `short_change` (the last two appended), so `suggest_action()` adds "; caution: heavily shorted (X% of shares sold short, Y days to cover): expect sharp price swings; keep any position small" to the reason. The action is unchanged: a BUY stays a BUY, and the rules version is unchanged ([ADR-015](kb:adr-015-asic-short-positions)).

**Where it shows.** The company page: an amber "! Heavily shorted" or "! Shorted" tag beside the action, the caution in the reason, the Short selling card (sold short, days to cover, change over a month, the caution note and a year's chart) and, only when there's a caution, an information card (`shortInfoCard()`): "Buying a shorted share", or "You hold a shorted share" for a holder. It says in plain words what's happening, where the share sits on a four-band scale (Normal under 2%, Watch, Elevated, High; from `short_levels` in the payload, so it follows the settings, with a line when days to cover or a rising trend lifts the caution above the share's band), why the price can swing, and what to check before buying or, for a holder, that shorting isn't a reason to sell on its own. Portfolios: the amber ! beside the action of a held share with a caution (`short_caution` on each holding line), whose hover adds "Not a reason to sell on its own". Deliberately not on the dashboard: Needs attention is for things to act on, and the watchlist trigger is the opt-in route (agreed with the owner, 2026-10-10). The screener: the % short column (optional, amber when there's a caution) and an amber ! beside the action. Coattail, Most shorted (`GET /api/coattail/shorts`): the 25 most shorted ASX shares on the latest report and the 25 rising fastest over a month, ETFs left out, with the caution mark (without days to cover). Watchlists: Trigger: short interest above (%) on shares (`watchlist_items.short_above`). The AI company tool gives `short_selling` with days to cover and the caution.

## Code map

- `src/ingestion/short_positions.py`: fetch, parse, save, nightly run, CLI; `company_short()` and `most_shorted()` for the pages
- `src/screening/short_caution.py`: the caution levels and their wording
- `src/screening/actions.py`: adds the caution to the reason
- `src/settings.py`: `short_caution`, `short_warning`, `days_to_cover_caution`, `days_to_cover_high`
- `src/watchlist/lists.py`: the short interest trigger
- `src/portfolio/views.py`: `short_caution` on each holding line
- `gui.py`: company payload (`volumes`, `short_interest`, `short_caution`), screener rows (`short_caution`, `days_to_cover`), `/api/coattail/shorts`
- `web/app.js`: `volumeChart()`, `cautionTag()`, `shortInterestCard()`, `shortInfoCard()`, `renderShorts()`, the holdings table's caution mark
- `scripts/daily_refresh.ps1`: the Short Positions step, after Share Registries and before Valuation

## Data

- `short_positions`: one row per ASX code per report day (shared market data, no owner; excluded from search as numbers only)
- `daily_prices.volume`: shares traded each day
- `watchlist_items.short_above`: the trigger level

## Diagnosing problems

- No short data, or the card says no report: see the [runbook](kb:rb-short-positions).
- Days to cover blank: the share has no volume in the 20 trading days to the report.
- A share with a big short and no caution: check the settings in Admin, Model and rules.

## Known limits

- The ASIC file layout was built from its published column names, not a file fetched here: the first nightly runs on the owner's PC prove it (IMP-066).
- About four business days behind; ASIC's figures are what holders report, not every short.
- Market depth isn't available without a paid live feed.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_short_positions.py`
- `tests/integration/test_short_selling.py`
