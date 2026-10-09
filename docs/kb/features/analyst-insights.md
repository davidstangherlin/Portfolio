---
id: analyst-insights
title: Analyst ratings, price targets and holders
category: features
summary: How analyst ratings, price targets and top holders are fetched weekly in a staggered refresh and shown on company pages as context only.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §29
related: [coattail, ingestion]
code: [src/ingestion/insights_ingestion.py]
tables: [company_insights, analyst_ratings, top_holders]
---

## Purpose

Other people's views are useful context but never feed valuations, scores or signals, so Sift shows them clearly labelled as Yahoo's.

## How it works

Each company page carries three cards from Yahoo Finance, after the dividend chart: **Analyst ratings**, **Analyst price targets** and **Holders**. They're for context only. Nothing here feeds Sift's estimated value, scores, tests, signals or the screener.

**What's not included.** The "Analyst Insights" panel on Yahoo's own site (Morningstar and Argus research) is a paid Yahoo Finance Plus feature and isn't available through Yahoo's data feed. The free equivalents below are what Yahoo's own Analysis and Holders tabs show.

### Data

| Table | What it holds | Refreshed |
|---|---|---|
| `company_insights` | One row per share: when fetched, Yahoo's consensus (`recommendation_key`, `recommendation_mean` on 1 strong buy to 5 strong sell), analyst count, low / mean / median / high price targets, and the major holders breakdown (insiders %, institutions %, institutions % of float, number of institutions) | Replaced on each fetch |
| `analyst_ratings` | Strong buy, buy, hold, sell and strong sell counts per month | Yahoo gives the latest four months; each fetch adds or updates those months and older ones stay, so a longer history builds up |
| `top_holders` | Top 10 mutual fund holders and top 10 institutional holders: name, shares, % held, Yahoo's value, change since the holder's previous report, date reported | Replaced on each fetch |

Percentages are stored as percents (12.5 = 12.5%). `YahooClient.get_insights()` makes three requests per company: the profile (consensus, targets, analyst count), the monthly rating counts, and the holders. If the profile request fails, nothing is stored and the company is tried again the next night. If only one part is missing (common for small companies), that part is left empty.

### Weekly, staggered refresh

`run_ingestion` runs the insights step after prices and fundamentals. Each night it fetches the shares that are due, oldest first, never-fetched first, capped at a seventh of the ticker list (`ceil(n / 7)`). A share fetched in the last six days is never due. Every share is refreshed about once a week, and each night adds roughly 70 companies' worth of requests for the All Ords instead of about 500.

- **First week:** shares fill in over seven nights. To fill them all at once: `python -m src.ingestion.run_ingestion --tickers-file allords.txt --insights-only --insights-all --delay 0.75`
- **Opting out for a run:** `--skip-insights`. `--prices-only` and `--fundamentals-only` also leave it out.
- ETFs and LICs are skipped, like the rest of the share ingestion.

### Company page

- **Analyst ratings:** the consensus in words with Yahoo's 1 to 5 mean, and one stacked bar per month (strong buy to strong sell, 2px gaps, legend, hover or focus for the counts, data table). The colours are a diverging scale: two blues for buy, a neutral grey for hold, two reds for sell. Each arm passes the ordinal checks (one hue, lightness in order, visible steps, light end at least 2:1 against the card) in light and dark themes. Dark mode has its own steps, with the stronger rating brighter.
- **Analyst price targets:** a strip from the lowest to the highest target with today's price, the average target and Sift's estimated value marked, then the figures with each one's gap to the price.
- **Holders** (full width): the four major-holder figures, then the top mutual fund and institutional holder tables. "Value now" is shares x today's price, so it's in the share's own currency and current; Yahoo's own value is stored but not shown, because its currency and date vary. On a phone, shares and date reported are hidden and the headings shorten.
- **Before the first fetch:** a single Analyst ratings card says the data fills in within a week. "No analyst ratings / price targets on Yahoo Finance" shows when Yahoo has none.
- Each card ends with the fetch date and a ? link to its Help entry (topic **Analysts and holders**: analyst ratings, analyst price targets, major holders).

Known issue #34 covers the coverage limits.

## Code map

- `src/ingestion/insights_ingestion.py`: the weekly, staggered fetch and the company page payload

## Data

- `company_insights`: price targets and summary per company
- `analyst_ratings`: rating counts by period
- `top_holders`: each company's top 10 institutional and fund holders

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A company has no ratings: Yahoo has none for many smaller ASX companies (IMP-034).

## Known limits

- Thin coverage for ASX companies (IMP-034).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_insights_parse.py`
- `tests/integration/test_insights.py`
