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

This system is a local ASX (Australian Securities Exchange) value-investing research tool. It ingests daily prices and annual financial fundamentals for ASX-listed companies from Yahoo Finance, computes a standard set of value-investing metrics (grossed-up franked dividend yield, Graham Number, a 2-stage DCF or, for Financial Services/Real Estate companies, a Dividend Discount Model intrinsic value, margin of safety, and classic ratios), stores everything in PostgreSQL, and exposes a command-line screener that lists every company annotated with Y/N pass/fail indicators against configurable Graham/Buffett-style thresholds (optionally filterable down to just the companies passing, via `--passing-only`), four decision markers (§8.7) and a suggested action with its reason (§9.1). A parcel-level holdings table with Australian CGT record keeping (§19) lets held companies get HOLD / REVIEW / SELL.

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
        CALC[dividends.py / graham.py / dcf.py / ddm.py]
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
│   │   ├── holding.py                  Holding model - one share parcel (§19)
│   │   └── valuation_metric.py         ValuationMetric model
│   ├── ingestion/                      Yahoo Finance → database
│   │   ├── yahoo_client.py             yfinance wrapper, all external I/O isolated here
│   │   ├── common.py                   get_or_create_company() shared helper
│   │   ├── price_ingestion.py          Upserts daily_prices
│   │   ├── fundamentals_ingestion.py   Upserts financial_reports
│   │   └── run_ingestion.py            CLI entrypoint
│   ├── valuation/                      Financial calculations + orchestration
│   │   ├── dividends.py                Grossed-up (franked) dividend yield
│   │   ├── graham.py                   Graham Number
│   │   ├── dcf.py                      2-stage discounted cash flow (most sectors)
│   │   ├── ddm.py                      2-stage dividend discount model (Financial Services / Real Estate)
│   │   ├── markers.py                  Earnings quality, price position, dividend reliability, data confidence (§8.7)
│   │   ├── engine.py                   Pulls DB inputs together, picks DCF vs DDM by sector, upserts
│   │   └── run_valuation.py            CLI entrypoint
│   ├── portfolio/                      Your holdings (§19)
│   │   ├── cgt.py                      Australian CGT arithmetic: cost base, 12-month discount, FY summary
│   │   └── holdings.py                 Parcel add/sell (with splitting)/delete, position summaries
│   └── screening/
│       └── actions.py                  Suggested action + reason per company (§9.1)
├── screen_asx.py                       Root-level CLI: the value screener
├── portfolio.py                        Root-level CLI: record parcels, list positions, CGT report (§19)
├── requirements.txt                    Pinned dependency versions
├── requirements-dev.txt                requirements.txt + pytest (§10.12)
├── pytest.ini                          Test discovery config (testpaths, pythonpath, integration marker)
├── .env.example                        Template for local DB credentials
├── .gitignore                          Excludes .venv/, __pycache__/, .env, logs/, watchlist files
├── README.md                           Setup + workflow quick-start
├── scripts/
│   └── daily_refresh.ps1               Windows Task Scheduler automation (§16)
├── tests/                              pytest suite (§10.12, known-issue #6)
│   ├── conftest.py                     DB-reachability check, test-DB creation/schema apply, truncate-between-tests fixture
│   ├── unit/                           No database - pure functions + compute_metrics()
│   │   ├── _builders.py                In-memory Company/DailyPrice/FinancialReport/ValuationInputs factories
│   │   ├── test_dividends.py, test_graham.py, test_dcf.py, test_ddm.py
│   │   ├── test_engine.py              Sector routing, overflow clamping, trend fields - real historical regressions
│   │   ├── test_markers.py, test_cgt.py, test_actions.py
│   └── integration/                    Needs a real local PostgreSQL instance
│       ├── test_schema.py              Idempotent apply, view column coverage
│       ├── test_valuation_pipeline.py  gather_inputs/upsert/run_valuation crash isolation, markers end to end
│       ├── test_screener.py            build_query()/annotate_row() against the real view, held vs not-held actions
│       └── test_portfolio.py           Parcel splitting, brokerage apportionment, sell order, guards
└── docs/
    └── AS_BUILT.md                     This document
```

**Total custom code:** ~1,390 lines across 24 Python files + 1 SQL file (line counts current as at this document's date; see §9 for the exact per-file breakdown) - plus `tests/`, a 156-test suite (§10.12, §10.13).

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
        numeric payout_ratio "added 2026-10-02, flags special dividends"
        numeric dcf_intrinsic_value
        numeric graham_number
        numeric margin_of_safety_percent
        varchar valuation_method "added 2026-10-02: 'DCF' or 'DDM', see 8.5/known-issue 8"
        numeric margin_of_safety_trend "added 2026-10-02: see 8.6/known-issue 17"
        varchar fundamentals_trend "added 2026-10-02: IMPROVING/STABLE/DECLINING, see 8.6"
        numeric cash_conversion "decision marker, see 8.7"
        varchar earnings_quality "STRONG/ADEQUATE/WEAK"
        numeric price_vs_200d "decision marker, see 8.7"
        numeric range_position_52w "0-100"
        varchar dividend_trend "GROWING/STEADY/CUT/NONE"
        varchar data_confidence "HIGH/MEDIUM/LOW"
        timestamptz created_at
    }
    holdings {
        uuid holding_id PK
        varchar asx_code "joined to companies.asx_code, no FK - see 19"
        numeric units
        varchar acquisition_method "PURCHASE/DRP/BONUS/TRANSFER/OTHER"
        date buy_date
        numeric buy_price
        numeric buy_brokerage
        date sell_date "NULL while held"
        numeric sell_price
        numeric sell_brokerage
        varchar broker
        text notes
        uuid split_from_id FK "self-reference for partial sales"
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

A `CREATE OR REPLACE VIEW` joining each active company to its **latest** `daily_prices` row and **latest** `valuation_metrics` row (via correlated `MAX(...)` subqueries). This is what `screen_asx.py` queries directly — it never queries the base tables. Columns exposed: `asx_code, company_name, sector, current_price, pe_ratio, pb_ratio, roe, debt_to_equity, grossed_up_dividend_yield, dcf_intrinsic_value, graham_number, margin_of_safety_percent, payout_ratio`.

**Hard-won `CREATE OR REPLACE VIEW` constraint, worth remembering for any future column addition:** PostgreSQL only allows appending new columns at the **end** of an existing view's column list — it cannot insert a column in the middle, even though the underlying `SELECT` is otherwise free to change. Placing `payout_ratio` between `grossed_up_dividend_yield` and `dcf_intrinsic_value` (its more "logical" position) failed with `ERROR: cannot change name of view column "dcf_intrinsic_value" to "payout_ratio"` when tested against a database that already had the view from before this column existed — caught in testing, before it ever reached the live database, by simulating exactly that upgrade path. `payout_ratio` is appended at the end of the `SELECT` instead; this has no effect on CLI output order since `screen_asx.py` selects columns by name, not position.

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

`ingest_daily_prices(session, asx_codes, period, delay_seconds)` — for each ticker: get-or-create the company, fetch the price history, and `INSERT ... ON CONFLICT (company_id, price_date) DO UPDATE` each bar. On conflict, `close_price`, `volume`, and `market_cap` are all overwritten with the new fetch's values (no coalescing — a price is a fact-for-that-day, so the newest fetch should always win).

**Per-ticker isolation (added 2026-10-02):** each ticker's processing is wrapped in its own `try/except` — an unexpected failure (network blip, malformed response, DB error) is logged via `logger.exception` (full traceback) and `session.rollback()`'s that ticker's partial work, then the loop continues to the next ticker rather than aborting the whole run. This matters once `asx_codes` is large: hitting at least one edge-case ticker over a few hundred is likely, and losing the rest of the batch to one bad ticker would be a costly failure mode. Validated directly: a simulated crash on ticker 2-of-4 was caught and logged, the batch continued to tickers 3 and 4, and the database ended up with exactly the 3 successful companies and no orphaned/partial row for the failed one (the `session.rollback()` cleanly undoes that ticker's `get_or_create_company()` flush too).

`delay_seconds` sleeps between tickers to reduce the chance of Yahoo's informal rate limiting on a large batch (there's no officially documented limit to tune against — this is a precaution, not a guarantee).

### 7.4 `fundamentals_ingestion.py`

`ingest_fundamentals(session, asx_codes, max_years, delay_seconds)` — same get-or-create pattern, per-ticker isolation, and delay pacing as `price_ingestion.py` above, then `INSERT ... ON CONFLICT (company_id, fiscal_year, period_type) DO UPDATE`.

**Important design decision:** on conflict, most numeric columns use `COALESCE(excluded.col, financial_reports.col)` — i.e. **a `NULL` from a fresh fetch never overwrites a previously-stored value**. This guards against a partial/flaky Yahoo response silently wiping out previously good historical data on a re-run. `franking_percentage` and `corporate_tax_rate` are the exception: they are resolved to explicit defaults (`100.0` / `30.0`) in Python *before* the insert if Yahoo doesn't supply them (which it never does), so they are never `NULL` going in and the coalesce question doesn't arise for them.

### 7.5 `run_ingestion.py` — CLI

```
python -m src.ingestion.run_ingestion (--tickers BHP CBA CSL | --tickers-file watchlist.txt | both) [--period 1y] [--prices-only | --fundamentals-only] [--max-years N] [--delay SECONDS]
```

**`--tickers-file`** (added 2026-10-02) reads ASX codes from a plain text file — one or more per line, whitespace- or comma-separated, blank lines and `#`-comments ignored. This exists specifically for large watchlists (e.g. a full index's constituents) where typing hundreds of codes on the command line isn't practical. `--tickers` and `--tickers-file` can be combined; the combined list is deduplicated case-insensitively, preserving first-seen order. Validated directly against a sample file mixing comma-separated, whitespace-separated, commented, and duplicate (differently-cased) entries — all parsed and deduplicated correctly.

**`--delay`** (added 2026-10-02) — see §7.3.

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

**`payout_ratio` companion metric (added 2026-10-02, in `engine.py` not `dividends.py` — see §8.4).** A high grossed-up yield on its own can't distinguish a genuinely strong, sustainable dividend from a one-off special distribution. Found in practice at 500-ticker scale: Tower Limited (TWR) showed a 106.85% grossed-up yield driven by a single `FY` where `dividends_per_share` ($1.1930) was 519% of that year's `eps` ($0.2300) — three prior years all showed normal 12-82% payout ratios, making FY2025 a clear outlier consistent with a special dividend or capital return, not ordinary income. `payout_ratio = (dividends_per_share / eps) * 100` is now stored alongside the yield and surfaced in `screen_asx.py`'s output with a `>150%` warning (the user explicitly chose "flag, don't hide" over nulling the yield out or leaving it unaddressed). Same `NUMERIC(6,2)` overflow risk as `margin_of_safety_percent` (near-zero/negative EPS against a real dividend) — guarded with the same "return `None` past a sanity threshold" pattern rather than crashing.

### 8.2 `graham.py` — Graham Number

```
Graham Number = sqrt(22.5 × EPS × BVPS)
```

`book_value_per_share()` computes `BVPS = total_equity / shares_outstanding`. Returns `None` (not zero, not an exception) whenever EPS or BVPS is `≤ 0`, since Graham's method is explicitly undefined for loss-making or negative-equity companies.

### 8.3 `dcf.py` / `ddm.py` — Two-Stage DCF and Dividend Discount Model

**`dcf.py` — Two-Stage DCF** (used for most sectors):
- **Stage 1:** grows the latest `free_cash_flow` at `growth_rate` for `stage1_years` (default 5), discounting each year at `discount_rate`
- **Stage 2:** Gordon Growth terminal value on the final stage-1 FCF, grown at `terminal_growth_rate` in perpetuity, discounted back `stage1_years` periods
- **Equity value** = PV(stage 1) + PV(terminal) + cash − total debt
- **Intrinsic value per share** = equity value / shares outstanding

Defaults: `growth_rate = 8%`, `discount_rate = 9%` (task spec's 8–10% baseline, midpoint chosen), `terminal_growth_rate = 2.5%`, `stage1_years = 5`. All four are CLI flags on `run_valuation.py` — nothing is hardcoded without an override path.

**Validity guard:** raises `ValueError` if `discount_rate ≤ terminal_growth_rate` (the perpetuity formula diverges otherwise).

**Sanity guard on `margin_of_safety_percent()`** (added 2026-10-02, known-issue #12): returns `None` rather than a wild, DB-overflowing percentage when `dcf_intrinsic_value` is implausibly small relative to price. Found in practice at 500-ticker scale — a micro-cap produced a −128,521.87% "margin of safety," which crashed the entire valuation run until this guard (and the per-company isolation below) were added.

**`ddm.py` — Two-Stage Dividend Discount Model** (added 2026-10-02, known-issue #8; used only for Financial Services / Real Estate — see §8.4 for the sector routing logic):
- Same two-stage mechanics as `dcf.py` (stage-1 explicit growth for `stage1_years`, then a Gordon Growth terminal value), substituted onto `dividends_per_share` instead of `free_cash_flow`:
  `PV(stage1) = Σ D·(1+g)^t / (1+r)^t`, terminal value on the final stage-1 dividend, discounted back the same way.
- **Intrinsic value per share** = PV(stage 1) + PV(terminal) — directly a per-share figure, with **no separate cash/debt netting and no `shares_outstanding` input**: dividends are already paid out of post-tax, post-financing earnings, so there's nothing left to add back or net off, and this path doesn't carry the shares-outstanding estimation risk flagged in known-issue #3.
- Defaults: `growth_rate = 5%` (dividend growth is typically steadier/lower than FCF growth — a deliberate difference from `dcf.py`'s 8% default), `discount_rate = 9%`, `terminal_growth_rate = 2.5%`, `stage1_years = 5`. Reuses the same `--growth-rate`/`--discount-rate`/`--terminal-growth-rate`/`--stage1-years` CLI flags as the DCF path (see §14 for the deliberate simplification this represents — one global assumption set, not a second set of per-sector CLI flags).
- **Why dividends instead of FCF for these sectors:** banks, insurers and REITs routinely report negative or highly volatile "free cash flow" under the standard operating-CF-minus-capex definition, because loan book movements, policy reserve movements and property revaluations dominate it rather than the kind of reinvestment capex the DCF model assumes (confirmed in practice — see §10.6's note on CBA). Dividends are the natural analogue: these are dividend-driven business models almost by definition, and typically pay out a high, relatively stable share of earnings.
- Same multi-year averaging as the DCF's FCF base: `_average_dividend_per_share()` in `engine.py` uses the mean `dividends_per_share` across the same `fcf_average_years` window, for the same single-year-volatility reasons documented in §8.4 for the DCF (and consistent with the `payout_ratio` warning in §8.1 for a special-dividend year).
- Returns `None` if the base dividend is `≤ 0` (a non-dividend-paying financial/REIT correctly gets no DDM intrinsic value rather than a fabricated one) — same "skip rather than fabricate" philosophy used everywhere else in this codebase.

### 8.4 `engine.py` — Orchestration

For each company: pulls the latest `daily_prices` row and the last `fcf_average_years` (default 3) `financial_reports` rows (`period_type = 'FY'` only — half-year reports are stored but not currently used in valuation), computes every `valuation_metrics` column, and upserts via `INSERT ... ON CONFLICT (company_id, as_of_date) DO UPDATE`.

**Sector-aware DCF-vs-DDM routing** (added 2026-10-02, known-issue #8, resolved): `compute_metrics()` checks `company.sector` against `_SECTOR_AWARE_SECTORS = {"Financial Services", "Real Estate"}` (spelled exactly as yfinance's `.info["sector"]` returns them for ASX companies) and picks the model accordingly — `ddm.two_stage_ddm()` for those two sectors, `dcf.two_stage_dcf()` for everything else. Both write into the same `dcf_intrinsic_value` column (no schema duplication), with a new `valuation_method` column (`'DCF'` / `'DDM'` / `NULL`) recording which one actually ran, so the screener and any downstream review can tell the two kinds of number apart rather than treating every `dcf_intrinsic_value` identically. `margin_of_safety_percent()` is computed identically either way — it only needs an intrinsic value and a price, not which model produced the intrinsic value.

**`growth_rate` defaults per-model when not explicitly set on the CLI.** `compute_metrics()`'s `growth_rate` parameter defaults to `None`, not a fixed value: when `None`, it resolves to `ddm.DEFAULT_GROWTH_RATE` (5%) for sector-aware companies or `dcf.DEFAULT_GROWTH_RATE` (8%) otherwise, reflecting that sustained dividend growth is typically a more conservative assumption than FCF growth. Passing an explicit `--growth-rate` on `run_valuation.py` overrides this and applies uniformly to whichever model runs for a given company, same as before. `discount_rate`, `terminal_growth_rate` and `stage1_years` are shared across both models unconditionally (no per-sector default) — only the stage-1 growth assumption was judged to need a different starting point by sector; see §14, item 7 for the design trade-off this represents.

**Why this was needed — the CBA finding (§10.6), generalised.** The first live run already showed CBA getting a `NULL` margin of safety because its `free_cash_flow` wasn't meaningfully positive under the standard DCF definition — correctly skipped rather than fabricated, but it meant **every** Financial Services and Real Estate company would silently never get a margin-of-safety figure, a real coverage gap for a value screener (banks, insurers and REITs are a meaningful slice of the ASX). The fix doesn't change the "don't fabricate" philosophy — it changes which input the model is built on for these sectors, since dividends (not FCF) are the value driver that actually behaves sensibly for them.

**Validated with synthetic data** (not live, since this needs a specific sector/FCF combination that's awkward to guarantee from a live sample): seeded a synthetic bank (Financial Services sector, `free_cash_flow` negative in every one of 4 years — realistic for a bank's loan-book-dominated operating cash flow — but a real, growing 4-year dividend history) against a disposable PostgreSQL instance alongside a synthetic miner (ordinary sector, positive FCF, as a control). Confirmed: the bank correctly got `valuation_method = 'DDM'` with a real, non-`NULL` margin of safety (37.26% in the test data) where the old code would have left it `NULL`; the miner correctly got `valuation_method = 'DCF'`, completely unaffected by the change. Both appeared correctly in `screen_asx.py`'s output, with the new `valuation_method` column distinguishing them.

**Per-company isolation and incremental commits** (added 2026-10-02, known-issue #13): `run_valuation()` now commits after each company rather than once at the end, and wraps each company in its own try/except. Before this fix, a single company's unhandled exception anywhere in the batch would lose every other company's already-computed work too, since nothing had been committed yet — this is exactly what happened on the first 500-ticker run, before the margin-of-safety guard above existed. Matches the ingestion layer's existing per-ticker isolation pattern (§7.3).

**Generic column-overflow guard on every field, not just margin_of_safety_percent/payout_ratio** (added 2026-10-02, known-issue #15): `upsert_valuation_metric()` now runs every field through `_clamp_to_column_precision()` immediately before the insert — nulling (and logging) any value whose magnitude would overflow its target `NUMERIC` column, derived directly from the column definitions in `db/schema.sql`, rather than crashing. This exists because the failure mode turned out not to be isolated to the two fields first found: at 500-ticker scale, `BRN`'s `roic` hit 10,129.90% (over `NUMERIC(6,2)`'s 9999.99 limit) and `WHI`'s `pb_ratio` hit ~203 million (over `NUMERIC(10,2)`'s ~100 million limit) with `roe` simultaneously at 134,600% — both crashed their company's entire valuation row despite the crash-isolation fix (#13) correctly containing the damage to just those two companies. The margin_of_safety_percent/payout_ratio guards (§8.3, §8.1) keep their tighter, business-meaningful 5000% sanity threshold and are unaffected by this change; this is an additional, purely mechanical backstop covering every other field. Validated by replaying both companies' exact failing payloads from their crash tracebacks against a live PostgreSQL instance: both now upsert successfully, with only the pathological field nulled and every other valid field (e.g. BRN's `pe_ratio`, `pb_ratio`, `roe`) preserved.

**`upsert_valuation_metric()` returns the post-clamp metrics, and callers use that return value** (added 2026-10-02, same-day follow-up). Caught directly in the user's own live run: the re-run after the guard above landed still printed `WHI: ... ROE=134600% ...` in `run_valuation.py`'s console summary, even though the database correctly stored `NULL` for that field — because `run_valuation_for_company()` was returning the pre-clamp `metrics` dict it already had, not the clamped one `upsert_valuation_metric()` computed internally and discarded. Not a data bug (the database was always correct), but a real console-vs-database inconsistency that could mislead anyone reading terminal output without cross-checking the DB. Fixed by having `upsert_valuation_metric()` return the clamped dict and `run_valuation_for_company()` return *that*, so `results` (and therefore every logger line, and any future caller) is guaranteed to match what's actually stored. Validated end-to-end: a company engineered to overflow `roe` now shows `None` in both the returned dict and a direct database query, where it previously showed the raw overflowing value in one and `NULL` in the other.

**Shares outstanding** is not a schema column. It is derived as `market_cap / close_price` from the latest price row, falling back to `net_profit_after_tax / eps` if market cap is unavailable. This value feeds BVPS (→ Graham Number), FCF-per-share (→ price-to-FCF), and the DCF's per-share conversion — **it is the single most consequential derived value in the entire valuation layer**, worth prioritising in any design review.

**DCF free cash flow base is a multi-year average, not just the latest year** (added 2026-10-02, after the SUN finding below). `gather_inputs()` fetches the last `fcf_average_years` `FY` reports (default 3) and `compute_metrics()` uses the simple mean of their `free_cash_flow` values as the DCF's starting point — gracefully averaging over however many years actually have a value (1, 2, or 3+), and returning `None` only if none do. **Every other metric** (ROE, D/E, P/E, P/B, EV/EBIT, dividend yield, Graham Number) still uses only the single latest `FY` report — this is a point-in-time ratio snapshot in every case *except* the DCF, which specifically needed smoothing.

**Why this exists — the SUN case study.** Live-testing against Suncorp Group (SUN) surfaced the problem directly: its reported `free_cash_flow` across FY2023–FY2026 was $742M / $2,497M / $2,550M / $1,585M — a 3.4x swing across 4 years. With the original single-year-only DCF base (the latest year, $1,585M), the computed margin of safety swung from **+34.45% to −9.84%** depending only on which growth/discount-rate scenario was tested (8%/9% vs 3%/11%) — the entire conclusion was an artefact of which year happened to be "latest," not a robust read on value. Averaging over 3 years (→ a $2,210.67M base) produces a materially more defensible number. This is logged as resolved against known-issue #4's residual risk (§11) and is the direct fix for what's now issue #9.

`--fcf-average-years 1` on the CLI reproduces the old single-year behaviour exactly, for anyone who wants to compare or who has a specific reason to weight only the most recent year.

**`current_ratio` is hardcoded to `None`** — the schema has no current-assets/current-liabilities split (only `total_assets`/`total_liabilities`), so a genuine current ratio cannot be derived. This is a deliberate "don't fabricate a number" decision, not a bug.

A company with no price row or no `FY` financial report is skipped entirely (logged as a warning), never valued with partial/garbage inputs.

### 8.5 `run_valuation.py` — CLI

```
python -m src.valuation.run_valuation (--all | --tickers BHP CBA) [--growth-rate D] [--discount-rate D] [--terminal-growth-rate D] [--stage1-years N] [--fcf-average-years N] [--trend-days N]
```

### 8.6 Trend Indicators — "Momentum Into Value" and the Value-Trap Warning (added 2026-10-02)

User request: *"is there another ranking to alert users to items worth looking at based on a trend? Something to help catch the next best share before others catch on? ... will be good to have a field that can populate in time to identify a potential value trap."* Two new `valuation_metrics` columns, computed independently and populating on different timelines:

**`margin_of_safety_trend`** — the change in `margin_of_safety_percent` versus the most recent `valuation_metrics` snapshot at least `trend_days` (default 30) old for the same company. `_prior_margin_of_safety()` queries for the newest row with `as_of_date <= as_of_date - trend_days`, so a gap in daily runs (machine off for a day) doesn't break it - it just uses whatever snapshot is old enough. This is the "momentum into value" signal: rising means the company is getting cheaper relative to its intrinsic value *since that earlier snapshot*, not just cheap in absolute terms - the idea being that a company newly crossing into value territory, or cheapening fastest, is more interesting to act on than one that's been statically cheap for months (often a sign something is wrong, not a sign of mispricing - see `fundamentals_trend` below). Depends on the schema's existing `UNIQUE(company_id, as_of_date)` design already accumulating one row per company per day once `scripts/daily_refresh.ps1` runs daily - no new schema mechanism was needed for the history itself, only for the two derived columns.

**Cold-start, by design, not a bug.** `margin_of_safety_trend` is `NULL` for every company until a `trend_days`-old snapshot exists - i.e. until daily automation has been running for that long. This was flagged explicitly by the user ("a field that can populate in time") and is surfaced directly: `screen_asx.py` prints a note when every row's trend is blank, rather than leaving the user to wonder whether it's broken (§9).

**`fundamentals_trend`** — `'IMPROVING'` / `'STABLE'` / `'DECLINING'`, computed by `_fundamentals_trend()` from the latest vs oldest `FinancialReport` in the same `fcf_average_years`-report window already fetched for the DCF/DDM average (§8.4) - no new DB query needed, and no cold-start wait, since it only needs annual report history that's typically already ingested (2+ years). Classification is a simple, explainable heuristic, consistent with this codebase's existing formula style (Graham Number, grossed-up yield): ROE change in percentage points and revenue change as a fraction, each compared against a fixed threshold (`_ROE_TREND_THRESHOLD = 2pp`, `_REVENUE_TREND_THRESHOLD = 5%`) -  `DECLINING` if either signal is clearly negative, `IMPROVING` if either is clearly positive (and neither is negative), `STABLE` otherwise, `None` if fewer than 2 distinct FY reports exist or neither signal is computable. **Not a sophisticated trend model** - a decline that started mid-window and partially recovered, or a company with only 2 FY reports, gets a trend based on just the two endpoints available; treat it as a prompt to look closer, not a verdict (documented in README.md's Known Data Model Limitations).

**Why two independent fields rather than one combined score:** `margin_of_safety_trend` is price-driven (changes daily, needs accumulated history) while `fundamentals_trend` is business-driven (changes only as new annual reports are ingested, available immediately). Conflating them into a single score would hide which kind of signal is actually driving it - keeping them separate lets the screener combine them explicitly and transparently (§9's `trap_risk` = cheap (`mos_ok`) **and** fundamentals declining; `momentum_ok` uses `margin_of_safety_trend` alone).

Both columns are appended at the **end** of the `valuation_metrics` table and the `asx_value_screener` view's `SELECT` list (§4.4's `CREATE OR REPLACE VIEW` append-only lesson applies here too), with idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` for pre-existing databases. `margin_of_safety_trend` is covered by the existing generic `_clamp_to_column_precision()` overflow guard (§8.4, known-issue #15) exactly like every other `NUMERIC` column - no separate sanity cap was needed.

### 8.7 Decision Markers (`markers.py`, added 2026-10-02)

User request: *"are there any other markers or decision points we should add to help level me up as an investor?"* Four were chosen, each answering a question the four classic value criteria can't, and all built from data the pipeline already collects. Computed in `compute_metrics()`, stored in `valuation_metrics` (appended to the table and view per §4.4's append-only lesson), and deliberately simple rules - prompts to look closer, not verdicts.

| Marker | Question | Rule | Why it matters |
|---|---|---|---|
| `earnings_quality` (from `cash_conversion`) | Is reported profit turning into cash? | Operating cash flow / NPAT, summed over the `fcf_average_years` window: `STRONG` >= 100%, `ADEQUATE` >= 80%, `WEAK` below. `NULL` for loss-makers and for Financial Services/Real Estate | Accounting profit can be flattered by accruals and revaluations; persistent shortfalls between profit and cash are one of the most reliable early warnings, and P/E and ROE can't see them |
| `price_signal` (from `price_vs_200d`, `range_position_52w`) | Is the price stabilising or still falling? | `NEW LOWS` = below the 200-trading-day average **and** in the bottom 10% of the 52-week range; `DOWNTREND` = below the average; `UPTREND` = above. Needs 200 stored daily prices | Separates "cheap and basing" from "cheap and still falling" - buying the falling knife is the classic value-investing mistake. The label is derived in the screener from the two stored numbers |
| `dividend_trend` | Is the dividend dependable? | Over up to 5 FY reports: `CUT` if any year-on-year drop exceeds 10%, `GROWING` if the latest is >5% above the oldest with no cuts, `STEADY` otherwise, `NONE` for non-payers | A yield is only worth what its reliability is worth. A year after a special dividend correctly reads as a cut in cash terms; `payout_ratio` flags the special year itself |
| `data_confidence` | How much of this analysis rests on missing data? | 11 checks (price, market cap, EPS, NPAT, revenue, equity, debt, OCF, FCF, 3+ FY reports, 200+ daily prices): `HIGH` >= 90%, `MEDIUM` >= 70%, `LOW` below. Dividends aren't counted - a non-payer isn't missing data | Tells you when a signal is built on thin ground before you act on it |

**Design notes.** `gather_inputs()` now fetches up to `max(fcf_average_years, 5)` FY reports in one query and slices the first `fcf_average_years` for the DCF/DDM base and `fundamentals_trend` (unchanged behaviour), keeping the longer history for `dividend_trend`. A second query fetches the last 365 calendar days of closes for the price markers. Both new `ValuationInputs` fields default to empty lists, so the existing unit-test builders needed no change. `cash_conversion`, `price_vs_200d` and `range_position_52w` are covered by `_clamp_to_column_precision()` like every other numeric column.

**Price history prerequisite.** `scripts/daily_refresh.ps1` ingests the default `--period 1mo` of prices each day, so a database built that way holds too little history for the 200-day average until it has run for ~10 months. A one-off backfill fixes this immediately: `python -m src.ingestion.run_ingestion --tickers-file allords.txt --prices-only --period 1y --delay 0.5` (upserts, so it's safe to re-run). Until then `price_signal` is blank and `data_confidence` tops out at 10 of 11 checks, which is still `HIGH`.

---

## 9. Screener (`screen_asx.py`)

Queries `asx_value_screener` directly via raw parameterised SQL (`sqlalchemy.text()`), not through the ORM — this view is read-only and reporting-oriented, so Core SQL was chosen over an ORM mapping for simplicity.

**Show-every-company design (changed 2026-10-02 — see below for the pre-change behaviour this replaced).** The four classic value criteria are no longer a SQL `WHERE` filter. `build_query()` only ever filters by `--sector` (a genuine filter — there's no ambiguity about whether a company is in a given sector); the four criteria are computed row-by-row in Python by `annotate_row()` against whatever the query returns, and every row is shown regardless of outcome. This was a deliberate user-requested change: filtering silently drops a company that's close to passing (or missing one input metric) from the output entirely, which hides exactly the information a reviewer most wants to see — *how close* something is, and *why* it didn't clear a particular bar.

**Indicator columns**, one `Y`/`N` column per criterion plus a combined `overall` column:

| Indicator | Criterion | Default threshold | Flag to override |
|---|---|---|---|
| `mos_ok` | Margin of Safety | `> 20%` | `--min-margin-of-safety` |
| `roe_ok` | ROE | `> 12%` | `--min-roe` |
| `de_ok` | Debt/Equity | `< 0.80` | `--max-debt-equity` |
| `yield_ok` | Grossed-Up Dividend Yield | `> 4.5%` | `--min-yield` |
| `overall` | all four (`AND`) by default | — | `--any-of` switches to any one (`OR`) |

Additional flags: `--sector` (exact match filter, unchanged), `--passing-only` (filters the *displayed* rows down to `overall = Y` — restores the pre-change filtered-to-matches-only view, as an opt-in rather than the default), `--limit` (default: **no limit**, i.e. show every company returned by the query — previously defaulted to 25 under the old filtered view, where a small cap made more sense).

**NULL handling, same semantics as the old `WHERE`-based version but now explicit in Python:** `annotate_row()` treats a `None` source value as not clearing the bar (`value is not None and compare(value, threshold)`), so a company missing an input metric (e.g. no DCF result because FCF and dividends were both unusable) shows `N` for that one criterion rather than crashing or being silently dropped from the result — it's still shown, with every other indicator it does have data for computed normally (validated directly with a company missing both yield and margin-of-safety inputs but present on the others — see §10.10).

Output rendered via `tabulate` in `simple` format with 2-decimal-place float formatting. The summary line now reads `N companies shown, M passing (all/any of the four criteria)` instead of the old `N companies matched`.

**`payout_ratio` warning (added 2026-10-02):** a `payout_ratio` column is included in every result row, and any row with `payout_ratio > 150%` triggers a printed warning listing the affected tickers after the table — a visible flag, not a filter; the row still appears, the yield still shows, but the warning makes clear it likely reflects a one-off special dividend rather than sustainable income. See §8.1 for the TWR case that motivated this. Unaffected by the show-every-company change — it was already additive, never a filter.

**`valuation_method` column (added 2026-10-02, known-issue #8):** every row also shows `valuation_method` (`DCF` or `DDM`), so it's visible at a glance which intrinsic-value model priced that company — see §8.3/§8.4 for why Financial Services and Real Estate companies are priced differently. Note the default `--max-debt-equity 0.80` threshold is structural for banks (leverage is their business model, not a risk flag the way it is for an industrial company) and will read `de_ok = N` for nearly every Financial Services company regardless of how cheap it is on other measures, pulling `overall` to `N` under the default all-four logic; use a much higher `--max-debt-equity` or `--any-of` when screening financials specifically — the row itself is always shown either way (also documented in README.md).

**Trend indicators and `--rank-by momentum` (added 2026-10-02, §8.6):** two more informational indicator columns, deliberately **excluded from `overall`** since they answer a different question than the core four-criterion value screen:

| Indicator | Meaning | Flag to override |
|---|---|---|
| `momentum_ok` | `Y` when `margin_of_safety_trend` has improved by more than the threshold | `--min-mos-trend` (default 5pp) |
| `trap_risk` | `Y` when `mos_ok` is `Y` **and** `fundamentals_trend == 'DECLINING'` | not overridable - a composite of two already-overridable inputs |

`--rank-by momentum` changes the `ORDER BY` from `margin_of_safety_percent` to `margin_of_safety_trend` (both `DESC NULLS LAST`), surfacing companies getting cheaper *fastest* rather than companies that are simply cheap in absolute terms right now - the "catch it before others" ranking the user asked for. `trap_risk`-flagged tickers get a printed warning line after the table, the same pattern as the existing `payout_ratio` warning. When every row's `margin_of_safety_trend` is `NULL` (the cold-start case, §8.6), a note is printed explaining why rather than leaving it to look broken.

**What this replaced:** before 2026-10-02, the four criteria were a SQL `WHERE` clause (`AND`/`OR` joined per `--any-of`), so a non-matching company simply never appeared in the output at all, and the default `--limit` was 25 (reasonable when the result was already filtered to matches). §10.3's Company A/B validation and its "correctly failed the default screen, and correctly appeared only under `--any-of`" language describe that earlier filtering behaviour; the underlying NULL-handling and pass/fail logic it validated carried over unchanged into `annotate_row()`, just expressed as an indicator column instead of a row filter.

### 9.1 Suggested Actions (`src/screening/actions.py`, added 2026-10-02)

User request: *"add a field with variables advise on possible actions? for example watch, investigate, buy, sell, hold"*. Every row gets an `action` and an `action_reason`. The reason is the point: it names the specific tests and markers behind the call, so the output teaches the reasoning instead of issuing a bare verdict. `suggest_action()` is a pure function of the annotated row plus an optional `PositionSummary` (§19), so the rules are unit-tested directly (`tests/unit/test_actions.py`).

**Red flags** (any one can downgrade a call): `trap_risk`, `payout_ratio > 150%`, `earnings_quality = WEAK`, `dividend_trend = CUT`, `price_signal = NEW LOWS`, `data_confidence = LOW`.

**Not held** (first matching rule wins):

| Action | Rule |
|---|---|
| `AVOID` | `trap_risk` **and** weak earnings quality: cheap, deteriorating, and profit not backed by cash |
| `BUY` | passes all four value tests with no red flags (notes momentum if `momentum_ok`) |
| `INVESTIGATE` | passes all four but has a red flag, or is cheap and passes 3 of 4 (names the failed test) |
| `WATCH` | cheap but failing 2+ tests; or getting cheaper fast (`momentum_ok`); or ROE, debt and yield pass but the price isn't cheap yet - the "wonderful company, wait for a fair price" list. Red flags are appended |
| `IGNORE` | no value signal (not listed in the `--actions` report) |

**Held** (any open parcel in `holdings`):

| Action | Rule |
|---|---|
| `SELL` | fundamentals `DECLINING` **and** at least one of: trading above estimated value, weak earnings quality, dividend cut |
| `REVIEW` | any red flag, or margin of safety below -50% (now well above estimated value - Graham's sell discipline) |
| `HOLD` | otherwise ("could add" if it still passes all four tests) |

**CGT timing note.** On `SELL`/`REVIEW`, if a held parcel reaches the 12-month CGT discount within 90 days, the reason says how many units, from what date, and how many days away - waiting can halve the tax on the gain. Never added to `HOLD`.

**Presentation.** The full table gains `earnings_quality`, `price_signal`, `dividend_trend`, `data_confidence`, `held` and `action` (raw marker numbers stay in the database; company names are truncated to keep width down). `--actions` prints a grouped report instead (SELL, REVIEW, HOLD, BUY, INVESTIGATE, WATCH, AVOID) with the wrapped reason per company, action counts, any holdings that aren't on the screening watchlist, and a one-line reminder that these are rule-based research prompts, not financial advice. `--held` restricts either view to companies you hold. The daily automation log now records `--actions` rather than the full table.

**Found in end-to-end testing:** the first version didn't append red flags to `WATCH` reasons, so a company with ~45% cash conversion read "quality passes, wait for a better price" - a cleaner bill of health than the data supported. Fixed (red flags now appended to every non-`IGNORE` reason) with a regression test, and the wording changed from "quality passes" to "ROE, debt and yield pass" to say exactly which tests passed.

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
- ~~No automated test suite exists yet~~ **Resolved 2026-10-02 - see §10.12.**
- Given the field-name break found in §10.6, the **other** Yahoo-sourced field — `get_price_history()`'s `sharesOutstanding` lookup from `.info` — has not been separately re-verified against live data, though price/volume/market_cap ingestion itself did return correctly (§10.6). `.info` is a different API surface (plain dict, not a statement DataFrame) and less likely to share this exact failure mode, but it hasn't been explicitly checked.

### 10.9 Sector-Aware DDM — Synthetic Data (2026-10-02)

Validated against a disposable PostgreSQL instance (not live Yahoo data — the specific combination needed, a real Financial Services company with a clean multi-year negative-FCF-but-growing-dividend history, is awkward to guarantee from whatever happens to be in the live database at test time, so synthetic data gives a controlled, repeatable check):

- **Synthetic bank** (`BANK.AX`, sector `Financial Services`): `free_cash_flow` set **negative in all 4 years** (−$3.0bn to −$3.5bn, modelling loan-book growth dominating operating cash flow, as real banks report) but a real, steadily growing 4-year dividend history ($1.80 → $2.10/share). Old code path: `dcf_fcf > 0` check fails → `dcf_intrinsic_value` and `margin_of_safety_percent` both `NULL`, company invisible to the screener under any threshold. New code path: correctly routed to `ddm.two_stage_ddm()` on `sector == "Financial Services"`.
- **Synthetic miner** (`MINE.AX`, sector `Basic Materials`, control): positive FCF across all 4 years, to confirm the existing DCF path is completely unaffected by this change. Correctly routed to `dcf.two_stage_dcf()`, `valuation_method = 'DCF'`, `dcf_intrinsic_value = 139.4462`, `margin_of_safety_percent = 71.32%` — identical in every run below, regardless of the `--growth-rate` flag's interaction with the DDM path.
- **Per-model default growth rate, confirmed by running the same seeded database twice:**
  - Run 1, no `--growth-rate` flag (should pick each model's own default: 8% DCF / 5% DDM): BANK → `valuation_method = 'DDM'`, `dcf_intrinsic_value = 35.1125`, `margin_of_safety_percent = 28.80%`.
  - Run 2, explicit `--growth-rate 0.08` (should apply uniformly to both models, making BANK's DDM use the same 8% as MINE's DCF): BANK → `dcf_intrinsic_value = 39.8462`, `margin_of_safety_percent = 37.26%` — a higher intrinsic value than Run 1, exactly as expected from a higher assumed growth rate, and matching an earlier routing-only test run with growth-rate held at 8% for both paths.
  - This confirms both halves of the design: left unset, the DDM correctly uses its own more conservative 5% default rather than silently inheriting the DCF's 8%; set explicitly, the override still applies uniformly to whichever model runs, unchanged from pre-DDM behaviour.
- **Screener confirmation:** `screen_asx.py --any-of --min-margin-of-safety 30` correctly returned both companies, with `BANK` showing `valuation_method = DDM` and `MINE` showing `valuation_method = DCF` in the output — confirming the new column surfaces correctly end-to-end, not just in the database.
- **Residual note surfaced by this test, not a defect:** `BANK`'s synthetic `debt_to_equity` (14.0, realistic for a bank's balance sheet) failed the screener's default `--max-debt-equity 0.80` threshold even with a real margin of safety computed — confirming this threshold is structurally unsuited to Financial Services companies regardless of how the DCF-vs-DDM question is resolved. Documented in README.md and §9 as a threshold-tuning note (use `--max-debt-equity` with a much higher value, or `--any-of`, when screening financials), not treated as a new known-issue since it's a screener-default question, not a valuation-correctness one.
- Schema migration re-verified idempotent across two separate disposable databases: re-running `db/schema.sql` correctly reported `payout_ratio`/`valuation_method already exists, skipping` with no errors each time.
- Test artifacts (seed scripts, both disposable databases) deleted after validation; nothing from this test is part of the committed repository.

### 10.10 Screener Show-Every-Company Redesign — Synthetic Data (2026-10-02)

User explicitly asked to stop filtering non-matching companies out of `screen_asx.py`'s output and instead show every company with a visible Y/N indicator per criterion. Validated against a disposable PostgreSQL instance with three synthetic companies chosen to exercise every case: a clean pass, a clean fail, and a company with missing input data on some (not all) criteria:

- **`GOOD.AX`** (cheap, strong ROE, low debt, solid franked yield): correctly showed `Y` on all four indicators and `overall = Y`.
- **`BAD.AX`** (expensive, weak ROE, high debt, negligible yield, negative-implying DCF so `margin_of_safety_percent = NULL`): correctly showed `N` on all four indicators (including `mos_ok = N` for the `NULL` margin of safety, not an error) and `overall = N`.
- **`MISS.AX`** (loss-making, no dividend so `grossed_up_dividend_yield` and `margin_of_safety_percent` are both `NULL`, but real, passing `debt_to_equity`): correctly showed `N` for `mos_ok` and `yield_ok` (the two it has no data for), **`Y` for `de_ok`** (the one it does have data for and does clear), and `N` for `roe_ok` (negative ROE, genuinely fails) — confirming a company with partial data gets a precise, metric-by-metric readout rather than being blanket-excluded or blanket-marked as failing.
- All three companies appeared in the default (no-filter) run - confirming the headline change: nothing is hidden by default any more.
- `--any-of`: `MISS.AX`'s `overall` correctly flipped from `N` to `Y` (since `de_ok = Y` is enough under "any one of four"), while `GOOD`/`BAD` were unaffected (already all-`Y`/all-`N` respectively, so `AND` vs `OR` makes no difference to them).
- `--passing-only`: correctly reduced the output to just `GOOD.AX` (the only `overall = Y` row), reproducing the pre-change filtered behaviour exactly, as the flag is designed to.
- `--sector Technology`: correctly reduced the output to just `BAD.AX` (the only company in that sector), confirming `--sector` remains a true SQL-level filter, unlike the four criteria.
- `--limit 1`: correctly capped the output to the single top-ranked row (by margin of safety, `GOOD.AX`), confirming the new default-unlimited `--limit` still works as an explicit cap when passed.
- Test artifacts (seed script, disposable database) deleted after validation; nothing from this test is part of the committed repository.

### 10.11 Trend Indicators — Synthetic Data (2026-10-02)

Validated against a disposable PostgreSQL instance with three synthetic companies chosen to exercise `margin_of_safety_trend`, `fundamentals_trend`, `momentum_ok`, `trap_risk`, `--rank-by momentum`, and the cold-start note, in one pass:

- **`TRAP.AX`**: 4 years of `financial_reports` engineered with ROE declining 20% → 13.3% → 6.7% → 1.7% and revenue declining $900M → $600M, plus a pre-inserted `valuation_metrics` row 45 days in the past (`margin_of_safety_percent = 15.00`) as the trend baseline. Result: `fundamentals_trend = 'DECLINING'` (correctly, from the ROE/revenue direction alone), `margin_of_safety_trend = +24.73` (today's 39.73% computed MoS minus the 15.00% baseline), `mos_ok = Y` (39.73% clears the 20% default), and critically **`trap_risk = Y`** - the composite correctly fired because a cheap company with deteriorating fundamentals is exactly the case it's designed to catch, even though `momentum_ok` was *also* `Y` for this company (the price-driven trend was positive even though the business trend was negative) - confirming the two signals are independent and `trap_risk` looks at fundamentals specifically, not price momentum.
- **`GROW.AX`**: ROE improving 2% → 6% → 12% → 20%, revenue growing $300M → $550M, prior snapshot 45 days ago at `margin_of_safety_percent = 10.00`. Result: `fundamentals_trend = 'IMPROVING'`, `margin_of_safety_trend = +65.84`, `momentum_ok = Y`, and correctly **`trap_risk = N`** despite also passing `mos_ok` - the fundamentals signal correctly distinguishes this from `TRAP.AX` even though both are cheap and both have positive price momentum.
- **`COLD.AX`**: only 1 `FY` report (so `fundamentals_trend` has nothing to compare, `_fundamentals_trend()` correctly returns `None` for `< 2` reports) and no prior `valuation_metrics` row at all (`_prior_margin_of_safety()` correctly returns `None` - no row exists that's `trend_days` old). Result: both trend columns `NULL`, `momentum_ok = N` (a `None` comparison correctly evaluates to not-met, not an error), `trap_risk = N` (also correctly `N` regardless of fundamentals since `mos_ok` was `N` anyway on this company's numbers) - confirming a genuinely new company renders cleanly with blank trend fields rather than crashing or showing misleading data.
- **`--rank-by momentum`**: re-ran the same query with `ORDER BY margin_of_safety_trend DESC NULLS LAST` - correctly reordered (`GROW` first at +65.84, `TRAP` second at +24.73, `COLD` last with `NULL`).
- **Cold-start note**: filtering to `--sector "Health Care"` (isolating `COLD.AX`, the only company with no trend data) correctly triggered the printed "needs roughly 30 days of accumulated daily valuation history" note; the unfiltered 3-company run correctly did **not** print it, since `TRAP`/`GROW` both had real trend values (confirming the note's `any()` check is calibrated at "every row blank," not "any row blank").
- `trap_risk` warning line confirmed printed for `TRAP` only, in the same style as the existing `payout_ratio` warning.
- Test artifacts (seed script, disposable database) deleted after validation; nothing from this test is part of the committed repository.

### 10.12 Automated Test Suite (`tests/`) — Added 2026-10-02

**Known-issue #6, resolved.** Every fix in §10.1-§10.11 was validated by hand against a disposable PostgreSQL instance - real, not mocked, and genuinely effective at catching the bugs this project has actually hit (numeric overflow, view column ordering, upsert/commit semantics), but manual and not repeatable without re-reading this document and re-typing each scenario. `tests/` formalises the highest-value scenarios already documented above into a `pytest` suite that runs in under a second and can be re-run on every change going forward.

**Two tiers, by design:**

- **`tests/unit/`** - pure functions and `compute_metrics()`, no database at all. `compute_metrics()` takes a `ValuationInputs` dataclass and plain (unpersisted) ORM objects - SQLAlchemy models can be constructed and have their attributes read without ever touching a session - so the DCF-vs-DDM sector routing, per-model growth-rate defaults, `payout_ratio`/`margin_of_safety_percent` sanity caps, `_clamp_to_column_precision()`, and `_fundamentals_trend()` are all covered here, instantly and without any setup. 64 tests.
- **`tests/integration/`** - the parts that genuinely need a real database: `gather_inputs()`'s queries (including the `margin_of_safety_trend` cross-row lookup), `upsert_valuation_metric()`'s overflow clamp actually round-tripping through PostgreSQL, `run_valuation()`'s per-company crash isolation (validated with a real forced exception via `monkeypatch`, not just a skip case), and `screen_asx.py`'s `build_query()`/`annotate_row()` against the real `asx_value_screener` view. 15 tests, requiring a local PostgreSQL instance (`tests/conftest.py` creates the `asx_test` database and applies `db/schema.sql` automatically on first run - set `TEST_DATABASE_URL` to point elsewhere, e.g. a CI database).

**Regression-pinned against real historical figures**, per this project's own suggested-next-step: SUN's documented 3-year FCF average ($2,210.67M, known-issue #9), TWR's documented payout ratio (518.70%, from $1.1930 DPS / $0.2300 EPS, known-issue #14), and BRN/WHI's exact overflow values (`roic` 10,129.90%, `pb_ratio` ~203M, `roe` 134,600%, known-issue #15) are used as literal test fixtures, not synthetic approximations - if any of these formulas regress, the test that catches it cites the exact real-world case that originally found the bug.

**Graceful skip, not a hard dependency.** `tests/conftest.py`'s database-reachability check is deliberately *not* an `autouse` fixture - only `db_session` (and anything that requests it) depends on it, so `tests/unit/` runs and passes identically whether or not Postgres is even installed. `tests/integration/` skips with a clear reason (`pytest.skip(...)`, not a failure) if no database is reachable, so `pytest` is safe to run on a fresh clone before `db/schema.sql` has ever been applied. This was found and fixed during development: an earlier version made the database check `autouse=True` at session scope, which skipped *every* test in the suite - including pure unit tests that never request a database - the moment Postgres was stopped, since every test implicitly depended on the autouse fixture. Caught by literally stopping Postgres and re-running the suite, exactly the kind of check a test suite about testing needs to survive itself.

**Running them:**
```bash
pip install -r requirements-dev.txt
pytest                              # runs both tiers; integration tests skip if no DB is reachable
pytest tests/unit                   # unit tests only, no database needed at all
pytest -m integration               # integration tests only
TEST_DATABASE_URL=postgresql+psycopg2://... pytest   # point at a different test database
```

### 10.13 Decision Markers, Suggested Actions and Holdings (2026-10-02)

- **77 new tests** (156 total): `test_markers.py` (every band boundary, TWR's special-dividend shape reading as `CUT`), `test_cgt.py` (12-month boundary both sides of the anniversary, 29 February purchases, Australian FY labels, loss ordering in the FY summary), `test_actions.py` (every action rule, each red flag downgrading `BUY`, the CGT timing window), `test_portfolio.py` (partial-sale split preserving the combined cost base to the cent, FIFO across parcels, min-tax choosing a smaller undiscounted gain over a larger discounted one, specific-parcel sales, oversell and sell-before-buy guards, the schema's own `CHECK` constraint), plus markers end to end through `run_valuation_for_company()` with 250 days of real stored prices and five FY reports, and identical held/not-held companies getting `HOLD` vs `BUY`.
- **Migration over live-shaped data:** created a database from the previous `db/schema.sql`, inserted a company with prices and a valuation, then applied the new schema - zero errors, 10 `ALTER TABLE`s, existing values intact and readable through the view alongside the new (empty until re-valued) columns, `holdings` created.
- **CLIs end to end** on five synthetic companies built to hit specific rules: identical fundamentals with a rising price (`GEM`, held, `HOLD`) and a falling one (`KNIFE`, `INVESTIGATE`, "price still making new lows"); a declining business held ~10 months (`FADE`, `SELL`, with "300 units qualify for the CGT discount from 07 Dec 2026 (66 days)"); an expensive held company (`PRICY`, `REVIEW`); and weak cash conversion (`LEAK`). `portfolio.py sell --order min-tax` correctly sold the DRP parcel before the larger, older one, and split $9.95 sale brokerage into $0.50 + $9.45. This run found the `WATCH`-reason gap described in §9.1, fixed before commit.
- Test databases and seed scripts deleted afterwards.

---

## 11. Known Issues & Design Limitations

| # | Issue | Impact | Suggested Resolution |
|---|---|---|---|
| 1 | `current_ratio` always `NULL` | Screener can't filter on liquidity | Add `current_assets`/`current_liabilities` columns to `financial_reports` if this metric matters |
| 2 | Franking % / tax rate default to 100% / 30% for every ingested company | Wrong grossed-up yield for LICs, foreign-domiciled ASX listings, or any partly-franked payer | Manually correct affected rows after ingestion; no automated source exists for this data |
| 3 | Shares outstanding is derived, not stored | A stale/wrong `market_cap` from Yahoo silently skews Graham Number, P/B, FCF/share, and DCF-per-share together | Consider adding a `shares_outstanding` column sourced independently, if data quality issues appear |
| 4 | `yfinance` field names are unversioned and change without notice | **Materialised on the first live run (2026-10-01):** every balance-sheet/income/cash-flow field except EBIT came back `NULL` due to a PascalCase-vs-spaced naming mismatch. Fixed same day — see §10.6. Residual risk: Yahoo can change these labels again at any time | Use the diagnostic script in §10.6 to re-check field names if ROE/D-E/margin-of-safety start coming back `NULL` again after previously working |
| 5 | Yahoo Finance blocked from the sandboxed dev environment used for initial development | Live ingestion couldn't be exercised until moved to the user's own machine (see §10.7) | Resolved — ingestion now runs from the user's own machine, which has normal network access |
| 6 | ~~No automated test suite~~ **RESOLVED 2026-10-02** | Regressions in the valuation formulas would only surface by manual inspection | Fixed: `tests/` adds a 79-test `pytest` suite (64 unit, 15 integration), regression-pinned against real historical figures (SUN's FCF average, TWR's payout ratio, BRN/WHI's overflow values) from this very table. See §10.12 |
| 7 | `.env` holds a plaintext DB password | Standard local-dev risk, already `.gitignore`d | Fine for local use; use a secrets manager if ever deployed beyond a single machine |
| 8 | ~~A single generic DCF model is applied to every sector, including banks~~ **RESOLVED 2026-10-02** | Confirmed in practice (§10.6): CBA's `free_cash_flow` is not meaningfully positive under the standard operating-CF-minus-capex definition, since loan book movements dominate it for a bank — DCF is correctly skipped for CBA rather than producing a misleading number, but this meant financial-sector (and REIT) companies would generally never get a margin-of-safety figure at all | Fixed: `engine.py` now routes Financial Services and Real Estate companies to a new two-stage Dividend Discount Model (`src/valuation/ddm.py`) instead of the FCF-based DCF, with a new `valuation_method` column recording which model priced each company. Validated with synthetic data (§10.9): a bank with negative FCF in all 4 years but a real dividend history now gets a usable margin-of-safety figure instead of `NULL`. Residual note: the screener's default `--max-debt-equity 0.80` is still structurally unsuited to financials (leverage is their business model) — a threshold-tuning question, documented in README.md/§9, not a valuation defect |
| 9 | ~~DCF used only the single latest year's `free_cash_flow` as its base~~ **RESOLVED 2026-10-02** | Was highly sensitive to whichever year happened to be most recent — SUN's margin of safety swung +34% to −10% across reasonable growth/discount scenarios purely because of this (§8.4, §10.6) | Fixed: DCF base is now a `fcf_average_years`-year (default 3) simple mean, configurable via `--fcf-average-years` on `run_valuation.py` (set to 1 to restore old behaviour) |
| 10 | ~~One bad ticker could abort an entire ingestion batch; no pacing for large batches~~ **RESOLVED 2026-10-02** | Fine at 5-9 tickers, but a real risk once scaling to hundreds (e.g. a full index) — one edge-case ticker losing the rest of the run | Fixed: each ticker is isolated in its own try/except in both ingestion modules (logs and continues); `--delay` added to `run_ingestion.py` to pace requests. See §7.3-§7.5 |
| 11 | **No official, verified ASX 300 (or any index) constituent list is bundled with this project** | The codebase has no way to look up "what's currently in the ASX 300" — it only knows about whatever tickers you explicitly feed it via `--tickers`/`--tickers-file`. Hand-typing or AI-recalled ticker lists for an official index are both unreliable: index membership changes quarterly, and neither a human's memory nor a model's training data is a live feed | Source the current constituent list from an authoritative provider (ASX's own index data, or S&P Dow Jones Indices' published ASX 300 factsheet) and save it as a `--tickers-file`. Revisit each quarter if running this against the index on an ongoing basis — rebalances happen regularly |
| 12 | ~~`margin_of_safety_percent()` could overflow the `NUMERIC(6,2)` DB column~~ **RESOLVED 2026-10-02** | **Materialised at 500-ticker scale (first real-world crash of the project):** a micro-cap with a near-zero DCF intrinsic value (likely a bad shares-outstanding estimate, known-issue #3) produced a margin of safety of −128,521.87%, which the database correctly rejected with `NumericValueOutOfRange`, crashing the entire `run_valuation --all` call | Fixed: `margin_of_safety_percent()` now returns `None` (not a wild number) when the result's magnitude exceeds a 5000% sanity threshold — treated as "the DCF broke down for this company," consistent with the codebase's existing don't-fabricate-a-number philosophy. Validated by replaying the exact failing inputs from the crash traceback |
| 13 | ~~`run_valuation()` committed only once, after processing every company~~ **RESOLVED 2026-10-02** | **Far more costly than issue #12 on its own:** when the overflow crash hit mid-batch on a ~500-company run, *every other company already successfully valued in that same run was lost* too, since nothing had been committed yet. One bad company cost the entire batch's work, not just its own | Fixed: each company is now isolated in its own try/except and committed individually, matching the pattern already used in `price_ingestion.py`/`fundamentals_ingestion.py` (§7.3). A failure on one company is logged and the run continues; prior successes are safe. Validated by simulating a crash on company 2-of-4 and confirming companies 1, 3, and 4 all had committed `valuation_metrics` rows despite it |
| 14 | ~~Grossed-up dividend yield had no way to flag a one-off special dividend vs sustainable income~~ **RESOLVED 2026-10-02** | TWR showed a 106.85% grossed-up yield driven by a single `FY`'s dividend at 519% of that year's EPS (prior 3 years: 12-82%, all normal) — a special dividend/capital return almost certainly, but nothing in the output said so | Fixed: new `payout_ratio` column (schema, model, `engine.py`) stored alongside the yield, surfaced in `screen_asx.py` with a `>150%` printed warning naming affected tickers. User's explicit choice: flag visibly, don't null out or silently hide. See §8.1, §9 |
| 15 | ~~Numeric overflow could crash any ratio, not just margin_of_safety_percent~~ **RESOLVED 2026-10-02** | On the first 500-ticker run with the #12/#13 fixes already in place, two *more* companies crashed on two *different* fields: BRN's `roic` (10,129.90%) and WHI's `pb_ratio` (~203 million) and `roe` (134,600%) all overflowed their columns. Crash isolation (#13) correctly contained the damage to just those two companies, but each still lost its entire valuation row to one bad field | Fixed: `upsert_valuation_metric()` now runs every field through a generic `_clamp_to_column_precision()` check derived directly from `db/schema.sql`'s column definitions, nulling (and logging) anything that would overflow rather than crashing - applied to all 14 `valuation_metrics` columns, not just the two found first. Validated by replaying both companies' exact failing payloads: both now upsert successfully with only the pathological field nulled. See §8.4 |
| 16 | The pipeline had to be run by hand (three separate commands) every time fresh data was wanted | Easy to let data go stale; no way to "just check it daily" without remembering the exact command sequence | Resolved 2026-10-02: `scripts/daily_refresh.ps1` runs ingestion → valuation → screener in one unattended pass, wired into Windows Task Scheduler. See §16 |
| 17 | There was no way to tell *newly cheap* or *rapidly cheapening* companies from ones that have simply been statically cheap for months, nor any flag for a company that's cheap because its fundamentals are deteriorating (a classic value trap) | A static margin-of-safety snapshot alone can't distinguish "the market just mispriced this" from "this has been the market's fair assessment of a declining business for a while" — exactly the distinction that matters for acting early rather than falling for a trap | Resolved 2026-10-02 (user request): added `margin_of_safety_trend` (price-driven, needs `trend_days` of accumulated daily history - genuine cold-start gap, not a bug) and `fundamentals_trend` (business-driven, from existing annual report history, populates immediately) as two independent signals; screener surfaces them as `momentum_ok`/`--rank-by momentum` and a composite `trap_risk` warning. See §8.6, §9, §10.11 |
| 18 | `fundamentals_trend` is a simple two-endpoint heuristic (latest vs oldest FY report's ROE/revenue direction), not a sophisticated trend model | Won't catch a decline that started mid-window and partially recovered; a company with only 2 FY reports gets a trend based on just those two points | Acceptable as-is, consistent with this codebase's existing formula simplicity (Graham Number, grossed-up yield); treat `trap_risk`/`fundamentals_trend` as a prompt to look closer, not a verdict. A weighted/multi-point regression would be the proper fix if false positives/negatives become a practical problem |
| 19 | Holdings record keeping covers CGT on share parcels only | Dividend income and franking credits received, carried-forward capital losses from earlier years, and cost base adjustments from corporate actions (returns of capital, bonus issues, rights issues, share consolidations, demergers) aren't modelled - a `BONUS` parcel's cost base is whatever you enter | Treat `portfolio.py cgt` as a working record to reconcile against broker statements, not a tax return. A `dividends_received` table (amount, franking %, date per holding) would be the natural next addition for tax time |
| 20 | Price markers need 200+ stored daily prices; the daily refresh only fetches 1 month | `price_signal`/`price_vs_200d` blank until history accumulates (~10 months) | One-off backfill: `python -m src.ingestion.run_ingestion --tickers-file allords.txt --prices-only --period 1y --delay 0.5` (§8.7) |
| 21 | Suggested actions are rule-based, with fixed thresholds | The rules can't know context the data doesn't hold (a takeover bid, a one-off write-down, management change) and treat every sector with the same thresholds | By design - each action carries its reason so it can be checked, and every flag is a prompt to read the underlying numbers. Not financial advice |

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

# 5. Run the pipeline (1y+ of prices so the 200-day price markers populate, §8.7)
python -m src.ingestion.run_ingestion --tickers BHP CBA CSL WES WOW --period 2y
python -m src.valuation.run_valuation --all
python screen_asx.py --actions

# 6. (Optional) Record holdings so held companies get HOLD/REVIEW/SELL (§19)
python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --brokerage 9.95

# 7. (Optional) Run the test suite (§10.12) - uses its own asx_test database,
#    created automatically, never the one configured above
pip install -r requirements-dev.txt
pytest
```

**Full teardown/reset** (destroys all ingested data, keeps schema definition intact for re-apply). `holdings` is deliberately not in this list - parcel records are your tax records, not re-downloadable market data:
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
| `screen_asx.py` returns "No companies found" unexpectedly | Since 2026-10-02 the screener shows every company by default (§9) - an empty result now means either `--sector`/`--passing-only` filtered everything out, or `run_valuation` hasn't been (re)run since the last ingestion (the view has nothing to join against) | Drop `--sector`/`--passing-only` to confirm; run `python -m src.valuation.run_valuation --all` before screening; check `valuation_metrics.as_of_date` is recent |
| Grossed-up yield looks absurd (very large or negative) | `franking_percentage`/`corporate_tax_rate` stored incorrectly (e.g. as a fraction `1.0` instead of `100.0`) | These columns must be whole-number percentages per the schema; check `dividends.py`'s `/100` conversion assumption still holds |
| Margin of safety is always `None` for a company with real data | For most sectors: `free_cash_flow` is `None`/`≤ 0` across the averaging window. For Financial Services/Real Estate (§8.3/§8.4): `dividends_per_share` is `None`/`≤ 0` across the same window — these use the DDM, not the DCF, and won't have a `dcf_free_cash_flow`-driven result regardless of FCF | Check the source `financial_reports` rows and `valuation_metrics.valuation_method` (will be `NULL` if neither model ran); this is by design, not a bug |
| Margin of safety is `None` specifically for a bank/insurer/REIT with real dividends | Check `companies.sector` matches `_SECTOR_AWARE_SECTORS` exactly (`"Financial Services"`, `"Real Estate"` — yfinance's exact spelling) | A sector spelled differently (e.g. a stale/partial Yahoo profile) falls through to the DCF path instead of the DDM path and will likely come back `NULL` on negative FCF |
| `TIMESTAMP WITH TIMEZONE` syntax error if re-authoring the schema by hand | Invalid PostgreSQL syntax — correct form is `TIMESTAMP WITH TIME ZONE` | Already fixed in the committed `db/schema.sql`; don't reintroduce this typo |
| `pytest` reports every test in `tests/integration/` skipped | Local PostgreSQL isn't running, or `TEST_DATABASE_URL` points somewhere unreachable | Start Postgres (`service postgresql start` / Windows service), or set `TEST_DATABASE_URL`; `tests/unit/` should still show as passed, not skipped, regardless |
| `pytest` reports *every* test skipped, including `tests/unit/` | A regression of the exact bug found during §10.12's own development: the database-reachability fixture became `autouse=True` again, so unit tests started depending on it despite never touching the DB | Confirm `_test_database` in `tests/conftest.py` is not `autouse` - only `db_session` should request it |

---

## 14. Notes for External Code Design Review (e.g. ChatGPT)

If handing this document plus the source to another model for review, the highest-value areas to interrogate are:

1. **`src/valuation/dividends.py`** — confirm the franking credit formula and the percentage-to-fraction conversion are correct against the current ATO methodology
2. **`src/valuation/dcf.py`** — confirm the two-stage DCF mechanics (particularly the terminal value formula and the point at which it's discounted back) match standard practice
3. **`src/valuation/engine.py`, `_estimate_shares_outstanding()`** — this single derived value cascades into four other metrics; worth an opinion on whether deriving it from `market_cap / price` is more or less reliable than the NPAT/EPS fallback
4. **`src/ingestion/yahoo_client.py`, `get_annual_fundamentals()`** — field-name mapping was fixed on 2026-10-01 after live data revealed a naming mismatch (see §10.6); a second opinion on whether the corrected PascalCase labels are complete/robust (and whether the fallback chains — e.g. `StockholdersEquity` vs `CommonStockEquity` — pick the right one in edge cases) would be valuable
5. **Upsert/coalesce strategy in `fundamentals_ingestion.py`** — worth confirming the "never let a NULL fetch overwrite good data" design is the right call versus simply always taking the latest fetch
6. **`src/valuation/engine.py`, `_average_free_cash_flow()`** — a straightforward simple mean over 3 years (§8.4); worth a second opinion on whether a recency-weighted average or outlier-trimming would be more defensible than an unweighted mean, particularly for cyclical or recently-restructured companies (SUN's own FY2023 debt collapse — likely a bank-arm divestment — is exactly this kind of structural break a simple mean doesn't account for)
7. **`src/valuation/ddm.py` and the sector routing in `engine.py`'s `compute_metrics()`** (added 2026-10-02, §8.3/§8.4) — two deliberate simplifications worth a second opinion: (a) `_SECTOR_AWARE_SECTORS` is an exact-string match against yfinance's two GICS-like sector labels (`"Financial Services"`, `"Real Estate"`) with no fuzzy matching or fallback if Yahoo's labelling is inconsistent for a given company; (b) the DDM reuses the same `--growth-rate`/`--discount-rate`/`--terminal-growth-rate`/`--stage1-years` CLI inputs as the DCF path rather than exposing a second set of dividend-specific assumptions, so a single `run_valuation --all` invocation applies one global growth-rate assumption to both FCF growth (DCF sectors) and dividend growth (Financial Services/Real Estate) — a reasonable simplification given the project's existing "one global assumption set" design, but worth checking whether a lower default growth rate specifically for sustained dividend growth (DDM's own default is 5% vs DCF's 8%, used only when the caller doesn't override) is adequate, or whether real-world bank/REIT dividend growth is better modelled with its own CLI-exposed default
8. **`src/valuation/engine.py`'s `_fundamentals_trend()`** (added 2026-10-02, §8.6) — a deliberately simple two-endpoint (latest vs oldest fetched FY report) heuristic on ROE and revenue direction, with fixed thresholds (2pp ROE, 5% revenue). Worth a second opinion on: whether two fixed thresholds are well-calibrated across very different company sizes/sectors (a 2pp ROE swing may be noise for a volatile miner but meaningful for a stable bank), whether a monotonic multi-point check across all fetched years (not just the two endpoints) would catch a mid-window dip/recovery that the current endpoint-only comparison misses, and whether `trap_risk`'s binary composite (`mos_ok AND fundamentals_trend == 'DECLINING'`) is the right combination logic versus, say, a severity-weighted score

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
| 2026-10-02 | Fixed the root design issue (known-issue #9): `engine.py`'s DCF now averages `free_cash_flow` over the last `fcf_average_years` (default 3) `FY` reports instead of using only the latest year. Configurable via `--fcf-average-years` on `run_valuation.py` (`1` restores old behaviour). Validated by replaying SUN's real 4-year FCF figures against a disposable PostgreSQL instance: confirmed the 3-year average computes exactly as expected ($2,210.67M, matching a manual calculation) and that intrinsic value scales monotonically and correctly across 1-year/3-year/4-year windows. On the live DB, SUN's margin of safety rose to 53.73% under the new default, and CHC switched from "DCF skipped" to "DCF computed" (still negative) - the fix can change *whether* a DCF runs, not just its value |
| 2026-10-02 | User requested widening the watchlist to the full ASX 300, in order to give SUN real competition to be judged against. Fixed two scaling blockers first (known-issue #10): `run_ingestion.py` gained `--tickers-file` (bulk ticker lists from a text file) and `--delay` (pacing between tickers); both ingestion modules now isolate each ticker in its own try/except so one bad ticker can't abort a multi-hundred-ticker batch. Both validated directly (file-parsing/dedup logic, and a simulated mid-batch crash that was caught, logged, and the batch continued). Flagged known-issue #11: no official ASX 300 constituent list is bundled or fabricated by this project - deliberately left to the user to source from an authoritative provider, rather than guessing at index membership |
| 2026-10-02 | User sourced their own 500-ticker All Ordinaries list (`allords.txt`) and ran a real ~500-ticker ingestion successfully. `run_valuation --all` then crashed with `psycopg2.errors.NumericValueOutOfRange` on a micro-cap whose DCF intrinsic value was near-zero, producing a −128,521.87% "margin of safety" that overflowed the `NUMERIC(6,2)` column - the first real production-scale failure of the project (known-issue #12). Investigation found a second, more serious issue it exposed (known-issue #13): `run_valuation()` committed only once at the end of the whole batch, so this single crash lost every other company's already-computed valuation work too, not just the one that failed. Fixed both same day: `margin_of_safety_percent()` now returns `None` past a 5000% sanity threshold instead of a wild number; `run_valuation()` now isolates and commits each company individually, matching the ingestion layer's existing pattern. Both validated directly: the guard against the exact failing inputs from the crash traceback, and the commit isolation against a simulated mid-batch crash confirming prior successes survive it |
| 2026-10-02 | After the fix, `screen_asx.py` returned 17 real matches from the ~500-company universe, including several well-known large-caps (RIO, FMG, JBH, QBE, PMV) alongside smaller names - a credibility signal that the pipeline is surfacing sensible results at scale, not just noise. Two results flagged for scrutiny: TWR's 106.85% yield was traced to a single `FY`'s dividend at 519% of EPS (prior years normal), almost certainly a special dividend/capital return - fixed by adding `payout_ratio` as known-issue #14 (see above). GQG's 104% ROE was verified against raw data (NPAT $463.252M / equity $444.474M) and confirmed genuine and structural (ROE has trended 76% → 81% → 104% → 104% over 4 years, not a one-off spike) - consistent with an asset-light fund manager's capital structure, no fix needed, left on the list as-is |
| 2026-10-02 | While implementing `payout_ratio`, found and fixed a real schema-migration bug before it reached the live database: `CREATE OR REPLACE VIEW` cannot insert a new column in the middle of an existing view's column list (only append at the end) - the first attempt (placing `payout_ratio` between `grossed_up_dividend_yield` and `dcf_intrinsic_value`) failed with `ERROR: cannot change name of view column` when tested against a simulated pre-existing database. Fixed by appending the column at the end of the view's `SELECT` instead (no effect on CLI output order, since `screen_asx.py` selects by name). Validated the full migration path end-to-end: an old-schema database with real data in it, upgraded via the new `db/schema.sql`, confirmed to both preserve the existing data and add the new column cleanly |
| 2026-10-02 | User re-ran `run_valuation --all` across the full 501-company database (after the schema migration above) and hit two more individual-company crashes, each on a different field than any guard already covered: BRN's `roic` at 10,129.90% (`NUMERIC(6,2)` overflow) and WHI's `pb_ratio` at ~203 million plus `roe` at 134,600% (`NUMERIC(10,2)`/`NUMERIC(6,2)` overflow). The #13 crash-isolation fix worked exactly as designed - 485/501 companies still valued successfully despite these two failures - but each of the two still lost its entire row to one bad field. Root-caused as the same overflow failure mode recurring on new fields, not a one-off: fixed with a generic `_clamp_to_column_precision()` guard (known-issue #15) applied to all 14 `valuation_metrics` columns before every upsert, derived mechanically from `db/schema.sql`'s own column definitions. Validated by replaying both companies' exact failing payloads from their tracebacks against a live PostgreSQL instance: both now upsert successfully, with only the pathological field nulled and every other valid field preserved |
| 2026-10-02 | User re-ran again: zero crashes, 487/501 valued (exactly the +2 recovery expected). But the console summary for WHI still printed `ROE=134600%` despite the database correctly holding `NULL` - caught directly from the user's own terminal output, not a self-generated test. Root cause: `run_valuation_for_company()` was returning its own pre-clamp `metrics` dict rather than the clamped one `upsert_valuation_metric()` computed and discarded internally - a real console-vs-database inconsistency, not a data bug. Fixed same day: `upsert_valuation_metric()` now returns the clamped dict, and callers use that, so logged/returned values are guaranteed to match what's actually stored. Validated end-to-end against a company engineered to overflow `roe`: both the returned dict and a direct database query now agree (`None` in both), where before the fix they disagreed |
| 2026-10-02 | User confirmed the fix live: re-ran `run_valuation --all` + `screen_asx.py` and pasted the full output. Zero crashes, zero errors across all 501 companies; WHI's console line now correctly reads `ROE=None%`, matching the database. The 17-company screener result is unchanged (expected - BRN/WHI never cleared thresholds either way). Pipeline considered stable and hardened at full watchlist scale as of this date |
| 2026-10-02 | User requested Windows Task Scheduler automation so the pipeline runs daily without manual commands (known-issue #16). Added `scripts/daily_refresh.ps1`: runs ingestion → valuation → screener in sequence (deliberately not stop-on-error chained, so one failed step doesn't block the rest), logs everything to a timestamped file under `logs\`, and prunes logs older than 30 days. Validated end-to-end in a disposable environment before handing to the user: installed PowerShell Core, seeded a throwaway PostgreSQL database with one real company via the ORM, and ran the script via `pwsh` - confirmed the log file correctly captured all three phase headers, a simulated network failure during ingestion didn't halt the later steps, and valuation/screener output was computed and logged correctly from the already-seeded data. Documented in README.md (`Daily Automation` section, with exact Task Scheduler trigger/action settings) and here (§16) |
| 2026-10-02 | User requested sector-aware valuation for financials/REITs (known-issue #8). Added `src/valuation/ddm.py`: a two-stage Dividend Discount Model with the same stage-1-growth-then-Gordon-Growth-terminal-value mechanics as `dcf.py`, substituted onto `dividends_per_share` instead of `free_cash_flow` (no shares-outstanding input needed - the DDM result is already per-share). `engine.py` now routes Financial Services and Real Estate companies (`_SECTOR_AWARE_SECTORS`, matching yfinance's exact sector spelling) to the DDM instead of the standard DCF, since these sectors' "free cash flow" is dominated by balance-sheet movements rather than reinvestment capex and isn't a meaningful DCF input - previously confirmed in practice with CBA (§10.6). Added a `valuation_method` column (schema + ORM + screener output) recording which model priced each company (`'DCF'`/`'DDM'`/`NULL`), using the same append-at-the-end-of-the-view lesson learned from known-issue #14's `payout_ratio` migration. `growth_rate` now defaults per-model (8% DCF / 5% DDM) when not explicitly set via `--growth-rate`, since dividend growth is typically a more conservative assumption than FCF growth - an explicit `--growth-rate` still applies uniformly to whichever model runs, as before. Validated with synthetic data on a disposable PostgreSQL instance (§10.9): a bank with negative FCF in all 4 years but a real, growing dividend history went from `margin_of_safety_percent = NULL` (old behaviour) to a real, usable 28.80%/37.26% figure (default/explicit-growth-rate runs respectively) depending on which growth assumption applied, confirming the per-model default resolves correctly; a control company (ordinary sector, positive FCF) was confirmed completely unaffected by the change. Also surfaced (not a defect): the screener's default `--max-debt-equity 0.80` is structurally unsuited to financials, documented as a threshold-tuning note in README.md/§9 rather than a new known-issue |
| 2026-10-02 | User asked for `screen_asx.py` to stop filtering non-matching companies out of the output and instead show every company with a visible pass/fail indicator per criterion. Rewrote the screener (§9): the four classic criteria (margin of safety, ROE, debt/equity, grossed-up yield) moved from a SQL `WHERE` clause to Python-side `annotate_row()`, adding one `Y`/`N` column per criterion (`mos_ok`/`roe_ok`/`de_ok`/`yield_ok`) plus a combined `overall` column (`AND` of all four by default, `OR` under `--any-of`, same logic as before - just an indicator now, not a filter). `--sector` remains a true SQL filter. Added `--passing-only` to restore the old filtered-to-matches-only view as an opt-in. Changed `--limit`'s default from 25 to unlimited, since showing everyone was the point of the change. Validated with three synthetic companies on a disposable PostgreSQL instance (§10.10): a clean pass, a clean fail, and a company with data missing on some but not all criteria - confirmed the partial-data company got a precise per-criterion readout (`Y` on the one metric it had and passed, `N` on the two it had no data for) rather than being blanket-excluded, and that `--any-of`, `--passing-only`, `--sector` and `--limit` all still behave correctly under the new design |
| 2026-10-02 | User asked whether another ranking could help catch a promising share before others do, and for a field to help identify a potential value trap (known-issue #17). Added two independent `valuation_metrics` columns: `margin_of_safety_trend` (price-driven - the change in margin of safety vs the most recent snapshot at least `trend_days` days old, default 30, new `--trend-days` flag on `run_valuation.py`) and `fundamentals_trend` (business-driven - `'IMPROVING'`/`'STABLE'`/`'DECLINING'` from ROE/revenue direction across the same multi-year `financial_reports` window used for the DCF/DDM average, known-issue #18). `screen_asx.py` gained two informational indicators deliberately excluded from `overall`: `momentum_ok` (margin_of_safety_trend above `--min-mos-trend`, default 5pp) and `trap_risk` (a composite: `mos_ok` cheap **and** `fundamentals_trend` declining - a candidate value trap), plus `--rank-by momentum` to sort by the trend instead of absolute margin of safety for a "catch it before others" view, and a `trap_risk` warning line matching the existing `payout_ratio` warning's style. `margin_of_safety_trend` is `NULL` for every company until `trend_days` of daily automation history has accumulated - a genuine cold-start gap the user explicitly anticipated ("a field that can populate in time"); the screener prints a note explaining this rather than leaving a blank column to look broken. `fundamentals_trend` has no such wait, since it only needs already-ingested annual report history. Validated with three synthetic companies on a disposable database (§10.11): a cheap-but-declining company correctly flagged `trap_risk = Y` despite also having positive price momentum (confirming the two signals are independent), a cheap-and-improving company correctly flagged `trap_risk = N`, and a brand-new company with no prior snapshot and only 1 FY report correctly showed blank trend fields rather than erroring |
| 2026-10-02 | User asked to address known-issue #6 (no automated test suite). Added `tests/` - a 79-test `pytest` suite, two tiers: `tests/unit/` (64 tests, pure functions + `compute_metrics()`, no database - `compute_metrics()` takes plain, unpersisted ORM objects) and `tests/integration/` (15 tests, a real local PostgreSQL instance via `tests/conftest.py`, which creates an `asx_test` database and applies `db/schema.sql` automatically). Several tests regression-pin real historical figures already documented in this table: SUN's 3-year FCF average ($2,210.67M, known-issue #9), TWR's payout ratio (518.70%, known-issue #14), and BRN/WHI's exact overflow values (known-issue #15) - per this project's own suggested-next-step to use them as test fixtures. `run_valuation()`'s per-company crash isolation (known-issue #13) is validated with a real forced exception via `monkeypatch`, not just a skip case. Found and fixed a real bug in the test suite itself during development: the database-reachability fixture was initially `autouse=True` at session scope, which skipped *every* test - including pure unit tests that never touch a database - the moment Postgres was stopped; caught by literally stopping Postgres and re-running the suite, fixed by making only `db_session` depend on it. See §10.12 |
| 2026-10-02 | User confirmed the DDM/trend/screener-redesign/test-suite work live on the real ~500-company database: re-applied `db/schema.sql` (idempotent, confirmed via `NOTICE: ... already exists, skipping` on every new column), re-ran `run_valuation --all` (487/501 valued, zero crashes - the only two warnings were the already-known BRN `roic`/WHI `pb_ratio`+`roe` overflow cases, caught and nulled exactly as designed), then `screen_asx.py` (487 rows shown, 16 passing `overall`, `margin_of_safety_trend` correctly blank for every company with the cold-start note printed, `fundamentals_trend` populated for every company with 2+ years of reports). Both warning lines fired against real data: `payout_ratio > 150%` for 29 tickers, `trap_risk` for 49. Cross-referencing the two lists surfaced a real, actionable finding: 10 tickers (GNC, YAL, IEL, RMC, OML, HZN, EDV, GNE, PRN, NHC) appear in **both** - an inflated yield from a likely special dividend *and* declining fundamentals *and* currently reading as cheap, exactly the combination `trap_risk` exists to catch. Pipeline confirmed stable and fully operational with every feature from this session's work (DDM, trend indicators, show-every-company screener, automated tests) now exercised together on live, non-synthetic data at full watchlist scale |
| 2026-10-02 | User asked for more decision points "to level me up as an investor", a suggested-action field (watch, investigate, buy, sell, hold), and a holdings table with tax-relevant fields. Added: four decision markers (earnings quality, price position, dividend reliability, data confidence - §8.7) as six new `valuation_metrics` columns; `src/screening/actions.py` giving every company an action and a plain-English reason (§9.1), with `--actions` and `--held` on the screener and the daily log switched to the action report; a parcel-level `holdings` table and `portfolio.py` CLI (add, sell with automatic partial-parcel splitting and `fifo`/`min-tax`/specific-parcel ordering, list, CGT report per financial year, delete) with Australian CGT arithmetic: cost base including brokerage, the 12-month discount test, losses applied to non-discountable gains first (§19). Held companies get SELL/REVIEW/HOLD, with a note when a parcel is within 90 days of the CGT discount. 77 new tests (156 total); schema migration verified over an old-schema database holding data; end-to-end CLI run found and fixed a `WATCH` reason omitting red flags (§10.13). Known issues #19-21 added |

---

## 16. Automation (`scripts/daily_refresh.ps1`)

**Purpose:** removes the need to manually run three separate commands (ingestion, valuation, screener) to keep the database current. Designed to be triggered daily and unattended by Windows Task Scheduler, after ASX market close.

**Design decisions:**
- **No stop-on-error chaining** (`;` between steps, not `&&` or `-and`): a transient Yahoo Finance network blip during ingestion should not prevent valuation/screener from still running against whatever data is already in the database from the previous day. Each step's own per-ticker/per-company error isolation (§7.3-§7.5, §8.4, known-issues #10/#13) already handles failures within a step; this script's job is only to make sure a whole-step failure doesn't cascade into skipping the rest of the pipeline.
- **Single timestamped log file per run** (`logs\refresh_<yyyy-MM-dd_HHmmss>.log`), capturing stdout and stderr from all three steps (`2>&1` redirect piped through `Add-Content`), so an unattended run can be checked after the fact without having to watch it live.
- **30-day log retention**, pruned at the end of every run (`Get-ChildItem` + `Where LastWriteTime` + `Remove-Item`), so the `logs\` folder doesn't grow unbounded on a machine that's left running this indefinitely.
- **Self-locating repo root** (`Split-Path -Parent $PSScriptRoot`): the script resolves every other path (venv activation, watchlist file, log directory) relative to its own location rather than a hardcoded path, so it keeps working if the repo is cloned or moved elsewhere.
- **Watchlist file is a single variable** (`$WatchlistFile`) at the top of the script, so switching from `allords.txt` to a narrower list (e.g. a sourced ASX 300 file, known-issue #11) is a one-line edit.

**Validation performed (2026-10-02, disposable test environment, not the user's machine):**
- Installed PowerShell Core (`pwsh`) to get a real PowerShell interpreter to test against.
- Created a disposable PostgreSQL database and seeded one real company (BHP) via the ORM, so the valuation/screener steps had real data to operate on.
- Ran a Linux-path variant of the script (the only difference from the real script: `.venv/bin/Activate.ps1` instead of `.venv\Scripts\Activate.ps1` - confirmed via `diff`) through `pwsh -NoProfile -File`.
- First attempt failed due to a test-setup artifact (the test copy was run from the wrong directory, so `$PSScriptRoot` resolved incorrectly) - not a script defect; fixed by placing the test copy inside `scripts/` as the real script would be, and re-ran.
- Second run succeeded end-to-end: the log file correctly showed all three phase headers with timestamps, correctly captured the (expected, sandbox-only) Yahoo network failure during ingestion without halting the script, and correctly computed and logged valuation + screener output from the seeded data.
- All test artifacts (test script copy, test `.env`, test watchlist file, `logs/` directory, disposable database) were deleted after validation; nothing from this test run is part of the committed repository.

**Task Scheduler wiring:** see the "Daily Automation" section of `README.md` for the exact one-time GUI setup (trigger time, action command line, recommended settings).

---

## 17. Prompts to Recreate This Project

A condensed, ordered record of the prompts that actually built this project, kept here as a design-intent record, for rebuilding an equivalent system elsewhere, and as onboarding context for anyone (human or AI) picking this up. Not a literal transcript - operational debugging exchanges ("run this command", "paste that output") are omitted; what's kept are the prompts that drove a design decision or a piece of work. The current repository already contains every fix below - don't replay this list against this repo, only against a fresh one.

1. **Schema.** Provided a draft PostgreSQL schema (companies, daily_prices, financial_reports, valuation_metrics, an `asx_value_screener` view) for an ASX value-investing database, targeting franking credits, dividend yields, debt/equity, and intrinsic valuation. → Fixed an invalid-syntax bug (`TIMESTAMP WITH TIMEZONE` → `TIMESTAMP WITH TIME ZONE`) found by actually running it, not just reading it.

2. **Full pipeline build.** *"You are an expert Python engineer and Quantitative Value Investing Analyst specializing in ASX equities. Build a Python module using yfinance to ingest daily prices and financial report histories for ASX listed stocks (append .AX to ticker codes). Compute ASX Grossed-Up Dividend Yields incorporating franking percentages [formula given]. Compute Graham Number = SQRT(22.5 × EPS × Book Value Per Share). Compute a 2-stage DCF intrinsic valuation model with customizable growth rate and baseline 8-10% discount rate. Set up SQLAlchemy ORM models matching all schema tables. Construct a CLI screener (screen_asx.py) querying the database for Margin of Safety > 20%, ROE > 12%, Debt to Equity < 0.80, Grossed-Up Yield > 4.5%. Set up the initial project folder layout (src/models, src/ingestion, src/valuation) and write the base code implementations."* → Produced the entire `src/` tree, `requirements.txt`, `.env.example`, `README.md`.

3. **As-built documentation.** *"Can you give me an as built document? I want to be able to use it to fault find, rebuild if required and have ChatGPT check code design."* → Produced `docs/AS_BUILT.md` with architecture, schema ERD, module design notes, a fault-finding table, a rebuild runbook, and notes aimed specifically at an external code-design review.

4. **Live validation, iteratively.** Ran the pipeline for real (not just unit-tested) against a handful of tickers at a time, in this order: `BHP CBA CSL WES WOW` → `GMG LLC CHC SUN RRF`. Each real run surfaced a genuine bug or design gap (wrong Yahoo field-name casing, single-year DCF volatility, no way to flag a special dividend) that got root-caused against the actual failing data and fixed before moving on - never patched speculatively.

5. **Scale.** *"Widen the watchlist to asx 300"* (and, practically, to a ~500-company All Ordinaries list the user sourced themselves). → Forced two real engineering fixes: bulk ticker input (`--tickers-file`, `--delay`) and per-company crash isolation in both ingestion and valuation, because a single bad company at that scale could otherwise lose the whole batch's work. Also forced two numeric-overflow fixes once genuinely pathological micro-cap data (10,000%+ ratios) started appearing, which never showed up at 5-9 ticker scale.

6. **This section.** *"Update my as built guide, with prompts to recreate. Include suggested next prompts to start next time."*

7. **Automation.** *"Automate via Windows Task Scheduler."* → Produced `scripts/daily_refresh.ps1` (ingestion → valuation → screener, logged, non-stop-on-error), validated in a disposable test environment before being handed to the user, plus the exact Task Scheduler GUI setup steps (README.md) and this section's design/validation notes.

8. **Sector-aware valuation.** *"Sector-aware valuation for financials/REITs (known-issue #8)."* → Produced `src/valuation/ddm.py` (two-stage Dividend Discount Model) and routing logic in `engine.py` directing Financial Services/Real Estate companies to it instead of the standard FCF-based DCF, plus a new `valuation_method` column so the screener shows which model priced each company. Validated with synthetic data (a bank with negative FCF in every year but a real dividend history) on a disposable database, confirming it now gets a real margin-of-safety figure instead of `NULL`, and that ordinary (DCF-path) companies are completely unaffected.

9. **Screener redesign - show everyone, don't filter.** *"Rather than filtering out tickers that don't meet the threshold, show them but with a visible indicator. Perhaps Y for yes it meets or N for no it doesn't."* → Rewrote `screen_asx.py` so the four classic criteria are Y/N indicator columns (plus a combined `overall`) computed in Python against every company, instead of a SQL `WHERE` filter that silently dropped non-matching rows. Added `--passing-only` to restore the old filtered view as an option, and changed `--limit`'s default to unlimited. Validated with three synthetic companies (clean pass, clean fail, partial data) on a disposable database.

10. **Trend indicators - momentum into value and a value-trap flag.** *"Is there another ranking to alert users to items worth looking at based on a trend? Something to help catch the next best share before others catch on?"*, followed by *"momentum into value sounds good. will be good to have a field that can populate in time to identify a potential value trap."* → Added `margin_of_safety_trend` (price-driven, needs accumulated daily history - a cold-start the user explicitly anticipated) and `fundamentals_trend` (business-driven, from existing annual reports, populates immediately), with `screen_asx.py` gaining `momentum_ok`/`trap_risk` indicators and a `--rank-by momentum` ranking. Validated with three synthetic companies (declining-fundamentals trap, improving-fundamentals momentum play, brand-new cold-start company) on a disposable database.

11. **Automated test suite (known-issue #6).** *"Address known-issue #6 (no automated test suite)."* → Added `tests/` - a 79-test `pytest` suite split into `tests/unit/` (pure functions, no database) and `tests/integration/` (real local PostgreSQL via `tests/conftest.py`), regression-pinned against SUN's/TWR's/BRN's/WHI's real documented figures. Found and fixed a real bug in the suite itself during development (an `autouse` fixture skipping every test, not just the DB-dependent ones) by literally stopping Postgres and re-running it.

12. **Decision markers, suggested actions and holdings.** *"Are there any other markers or decision points we should add to help level me up as an investor? And then add a field with variables advise on possible actions? For example watch, investigate, buy, sell, hold"*, then (choosing a database table for holdings) *"add tax beneficial fields. number of shares, buy price, sell price and dates bought, anything else that would be helpful for record keeping"*. → Added earnings quality, price position, dividend reliability and data confidence markers; a rule-based action plus reason for every company; a parcel-level `holdings` table and `portfolio.py` with Australian CGT record keeping.

---

## 18. Suggested Next Prompts

Ready-to-use prompts for picking this project back up. Each assumes you're starting a fresh session with the code already on your machine (`git pull` first) and the database already populated from the ~500-company All Ordinaries run.

**Resume / orient:**
> "Pull the latest from the Portfolio repo, read docs/AS_BUILT.md, and give me a one-screen status summary - what's working, what's outstanding, and what you'd recommend doing next."

**Deep-dive the strongest candidates (lowest data-quality doubt):**
> "Of the 17 companies currently clearing the screen, RIO, FMG, JBH, QBE and SUN are the ones with the least data-quality doubt attached. For each, pull the last 4 years of financial_reports, sanity-check the raw EPS/NPAT/equity/FCF trend, and tell me which ones look like genuine value versus which ones are being flattered by this quarter's numbers."

**Source and load the real ASX 300 (if you want the narrower, more liquid universe instead of the broader All Ords list):**
> "I've downloaded the current ASX 300 constituent list from [S&P/ASX source] and saved it as asx300.txt. Run the full ingestion and valuation pipeline against it and show me the screener results compared to what the All Ords run found."

**Automate it:** ✅ Done 2026-10-02 - see `scripts/daily_refresh.ps1`, §16, and README.md's "Daily Automation" section.

**Check the automation is actually running (after Task Scheduler has been live a few days):**
> "Check the last few files in logs\ and tell me whether the daily refresh has been running successfully, whether the screener results have changed, and flag anything that looks wrong (repeated ingestion errors, a day that didn't run at all, etc.)."

**Sector-aware valuation (known-issue #8):** ✅ Done 2026-10-02 - see `src/valuation/ddm.py`, §8.3/§8.4, §10.9, and the `valuation_method` column.

**Re-run a wider ticker list now that financials/REITs get a real valuation:**
> "Re-run ingestion and valuation across the full All Ordinaries watchlist now that Financial Services and Real Estate companies get a Dividend Discount Model instead of being silently skipped. Show me the screener results with --any-of or a higher --max-debt-equity for financials, and tell me which banks/insurers/REITs now clear a reasonable margin of safety that wouldn't have shown up before."

**Screener show-everyone redesign (Y/N indicators instead of filtering):** ✅ Done 2026-10-02 - see `screen_asx.py`'s `annotate_row()`, §9, §10.10. Run `python screen_asx.py` with no flags to see every company with `mos_ok`/`roe_ok`/`de_ok`/`yield_ok`/`overall` columns; `--passing-only` restores the old filtered view.

**See how many more companies are now visible with the new show-everyone screener:**
> "Run python screen_asx.py with no filters across the full watchlist and tell me: how many companies are shown in total, how many pass overall, and of the ones that don't pass, which are closest (failing only one indicator) - those are the most interesting ones to look at next."

**Trend indicators (momentum into value / value-trap flag, known-issue #17):** ✅ Done 2026-10-02 - see `margin_of_safety_trend`/`fundamentals_trend` (§8.6), `momentum_ok`/`trap_risk`/`--rank-by momentum` in `screen_asx.py` (§9), and §10.11 for validation. `margin_of_safety_trend` needs `--trend-days` (default 30) of accumulated daily history to populate - check in once the daily automation has been running that long.

**Check whether momentum/trend data has started populating:**
> "Run python screen_asx.py and tell me whether margin_of_safety_trend is populated yet (it needs ~30 days of daily automation history) - if it is, show me the top 5 by --rank-by momentum and flag anything with trap_risk = Y so I know to look closer before acting on it."

**Harden further (known-issue #6):** ✅ Done 2026-10-02 - see `tests/`, §10.12. Run `pip install -r requirements-dev.txt && pytest`. 64 unit tests need no database at all; 15 integration tests use a disposable `asx_test` database created automatically.

**Extend test coverage to the ingestion layer:**
> "tests/ currently covers the valuation layer only (dividends, graham, dcf, ddm, engine) and the screener. src/ingestion/ (yahoo_client.py, price_ingestion.py, fundamentals_ingestion.py, run_ingestion.py) has no test coverage yet - particularly the per-ticker crash isolation and the --tickers-file parsing/dedup logic. Add tests for those, using a mocked/stubbed yfinance response rather than hitting the real API."

**Sanity-check a specific result before acting on it:**
> "Before I act on [TICKER]'s result, pull its raw financial_reports history and walk me through whether the numbers feeding its valuation look trustworthy, the way we did for SUN and TWR."

**Decision markers, suggested actions, holdings (§8.7, §9.1, §19):** ✅ Done 2026-10-02.

**Walk me through today's action report:**
> "Here's today's python screen_asx.py --actions output. For each BUY and INVESTIGATE, explain in plain terms what the reason means, what I should check before acting, and which of them you'd look at first."

**Track dividend income and franking credits for tax time (known-issue #19):**
> "Add a dividends_received table linked to my holdings (payment date, amount, franking %) and a portfolio.py command that totals franked dividends and franking credits per financial year, alongside the CGT report."

**Tune the action rules once I've seen them on real data:**
> "Having watched the suggested actions for a few weeks, here's where they felt wrong: [examples]. Adjust the rules in src/screening/actions.py, keep a test for each change, and update §9.1."

---

## 19. Portfolio Holdings & CGT Record Keeping (`portfolio.py`, `src/portfolio/`)

**Purpose.** Lets the screener know what you own (so held companies get HOLD / REVIEW / SELL rather than buy-side actions, §9.1) and keeps the records Australian CGT needs. User choice: a database table rather than a file, with tax-relevant fields and anything else useful for record keeping.

**Parcel model.** One `holdings` row per parcel: every purchase, DRP allocation, bonus issue or transfer-in is its own parcel with its own acquisition date, because CGT (including the 12-month discount) is assessed per parcel. Fields: `asx_code`, `units`, `acquisition_method` (`PURCHASE`/`DRP`/`BONUS`/`TRANSFER`/`OTHER`), `buy_date`, `buy_price` (per share), `buy_brokerage`, `sell_date`, `sell_price`, `sell_brokerage`, `broker`, `notes`, `split_from_id`. Keyed on `asx_code` with no foreign key to `companies`, so anything can be recorded whether or not it's on the watchlist. `CHECK` constraints enforce positive units, non-negative prices, sell date on or after buy date, and sell date/price present together.

**Partial sales split the parcel.** Selling 30 of 100 units creates a new sold row for the 30 (`split_from_id` pointing to the original) and leaves the original row holding 70. Buy brokerage is apportioned by units (rounded to the cent, remainder kept on the open portion) so the combined cost base is unchanged to the cent; sale brokerage is apportioned across every parcel a sale consumes, with the last parcel taking the rounding remainder so nothing is lost.

**Sale order.** `fifo` (default, oldest first - also usually the parcels already past 12 months), `min-tax` (smallest taxable gain first per unit, counting the 50% discount: a $60 discounted gain is $30 taxable, so it's sold after a $10 undiscounted one; losses sort first), or `--parcel <id>` for specific identification. Identifying the parcel sold is permitted by the ATO; keep the trade confirmation that shows which you chose.

**CGT arithmetic (`cgt.py`).** Cost base = units x price + buy brokerage. Proceeds = units x price - sell brokerage. Discount eligibility: the sale must fall after the first anniversary of purchase (the 12 months excludes the acquisition and disposal days; a 29 February purchase anniversaries on 28 February). Financial year summary: discountable gains, non-discountable gains and losses; losses applied to non-discountable gains first, then discountable; 50% discount on what remains; leftover losses shown as carried forward. The 50% rate is for individuals and trusts (super funds 33 1/3%, companies nil).

**CLI.**
```
python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --brokerage 9.95 [--method DRP] [--broker CommSec] [--notes ...]
python portfolio.py sell BHP --units 30 --price 48.10 --date 2026-04-02 --brokerage 9.95 [--order fifo|min-tax] [--parcel 1a2b3c4d]
python portfolio.py list [--all]       # open parcels: cost base, value, unrealised gain, days held, discount date
python portfolio.py cgt [--fy 2025-26] # realised gains and the FY summary
python portfolio.py delete 1a2b3c4d    # fix a data-entry mistake
```

**Limits (known-issue #19).** Not tracked: dividend income and franking credits, losses carried forward from earlier years, and cost base adjustments from corporate actions (returns of capital, bonus/rights issues, consolidations, demergers). A record-keeping aid to reconcile against broker statements, not tax advice.

**Back it up.** Unlike market data, holdings can't be re-downloaded. The teardown command in §12 deliberately leaves the table alone, and a periodic `pg_dump -t holdings asx_value > holdings_backup.sql` keeps a copy outside the database.
