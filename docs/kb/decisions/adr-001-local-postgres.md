---
id: adr-001-local-postgres
title: Decision: PostgreSQL as the single store
category: decisions
summary: Why every fact Sift holds, from prices to personal settings, lives in one PostgreSQL database.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [data-model, adr-011-idempotent-schema, adr-006-postgres-full-text-search]
code: [db/schema.sql, src/config.py]
---

## Status

Accepted, 2026-09-15.

## Context

Sift needs reliable storage for market history, valuations, a never-edited track record and people's tax records, with exact decimals, constraints and room to grow to a hosted service.

## Decision

Use PostgreSQL for everything, with the schema in one file (`db/schema.sql`). Use exact `NUMERIC` for money and ratios, foreign keys with cascades, and views where a report needs a join.

## Options considered

- **SQLite:** simpler on one PC, but weaker concurrency, typing and no path to a hosted multi-user service.
- **A document store:** flexible, but the data is relational and the track record needs joins and constraints.
- **Files (CSV, Excel):** no integrity, no concurrent access.

## Consequences

One dependency to install and back up; full text search, JSONB and arrays come built in; hosted PostgreSQL (Supabase) is available for Phase 4.

## Revisit when

Data volume or query load outgrows one database (not expected at public scale for this design).
