---
id: rb-data-out-of-date
title: Runbook: data out of date
category: operations
summary: The data chip is amber or a company's figures are older than expected; how to tell a missed night from a single company's problem.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [rb-nightly-run-failed, ingestion, valuation-models]
code: [gui.py, src/ingestion/run_ingestion.py, src/valuation/run_valuation.py]
tables: [daily_prices, valuation_metrics]
---

## Symptoms

- The data chip says "out of date" (newest valuation older than the last weekday's close).
- One company's price or valuation date is older than the others'.

## Impact

Actions and margins of safety use the last stored figures. A public holiday also shows amber, harmlessly.

## Check

1. Hover the data chip: it lists the newest valuation date, price date and the last run's result.
2. If every company is behind: the nightly run didn't finish; use [Nightly run failed](kb:rb-nightly-run-failed).
3. If one company is behind: look up its newest rows:
   ```sql
   SELECT max(price_date) FROM daily_prices WHERE company_id = (SELECT company_id FROM companies WHERE asx_code = 'BHP');
   SELECT max(as_of_date) FROM valuation_metrics WHERE company_id = (SELECT company_id FROM companies WHERE asx_code = 'BHP');
   ```
   A newer price than valuation means its valuation failed; the log names it. No new price usually means a suspended or delisted code.

## Fix

- One company: `python -m src.ingestion.run_ingestion --tickers BHP` then `python -m src.valuation.run_valuation --tickers BHP` (or the whole run).
- Delisted: remove it from `allords.txt`.

## Verify

The chip turns green after the next run, and the company page shows today's date.

## Prevent and escalate

Recurring single-company failures belong in the register with the company code and the log message.
