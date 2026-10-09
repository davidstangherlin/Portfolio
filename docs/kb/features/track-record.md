---
id: track-record
title: Track record: recording and scoring Sift's calls
category: features
summary: How every night's calls are recorded, never edited, and scored at 1, 3, 6 and 12 months against the average screened company, and how the Track record page answers 'is Sift right?'.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §21
related: [personal-nightly-results, screener-actions, adr-005-immutable-signal-record]
code: [src/tracking/signals.py, src/tracking/outcomes.py, src/tracking/report.py, src/tracking/record_signals.py, src/tracking/score_signals.py]
tables: [signal_snapshots, signal_outcomes, track_record_monthly]
---

## Purpose

The track record judges the rules on results. It can only measure forward from the first night recorded, so recording runs every night and history is never rewritten.

## How it works

**Purpose.** Answer "is Sift right?" with evidence: record what Sift said about every company each night, then compare it with what the share price did over the following 1, 3, 6 and 12 months against the average of every screened company. Recording starts first, because results can only ever be measured forward from the first night recorded (IMP-026).

**What is recorded (`signal_snapshots`, [§4](kb:data-model)).** One row per screened company per valuation date: closing price on that date, suggested action and reason, whether it was held, valuation status, margin of safety, estimated value and model, score total and per spoke, the four value tests, red flags and `rules_version`. Written by `record_signals()` straight after valuation (nightly step 3, [§16](kb:nightly-run)).

**Rules.**
- **Never edited.** `INSERT ... ON CONFLICT DO NOTHING` on `(company_id, snapshot_date)`. A second run the same night, or a later rule change, can't rewrite what was said at the time.
- **Dated by the valuation, not the run.** `snapshot_date` is the company's latest `valuation_metrics.as_of_date`, which is the price date the valuation used.
- **Stale valuations are skipped.** If a company's newest price is newer than its newest valuation (its valuation failed tonight), it is not recorded and is logged as a WARNING, rather than pairing yesterday's estimate with today's price.
- **`RULES_VERSION`** (`src/tracking/signals.py`, currently `2026-10-05`) is the date the screening rules last changed. Bump it whenever thresholds, actions, scores or valuation models change, so each rule set is judged on its own results.
- **Same rows as the GUI.** The recorder uses `load_universe()` (`src/screening/enriched.py`), the loader the dashboard and screener use, so the record holds exactly what was on screen.

**Dashboard layout.** `web/dashlayout.js` arranges the widgets: each `renderDashboard` widget has an id (attention, changes, movers, top, etfs, lics, portfolios, actions, tracking) and a default order. Every widget starts pinned; its pin (top right) unlocks it for this visit, showing a bar to drag it by (pointer events on the window, so mouse and touch both work; the page scrolls to keep the widget under the pointer, and scroll anchoring is off during the drag), ↑ ↓ buttons, half/full width (hidden on one-column screens) and Hide. Hidden widgets get a Show button under the dashboard, with Reset to default layout once anything is saved. The layout, `{"cards": [{"id", "hidden", "wide"}]}` with `wide` null for the widget's default, is saved with `PUT /api/dashboard/layout` (cleared with `DELETE`) in `ui_preferences` (`src/preferences.py` checks its shape) and returned as `layout` in `/api/dashboard`. `dlArrange` drops ids Sift no longer has and puts widgets missing from the saved list (new ones, or the Portfolios widget on days it has nothing to show) straight after the widget they follow by default, so adding a widget needs no migration. Tests: `tests/js/dash_layout.test.js`, `tests/unit/test_preferences.py`, and an API round trip in `tests/integration/test_gui.py`.

**What changed (dashboard).** `signal_changes()` compares the latest two snapshot dates. Each action has a rank (BUY and ACCUMULATE 1, INVESTIGATE 2, WATCH and HOLD 3, REVIEW and IGNORE 4, AVOID and SELL 5). A move between equal ranks is not a change (BUY to ACCUMULATE after buying), and neither is any move where the held flag changed, because buying or selling, not the market, caused it. Better moves are listed first.

**Recording status.** `tracking_status()` gives first and latest dates, nights recorded, signals recorded, companies on the latest night and the date each horizon's first results are due (first date plus 1, 3, 6 and 12 months).

**Scoring (stage 4, `outcomes.py`, nightly step 4).** In one transaction, after the night's signals are recorded:
1. **Which signals are scored.** Each company's first snapshot of each calendar month (the *cohort*: one per company per month, so a company that stays BUY for a month counts once, not 21 times) and every snapshot where its action changed from the previous one with the held flag unchanged (a *change*; buying or selling isn't a signal). Each outcome row records which it is (`is_cohort`, `is_change`; both when a change falls on the month's first night).
2. **When.** A horizon is scored once the market data reaches it: signal date plus 1, 3, 6 or 12 months (end-of-month dates clamp, as `add_months`) on or before the newest stored price date.
3. **How.** End price: the company's last close on or before the horizon. Total return = (end price + every dividend with an ex-date after the signal and up to the horizon, one-offs included - signal price) / signal price. **Benchmark:** the plain average total return, the same way, of every company screened on the signal's night (`universe_size`). **Excess return** = total return - benchmark, in percentage points. **Gap closed** = share of the distance from price to estimated value covered, for signals priced below their estimate. A company with no close within 10 days of the horizon is flagged `delisted` and scored at its last price, so failures stay in the record instead of disappearing.
4. **Monthly summary.** `track_record_monthly` is rebuilt for every month that still has scored cohort signals: per month, action, horizon and rules version, the count, how many beat the benchmark, and the average return, average excess and median excess. Months whose detail is gone keep their rows.
5. **Deletion.** Snapshots before the first day of the month 14 months back are deleted, with their outcomes by cascade. Whole months only: deleting part of a month would make a later day that month's "first signal" and score it twice. Runs after the summary, so nothing is deleted unsummarised. On 5 October 2026 the cutoff is 1 August 2025.

**Track record page (`report.py`, `GET /api/track-record[?version=]`).**
- **Is Sift accurate?** From the permanent monthly summary, per period: one sentence per action ("BUY calls beat the average screened share by 5.8 points over 3 months; 67% of 202 beat it"), its confidence (too early under 30 signals, moderate 30 to 100, solid above 100), a tick when the direction is what the action intends (BUY, ACCUMULATE, INVESTIGATE should beat the average; AVOID and SELL should trail it; WATCH, HOLD, REVIEW and IGNORE are neutral), and the order check: BUY above WATCH above AVOID on average excess return, judged only when all three have 30 signals. Averages across months are weighted by each month's count. A "By month" table lists each month for the chosen period.
- **What did I miss?** From the last 14 months of detail, each signal at its longest scored horizon: BUY or INVESTIGATE on shares not held, with no parcel bought (any portfolio) from the signal date to 30 days after, that beat the average by more than 10 points. **Calls that saved money:** AVOID on shares not held, and SELL on shares held, that trailed it by more than 10 points. First qualifying call per company, best first, up to 20, with price then and now and whether it's still undervalued. Watchlist companies carry a ★.
- **What should I look at now?** *Proven* actions are the buy-side actions (BUY, INVESTIGATE, ACCUMULATE) beating the average at 3 months (1 month until 3-month results exist) with at least moderate confidence; until one is, BUY stands in "on the rules' own terms" and the page says so. Today's signals of a proven action with margin of safety above 20% are split into **New this week** (that action's current run started in the last 7 days) and **Still open**, with price when the run started and now. **Moved on** lists companies with a proven signal in the last 90 days that no longer qualify, and why, checked in this order: you bought it; the price rose out of the buy zone (margin of safety at or below 20% and the price above the signal's); the estimated value fell (margin of safety at or below 20% without a price rise); or its action changed.
- **Rules version filter** limits the verdict, missed and saved lists to one `rules_version`. Empty panels say when their first results are due, or, with a version selected, that its signals aren't old enough yet.
- **Dashboard:** the Track record card shows the BUY line at 3 months (1 month until then) once results exist.

**Validated against made-up history.** `tests/integration/test_track_record.py` builds 13 months of daily prices and signals for a rising BUY, a falling AVOID, a flat WATCH that pays a dividend and turns BUY, and a company that stops trading, then checks benchmark arithmetic, dividends, scorecard selection, delisting, the summary, deletion at the month boundary, the verdict, the rules-version filter and the 30-day purchase rule. A disposable GUI database with 60 synthetic companies, whose signals were set to partly predict their returns, and two rules versions produced 21,816 outcomes in about 20 seconds; the page showed BUY at +5.8 points (solid), the order check "in order", and the 12-month filter's empty state.

## Code map

- `src/tracking/signals.py`: nightly recording (shared calls and each person's held calls), what changed
- `src/tracking/outcomes.py`: scoring, monthly summary, 14-month retention
- `src/tracking/report.py`: the Track record page's figures
- `src/tracking/record_signals.py`: nightly step: record
- `src/tracking/score_signals.py`: nightly step: score

## Data

- `signal_snapshots`: Sift's shared call per company per night; never edited
- `signal_outcomes`: what happened after a night, per horizon
- `track_record_monthly`: the permanent monthly summary

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- 'Too early' everywhere: results start one month after recording began; the page shows when each horizon is due.
- Results look skewed after a rules change: filter by rules version; bump RULES_VERSION whenever rules change.

## Known limits

- Can't be backfilled (IMP-026).
- The benchmark is the plain average of screened companies, not an index (IMP-029).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/integration/test_tracking.py`
- `tests/integration/test_track_record.py`
