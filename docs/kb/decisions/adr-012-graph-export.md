---
id: adr-012-graph-export
title: Decision: a graph export for Neo4j, PostgreSQL stays the source
category: decisions
summary: Why Sift writes a nightly Neo4j-ready export instead of moving data into a graph database or syncing to one live.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [ai-and-graph, adr-001-local-postgres, adr-013-local-mcp-server]
code: [src/graph/export.py, src/graph/entities.py]
---

## Status

Accepted, 2026-10-09.

## Context

The owner wants Sift ready for a knowledge graph (Neo4j) to explore who holds what, fund overlap and relationships across portfolios, without yet running a graph database.

## Decision

Keep PostgreSQL as the only store. Add entity records (managers, holders, linked fund holdings) and write a nightly snapshot as CSV files with a re-runnable `load.cypher`, loadable into Neo4j Desktop or Aura at any time. Personal data is included by default and can be left out (`--shared-only`).

## Options considered

- **Move to Neo4j:** strong for traversals, but loses SQL, constraints and the existing code; two stores for one truth.
- **Live sync to a running Neo4j:** always current, but needs Neo4j installed, a password and a driver now.
- **PostgreSQL graph extension (Apache AGE):** no second database, but not offered on Supabase, where Sift is heading.

## Consequences

No new software to run; the graph is at most a day old. The export's format is the contract: a live sync later writes the same nodes and relationships.

## Revisit when

Graph questions become frequent enough that a day-old snapshot isn't good enough, or a hosted graph is wanted for testers.
