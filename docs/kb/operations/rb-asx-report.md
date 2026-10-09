---
id: rb-asx-report
title: Runbook: the ASX ETF report won't load
category: operations
summary: The monthly ASX investment products report isn't loaded; how to tell if it's simply not out yet, and how to load it by hand.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [etfs-collection, lics]
code: [src/etf/asx_report.py, src/etf/run_etfs.py]
tables: [asx_report_loads, etf_monthly]
---

## Symptoms

ETF and LIC facts or NTA stay on last month; the ETFs step logs that the report couldn't be downloaded.

## Impact

Fund facts and NTA are a month older than usual; prices and returns still update nightly.

## Check

1. The ASX usually publishes the report in the first weeks of the month; before then "not out yet" is normal.
2. `SELECT * FROM asx_report_loads ORDER BY loaded_at DESC LIMIT 3;` shows what has loaded.
3. If the ASX moved or renamed the file, the download fails every night after mid-month.

## Fix

Download the report by hand from the ASX website and load it: `python -m src.etf.run_etfs --report <path to xlsx>` (see `--help` for the exact options), or `--inspect` to see how a changed layout reads.

## Verify

The ETF screener shows the new month's facts.

## Prevent and escalate

A layout change shows as unmapped columns in `--inspect`; record it in the register with the file.
