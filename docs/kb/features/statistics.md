---
id: statistics
title: Statistics: rule reliability, chances and likely ranges
category: features
summary: Whether each action beats the average share by more than luck (Track record), the chance of reaching the estimated value or analysts' target in 12 months, and the likely range for the year ahead, from nightly volatility.
version: 1.0
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-01-10
source: AS_BUILT change log, 2026-10-10
related: [track-record, adr-016-statistics-libraries, adr-017-statistics-methods, nightly-run, ai-and-graph]
code: [src/analytics/prices.py, src/analytics/rules.py, src/analytics/words.py, src/analytics/run.py, src/tracking/report.py, src/tracking/outcomes.py, gui.py, web/app.js, web/style.css]
tables: [price_statistics, track_record_monthly, daily_prices]
---

## Purpose

Give everyday investors three answers with tested statistics, in plain words (asked for 2026-10-10, presentation agreed from a mock-up in Sift's colours): is each rule really working, how likely a share is to reach a price, and how much its price is likely to move. Built on NumPy, SciPy and statsmodels ([ADR-016](kb:adr-016-statistics-libraries)); the methods and their limits are in [ADR-017](kb:adr-017-statistics-methods). The same nightly figures (volatility and beta) will drive the crash test simulator (IMP-067).

## How it works

**Plain words first.** Every statistic leads with a sentence, then one picture, then "How this is worked out" behind a twisty. Chances are numbers in 10 with a fixed word (`src/analytics/words.py`): Very unlikely (under 1 in 10), Unlikely (1 to 2), Possible (3 to 4), About even (5), Likely (6 to 7), Very likely (8 or more). Chances and ranges use Sift's chart blue, never green or red, so they don't read as buy or sell; status colours appear only on verdict pills, with an icon and words. Admins see the exact figures (percentages, t and p) inside the twisties.

**Nightly Statistics step** (`python -m src.analytics.run`, after Track Record). `prices.refresh()` works out, for every active security with prices, into `price_statistics` (one row each, replaced nightly):
- **Volatility:** the standard deviation of daily log returns over up to three years, times sqrt(252). Needs 250 returns (about a year).
- **Beta:** the slope (statsmodels OLS) of weekly log returns on an ASX 200 fund's: IOZ, else STW, A200 or VAS. Weekly because small companies don't trade every day. Needs 52 weeks. Not shown yet; kept for the crash test.
- **Likely range:** price x e^(-volatility) to price x e^(+volatility), two years in three.
- **Chance of reaching** Sift's estimated value and the analysts' target (`company_insights.target_mean`), shares only: 2 x (1 - N(ln(level / price) / volatility)), the chance a driftless random walk in the log price touches the level within a year. A level at or below the price is already reached (no chance figure).

**Company page.** `GET /api/company/{code}` returns `statistics` (`company_statistics()`). The **Price against estimated value** card gains "Chance of reaching it within 12 months": a row each for Sift's estimated value and the analysts' target, with the level and how far above today it is, ten dots (`chanceDots()`) and the words; "Already reached" or "Needs a year of prices" otherwise. The **Share price** card becomes "last 12 months and the year ahead": a sentence ("In a typical year, GEM would end between $3.05 and $5.78 (two years in three)"), the chart continued 12 months past Today with the shaded range (weekly points, `aheadRange()`; `lineChart({ ahead })`), the range's ends labelled, and hover giving the range at each point ahead. `volumeChart({ until })` extends the same axis so the volume bars stay lined up.

**Track record.** Each action in "Is Sift accurate?" gets a verdict pill, a luck sentence and a bar (`verdictLine()`, `edgeBar()`): `report.verdict()` adds `test` from `rules.test()`, a t-test on the calls' excess returns from the permanent monthly summary. `track_record_monthly.excess_sumsq` (filled by `refresh_monthly()`) gives the spread, so the test covers the whole history. Verdicts: Beating the average (the 95% range wholly above zero), Trailing the average (wholly below), Too early to tell (it spans zero), Needs more calls (under 30). A tick when the result is what the action intends (BUY, INVESTIGATE, ACCUMULATE beating; AVOID, SELL trailing), a cross for the opposite. The standard error is widened by the square root of the horizon in months for overlapping calls. Luck is told as odds ("about a 1 in 40 chance"). The dashboard's Track record line shows the BUY verdict.

**AI and graph.** The AI `company` tool returns `price_statistics` (volatility, beta, likely range, chances in words); `track_record` carries each action's `test`. Graph Company nodes carry `volatility` and `beta`.

## Code map

- `src/analytics/prices.py`: volatility, beta, likely range, chance of reaching, nightly refresh, company figures
- `src/analytics/rules.py`: the rule test
- `src/analytics/words.py`: chances and odds in words
- `src/analytics/run.py`: the nightly step
- `src/tracking/outcomes.py`, `src/tracking/report.py`: the summary's sum of squares; the test in the verdict
- `web/app.js`: `chancesBlock()`, `chanceDots()`, `workedOut()`, `aheadRange()`, `lineChart({ ahead })`, `volumeChart({ until })`, `verdictLine()`, `edgeBar()`

## Data

- `price_statistics`: one row per security, shared market data (excluded from search: numbers only)
- `track_record_monthly.excess_sumsq`: the sum of squared excess returns per month, action, horizon and rules version

## Diagnosing problems

- No range or chances on a company page: fewer than about 250 daily prices, or the Statistics step hasn't run (check the nightly log; run `python -m src.analytics.run`).
- Beta blank everywhere: no ASX 200 fund's prices (IOZ, STW, A200 or VAS); the log warns.
- Every action "Needs more calls" although there are results: the monthly rows predate `excess_sumsq`; the next Track Record step rebuilds every month with detail.

## Known limits

- Ranges and chances describe how the price has moved; they assume no trend and know nothing about news, results or value. Pages say so.
- Prices are treated as normal in the log; real markets have more extreme days than that, so the range is a guide, not a bound.
- The overlap adjustment is a rule of thumb, chosen to claim less rather than more ([ADR-017](kb:adr-017-statistics-methods)).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_analytics.py`
- `tests/integration/test_statistics.py`
- `tests/integration/test_track_record.py`
- `tests/unit/test_stats_stack.py`
