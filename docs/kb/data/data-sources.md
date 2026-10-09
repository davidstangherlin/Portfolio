---
id: data-sources
title: Data sources
category: data
summary: Where every kind of data in Sift comes from, how often it's refreshed, how reliable it is, and what to watch for before Sift is offered to the public.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [ingestion, etfs-collection, analyst-insights, adr-003-yahoo-data-source, ref-dependencies]
code: [src/ingestion/yahoo_client.py, src/etf/asx_report.py, allords.txt]
---

## Purpose

Sift's judgement is only as good as its inputs. This article lists every source so a problem can be traced to it, and so the risks of each are visible when planning.

## Sources

| Data | Source | Refreshed | Stored in | Reliability |
|---|---|---|---|---|
| Which shares are screened | `allords.txt`, the nightly ticker file kept by the owner (not in git) | When edited | `companies` | As good as the list; no official index list is bundled (IMP-011) |
| Share, ETF and LIC prices | Yahoo Finance via yfinance | Nightly | `daily_prices` | Good; occasional gaps; older history was dividend-adjusted (IMP-031) |
| Annual statements | Yahoo Finance | Weekly, a seventh of the shares each night | `financial_reports` | Field names change without notice (IMP-004); shares outstanding derived (IMP-003) |
| Dividends | Yahoo Finance | Weekly, with statements | `dividend_payments` | One-offs flagged and held out |
| Exchange rates | Yahoo Finance | With statements | Used during ingestion | No direct PGK pair; chained through USD (IMP-036) |
| Company descriptions, sector | Yahoo Finance | With statements | `companies` | Sector spelling decides DCF or DDM |
| ETF and LIC facts, NTA, index returns | ASX monthly investment products report (Excel) | Monthly | `etf_monthly`, `asx_index_returns` | Authoritative; NTA about a month old (IMP-033) |
| Fund profiles and holdings | Yahoo Finance | Weekly | `fund_profiles`, `fund_holdings` | Top holdings only |
| Analyst ratings, targets, holders | Yahoo Finance | Weekly, staggered | `analyst_ratings`, `company_insights`, `top_holders` | Thin for ASX companies (IMP-034); context only |
| Portfolios, watchlists, settings | People using Sift | When saved | Personal tables | Entered by the person |

## Before a public release

Yahoo Finance's data is offered for personal use. Showing it to other people in a hosted service may need a licensed data provider; this is recorded as a risk (IMP-051) and should be settled before Phase 5 (testers outside the household) of the multi-user plan.
