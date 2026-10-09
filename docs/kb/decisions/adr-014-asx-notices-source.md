---
id: adr-014-asx-notices-source
title: Decision: ASX's own announcement lists for director and substantial holder notices
category: decisions
summary: Why director trades and substantial holder notices come from ASX's free market-wide announcement lists, read nightly with each notice's PDF, rather than a paid feed or per-company polling.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [coattail, rb-asx-notices, adr-003-yahoo-data-source, adr-008-supabase-flyio]
code: [src/coattail/notices.py, src/coattail/notice_reader.py]
---

## Status

Accepted, 2026-10-09.

## Context

The owner wants each day's ASX director trades (Appendix 3Y) and substantial holder notices (forms 603, 604, 605) for every ASX company, with the details of each, on Coattail, company pages and the dashboard. The notices are ASX announcements: free to read, but published as PDFs, and the build environment can't reach ASX to try them.

## Decision

Read ASX's two market-wide announcement lists each night (`todayAnns.do`, `prevBusDayAnns.do`): two requests cover every company. Keep the notices by title, then download and read each one's PDF (about 50 to 150 a day) with a reader built on the forms' fixed labels. Fetch with a browser's fingerprint, as the ETF report download already does successfully from the owner's PC. Keep what can't be read, marked, with a link to the original.

## Options considered

- **A paid announcements feed** (for example a market data vendor's API): structured and reliable, but a cost and a contract before Sift has users. Likely needed for the public service in any case.
- **Each company's announcements page or ASX's data service, company by company:** about 2,000 requests a night for every company; kept only for a six-month backfill of chosen companies (`--codes`, `--mine`).
- **Titles only, no PDFs:** quick and reliable, but the user would open every PDF to see what happened; the user chose the details.

## Consequences

No cost and one source for both kinds of notice. The reader depends on the forms' wording and on ASX's page layout: a change to either shows as "Not read" notices or a warning that a list page had no announcements ([runbook](kb:rb-asx-notices)), and is fixed in one module with `READER_VERSION` raised and `--reread`. Scanned PDFs can't be read. The build environment can't test against ASX, so the first nights on the owner's PC are the real test (`--dry-run`).

## Revisit when

Sift is hosted for the public (ASX's terms of use for redistribution, and a hosted server's requests may be refused), the reader misses too many notices, or ASX changes the lists.
