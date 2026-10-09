---
id: rb-nightly-run-failed
title: Runbook: the nightly run failed or didn't finish
category: operations
summary: What to check and do when the nightly run stops partway, fails a step, or doesn't run at all.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [nightly-run, rb-data-out-of-date, rb-database-connection, rb-yahoo-fields]
code: [scripts/daily_refresh.ps1]
---

## Symptoms

- The data chip in Sift's menu bar is amber: "out of date" or "run problems".
- The newest log in `logs\` has no `Finished` line, or a step logged errors.
- Task Scheduler shows a result other than `0x0` for the Sift task.

## Impact

Prices, valuations and the night's record aren't updated. Pages still work with the last stored figures. A missed night doesn't damage the track record; it simply has no row for that night.

## Check

1. Open the newest `logs\refresh_<date>.log`. Each step starts with `--- Name --- started HH:mm:ss` and ends with `Name took N min`. The last heading without a "took" line is where it stopped.
2. Task Scheduler, the Sift task, Last Run Result:
   - `0xC000013A`: the window was closed or the task was ended from outside (IMP-035). Check the task settings in README, Daily Automation: hidden window, no idle conditions, 4-hour limit.
   - `0x1`: a step failed; read that step's lines in the log.
3. Ingestion step full of `Cookie/crumb fetch failed` or "possibly delisted": Yahoo can't be reached. Test from the same PC: open https://finance.yahoo.com in a browser.
4. Every company fails valuation with "column does not exist": the schema step failed; read its lines (see [A page shows an error](kb:rb-page-error)).

## Fix

- Yahoo unreachable: wait and re-run; if it persists for days, see [Yahoo fields changed](kb:rb-yahoo-fields) and check the yfinance version.
- Run it again by hand: Task Scheduler, right-click the task, Run; or in PowerShell from the Sift folder: `.\scripts\daily_refresh.ps1`. Every step is safe to re-run.
- Database not running: see [Database won't connect](kb:rb-database-connection).

## Verify

The log ends with `Finished`, the data chip is no longer amber, and today's date shows on the dashboard.

## Prevent and escalate

Nightly failures aren't alerted anywhere yet (IMP-048). If a step fails three nights running, raise a register item with the log lines.
