# ASX Value Investing Database & Screener — As-Built Document

| | |
|---|---|
| **Repository** | `davidstangherlin/Portfolio` |
| **Default branch** | `main` |
| **Document purpose** | Fault-finding, disaster recovery / rebuild, and third-party (e.g. ChatGPT) code design review |
| **Document version** | 2.3 |
| **Date** | 2026-10-06 (first issued 2026-09-15) |
| **Covers commits** | `d60ef53` (schema) to ETFs in Sift (2026-10-06); §15 has the full history |

---

## 1. Executive Summary

This system is a local ASX (Australian Securities Exchange) value-investing research tool, with a web interface called **Sift**. Each night it ingests prices and annual financial statements for about 500 ASX companies from Yahoo Finance, values every company (a two-stage discounted cash flow model, or a dividend discount model for banks, insurers and REITs), and computes the classic ratios, the franking-adjusted dividend yield, the Graham Number and the margin of safety. Every company is tested against four Graham/Buffett-style value tests, checked for quality and trend markers and red flags, scored on a 30-check score wheel, and given a suggested action with its reason (§8, §9).

Around that core:
- **Sift** (§20) shows it all in a browser, on a PC or a phone at home: a dashboard of what needs attention and what changed overnight, a filterable screener, a page per company with charts, and a searchable **Help** page (§23).
- **Portfolios** (§19, §19.1) keep parcel-level CGT records across several portfolios, each with its owner's tax type, with trades entered in the browser or at the command line.
- **Watchlists** (§22) follow companies without owning them, with notes and price or value triggers.
- **Track record** (§21) records what Sift said every night and scores it after 1, 3, 6 and 12 months against the average screened company, so the rules are judged on results.
- **Knowledge base** (§23): one file, `web/knowledge.json`, supplies the Help page, every hover explanation and the glossary of the Word rules document.
- **ETFs** (§25): every ASX exchange traded fund collected alongside the shares: its fund facts monthly from the ASX's own report, prices and distributions nightly with full history, and Sift's own total returns from 1 month to 10 years. Not valued or scored as companies. Sift shows them under their own heading, apart from shares: an ETF screener and page per ETF, and separate ETF sections on the dashboard, in portfolios and in watchlists (§26).
- **Admin console** (§24): every setting, formula and threshold in one registry, shown with its Help entry; every company figure shown step by step; and what-if scenarios that compare different settings with live on today's data without changing anything live.

**Status as at 2026-10-06:** in daily use on the user's Windows PC, refreshed by Windows Task Scheduler at 6 pm (§16), against a live PostgreSQL database of about 500 companies. All four stages of the Sift build (menu bar and dashboard, portfolios, watchlists, track record), the knowledge base and the admin console (phases 1 and 2) are complete, and stages 1 and 2 of ETFs (collection, and presenting them apart from shares) are built. 533 automated tests pass (§10.14). Yahoo Finance is blocked from the development environment, so live ingestion is exercised only on the user's PC (§10.7). The track record's first results arrive about a month after recording began.

**Architecture:**

```mermaid
flowchart LR
    subgraph External
        YF[Yahoo Finance]
    end
    subgraph Nightly["Nightly job (scripts/daily_refresh.ps1)"]
        SCH[apply_schema]
        ING[src/ingestion/]
        VAL[src/valuation/]
        REC[src/tracking/ record + score]
    end
    subgraph Storage["PostgreSQL (db/schema.sql)"]
        MKT[(companies, prices,\nreports, valuations)]
        MINE[(portfolios, holdings,\nwatchlists)]
        TR[(signal snapshots,\noutcomes, monthly)]
        VIEW[[asx_value_screener view]]
    end
    subgraph Use["What you use"]
        CLI[screen_asx.py / portfolio.py]
        GUI[gui.py: Sift]
        KB[web/knowledge.json]
        DOC[Word rules document]
    end

    YF --> ING --> MKT
    SCH --> Storage
    MKT --> VAL --> MKT
    MKT --> VIEW
    VIEW --> REC --> TR
    VIEW --> CLI
    VIEW --> GUI
    MINE <--> GUI
    MINE <--> CLI
    TR --> GUI
    KB --> GUI
    KB --> DOC
```

---

## 2. Repository Structure

```
Portfolio/
├── db/
│   └── schema.sql                      PostgreSQL DDL — source of truth for the data model
├── src/
│   ├── config.py                       DB connection resolution (env-var driven)
│   ├── settings.py                     Every adjustable setting: live values, ranges, formulas, guard rails (§24)
│   ├── models/                         SQLAlchemy 2.0 ORM layer
│   │   ├── base.py                     Declarative Base
│   │   ├── company.py                  Company model + relationships
│   │   ├── daily_price.py              DailyPrice model
│   │   ├── dividend_payment.py         DividendPayment model - one row per ex-dividend date (§20)
│   │   ├── financial_report.py         FinancialReport model
│   │   ├── holding.py                  Holding model - one share parcel (§19)
│   │   ├── portfolio.py                Portfolio model - a named owner with a tax type (§19.1)
│   │   ├── watchlist.py                Watchlist and WatchlistItem models (§22)
│   │   ├── signal_snapshot.py          SignalSnapshot model - what Sift said each night (§21)
│   │   ├── etf.py                      EtfMonthly and EtfPerformance models (§25)
│   │   ├── scenario.py                 Scenario model - a saved what-if: name, notes, changed settings (§24)
│   │   └── valuation_metric.py         ValuationMetric model
│   ├── ingestion/                      Yahoo Finance → database
│   │   ├── yahoo_client.py             yfinance wrapper, all external I/O isolated here
│   │   ├── common.py                   get_or_create_company(), ensure_profile() shared helpers
│   │   ├── dividend_history.py         Ordinary dividends per financial year, abnormal one-offs held out (§7.6)
│   │   ├── currency.py                 Converts statement figures into the share price's currency (§7.7)
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
│   │   ├── holdings.py                 Portfolios; parcel add/sell (with splitting)/delete/undo sale; position summaries
│   │   ├── views.py                    Portfolio figures for the web GUI: totals, positions, parcels, CGT by year (§19.1)
│   │   └── trade_input.py              Checks on trades typed into the browser, with plain-English errors (§19.1)
│   ├── admin/                          Admin console (§24)
│   │   ├── scenarios.py                What-if runs on cached inputs, live vs scenario comparison, saving
│   │   └── workings.py                 A company's figures step by step, and the sensitivity grid
│   ├── etf/                            ETFs (§25)
│   │   ├── asx_report.py               Finds, downloads and reads the ASX Investment Products report; loads the ETF list
│   │   ├── prices.py                   Nightly ETF prices and distributions, full history the first time
│   │   ├── performance.py              Total returns 1 month to 10 years, trailing yield, check against the report
│   │   ├── views.py                    ETF screener rows, an ETF's page, category averages, reference fund (§26)
│   │   └── run_etfs.py                 CLI entrypoint; nightly step 1b (§16); --inspect, --report
│   ├── apply_schema.py                 Applies db/schema.sql via .env; nightly step 0 (§16)
│   ├── screening/
│   │   ├── actions.py                  Suggested action + reason per company (§9.1)
│   │   ├── enriched.py                 Screener rows + scores + valuation status, shared by GUI and tracking (§21)
│   │   └── scores.py                   Score wheel: 5 axes x 6 yes/no checks (§20)
│   ├── watchlist/
│   │   └── lists.py                    Watchlists: names, entries with notes and triggers, trigger checks (§22)
│   └── tracking/                       Prediction track record (§21)
│       ├── signals.py                  Nightly signal snapshots, action changes, recording status
│       ├── record_signals.py           CLI entrypoint; nightly step 3 (§16)
│       ├── outcomes.py                 Scores signals at 1/3/6/12 months, monthly summary, 14-month deletion
│       ├── score_signals.py            CLI entrypoint; nightly step 4 (§16)
│       └── report.py                   Track record page: verdict, order check, missed, saved, still actionable
├── screen_asx.py                       Root-level CLI: the value screener
├── portfolio.py                        Root-level CLI: record parcels, list positions, CGT report (§19)
├── gui.py                              Root-level web GUI server: FastAPI over the screener's own loader (§20)
├── web/                                index.html, style.css, app.js - the GUI front end, no build step (§20)
│   └── knowledge.json                  The knowledge base: Help page, hover explanations, Word glossary (§23)
├── requirements.txt                    Pinned dependency versions
├── requirements-dev.txt                requirements.txt + pytest (§10.12)
├── pytest.ini                          Test discovery config (testpaths, pythonpath, integration marker)
├── .env.example                        Template for local DB credentials
├── .gitignore                          Excludes .venv/, __pycache__/, .env, logs/, watchlist files
├── README.md                           Setup + workflow quick-start
├── scripts/
│   ├── daily_refresh.ps1               Windows Task Scheduler automation (§16)
│   ├── build_rules_doc.js              Builds the Word rules document; glossary from web/knowledge.json (§23)
│   └── package.json                    The builder's one dependency (docx 9.8.1)
├── tests/                              pytest suite (§10.12, known-issue #6)
│   ├── conftest.py                     DB-reachability check, test-DB creation/schema apply, truncate-between-tests fixture
│   ├── unit/                           No database - pure functions + compute_metrics()
│   │   ├── _builders.py                In-memory Company/DailyPrice/FinancialReport/ValuationInputs factories
│   │   ├── test_dividends.py, test_graham.py, test_dcf.py, test_ddm.py
│   │   ├── test_engine.py              Sector routing, overflow clamping, trend fields - real historical regressions
│   │   ├── test_markers.py, test_cgt.py, test_actions.py
│   │   ├── test_dashboard.py           Nightly-log reading, stale-data weekday rule, valuation status
│   │   ├── test_knowledge.py           The knowledge base: IDs, links, hover labels, placeholders, glossary (§23)
│   │   ├── test_trade_input.py         Browser input checks, CGT discount by tax type, the cross-site write guard
│   │   ├── test_watchlist_triggers.py  Trigger thresholds and entry checks (§22)
│   │   ├── _etf_report.py              Builds spreadsheets shaped like the ASX report, in two layouts
│   │   ├── test_asx_report.py          Reading the ASX report: headings, groups, units, download fallbacks (§25)
│   │   ├── test_etf_views.py           Growth of $10,000, distributions by year, category averages (§26)
│   │   ├── test_etf_performance.py     Total returns, reinvestment, annualising, trailing yield (§25)
│   │   ├── test_yahoo_prices.py        Closes as traded, with splits and distributions (§25)
│   │   ├── test_settings.py            The settings registry: live values pinned, ranges, guard rails, modules read it (§24)
│   └── integration/                    Needs a real local PostgreSQL instance
│       ├── test_schema.py              Idempotent apply, view column coverage
│       ├── test_valuation_pipeline.py  gather_inputs/upsert/run_valuation crash isolation, markers end to end
│       ├── test_screener.py            build_query()/annotate_row() against the real view, held vs not-held actions
│       ├── test_portfolio.py           Parcel splitting, brokerage apportionment, sell order, guards
│       ├── test_ingestion.py           Franking by domicile, country backfill
│       ├── test_gui.py                 Web API payloads, dashboard and the password guard (§20)
│       ├── test_tracking.py            Signal snapshots: written once, stale valuations skipped, changes (§21)
│       ├── test_track_record.py        Scoring against made-up history, summary, deletion, report rules (§21)
│       ├── test_watchlists.py          Watchlist rules, API, and where watchlists show up (§22)
│       ├── test_etf_gui.py             ETF screener and page, ETFs apart in dashboard, portfolios, watchlists (§26)
│       ├── test_etfs.py                ETF loading, kept out of share screens, backfill, splits, performance (§25)
│       └── test_admin.py               Scenarios match live when unchanged, workings match the engine, admin API (§24)
└── docs/
    ├── AS_BUILT.md                     This document
    ├── OVERVIEW.md                     Plain-English summary: what, why, who
    └── ASX_Value_Screener_Rules_and_Methodology.docx   Every rule and threshold, with methodology and glossary
```

**Total custom code (2026-10-06):** about 8,300 lines across 62 Python files, 3,200 lines of web front end (`web/`) and 465 lines of SQL, plus `tests/`: 533 tests (409 unit, 124 integration) in 36 files, of which 98 are one text check per knowledge base entry. A coverage run puts the tested share of the code at 87% overall and 90% or more for everything added since 2026-10-05; the gaps are the Yahoo Finance network calls and the `run_ingestion` / `run_valuation` command wrappers (§10.14).

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
    companies ||--o{ dividend_payments : has
    companies ||--o{ signal_snapshots : has
    signal_snapshots ||--o{ signal_outcomes : "scored as"
    portfolios ||--o{ holdings : holds
    watchlists ||--o{ watchlist_items : lists
    companies ||--o{ watchlist_items : "watched as"

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
        varchar country "Yahoo domicile; drives franking"
        varchar trading_currency "share price currency, AUD on the ASX"
        varchar financial_currency "currency statements are published in"
    }
    dividend_payments {
        uuid company_id PK,FK
        date ex_date PK "ex-dividend date"
        numeric amount "per share, trading currency"
        boolean abnormal "one-off held out of dividend figures"
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
        numeric dividends_per_share "ordinary, per financial year"
        numeric abnormal_distributions_per_share "one-offs held out"
        varchar reporting_currency "statements converted from this"
        numeric fx_rate "rate applied at balance date"
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
        uuid portfolio_id FK "NOT NULL, ON DELETE RESTRICT"
    }
    watchlist_items {
        uuid watchlist_id PK,FK "ON DELETE CASCADE"
        uuid company_id PK,FK "ON DELETE CASCADE"
        text note
        numeric mos_above "trigger"
        numeric price_below "trigger, > 0"
    }
    portfolios {
        uuid portfolio_id PK
        varchar name UK
        varchar tax_type "INDIVIDUAL/TRUST/SMSF/COMPANY"
        timestamptz archived_at "NULL while active"
    }
    signal_snapshots {
        uuid company_id PK,FK
        date snapshot_date PK "the price date the valuation used"
        numeric price
        varchar action
        boolean held
        varchar valuation_status
        numeric margin_of_safety_percent
        numeric estimated_value
        smallint score_total "plus one column per spoke"
        boolean mos_ok "plus roe_ok, de_ok, yield_ok"
        text_array red_flags
        varchar rules_version
    }
```

### 4.2 Constraints of Note

- `companies.ticker` and `companies.asx_code` are both `UNIQUE`
- `holdings.portfolio_id` is `NOT NULL` and `ON DELETE RESTRICT`: a portfolio can't be deleted out from under its parcels at the database level; `delete_portfolio()` removes open parcels first and refuses outright once there are sales (§19.1)
- `signal_snapshots` has `PRIMARY KEY (company_id, snapshot_date)`, and the recorder inserts with `ON CONFLICT DO NOTHING`: a date once recorded is never rewritten (§21)
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
- `YahooClient.get_profile()` — company name / sector / industry / country (used when creating a new `Company` row, and once per existing company to backfill `country`)
- `YahooClient.get_price_history(period)` — daily close/volume/market-cap bars; market cap is derived as `close_price × sharesOutstanding` (from `yfinance`'s `.info`) since Yahoo's history endpoint doesn't return market cap directly
- `YahooClient.get_annual_fundamentals(max_years)` — pulls income statement, balance sheet, and cash flow statement (annual frequency), maps Yahoo's field names onto our schema's columns
- `YahooClient.get_fx_history(from, to, start, end)` — daily exchange-rate closes (e.g. `USDAUD=X`) for currency conversion (§7.7); `get_profile()` also returns `trading_currency` (`info["currency"]`) and `financial_currency` (`info["financialCurrency"]`)
- `YahooClient.get_dividend_payments()` — every per-share dividend payment from `ticker.dividends` (ex-date, amount), raw. Financial-year matching and abnormal-distribution exclusion happen in `dividend_history.py` (§7.6). Replaced `get_dividends_per_share(fiscal_year)`, which summed by calendar year (2026-10-05)

**Every method here is defensive**: wrapped in `try/except Exception`, logs and returns `None`/`[]`/`{}` rather than raising, because Yahoo's field availability is inconsistent across companies and changes without notice. This was a deliberate design decision, not an oversight — see §8.2.

**Field mapping is best-effort.** Example: `free_cash_flow` is read directly from Yahoo if present, otherwise derived as `Operating Cash Flow + Capital Expenditure` (Yahoo reports capex as an already-negative outflow). `total_debt` falls back to `Long Term Debt + Current Debt` if Yahoo's consolidated `Total Debt` field is absent.

**Not sourced from Yahoo at all:** franking percentage, corporate tax rate. Yahoo has no concept of Australian franking credits. These are defaulted in `fundamentals_ingestion.py` (see below), using Yahoo's reported `country` to set foreign-domiciled companies to 0% franked (added 2026-10-05).

### 7.2 `common.py` — `get_or_create_company()`

Looks up a `Company` by `asx_code`; if absent, creates one using `YahooClient.get_profile()` data (falling back to the bare ASX code as the company name if the profile fetch fails). Called by both ingestion modules before fetching prices/fundamentals — **this means a `Company` row can exist with no price or financial data at all**, if the network call for profile succeeded (or even failed with a fallback name) but the subsequent price/fundamentals call failed. This was observed directly during testing (see §10.2) and is handled correctly downstream by `engine.py` (skips companies with incomplete data rather than erroring).

**`ensure_country()` (added 2026-10-05):** backfills `companies.country` for rows created before the column existed. Called from fundamentals ingestion only (not prices-only runs), it costs one profile request per company, once; a company Yahoo reports no country for stays `NULL` and is retried next run.

### 7.3 `price_ingestion.py`

`ingest_daily_prices(session, asx_codes, period, delay_seconds)` — for each ticker: get-or-create the company, fetch the price history, and `INSERT ... ON CONFLICT (company_id, price_date) DO UPDATE` each bar. On conflict, `close_price`, `volume`, and `market_cap` are all overwritten with the new fetch's values (no coalescing — a price is a fact-for-that-day, so the newest fetch should always win).

**Per-ticker isolation (added 2026-10-02):** each ticker's processing is wrapped in its own `try/except` — an unexpected failure (network blip, malformed response, DB error) is logged via `logger.exception` (full traceback) and `session.rollback()`'s that ticker's partial work, then the loop continues to the next ticker rather than aborting the whole run. This matters once `asx_codes` is large: hitting at least one edge-case ticker over a few hundred is likely, and losing the rest of the batch to one bad ticker would be a costly failure mode. Validated directly: a simulated crash on ticker 2-of-4 was caught and logged, the batch continued to tickers 3 and 4, and the database ended up with exactly the 3 successful companies and no orphaned/partial row for the failed one (the `session.rollback()` cleanly undoes that ticker's `get_or_create_company()` flush too).

`delay_seconds` sleeps between tickers to reduce the chance of Yahoo's informal rate limiting on a large batch (there's no officially documented limit to tune against — this is a precaution, not a guarantee).

### 7.4 `fundamentals_ingestion.py`

`ingest_fundamentals(session, asx_codes, max_years, delay_seconds)` — same get-or-create pattern, per-ticker isolation, and delay pacing as `price_ingestion.py` above, then `INSERT ... ON CONFLICT (company_id, fiscal_year, period_type) DO UPDATE`.

**Important design decision:** on conflict, most numeric columns use `COALESCE(excluded.col, financial_reports.col)` — i.e. **a `NULL` from a fresh fetch never overwrites a previously-stored value**. This guards against a partial/flaky Yahoo response silently wiping out previously good historical data on a re-run. `franking_percentage` and `corporate_tax_rate` are the exception: they are resolved to explicit defaults (`100.0` / `30.0`) in Python *before* the insert if Yahoo doesn't supply them (which it never does), so they are never `NULL` going in and the coalesce question doesn't arise for them.

**Franking by domicile (added 2026-10-05, known-issue #2):** `franking_percentage_for()` sets 0% for any company whose `country` is known and isn't Australia (NZ, US, Irish and other foreign listings pay no Australian franking credits), otherwise the 100% default. For foreign companies the on-conflict update also writes `franking_percentage`, so years stored at the old 100% default are corrected on the next run. Australian rows are deliberately left alone on update so a hand-corrected partial franking figure survives re-ingestion.

### 7.5 `run_ingestion.py` — CLI

```
python -m src.ingestion.run_ingestion (--tickers BHP CBA CSL | --tickers-file watchlist.txt | both) [--period 1y] [--prices-only | --fundamentals-only] [--max-years N] [--delay SECONDS]
```

**`--tickers-file`** (added 2026-10-02) reads ASX codes from a plain text file — one or more per line, whitespace- or comma-separated, blank lines and `#`-comments ignored. This exists specifically for large watchlists (e.g. a full index's constituents) where typing hundreds of codes on the command line isn't practical. `--tickers` and `--tickers-file` can be combined; the combined list is deduplicated case-insensitively, preserving first-seen order. Validated directly against a sample file mixing comma-separated, whitespace-separated, commented, and duplicate (differently-cased) entries — all parsed and deduplicated correctly.

**`--delay`** (added 2026-10-02) — see §7.3.

### 7.6 `dividend_history.py` — ordinary dividends per financial year (added 2026-10-05)

Pure functions that turn the raw payment list into `financial_reports.dividends_per_share` and the new `abnormal_distributions_per_share`. Found on Tower (TWR), whose 519% payout ratio was real arithmetic on bad input.

- **Abnormal distributions.** For each payment, the "typical annual dividend" is the median of the trailing-twelve-month totals at every other payment within three years of it. A payment more than `ABNORMAL_DISTRIBUTION_MULTIPLE` (2) times that is abnormal: excluded from `dividends_per_share` and summed into `abnormal_distributions_per_share`. Needs at least 2 comparable payments, otherwise nothing is excluded. Using annual totals rather than individual payments means an uneven split (a 2c interim and a 10c final) is not mistaken for a one-off. Tower's A$1.0777 capital return (1 in 10 shares cancelled, recorded by Yahoo against every share) is about ten times its usual year and is excluded; its 15c final dividend is not.
- **Financial-year matching.** A financial year takes ex-dates in the twelve months ending `FY_DIVIDEND_LAG_MONTHS` (4) after its balance date: the interim paid during the year plus the final paid after it, for June, September and December year-ends alike; quarterly payers still total twelve months. If that window hasn't closed, it falls back to the twelve months to today.
- **Zero versus missing.** A company with any dividend history that paid nothing in a year now gets 0, not NULL. Because `dividends_per_share` is in `_COALESCE_ON_UPDATE`, a NULL would have kept a stale stored figure; a 0 overwrites it. NULL now means no dividend history at all.
- **Scope of the correction.** Applied on the next fundamentals ingestion to every year Yahoo returns (the latest four). An older stored fifth year keeps its calendar-year figure; it only feeds `dividend_trend`'s oldest point.
- **Surfaced, not silent.** The web GUI's dividend card states any excluded amount and lists it in its data table.

### 7.7 `currency.py` — statements in the share price's currency (added 2026-10-05, known-issue #25)

- **The problem.** Yahoo returns each company's statements in its reporting currency (`info["financialCurrency"]`): USD for most large miners, NZD for NZ listings. Prices are in the trading currency (`info["currency"]`, AUD on the ASX). Nothing converted between them, so a US-dollar EPS or free cash flow was set against an Australian-dollar price.
- **Where it's fixed.** At ingestion, so everything downstream (engine, view, screener, GUI) works in one currency without change. `ensure_profile()` (`common.py`, replacing `ensure_country()`) backfills `companies.trading_currency` and `financial_currency` once per company; a profile without a statements currency means statements in the trading currency. `fundamentals_ingestion.convert_to_trading_currency()` fetches the daily exchange-rate history once per company (`YahooClient.get_fx_history()`, e.g. `USDAUD=X`) and `currency.apply_conversion()` multiplies every statement field (`MONETARY_FIELDS`: revenue through net tangible assets, including EPS) by the rate on each report's own balance date: the last close on or before it, no more than 10 days old (balance dates often fall on weekends).
- **Not converted.** `dividends_per_share` and `abnormal_distributions_per_share`: Yahoo's dividend feed is already per share in the trading currency.
- **Recorded.** `financial_reports.reporting_currency` and `fx_rate` say what was done (rate 1 for same-currency companies). The GUI's Key ratios panel shows it.
- **Failure is loud, not silent.** No usable rate raises `CurrencyConversionError`; per-ticker isolation logs it and skips that company's fundamentals for the run, rather than storing figures in the wrong currency.
- **Scope.** Applied on the next fundamentals ingestion to the four years Yahoo returns. An older stored fifth year stays unconverted; only its dividend (already in AUD) is used, by `dividend_trend`.
- **Residual effect.** Each year converts at its own rate, so `fundamentals_trend`'s revenue change is in AUD and includes currency movements. ROE, ROIC, cash conversion and debt/equity are ratios within one year and unaffected.

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
| `dividend_trend` | Is the dividend dependable? | Over up to 5 FY reports: `CUT` if the latest dividend is more than 10% below last year's or below the median of the earlier years (a cut that still stands), `GROWING` if the latest is >5% above the oldest, `STEADY` otherwise, `NONE` for non-payers. Revised 2026-10-05: previously any year-on-year drop in the window counted, which flagged nearly every miner and energy producer for dividends they vary with earnings by policy | A yield is only worth what its reliability is worth. A year after a special dividend correctly reads as a cut in cash terms; `payout_ratio` flags the special year itself, and the median stops one special year from inflating the baseline |
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
| `ACCUMULATE` | still passes all four value tests with no red flags: the same bar as `BUY` for a share you don't own, so consider adding (notes momentum if `momentum_ok`). Added 2026-10-05 |
| `HOLD` | otherwise: no red flags, but fails one or more tests (named in the reason), so not a candidate to add to |

**CGT timing note.** On `SELL`/`REVIEW`, if a held parcel reaches the 12-month CGT discount within 90 days, the reason says how many units, from what date, and how many days away - waiting can halve the tax on the gain. Never added to `ACCUMULATE` or `HOLD`, since neither suggests selling.

**Presentation.** The full table gains `earnings_quality`, `price_signal`, `dividend_trend`, `data_confidence`, `held` and `action` (raw marker numbers stay in the database; company names are truncated to keep width down). `--actions` prints a grouped report instead (SELL, REVIEW, ACCUMULATE, HOLD, BUY, INVESTIGATE, WATCH, AVOID) with the wrapped reason per company, action counts, any holdings that aren't on the screening watchlist, and a one-line reminder that these are rule-based research prompts, not financial advice. `--held` restricts either view to companies you hold. The daily automation log now records `--actions` rather than the full table.

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

### 10.14 Web GUI, Portfolios, Watchlists, Track Record and Admin Console (2026-10-05 to 2026-10-06)

- **533 tests** (409 unit, 124 integration), up from 156 at §10.13. Presenting ETFs (§26) added 25: the ETF page helpers, the ETF APIs, and ETFs kept apart on the dashboard, in portfolios and in watchlists, plus 14 Help entries. ETF collection (§25) added 80: reading the ASX report in two layouts, the performance maths, the raw-price change and the database steps end to end. The admin console (§24) added 26: the settings registry (`test_settings.py`), scenarios, workings and the admin API (`test_admin.py`), and five knowledge base entries. The knowledge base (§23) added 85 of them: integrity checks in `test_knowledge.py`, including one text check per entry, and a served-behind-the-password check. New since then: the web API end to end (`test_gui.py`), signal recording (`test_tracking.py`), track record scoring against 13 months of made-up daily history (`test_track_record.py`), portfolios and the CLI (`test_portfolio.py`), watchlists (`test_watchlists.py`, `test_watchlist_triggers.py`), browser input checks and the same-page write guard (`test_trade_input.py`), and the dashboard's log and stale-data rules (`test_dashboard.py`).
- **Schema:** re-applied (idempotent), upgraded from an older database with existing parcels (moved into "My portfolio"), and built from an empty database. The last caught a table created before the one it refers to, which every pre-existing test database had hidden.
- **Coverage check** (`coverage run -m pytest`, re-run 2026-10-06): 87% of statements overall; 95% to 97% for the admin console's modules (`src/settings.py`, `src/admin/`); 90% to 100% for every module added on 2026-10-05, after tests were added for the still-actionable grouping, both nightly track record commands, the GUI's start-up schema step and unarchiving. Not covered by tests: the Yahoo Finance network calls and the `run_ingestion` / `run_valuation` command wrappers, which are exercised by the nightly job on the user's PC (Yahoo is blocked from the build environment, §10.7).
- **In the browser:** each stage was driven in headless Chromium against seeded disposable databases at 1280px, 1000px and 390px, light and dark, through every create, edit, delete and error path, before release.

---

## 11. Known Issues & Design Limitations

| # | Issue | Impact | Suggested Resolution |
|---|---|---|---|
| 1 | `current_ratio` always `NULL` | Screener can't filter on liquidity | Add `current_assets`/`current_liabilities` columns to `financial_reports` if this metric matters |
| 2 | Franking % / tax rate default to 100% / 30% for Australian companies | Wrong grossed-up yield for LICs or any partly-franked Australian payer | Partly resolved 2026-10-05: foreign-domiciled listings are now set to 0% from Yahoo's `country` (§7.4). Remaining cases: manually correct affected rows (the correction survives re-ingestion); no automated source exists. A foreign company that attaches some Australian franking (rare) is now understated |
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
| 22 | Pulling code that added a column broke the live database until `db\schema.sql` was reapplied by hand (happened three times) | Every company failed valuation; the screener and `portfolio.py` errored | Resolved 2026-10-05: `python -m src.apply_schema` applies the schema through `.env` (no psql/password), and `daily_refresh.ps1` runs it first every night (§16) |
| 23 | Web GUI phone access uses HTTP Basic authentication over plain HTTP | On a shared or compromised network the password and holdings could be read in transit | Use `--lan` only on your own home Wi-Fi (network set to Private), never port-forward it; the default mode listens on this PC only |
| 24 | Yahoo's dividend feed mixed in one-off distributions and was summed by calendar year | A capital return read as a dividend (TWR: 519% payout, 107% yield, inflated DDM value, false "cut"); dividends half a year out of step with earnings for September and December year-ends | Resolved 2026-10-05: `dividend_history.py` (§7.6) excludes abnormal distributions (shown, not hidden) and matches dividends to each financial year |
| 25 | No currency conversion between financial statements and share prices | Yahoo reports some companies' statements in USD (many miners, e.g. BHP, RIO, S32) or NZD (NZ listings) while ASX prices are in AUD; EPS, book value and free cash flow were compared to an AUD price unconverted, distorting P/E, P/B, estimated value, margin of safety and the Graham Number by the exchange rate | Resolved 2026-10-05: statements converted into the trading currency at each balance date's rate during ingestion (§7.7). Residual: revenue trend is measured in AUD, so it includes currency movements |
| 26 | The track record starts from the night signal recording first runs (stage 1, 2026-10-05) and can't be backfilled | No accuracy results until a month after the first recording; 12-month results take a year. Reconstructing past signals from today's data would use information the rules didn't have at the time, flattering the results | By design. The dashboard and Track record page show when each horizon's first results are due |
| 27 | Parcels can't be moved between portfolios, and changing a portfolio's tax type re-rates its past sales | An off-market transfer (for example shares moved into an SMSF) has to be entered as a sale in one portfolio and a buy in the other, which is also how the ATO treats it; a tax type changed by mistake changes the CGT report until changed back | By design for now. A transfer feature would need to record the change of ownership date and value |
| 28 | Watchlist triggers are a state, not an alert | A trigger shows while it's true (dashboard, watchlist page) and disappears when it stops being true; nothing is sent, and a trigger met and lost between two visits isn't recorded | By design for now. The nightly signal record (§21) could later keep trigger history if wanted |
| 29 | The benchmark is the plain average of the screened companies, not an index | Small companies count as much as large ones, so a BUY list tilted to large companies is judged against a small-company-heavy average; brokerage, tax and timing within the day are ignored | By design: it measures whether the rules pick better companies from the ones they look at, which an index wouldn't. A market-capitalisation-weighted benchmark could be added alongside |
| 30 | What-if scenarios are judged on today's data only, and keep momentum at its live value | A scenario shows what would change tonight, not whether it would have done better over the past year; a scenario that moves the margin of safety a lot is shown with the live trend | By design for phases 1 and 2 (§24). Phase 4 (backtesting a scenario against the track record's history) would answer the first; nothing changes live until a scenario is deliberately published (phase 3, not built) |
| 31 | Share prices stored before 2026-10-06 were dividend-adjusted a month at a time | Closes in the month before each ex-date were scaled down by that dividend and older ones weren't, leaving a small step at each ex-date in charts, the 52-week range and the 200-day average | Fixed for new prices (§25). To clean the existing history once: `python -m src.ingestion.run_ingestion --tickers-file allords.txt --prices-only --period 2y` |
| 32 | The ETF report reader was built without seeing the real spreadsheet | A heading worded differently from anything expected is kept in `raw` but not mapped to its column | Run `python -m src.etf.run_etfs --inspect` on the first downloaded report and adjust `match_field()` for anything not found (§25) |

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

# 4. Configuration, then the schema (no psql needed; safe to re-run)
cp .env.example .env
# edit .env → DATABASE_URL=postgresql+psycopg2://postgres:change_me@localhost:5432/asx_value
python -m src.apply_schema

# 5. Run the pipeline (1y+ of prices so the 200-day price markers populate, §8.7)
python -m src.ingestion.run_ingestion --tickers BHP CBA CSL WES WOW --period 2y
python -m src.valuation.run_valuation --all
python -m src.tracking.record_signals    # starts the track record (§21)
python -m src.tracking.score_signals     # scores signals once 1/3/6/12 months have passed
python screen_asx.py --actions

# 6. (Optional) Record holdings so held companies get SELL/REVIEW/ACCUMULATE/HOLD (§19);
#    or record them in Sift (step 7)
python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --brokerage 9.95

# 7. (Optional) Sift, the web GUI (§20): http://localhost:8000
python gui.py

# 8. (Optional) Run the test suite (§10.12, §10.14) - uses its own asx_test database,
#    created automatically, never the one configured above
pip install -r requirements-dev.txt
pytest
```

From then on, the schema update and step 5's commands run nightly via `scripts/daily_refresh.ps1` (§16).

**Full teardown/reset** (destroys all ingested data, keeps schema definition intact for re-apply). `holdings` and `portfolios` are deliberately not in this list - parcel records are your tax records, not re-downloadable market data. Because the other tables refer to `companies`, `CASCADE` also empties `dividend_payments`, `signal_snapshots` and `signal_outcomes` (the last 14 months of track record detail) and `watchlist_items` (every watchlist's companies, notes and triggers; the lists themselves stay). `track_record_monthly` survives. Back up first if you want those back:
```bash
psql "$DATABASE_URL" -c "TRUNCATE companies, daily_prices, financial_reports, valuation_metrics CASCADE;"
```

---

## 13. Fault-Finding Guide

| Symptom | Likely Cause | Check / Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | Running a script from outside the repo root, or `PYTHONPATH` not set | Always run `python -m src.x.y` or `python screen_asx.py` **from the repo root** with the venv active |
| `UndefinedColumn: column ... does not exist` or `relation "holdings" does not exist` | The code is newer than the database schema (known-issue #22) | `python -m src.apply_schema`, then re-run the command. The nightly job does this automatically, and so does starting `python gui.py` |
| A Sift page shows "Could not load" | The server hit an error. Since 2026-10-05 the page shows the cause; before that only "Request failed (500)" | Read the message on the page (the full traceback is in the window running `gui.py`). "Missing a table or column" means the fix above |
| Phone can't open the GUI, or the browser keeps asking for a password | `--lan` not used, the firewall rule is missing, the Wi-Fi network is set to Public, or the wrong `GUI_PASSWORD` | Run `python gui.py --lan`, add the `netsh` rule (README, Web GUI), set the network to Private; any username plus the `.env` password |
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
| 2026-10-05 | After the first live action report, two rules were producing noise. (1) `dividend_trend` flagged any year-on-year drop over 5 years, which caught nearly every miner and energy producer and alone pushed a held BHP to REVIEW; revised to flag only a cut that still stands (latest >10% below last year or the earlier-years median), wording changed to "dividend cut and not yet restored" (§8.7). (2) Foreign-domiciled listings (SKT, GQG, SPK and others) were grossed up as fully franked; added `companies.country` from Yahoo, backfilled once per company, and set foreign companies to 0% franked, correcting already-stored years (§7.4, known-issue #2). Also added `python -m src.apply_schema` and made it step 0 of the nightly job, after the same missing-column failure hit the live database a third time (known-issue #22, §16). 21 new tests (177 total); migration verified over an old-schema database holding data |
| 2026-10-05 | User asked for a buy-more action for shares already held, as more useful than SELL/HOLD/REVIEW alone. Added `ACCUMULATE`: a held share that still passes all four value tests with no red flags (the same bar as `BUY`). `HOLD` now means no red flags but failing a test, and names the failed tests. Report order SELL, REVIEW, ACCUMULATE, HOLD. 3 new tests (180 total); rules document updated |
| 2026-10-05 | User asked for an interactive HTML GUI, Simply Wall St style. Chose: local web app, screener table and company page, phone access on home Wi-Fi. Added `gui.py` (FastAPI, read-only, reusing the screener's own row loader via a new `load_annotated_rows()`), a no-build-step front end in `web/` drawing every chart as inline SVG, and `src/screening/scores.py`: a score wheel of 5 axes x 6 named yes/no checks. `--lan` requires `GUI_PASSWORD` (HTTP Basic on every route, static files included). Validated against a seeded disposable database in headless Chromium at desktop and phone widths, light and dark: fixed a hidden button showing, chart text scaling with card width (charts now draw at their real pixel width), a stray `null`, and phone column overflow. 14 new tests (194 total). Known issue #23 |
| 2026-10-05 | User asked for a hover explanation on each table heading in the web GUI. Added explanations to all 10 screener headings and all 18 company-page labels (markers and key ratios): hover or keyboard focus with a mouse, a tap-able "i" on touch screens. Thresholds in the text come from the live screener settings. Checked in headless Chromium at desktop and phone sizes: first version's "i" icons pushed the Action column off a 1280px screen, so they now show only on touch screens, with a dotted underline as the desktop cue |
| 2026-10-05 | User asked for explanations on the estimated value and Graham Number bars, and for the Graham Number's definition. Added hover/tap explanations to all three valuation bar labels; the estimated value text states the company's model and its assumptions. Corrected the rules document (section 4.6), which still said the Graham Number fed nothing: it is one of the score wheel's Value checks |
| 2026-10-05 | User asked whether TWR's "payout ratio 519%" with "dividend cut and not yet restored" meant a wrong formula. The formula was right; the input wasn't: Yahoo recorded Tower's March 2025 capital return (A$1.0777 per cancelled share) as a dividend on every share, and dividends were summed by calendar year. Added `src/ingestion/dividend_history.py` (§7.6): abnormal one-offs (over 2x the typical annual dividend) excluded and stored in new column `financial_reports.abnormal_distributions_per_share`, and dividends matched to each financial year (12 months of ex-dates ending 4 months after balance date). Web GUI shows excluded amounts; dividend help texts updated. Also found and logged known-issue #25 (no currency conversion for USD/NZD reporters). 12 new tests (206 total) |
| 2026-10-05 | User asked to fix known-issue #25 (no currency conversion). Added `src/ingestion/currency.py` (§7.7): statements converted into the trading currency at each balance date's exchange rate during ingestion, dividends left as is; `companies.trading_currency`/`financial_currency` and `financial_reports.reporting_currency`/`fx_rate` added; `ensure_profile()` replaces `ensure_country()`; no rate means the company is skipped for the run, never stored unconverted. GUI Key ratios shows the accounts currency and rate. 11 new tests (217 total) |
| 2026-10-05 | User asked to review a Gemini UI mock-up and apply it if good. Reviewed and declined as-is (hard-coded sample valuations, misstated methodology, CDN/in-browser JSX dependencies, defects); rebuilt its ideas in the existing front end at the user's choice: renamed Sift, restyled (palette re-validated, separate UI accent), Light/Dark/System theme switch, valuation status pill, company summary strip with implied upside and the model's assumptions, responsive breakpoints. 2 new tests (219 total). §20 |
| 2026-10-05 | User asked for the score breakdown to collapse, keeping each spoke's score visible, with a pink twisty. Each spoke is now a collapsible section, closed by default, plus Expand all / Collapse all. Checked in headless Chromium, light and dark. §20 |
| 2026-10-05 | User asked for the 0% line in "Margin of safety over time" to be pink. The zero line now uses the pink `--twisty` token (1.5px, `.zero-line`), and the chart's hint explains it (0% = price equals estimated value). §20 |
| 2026-10-05 | User asked for a pink "D" on the 12-month price chart when a dividend is paid, added to the legend and table. Added `dividend_payments` table and model (individual payments were not stored before, only yearly totals), filled during fundamentals ingestion with the abnormal flag; `/api/company` returns the last 12 months; chart markers at ex-dividend dates (Yahoo has no payment dates), outlined for one-offs, legend entries and a Dividend column in the data table. 2 new tests (221 total). §20 |
| 2026-10-05 | User asked for a way to track prediction accuracy, finalised the design over two rounds (benchmark against the screened universe; 1, 3, 6 and 12 months; from today only; 14 months of detail plus monthly summaries; a verdict panel, missed opportunities and still-actionable lists) and added a menu bar, multiple watchlists and portfolios, Markets links and a dashboard home page. Built in four stages. **Stage 1** (this change): menu bar with search and a data-date chip, dashboard, holdings page, the screener moved to `#/screener`, and nightly signal recording (`signal_snapshots`, `src/tracking/`, nightly step 3) so the record starts as early as possible. Shared the GUI's row enrichment as `src/screening/enriched.py` so the GUI and the recorder judge identical rows. 239 tests pass (18 new). Checked in headless Chromium at 1280px, 1000px and 390px, light and dark, against a seeded database with two nights of signals |
| 2026-10-05 | **Stage 2:** multiple portfolios, each with a tax type setting its CGT discount (individual and trust 50%, SMSF 33⅓%, company none), and trade entry in the browser (§19.1). `portfolios` table; `holdings.portfolio_id` with existing parcels migrated into "My portfolio"; archive (all sold) and delete (no sales) rules; undo sale; `portfolio.py --portfolio` and `portfolios` and `undo-sale` commands; per-portfolio CGT reports. Browser changes need the password and must come from Sift's own pages (custom header, Sec-Fetch-Site and Origin checks). 280 tests pass (41 new). Checked in headless Chromium: create, buy, sell (oldest first and smallest tax first), a refused future date, undo, delete, archive and delete rules, at 1280px and 390px |
| 2026-10-05 | User reported the Track record page showing "Could not load: Request failed (500)" after pulling stage 2. Reproduced on a database with the previous schema: every page failed with `relation "portfolios" does not exist`, because the GUI was restarted before the schema step had run (known-issue #22 again, this time in the GUI). Fixes: `python gui.py` now applies the schema on start (`prepare_database()`, the same idempotent step as nightly step 0, reported on the console and never blocking the server), and an unexpected server error now returns its cause to the page (`error_message()`), with the exact command when the database is behind the code. 283 tests pass (3 new) |
| 2026-10-05 | **Stage 3:** multiple watchlists (§22): `watchlists` and `watchlist_items` (note, margin-of-safety and price triggers), a Watchlists overview and page per list, "Add to watchlist" on company pages, a watchlist filter and ★ in the screener, triggered entries under Needs attention, and watchlist companies first in What changed. Caught by the new tests before release: the company page failed for a company already on a list (it read a field only the screener's rows carry). 301 tests pass (18 new). Checked in headless Chromium at 1280px and 390px |
| 2026-10-05 | **Stage 4:** the track record is scored (§21): `signal_outcomes` and `track_record_monthly`, nightly step 4 (`score_signals`), and the Track record page's verdict panel with confidence and the order check, By month, What did I miss and Calls that saved money, What should I look at now, and a rules-version filter; the dashboard shows the headline BUY result. Found and fixed before release: `db/schema.sql` created `signal_outcomes` before the `signal_snapshots` it refers to, which only fails on a brand-new database, so every existing test database missed it; a new test now builds the schema from nothing. Also fixed the period buttons not showing which was selected. 312 tests pass (11 new). Checked against 13 months of made-up history in headless Chromium |
| 2026-10-05 | User asked whether to add a searchable knowledge base from the glossary and build documents. Chose user help only, inside Sift, as the single source for the hover text and the Word glossary, without AI question-answering. Added `web/knowledge.json` (78 entries: every hover explanation, acronym and glossary term, merged one per concept, plus guides to each part of Sift), a Help page with search, topic filters and deep links, term search in the menu bar, and `scripts/build_rules_doc.js` (the Word document's builder, until then only in a temporary build workspace). The rebuilt Word document matches the previous one except one glossary row now sorted correctly. Browser checks found and fixed two bugs: every Help entry opening on a deep link, and SMSF opening the Portfolios guide instead of its own entry. 402 tests pass (85 new) |
| 2026-10-06 | User asked to view every formula, calculation and metric in an admin console, adjust them and run hypothetical models. Chose phases 1 and 2 (view with workings; a what-if lab on today's data, nothing live changes), all four groups of settings and the same password, and asked for links to the Help entry for each concept. Added `src/settings.py` (29 settings, one source for every module, live values unchanged and pinned by tests), `src/admin/` (show workings with a sensitivity grid; scenario runs on cached inputs compared with live), the `scenarios` table, the Model and rules and What-if scenarios pages, a Show workings card on every company page, five Help entries in a new Admin topic, a pink ? link from every setting and working step to its Help entry, and §11.6 plus the two new glossary terms in the Word rules document. A no-change scenario reproduces live exactly. 428 tests pass (26 new). §24 |
| 2026-10-06 | User asked how to collect the ASX's ETFs into the database like the shares. Chose all four uses (price holdings, compare and screen, look-through value, watchlists), every ASX ETF, the ASX monthly report as the source with the download automated as far as possible, AMIT cost base adjustments included, and 1 to 10-year performance; agreed four stages and built stage 1. Added `companies.security_type`, `etf_monthly` and `etf_performance`, `src/etf/` (the ASX report finder, downloader and heading-based reader with `--inspect`; nightly prices and distributions with a full-history backfill; total returns 1 month to 10 years with a check against the report), nightly step 1b, ETFs kept out of share valuation and the screener view, and Help entries. Found and fixed while building it: Yahoo prices were stored dividend-adjusted a month at a time (known-issue #31), and a split left price history half-adjusted. 508 tests pass (80 new). §25 |
| 2026-10-06 | User asked for ETFs to be presented under their own heading, separate from shares, and chose the menu bar, portfolios, watchlists, and the dashboard and search, then to start stage 2 now. Added an ETFs menu item, the ETF screener and a page per ETF (performance against the category average and a chosen reference fund, growth of $10,000, unit price with distribution markers, distributions by financial year, fund facts, fund size over time), a full-width ETFs card on the dashboard, Shares and ETFs sections with subtotals in portfolios and watchlists, ETF results in search, and a yield trigger for ETFs (`watchlist_items.yield_above`) with margin of safety triggers refused for ETFs. A third chart colour (`--s3`) was validated for both themes. 14 new Help entries in a new ETFs topic. 533 tests pass (25 new). §26 |

---

## 16. Automation (`scripts/daily_refresh.ps1`)

**Step 1b, ETFs (added 2026-10-06):** `python -m src.etf.run_etfs` runs after share ingestion: last month's ASX Investment Products report if it isn't loaded yet, then prices and distributions for every active ETF (full history the first time), then ETF performance (§25). A report that isn't out yet or can't be downloaded is logged and the step carries on.

**Step 4, Track Record (added 2026-10-05):** `python -m src.tracking.score_signals` scores every signal whose 1, 3, 6 or 12 months the prices have reached, rebuilds the monthly summary, then deletes detail older than 14 whole months (§21). Re-running it scores nothing twice. Suggested Actions is now step 5.

**Step 3, Signal Record (added 2026-10-05):** `python -m src.tracking.record_signals` runs straight after valuation and writes tonight's `signal_snapshots` (§21). Re-running it the same night changes nothing. A company whose valuation failed tonight is skipped and listed as a WARNING rather than recorded with a stale estimate. Suggested Actions is now step 4.

**Step 0 (added 2026-10-05):** `python -m src.apply_schema` runs before ingestion, so a `git pull` that changes the schema can't leave the night's run failing on every company (known-issue #22). The schema runs in one transaction: if it fails, nothing changes and the later steps still run against the existing schema.

**Purpose:** removes the need to run each step by hand (originally three commands: ingestion, valuation, screener; now six, see the steps above) to keep the database current. Designed to be triggered daily and unattended by Windows Task Scheduler, after ASX market close.

**Design decisions:**
- **No stop-on-error chaining** (`;` between steps, not `&&` or `-and`): a transient Yahoo Finance network blip during ingestion should not prevent valuation/screener from still running against whatever data is already in the database from the previous day. Each step's own per-ticker/per-company error isolation (§7.3-§7.5, §8.4, known-issues #10/#13) already handles failures within a step; this script's job is only to make sure a whole-step failure doesn't cascade into skipping the rest of the pipeline.
- **Single timestamped log file per run** (`logs\refresh_<yyyy-MM-dd_HHmmss>.log`), capturing stdout and stderr from every step (`2>&1` redirect piped through `Add-Content`), so an unattended run can be checked after the fact without having to watch it live.
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

13. **Rule tuning after the first live run.** Asked to review the first live action report, then chose (A) judging only recent dividends so a cut since restored stops counting, and (yes) 0% franking for companies whose Yahoo-reported country isn't Australia. → Revised `dividend_trend` to standing cuts only; added `companies.country` and 0% franking for foreign listings; added `src.apply_schema` as the nightly job's first step.

14. **Accumulate for held shares.** *"With the shares I hold that should also include BUY more or an Accumulate. That would be better than Sell, Hold, Review."* → Added `ACCUMULATE` for held shares passing all four tests with no red flags; `HOLD` now names the failed tests.

15. **Interactive web GUI.** *"How do I build an interactive HTML GUI to view this? I also want to be able to interact with it like Simply Wall Street."* Then chose a local web app, the screener table and company page, and phone access on home Wi-Fi. → Added `gui.py`, `web/` and the score wheel (§20).

16. **Dividend data quality.** *"Check the payout ratio 519% suggests a one-off dividend; dividend cut and not yet restored. Is this an incorrect formula?"* Then *"Yes implement both"* (exclude abnormal distributions; match dividends to financial years). → §7.6, known-issues #24 and #25.

17. **Currency conversion.** *"YES FIX THAT"* (known-issue #25: statements in USD/NZD compared with AUD prices). → §7.7.

18. **Sift restyle.** *"Gemini did some work for the UI. Can you check the code and if it looks good apply it"*, then chose the light/dark switch, company summary strip, valuation status pill and visual restyle, and the name *"Sift"*. → §20.

19. **Track record, menu bar and dashboard.** *"I want a way to track the accuracy of our predictions over time... Let's finalise the design before building."* Then a 14-month retention limit with monthly summaries, a verdict panel, missed opportunities and still-actionable lists, *"we also need to add a top line banner for menu selection"* with multiple watchlists and portfolios, Markets links and a dashboard home page, and *"yes start on stage 1"*. → §20, §21.

20. **Multiple portfolios.** *"start on stage 2"* (agreed earlier: a tax type per portfolio, all editing in the browser, archive a portfolio with sales, the existing parcel into "My portfolio"). → §19.1.

21. **Multiple watchlists.** *"start on stage 3"* (agreed earlier: several named lists, a note and triggers per company, "Add to watchlist" on company pages, watchlist companies first in What changed). → §22.

22. **Scoring the track record.** *"Stage 4"* (agreed earlier: 1, 3, 6 and 12 months against the screened-universe average, 14 months of detail plus permanent monthly summaries, a verdict panel with confidence, missed opportunities, still actionable, a rules-version filter). → §21.

23. **Knowledge base.** *"Should we consider including a searchable knowledge base in this solution, using the glossary and build files?"* Then chose user help only, inside Sift, one source for the hover text and Word glossary, no AI Q&A. → §23.

24. **Admin console.** *"With the app I want to be able to view all of the formulas calculations and metrics in an admin console. I'd like the ability to adjust them and run some hypothetical models."* Then chose phases 1 and 2, all four groups of settings and the same password, and *"Continue with the build as designed. Add links to the knowledge base article that references the concept."* → §24.

25. **ETFs.** *"How do we collect the ETF's available on the ASX into a database like the shares?"* Then chose all four uses, every ASX ETF, the ASX monthly report with the download automated, AMIT included now, and *"There will be a lot of performance data to add in. 1 yr, 5 yr, 10yr perf. etc."*; agreed four stages and *"yes"* to starting stage 1. → §25.

26. **ETFs apart from shares.** *"When presenting ETFs I want that under the etf heading separated to shares"*. Then chose the menu bar, portfolios, watchlists, and the dashboard and search, and to start stage 2 now. → §26.

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

**Web GUI, multiple portfolios, watchlists and the track record (§19.1, §20, §21, §22):** ✅ Done 2026-10-05.

**Searchable knowledge base (§23):** ✅ Done 2026-10-05.

**Admin console, phases 1 and 2 (§24):** ✅ Done 2026-10-06.

**ETFs stage 1, collection (§25):** ✅ Done 2026-10-06.

**Check the first ASX report load (on the PC, once):**
> "Here's the output of `python -m src.etf.run_etfs --inspect` on this month's ASX report: [paste]. Fix any heading that wasn't matched, then confirm the ETF count and a few funds' fees and returns against the ASX website."

**ETFs stage 2, presented apart from shares (§26):** ✅ Done 2026-10-06.

**ETFs stage 3 (AMIT):**
> "Start ETF stage 3: enter each year's AMIT cost base increase or decrease per ETF from the annual tax statement, spread across the parcels held at 30 June, with a decrease beyond the cost base becoming a capital gain."

**ETFs stage 4 (look-through value):**
> "Start ETF stage 4: for ETFs tracking an S&P/ASX index Sift covers, a market-cap-weighted look-through margin of safety, earnings quality and score from Sift's own share valuations."

**Publish a scenario as the live rules (phase 3, only once the track record supports it):**
> "Add a way to publish a saved scenario as the live settings, with a confirmation, a record of who changed what and when, a new RULES_VERSION so the track record judges the new rules separately, and a one-click way back."

**Backtest a scenario (phase 4, once there are several months of signal history):**
> "Score a saved scenario against the track record's history: what would it have said each night, and how would those calls have done against the average, next to the live rules?"

**Add a Help entry or correct a definition:**
> "In web/knowledge.json, add an entry for [term] (or correct [entry]) in the right topic, with related terms and a link into Sift, then rebuild the Word document and run the tests."

**Ask Sift questions in plain English (only if Help search proves too narrow):**
> "Add AI question-answering to the Help page using web/knowledge.json as its only source. Explain the cost, what leaves my PC, and where the API key goes before building."

**Read the first track record results (from about a month after recording starts):**
> "Open the Track record numbers for me: for each action at 1 month, how did it do against the average, how confident can we be yet, and is anything surprising? Don't change any rules yet."

**Review the rules once the track record is solid (6 to 12 months in):**
> "The track record now has [N] months of results. Where are the actions out of order or weaker than expected? Propose rule changes with the evidence for each, and bump RULES_VERSION so the new rules are judged separately."

**Add a size-weighted benchmark alongside the plain average (known-issue #29):**
> "Add a market-capitalisation-weighted benchmark to the track record next to the equal-weighted one, and show both on the Track record page."

**Tune the action rules once I've seen them on real data:**
> "Having watched the suggested actions for a few weeks, here's where they felt wrong: [examples]. Adjust the rules in src/screening/actions.py, keep a test for each change, and update §9.1."

---

## 19. Portfolio Holdings & CGT Record Keeping (`portfolio.py`, `src/portfolio/`)

**Purpose.** Lets the screener know what you own (so held companies get SELL / REVIEW / ACCUMULATE / HOLD rather than buy-side actions, §9.1) and keeps the records Australian CGT needs. User choice: a database table rather than a file, with tax-relevant fields and anything else useful for record keeping.

**Parcel model.** One `holdings` row per parcel: every purchase, DRP allocation, bonus issue or transfer-in is its own parcel with its own acquisition date, because CGT (including the 12-month discount) is assessed per parcel. Fields: `asx_code`, `units`, `acquisition_method` (`PURCHASE`/`DRP`/`BONUS`/`TRANSFER`/`OTHER`), `buy_date`, `buy_price` (per share), `buy_brokerage`, `sell_date`, `sell_price`, `sell_brokerage`, `broker`, `notes`, `split_from_id`. Keyed on `asx_code` with no foreign key to `companies`, so anything can be recorded whether or not it's on the watchlist. `CHECK` constraints enforce positive units, non-negative prices, sell date on or after buy date, and sell date/price present together.

**Partial sales split the parcel.** Selling 30 of 100 units creates a new sold row for the 30 (`split_from_id` pointing to the original) and leaves the original row holding 70. Buy brokerage is apportioned by units (rounded to the cent, remainder kept on the open portion) so the combined cost base is unchanged to the cent; sale brokerage is apportioned across every parcel a sale consumes, with the last parcel taking the rounding remainder so nothing is lost.

**Sale order.** `fifo` (default, oldest first - also usually the parcels already past 12 months), `min-tax` (smallest taxable gain first per unit, counting the portfolio's discount: for an individual, a $60 discounted gain is $30 taxable, so it's sold after a $10 undiscounted one; losses sort first), or `--parcel <id>` for specific identification. Identifying the parcel sold is permitted by the ATO; keep the trade confirmation that shows which you chose.

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

**Back it up.** Unlike market data, holdings can't be re-downloaded. The teardown command in §12 deliberately leaves the table alone, and a periodic `pg_dump -t holdings -t portfolios asx_value > holdings_backup.sql` keeps a copy outside the database.

### 19.1 Portfolios and Trade Entry in the Browser (stage 2, added 2026-10-05)

**Purpose.** Hold several portfolios (for example your own shares, a family trust and a self-managed super fund), each taxed as its owner is, and record trades in Sift instead of only at the command line.

**Model.** `portfolios` (name, unique ignoring case; `tax_type`; `archived_at`). Every parcel has a `portfolio_id`. The schema migration creates "My portfolio" (individual) and moves existing parcels into it, only when there are parcels without a portfolio, then makes the column `NOT NULL`; re-running it changes nothing. On a fresh database the first `add_parcel()` creates "My portfolio".

**Tax type sets the CGT discount (`cgt.DISCOUNT_RATES`).** Individual 50%, trust 50% (passed through to beneficiaries), complying super fund including SMSF 33⅓%, company 0%. It drives the FY summary (`summarise(..., discount_rate)`), `min-tax` sale ordering, and whether a parcel ever waits for a discount date: company parcels never do, so they're left out of `next_discount_date`, the screener's "consider timing any sale" reason (§9.1) and the dashboard's CGT reminders. Changing a portfolio's tax type re-rates the sales already recorded in it (the settings form warns when there are any).

**Rules.**
- **Choosing a portfolio:** a function given no portfolio uses the only active one; with several it refuses and names them (`portfolio.py --portfolio NAME`).
- **Sales stay inside a portfolio:** `sell()` only draws on that portfolio's parcels, and a split-off sold portion keeps the portfolio.
- **Archive** needs every parcel sold; an archived portfolio refuses new trades, leaves the menu and dashboard, and keeps its sales in the CGT report. Unarchive reverses it.
- **Delete** removes the portfolio and its open parcels, and is refused once it has any sale, because the ATO expects records kept for five years after each sale: archive instead.
- **Undo sale** (`undo_sale()`): a sold portion split from a still-open parcel goes back into it (units and buy brokerage restored, so the cost base is exact again); otherwise the parcel reopens. Delete is only for open parcels entered by mistake.
- **Held means held in any portfolio:** suggested actions (§9.1) treat a company as held when any active portfolio holds it.

**Browser (`gui.py`).** `GET /api/portfolios` (each with totals; `?brief=1` names only, for the menu), `POST /api/portfolios`, `GET|PATCH|DELETE /api/portfolios/{id}` (detail; rename, tax type, archive or unarchive; delete), `POST /api/portfolios/{id}/buys`, `POST /api/portfolios/{id}/sales`, `DELETE /api/parcels/{id}` (open parcels only), `POST /api/parcels/{id}/undo-sale`. Each change runs in one transaction; a rule broken is a 400 with a plain-English message (`trade_input.py` checks codes, numbers, decimal places within the column sizes, and that the date isn't in the future), and nothing is half-saved. Pages: `#/portfolios` (a card per portfolio, archived ones folded away, and a create form; `?new=1` jumps to it) and `#/portfolio/{id}` (summary strip, holdings, Record a trade, Settings, Open parcels, Sales, Capital gains by financial year). Deleting a parcel or portfolio, undoing a sale and archiving all ask for confirmation first.

**Write protection.** The same password as viewing. Because a browser sends saved Basic-auth credentials with any site's request, a password alone wouldn't stop another website's page posting to Sift, so every POST, PATCH, PUT or DELETE must also pass `_same_site_write()`: the `X-Sift: 1` header that Sift's own script adds (another site can't add a custom header without a CORS permission Sift never grants), `Sec-Fetch-Site` same-origin when the browser sends it, and an `Origin` whose host matches. Anything else gets a 403 before reaching a route.

**CLI.** `portfolio.py portfolios [list|create|archive|unarchive] [NAME] [--tax-type ...]`, `--portfolio/-p` on `add`, `sell`, `list` and `cgt`, and `undo-sale PARCEL`. `list` and `cgt` show every portfolio separately, each `cgt` report at its own discount rate.

---

## 20. Web GUI (`gui.py`, `web/`, `src/screening/scores.py`, added 2026-10-05)

**Purpose.** A browser view of the screener, Simply Wall St style: a filterable table of every company and a page per company with a score wheel, valuation, quality markers and charts. Usable from a phone on home Wi-Fi. Writes only portfolios and trades (§19.1).

**Architecture.**
- `gui.py`: FastAPI app run by uvicorn. `GET /api/screener` (every row, trimmed to the fields the table needs, plus five axis scores) and `GET /api/company/{code}` (the full row, the 30 checks, the four tests with thresholds, red flags, position, 365 days of prices, margin-of-safety history and up to 5 FY reports). `/` and `/static/*` serve `web/`.
- Added with the dashboard (stage 1): `GET /api/dashboard`, `GET /api/status` (the data chip) and `GET /api/companies` (the search list); see "Menu bar and dashboard" below.
- Both endpoints call `screen_asx.load_annotated_rows()`, the same loader the CLI uses, so the browser and `screen_asx.py` can never disagree on a test, flag or action. Two extra `DISTINCT ON` queries add `roic`, `graham_number` and the latest FY report for the score wheel without a per-company query. Since stage 1 this enrichment lives in `src/screening/enriched.py` (`load_universe()`), shared with the signal recorder (§21).
- `web/`: plain HTML, CSS and JavaScript, no framework, no build step, no CDN. Charts are inline SVG drawn at their real on-screen width (redrawn on resize) so text stays legible on a phone. All text is inserted with `textContent`. Hash routing: `#/` dashboard, `#/screener` (optionally `?action=BUY,INVESTIGATE`, `?held=1` or `?watchlist=NAME` to open it pre-filtered), `#/company/BHP`, `#/portfolios` and `#/portfolio/{id}`, `#/watchlists` and `#/watchlist/{id}`, `#/track-record`, `#/help` (with `?q=` or `/{entry}`, §23); anything else goes to the dashboard.
- Charts follow the dataviz method: validated categorical palette (blue/orange, checked light and dark), 2px lines, hairline grid, one axis per chart, legend only for two or more series, crosshair or per-bar tooltips, a data table under every chart, and light and dark themes.

**Field explanations.** The text comes from `web/knowledge.json` (§23), loaded before the first page draws. Every screener column heading, every label in the company page's markers and key-ratios panels, and the three bar labels in "Price against estimated value" (share price, estimated value, Graham Number) carries a plain-English explanation (what it measures, the formula, and the pass threshold, read from the live thresholds so it can't drift from the rules). `withHelp()` in `app.js` shows it on mouse hover and keyboard focus; on touch screens a small "i" button shows it on tap without triggering the column sort. With a mouse the "i" buttons are hidden and headings get a dotted underline instead, which keeps the table within a 1280px screen. The estimated value explanation follows the company's model (DCF or DDM, with its growth, terminal and discount rates); labels inside SVG charts use `svgLabelHelp()`, with an SVG "i" for touch screens.

**Score wheel (`scores.py`).** Five axes, six yes/no checks each; the score per axis is the count passed (0-6). A check is True, False or None (no data), and None never counts as a pass. Thresholds reuse the screener's own where one exists.

| Axis | Checks |
|---|---|
| Value | margin of safety > 0; > 20%; > 40%; P/E between 0 and 15; P/B between 0 and 1.5; price below Graham Number |
| Performance | ROE > 12%; ROE > 20%; ROIC > 10%; fundamentals not DECLINING; earnings quality STRONG or ADEQUATE; earnings quality STRONG |
| Health | debt/equity < 0.8; < 0.4; cash ≥ total debt; positive equity; positive free cash flow; positive net profit |
| Dividend | pays a dividend; grossed-up yield > 4.5%; > 6%; payout ratio ≤ 100%; dividend trend STEADY or GROWING; GROWING |
| Momentum | price signal UPTREND; not NEW LOWS; in upper half of 52-week range; margin-of-safety trend > 0; momentum_ok; fundamentals IMPROVING |

The wheel describes; it does not decide. The suggested action still comes only from §9.1's rules.

**Start-up.** `main()` applies `db/schema.sql` before serving (`prepare_database()`), so a `git pull` followed by a GUI restart can't leave the pages failing until the nightly run. An unexpected error on any route is logged with its traceback and returned as a readable `detail` (`error_message()`), which the page shows after "Could not load".

**Security.** Default host `127.0.0.1` (this PC only). `--lan` binds `0.0.0.0` and refuses to start unless `GUI_PASSWORD` is set. When set, middleware requires HTTP Basic auth (any username, constant-time password compare) on every route including static files; a malformed header is a 401, not an error. The only writes are portfolios and trades, and they must also come from Sift's own pages (§19.1). Known-issue #23 covers plain HTTP on the LAN.

**Validation (2026-10-05).** Seeded a disposable database with eight synthetic companies built to hit specific paths (a clean pass held, a held falling knife, a bank on DDM, a foreign listing, a REIT, an overvalued tech stock, a loss-maker), ran the server and drove it in headless Chromium at 1280px and 390px, light and dark, plus search, sort, row navigation and chart hover. Fixed four defects found on screen: the "Show more" button visible when it should be hidden (CSS overrode `[hidden]`), chart text scaling with card width, a `null` printed by the native `replaceChildren`, and table overflow on a phone. `tests/unit/test_scores.py` and `tests/integration/test_gui.py` cover the checks, both payloads, the 404, and the password guard on API, page and static files.

**Sift restyle (2026-10-05).** The user supplied a Gemini mock-up ("Intrinsik": React, Tailwind and Babel from CDNs, hard-coded sample stocks). Not applied as-is: it showed invented valuations, misstated the method (per-stock "WACC", "10-year" model, "implied upside" equal to margin of safety, an "undervalued" cut at 10%, a 5-spoke snowflake scored out of 5), depended on unpinned CDN scripts and compiled JSX in the browser, and had defects (an invalid SVG path, a non-existent `top-18` class, no saved theme). Its design ideas were rebuilt in the existing no-dependency front end instead, at the user's choice:
- **Name:** Sift (header, page title). Documents keep "ASX value screener" as the description.
- **Restyle:** slate/teal tokens, card layout, uppercase table and card headings, tinted Y/N marks. UI accent (`--accent`) is separate from chart series colour: the chart pair was re-validated on the new surfaces (light `#0284c7`/`#eb6834` on `#ffffff`; dark keeps `#3987e5`/`#d95926` on `#161f30`, because the mock-up's `#38bdf8` failed the lightness band for data marks). No external fonts: Inter is used only if installed.
- **Theme switch:** gear menu with Light / Dark / System; `html[data-theme]` drives the dark tokens alongside `prefers-color-scheme`; saved in `localStorage` (`sift-theme`, wrapped in try/catch) and applied by an inline script before first paint.
- **Valuation status pill:** `valuationStatus()` - Undervalued above the live margin-of-safety threshold (20%), Fair value 0-20%, Overvalued below 0, No estimate when blank. Label plus tint, never colour alone.
- **Summary strip:** share price, estimated value (with model), margin of safety, implied upside = (value - price) / price; then a model note built from `/api/company`'s new `model` field (the engines' default assumptions, which the nightly run uses).
- **Collapsible score breakdown:** each spoke is a `<details>` section, closed by default, whose summary line keeps the spoke name and score (e.g. "Performance 5 / 6"); a pink twisty (`--twisty`, `#db2777` light / `#f472b6` dark) rotates when open, and an "Expand all / Collapse all" link toggles every spoke. Cuts the panel from about 1,160px to about 360px tall.
- **Dividend markers on the price chart:** a pink "D" on the price line at each ex-dividend date in the last 12 months (placed on the first trading day on or after it), outlined when the payment was an abnormal one-off excluded from dividend figures. Hover or focus shows the date and amount; the legend explains both styles; the chart's data table adds a "Dividend (ex-date)" column and includes every ex-dividend day. Yahoo provides ex-dividend dates, not payment dates, so the marker shows the ex-date. Backed by the new `dividend_payments` table (company, ex-date, amount, abnormal flag), filled by `fundamentals_ingestion.upsert_dividend_payments()` on every fundamentals run (re-runs update, never duplicate), and returned by `/api/company` as `dividends`.
- **Responsive table:** page width 1440px; Sector hides below 1360px, the valuation pill and Y/N marks below 1100px, ratios below 900px; checked to fit without horizontal scroll from 1920px down to 360px.

**Run it.** See README, Web GUI: `python gui.py`, or `python gui.py --lan` with `GUI_PASSWORD` and a one-off firewall rule for phone access.

**Menu bar and dashboard (stage 1, 2026-10-05).**
- **Menu bar:** Dashboard | Screener | Watchlists ▾ | Portfolios ▾ | Track record | Markets ↗ ▾, then a company search, the data chip and the settings gear. The current page has a pink (`--twisty`) underline; a company page highlights nothing. Dropdowns open on click (so they work on touch), close on Escape, an outside click or navigation, and only one is open at a time. Below 1060px the menu folds behind a ☰ button into a vertical panel (current page marked with a pink left bar). Markets links open in a new tab with `rel="noopener noreferrer"`: ASX, the ASX exchange traded products directory, NYSE and Nasdaq. Watchlists and Portfolios list each watchlist and portfolio, with All and + New links (§19.1, §22).
- **Search:** a `<datalist>` of every screened code and name from `/api/companies`. Picking an entry, or pressing Enter, opens the company: exact code first, then code prefix, then name contains. No match shows a short tooltip.
- **Data chip (`/api/status`):** newest `valuation_metrics.as_of_date`, newest price date, and the latest `logs/refresh_*.log` parsed by `last_refresh()`. Stale when the newest valuation is older than the previous weekday (so Friday's data is current all weekend; a public holiday shows amber harmlessly). The log reader handles UTF-8 and UTF-16 (PowerShell) files and classifies a run as `ok`, `errors` (one or more ERROR lines: individual companies that failed, normal on most nights), `crashed` (a traceback with no ERROR line before it: a whole step died), `running` (unfinished and under 3 hours old) or `incomplete`. Amber, with a "!", only for stale data, `crashed` or `incomplete`, so routine Yahoo gaps don't train you to ignore it.
- **Dashboard (`/api/dashboard`):** one `load_universe()` call feeds: a portfolio strip (value at the latest close, today's change from the two latest closes, unrealised gain, cost base); Needs attention (held SELL/REVIEW with reasons, parcels reaching the CGT discount within 90 days, holdings not on the watchlist file); What changed (§21); Top opportunities (up to six, BUY then INVESTIGATE, by score total then margin of safety; shares you hold are excluded because their actions are the held set); action counts linking to the pre-filtered screener; recording status; and a footer repeating the data status in full.
- **Portfolios:** the Portfolios menu lists active portfolios; with more than one, the dashboard adds a card listing each with its value and gain (§19.1).
- **Back link:** a company page's back link returns to the page you came from (dashboard, screener with its filters, holdings or track record), defaulting to the screener.

---

## 21. Track Record (`src/tracking/`, recording added in stage 1, scoring in stage 4, 2026-10-05)

**Purpose.** Answer "is Sift right?" with evidence: record what Sift said about every company each night, then compare it with what the share price did over the following 1, 3, 6 and 12 months against the average of every screened company. Recording starts first, because results can only ever be measured forward from the first night recorded (known-issue #26).

**What is recorded (`signal_snapshots`, §4).** One row per screened company per valuation date: closing price on that date, suggested action and reason, whether it was held, valuation status, margin of safety, estimated value and model, score total and per spoke, the four value tests, red flags and `rules_version`. Written by `record_signals()` straight after valuation (nightly step 3, §16).

**Rules.**
- **Never edited.** `INSERT ... ON CONFLICT DO NOTHING` on `(company_id, snapshot_date)`. A second run the same night, or a later rule change, can't rewrite what was said at the time.
- **Dated by the valuation, not the run.** `snapshot_date` is the company's latest `valuation_metrics.as_of_date`, which is the price date the valuation used.
- **Stale valuations are skipped.** If a company's newest price is newer than its newest valuation (its valuation failed tonight), it is not recorded and is logged as a WARNING, rather than pairing yesterday's estimate with today's price.
- **`RULES_VERSION`** (`src/tracking/signals.py`, currently `2026-10-05`) is the date the screening rules last changed. Bump it whenever thresholds, actions, scores or valuation models change, so each rule set is judged on its own results.
- **Same rows as the GUI.** The recorder uses `load_universe()` (`src/screening/enriched.py`), the loader the dashboard and screener use, so the record holds exactly what was on screen.

**What changed (dashboard).** `signal_changes()` compares the latest two snapshot dates. Each action has a rank (BUY and ACCUMULATE 1, INVESTIGATE 2, WATCH and HOLD 3, REVIEW and IGNORE 4, AVOID and SELL 5). A move between equal ranks is not a change (BUY to ACCUMULATE after buying), and neither is any move where the held flag changed, because buying or selling, not the market, caused it. Better moves are listed first.

**Recording status.** `tracking_status()` gives first and latest dates, nights recorded, signals recorded, companies on the latest night and the date each horizon's first results are due (first date plus 1, 3, 6 and 12 months).

**Scoring (stage 4, `outcomes.py`, nightly step 4).** In one transaction, after the night's signals are recorded:
1. **Which signals are scored.** Each company's first snapshot of each calendar month (the *cohort*: one per company per month, so a company that stays BUY for a month counts once, not 21 times) and every snapshot where its action changed from the previous one with the held flag unchanged (a *change*; buying or selling isn't a signal). Each outcome row records which it is (`is_cohort`, `is_change`; both when a change falls on the month's first night).
2. **When.** A horizon is scored once the market data reaches it: signal date plus 1, 3, 6 or 12 months (end-of-month dates clamp, as `add_months`) on or before the newest stored price date.
3. **How.** End price: the company's last close on or before the horizon. Total return = (end price + every dividend with an ex-date after the signal and up to the horizon, one-offs included - signal price) / signal price. **Benchmark:** the plain average total return, the same way, of every company screened on the signal's night (`universe_size`). **Excess return** = total return - benchmark, in percentage points. **Gap closed** = share of the distance from price to estimated value covered, for signals priced below their estimate. A company with no close within 10 days of the horizon is flagged `delisted` and scored at its last price, so failures stay in the record instead of disappearing.
4. **Monthly summary.** `track_record_monthly` is rebuilt for every month that still has scored cohort signals: per month, action, horizon and rules version, the count, how many beat the benchmark, and the average return, average excess and median excess. Months whose detail is gone keep their rows.
5. **Deletion.** Snapshots before the first day of the month 14 months back are deleted, with their outcomes by cascade. Whole months only: deleting part of a month would make a later day that month's "first signal" and score it twice. Runs after the summary, so nothing is deleted unsummarised. On 5 October 2026 the cutoff is 1 August 2025.

**Track record page (`report.py`, `GET /api/track-record[?version=]`).**
- **Is Sift accurate?** From the permanent monthly summary, per period: one sentence per action ("BUY calls beat the average screened share by 5.8 points over 3 months; 67% of 202 beat it"), its confidence (too early under 30 signals, moderate 30 to 100, solid above 100), a tick when the direction is what the action intends (BUY, ACCUMULATE, INVESTIGATE should beat the average; AVOID and SELL should trail it; WATCH, HOLD, REVIEW and IGNORE are neutral), and the order check: BUY above WATCH above AVOID on average excess return, judged only when all three have 30 signals. Averages across months are weighted by each month's count. A "By month" table lists each month for the chosen period.
- **What did I miss?** From the last 14 months of detail, each signal at its longest scored horizon: BUY or INVESTIGATE on shares not held, with no parcel bought (any portfolio) from the signal date to 30 days after, that beat the average by more than 10 points. **Calls that saved money:** AVOID on shares not held, and SELL on shares held, that trailed it by more than 10 points. First qualifying call per company, best first, up to 20, with price then and now and whether it's still undervalued. Watchlist companies carry a ★.
- **What should I look at now?** *Proven* actions are the buy-side actions (BUY, INVESTIGATE, ACCUMULATE) beating the average at 3 months (1 month until 3-month results exist) with at least moderate confidence; until one is, BUY stands in "on the rules' own terms" and the page says so. Today's signals of a proven action with margin of safety above 20% are split into **New this week** (that action's current run started in the last 7 days) and **Still open**, with price when the run started and now. **Moved on** lists companies with a proven signal in the last 90 days that no longer qualify, and why, checked in this order: you bought it; the price rose out of the buy zone (margin of safety at or below 20% and the price above the signal's); the estimated value fell (margin of safety at or below 20% without a price rise); or its action changed.
- **Rules version filter** limits the verdict, missed and saved lists to one `rules_version`. Empty panels say when their first results are due, or, with a version selected, that its signals aren't old enough yet.
- **Dashboard:** the Track record card shows the BUY line at 3 months (1 month until then) once results exist.

**Validated against made-up history.** `tests/integration/test_track_record.py` builds 13 months of daily prices and signals for a rising BUY, a falling AVOID, a flat WATCH that pays a dividend and turns BUY, and a company that stops trading, then checks benchmark arithmetic, dividends, scorecard selection, delisting, the summary, deletion at the month boundary, the verdict, the rules-version filter and the 30-day purchase rule. A disposable GUI database with 60 synthetic companies, whose signals were set to partly predict their returns, and two rules versions produced 21,816 outcomes in about 20 seconds; the page showed BUY at +5.8 points (solid), the order check "in order", and the 12-month filter's empty state.

---

## 22. Watchlists (`src/watchlist/lists.py`, stage 3 added 2026-10-05)

**Purpose.** Follow companies without owning them, in as many named lists as you like, with a reason and a price or value level for each, so the dashboard says when one gets there.

**ETFs (added 2026-10-06, §26):** watchlists hold ETFs too, shown under their own heading, with a yield trigger for ETFs (`yield_above`); a margin of safety trigger is for shares only.

**Model.** `watchlists` (name, unique ignoring case and repeated spaces) and `watchlist_items` keyed `(watchlist_id, company_id)`: optional `note` (up to 500 characters), `mos_above` (percent, may be negative) and `price_below` (above zero). Both foreign keys cascade, so deleting a list deletes its entries and nothing else. Entries reference `companies`, so only companies Sift values can be watched; adding any other code is refused with a pointer to the nightly ticker file (`allords.txt`). That file and these lists are different things: the file decides what gets valued, a list decides what you follow.

**Triggers (`triggers()`).** Judged against the screener's own row for the company: margin of safety **strictly above** `mos_above`, latest close **at or below** `price_below`. A company with no current value or price meets neither. An entry is "triggered" while any trigger is met; it's a live state, not a stored event (known-issue #28).

**Where watchlists show.**
- **Watchlists pages:** `#/watchlists` (a card per list with company and trigger counts, and a create form; `?new=1` jumps to it) and `#/watchlist/{id}` (entries, triggered first, with score, price, margin of safety, valuation, action, each trigger ticked or not, and the note; one form adds a company or, via Edit, updates its note and triggers; rename and delete).
- **Company page:** "☆ Add to watchlist" opens a panel ticking every list the company is on; ticking adds, unticking removes (asking first, and saying when a note or triggers will go), and naming a new list creates it with the company on it. A line under the strip names the lists and whether a trigger is met.
- **Screener:** a pink ★ after the code (hover for the list names) and a filter: any watchlist, or one by name (`#/screener?watchlist=NAME` presets it).
- **Dashboard:** triggered entries join Needs attention with the list, the trigger and the note; What changed lists watchlist companies first, then better moves first.
- **Menu:** the Watchlists dropdown lists every watchlist, plus All watchlists and + New watchlist.

**API.** `GET /api/watchlists` (counts; `?brief=1` names only), `POST /api/watchlists` (optionally with `asx_code` to start it with that company), `GET|PATCH|DELETE /api/watchlists/{id}`, `PUT /api/watchlists/{id}/items/{code}` (add or update: the same call), `DELETE /api/watchlists/{id}/items/{code}`. The screener rows carry `watchlists` (list names), the company payload carries every list with membership, note and triggers, and the dashboard carries `triggered`. Writes go through the same password, same-page guard and one-transaction `change()` as portfolios (§19.1); rule breaks return a 400 with a plain-English message.

---

## 23. Knowledge Base and Help (`web/knowledge.json`, added 2026-10-05)

**Purpose.** One searchable place for every term, rule and how-to, and one source for text that used to live in three places (the hover explanations in `app.js`, the Word glossary in the document builder, and the README), so a definition can't say one thing on hover and another in the document.

**Source: `web/knowledge.json`.** `categories` (ten topics) and `entries`, each with: `id` (also its link, `#/help/<id>`), `title`, `category`, `definition` (one line; the Word glossary text for glossary entries), optional `hover` and `labels` (the UI labels that show it, e.g. "Debt/equity"), `body` paragraphs, `aliases` (search words such as SMSF or special dividend), `related` IDs and `links` into Sift. Glossary entries carry `glossary: "acronym"` (with `abbreviation` and `full`) or `glossary: "term"` (with `glossary_title`). `{margin_of_safety}`, `{roe}`, `{debt_to_equity}` and `{yield}` are filled with the live thresholds wherever the text is shown. The first version merged the 37 hover explanations, both valuation-model explanations, 23 acronyms and 27 glossary terms into 78 entries (one per concept, e.g. ROE's acronym, glossary meaning and hover text are one entry), and added guides to the dashboard, the nightly refresh, actions, the score wheel, portfolios and trades, watchlists and the track record, each checked against the code.

**Where it's used.**
- **Hover explanations:** `app.js` loads the file before the first page draws and builds `FIELD_HELP` (label to text) and `ESTIMATED_VALUE_HELP` (DCF/DDM) from it; `withHelp()` and `svgLabelHelp()` are unchanged. If the file can't load, pages still work without explanations.
- **Help page (`#/help`, `#/help?q=`, `#/help/<id>`):** entries grouped by topic, each a collapsible row (pink twisty) with the definition, "In Sift" hover text where it differs, the full explanation, related terms and links. Search needs every word to appear and ranks exact names, then titles starting with the query, then names and aliases, then definitions, then anywhere; up to three results open automatically. Topic chips filter.
- **Menu search:** an exact company code wins; then an exact term (title, abbreviation or full name before aliases) opens its entry; then companies by code prefix or name; then, if any entry matches, the Help results. Terms appear in the search list labelled Help.
- **Word document:** `scripts/build_rules_doc.js` takes Appendix A's acronyms and key terms from the file (sorted by name), and writes the rest of the document itself. Run `npm install` once in `scripts/`, then `node build_rules_doc.js`.

**Checks (`tests/unit/test_knowledge.py`).** IDs unique and URL-safe; every entry has a title, definition and known category; every related ID and link is real; every UI label Sift asks for is explained exactly once; both valuation models are explained; glossary entries have what the Word table needs and none were lost; and, per entry, no em dashes and no unknown placeholders. `test_gui.py` checks the file is served behind the password.

**Not included, by choice:** AS_BUILT stays a separate technical document, and there's no AI question-answering (it would need an API key and send questions out). Both can be added later; the Help search would be the place to hang Q&A.

---

## 24. Admin Console: Model and Rules, Show Workings, What-if Scenarios (`src/settings.py`, `src/admin/`, added 2026-10-06)

**Purpose.** See every formula, threshold and calculation Sift uses, and try different settings against today's data, without changing anything live. Built as phases 1 and 2 of the agreed design: view and explain (phase 1), and a what-if lab (phase 2). Publishing a scenario as the live rules (phase 3) and backtesting a scenario against the track record (phase 4) are not built.

**One registry for every setting (`src/settings.py`).** `ModelSettings` is a frozen dataclass of the 29 adjustable settings, and `LIVE` holds the values the nightly job uses. Every module that used its own constant now reads it from `LIVE`, so the registry is the single source:

| Group | Settings | Read by |
|---|---|---|
| Valuation models | DCF growth, DDM growth, discount rate, terminal growth, stage-one years, cash flow averaging years | `dcf.py`, `ddm.py`, `engine.py` |
| Value tests | Minimum margin of safety, ROE, maximum debt/equity, minimum grossed-up yield | `screen_asx.py` |
| Markers and actions | Earnings quality STRONG and ADEQUATE, new-lows range, dividend cut and growth ratios, ROE and revenue trend steps, momentum step, payout warning, overvalued review level | `markers.py`, `engine.py`, `actions.py`, `screen_asx.py` |
| Score wheel | The nine thresholds the 30 checks use beyond the four tests | `scores.py` |

Each setting carries its group, label, unit, allowed range, formula, where it's used and the knowledge base entry that explains it (`help_id`). `with_overrides()` builds a scenario's settings from entered values (rates entered as percents, e.g. 9 for 9%), and `check()` refuses combinations that make no sense: discount rate not above terminal growth, ADEQUATE above STRONG, and any score wheel "strong" threshold not stricter than its value test. The live values did not change: `tests/unit/test_settings.py` pins all 29, and the score wheel's labels are built from the settings but read exactly as before at the live values.

**Model and rules (`#/admin`).** Opened from the gear panel ("Model and rules", "What-if scenarios"), behind the same password as the rest of Sift. Shows the nightly pipeline, then every setting by group with its live value, range, formula and where it's used. Each setting has a pink **?** link to its Help entry, and the Help entries for the admin console and scenarios link back to these pages.

**Show workings (`src/admin/workings.py`, a card on every company page).** Every figure on the company page step by step: the base years and their average, the assumptions, the year-by-year projection, the discounting and terminal value, the estimated value and margin of safety; then the ratios, each value test with its threshold and result, and each marker with the rule that set it. A sensitivity grid shows the estimated value at discount rates from 7% to 11% (plus the live rate, if outside that) against growth 2 and 4 points either side of the live rate, with the live cell outlined. Every step links to the Help entry for the concept. A selector re-runs the workings under any saved scenario. Tests check the final figures equal `compute_metrics()` exactly for a DCF company and a bank (DDM), so the workings can't drift from the numbers Sift uses.

**What-if scenarios (`src/admin/scenarios.py`, `#/admin/scenarios`).**
- **Editor:** every setting with its live value; changed values turn pink. Run compares the scenario with live on today's data without saving; Save keeps it by name with notes. A scenario stores only the settings that differ from live, in the units entered (`scenarios` table, `overrides` JSONB), so it follows any later change to a live value it didn't override.
- **Results:** how many companies hold each action under live and the scenario, the moves between actions, every company whose action, status or value changed (better moves first, held and watched companies flagged, and a separate "Yours" list), the margin of safety distribution, median margin of safety, average score and number valued.
- **How a run works:** each company's inputs (latest price, up to five annual reports, recent closes) are gathered once and cached in memory until the data changes (keyed by the latest price date, latest valuation date and row counts). Each run then values, tests, scores and assigns actions for the whole universe in memory, twice (live and scenario). Values are rounded to their column sizes as the nightly job stores them, so a scenario with no changes matches live exactly (tested).
- **Nothing live changes:** a run writes nothing. Saving writes only the `scenarios` row. Valuations, the screener, signals and the track record are untouched.
- **Kept at live values:** the margin-of-safety trend (momentum) compares with the live figure stored 30 days ago, so a scenario uses the live trend rather than mixing its own figure with a stored live one. Holdings and watchlists are today's.

**API.** `GET /api/admin/settings`; `GET|POST /api/admin/scenarios`; `GET|PUT|DELETE /api/admin/scenarios/{id}`; `POST /api/admin/run` (a run from the editor's current values; reads only, POST because it carries the settings); `GET /api/company/{code}/workings?scenario={id}`. Writes go through the same password, same-page guard and one-transaction `change()` as portfolios (§19.1). An unknown setting, a value outside its range, a duplicate or blank name, or a `check()` failure returns a 400 with a plain-English message.

**Knowledge base.** Five new entries in a new Admin topic: Admin console, Scenario and Growth rate (both in the Word glossary), Show workings and Sensitivity grid. DCF, DDM and discount rate link to them. 83 entries in all.

**Tests.** `tests/unit/test_settings.py` (pinned live values, every setting's metadata and Help link, every module reading the registry, override units, each guard rail, score labels and markers under changed settings) and `tests/integration/test_admin.py` (no-change scenario equals live exactly, a stricter ROE test moves a company from ACCUMULATE to HOLD, a valuation change matches the engine, the cache follows the data, workings equal the engine for DCF and DDM with every Help link real, and the API end to end including the write guard, 400s, 404s, rename and delete). Checked in headless Chromium at 1280px and 390px against a disposable database of 60 companies with 13 months of made-up history.

**Limits.**
- A scenario is judged on today's data only; it can't yet say how it would have done in the past (phase 4).
- Momentum stays live, as above, so a scenario that changes the margin of safety a lot shows the live trend beside it.
- The cache is per server process; the first run after the nightly job (or a restart) gathers inputs again, which takes a few seconds for 500 companies.

---

## 25. ETFs, Stage 1: Collection (`src/etf/`, added 2026-10-06)

**Purpose.** Bring every ASX exchange traded fund into the database alongside the shares: which ETFs exist and their fund facts each month, their daily prices and distributions with full history, and their performance over 1 month to 10 years. Stage 1 of four agreed with the user: (1) collect, (2) an ETF screener, page per ETF, watchlists and portfolio pricing, (3) AMIT cost base adjustments in the CGT records, (4) look-through value for Australian share ETFs. Stages 2 to 4 are not built yet.

**Model.**
- `companies.security_type` is `SHARE` (default) or `ETF` (checked by the database). ETFs live in `companies` so they share `daily_prices`, `dividend_payments`, watchlist entries and holdings with shares. The ticker is the code plus `.AX`; trading and statement currency AUD.
- `etf_monthly`: one row per ETF per report month, kept for good: fund name, issuer, product type, category and sub-category, benchmark, MER, fund size, net flows, average spread, value traded, distribution yield and frequency, listing date, the report's own 1, 3 and 6-month and 1, 3, 5 and 10-year and since-inception returns, the source file, and `raw` (every column of the row as written, so nothing the ASX publishes is lost if a heading isn't recognised). Percents are whole-number percents (0.07 = 0.07%), money in AUD.
- `etf_performance`: one row per ETF, recalculated nightly: Sift's own total returns for the same periods, distributions in the last 12 months and the trailing yield, the first price date, and the check against the report (below).

**The ETF list: the ASX Investment Products report (`src/etf/asx_report.py`).**
- **Source.** The ASX's monthly report, a spreadsheet published by about the seventh business day of the next month, listing every exchange traded product.
- **Getting it (`ensure_latest`).** Each night, until last month's report is loaded: the newest spreadsheet in `data/asx_reports/` (gitignored) newer than what's loaded, so a file saved by hand is used first; otherwise the report page is read for its spreadsheet links and the newest one downloaded; if the page can't be read, the expected addresses for the last two months are tried (the PDFs live under `/content/dam/asx/issuers/asx-investment-products-reports/<year>/pdf/`; the spreadsheet folder is assumed alongside). Downloads use `curl_cffi` (installed with yfinance) with a browser fingerprint. Once last month's report is loaded, no request is made until the next month. Not available yet is logged as INFO until the 15th, then as a WARNING; neither turns the dashboard's run status red.
- **Reading it.** The layout isn't a published format, so nothing depends on fixed rows or columns. ETP sheets are picked by name (LIC, LIT, mFund, A-REIT and infrastructure sheets skipped). The heading row is the first with an ASX code column; a group heading above (a merged "Performance" over "1 Month", "1 Year") is carried into each column's label, and a sub-heading row below is picked up too. A column's own heading decides its field; a bare period ("1 Year") or an unrecognised heading takes its meaning from the group heading, so "1 Year" under Flows is a flow and under Performance a return. Percents come from the cell's percent format; a column that isn't percent-formatted with every value at or below a fraction limit (0.05 for fees and spreads, 0.3 for yields, 1.5 for returns) is multiplied by 100. Money is scaled by its label ($m, $b, $000), and a fund size column with no unit but a median under $100,000 is read as millions. Rows need a code written in capitals (so Total and Average rows drop out) and a product type that isn't an LIC, LIT or mFund.
- **Loading it (`load_report`).** Every ETP becomes or stays an ETF (a code already known as a share is reclassified, with a WARNING), and gets that month's `etf_monthly` row; re-loading a month replaces it. When the report is the newest loaded, active ETFs it no longer lists are marked inactive (their history stays) and returning ones reactivated.
- **Checking a file.** `python -m src.etf.run_etfs --inspect FILE` prints each sheet's heading row, every column's label and the field it was matched to, notes on scaling, fields not found and three sample rows, without loading anything. `--report FILE [--month YYYY-MM]` loads a file by hand.

**Prices and distributions (`src/etf/prices.py`).** One Yahoo request per active ETF brings closes, splits and distributions. An ETF with no stored prices gets its full history (the one-off backfill behind the 10-year returns); after that, the last month. Distributions go into `dividend_payments` with none held out as abnormal (a fund's year-end distribution of gains is part of its return, unlike a company's one-off). Prices are written a thousand rows per statement.

**Prices are now stored as traded, for shares too.** yfinance's default (`auto_adjust=True`) scales every earlier close down by each later dividend. Fetched a month at a time, that left the stored history with a step at each ex-date (the month before it scaled down, everything older not), and a total return built from such closes plus distributions would count distributions twice. `YahooClient.get_price_history()` now asks for `auto_adjust=False`: closes are split-adjusted only. The track record was unaffected in practice (its start price is the snapshot price and its end price is fetched within days of the horizon, both effectively unadjusted), but charts, the 52-week range and the 200-day average carried the steps. Existing share history keeps them until refetched (known-issue #31).

**Splits (`fetch_bars`, shares and ETFs).** A split changes every earlier split-adjusted close. When a fetch includes a split and the stored close before it no longer matches the fetched one (more than 1% apart), the stored prices are deleted and the full history refetched; for an ETF its distributions are replaced too. The check means it happens once, not every night the split stays in the month's window.

**Performance (`src/etf/performance.py`).**
- **Total return:** one unit bought at the close on the start date (the last close on or before it), each distribution reinvested at the close on its ex-date (or the next close, if the ex-date has none), valued at the end date's close.
- **Periods:** 1, 3 and 6 months and 1 year as they are; 3, 5 and 10 years as a yearly rate over their nominal years; since first price as a yearly rate over its actual length once it's over a year. No figure without a close within 10 days of the period's start and end, so a fund younger than the period shows nothing rather than a shorter period's return.
- **Trailing yield:** distributions with ex-dates in the 12 months to the latest close (the one exactly 12 months ago excluded), divided by that close.
- **As at:** the latest ETF price date.
- **Check against the ASX:** each ETF's 1-year return measured at its latest report's month end, stored beside the report's figure. The nightly log lists ETFs more than 2 points apart: usually a distribution Yahoo missed, a bad price, or the report working its figure out another way (for example from net asset value).

**Kept apart from shares.** `run_valuation` values only `SHARE`s. The `asx_value_screener` view adds `security_type = 'SHARE'`, so ETFs stay out of the screener, menu search, company pages, signals, the track record's average and what-if scenarios, all of which read the view. The menu's latest price date counts shares only. Portfolio pages already value any parcel with a price, so ETF parcels are valued once ETF prices are loaded (stage 2 adds their own figures).

**Nightly step 1b (§16).** `python -m src.etf.run_etfs`: the report if due, then prices and distributions (0.5 seconds between ETFs), then performance. A report failure is logged and the prices still run. The first night fetches about 400 full histories (an estimated 10 to 15 minutes, once); after that a few minutes.

**Tests.**
- `tests/unit/test_asx_report.py`: month from a name or title cell, page links, heading matching, group headings, both layouts, fraction and $m scaling, skipped sheets and rows, the download fallbacks and the local folder. It reads spreadsheets built in two plausible layouts by `tests/unit/_etf_report.py`.
- `tests/unit/test_etf_performance.py`: reinvestment, ex-dates without a close, stale periods, annualising, young funds and the trailing yield.
- `tests/unit/test_yahoo_prices.py`: closes as traded, with splits and distributions.
- `tests/integration/test_etfs.py`: loading, re-loading, retiring and reclassifying; the monthly check that doesn't touch the network once loaded; ETFs out of valuation and the view; the security type check; the backfill, monthly fetch and one-off split refetch for an ETF and a share; and performance with the report check.

**Limits.**
- The real spreadsheet couldn't be opened from the build environment (the ASX site is blocked there, as Yahoo is, §10.7), so the reader was built for plausible layouts and tested on those. The first run on the user's PC should start with `--inspect` on a downloaded report.
- Yahoo's ETF distributions are occasionally late or missing; the report check is there to catch it.
- Performance is before tax and ignores franking and brokerage, like the track record (known-issue #29).

---

## 26. ETFs, Stage 2: Presenting ETFs Apart From Shares (`src/etf/views.py`, `web/`, added 2026-10-06)

**Purpose.** Show ETFs in Sift under their own heading, separate from shares everywhere they appear, as the user asked: *"When presenting ETFs I want that under the etf heading separated to shares"*. The user chose the separation for the menu bar, portfolios, watchlists, and the dashboard and search. ETFs are judged on fee, size, distributions and total return; they have no estimated value, suggested action or score, so nothing share-specific is shown for them.

**Where ETFs show.**
- **Menu bar:** a new **ETFs** item next to Screener. The Screener stays shares only.
- **ETF screener (`#/etfs`, `/api/etfs`):** every active ETF with category, issuer, fee, fund size, 1, 3, 5 and 10-year return, 12-month yield and spread. Sorted by fund size by default; any column sorts. Search covers code, name and the index tracked; filters for category (with counts), issuer, watchlist and held only. `#/etfs?category=&watchlist=&held=1` presets the filters.
- **ETF page (`#/etf/CODE`, `/api/etf/CODE?compare=`):**
  - Stat tiles: unit price and day move, fee (with the cost on $10,000), fund size and net flows, 12-month yield.
  - **Performance:** each period beside the category average and a reference fund, as a column chart and a table. The reference starts as the largest other fund in the same category (`default_reference`) and can be changed (same-category funds listed first); the choice is kept in the address. The report check note appears when Sift's 1-year return differs from the ASX report's by more than 2 points.
  - **Growth of $10,000** over 1, 3, 5 or 10 years or all history, for the ETF and the reference fund from the same start date, distributions reinvested (`growth_index`, sampled weekly). When the reference fund's history is shorter, the start moves to its first price and the chart says so.
  - **Unit price, last 12 months** with D markers on distribution ex-dates; **distributions per unit** by financial year (July to June, the current year marked as partial); **fund facts**; **fund size over time** once two months of reports are loaded.
  - ☆ Add to watchlist, the holding line, and back to the ETF screener.
  - `#/company/CODE` for an ETF code redirects to its ETF page.
- **Dashboard:** a full-width **ETFs** card: watchlist triggers met on ETFs, ETF parcels reaching the CGT discount, and the ETFs you hold or watch (held first, then the biggest move) with day move, 1-year return and yield, linking to the ETF screener. Needs attention stays shares only, and a held ETF is no longer listed as "held but not screened". A line under the portfolio figures splits the total: Shares $X (n) | ETFs $Y (n).
- **Portfolios:** each portfolio page shows **Shares** and **ETFs** under separate headings, each with its value, gain and today's change, below the combined figures. ETF lines show unit price, 1-year return and yield instead of an action. Parcels and sales tag ETF codes. Portfolio cards count companies and ETFs separately. Buying and selling an ETF works as for a share.
- **Watchlists:** each list shows **Shares** and **ETFs** under separate headings, ETFs with unit price, day move, 1-year return, yield, triggers and note. Overview cards count companies and ETFs separately.
- **Search:** ETFs are in the menu search list, labelled ETF (shares labelled Share), and open their own page.

**Watchlist triggers by type.** New `watchlist_items.yield_above` (ETFs only): met while the 12-month distribution yield is above it. Price at or below works for both. A margin of safety trigger on an ETF, or a yield trigger on a share, is refused with a plain-English message. Editing an entry shows only the triggers that apply to it.

**Backend.**
- `src/etf/views.py`: `etf_rows()` (one query: latest report row, performance, two latest closes; held units and watchlists), `category_averages()`, `default_reference()`, `weekly()`, `distributions_by_year()`, `etf_detail()`, `screener_payload()`.
- `src/etf/performance.py`: `growth_index()`, the daily value of one unit with distributions reinvested exactly as `growth()` reinvests them, so a rebased chart agrees with the returns table.
- `src/portfolio/views.py`: `security_types()`, `with_types()` (marks each line SHARE or ETF and adds the ETF figures), `sections()` (subtotals per type); `combined()`, `portfolio_summaries()` and `portfolio_detail()` return `sections`.
- `gui.py`: `/api/etfs`, `/api/etf/{code}`; `etf_panel()` for the dashboard; `companies_index()` marks each code's type; watchlist payloads judge shares on screener rows and ETFs on ETF rows (`watch_rows`) and split entries into `items` (shares) and `etfs`; UUIDs serialise as text.

**Chart colour.** The reference fund needed a third series colour. `--s3` is raspberry (#c2337a light, #e04f9a dark), checked with the dataviz validator against `--s1` and `--s2` on each theme's surface, all pairs: colour-blind separation and contrast pass in both themes. Violet failed in dark mode (too close to the blue).

**Help.** A new ETFs topic: 14 new entries (ETF screener, an ETF's page, fee (MER), fund size (FUM), bid/ask spread, net flows, total return, 12-month yield, unit price, day move, category, issuer, category average and reference fund) plus the ETF and ASX report entries moved into it. MER and FUM are new acronyms, and Total return and Trailing yield new terms, in the Word glossary. The getting around, dashboard, portfolios and watchlists guides mention ETFs. Every new column heading has hover text (`test_knowledge.py` checks each label).

**Tests.** `tests/unit/test_etf_views.py` (the growth index agrees with `growth()`, weekly sampling, financial-year distributions, category averages, default reference) and `tests/integration/test_etf_gui.py` (the ETF screener and page APIs, share and ETF codes refused or redirected, search types, the dashboard's ETF card and split totals, portfolio sections, and watchlist triggers by type). Checked in headless Chromium against a disposable database with 15 made-up ETFs and 10 or more years of prices: every page at 1280px and 390px (no sideways scroll), light and dark, the reference fund picker, growth periods, the distribution markers, search, the company-to-ETF redirect, and adding, editing and refusing watchlist triggers.

**Limits.**
- Category averages are plain averages of the ETFs in the category that have a figure, not weighted by size.
- The reference fund isn't remembered between visits; it's in the page address.
- Yields and returns are before franking and tax (known-issue #29).
