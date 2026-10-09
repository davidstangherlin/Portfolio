---
id: adr-011-idempotent-schema
title: Decision: one idempotent schema file instead of migrations
category: decisions
summary: Why the database schema is a single re-runnable file applied at start-up and each night, rather than numbered migrations.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [data-model, setup-and-configuration, rb-page-error]
code: [db/schema.sql, src/apply_schema.py]
---

## Status

Accepted, 2026-10-05.

## Context

Pulling code with a new column broke the live database three times until the schema was applied by hand (IMP-022).

## Decision

Keep the whole schema in `db/schema.sql`, every statement safe to re-run (`IF NOT EXISTS`, guarded blocks), applied in one transaction on start-up and before each nightly run.

## Options considered

- **A migration tool (Alembic):** ordered, reversible migrations, but more machinery for one database.
- **Apply by hand:** what broke.

## Consequences

Upgrades are automatic; the file reads as the current design. Renames and data moves need care to stay re-runnable, and there's no automatic rollback.

## Revisit when

Several databases at different versions must be upgraded (hosting with staging and production).
