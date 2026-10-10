---
id: screener-actions
title: Screener, value tests, score wheel and suggested actions
category: features
summary: How every valued company is tested against the four value tests, scored on the 30-check wheel and given a suggested action (Recommendation) with its reason.
version: 1.2
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-10
next_review: 2027-01-09
source: AS_BUILT §9, §9.1
related: [valuation-models, trends-markers, track-record, web-gui, volume-and-short-selling, financial-health]
code: [screen_asx.py, src/screening/actions.py, src/screening/scores.py, src/screening/enriched.py, src/screening/movers.py]
tables: [valuation_metrics, daily_prices]
---

## Purpose

The screener is the single source of every company's tests, score and suggested action. The command line and the web pages both call the same loader, so they can never disagree.

## How it works

### Screener (`screen_asx.py`)

Queries `asx_value_screener` directly via raw parameterised SQL (`sqlalchemy.text()`), not through the ORM, this view is read-only and reporting-oriented, so Core SQL was chosen over an ORM mapping for simplicity.

**Show-every-company design (changed 2026-10-02, see below for the pre-change behaviour this replaced).** The four classic value criteria are no longer a SQL `WHERE` filter. `build_query()` only ever filters by `--sector` (a genuine filter, there's no ambiguity about whether a company is in a given sector); the four criteria are computed row-by-row in Python by `annotate_row()` against whatever the query returns, and every row is shown regardless of outcome. This was a deliberate user-requested change: filtering silently drops a company that's close to passing (or missing one input metric) from the output entirely, which hides exactly the information a reviewer most wants to see, *how close* something is, and *why* it didn't clear a particular bar.

**Indicator columns**, one `Y`/`N` column per criterion plus a combined `overall` column:

| Indicator | Criterion | Default threshold | Flag to override |
|---|---|---|---|
| `mos_ok` | Margin of Safety | `> 20%` | `--min-margin-of-safety` |
| `roe_ok` | ROE | `> 12%` | `--min-roe` |
| `de_ok` | Debt/Equity | `< 0.80` | `--max-debt-equity` |
| `yield_ok` | Grossed-Up Dividend Yield | `> 4.5%` | `--min-yield` |
| `overall` | all four (`AND`) by default | - | `--any-of` switches to any one (`OR`) |

Additional flags: `--sector` (exact match filter, unchanged), `--passing-only` (filters the *displayed* rows down to `overall = Y`, restores the pre-change filtered-to-matches-only view, as an opt-in rather than the default), `--limit` (default: **no limit**, i.e. show every company returned by the query, previously defaulted to 25 under the old filtered view, where a small cap made more sense).

**NULL handling, same semantics as the old `WHERE`-based version but now explicit in Python:** `annotate_row()` treats a `None` source value as not clearing the bar (`value is not None and compare(value, threshold)`), so a company missing an input metric (e.g. no DCF result because FCF and dividends were both unusable) shows `N` for that one criterion rather than crashing or being silently dropped from the result, it's still shown, with every other indicator it does have data for computed normally (validated directly with a company missing both yield and margin-of-safety inputs but present on the others, see [§10.10](kb:testing-and-validation)).

Output rendered via `tabulate` in `simple` format with 2-decimal-place float formatting. The summary line now reads `N companies shown, M passing (all/any of the four criteria)` instead of the old `N companies matched`.

**`payout_ratio` warning (added 2026-10-02):** a `payout_ratio` column is included in every result row, and any row with `payout_ratio > 150%` triggers a printed warning listing the affected tickers after the table, a visible flag, not a filter; the row still appears, the yield still shows, but the warning makes clear it likely reflects a one-off special dividend rather than sustainable income. See [§8.1](kb:valuation-models) for the TWR case that motivated this. Unaffected by the show-every-company change, it was already additive, never a filter.

**`valuation_method` column (added 2026-10-02, IMP-008):** every row also shows `valuation_method` (`DCF` or `DDM`), so it's visible at a glance which intrinsic-value model priced that company, see [§8.3](kb:valuation-models)/[§8.4](kb:valuation-models) for why Financial Services and Real Estate companies are priced differently. Note the default `--max-debt-equity 0.80` threshold is structural for banks (leverage is their business model, not a risk flag the way it is for an industrial company) and will read `de_ok = N` for nearly every Financial Services company regardless of how cheap it is on other measures, pulling `overall` to `N` under the default all-four logic; use a much higher `--max-debt-equity` or `--any-of` when screening financials specifically, the row itself is always shown either way (also documented in README.md).

**Trend indicators and `--rank-by momentum` (added 2026-10-02, [§8.6](kb:trends-markers)):** two more informational indicator columns, deliberately **excluded from `overall`** since they answer a different question than the core four-criterion value screen:

| Indicator | Meaning | Flag to override |
|---|---|---|
| `momentum_ok` | `Y` when `margin_of_safety_trend` has improved by more than the threshold | `--min-mos-trend` (default 5pp) |
| `trap_risk` | `Y` when `mos_ok` is `Y` **and** `fundamentals_trend == 'DECLINING'` | not overridable - a composite of two already-overridable inputs |

`--rank-by momentum` changes the `ORDER BY` from `margin_of_safety_percent` to `margin_of_safety_trend` (both `DESC NULLS LAST`), surfacing companies getting cheaper *fastest* rather than companies that are simply cheap in absolute terms right now - the "catch it before others" ranking the user asked for. `trap_risk`-flagged tickers get a printed warning line after the table, the same pattern as the existing `payout_ratio` warning. When every row's `margin_of_safety_trend` is `NULL` (the cold-start case, [§8.6](kb:trends-markers)), a note is printed explaining why rather than leaving it to look broken.

**What this replaced:** before 2026-10-02, the four criteria were a SQL `WHERE` clause (`AND`/`OR` joined per `--any-of`), so a non-matching company simply never appeared in the output at all, and the default `--limit` was 25 (reasonable when the result was already filtered to matches). [§10.3](kb:testing-and-validation)'s Company A/B validation and its "correctly failed the default screen, and correctly appeared only under `--any-of`" language describe that earlier filtering behaviour; the underlying NULL-handling and pass/fail logic it validated carried over unchanged into `annotate_row()`, just expressed as an indicator column instead of a row filter.

### Suggested Actions

User request: *"add a field with variables advise on possible actions? for example watch, investigate, buy, sell, hold"*. Every row gets an `action` and an `action_reason`. The reason is the point: it names the specific tests and markers behind the call, so the output teaches the reasoning instead of issuing a bare verdict. `suggest_action()` is a pure function of the annotated row plus an optional `PositionSummary` ([§19](kb:portfolios-cgt)), so the rules are unit-tested directly (`tests/unit/test_actions.py`).

**Red flags** (any one can downgrade a call): `trap_risk`, `payout_ratio > 150%`, `earnings_quality = WEAK`, `dividend_trend = CUT`, `price_signal = NEW LOWS`, `data_confidence = LOW`.

**Not held** (first matching rule wins):

| Action | Rule |
|---|---|
| `AVOID` | `trap_risk` **and** weak earnings quality: cheap, deteriorating, and profit not backed by cash |
| `BUY` | passes all four value tests with no red flags (notes momentum if `momentum_ok`) |
| `INVESTIGATE` | passes all four but has a red flag, or is cheap and passes 3 of 4 (names the failed test) |
| `WATCH` | cheap but failing 2+ tests; or getting cheaper fast (`momentum_ok`); or ROE, debt and yield pass but the price isn't cheap yet - the "wonderful company, wait for a fair price" list. Red flags are appended |
| `IGNORE` | no value signal (not listed in the `--actions` report) |

**Held** (any open parcel in `holdings`):

| Action | Rule |
|---|---|
| `SELL` | fundamentals `DECLINING` **and** at least one of: trading above estimated value, weak earnings quality, dividend cut |
| `REVIEW` | any red flag, or margin of safety below -50% (now well above estimated value - Graham's sell discipline) |
| `ACCUMULATE` | still passes all four value tests with no red flags: the same bar as `BUY` for a share you don't own, so consider adding (notes momentum if `momentum_ok`). Added 2026-10-05 |
| `HOLD` | otherwise: no red flags, but fails one or more tests (named in the reason), so not a candidate to add to |

**CGT timing note.** On `SELL`/`REVIEW`, if a held parcel reaches the 12-month CGT discount within 90 days, the reason says how many units, from what date, and how many days away - waiting can halve the tax on the gain. Never added to `ACCUMULATE` or `HOLD`, since neither suggests selling.

**Presentation.** The full table gains `earnings_quality`, `price_signal`, `dividend_trend`, `data_confidence`, `held` and `action` (raw marker numbers stay in the database; company names are truncated to keep width down). `--actions` prints a grouped report instead (SELL, REVIEW, ACCUMULATE, HOLD, BUY, INVESTIGATE, WATCH, AVOID) with the wrapped reason per company, action counts, any holdings that aren't on the screening watchlist, and a one-line reminder that these are rule-based research prompts, not financial advice. `--held` restricts either view to companies you hold. The daily automation log now records `--actions` rather than the full table.

**Short-selling caution** (added 2026-10-10, `src/screening/short_caution.py`): a share with a HIGH or ELEVATED short-selling caution (short interest and days to cover, see [Volume and short selling](kb:volume-and-short-selling)) gets "; caution: ..." added to any reason but IGNORE's. It isn't a red flag and never changes the action, so the rules version is unchanged ([ADR-015](kb:adr-015-asic-short-positions)).

**Financial distress caution** (added 2026-10-10, `src/analytics/health.py`): a share whose Altman Z-Score is in the distress zone (below 1.81) gets "; caution: possible financial distress (Altman Z-Score X, distress zone): check the balance sheet and latest results" added in the same way. It never changes the action ([Financial health](kb:financial-health)).

**Found in end-to-end testing:** the first version didn't append red flags to `WATCH` reasons, so a company with ~45% cash conversion read "quality passes, wait for a better price" - a cleaner bill of health than the data supported. Fixed (red flags now appended to every non-`IGNORE` reason) with a regression test, and the wording changed from "quality passes" to "ROE, debt and yield pass" to say exactly which tests passed.

## Code map

- `screen_asx.py`: the row loader (load_annotated_rows, annotate_row) and the command-line screener
- `src/screening/actions.py`: suggested actions and red flags
- `src/screening/scores.py`: the score wheel's checks
- `src/screening/enriched.py`: load_universe(): screener rows with scores and status, for Sift's pages and the nightly record
- `src/screening/movers.py`: biggest movers on the dashboard

## Data

- `asx_value_screener (view)`: each company joined to its latest price and valuation

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- 'No companies found': valuation hasn't run since ingestion, or filters exclude everything.
- A held share shows BUY: actions use the current person's holdings; check they're signed in as (or impersonating) the right person.

## Known limits

- Actions are rule-based with fixed thresholds and can't know context such as a takeover bid (IMP-021).
- Debt to equity suits industrial companies better than banks.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_actions.py`
- `tests/unit/test_scores.py`
- `tests/unit/test_movers.py`
- `tests/integration/test_screener.py`
