---
id: rb-search-index
title: Runbook: search finds nothing or misses new things
category: operations
summary: How to check the search index's areas and rebuild them when search returns nothing or misses recent changes.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [search]
code: [src/search/indexer.py, src/search/reindex.py]
tables: [search_index, search_index_runs]
---

## Symptoms

Search returns nothing, or misses a company, help article or developer article added recently.

## Impact

Only search; pages and lists work.

## Check

Admin, Search, Search index card: items per area and each area's last rebuild. An area with 0 items or an old date is the problem. Market and Coattail rebuild nightly; help, pages and this knowledge base on every start; personal rows on every save.

## Fix

- Rebuild from Admin, Search (one area or all), or: `python -m src.search.reindex` (add `--area market` for one area).
- A rebuild error in the server window naming a table or column: the schema is behind; see [A page shows an error](kb:rb-page-error).

## Verify

Search for the missing thing.

## Prevent and escalate

A new table or page must be added to the search registers; `tests/unit/test_search_coverage.py` enforces it.
