---
id: rb-short-positions
title: Runbook: short positions aren't loading
category: operations
summary: No new ASIC short position reports, or the Short Positions step fails; how to tell whether ASIC refused the request, hasn't published yet, or changed the file.
version: 1.2
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-01-10
related: [volume-and-short-selling, adr-015-asic-short-positions, rb-nightly-run-failed]
code: [src/ingestion/short_positions.py]
tables: [short_positions]
---

## Symptoms

Coattail, Most shorted says no reports are loaded or the report date is more than a week old; company pages say there's no ASIC report; the nightly log's Short Positions step shows "0 days loaded" for several nights or an "unexpected columns" error.

## Impact

The short-selling card, % short column, Most shorted tab, cautions and short interest triggers go stale. Actions are unaffected (the caution never changes them).

## Check

1. The nightly log (`logs/`), Short Positions step: "N days loaded, M not published yet or holidays, R refused", and any warning: "ASIC refused ... (status 403)" or "Short positions are out of date".
2. Run `python -m src.ingestion.short_positions --dry-run` in the Sift console (`sift_console.bat`): it fetches the newest file and prints the 10 most shorted, saving nothing.
3. `SELECT max(report_date), count(*) FROM short_positions;`

## Fix

- **"relation short_positions does not exist":** the table is created when Sift starts or the nightly run begins, and neither had run since the update. The command now creates it itself; on older code run `python -m src.apply_schema` first.
- **"ASIC refused":** ASIC blocked the automatic download (or the network failed). One night is nothing; every night means downloading by hand, below.
- **"0 days loaded" for a day or two:** normal. ASIC publishes about four business days late, and public holidays have no file.
- **Nothing for a week:** ASIC may be refusing requests or has moved the file. Open ASIC's short position reports table (asic.gov.au, Regulatory resources, Markets, Short selling) in a browser, download the daily files into `data\ASIC` keeping ASIC's file names (they carry the date), and load them: `python -m src.ingestion.short_positions --folder` (or one file with `--file`). The nightly run also loads anything new in that folder. If the address changed, update `URL`.
- **"unexpected columns":** ASIC changed the headings. Compare the file's first line with `parse()`, fix, and add the case to `tests/unit/test_short_positions.py`.
- **Missing history:** `python -m src.ingestion.short_positions --days 365`.

## Verify

The dry run prints products and percentages, and Most shorted shows the latest report.

## Prevent and escalate

Record any file change in the improvement register (IMP-066) with the first lines of the file. If ASIC blocks the requests for good, see [ADR-015](kb:adr-015-asic-short-positions)'s options.
