---
id: personal-nightly-results
title: Each person's nightly results (multi-user Phase 2)
category: features
summary: How the nightly record splits into Sift's shared calls and each person's calls on their own holdings, and which track record views are personal.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §34
related: [track-record, accounts-owners, adr-009-shared-calls-personal-layer]
code: [src/tracking/signals.py, src/tracking/outcomes.py, src/tracking/report.py]
tables: [position_snapshots]
---

## Purpose

With several people, one person's holdings mustn't shape everyone's results. The shared record holds the market call for someone not holding each share; each person's held calls are recorded separately and laid over it in their own views.

## How it works

Before this phase the nightly record ([§21](kb:track-record)) was made with the owner's holdings, so a held share's row carried the owner's call on it (HOLD, SELL, ACCUMULATE, REVIEW) instead of Sift's market call. With several people that mixes one person's portfolio into everyone's results. The user chose shared calls with a personal layer.

**Shared record.** `signal_snapshots` is Sift's call for someone who doesn't hold the share (BUY, INVESTIGATE, WATCH, AVOID, IGNORE), the same for everyone. `record_signals()` builds it from `load_universe(session, today, neutral=True)`, which annotates rows with no positions (`load_annotated_rows(..., positions={})`). The search index's market rows ([§32](kb:search)) use the same neutral rows, so the Recommendation tick boxes are shared. `held` is now only true on rows from before Phase 2.

**Personal layer.** `position_snapshots (owner_id, company_id, snapshot_date)`: units, action, reason and rules version for each active person's call on each share they hold, written by `record_positions()` straight after the shared rows, for the nights just recorded, using `suggest_action()` with that person's `position_summaries()` (so the CGT timing note is theirs too). Rows reference the night's shared row and are pruned with it by cascade; `ON CONFLICT DO NOTHING` keeps them unedited. The nightly log reports how many were written. Storage grows with holdings, not with people times companies.

**A person's view of a night.** `person_nights(session, since)`: every shared row with the current user's call laid over it on nights they held the share (`held` true). Shared rows from before Phase 2 marked held are left out unless they're this person's.

**Moving the old history.** `db/schema.sql` copies every shared row marked held into the first admin's `position_snapshots` (idempotent), and the shared rows stay, still marked held. The monthly summary (`refresh_monthly`) and the shared lists leave them out.

**Scoring.** Outcomes (`signal_outcomes`) belong to a company and night, not a person: what a share did afterwards doesn't depend on who held it, and the benchmark is the same night's average. `fill_outcomes()` scores the shared scorecard nights (first of each month, action changes) as before, plus the nights people's held calls need: each person's first held call of each month on a company, and any night their call changed while they held it the night before. Such extra rows carry `is_cohort` and `is_change` false, so the shared verdict and lists ignore them.

**What is per person.**
- *What changed* (dashboard, `signal_changes`): from `person_nights` for the latest two nights. A move caused by buying or selling (held on one night, not the other) is still not a change.
- *What did I miss? / Calls that saved money* (`missed_and_saved`): each scored night at its longest horizon with the person's own call when they held the share; missed BUY and INVESTIGATE only on nights they didn't hold it and didn't buy within 30 days; saved SELL only on their own held calls.
- *What should I look at now?* (`actionable`): run history from `person_nights`, so "you bought it" and fresh runs are theirs.
- *Is Sift accurate?* and the monthly table stay shared: they judge Sift's market calls. Held calls aren't in the monthly verdict.

**Tests.** `tests/integration/test_personal_record.py`: the shared row is not held and each holder's call is recorded once with units (a second run adds nothing); each person sees their own call laid over the shared one; What changed shows the owner's held-call move and the shared move to the owner, and only the shared move to someone else; a mid-month SELL that only the owner's call makes worth scoring gets an outcome, appears in the owner's saved list and not in anyone else's; old held rows move to the first admin on the schema run, stay invisible to others, and the move is idempotent.

## Code map

- `src/tracking/signals.py`: record_positions(), person_nights(), signal_changes()
- `src/tracking/outcomes.py`: scores the nights people's held calls need
- `src/tracking/report.py`: missed, saved and look-at-now lists per person

## Data

- `position_snapshots`: per person: their call on each held share each night, hung off the shared row

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Someone's 'What changed' is empty while others' aren't: changes caused by buying or selling are left out by design.
- A held call has no outcome: only each person's first held call of a month and nights their call changed are scored.

## Known limits

- Held calls aren't in the monthly verdict, which judges Sift's market calls only.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/integration/test_personal_record.py`
