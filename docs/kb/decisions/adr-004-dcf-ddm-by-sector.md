---
id: adr-004-dcf-ddm-by-sector
title: Decision: DCF for most companies, DDM for banks, insurers and REITs
category: decisions
summary: Why banks, insurers and REITs are valued with a dividend discount model instead of discounted free cash flow.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [valuation-models, review-hotspots]
code: [src/valuation/engine.py, src/valuation/ddm.py, src/valuation/dcf.py]
---

## Status

Accepted, 2026-10-02.

## Context

Free cash flow means little for a bank (loan movements dominate it), so the DCF left financial and real estate companies without an estimate.

## Decision

Route the sectors 'Financial Services' and 'Real Estate' (Yahoo's spelling) to a two-stage dividend discount model, and record which model priced each company (`valuation_method`).

## Options considered

- **DCF for everyone:** no estimate for banks.
- **Price to book for financials:** a ratio, not a value estimate comparable with the margin of safety.
- **Residual income model:** better for banks in theory, but needs data Yahoo doesn't supply reliably.

## Consequences

Every sector gets an estimate; the sector match is exact, so a misspelt sector falls back to DCF.

## Revisit when

Sector labels from the data source change, or a better bank valuation becomes feasible.
