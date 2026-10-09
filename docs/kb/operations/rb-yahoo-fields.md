---
id: rb-yahoo-fields
title: Runbook: Yahoo changed its fields or blocked requests
category: operations
summary: Ratios or margins of safety go blank across many companies, or every fetch fails; how to confirm Yahoo changed and how to adapt.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [ingestion, data-sources, adr-003-yahoo-data-source]
code: [src/ingestion/yahoo_client.py, requirements.txt]
---

## Symptoms

- ROE, debt to equity or margin of safety suddenly blank for many companies that had them.
- Every ticker fails with crumb or cookie errors although the internet works.

## Impact

Valuations keep the last stored statements (a blank fetch never overwrites a stored figure), so damage is limited, but new statements aren't picked up.

## Check

1. In Python, fetch one company and look at the field names:
   ```python
   import yfinance as yf
   t = yf.Ticker("BHP.AX"); print(list(t.balance_sheet.index)[:40])
   ```
   Compare with the names `yahoo_client.py` maps.
2. Check whether a newer yfinance release mentions the change.

## Fix

- Renamed fields: add the new name to the mapping in `yahoo_client.py` (keep the old as a fallback), with a unit test using the new shape.
- Blocking: upgrade yfinance (`pip install yfinance==<new>`), update `requirements.txt`, run the tests.

## Verify

Re-run ingestion for a few tickers, then valuation; the figures return.

## Prevent and escalate

This is the main data risk (IMP-004, IMP-051). If Yahoo becomes unusable, the decision record [Yahoo as the data source](kb:adr-003-yahoo-data-source) lists the alternatives.
