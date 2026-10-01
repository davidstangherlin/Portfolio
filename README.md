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
    dcf.py                    2-stage discounted cash flow (most sectors)
    ddm.py                    2-stage dividend discount model (Financial Services / Real Estate)
    engine.py                 pulls DB inputs together, picks DCF vs DDM by sector, upserts valuation_metrics
    run_valuation.py          CLI entrypoint
screen_asx.py               CLI value screener
requirements.txt
.env.example
scripts/
  daily_refresh.ps1          Windows Task Scheduler automation (see below)
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

# 2. Compute valuation metrics (ratios, grossed-up yield, Graham Number,
#    DCF/DDM intrinsic value, margin of safety, trend indicators) from the
#    latest ingested data
python -m src.valuation.run_valuation --all

# 3. Screen for value opportunities - shows every company, not just the
#    ones that pass (see below)
python screen_asx.py
python screen_asx.py --min-roe 15 --min-yield 5 --sector Financials
python screen_asx.py --passing-only              # old filtered-to-matches-only view
```

`screen_asx.py` lists **every** company with a `Y`/`N` indicator column per
criterion (`mos_ok`, `roe_ok`, `de_ok`, `yield_ok`) plus an `overall` column,
rather than filtering non-matching companies out of the result entirely - so a
company close to clearing the bar (or missing one input metric) stays visible
instead of silently disappearing. Default thresholds used for the indicators:
Margin of Safety > 20%, ROE > 12%, Debt/Equity < 0.80, Grossed-Up Dividend
Yield > 4.5%. `overall` requires all four by default; pass `--any-of` to
require only one. Pass `--passing-only` to filter down to just the rows where
`overall = Y` (the screener's pre-2026-10 behaviour). Rows are ordered by
margin of safety (best first) and unlimited by default; pass `--limit N` to cap
how many are shown.

**Sector-aware intrinsic valuation:** Financial Services and Real Estate companies
are priced with a Dividend Discount Model instead of the standard DCF (banks,
insurers and REITs report "free cash flow" dominated by balance-sheet movements,
not reinvestment capex, so a standard DCF doesn't apply to them - see Known Data
Model Limitations below). Every screener row includes a `valuation_method` column
(`DCF` or `DDM`) showing which model priced it. Note the default Debt/Equity < 0.80
threshold is structural for banks (leverage is their business model) - use
`--max-debt-equity` with a much higher value, or `--any-of`, when screening
Financial Services companies specifically.

**"Momentum into value" and a value-trap warning:** two more indicators, both
informational (excluded from `overall` - they answer a different question
than the core four-criterion screen):

- **`momentum_ok`** - `Y` when `margin_of_safety_trend` (the change in margin
  of safety vs `--trend-days` ago, default 30) has improved by more than
  `--min-mos-trend` (default 5 percentage points). This is the "catch it
  before others" ranking: pass `--rank-by momentum` to sort by
  `margin_of_safety_trend` instead of absolute margin of safety, surfacing
  companies getting cheaper *fastest* rather than ones that have simply been
  cheap for a while.
- **`trap_risk`** - `Y` when a company passes `mos_ok` (looks cheap) but its
  `fundamentals_trend` is `DECLINING` (ROE and/or revenue trending down across
  the financial-report years used for the DCF/DDM average). A visible flag
  for a potential value trap: cheap because the business is deteriorating,
  not because the market has mispriced it. Flagged tickers are also called
  out in a printed warning line, the same way `payout_ratio` is.

`margin_of_safety_trend` needs real history to populate: it compares today's
margin of safety against the most recent `valuation_metrics` snapshot at
least `--trend-days` old for that company, so it (and `momentum_ok`) will be
blank for every company until daily automation (see below) has been running
for that long - the screener prints a note when this is the case, so a blank
column reads as "not enough history yet," not a bug. `fundamentals_trend`
has no such wait: it only needs 2+ years of already-ingested annual reports,
so it populates on the very next `run_valuation` run.

## Daily Automation (Windows Task Scheduler)

`scripts/daily_refresh.ps1` runs the full pipeline unattended, in order:
ingestion → valuation → screener, logging everything to a timestamped file
under `logs\` (pruned automatically after 30 days). Each step runs even if
a previous one hit problems, so a transient Yahoo Finance network error
during ingestion doesn't block valuation/screener from running against
whatever data is already in the database.

**Prerequisites** (already set up on a machine you've run the project on
manually): `.venv` created and `requirements.txt` installed, `.env`
configured, and a watchlist file (e.g. `allords.txt`) present at the repo
root. The script resolves the repo root from its own location, so it
keeps working if the repo is moved.

**One-time setup:**

1. `git pull` to get `scripts/daily_refresh.ps1` onto your machine.
2. Confirm your watchlist file (`allords.txt` by default — edit the
   `$WatchlistFile` line in the script if you use a different name/file)
   exists at the repo root.
3. Open **Task Scheduler** → **Create Task** (not *Basic Task*, so you get
   the full options below):
   - **General**: name it e.g. `ASX Value Screener - Daily Refresh`; select
     "Run whether user is logged on or not" if you want it to run even when
     locked out.
   - **Triggers** → **New**: Daily, start time after ASX close with a
     buffer for Yahoo Finance data to settle — **6:00 PM** local time is a
     reasonable default.
   - **Actions** → **New**:
     - Program/script: `powershell.exe`
     - Add arguments: `-NoProfile -ExecutionPolicy Bypass -File "C:\Users\mrdav\Portfolio\scripts\daily_refresh.ps1"`
   - **Conditions**: untick "Start the task only if the computer is on AC
     power" if this runs on a laptop that may be on battery.
   - **Settings**: tick "Run task as soon as possible after a scheduled
     start is missed" so a missed run (machine off at 6pm) catches up next
     time it's on.
4. Run the task once manually (right-click → Run) to confirm it works, then
   check `logs\refresh_<timestamp>.log` for the three phase headers and no
   unexpected errors.

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
- **Debt/Equity is structurally high for Financial Services companies** (banks'
  leverage is their business model, not a red flag the way it is for an
  industrial company) - the default `--max-debt-equity 0.80` indicator
  threshold will read `N` for nearly every bank/insurer regardless of how
  cheap it is on other measures, pulling `overall` to `N` under the default
  all-four-required logic. This is a threshold-tuning issue, not a valuation
  bug: the DDM-based margin of safety for these companies is computed
  correctly (see Workflow above); it's the `de_ok` leg of `overall` that
  needs a much higher `--max-debt-equity` (or `--any-of`) when screening
  financials - the row itself is always shown either way.
- **`margin_of_safety_trend`/`momentum_ok` are blank for a genuine cold-start
  period.** They compare today's margin of safety against a `valuation_metrics`
  snapshot at least `--trend-days` old (default 30), so there's nothing to
  compare against until daily automation has accumulated that much history -
  this isn't a bug, and the screener prints a note confirming it. `fundamentals_trend`/
  `trap_risk` don't have this constraint (they use already-ingested annual
  report history, not daily snapshots) and populate immediately once a
  company has 2+ years of `financial_reports`.
- **`fundamentals_trend` is a simple heuristic** (latest vs oldest FY report's
  ROE and revenue direction, see `src/valuation/engine.py`'s `_fundamentals_trend()`),
  not a sophisticated trend model - it won't catch a decline that started
  mid-window and partially recovered, and a company with only 2 FY reports
  gets a trend based on just those two points. Treat `trap_risk` as a prompt
  to look closer, not a verdict.
