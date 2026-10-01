# ASX Value Investing Database & Screener — As-Built Document

| | |
|---|---|
| **Repository** | `davidstangherlin/Portfolio` |
| **Default branch** | `main` |
| **Document purpose** | Fault-finding, disaster recovery / rebuild, and third-party (e.g. ChatGPT) code design review |
| **Document version** | 1.0 |
| **Date** | 2026-09-15 |
| **Covers commits** | `d60ef53` (schema), `4f5d297` (pipeline + CLI) |

---

## 1. Executive Summary

This system is a local ASX (Australian Securities Exchange) value-investing research tool. It ingests daily prices and annual financial fundamentals for ASX-listed companies from Yahoo Finance, computes a standard set of value-investing metrics (grossed-up franked dividend yield, Graham Number, 2-stage DCF intrinsic value, margin of safety, and classic ratios), stores everything in PostgreSQL, and exposes a command-line screener that filters companies against configurable Graham/Buffett-style thresholds.

**Status as at this document's date:** code complete and mechanically validated end-to-end against a live PostgreSQL instance using seeded data. Live Yahoo Finance ingestion has **not yet been run successfully from a real internet connection** — it was attempted from a sandboxed development environment whose network policy blocks Yahoo Finance outright (see §8, Known Issues). It should work unmodified from a normal internet connection; this has not yet been confirmed by the user.

**Three-tier architecture:**

```mermaid
flowchart LR
    subgraph External
        YF[Yahoo Finance API]
    end
    subgraph Ingestion["src/ingestion/"]
        YC[yahoo_client.py]
        PI[price_ingestion.py]
        FI[fundamentals_ingestion.py]
    end
    subgraph Storage["PostgreSQL (db/schema.sql)"]
        DB[(companies / daily_prices /\nfinancial_reports / valuation_metrics)]
        VIEW[[asx_value_screener view]]
    end
    subgraph Valuation["src/valuation/"]
        ENG[engine.py]
        CALC[dividends.py / graham.py / dcf.py]
    end
    subgraph CLI
        SCREEN[screen_asx.py]
    end

    YF --> YC --> PI --> DB
    YC --> FI --> DB
    DB --> ENG
    ENG --> CALC
    ENG -->|upsert| DB
    DB --> VIEW --> SCREEN
```

---

## 2. Repository Structure

```
Portfolio/
├── db/
│   └── schema.sql                      PostgreSQL DDL — source of truth for the data model
├── src/
│   ├── config.py                       DB connection resolution (env-var driven)
│   ├── models/                         SQLAlchemy 2.0 ORM layer
│   │   ├── base.py                     Declarative Base
│   │   ├── company.py                  Company model + relationships
│   │   ├── daily_price.py              DailyPrice model
│   │   ├── financial_report.py         FinancialReport model
│   │   └── valuation_metric.py         ValuationMetric model
│   ├── ingestion/                      Yahoo Finance → database
│   │   ├── yahoo_client.py             yfinance wrapper, all external I/O isolated here
│   │   ├── common.py                   get_or_create_company() shared helper
│   │   ├── price_ingestion.py          Upserts daily_prices
│   │   ├── fundamentals_ingestion.py   Upserts financial_reports
│   │   └── run_ingestion.py            CLI entrypoint
│   └── valuation/                      Financial calculations + orchestration
│       ├── dividends.py                Grossed-up (franked) dividend yield
│       ├── graham.py                   Graham Number
│       ├── dcf.py                      2-stage discounted cash flow
│       ├── engine.py                   Pulls DB inputs together, computes, upserts
│       └── run_valuation.py            CLI entrypoint
├── screen_asx.py                       Root-level CLI: the value screener
├── requirements.txt                    Pinned dependency versions
├── .env.example                        Template for local DB credentials
├── .gitignore                          Excludes .venv/, __pycache__/, .env
├── README.md                           Setup + workflow quick-start
└── docs/
    └── AS_BUILT.md                     This document
```

**Total custom code:** ~1,390 lines across 24 Python files + 1 SQL file (line counts current as at this document's date; see §9 for the exact per-file breakdown).

---

## 3. Environment & Prerequisites

| Component | Version used in development/testing | Notes |
|---|---|---|
| Python | 3.11 | 3.11+ required (uses `X \| None` union type syntax throughout) |
| PostgreSQL | 16 | Schema uses only standard SQL + `uuid-ossp` extension; should work on PG 13+ |
| SQLAlchemy | 2.0.52 | Uses 2.0-style `Mapped[]` / `mapped_column()` declarative syntax throughout |
| psycopg2-binary | 2.9.13 | PostgreSQL driver |
| yfinance | 1.7.0 | Unofficial Yahoo Finance client — see §8 for stability caveats |
| pandas | 3.0.5 | yfinance dependency, used directly in `yahoo_client.py` for NaN/date handling |
| python-dotenv | 1.2.3 | Loads `.env` in `src/config.py` |
| tabulate | 0.10.0 | Table formatting in `screen_asx.py` |

Full pinned list: `requirements.txt` (repo root).

---

## 4. Database Design (`db/schema.sql`)

### 4.1 Entity-Relationship Diagram

```mermaid
erDiagram
    companies ||--o{ daily_prices : has
    companies ||--o{ financial_reports : has
    companies ||--o{ valuation_metrics : has

    companies {
        uuid company_id PK
        varchar ticker UK "e.g. BHP.AX"
        varchar company_name
        varchar sector
        varchar industry
        varchar asx_code UK "e.g. BHP"
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }
    daily_prices {
        uuid price_id PK
        uuid company_id FK
        date price_date
        numeric close_price
        bigint volume
        numeric market_cap
        timestamptz created_at
    }
    financial_reports {
        uuid report_id PK
        uuid company_id FK
        int fiscal_year
        varchar period_type "FY | H1 | H2"
        date report_date
        numeric revenue
        numeric ebit
        numeric net_profit_after_tax
        numeric operating_cash_flow
        numeric free_cash_flow
        numeric capital_expenditure
        numeric eps
        numeric total_assets
        numeric total_liabilities
        numeric total_equity
        numeric total_debt
        numeric cash_and_equivalents
        numeric net_tangible_assets
        numeric dividends_per_share
        numeric franking_percentage "default 100.0"
        numeric corporate_tax_rate "default 30.0"
        timestamptz created_at
    }
    valuation_metrics {
        uuid valuation_id PK
        uuid company_id FK
        date as_of_date
        numeric pe_ratio
        numeric pb_ratio
        numeric price_to_fcf
        numeric ev_to_ebit
        numeric roe
        numeric roic
        numeric debt_to_equity
        numeric current_ratio "always NULL - see 8.1"
        numeric uncapped_dividend_yield
        numeric grossed_up_dividend_yield
        numeric dcf_intrinsic_value
        numeric graham_number
        numeric margin_of_safety_percent
        timestamptz created_at
    }
```

### 4.2 Constraints of Note

- `companies.ticker` and `companies.asx_code` are both `UNIQUE`
- `daily_prices` has a `UNIQUE (company_id, price_date)` constraint — one price per company per day, and the upsert logic in `price_ingestion.py` relies on this as its conflict target
- `financial_reports` has a `UNIQUE (company_id, fiscal_year, period_type)` constraint and a `CHECK (period_type IN ('FY', 'H1', 'H2'))`
- `valuation_metrics` has `UNIQUE (company_id, as_of_date)` — one valuation snapshot per company per day
- All foreign keys are `ON DELETE CASCADE` — deleting a company deletes all its prices/reports/valuations
- Indexes: `idx_companies_asx`, `idx_daily_prices_date`, `idx_financials_year` (all `IF NOT EXISTS`, safe to re-run)

### 4.3 `asx_value_screener` View

A `CREATE OR REPLACE VIEW` joining each active company to its **latest** `daily_prices` row and **latest** `valuation_metrics` row (via correlated `MAX(...)` subqueries). This is what `screen_asx.py` queries directly — it never queries the base tables. Columns exposed: `asx_code, company_name, sector, current_price, pe_ratio, pb_ratio, roe, debt_to_equity, grossed_up_dividend_yield, dcf_intrinsic_value, graham_number, margin_of_safety_percent`.

### 4.4 Known Schema Fix Applied

The original schema draft used `TIMESTAMP WITH TIMEZONE`, which is **not valid PostgreSQL** (the correct type is `TIMESTAMP WITH TIME ZONE`). This was corrected across all four tables before the schema was ever applied — see commit `d60ef53`. Confirmed by running the corrected script against a live PostgreSQL 16 instance with zero errors, twice (to prove idempotency).

---

## 5. Configuration (`src/config.py`, `.env.example`)

Connection string resolution order:

1. `DATABASE_URL` environment variable (or `.env` entry) — used verbatim if set
2. Otherwise built from `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` (defaults: `localhost` / `5432` / `asx_value` / `postgres` / empty)

`get_engine()` and `get_session_factory()` are `@lru_cache`d singletons — one engine per process. `get_session()` returns a fresh `Session`; callers are responsible for closing it (all CLI entrypoints use it as a context manager).

**This module never creates or migrates schema** — `Base.metadata.create_all()` is never called anywhere in the codebase. Schema lifecycle is entirely `db/schema.sql`, applied manually via `psql`.

---

## 6. ORM Layer (`src/models/`)

Standard SQLAlchemy 2.0 declarative models, one file per table, mapped **column-for-column** to `db/schema.sql` (verified by direct insert/round-trip testing against a live database — see §10).

**Design pattern used:** relationships are declared via string forward references (e.g. `Mapped[list["DailyPrice"]]`) rather than direct imports, to avoid circular imports between `company.py` and the three child models. This means **models must always be imported via `from src.models import ...`** (which imports `src/models/__init__.py`, registering every model class with SQLAlchemy's mapper registry) — importing a submodule directly (e.g. `from src.models.company import Company`) in isolation, before the other modules have been imported, will fail when the relationship is first resolved.

All `TIMESTAMP WITH TIME ZONE` columns map to `DateTime(timezone=True)` with `server_default=func.current_timestamp()`.

---

## 7. Ingestion Layer (`src/ingestion/`)

### 7.1 `yahoo_client.py` — External I/O Boundary

All Yahoo Finance / `yfinance` calls are isolated in this one module. Nothing else in the codebase talks to the network directly.

- `to_yahoo_symbol(asx_code)` — appends `.AX` if not already present
- `YahooClient.get_profile()` — company name / sector / industry (used only when creating a new `Company` row)
- `YahooClient.get_price_history(period)` — daily close/volume/market-cap bars; market cap is derived as `close_price × sharesOutstanding` (from `yfinance`'s `.info`) since Yahoo's history endpoint doesn't return market cap directly
- `YahooClient.get_annual_fundamentals(max_years)` — pulls income statement, balance sheet, and cash flow statement (annual frequency), maps Yahoo's field names onto our schema's columns
- `YahooClient.get_dividends_per_share(fiscal_year)` — sums per-share dividend payments for a calendar year from `ticker.dividends`

**Every method here is defensive**: wrapped in `try/except Exception`, logs and returns `None`/`[]`/`{}` rather than raising, because Yahoo's field availability is inconsistent across companies and changes without notice. This was a deliberate design decision, not an oversight — see §8.2.

**Field mapping is best-effort.** Example: `free_cash_flow` is read directly from Yahoo if present, otherwise derived as `Operating Cash Flow + Capital Expenditure` (Yahoo reports capex as an already-negative outflow). `total_debt` falls back to `Long Term Debt + Current Debt` if Yahoo's consolidated `Total Debt` field is absent.

**Not sourced from Yahoo at all:** franking percentage, corporate tax rate. Yahoo has no concept of Australian franking credits. These are defaulted in `fundamentals_ingestion.py` (see below).

### 7.2 `common.py` — `get_or_create_company()`

Looks up a `Company` by `asx_code`; if absent, creates one using `YahooClient.get_profile()` data (falling back to the bare ASX code as the company name if the profile fetch fails). Called by both ingestion modules before fetching prices/fundamentals — **this means a `Company` row can exist with no price or financial data at all**, if the network call for profile succeeded (or even failed with a fallback name) but the subsequent price/fundamentals call failed. This was observed directly during testing (see §10.2) and is handled correctly downstream by `engine.py` (skips companies with incomplete data rather than erroring).

### 7.3 `price_ingestion.py`

`ingest_daily_prices(session, asx_codes, period)` — for each ticker: get-or-create the company, fetch the price history, and `INSERT ... ON CONFLICT (company_id, price_date) DO UPDATE` each bar. On conflict, `close_price`, `volume`, and `market_cap` are all overwritten with the new fetch's values (no coalescing — a price is a fact-for-that-day, so the newest fetch should always win).

### 7.4 `fundamentals_ingestion.py`

`ingest_fundamentals(session, asx_codes, max_years)` — same get-or-create pattern, then `INSERT ... ON CONFLICT (company_id, fiscal_year, period_type) DO UPDATE`.

**Important design decision:** on conflict, most numeric columns use `COALESCE(excluded.col, financial_reports.col)` — i.e. **a `NULL` from a fresh fetch never overwrites a previously-stored value**. This guards against a partial/flaky Yahoo response silently wiping out previously good historical data on a re-run. `franking_percentage` and `corporate_tax_rate` are the exception: they are resolved to explicit defaults (`100.0` / `30.0`) in Python *before* the insert if Yahoo doesn't supply them (which it never does), so they are never `NULL` going in and the coalesce question doesn't arise for them.

### 7.5 `run_ingestion.py` — CLI

```
python -m src.ingestion.run_ingestion --tickers BHP CBA CSL --period 1y [--prices-only | --fundamentals-only] [--max-years N]
```

---

## 8. Valuation Layer (`src/valuation/`)

### 8.1 `dividends.py` — Grossed-Up Dividend Yield

Implements the ATO franking credit formula:

```
franking_credit = DPS × franking_fraction × (tax_rate_fraction / (1 − tax_rate_fraction))
gross_dividend  = DPS + franking_credit
grossed_up_yield = (gross_dividend / price) × 100
```

**Design note for reviewers:** `financial_reports.franking_percentage` and `corporate_tax_rate` are stored as **whole-number percentages** (`100.0`, `30.0`) per the schema. The formula as originally specified requires **fractions** (`1.0`, `0.30`) — feeding whole numbers directly into the formula as given produces a mathematically broken result (`1 − 30` is negative). `dividend_yields()` performs the `/100` conversion before calling `gross_dividend()`. This is the single most important formula detail to check if yields ever look wildly wrong.

### 8.2 `graham.py` — Graham Number

```
Graham Number = sqrt(22.5 × EPS × BVPS)
```

`book_value_per_share()` computes `BVPS = total_equity / shares_outstanding`. Returns `None` (not zero, not an exception) whenever EPS or BVPS is `≤ 0`, since Graham's method is explicitly undefined for loss-making or negative-equity companies.

### 8.3 `dcf.py` — Two-Stage DCF

- **Stage 1:** grows the latest `free_cash_flow` at `growth_rate` for `stage1_years` (default 5), discounting each year at `discount_rate`
- **Stage 2:** Gordon Growth terminal value on the final stage-1 FCF, grown at `terminal_growth_rate` in perpetuity, discounted back `stage1_years` periods
- **Equity value** = PV(stage 1) + PV(terminal) + cash − total debt
- **Intrinsic value per share** = equity value / shares outstanding

Defaults: `growth_rate = 8%`, `discount_rate = 9%` (task spec's 8–10% baseline, midpoint chosen), `terminal_growth_rate = 2.5%`, `stage1_years = 5`. All four are CLI flags on `run_valuation.py` — nothing is hardcoded without an override path.

**Validity guard:** raises `ValueError` if `discount_rate ≤ terminal_growth_rate` (the perpetuity formula diverges otherwise).

### 8.4 `engine.py` — Orchestration

For each company: pulls the latest `daily_prices` row and the last `fcf_average_years` (default 3) `financial_reports` rows (`period_type = 'FY'` only — half-year reports are stored but not currently used in valuation), computes every `valuation_metrics` column, and upserts via `INSERT ... ON CONFLICT (company_id, as_of_date) DO UPDATE`.

**Shares outstanding** is not a schema column. It is derived as `market_cap / close_price` from the latest price row, falling back to `net_profit_after_tax / eps` if market cap is unavailable. This value feeds BVPS (→ Graham Number), FCF-per-share (→ price-to-FCF), and the DCF's per-share conversion — **it is the single most consequential derived value in the entire valuation layer**, worth prioritising in any design review.

**DCF free cash flow base is a multi-year average, not just the latest year** (added 2026-10-02, after the SUN finding below). `gather_inputs()` fetches the last `fcf_average_years` `FY` reports (default 3) and `compute_metrics()` uses the simple mean of their `free_cash_flow` values as the DCF's starting point — gracefully averaging over however many years actually have a value (1, 2, or 3+), and returning `None` only if none do. **Every other metric** (ROE, D/E, P/E, P/B, EV/EBIT, dividend yield, Graham Number) still uses only the single latest `FY` report — this is a point-in-time ratio snapshot in every case *except* the DCF, which specifically needed smoothing.

**Why this exists — the SUN case study.** Live-testing against Suncorp Group (SUN) surfaced the problem directly: its reported `free_cash_flow` across FY2023–FY2026 was $742M / $2,497M / $2,550M / $1,585M — a 3.4x swing across 4 years. With the original single-year-only DCF base (the latest year, $1,585M), the computed margin of safety swung from **+34.45% to −9.84%** depending only on which growth/discount-rate scenario was tested (8%/9% vs 3%/11%) — the entire conclusion was an artefact of which year happened to be "latest," not a robust read on value. Averaging over 3 years (→ a $2,210.67M base) produces a materially more defensible number. This is logged as resolved against known-issue #4's residual risk (§11) and is the direct fix for what's now issue #9.

`--fcf-average-years 1` on the CLI reproduces the old single-year behaviour exactly, for anyone who wants to compare or who has a specific reason to weight only the most recent year.

**`current_ratio` is hardcoded to `None`** — the schema has no current-assets/current-liabilities split (only `total_assets`/`total_liabilities`), so a genuine current ratio cannot be derived. This is a deliberate "don't fabricate a number" decision, not a bug.

A company with no price row or no `FY` financial report is skipped entirely (logged as a warning), never valued with partial/garbage inputs.

### 8.5 `run_valuation.py` — CLI

```
python -m src.valuation.run_valuation (--all | --tickers BHP CBA) [--growth-rate D] [--discount-rate D] [--terminal-growth-rate D] [--stage1-years N] [--fcf-average-years N]
```

---

## 9. Screener (`screen_asx.py`)

Queries `asx_value_screener` directly via raw parameterised SQL (`sqlalchemy.text()`), not through the ORM — this view is read-only and reporting-oriented, so Core SQL was chosen over an ORM mapping for simplicity.

**Default thresholds** (all four combined with `AND` by default; `--any-of` switches to `OR`):

| Criterion | Default | Flag to override |
|---|---|---|
| Margin of Safety | `> 20%` | `--min-margin-of-safety` |
| ROE | `> 12%` | `--min-roe` |
| Debt/Equity | `< 0.80` | `--max-debt-equity` |
| Grossed-Up Dividend Yield | `> 4.5%` | `--min-yield` |

Additional flags: `--sector` (exact match filter), `--limit` (default 25), `--any-of`.

**NULL handling:** any criterion column that is `NULL` (e.g. a company with no DCF result because FCF was negative) evaluates to unknown/false in the `WHERE` clause under both `AND` and `OR` — such a company simply never appears rather than causing an error. This was verified directly (see §10.3, Company B).

Output rendered via `tabulate` in `simple` format with 2-decimal-place float formatting.

---

## 10. Testing & Validation Performed To Date

All of the following was executed against a live, disposable PostgreSQL 16 instance (not mocked), in the environment this document was authored in:

### 10.1 Schema Validation
- Fresh `psql -f db/schema.sql` apply: zero errors
- Re-run of the same script: zero errors (proves `IF NOT EXISTS` / `CREATE OR REPLACE` idempotency)
- Manual insert across all four tables + `SELECT` through `asx_value_screener`: correct joined output

### 10.2 ORM Round-Trip
- Inserted a `Company`, `DailyPrice`, and `FinancialReport` via the ORM; read back via `session.query(Company).filter_by(...)`; relationships (`company.daily_prices`, `company.financial_reports`) populated correctly

### 10.3 Valuation Engine — Synthetic Data
Two synthetic companies were seeded directly (not via Yahoo):
- **Company A** (cheap, ROE 18%, D/E 0.2, fully franked 7% cash yield → 10% grossed-up): computed margin of safety ≈ 45.7%, correctly **passed** the default screen
- **Company B** (expensive, ROE 13.3%, D/E 3.0, unfranked 0.125% yield, negative FCF-implied DCF): DCF intrinsic value came out negative → `margin_of_safety_percent` correctly returned `None` rather than a nonsensical negative-of-negative percentage; correctly **failed** the default screen, and correctly appeared only under `--any-of` (on the ROE leg alone)

### 10.4 Screener CLI
- Default thresholds: correctly returned only the passing company
- Deliberately unreachable threshold (`--min-roe 50`): correctly returned zero rows, no error
- `--any-of`: correctly returned both companies
- `--sector Technology` combined with default `AND` thresholds: correctly returned zero rows (the one Technology company failed the combined criteria)

### 10.5 Clean-Install Verification
A fresh Python venv built solely from `requirements.txt` (no dev environment carry-over) successfully imported every module in the codebase, including both CLI entrypoints.

### 10.6 Live Ingestion — First Successful Run (2026-10-01)

Run from the user's own Windows machine (unrestricted network), not the sandboxed dev environment — see §10.7 for that earlier, blocked attempt.

- `run_ingestion` pulled 508 daily price bars (≈2 years of trading days) and 4 annual financial reports per ticker, for all 5 tickers (BHP, CBA, CSL, WES, WOW), zero errors
- `run_valuation` ran without crashing, but **`roe`, `debt_to_equity`, and `margin_of_safety_percent` came back `NULL` for every company** — only `grossed_up_dividend_yield` populated correctly
- **Root cause (confirmed by direct inspection of live `yfinance` 1.7.0 output):** Yahoo's income statement / balance sheet / cash flow row labels are **PascalCase with no spaces** (`NetIncome`, `StockholdersEquity`, `TotalDebt`, `FreeCashFlow`) in this version. `get_annual_fundamentals()` was written against spaced, title-cased labels (`"Net Income"`, `"Stockholders Equity"`), which do not match and so every `.index` lookup silently returned `None` — except `"EBIT"`, which is spelled identically both ways and so worked by coincidence. This is exactly the risk flagged in §11, issue #4, below, materialising on the very first live run.
- **Fixed same day** — all row-label strings in `get_annual_fundamentals()` updated to the confirmed-correct PascalCase form (commit `<see §15>`). Diagnostic method: a standalone script dumping `.index` and `.columns` for `get_income_stmt()`, `get_balance_sheet()`, `get_cash_flow()` against a live ticker — kept below for reuse if Yahoo changes field names again.

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

  **Note on CBA's `NULL` margin of safety:** this is expected, not a bug. `engine.py` only attempts a DCF when `free_cash_flow > 0` for the latest `FY` report (§8.4). Banks routinely report negative or highly volatile "free cash flow" under the conventional operating-CF-minus-capex definition, because loan book movements dominate operating cash flow — a standard DCF model doesn't meaningfully apply to financial-sector companies. This is a known limitation of applying a single generic DCF across all sectors (see §11 for a candidate addition to the known-issues table), not a data or code defect.

  **Note on the negative margins of safety generally:** every company's DCF-implied intrinsic value came out below its current price at default assumptions (8% growth, 9% discount rate). That's a legitimate output, not a bug — it reads as "these five ASX blue chips are not Graham-cheap at current prices and default DCF assumptions," which is an unsurprising result for large, well-covered mega-caps. `screen_asx.py`'s default thresholds correctly returned zero matches on this five-company sample as a result.

### 10.7 Earlier Blocked Attempt (Sandboxed Dev Environment, 2026-09-15)

Before the user's own machine was used, live ingestion was attempted from a sandboxed dev environment whose outbound network policy explicitly blocks `guce.yahoo.com` and `query2.finance.yahoo.com` (HTTP 403 at the proxy/gateway level — confirmed via proxy diagnostic logs, not a code-level failure). The ingestion code degraded exactly as designed under that failure (created `Company` fallback rows, logged per-ticker errors, returned zero counts, did not crash). This is what first surfaced the general risk later confirmed in §10.6.

### 10.8 Still Outstanding
- No automated test suite exists yet (see §12, Recommendations).
- Given the field-name break found in §10.6, the **other** Yahoo-sourced field — `get_price_history()`'s `sharesOutstanding` lookup from `.info` — has not been separately re-verified against live data, though price/volume/market_cap ingestion itself did return correctly (§10.6). `.info` is a different API surface (plain dict, not a statement DataFrame) and less likely to share this exact failure mode, but it hasn't been explicitly checked.

---

## 11. Known Issues & Design Limitations

| # | Issue | Impact | Suggested Resolution |
|---|---|---|---|
| 1 | `current_ratio` always `NULL` | Screener can't filter on liquidity | Add `current_assets`/`current_liabilities` columns to `financial_reports` if this metric matters |
| 2 | Franking % / tax rate default to 100% / 30% for every ingested company | Wrong grossed-up yield for LICs, foreign-domiciled ASX listings, or any partly-franked payer | Manually correct affected rows after ingestion; no automated source exists for this data |
| 3 | Shares outstanding is derived, not stored | A stale/wrong `market_cap` from Yahoo silently skews Graham Number, P/B, FCF/share, and DCF-per-share together | Consider adding a `shares_outstanding` column sourced independently, if data quality issues appear |
| 4 | `yfinance` field names are unversioned and change without notice | **Materialised on the first live run (2026-10-01):** every balance-sheet/income/cash-flow field except EBIT came back `NULL` due to a PascalCase-vs-spaced naming mismatch. Fixed same day — see §10.6. Residual risk: Yahoo can change these labels again at any time | Use the diagnostic script in §10.6 to re-check field names if ROE/D-E/margin-of-safety start coming back `NULL` again after previously working |
| 5 | Yahoo Finance blocked from the sandboxed dev environment used for initial development | Live ingestion couldn't be exercised until moved to the user's own machine (see §10.7) | Resolved — ingestion now runs from the user's own machine, which has normal network access |
| 6 | No automated test suite | Regressions in the valuation formulas would only surface by manual inspection | See §12 |
| 7 | `.env` holds a plaintext DB password | Standard local-dev risk, already `.gitignore`d | Fine for local use; use a secrets manager if ever deployed beyond a single machine |
| 8 | A single generic DCF model is applied to every sector, including banks | Confirmed in practice (§10.6): CBA's `free_cash_flow` is not meaningfully positive under the standard operating-CF-minus-capex definition, since loan book movements dominate it for a bank — DCF is correctly skipped for CBA rather than producing a misleading number, but this means financial-sector companies will generally never get a margin-of-safety figure at all | Acceptable as-is (skip-rather-than-fabricate is the right default); a sector-aware valuation path (e.g. P/B or dividend-discount model for financials) would be the proper fix if screening banks matters |
| 9 | ~~DCF used only the single latest year's `free_cash_flow` as its base~~ **RESOLVED 2026-10-02** | Was highly sensitive to whichever year happened to be most recent — SUN's margin of safety swung +34% to −10% across reasonable growth/discount scenarios purely because of this (§8.4, §10.6) | Fixed: DCF base is now a `fcf_average_years`-year (default 3) simple mean, configurable via `--fcf-average-years` on `run_valuation.py` (set to 1 to restore old behaviour) |

---

## 12. Rebuild Runbook (From Zero)

```bash
# 1. Get the code
git clone https://github.com/davidstangherlin/Portfolio.git
cd Portfolio

# 2. Python environment
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Database (Docker path shown; any PostgreSQL 13+ works)
docker run --name asx-db -e POSTGRES_PASSWORD=change_me -e POSTGRES_DB=asx_value -p 5432:5432 -d postgres:16
psql "postgresql://postgres:change_me@localhost:5432/asx_value" -f db/schema.sql

# 4. Configuration
cp .env.example .env
# edit .env → DATABASE_URL=postgresql+psycopg2://postgres:change_me@localhost:5432/asx_value

# 5. Run the pipeline
python -m src.ingestion.run_ingestion --tickers BHP CBA CSL WES WOW --period 2y
python -m src.valuation.run_valuation --all
python screen_asx.py
```

**Full teardown/reset** (destroys all ingested data, keeps schema definition intact for re-apply):
```bash
psql "$DATABASE_URL" -c "TRUNCATE companies, daily_prices, financial_reports, valuation_metrics CASCADE;"
```

---

## 13. Fault-Finding Guide

| Symptom | Likely Cause | Check / Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | Running a script from outside the repo root, or `PYTHONPATH` not set | Always run `python -m src.x.y` or `python screen_asx.py` **from the repo root** with the venv active |
| `sqlalchemy.exc.OperationalError: could not connect to server` | Postgres not running, or wrong `DATABASE_URL` | `pg_isready`, confirm the container/service is up, re-check `.env` |
| `psycopg2.errors.UniqueViolation: duplicate key ... companies_ticker_key` | Attempting to insert a `Company` that already exists via raw insert instead of `get_or_create_company()` | Use `src.ingestion.common.get_or_create_company()`, or query-then-update if scripting manually |
| Ingestion logs `Cookie/crumb fetch failed` repeatedly, then `possibly delisted; no price data found` | `yfinance` couldn't reach Yahoo at all (network/firewall/proxy block) | Test with `curl -I https://query2.finance.yahoo.com` from the same machine; if that fails, it's network policy, not code |
| Ingestion returns `0` for every ticker but doesn't error | Same as above — check the logs, not just the return value; the code always degrades gracefully rather than crashing | See previous row |
| `screen_asx.py` returns "No companies matched" unexpectedly | Either genuinely no companies clear the bar, or `run_valuation` hasn't been (re)run since the last ingestion | Run `python -m src.valuation.run_valuation --all` before screening; check `valuation_metrics.as_of_date` is recent |
| Grossed-up yield looks absurd (very large or negative) | `franking_percentage`/`corporate_tax_rate` stored incorrectly (e.g. as a fraction `1.0` instead of `100.0`) | These columns must be whole-number percentages per the schema; check `dividends.py`'s `/100` conversion assumption still holds |
| Margin of safety is always `None` for a company with real data | `free_cash_flow` is `None` or `≤ 0` for that company's latest `FY` report — DCF is intentionally not computed in that case | Check the source `financial_reports` row; this is by design, not a bug |
| `TIMESTAMP WITH TIMEZONE` syntax error if re-authoring the schema by hand | Invalid PostgreSQL syntax — correct form is `TIMESTAMP WITH TIME ZONE` | Already fixed in the committed `db/schema.sql`; don't reintroduce this typo |

---

## 14. Notes for External Code Design Review (e.g. ChatGPT)

If handing this document plus the source to another model for review, the highest-value areas to interrogate are:

1. **`src/valuation/dividends.py`** — confirm the franking credit formula and the percentage-to-fraction conversion are correct against the current ATO methodology
2. **`src/valuation/dcf.py`** — confirm the two-stage DCF mechanics (particularly the terminal value formula and the point at which it's discounted back) match standard practice
3. **`src/valuation/engine.py`, `_estimate_shares_outstanding()`** — this single derived value cascades into four other metrics; worth an opinion on whether deriving it from `market_cap / price` is more or less reliable than the NPAT/EPS fallback
4. **`src/ingestion/yahoo_client.py`, `get_annual_fundamentals()`** — field-name mapping was fixed on 2026-10-01 after live data revealed a naming mismatch (see §10.6); a second opinion on whether the corrected PascalCase labels are complete/robust (and whether the fallback chains — e.g. `StockholdersEquity` vs `CommonStockEquity` — pick the right one in edge cases) would be valuable
5. **Upsert/coalesce strategy in `fundamentals_ingestion.py`** — worth confirming the "never let a NULL fetch overwrite good data" design is the right call versus simply always taking the latest fetch
6. **`src/valuation/engine.py`, `_average_free_cash_flow()`** — a straightforward simple mean over 3 years (§8.4); worth a second opinion on whether a recency-weighted average or outlier-trimming would be more defensible than an unweighted mean, particularly for cyclical or recently-restructured companies (SUN's own FY2023 debt collapse — likely a bank-arm divestment — is exactly this kind of structural break a simple mean doesn't account for)

---

## 15. Change Log

| Date | Change |
|---|---|
| 2026-09-14 | `db/schema.sql` created; `TIMESTAMP WITH TIMEZONE` typo fixed to `TIMESTAMP WITH TIME ZONE`; validated against live PostgreSQL |
| 2026-09-14 | Full pipeline built: ORM models, ingestion (`yahoo_client`, `price_ingestion`, `fundamentals_ingestion`), valuation (`dividends`, `graham`, `dcf`, `engine`), `screen_asx.py` CLI; validated end-to-end with synthetic data |
| 2026-09-14 | Repository consolidated onto `main` as the sole/default branch (previously only existed as a feature branch with no base to PR against) |
| 2026-09-15 | Live ingestion attempted from a sandboxed dev environment; blocked by that environment's network policy (Yahoo Finance denied at the proxy). Pipeline re-validated end-to-end using seeded BHP/CBA data to confirm valuation engine and screener remain correct independent of the network issue |
| 2026-09-15 | This As-Built document created |
| 2026-10-01 | First successful live ingestion, run from the user's own Windows machine (PostgreSQL installed natively after Docker was blocked by lack of virtualisation support): 508 price bars + 4 annual reports per ticker across 5 tickers, zero errors |
| 2026-10-01 | Live run exposed a Yahoo field-naming mismatch (`get_annual_fundamentals()` used spaced labels; live API returns PascalCase) causing ROE, D/E and margin of safety to compute as `NULL` for every company. Root-caused via a live diagnostic dump of actual field names, fixed in `src/ingestion/yahoo_client.py`, and pushed |
| 2026-10-01 | Fix confirmed: re-ingested + re-valued all 5 tickers with real, non-`NULL` ROE/D-E/margin-of-safety figures. Pipeline is now fully operational end-to-end on live data. Screener correctly returned zero matches on this sample under default thresholds (none of the five mega-caps clear a 20% margin of safety at current prices) |
| 2026-10-01 | Expanded live-tested ticker list to GMG, LLC, CHC, SUN, RRF. RRF failed to resolve on Yahoo (invalid/delisted code, unresolved). SUN cleared the screen on relaxed ROE (`--min-roe 9`): MoS 34.45%, yield 6.10%, D/E 0.26 |
| 2026-10-02 | Stress-tested SUN's DCF across growth/discount scenarios: margin of safety swung from +34.45% (8%/9%) to +12.50% (5%/10%) to −9.84% (3%/11%) — traced to a single-year FCF base (SUN's `free_cash_flow` varied 3.4x across FY2023–FY2026). Also noted SUN's `total_debt` collapsed ~90% between FY2023 and FY2024, consistent with (unverified) a bank-arm divestment — a likely structural break, not a data error |
| 2026-10-02 | Fixed the root design issue (known-issue #9): `engine.py`'s DCF now averages `free_cash_flow` over the last `fcf_average_years` (default 3) `FY` reports instead of using only the latest year. Configurable via `--fcf-average-years` on `run_valuation.py` (`1` restores old behaviour). Validated by replaying SUN's real 4-year FCF figures against a disposable PostgreSQL instance: confirmed the 3-year average computes exactly as expected ($2,210.67M, matching a manual calculation) and that intrinsic value scales monotonically and correctly across 1-year/3-year/4-year windows |
