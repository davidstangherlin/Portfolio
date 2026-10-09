---
id: fault-finding-guide
title: Fault-finding guide
category: operations
summary: Symptom, likely cause and fix for the problems seen so far, from module errors to blank margins of safety.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §13
related: [rb-nightly-run-failed, rb-page-error, rb-database-connection, rb-yahoo-fields]
---

## Summary

A quick lookup table. For the common incidents there are step-by-step runbooks in this section; start there when one matches.

| Symptom | Likely Cause | Check / Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | Running a script from outside the repo root, or `PYTHONPATH` not set | Always run `python -m src.x.y` or `python screen_asx.py` **from the repo root** with the venv active |
| `UndefinedColumn: column ... does not exist` or `relation "holdings" does not exist` | The code is newer than the database schema (IMP-022) | `python -m src.apply_schema`, then re-run the command. The nightly job does this automatically, and so does starting `python gui.py` |
| A Sift page shows "Could not load" | The server hit an error. Since 2026-10-05 the page shows the cause; before that only "Request failed (500)" | Read the message on the page (the full traceback is in the window running `gui.py`). "Missing a table or column" means the fix above |
| Phone can't open the GUI, or the browser keeps asking for a password | `--lan` not used, the firewall rule is missing, the Wi-Fi network is set to Public, or the wrong `GUI_PASSWORD` | Run `python gui.py --lan`, add the `netsh` rule (README, Web GUI), set the network to Private; any username plus the `.env` password |
| `sqlalchemy.exc.OperationalError: could not connect to server` | Postgres not running, or wrong `DATABASE_URL` | `pg_isready`, confirm the container/service is up, re-check `.env` |
| `psycopg2.errors.UniqueViolation: duplicate key ... companies_ticker_key` | Attempting to insert a `Company` that already exists via raw insert instead of `get_or_create_company()` | Use `src.ingestion.common.get_or_create_company()`, or query-then-update if scripting manually |
| Ingestion logs `Cookie/crumb fetch failed` repeatedly, then `possibly delisted; no price data found` | `yfinance` couldn't reach Yahoo at all (network/firewall/proxy block) | Test with `curl -I https://query2.finance.yahoo.com` from the same machine; if that fails, it's network policy, not code |
| Ingestion returns `0` for every ticker but doesn't error | Same as above, check the logs, not just the return value; the code always degrades gracefully rather than crashing | See previous row |
| `screen_asx.py` returns "No companies found" unexpectedly | Since 2026-10-02 the screener shows every company by default ([§9](kb:screener-actions)) - an empty result now means either `--sector`/`--passing-only` filtered everything out, or `run_valuation` hasn't been (re)run since the last ingestion (the view has nothing to join against) | Drop `--sector`/`--passing-only` to confirm; run `python -m src.valuation.run_valuation --all` before screening; check `valuation_metrics.as_of_date` is recent |
| Grossed-up yield looks absurd (very large or negative) | `franking_percentage`/`corporate_tax_rate` stored incorrectly (e.g. as a fraction `1.0` instead of `100.0`) | These columns must be whole-number percentages per the schema; check `dividends.py`'s `/100` conversion assumption still holds |
| Margin of safety is always `None` for a company with real data | For most sectors: `free_cash_flow` is `None`/`≤ 0` across the averaging window. For Financial Services/Real Estate ([§8.3](kb:valuation-models)/[§8.4](kb:valuation-models)): `dividends_per_share` is `None`/`≤ 0` across the same window, these use the DDM, not the DCF, and won't have a `dcf_free_cash_flow`-driven result regardless of FCF | Check the source `financial_reports` rows and `valuation_metrics.valuation_method` (will be `NULL` if neither model ran); this is by design, not a bug |
| Margin of safety is `None` specifically for a bank/insurer/REIT with real dividends | Check `companies.sector` matches `_SECTOR_AWARE_SECTORS` exactly (`"Financial Services"`, `"Real Estate"`, yfinance's exact spelling) | A sector spelled differently (e.g. a stale/partial Yahoo profile) falls through to the DCF path instead of the DDM path and will likely come back `NULL` on negative FCF |
| `TIMESTAMP WITH TIMEZONE` syntax error if re-authoring the schema by hand | Invalid PostgreSQL syntax, correct form is `TIMESTAMP WITH TIME ZONE` | Already fixed in the committed `db/schema.sql`; don't reintroduce this typo |
| `pytest` reports every test in `tests/integration/` skipped | Local PostgreSQL isn't running, or `TEST_DATABASE_URL` points somewhere unreachable | Start Postgres (`service postgresql start` / Windows service), or set `TEST_DATABASE_URL`; `tests/unit/` should still show as passed, not skipped, regardless |
| `pytest` reports *every* test skipped, including `tests/unit/` | A regression of the exact bug found during [§10.12](kb:testing-and-validation)'s own development: the database-reachability fixture became `autouse=True` again, so unit tests started depending on it despite never touching the DB | Confirm `_test_database` in `tests/conftest.py` is not `autouse` - only `db_session` should request it |
