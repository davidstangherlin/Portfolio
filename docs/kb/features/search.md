---
id: search
title: Search across Sift
category: features
summary: The search index, its areas and registers, ranking, tick-box filters, learning from clicks and votes, synonyms, AI-ready embeddings, and who sees which rows.
version: 1.2
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §32
related: [adr-006-postgres-full-text-search, accounts-owners, developer-kb]
code: [src/search/indexer.py, src/search/query.py, src/search/learning.py, src/search/embeddings.py, src/search/reindex.py]
tables: [search_index, search_index_runs, search_queries, search_clicks, search_feedback, search_synonyms]
---

## Purpose

One search box finds anything a person may see. The index must grow with Sift: every new table or page is either searchable or excluded with a reason, enforced by a test.

## How it works

One search box (top right) for everything the user can see, with a scope switch and a results page with tick-box filters (the user's reference: ServiceNow ESC).

**Index.** `search_index` holds one row per searchable thing: `doc_id` (kind:id), `area`, `kind`, `owner_id`, `code`, `title`, `subtitle`, `body`, `url`, `facets` (JSONB: sector, category, recommendation, topic, codes) and `rank_boost`, with a weighted `search_vector` (code and title A, subtitle B, body C; the code under the `simple` configuration, the rest `english`). `src/search/indexer.py` builds five areas, each replaced as a unit and timed in `search_index_runs`:

| Area | Rows | From |
|---|---|---|
| market | shares, ETFs, LICs | `load_universe` (name, sector, Sift's action), `companies` (industry, description), `etf_rows` (category, issuer, benchmark), `fund_profiles` (description), `fund_holdings` (what each fund holds: "apple" finds the ETFs holding Apple) |
| coattail | fund managers | `coattail.holdings` ([§31](kb:coattail)): holder names and the codes and names of the companies held |
| personal | watchlists, portfolios, what-if scenarios | entries with their notes; open holdings; scenario names and notes |
| help | knowledge articles | `web/knowledge.json`: title, definition, aliases, labels, body; topic = category |
| pages | pages and settings | a list of Sift's pages, and every `src.settings.SETTINGS` entry |

**When it's rebuilt.** Everything after the nightly run (a Search Index step at the end of `scripts/daily_refresh.ps1`); the personal area inside every saved change (`gui.py` `change()`, in a savepoint so a search problem never blocks a save); help and pages at start-up, and everything if the index is empty (`prepare_search()`, after the schema step); and on demand from Admin (Search index card: items, last rebuild, trigger and time per area, and a Rebuild button: `POST /api/admin/search/reindex`) or `python -m src.search.reindex [--area …] [--trigger …]`. A full rebuild of about 700 rows takes under a second, so the planned weekly safety-net rebuild isn't needed: the nightly one is full.

**Query** (`src/search/query.py`, `GET /api/search`). Words are letters and digits only, little words dropped. Each word must match, either stemmed (`english`: dividends finds dividend) or as the start of an unstemmed word (`simple` prefix: wes finds Wesfarmers); stems are never prefixes, so franking doesn't find Franklin. Score: exact code 10, exact title 6, title starting with the query 2, plus `ts_rank_cd` × 4, typo similarity and `rank_boost`. Typo tolerance needs `pg_trgm` (created in a guarded block: without permission the schema still applies and search matches words only): when the words find fewer than 5 results and the query has 5 or more letters, titles with `word_similarity` above 0.42 are added (vangaurd finds Vanguard, about 0.44). Up to 400 candidates; the best 100 are shown, each with a `ts_headline` snippet.

**Tick boxes.** Type, Sector or category, Recommendation, Mine (Held and On a watchlist from open holdings and watchlist items at query time; My lists for watchlists and portfolios themselves) and Knowledge articles (help topic). Counts are disjunctive: each group's counts allow for the boxes ticked in the other groups but not its own. Groups show 8 boxes, then Show more. Ticked boxes live in the URL (`#/search?q=…&type=ETFs`), so Back works.

**Scope.** The box reads left to right: the text, then (behind a divider) the magnifying glass as a real submit button and a pink ▾ that opens Everything / This page: {page} (names only; the user asked for the grey descriptions under each to go). The menu opens right-aligned under the box (full width on phones). Tab goes text, search, scope; Escape closes the menu. On phones the text box gives way so the buttons stay inside it, and the data chip shrinks to its coloured dot (its aria-label still carries the full status). The dashboard and the results page default to Everything, every other page to This page, reset on each page change. Everything: an exact ASX code opens that page directly, anything else `#/search`. This page: a page with a search box (`.tf-search`: the screener, ETF and LIC lists, Coattail's holder cards, watchlist and portfolio tables; `.page-search`: Help) gets the words in it; any other page highlights the words (`mark.find-hit`) and Enter again moves to the next; words not on the page open the results from everywhere, with a line saying so.

**Learning from use** (`src/search/learning.py`, added 2026-10-09 at the user's request; they asked whether to add thumbs up/down and whether search improves over time).

- *Logged searches.* `search_queries` (query, `norm` = its matched words, result count, owner, the search box `scope`, and `impersonated_by`: the admin behind a search made while impersonating, so it isn't mistaken for the person's own). The results page asks the API to log (`log=1`) once per new search and reuses the `query_id` while only tick boxes change, so ticking boxes doesn't inflate counts.
- *Clicks.* Opening a result posts to `/api/search/click` (`fetch` with `keepalive`, so it survives the page change); `search_clicks` holds query, result and position.
- *Thumbs.* Pink thumbs up and down on every result (`thumbs()`), posting to `/api/search/feedback`; `search_feedback` keeps one vote per owner, search words and result (clicking again withdraws it). The user's own vote shows as a filled pink thumb.
- *Boosts.* For the same `norm`, each result gains `0.6 × ln(1 + clicks) + 1.5 × net votes` from the last 180 days, capped at ±3 (an exact code scores 10, an exact title 6), so a liked result climbs for that search without overriding exact matches. Clicks and votes are pooled across users on shared results.
- *Synonyms.* `search_synonyms` (groups of two or more terms, lower case). `variants()` swaps each term found in the query (single words or phrases) for the others in its group, up to 6 versions; a synonym match scores 90% of a typed-word match. Applied at query time, so no rebuild is needed.
- *Retention.* The log is pruned to a year at the nightly rebuild.
- *Admin, Search tab* (`#/admin/search`): the Search index card (moved from the settings page), Meaning-based search (AI) status, Synonyms (add as a comma-separated list, remove with ✕), and Search insights for the last 7, 30, 90 or 365 days: totals, top searches with the share that opened a result, searches that found nothing (the list to fix with synonyms), results with net negative votes, and By person: each person's searches, the share that found nothing and the share that opened a result (impersonated searches left out, counted in the totals line).

**AI-ready** (`src/search/embeddings.py`; the user chose ready-but-off, with a model running inside Sift when switched on).

- `search_index.content_hash` (SHA-1 of title, subtitle and body), `embedding` (`REAL[]`, so it works on any PostgreSQL) and `embedding_model`. A rebuild copies each unchanged row's embedding across (same `doc_id` and hash), so only new or changed rows are embedded again; `embed_missing()` fills the rest in batches of 64.
- The embedder is pluggable: `get_embedder()` returns None (off) unless `SIFT_EMBEDDINGS=local` is set and `sentence-transformers` is installed, when `LocalEmbedder` runs `sentence-transformers/all-MiniLM-L6-v2` (384 numbers per row, about 90MB, CPU) or `SIFT_EMBEDDING_MODEL`. A hosted embedder (Voyage AI, OpenAI) would be another class with the same `name` and `embed()`.
- When on, each search embeds the query once, compares it with every embedded row (one numpy matrix, cached until the index next changes) and blends: a row's score gains `2.0 × similarity` (similarity 0.30 or more), and rows found only by meaning join the results with that score. `/api/admin/search` reports on/off, model and rows embedded.
- At public scale on a host with pgvector, `embedding` becomes `vector(384)` with an HNSW index and the comparison moves into SQL. "Ask AI" answers would take the top results as context for a language model, with links back to them.

**Owners.** Shared rows have no `owner_id`; personal rows carry their owner's ([§33](kb:accounts-owners)), and the query returns only shared rows and the asker's own. A save rebuilds only the saver's personal rows (`reindex(..., everyone=False)`, deleting by area and owner); nightly and manual rebuilds do every user's. "Held" and "On a watchlist" tick boxes, thumbs and clicks are the current user's.

**Keeping up as Sift grows.** Two registers in `src/search/indexer.py`: `SOURCES` (each table that's searched, and the area that reads it) and `EXCLUDED` (each table that isn't, with why: price, statement and performance figures are numbers reached through the company or fund page; logs, layout settings and the index itself have nothing to find). `tests/unit/test_search_coverage.py` fails when `db/schema.sql` gains a table that's in neither, when a register names a table that's gone, and when a menu link in `web/index.html` is missing from `PAGES`. Help articles and admin settings are indexed straight from `web/knowledge.json` and `src/settings.py`, so they need nothing. `CLAUDE.md` records the rule and the steps for future changes. Adding content: a builder function per area in `BUILDERS`, a label in `KIND_LABELS`, and facets in `_values` if it should filter.

**Scale.** Today's index is about 700 rows and rebuilds fully in under a second. Expected growth, and what changes when:

| Stage | Rows | What holds, what changes |
|---|---|---|
| All ASX shares and funds | about 3,000 market rows | No change: PostgreSQL full text with GIN indexes is fast to millions of rows, and the nightly full rebuild stays a few seconds. |
| Test group (multi-user Phase 1) | plus about 50 personal rows per user | Built ([§33](kb:accounts-owners)): personal rows carry `owner_id` and a save replaces only the saving user's rows. |
| Public service | tens of thousands of users | Per-user personal rebuilds as above; market and help stay shared rows (no duplication per user). The query reads at most 400 candidates and counts facets in Python, which stays cheap; beyond that, counts can move into SQL. |
| "Ask AI" or meaning-based search | same rows | Add an embedding column (pgvector, available on Supabase) to `search_index`; the same builders feed it. A separate search engine (OpenSearch, Typesense) isn't needed at any of these sizes. |

**Tests.** `tests/unit/test_search_coverage.py` (every table and menu page accounted for) and a scenario search in `tests/integration/test_search.py` were added with the registers.

**Tests.** `tests/unit/test_search_query.py` (words, query shape) and `tests/integration/test_search.py` (ranking, word starts, typos, tick-box counts, a saved watchlist searchable at once through the API, admin status and rebuild, start-up). Browser-checked at 1400px and 390px: scope menu, results and tick boxes, this-page search on the screener, Help and a company page, the fall-back to everywhere, and the admin rebuild.

### Scopes

The pink ▾ beside the search box chooses where to search: **Everything** (every area a person may see, except the developer knowledge base), **This page** (the page's own filter or highlighting), and, for admins only, **Developer knowledge base** (`scope=devkb` on `/api/search`, only the `devkb` area). See [The developer knowledge base](kb:developer-kb).

## Code map

- `src/search/indexer.py`: areas, builders, the SOURCES, EXCLUDED and PAGES registers
- `src/search/query.py`: matching, ranking and tick boxes
- `src/search/learning.py`: logs, boosts, synonyms, insights
- `src/search/embeddings.py`: meaning-based search (off unless switched on)
- `src/search/reindex.py`: the command for rebuilding

## Data

- `search_index`: one row per searchable thing; owner_id for personal rows, audience 'admin' for developer articles
- `search_queries, search_clicks, search_feedback`: the learning logs
- `search_synonyms`: groups of words that find each other

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Search finds nothing new after a change: rebuild the index; see [Search finds nothing](kb:rb-search-index).
- A test fails naming a new table: add it to SOURCES or EXCLUDED in src/search/indexer.py.

## Known limits

- Meaning-based search is built but off (IMP-041).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_search_query.py`
- `tests/unit/test_search_coverage.py`
- `tests/integration/test_search.py`
- `tests/integration/test_search_learning.py`
