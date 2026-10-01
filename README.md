# ASX Value Investing Database & Screener

A local application for screening ASX-listed equities on classic Graham/Buffett
value criteria: margin of safety, ROE, debt/equity, and franking-adjusted
dividend yield.

## Project Layout

```
db/
  schema.sql               PostgreSQL schema (companies, daily_prices,
                            financial_reports, valuation_metrics, screener view)
src/
  config.py                DB connection (env-var driven)
  models/                  SQLAlchemy ORM models, one per schema table
  ingestion/
    yahoo_client.py         yfinance wrapper for ASX tickers (adds .AX suffix)
    price_ingestion.py      upserts daily_prices from Yahoo Finance
    fundamentals_ingestion.py  upserts financial_reports from Yahoo Finance
    run_ingestion.py        CLI entrypoint for both
  valuation/
    dividends.py            grossed-up (franked) dividend yield
    graham.py                Graham Number
    dcf.py                    2-stage discounted cash flow
    engine.py                 pulls DB inputs together, computes & upserts valuation_metrics
    run_valuation.py          CLI entrypoint
screen_asx.py               CLI value screener
requirements.txt
.env.example
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # edit with your DB credentials
psql "$DATABASE_URL" -f db/schema.sql
```

## Workflow

```bash
# 1. Pull prices and fundamentals from Yahoo Finance for a set of ASX codes
python -m src.ingestion.run_ingestion --tickers BHP CGF WES CBA --period 1y

# For a large watchlist, use a file instead (one or more codes per line,
# '#' comments allowed) and pace requests to ease Yahoo rate limiting:
python -m src.ingestion.run_ingestion --tickers-file watchlist.txt --delay 0.75

# 2. Compute valuation metrics (ratios, grossed-up yield, Graham Number, DCF,
#    margin of safety) from the latest ingested data
python -m src.valuation.run_valuation --all

# 3. Screen for value opportunities
python screen_asx.py
python screen_asx.py --min-roe 15 --min-yield 5 --sector Financials
```

Default screen thresholds: Margin of Safety > 20%, ROE > 12%, Debt/Equity < 0.80,
Grossed-Up Dividend Yield > 4.5% (all four required; pass `--any-of` to match on
any single criterion instead).

## Known Data Model Limitations

- **`current_ratio`** is left `NULL` by the valuation engine: `financial_reports`
  stores `total_assets`/`total_liabilities` but not the current (short-term)
  split, so a genuine current ratio can't be derived without adding those columns.
- **Franking percentage and corporate tax rate** aren't exposed by Yahoo Finance.
  Ingestion defaults new records to fully franked (100%) at the standard 30%
  Australian corporate rate; correct by hand for anything known to pay
  partly-franked or unfranked dividends.
- **Shares outstanding** isn't a schema column. It's derived at valuation time
  from `daily_prices.market_cap / close_price`, falling back to
  `net_profit_after_tax / eps` when market cap is unavailable.
