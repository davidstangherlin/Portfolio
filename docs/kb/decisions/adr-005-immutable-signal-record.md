---
id: adr-005-immutable-signal-record
title: Decision: a never-edited nightly record, scored by monthly cohort
category: decisions
summary: Why the track record is recorded nightly, never edited, scored one signal per company per month, and can't be backfilled.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [track-record, personal-nightly-results]
code: [src/tracking/signals.py, src/tracking/outcomes.py]
---

## Status

Accepted, 2026-10-05.

## Context

To judge the rules honestly, each call must be the one Sift actually made at the time, and results mustn't be inflated by counting the same call every night.

## Decision

Write each night's calls once (`ON CONFLICT DO NOTHING`), tag them with `RULES_VERSION`, score the first call of each month per company (the cohort) plus action changes, against the same night's average, and keep a permanent monthly summary.

## Options considered

- **Recompute history with today's rules:** uses information the rules didn't have; flatters results.
- **Score every night:** counts one call up to 21 times a month.

## Consequences

Results arrive only after each horizon passes; history before recording began doesn't exist (IMP-026).

## Revisit when

Never for immutability; the scoring method could change with a new rules version.
