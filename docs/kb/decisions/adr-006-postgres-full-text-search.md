---
id: adr-006-postgres-full-text-search
title: Decision: PostgreSQL full text search, not a search engine
category: decisions
summary: Why Sift's search uses PostgreSQL's built-in full text search and trigram matching instead of a separate search service.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [search]
code: [src/search/indexer.py, src/search/query.py]
---

## Status

Accepted, 2026-10-09.

## Context

Search had to cover every area of Sift, respect who may see what, learn from use and scale to a public service, without another service to run.

## Decision

One `search_index` table with weighted full text vectors, a typo fallback (pg_trgm), facets counted in Python, learning tables, and embeddings stored ready for meaning-based search.

## Options considered

- **OpenSearch or Elasticsearch:** powerful, but another service to host and keep in sync.
- **Typesense or Meilisearch:** simpler engines, still another service.
- **A hosted search API:** cost and sending data out.

## Consequences

No extra service; rebuilds take seconds. Ranking is simpler than a dedicated engine.

## Revisit when

The index passes a few million rows, or meaning-based search needs pgvector (a column change, not a new service).
