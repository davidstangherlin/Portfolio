---
id: statistics
title: Statistics: rule reliability, chances and likely ranges
category: features
summary: Whether each action beats the average share by more than luck (Track record), the chance of reaching the estimated value or analysts' target in 12 months, and the likely range for the year ahead, from nightly volatility.
version: 1.3
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-01-10
source: AS_BUILT change log, 2026-10-10
related: [track-record, adr-016-statistics-libraries, adr-017-statistics-methods, nightly-run, ai-and-graph]
code: [src/analytics/prices.py, src/analytics/rules.py, src/analytics/words.py, src/analytics/run.py, src/tracking/report.py, src/tracking/outcomes.py, gui.py, web/app.js, web/style.css, frontend/src/components/track.tsx, frontend/src/charts/edgeBar.ts]
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

**Track record.** Each action in "Is Sift accurate?" gets a verdict pill, a luck sentence and a bar (`verdictLine()`, `edgeBar()`): `report.verdict()` adds `test` from `rules.test()`, a t-test on the calls' excess returns from the permanent monthly summary. `track_record_monthly.excess_sumsq` (filled by `refresh_monthly()`) gives the spread, so the test covers the whole history. Verdicts: Beating the average (the 95% range wholly above zero), Trailing the average (wholly below), Too early to tell (it spans zero), Needs more calls (under 30). A tick when the result is what the action intends (BUY, INVESTIGATE, ACCUMULATE beating; AVOID, SELL trailing), a cross for the opposite. The standard error is widened by the square root of the horizon in months for overlapping calls. **Many tests at once:** every action at every period is one family, corrected together by `rules.adjust()` (Benjamini-Hochberg, at most 5% of findings expected false, `FALSE_FINDINGS`). The luck odds use the adjusted p-value (`q_value`), and every bar is widened to the matching level, max(findings, 1) x 5% / tests (Benjamini and Yekutieli's false coverage rate), so a bar clear of the average always means a finding. The test keeps `p_value`, `q_value`, `level` and `family` for admins. Luck is told as odds ("about a 1 in 40 chance"). The dashboard's Track record line shows the BUY verdict.

**Admin, Model and rules: Statistics.** Two settings (`src/settings.py`, group `statistics`): `stats_min_calls` (calls needed before judging a rule, 30) and `stats_years` (years of price history, 3). Both are listed with their live values, ranges and formulas; the fixed methods follow under "Fixed by design" (`STATISTICS_METHODS` in `gui.py`, `statisticsMethods()`). The group is left out of what-if scenarios (`WHAT_IF_GROUPS`), since no statistic changes a company's action. The rules document (`scripts/build_rules_doc.js`) has a Statistics chapter.

**AI and graph.** The AI `company` tool returns `price_statistics` (volatility, beta, likely range, chances in words); `track_record` carries each action's `test`. Graph Company nodes carry `volatility` and `beta`.

## Code map

- `src/analytics/prices.py`: volatility, beta, likely range, chance of reaching, nightly refresh, company figures
- `src/analytics/rules.py`: the rule test
- `src/analytics/words.py`: chances and odds in words
- `src/analytics/run.py`: the nightly step
- `src/tracking/outcomes.py`, `src/tracking/report.py`: the summary's sum of squares; the test in the verdict
- `web/app.js`: `chancesBlock()`, `chanceDots()`, `workedOut()`, `aheadRange()`, `lineChart({ ahead })`, `volumeChart({ until })`; the Track record verdicts are React (`frontend/src/components/track.tsx`, `frontend/src/charts/edgeBar.ts`)

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
- The multiple-testing correction treats the tests as roughly independent; the periods overlap, which Benjamini-Hochberg tolerates for positively related tests.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_analytics.py`
- `tests/integration/test_statistics.py`
- `tests/integration/test_track_record.py`
- `tests/unit/test_stats_stack.py`
- `tests/unit/test_health.py` (the multiple-testing correction)

## References

The theory each part uses. Links are given only where the address was checked (2026-10-10); the others are cited in full.

| Used for | Reference |
|---|---|
| Excess return against a benchmark (the track record and its test) | Fama, E. F., Fisher, L., Jensen, M. C. and Roll, R. (1969). The adjustment of stock prices to new information. *International Economic Review*, 10(1), 1 to 21. |
| The t-test (more than luck?) | Student [W. S. Gosset] (1908). The probable error of a mean. *Biometrika*, 6(1), 1 to 25. [doi:10.1093/biomet/6.1.1](https://doi.org/10.1093/biomet/6.1.1) |
| Overlapping returns inflate certainty | Hansen, L. P. and Hodrick, R. J. (1980). Forward exchange rates as optimal predictors of future spot rates: an econometric analysis. *Journal of Political Economy*, 88(5), 829 to 853. |
| Correcting errors for overlap (the more exact alternative, ADR-017) | Newey, W. K. and West, K. D. (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. *Econometrica*, 55(3), 703 to 708. [doi:10.2307/1913610](https://doi.org/10.2307/1913610) |
| Log-normal prices, volatility | Black, F. and Scholes, M. (1973). The pricing of options and corporate liabilities. *Journal of Political Economy*, 81(3), 637 to 654. Hull, J. C. *Options, Futures, and Other Derivatives*, Pearson (estimating volatility from historical data). |
| Chance of touching a level (first passage, reflection principle) | Shreve, S. E. (2004). *Stochastic Calculus for Finance II: Continuous-Time Models*. Springer, section 3.7. |
| Beta | Sharpe, W. F. (1964). Capital asset prices: a theory of market equilibrium under conditions of risk. *Journal of Finance*, 19(3), 425 to 442. [JSTOR 2977928](https://www.jstor.org/stable/2977928) |
| Weekly rather than daily returns for beta | Scholes, M. and Williams, J. (1977). Estimating betas from nonsynchronous data. *Journal of Financial Economics*, 5(3), 309 to 327. Dimson, E. (1979). Risk measurement when shares are subject to infrequent trading. *Journal of Financial Economics*, 7(2), 197 to 226. |
| Fat tails (the limits of the ranges) | Mandelbrot, B. (1963). The variation of certain speculative prices. *Journal of Business*, 36(4), 394 to 419. [doi:10.1086/294632](https://doi.org/10.1086/294632) |
| Many tests at once (false discovery rate) | Benjamini, Y. and Hochberg, Y. (1995). Controlling the false discovery rate: a practical and powerful approach to multiple testing. *Journal of the Royal Statistical Society, Series B*, 57(1), 289 to 300. [doi:10.1111/j.2517-6161.1995.tb02031.x](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) |
| Widening the bars to match (false coverage rate) | Benjamini, Y. and Yekutieli, D. (2005). False discovery rate-adjusted multiple confidence intervals for selected parameters. *Journal of the American Statistical Association*, 100(469), 71 to 81. [doi:10.1198/016214504000001907](https://doi.org/10.1198/016214504000001907) |
| Chances as numbers in 10 | Gigerenzer, G. and Hoffrage, U. (1995). How to improve Bayesian reasoning without instruction: frequency formats. *Psychological Review*, 102(4), 684 to 704. |

People's version: Help, "The theory behind Sift's statistics" (`statistics-theory`).
