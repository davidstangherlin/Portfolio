---
id: adr-003-yahoo-data-source
title: Decision: Yahoo Finance as the market data source
category: decisions
summary: Why market data comes from Yahoo Finance through yfinance, the risks that brings, and the alternatives if it fails.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [data-sources, ingestion, rb-yahoo-fields]
code: [src/ingestion/yahoo_client.py]
---

## Status

Accepted, 2026-09-15.

## Context

Sift needs prices, multi-year statements and dividends for about 500 ASX companies, nightly, at no cost, for personal research.

## Decision

Use Yahoo Finance through the yfinance library, isolated in one module (`yahoo_client.py`) so it can be replaced, with every ticker's failure contained and blank fetches never overwriting stored data.

## Options considered

- **A paid data provider (for example Morningstar, EOD Historical Data, Refinitiv):** reliable and licensed for redistribution, but a monthly cost.
- **ASX direct feeds:** authoritative prices but no statements; costly.
- **Company reports by hand:** accurate but not feasible for 500 companies.

## Consequences

Free and broad, but unofficial: field names change without notice (IMP-004) and its terms are for personal use, a risk for a public service (IMP-051).

## Revisit when

Before inviting people outside the household (Phase 5), or if Yahoo blocks requests for more than a week.
