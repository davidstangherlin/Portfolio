---
id: adr-009-shared-calls-personal-layer
title: Decision: shared nightly calls with a personal layer
category: decisions
summary: Why the nightly record holds Sift's market call for everyone, with each person's held-share calls recorded separately.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [personal-nightly-results, track-record]
code: [src/tracking/signals.py]
---

## Status

Accepted, 2026-10-09.

## Context

The nightly record used the owner's holdings, so held shares carried the owner's calls in everyone's results.

## Decision

Record Sift's call for someone not holding each share (shared), and each person's calls on shares they hold in `position_snapshots`. People's views lay their calls over the shared ones. Outcomes stay per company and night.

## Options considered

- **Fully personal records:** storage and run time grow with people times companies.
- **Shared only:** loses held-share changes and 'calls that saved money'.

## Consequences

One verdict everyone can compare; storage grows with holdings. Held calls aren't in the monthly verdict.

## Revisit when

People want a personal verdict on their held calls.
