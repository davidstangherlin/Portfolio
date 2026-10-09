---
id: admin-console
title: Admin console: model and rules, workings and what-if scenarios
category: features
summary: One registry of every setting and formula, step-by-step workings for any company, and what-if scenarios that compare other settings with live on today's data.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §24
related: [valuation-models, ref-settings]
code: [src/settings.py, src/admin/workings.py, src/admin/scenarios.py]
tables: [scenarios]
---

## Purpose

The admin console makes Sift's judgement inspectable and lets an admin test a rule change safely before anyone changes the live settings in code.

## How it works

**Purpose.** See every formula, threshold and calculation Sift uses, and try different settings against today's data, without changing anything live. Built as phases 1 and 2 of the agreed design: view and explain (phase 1), and a what-if lab (phase 2). Publishing a scenario as the live rules (phase 3) and backtesting a scenario against the track record (phase 4) are not built.

**One registry for every setting (`src/settings.py`).** `ModelSettings` is a frozen dataclass of the 29 adjustable settings, and `LIVE` holds the values the nightly job uses. Every module that used its own constant now reads it from `LIVE`, so the registry is the single source:

| Group | Settings | Read by |
|---|---|---|
| Valuation models | DCF growth, DDM growth, discount rate, terminal growth, stage-one years, cash flow averaging years | `dcf.py`, `ddm.py`, `engine.py` |
| Value tests | Minimum margin of safety, ROE, maximum debt/equity, minimum grossed-up yield | `screen_asx.py` |
| Markers and actions | Earnings quality STRONG and ADEQUATE, new-lows range, dividend cut and growth ratios, ROE and revenue trend steps, momentum step, payout warning, overvalued review level | `markers.py`, `engine.py`, `actions.py`, `screen_asx.py` |
| Score wheel | The nine thresholds the 30 checks use beyond the four tests | `scores.py` |

Each setting carries its group, label, unit, allowed range, formula, where it's used and the knowledge base entry that explains it (`help_id`). `with_overrides()` builds a scenario's settings from entered values (rates entered as percents, e.g. 9 for 9%), and `check()` refuses combinations that make no sense: discount rate not above terminal growth, ADEQUATE above STRONG, and any score wheel "strong" threshold not stricter than its value test. The live values did not change: `tests/unit/test_settings.py` pins all 29, and the score wheel's labels are built from the settings but read exactly as before at the live values.

**Model and rules (`#/admin`).** Opened from the gear panel ("Model and rules", "What-if scenarios"), behind the same password as the rest of Sift. Shows the nightly pipeline, then every setting by group with its live value, range, formula and where it's used. Each setting has a pink **?** link to its Help entry, and the Help entries for the admin console and scenarios link back to these pages.

**Show workings (`src/admin/workings.py`, a card on every company page).** Every figure on the company page step by step: the base years and their average, the assumptions, the year-by-year projection, the discounting and terminal value, the estimated value and margin of safety; then the ratios, each value test with its threshold and result, and each marker with the rule that set it. A sensitivity grid shows the estimated value at discount rates from 7% to 11% (plus the live rate, if outside that) against growth 2 and 4 points either side of the live rate, with the live cell outlined. Every step links to the Help entry for the concept. A selector re-runs the workings under any saved scenario. Tests check the final figures equal `compute_metrics()` exactly for a DCF company and a bank (DDM), so the workings can't drift from the numbers Sift uses.

**What-if scenarios (`src/admin/scenarios.py`, `#/admin/scenarios`).**
- **Editor:** every setting with its live value; changed values turn pink. Run compares the scenario with live on today's data without saving; Save keeps it by name with notes. A scenario stores only the settings that differ from live, in the units entered (`scenarios` table, `overrides` JSONB), so it follows any later change to a live value it didn't override.
- **Results:** how many companies hold each action under live and the scenario, the moves between actions, every company whose action, status or value changed (better moves first, held and watched companies flagged, and a separate "Yours" list), the margin of safety distribution, median margin of safety, average score and number valued.
- **How a run works:** each company's inputs (latest price, up to five annual reports, recent closes) are gathered once and cached in memory until the data changes (keyed by the latest price date, latest valuation date and row counts). Each run then values, tests, scores and assigns actions for the whole universe in memory, twice (live and scenario). Values are rounded to their column sizes as the nightly job stores them, so a scenario with no changes matches live exactly (tested).
- **Nothing live changes:** a run writes nothing. Saving writes only the `scenarios` row. Valuations, the screener, signals and the track record are untouched.
- **Kept at live values:** the margin-of-safety trend (momentum) compares with the live figure stored 30 days ago, so a scenario uses the live trend rather than mixing its own figure with a stored live one. Holdings and watchlists are today's.

**API.** `GET /api/admin/settings`; `GET|POST /api/admin/scenarios`; `GET|PUT|DELETE /api/admin/scenarios/{id}`; `POST /api/admin/run` (a run from the editor's current values; reads only, POST because it carries the settings); `GET /api/company/{code}/workings?scenario={id}`. Writes go through the same password, same-page guard and one-transaction `change()` as portfolios ([§19.1](kb:portfolios-cgt)). An unknown setting, a value outside its range, a duplicate or blank name, or a `check()` failure returns a 400 with a plain-English message.

**Knowledge base.** Five new entries in a new Admin topic: Admin console, Scenario and Growth rate (both in the Word glossary), Show workings and Sensitivity grid. DCF, DDM and discount rate link to them. 83 entries in all.

**Tests.** `tests/unit/test_settings.py` (pinned live values, every setting's metadata and Help link, every module reading the registry, override units, each guard rail, score labels and markers under changed settings) and `tests/integration/test_admin.py` (no-change scenario equals live exactly, a stricter ROE test moves a company from ACCUMULATE to HOLD, a valuation change matches the engine, the cache follows the data, workings equal the engine for DCF and DDM with every Help link real, and the API end to end including the write guard, 400s, 404s, rename and delete). Checked in headless Chromium at 1280px and 390px against a disposable database of 60 companies with 13 months of made-up history.

**Limits.**
- A scenario is judged on today's data only; it can't yet say how it would have done in the past (phase 4).
- Momentum stays live, as above, so a scenario that changes the margin of safety a lot shows the live trend beside it.
- The cache is per server process; the first run after the nightly job (or a restart) gathers inputs again, which takes a few seconds for 500 companies.

## Code map

- `src/settings.py`: the registry: every setting's value, range, formula and help entry
- `src/admin/workings.py`: a company's figures step by step
- `src/admin/scenarios.py`: what-if runs and saved scenarios; scoped to the current person

## Data

- `scenarios`: per person: a saved set of setting overrides

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A scenario run shows no differences: overrides equal to live values are dropped on save.

## Known limits

- Scenarios judge today's data only; backtesting is not built (IMP-030).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_settings.py`
- `tests/integration/test_admin.py`
