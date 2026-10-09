---
id: adr-008-supabase-flyio
title: Decision: Supabase Auth and Postgres, Fly.io hosting
category: decisions
summary: The chosen path to a hosted, multi-user Sift: Supabase for sign-in and the database (Sydney), Fly.io for the app.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [accounts-owners, architecture]
code: [docs/MULTI_USER_PLAN.md]
---

## Status

Accepted, 2026-10-08.

## Context

Sift is moving from one PC to a test group, then the public. Building sign-in, password reset and account security by hand is risky.

## Decision

Use Supabase Auth for sign-in (Phase 3), Supabase Postgres in Sydney for the database and Fly.io in Sydney for the app (Phase 4). One shared screener universe for everyone.

## Options considered

- **Build sign-in in Sift:** full control, but security work and risk.
- **Auth0 or Clerk:** good, but a separate vendor from the database.
- **A single cloud VM:** cheap, but backups, patching and TLS are all manual.

## Consequences

About US$25 a month on Supabase Pro once hosted, plus Fly.io; Auth is free up to 50,000 monthly active users. Not built yet.

## Revisit when

Costs change materially, or a tester requirement (single sign-on, data residency) isn't met.
