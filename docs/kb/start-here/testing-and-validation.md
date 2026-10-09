---
id: testing-and-validation
title: Testing strategy and validation history
category: start-here
summary: How Sift is tested (unit tests with no database, integration tests on a real PostgreSQL, browser checks) and the record of validation performed as it was built.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2026-11-09
source: AS_BUILT §10
related: [ref-tests, change-process]
code: [tests/, tests/conftest.py]
---

## Summary

Current practice: run the whole suite before every push (`.venv/bin/python -m pytest -q`; Windows `.venv\Scripts\python -m pytest -q`), and check changed pages in a browser at desktop and phone widths. Integration tests use their own `asx_test` database, never the live one, and are skipped (not failed) when PostgreSQL isn't running. Every test file and its purpose: [Test catalogue](kb:ref-tests). The history below records how each part was validated when built.

All of the following was executed against a live, disposable PostgreSQL 16 instance (not mocked), in the environment this document was authored in:

### Schema Validation

- Fresh `psql -f db/schema.sql` apply: zero errors
- Re-run of the same script: zero errors (proves `IF NOT EXISTS` / `CREATE OR REPLACE` idempotency)
- Manual insert across all four tables + `SELECT` through `asx_value_screener`: correct joined output

### ORM Round-Trip

- Inserted a `Company`, `DailyPrice`, and `FinancialReport` via the ORM; read back via `session.query(Company).filter_by(...)`; relationships (`company.daily_prices`, `company.financial_reports`) populated correctly

### Valuation Engine, Synthetic Data

Two synthetic companies were seeded directly (not via Yahoo):
- **Company A** (cheap, ROE 18%, D/E 0.2, fully franked 7% cash yield → 10% grossed-up): computed margin of safety ≈ 45.7%, correctly **passed** the default screen
- **Company B** (expensive, ROE 13.3%, D/E 3.0, unfranked 0.125% yield, negative FCF-implied DCF): DCF intrinsic value came out negative → `margin_of_safety_percent` correctly returned `None` rather than a nonsensical negative-of-negative percentage; correctly **failed** the default screen, and correctly appeared only under `--any-of` (on the ROE leg alone)

### Screener CLI

- Default thresholds: correctly returned only the passing company
- Deliberately unreachable threshold (`--min-roe 50`): correctly returned zero rows, no error
- `--any-of`: correctly returned both companies
- `--sector Technology` combined with default `AND` thresholds: correctly returned zero rows (the one Technology company failed the combined criteria)

### Clean-Install Verification

A fresh Python venv built solely from `requirements.txt` (no dev environment carry-over) successfully imported every module in the codebase, including both CLI entrypoints.

### Live Ingestion, First Successful Run (2026-10-01)

Run from the user's own Windows machine (unrestricted network), not the sandboxed dev environment, see [§10.7](kb:testing-and-validation) for that earlier, blocked attempt.

- `run_ingestion` pulled 508 daily price bars (≈2 years of trading days) and 4 annual financial reports per ticker, for all 5 tickers (BHP, CBA, CSL, WES, WOW), zero errors
- `run_valuation` ran without crashing, but **`roe`, `debt_to_equity`, and `margin_of_safety_percent` came back `NULL` for every company**, only `grossed_up_dividend_yield` populated correctly
- **Root cause (confirmed by direct inspection of live `yfinance` 1.7.0 output):** Yahoo's income statement / balance sheet / cash flow row labels are **PascalCase with no spaces** (`NetIncome`, `StockholdersEquity`, `TotalDebt`, `FreeCashFlow`) in this version. `get_annual_fundamentals()` was written against spaced, title-cased labels (`"Net Income"`, `"Stockholders Equity"`), which do not match and so every `.index` lookup silently returned `None`, except `"EBIT"`, which is spelled identically both ways and so worked by coincidence. This is exactly the risk flagged in [§11](#/admin/kb/register), issue #4, below, materialising on the very first live run.
- **Fixed same day**, all row-label strings in `get_annual_fundamentals()` updated to the confirmed-correct PascalCase form (commit `<see §15>`). Diagnostic method: a standalone script dumping `.index` and `.columns` for `get_income_stmt()`, `get_balance_sheet()`, `get_cash_flow()` against a live ticker, kept below for reuse if Yahoo changes field names again.

```python
import yfinance as yf
t = yf.Ticker("BHP.AX")
for label, df in [("INCOME STATEMENT", t.get_income_stmt(freq="yearly")),
                   ("BALANCE SHEET", t.get_balance_sheet(freq="yearly")),
                   ("CASH FLOW", t.get_cash_flow(freq="yearly"))]:
    print(f"=== {label} INDEX ===\n{list(df.index) if df is not None else 'None/empty'}")
    print(f"=== {label} COLUMNS ===\n{list(df.columns) if df is not None else 'None/empty'}\n")
```

- **Fix confirmed the same day.** Re-running ingestion (to overwrite the old `NULL`-populated rows with correctly-mapped data) followed by `run_valuation --all` produced real, non-`NULL` figures for all five companies:

  | Ticker | ROE | D/E | Grossed-Up Yield | Margin of Safety |
  |---|---|---|---|---|
  | BHP | 19.90% | 0.55 | 5.73% | −33.76% |
  | CBA | 13.81% | 2.78 | 4.82% | `NULL` (see note below) |
  | CSL | −17.43% | 0.74 | 3.25% | −143.79% |
  | WES | 36.03% | 1.59 | 4.19% | −74.97% |
  | WOW | 23.73% | 3.44 | 3.64% | −32.51% |

  **Note on CBA's `NULL` margin of safety:** this is expected, not a bug. `engine.py` only attempts a DCF when `free_cash_flow > 0` for the latest `FY` report ([§8.4](kb:valuation-models)). Banks routinely report negative or highly volatile "free cash flow" under the conventional operating-CF-minus-capex definition, because loan book movements dominate operating cash flow, a standard DCF model doesn't meaningfully apply to financial-sector companies. This is a known limitation of applying a single generic DCF across all sectors (see [§11](#/admin/kb/register) for a candidate addition to the known-issues table), not a data or code defect.

  **Note on the negative margins of safety generally:** every company's DCF-implied intrinsic value came out below its current price at default assumptions (8% growth, 9% discount rate). That's a legitimate output, not a bug, it reads as "these five ASX blue chips are not Graham-cheap at current prices and default DCF assumptions," which is an unsurprising result for large, well-covered mega-caps. `screen_asx.py`'s default thresholds correctly returned zero matches on this five-company sample as a result.

### Earlier Blocked Attempt (Sandboxed Dev Environment, 2026-09-15)

Before the user's own machine was used, live ingestion was attempted from a sandboxed dev environment whose outbound network policy explicitly blocks `guce.yahoo.com` and `query2.finance.yahoo.com` (HTTP 403 at the proxy/gateway level, confirmed via proxy diagnostic logs, not a code-level failure). The ingestion code degraded exactly as designed under that failure (created `Company` fallback rows, logged per-ticker errors, returned zero counts, did not crash). This is what first surfaced the general risk later confirmed in [§10.6](kb:testing-and-validation).

### Still Outstanding

- ~~No automated test suite exists yet~~ **Resolved 2026-10-02 - see [§10.12](kb:testing-and-validation).**
- Given the field-name break found in [§10.6](kb:testing-and-validation), the **other** Yahoo-sourced field, `get_price_history()`'s `sharesOutstanding` lookup from `.info`, has not been separately re-verified against live data, though price/volume/market_cap ingestion itself did return correctly ([§10.6](kb:testing-and-validation)). `.info` is a different API surface (plain dict, not a statement DataFrame) and less likely to share this exact failure mode, but it hasn't been explicitly checked.

### Sector-Aware DDM, Synthetic Data (2026-10-02)

Validated against a disposable PostgreSQL instance (not live Yahoo data, the specific combination needed, a real Financial Services company with a clean multi-year negative-FCF-but-growing-dividend history, is awkward to guarantee from whatever happens to be in the live database at test time, so synthetic data gives a controlled, repeatable check):

- **Synthetic bank** (`BANK.AX`, sector `Financial Services`): `free_cash_flow` set **negative in all 4 years** (−$3.0bn to −$3.5bn, modelling loan-book growth dominating operating cash flow, as real banks report) but a real, steadily growing 4-year dividend history ($1.80 → $2.10/share). Old code path: `dcf_fcf > 0` check fails → `dcf_intrinsic_value` and `margin_of_safety_percent` both `NULL`, company invisible to the screener under any threshold. New code path: correctly routed to `ddm.two_stage_ddm()` on `sector == "Financial Services"`.
- **Synthetic miner** (`MINE.AX`, sector `Basic Materials`, control): positive FCF across all 4 years, to confirm the existing DCF path is completely unaffected by this change. Correctly routed to `dcf.two_stage_dcf()`, `valuation_method = 'DCF'`, `dcf_intrinsic_value = 139.4462`, `margin_of_safety_percent = 71.32%`, identical in every run below, regardless of the `--growth-rate` flag's interaction with the DDM path.
- **Per-model default growth rate, confirmed by running the same seeded database twice:**
  - Run 1, no `--growth-rate` flag (should pick each model's own default: 8% DCF / 5% DDM): BANK → `valuation_method = 'DDM'`, `dcf_intrinsic_value = 35.1125`, `margin_of_safety_percent = 28.80%`.
  - Run 2, explicit `--growth-rate 0.08` (should apply uniformly to both models, making BANK's DDM use the same 8% as MINE's DCF): BANK → `dcf_intrinsic_value = 39.8462`, `margin_of_safety_percent = 37.26%`, a higher intrinsic value than Run 1, exactly as expected from a higher assumed growth rate, and matching an earlier routing-only test run with growth-rate held at 8% for both paths.
  - This confirms both halves of the design: left unset, the DDM correctly uses its own more conservative 5% default rather than silently inheriting the DCF's 8%; set explicitly, the override still applies uniformly to whichever model runs, unchanged from pre-DDM behaviour.
- **Screener confirmation:** `screen_asx.py --any-of --min-margin-of-safety 30` correctly returned both companies, with `BANK` showing `valuation_method = DDM` and `MINE` showing `valuation_method = DCF` in the output, confirming the new column surfaces correctly end-to-end, not just in the database.
- **Residual note surfaced by this test, not a defect:** `BANK`'s synthetic `debt_to_equity` (14.0, realistic for a bank's balance sheet) failed the screener's default `--max-debt-equity 0.80` threshold even with a real margin of safety computed, confirming this threshold is structurally unsuited to Financial Services companies regardless of how the DCF-vs-DDM question is resolved. Documented in README.md and [§9](kb:screener-actions) as a threshold-tuning note (use `--max-debt-equity` with a much higher value, or `--any-of`, when screening financials), not treated as a new known-issue since it's a screener-default question, not a valuation-correctness one.
- Schema migration re-verified idempotent across two separate disposable databases: re-running `db/schema.sql` correctly reported `payout_ratio`/`valuation_method already exists, skipping` with no errors each time.
- Test artifacts (seed scripts, both disposable databases) deleted after validation; nothing from this test is part of the committed repository.

### Screener Show-Every-Company Redesign, Synthetic Data (2026-10-02)

User explicitly asked to stop filtering non-matching companies out of `screen_asx.py`'s output and instead show every company with a visible Y/N indicator per criterion. Validated against a disposable PostgreSQL instance with three synthetic companies chosen to exercise every case: a clean pass, a clean fail, and a company with missing input data on some (not all) criteria:

- **`GOOD.AX`** (cheap, strong ROE, low debt, solid franked yield): correctly showed `Y` on all four indicators and `overall = Y`.
- **`BAD.AX`** (expensive, weak ROE, high debt, negligible yield, negative-implying DCF so `margin_of_safety_percent = NULL`): correctly showed `N` on all four indicators (including `mos_ok = N` for the `NULL` margin of safety, not an error) and `overall = N`.
- **`MISS.AX`** (loss-making, no dividend so `grossed_up_dividend_yield` and `margin_of_safety_percent` are both `NULL`, but real, passing `debt_to_equity`): correctly showed `N` for `mos_ok` and `yield_ok` (the two it has no data for), **`Y` for `de_ok`** (the one it does have data for and does clear), and `N` for `roe_ok` (negative ROE, genuinely fails), confirming a company with partial data gets a precise, metric-by-metric readout rather than being blanket-excluded or blanket-marked as failing.
- All three companies appeared in the default (no-filter) run - confirming the headline change: nothing is hidden by default any more.
- `--any-of`: `MISS.AX`'s `overall` correctly flipped from `N` to `Y` (since `de_ok = Y` is enough under "any one of four"), while `GOOD`/`BAD` were unaffected (already all-`Y`/all-`N` respectively, so `AND` vs `OR` makes no difference to them).
- `--passing-only`: correctly reduced the output to just `GOOD.AX` (the only `overall = Y` row), reproducing the pre-change filtered behaviour exactly, as the flag is designed to.
- `--sector Technology`: correctly reduced the output to just `BAD.AX` (the only company in that sector), confirming `--sector` remains a true SQL-level filter, unlike the four criteria.
- `--limit 1`: correctly capped the output to the single top-ranked row (by margin of safety, `GOOD.AX`), confirming the new default-unlimited `--limit` still works as an explicit cap when passed.
- Test artifacts (seed script, disposable database) deleted after validation; nothing from this test is part of the committed repository.

### Trend Indicators, Synthetic Data (2026-10-02)

Validated against a disposable PostgreSQL instance with three synthetic companies chosen to exercise `margin_of_safety_trend`, `fundamentals_trend`, `momentum_ok`, `trap_risk`, `--rank-by momentum`, and the cold-start note, in one pass:

- **`TRAP.AX`**: 4 years of `financial_reports` engineered with ROE declining 20% → 13.3% → 6.7% → 1.7% and revenue declining $900M → $600M, plus a pre-inserted `valuation_metrics` row 45 days in the past (`margin_of_safety_percent = 15.00`) as the trend baseline. Result: `fundamentals_trend = 'DECLINING'` (correctly, from the ROE/revenue direction alone), `margin_of_safety_trend = +24.73` (today's 39.73% computed MoS minus the 15.00% baseline), `mos_ok = Y` (39.73% clears the 20% default), and critically **`trap_risk = Y`** - the composite correctly fired because a cheap company with deteriorating fundamentals is exactly the case it's designed to catch, even though `momentum_ok` was *also* `Y` for this company (the price-driven trend was positive even though the business trend was negative) - confirming the two signals are independent and `trap_risk` looks at fundamentals specifically, not price momentum.
- **`GROW.AX`**: ROE improving 2% → 6% → 12% → 20%, revenue growing $300M → $550M, prior snapshot 45 days ago at `margin_of_safety_percent = 10.00`. Result: `fundamentals_trend = 'IMPROVING'`, `margin_of_safety_trend = +65.84`, `momentum_ok = Y`, and correctly **`trap_risk = N`** despite also passing `mos_ok` - the fundamentals signal correctly distinguishes this from `TRAP.AX` even though both are cheap and both have positive price momentum.
- **`COLD.AX`**: only 1 `FY` report (so `fundamentals_trend` has nothing to compare, `_fundamentals_trend()` correctly returns `None` for `< 2` reports) and no prior `valuation_metrics` row at all (`_prior_margin_of_safety()` correctly returns `None` - no row exists that's `trend_days` old). Result: both trend columns `NULL`, `momentum_ok = N` (a `None` comparison correctly evaluates to not-met, not an error), `trap_risk = N` (also correctly `N` regardless of fundamentals since `mos_ok` was `N` anyway on this company's numbers) - confirming a genuinely new company renders cleanly with blank trend fields rather than crashing or showing misleading data.
- **`--rank-by momentum`**: re-ran the same query with `ORDER BY margin_of_safety_trend DESC NULLS LAST` - correctly reordered (`GROW` first at +65.84, `TRAP` second at +24.73, `COLD` last with `NULL`).
- **Cold-start note**: filtering to `--sector "Health Care"` (isolating `COLD.AX`, the only company with no trend data) correctly triggered the printed "needs roughly 30 days of accumulated daily valuation history" note; the unfiltered 3-company run correctly did **not** print it, since `TRAP`/`GROW` both had real trend values (confirming the note's `any()` check is calibrated at "every row blank," not "any row blank").
- `trap_risk` warning line confirmed printed for `TRAP` only, in the same style as the existing `payout_ratio` warning.
- Test artifacts (seed script, disposable database) deleted after validation; nothing from this test is part of the committed repository.

### Automated Test Suite (`tests/`), Added 2026-10-02

**Known-issue #6, resolved.** Every fix in [§10.1](kb:testing-and-validation)-[§10.11](kb:testing-and-validation) was validated by hand against a disposable PostgreSQL instance - real, not mocked, and genuinely effective at catching the bugs this project has actually hit (numeric overflow, view column ordering, upsert/commit semantics), but manual and not repeatable without re-reading this document and re-typing each scenario. `tests/` formalises the highest-value scenarios already documented above into a `pytest` suite that runs in under a second and can be re-run on every change going forward.

**Two tiers, by design:**

- **`tests/unit/`** - pure functions and `compute_metrics()`, no database at all. `compute_metrics()` takes a `ValuationInputs` dataclass and plain (unpersisted) ORM objects - SQLAlchemy models can be constructed and have their attributes read without ever touching a session - so the DCF-vs-DDM sector routing, per-model growth-rate defaults, `payout_ratio`/`margin_of_safety_percent` sanity caps, `_clamp_to_column_precision()`, and `_fundamentals_trend()` are all covered here, instantly and without any setup. 64 tests.
- **`tests/integration/`** - the parts that genuinely need a real database: `gather_inputs()`'s queries (including the `margin_of_safety_trend` cross-row lookup), `upsert_valuation_metric()`'s overflow clamp actually round-tripping through PostgreSQL, `run_valuation()`'s per-company crash isolation (validated with a real forced exception via `monkeypatch`, not just a skip case), and `screen_asx.py`'s `build_query()`/`annotate_row()` against the real `asx_value_screener` view. 15 tests, requiring a local PostgreSQL instance (`tests/conftest.py` creates the `asx_test` database and applies `db/schema.sql` automatically on first run - set `TEST_DATABASE_URL` to point elsewhere, e.g. a CI database).

**Regression-pinned against real historical figures**, per this project's own suggested-next-step: SUN's documented 3-year FCF average ($2,210.67M, IMP-009), TWR's documented payout ratio (518.70%, from $1.1930 DPS / $0.2300 EPS, IMP-014), and BRN/WHI's exact overflow values (`roic` 10,129.90%, `pb_ratio` ~203M, `roe` 134,600%, IMP-015) are used as literal test fixtures, not synthetic approximations - if any of these formulas regress, the test that catches it cites the exact real-world case that originally found the bug.

**Graceful skip, not a hard dependency.** `tests/conftest.py`'s database-reachability check is deliberately *not* an `autouse` fixture - only `db_session` (and anything that requests it) depends on it, so `tests/unit/` runs and passes identically whether or not Postgres is even installed. `tests/integration/` skips with a clear reason (`pytest.skip(...)`, not a failure) if no database is reachable, so `pytest` is safe to run on a fresh clone before `db/schema.sql` has ever been applied. This was found and fixed during development: an earlier version made the database check `autouse=True` at session scope, which skipped *every* test in the suite - including pure unit tests that never request a database - the moment Postgres was stopped, since every test implicitly depended on the autouse fixture. Caught by literally stopping Postgres and re-running the suite, exactly the kind of check a test suite about testing needs to survive itself.

**Running them:**
```bash
pip install -r requirements-dev.txt
pytest                              # runs both tiers; integration tests skip if no DB is reachable
pytest tests/unit                   # unit tests only, no database needed at all
pytest -m integration               # integration tests only
TEST_DATABASE_URL=postgresql+psycopg2://... pytest   # point at a different test database
```

### Decision Markers, Suggested Actions and Holdings (2026-10-02)

- **77 new tests** (156 total): `test_markers.py` (every band boundary, TWR's special-dividend shape reading as `CUT`), `test_cgt.py` (12-month boundary both sides of the anniversary, 29 February purchases, Australian FY labels, loss ordering in the FY summary), `test_actions.py` (every action rule, each red flag downgrading `BUY`, the CGT timing window), `test_portfolio.py` (partial-sale split preserving the combined cost base to the cent, FIFO across parcels, min-tax choosing a smaller undiscounted gain over a larger discounted one, specific-parcel sales, oversell and sell-before-buy guards, the schema's own `CHECK` constraint), plus markers end to end through `run_valuation_for_company()` with 250 days of real stored prices and five FY reports, and identical held/not-held companies getting `HOLD` vs `BUY`.
- **Migration over live-shaped data:** created a database from the previous `db/schema.sql`, inserted a company with prices and a valuation, then applied the new schema - zero errors, 10 `ALTER TABLE`s, existing values intact and readable through the view alongside the new (empty until re-valued) columns, `holdings` created.
- **CLIs end to end** on five synthetic companies built to hit specific rules: identical fundamentals with a rising price (`GEM`, held, `HOLD`) and a falling one (`KNIFE`, `INVESTIGATE`, "price still making new lows"); a declining business held ~10 months (`FADE`, `SELL`, with "300 units qualify for the CGT discount from 07 Dec 2026 (66 days)"); an expensive held company (`PRICY`, `REVIEW`); and weak cash conversion (`LEAK`). `portfolio.py sell --order min-tax` correctly sold the DRP parcel before the larger, older one, and split $9.95 sale brokerage into $0.50 + $9.45. This run found the `WATCH`-reason gap described in [§9.1](kb:screener-actions), fixed before commit.
- Test databases and seed scripts deleted afterwards.

### Web GUI, Portfolios, Watchlists, Track Record and Admin Console (2026-10-05 to 2026-10-06)

- **556 tests** (426 unit, 130 integration), up from 156 at [§10.13](kb:testing-and-validation). LICs ([§27](kb:lics)) and the real report's layout ([§25.1](kb:etfs-collection)) added 23. Presenting ETFs ([§26](kb:etfs-presentation)) added 25: the ETF page helpers, the ETF APIs, and ETFs kept apart on the dashboard, in portfolios and in watchlists, plus 14 Help entries. ETF collection ([§25](kb:etfs-collection)) added 80: reading the ASX report in two layouts, the performance maths, the raw-price change and the database steps end to end. The admin console ([§24](kb:admin-console)) added 26: the settings registry (`test_settings.py`), scenarios, workings and the admin API (`test_admin.py`), and five knowledge base entries. The knowledge base ([§23](kb:help-knowledge-base)) added 85 of them: integrity checks in `test_knowledge.py`, including one text check per entry, and a served-behind-the-password check. New since then: the web API end to end (`test_gui.py`), signal recording (`test_tracking.py`), track record scoring against 13 months of made-up daily history (`test_track_record.py`), portfolios and the CLI (`test_portfolio.py`), watchlists (`test_watchlists.py`, `test_watchlist_triggers.py`), browser input checks and the same-page write guard (`test_trade_input.py`), and the dashboard's log and stale-data rules (`test_dashboard.py`).
- **Schema:** re-applied (idempotent), upgraded from an older database with existing parcels (moved into "My portfolio"), and built from an empty database. The last caught a table created before the one it refers to, which every pre-existing test database had hidden.
- **Coverage check** (`coverage run -m pytest`, re-run 2026-10-06): 87% of statements overall; 95% to 97% for the admin console's modules (`src/settings.py`, `src/admin/`); 90% to 100% for every module added on 2026-10-05, after tests were added for the still-actionable grouping, both nightly track record commands, the GUI's start-up schema step and unarchiving. Not covered by tests: the Yahoo Finance network calls and the `run_ingestion` / `run_valuation` command wrappers, which are exercised by the nightly job on the user's PC (Yahoo is blocked from the build environment, [§10.7](kb:testing-and-validation)).
- **In the browser:** each stage was driven in headless Chromium against seeded disposable databases at 1280px, 1000px and 390px, light and dark, through every create, edit, delete and error path, before release.
