---
id: nightly-run
title: The nightly run
category: operations
summary: What scripts/daily_refresh.ps1 does at 6 pm: each step, its order, how failures are contained, logs and the Task Scheduler settings.
version: 1.5
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-10
next_review: 2027-01-09
source: AS_BUILT §16
related: [rb-nightly-run-failed, rb-data-out-of-date, ingestion, track-record]
code: [scripts/daily_refresh.ps1]
---

## Summary

The nightly run keeps everything current. Its steps, in order: Schema, Ingestion (prices daily, statements weekly), ETFs and LICs, Share Registries (each company's registry from ASX, see [Dividend reinvestment and share registries](kb:drp-and-registry)), ASX Notices (director trades and substantial holders, see [Coattail](kb:coattail)), Short Positions (ASIC's daily short position reports, see [Volume and short selling](kb:volume-and-short-selling)), Valuation, Signal Record, Track Record, Statistics (volatility, beta, likely ranges and chances, see [Statistics](kb:statistics)), Suggested Actions, Search Index, Graph Export (entity records and the Neo4j-ready files in `data/graph/`, see [AI and graph readiness](kb:ai-and-graph)). A failed step doesn't stop the later ones. Each run writes `logs\refresh_<date>.log`, kept 30 days. If a run fails, start with [Nightly run failed](kb:rb-nightly-run-failed).

**Runs cut off partway, and a lighter nightly run (2026-10-06):** from 5 October the user's runs stopped during ingestion at a different point each night (7, 14 and 28 minutes in), with no error in the log, after finishing in about 44 minutes from 2 to 4 October. Task Scheduler's last result was `0xC000013A` (the console-close signal), no sleep or shutdown was logged, and nothing was hung. The task had "Stop if the computer ceases to be idle" on and ran in a visible window, and the cut-offs fell on weekday evenings when the user was at the PC. So the run was being ended from outside (IMP-035). Fixed on the task (hidden window, idle conditions off, 4-hour limit, catch up a missed start; README, Daily Automation) and in the script:
- **Timed steps.** `Invoke-Step` writes each heading as `--- Name --- started HH:mm:ss` and adds `Name took N min` after it, so a stall or a slow step shows in the log. It writes error-output lines as plain text (2026-10-07): Windows PowerShell wraps each line Python logs to stderr as an error record, and a blank one used to appear as `System.Management.Automation.RemoteException`.
- **Weekly fundamentals.** `run_ingestion --weekly-fundamentals` (passed by the nightly script) fetches statements for the seventh of the shares fetched longest ago, never fetched first (`companies.fundamentals_fetched_at`, `due_for_fundamentals`). Statements change only at reporting time, and refetching all of them was about 27 of the 44 minutes; with the ETF and LIC prices (about 14 minutes a night) added this week, the full run would have passed an hour, and with the weekly refresh it's about 40 minutes. A share whose statements request failed outright (network, Yahoo error: `YahooClient.statements_failed`) isn't stamped, so it's retried the next night; one Yahoo simply has no statements for waits a week. Manual runs without the flag fetch every ticker, as before. Dividend payments come from the same step, so a new one shows on the company page's price chart within a week; valuations use each year's reported dividends and are unaffected.
- **One rule for both weekly refreshes.** `src/ingestion/rolling.py` (`nightly_share`) is shared by fundamentals and analyst ratings and holders ([§29](kb:analyst-insights)).
- **Sift's "did not finish" message** now names the usual outside causes and points to the README settings, and an unfinished run counts as still going for 4 hours (`RUN_STILL_GOING_HOURS`), matching the task's limit.

**Step 1b, ETFs and LICs (added 2026-10-06):** `python -m src.etf.run_etfs` runs after share ingestion: last month's ASX Investment Products report if it isn't loaded yet, then prices and distributions for every active ETF and LIC (full history the first time), then ETF performance ([§25](kb:etfs-collection)). A report that isn't out yet or can't be downloaded is logged and the step carries on.

**Step 4, Track Record (added 2026-10-05):** `python -m src.tracking.score_signals` scores every signal whose 1, 3, 6 or 12 months the prices have reached, rebuilds the monthly summary, then deletes detail older than 14 whole months ([§21](kb:track-record)). Re-running it scores nothing twice. Suggested Actions is now step 5.

**Step 3, Signal Record (added 2026-10-05):** `python -m src.tracking.record_signals` runs straight after valuation and writes tonight's `signal_snapshots` ([§21](kb:track-record)). Re-running it the same night changes nothing. A company whose valuation failed tonight is skipped and listed as a WARNING rather than recorded with a stale estimate. Suggested Actions is now step 4.

**Step 0 (added 2026-10-05):** `python -m src.apply_schema` runs before ingestion, so a `git pull` that changes the schema can't leave the night's run failing on every company (IMP-022). The schema runs in one transaction: if it fails, nothing changes and the later steps still run against the existing schema.

**Purpose:** removes the need to run each step by hand (originally three commands: ingestion, valuation, screener; now six, see the steps above) to keep the database current. Designed to be triggered daily and unattended by Windows Task Scheduler, after ASX market close.

**Design decisions:**
- **No stop-on-error chaining** (`;` between steps, not `&&` or `-and`): a transient Yahoo Finance network blip during ingestion should not prevent valuation/screener from still running against whatever data is already in the database from the previous day. Each step's own per-ticker/per-company error isolation ([§7.3](kb:ingestion)-[§7.5](kb:ingestion), [§8.4](kb:valuation-models), IMP-010/#13) already handles failures within a step; this script's job is only to make sure a whole-step failure doesn't cascade into skipping the rest of the pipeline.
- **Single timestamped log file per run** (`logs\refresh_<yyyy-MM-dd_HHmmss>.log`), capturing stdout and stderr from every step (`2>&1` redirect piped through `Add-Content`), so an unattended run can be checked after the fact without having to watch it live.
- **30-day log retention**, pruned at the end of every run (`Get-ChildItem` + `Where LastWriteTime` + `Remove-Item`), so the `logs\` folder doesn't grow unbounded on a machine that's left running this indefinitely.
- **Self-locating repo root** (`Split-Path -Parent $PSScriptRoot`): the script resolves every other path (venv activation, watchlist file, log directory) relative to its own location rather than a hardcoded path, so it keeps working if the repo is cloned or moved elsewhere.
- **Watchlist file is a single variable** (`$WatchlistFile`) at the top of the script, so switching from `allords.txt` to a narrower list (e.g. a sourced ASX 300 file, IMP-011) is a one-line edit.

**Validation performed (2026-10-02, disposable test environment, not the user's machine):**
- Installed PowerShell Core (`pwsh`) to get a real PowerShell interpreter to test against.
- Created a disposable PostgreSQL database and seeded one real company (BHP) via the ORM, so the valuation/screener steps had real data to operate on.
- Ran a Linux-path variant of the script (the only difference from the real script: `.venv/bin/Activate.ps1` instead of `.venv\Scripts\Activate.ps1` - confirmed via `diff`) through `pwsh -NoProfile -File`.
- First attempt failed due to a test-setup artifact (the test copy was run from the wrong directory, so `$PSScriptRoot` resolved incorrectly) - not a script defect; fixed by placing the test copy inside `scripts/` as the real script would be, and re-ran.
- Second run succeeded end-to-end: the log file correctly showed all three phase headers with timestamps, correctly captured the (expected, sandbox-only) Yahoo network failure during ingestion without halting the script, and correctly computed and logged valuation + screener output from the seeded data.
- All test artifacts (test script copy, test `.env`, test watchlist file, `logs/` directory, disposable database) were deleted after validation; nothing from this test run is part of the committed repository.

**Task Scheduler wiring:** see the "Daily Automation" section of `README.md` for the exact one-time GUI setup (trigger time, action command line, recommended settings).
