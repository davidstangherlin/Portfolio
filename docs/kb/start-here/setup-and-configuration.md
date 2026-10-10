---
id: setup-and-configuration
title: Setup, configuration and rebuilding from zero
category: start-here
summary: Software versions, how the database connection is configured, and the step-by-step rebuild of a working Sift from an empty machine.
version: 1.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-10
next_review: 2026-11-09
source: AS_BUILT §3, §5, §12
related: [system-overview, rb-backup-restore, ref-dependencies, adr-011-idempotent-schema, adr-016-statistics-libraries]
code: [src/config.py, .env.example, src/apply_schema.py, requirements.txt]
---

## Summary

Use this to set up a new machine, a test environment or a helper's laptop. Secrets (the database password, GUI_PASSWORD) live only in `.env`, which is never committed; never paste them into chat or tickets.

### Environment & Prerequisites

| Component | Version used in development/testing | Notes |
|---|---|---|
| Python | 3.11 | 3.11+ required (uses `X \| None` union type syntax throughout) |
| PostgreSQL | 16 | Schema uses only standard SQL + `uuid-ossp` extension; should work on PG 13+ |
| SQLAlchemy | 2.0.52 | Uses 2.0-style `Mapped[]` / `mapped_column()` declarative syntax throughout |
| psycopg2-binary | 2.9.13 | PostgreSQL driver |
| yfinance | 1.7.0 | Unofficial Yahoo Finance client, see §8 for stability caveats |
| pandas | 3.0.5 | yfinance dependency, used directly in `yahoo_client.py` for NaN/date handling |
| python-dotenv | 1.2.3 | Loads `.env` in `src/config.py` |
| tabulate | 0.10.0 | Table formatting in `screen_asx.py` |
| NumPy, SciPy, statsmodels | 2.4.6, 1.17.1, 0.15.0 | Statistics and forecasting ([ADR-016](kb:adr-016-statistics-libraries)) |

Full pinned list: `requirements.txt` (repo root).

### Configuration (`src/config.py`, `.env.example`)

Connection string resolution order:

1. `DATABASE_URL` environment variable (or `.env` entry), used verbatim if set
2. Otherwise built from `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` (defaults: `localhost` / `5432` / `asx_value` / `postgres` / empty)

`get_engine()` and `get_session_factory()` are `@lru_cache`d singletons, one engine per process. `get_session()` returns a fresh `Session`; callers are responsible for closing it (all CLI entrypoints use it as a context manager).

**This module never creates or migrates schema**, `Base.metadata.create_all()` is never called anywhere in the codebase. Schema lifecycle is entirely `db/schema.sql`, applied manually via `psql`.

### Rebuild Runbook (From Zero)

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

From then on, the schema update and step 5's commands run nightly via `scripts/daily_refresh.ps1` ([§16](kb:nightly-run)).

**Full teardown/reset** (destroys all ingested data, keeps schema definition intact for re-apply). `holdings` and `portfolios` are deliberately not in this list - parcel records are your tax records, not re-downloadable market data. Because the other tables refer to `companies`, `CASCADE` also empties `dividend_payments`, `signal_snapshots` and `signal_outcomes` (the last 14 months of track record detail) and `watchlist_items` (every watchlist's companies, notes and triggers; the lists themselves stay). `track_record_monthly` survives. Back up first if you want those back:
```bash
psql "$DATABASE_URL" -c "TRUNCATE companies, daily_prices, financial_reports, valuation_metrics CASCADE;"
```
