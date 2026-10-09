---
id: rb-asx-notices
title: Runbook: ASX notices aren't loading
category: operations
summary: No new director trades or substantial holder notices, or many marked "Not read"; how to tell whether ASX refused the requests, changed its pages, or the reader missed a layout.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [coattail, adr-014-asx-notices-source, rb-nightly-run-failed]
code: [src/coattail/notices.py, src/coattail/notice_reader.py]
tables: [asx_notices, director_trades, substantial_holdings]
---

## Symptoms

Coattail's Director trades or Substantial holders tab says the latest notice is days old; the nightly log's ASX Notices step warns "no answer" or "no announcements found on the page"; or many notices show "Not read".

## Impact

Coattail, company pages and the dashboard miss the newest notices. Nothing else depends on them.

## Check

1. The nightly log (`logs/`), ASX Notices step: the line "N followed (D director, S substantial holder)" and any warnings.
2. Run `python -m src.coattail.notices --dry-run` in the Sift console (`sift_console.bat`): it fetches today's lists and reads five notices, printing what it found, and saves nothing.
3. `SELECT read_status, count(*) FROM asx_notices WHERE released_at > now() - interval '7 days' GROUP BY 1;` and, for the unread ones, `read_note`.

## Fix

- **"no answer" or a status such as 403:** ASX refused the request. Try again later; if it persists, save the list page from the browser (ASX website, Announcements, Today's announcements, Save as) and load it: `python -m src.coattail.notices --html saved.html`.
- **"no announcements found on the page":** ASX changed the page. Save it from the browser and record it in the register; `parse_list()` in `src/coattail/notices.py` reads the rows.
- **Many "partial" notices:** the reader missed a layout. Open two of them (the Notice link), compare with `src/coattail/notice_reader.py`'s labels, fix, raise `READER_VERSION`, add the case to `tests/unit/test_notice_reader.py`, then `python -m src.coattail.notices --reread`.
- **"failed" notices:** the PDF didn't download; it's retried on the next two nights. After that, `--reread` tries again.
- **Missing history:** `python -m src.coattail.notices --mine` (six months for everything you hold or watch) or `--codes BHP PLS`.

## Verify

The tabs show today's notices, and the dry run prints notices with their details read.

## Prevent and escalate

Record any ASX page or form change in the improvement register with the saved page or PDF. If ASX blocks the requests for good, see [ADR-014](kb:adr-014-asx-notices-source)'s options.
