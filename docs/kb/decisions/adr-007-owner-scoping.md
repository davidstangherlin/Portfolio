---
id: adr-007-owner-scoping
title: Decision: scope personal data in the data layer
category: decisions
summary: Why each person's data is filtered by owner inside the domain functions, using a per-request current user, rather than in each route.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [accounts-owners, personal-nightly-results]
code: [src/accounts.py, gui.py]
---

## Status

Accepted, 2026-10-09.

## Context

Sift has about 40 routes that touch personal data, and more are added often. A missed filter in any one would show one person's portfolio to another.

## Decision

Keep the current person in a context variable set by the request middleware (`acting_as`). Every function that reads or writes personal data scopes itself with `current_user_id(session)`; lookups by id use scoped getters that return nothing for someone else's row. With no one set (command line, nightly job, tests), Sift acts as the first admin.

## Options considered

- **Filter in every route:** easy to forget once.
- **PostgreSQL row level security:** strong, but needs a database role per request; planned to reconsider when hosted.
- **A database per person:** strong isolation, heavy to run.

## Consequences

A new route is safe by default; a two-user test pattern proves isolation. Code outside a request must set the person explicitly when acting for someone else.

## Revisit when

When hosted (Phase 4): consider adding row level security as a second line of defence.
