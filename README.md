# ASX Value Investing Database & Screener

A local application for screening ASX-listed equities on classic Graham/Buffett
value criteria: margin of safety, ROE, debt/equity, and franking-adjusted
dividend yield.

See `docs/OVERVIEW.md` for a plain-English explanation of what this does, why
it's useful, and who it's for. See `docs/AS_BUILT.md` for full technical design.

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
    dividend_history.py     ordinary dividends per financial year, one-offs held out
    currency.py             converts statements into the share price's currency
    run_ingestion.py        CLI entrypoint for both
  valuation/
    dividends.py            grossed-up (franked) dividend yield
    graham.py                Graham Number
    dcf.py                    2-stage discounted cash flow (most sectors)
    ddm.py                    2-stage dividend discount model (Financial Services / Real Estate)
    markers.py                earnings quality, price position, dividend reliability, data confidence
    engine.py                 pulls DB inputs together, picks DCF vs DDM by sector, upserts valuation_metrics
    run_valuation.py          CLI entrypoint
  portfolio/
    cgt.py                    Australian CGT arithmetic (cost base, 12-month discount, FY summary)
    holdings.py               parcel records: add, sell (with splitting), positions
  screening/
    actions.py                suggested action + reason for each company
    scores.py                 score wheel checks for the web GUI
screen_asx.py               CLI value screener
portfolio.py                CLI for your holdings and CGT records
gui.py                      web GUI server (see Web GUI below)
web/                        web GUI page, styles and script (no build step)
requirements.txt
requirements-dev.txt        requirements.txt + pytest (see Testing below)
pytest.ini
.env.example
scripts/
  daily_refresh.ps1          Windows Task Scheduler automation (see below)
tests/
  conftest.py                 test-database setup (see Testing below)
  unit/                       no database needed - pure functions + compute_metrics()
  integration/                needs a local PostgreSQL instance
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # edit with your DB credentials
python -m src.apply_schema   # applies db/schema.sql via .env; safe to re-run
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
python screen_asx.py --actions                   # suggested action + reason, grouped
python screen_asx.py --actions --held            # just the shares you hold
```

The 200-day price markers need about a year of stored prices, but the daily
refresh only fetches a month. Backfill once (safe to re-run):

```bash
python -m src.ingestion.run_ingestion --tickers-file allords.txt --prices-only --period 1y --delay 0.5
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

## How Dividends Are Counted

Every dividend figure (yield, payout ratio, dividend trend and the dividend discount model
for banks, insurers and REITs) uses **ordinary dividends per financial year**:

- **Matched to the company's own financial year.** Each year counts the twelve months of
  ex-dividend dates ending four months after its balance date. That captures the interim
  paid during the year and the final paid after it, whether the year ends in June,
  September or December. If those four months haven't passed yet, the twelve months to
  today are used instead, so a year in progress isn't mistaken for a cut.
- **Abnormal one-offs excluded.** A single payment more than twice the company's usual
  annual dividend (a capital return recorded as a dividend, or a very large special) is
  held out and stored separately. The company page shows any excluded amount in its
  dividend chart, so nothing is hidden. Example: Tower (TWR) cancelled 1 in 10 shares in
  March 2025 at A$1.08 each; Yahoo recorded that as a dividend on every share, which had
  produced a 519% payout ratio and a 107% yield.

The correction applies as fundamentals are re-ingested (nightly, or straight away with
`python -m src.ingestion.run_ingestion --tickers-file allords.txt --fundamentals-only --delay 0.5`
then `python -m src.valuation.run_valuation --all`).

## Currency Conversion

Yahoo publishes many companies' financial statements in their own reporting currency: US
dollars for most large miners (BHP, RIO, S32), New Zealand dollars for NZ listings. ASX share
prices are in Australian dollars. Every statement figure (revenue, profit, earnings per share,
cash flow, assets, debt, equity) is converted into the share price's currency **at the exchange
rate on that report's balance date** as it is collected, so P/E, P/B, estimated value, margin
of safety and the Graham Number all compare like with like. Dividends are already recorded in
the trading currency and are not converted.

- If no exchange rate is available within 10 days of a balance date, that company's
  fundamentals are skipped for the run (logged) rather than stored in the wrong currency.
- The company page's Key ratios panel shows the accounts currency and the rate used, e.g.
  "USD, converted to AUD at 1.5234 (30 June 2025)".
- Because each year is converted at its own rate, revenue growth is measured in Australian
  dollars, so it includes currency movements. That is what an Australian investor experiences.

The correction applies on the next fundamentals ingestion (nightly, or straight away with
`python -m src.apply_schema`, then the `--fundamentals-only` ingestion and `run_valuation --all`).

## Decision Markers

Four extra columns, each answering a question the four value tests can't:

| Column | Question | Values |
|---|---|---|
| `earnings_quality` | Is reported profit turning into cash? (operating cash flow vs profit, 3 years) | `STRONG` / `ADEQUATE` / `WEAK` |
| `price_signal` | Is the price stabilising, or still falling? (200-day average, 52-week range) | `UPTREND` / `DOWNTREND` / `NEW LOWS` |
| `dividend_trend` | Is the dividend dependable? (up to 5 years) | `GROWING` / `STEADY` / `CUT` / `NONE`. `CUT` means the latest dividend is still more than 10% below last year or the earlier norm; a cut since restored no longer counts |
| `data_confidence` | How much of the analysis rests on missing data? | `HIGH` / `MEDIUM` / `LOW` |

## Suggested Actions

Every company gets an `action` and a reason explaining it. `python screen_asx.py --actions`
prints them grouped, which is also what the daily log records.

- **Shares you don't hold:** `BUY` (passes all four tests, no red flags), `INVESTIGATE`
  (passes but with a red flag, or cheap and passes 3 of 4), `WATCH` (cheap but failing
  tests, getting cheaper fast, or a quality company waiting for a better price),
  `AVOID` (cheap, declining and profit not backed by cash), `IGNORE` (no signal, not listed).
- **Shares you hold:** `SELL` (fundamentals declining plus overvalued, weak cash or a dividend
  cut), `REVIEW` (any red flag, or well above estimated value), `ACCUMULATE` (still passes
  all four tests with no red flags: the same bar as `BUY`, so consider adding), `HOLD`
  (no red flags, but fails a test, so not adding). On `SELL`/`REVIEW`, if a parcel is within
  90 days of the 12-month CGT discount, the reason says so, since waiting can halve the tax.

Red flags: value-trap risk, payout ratio over 150%, weak earnings quality, dividend cut,
price making new lows, low data confidence. These are rule-based research prompts, not
financial advice: read the reason, then check the numbers behind it.

## Web GUI (Sift)

`gui.py` is a local web app, branded **Sift**, over the same database and the same rules as
`screen_asx.py` (it calls the screener's own row loader, so the two never
disagree). It is read-only.

```
python gui.py           # this PC: open http://localhost:8000
python gui.py --lan     # also your phone on home Wi-Fi (see below)
```
Press `Ctrl+C` to stop it.

- **Menu bar:** Dashboard, Screener, Watchlists, Portfolios, Track record and Markets (links
  to the ASX, the ASX's exchange traded funds (ETFs) list, the New York Stock Exchange (NYSE)
  and Nasdaq, opening in a new tab). The pink underline shows where you are. On a phone or
  narrow window the menu folds behind the ☰ button. Watchlists and multiple portfolios
  arrive in later updates; the menus say so for now.
- **Find a company:** type a code or part of a name in the search box and pick from the list,
  or press Enter, to jump straight to that company's page.
- **Data chip:** next to the search box, the date of the latest prices and valuations. Green
  when current; amber with a "!" when the data is behind the last weekday's close (the
  nightly job didn't run, or it was a public holiday) or the last nightly run crashed or
  didn't finish. Hover it for the details, including when the last run started and finished
  and how many companies it couldn't update.
- **Dashboard (home page):** your portfolio's value, today's change, unrealised gain and cost
  base; **Needs attention** (held shares flagged SELL or REVIEW, and parcels reaching the
  capital gains tax (CGT) discount within 90 days); **What changed** (companies whose suggested
  action moved since the previous night, better first); **Top opportunities** (BUY, then
  INVESTIGATE, by score); today's action counts (click one to open the screener filtered to
  it); and how far the track record has got.
- **My holdings (Portfolios menu):** every open holding with units, cost base, price, value,
  gain, today's change, suggested action and the CGT discount date.
- **Track record:** Sift records every company's suggested action, valuation and score each
  night, never editing them afterwards, so they can be checked against what the share price
  did next. Results start one month after recording begins; until then the page shows
  what's been recorded and when each set of results is due.
- **Screener:** every company with a mini score wheel, price, margin of safety, ROE,
  debt/equity, grossed-up yield, the four Y/N tests and the suggested action. Click the
  action chips to filter, search by code or name, filter by sector, "passes all four" or
  "held only", and click a column header to sort. Click a row to open the company.
- **Company page:** the score wheel and the 30 checks behind it (in a "Score breakdown" panel
  where each spoke collapses to one line showing its score; click the pink twisty, or
  "Expand all", to see the checks), price against estimated
  value and the Graham Number, the four value tests, quality markers and red flags, key
  ratios, a 12-month price chart with the 200-day average and a pink **D** on each
  ex-dividend date (outlined if it was a one-off excluded from dividend figures; hover for the
  amount; the chart's data table lists them too), margin-of-safety history, and
  revenue, profit and dividends by year. Hover a chart for values; each has a data table.
- **Valuation status:** every company gets a pill: **Undervalued** (margin of safety above 20%,
  i.e. passes the value test), **Fair value** (0% to 20%), **Overvalued** (below 0%) or
  **No estimate**. Shown in the table and on the company page.
- **Summary strip:** the top of each company page shows share price, estimated value, margin of
  safety and **implied upside** ((value - price) / price, which is not the same as margin of
  safety), followed by the valuation model and its exact assumptions.
- **Light or dark:** the gear icon (top right) offers Light, Dark or System (follows Windows or
  your phone). Your choice is remembered in that browser.
- **Field explanations:** hover any column heading, or any label on the company page, to see
  what it measures, how it is calculated and the pass threshold. Underlined headings have one.
  On a phone, tap the small "i" next to the heading instead.
- **Score wheel:** five spokes (Value, Performance, Health, Dividend, Momentum), each a count
  of six yes/no checks, so every score traces to named rules. Missing data never counts as a
  pass. The checks are listed in `src/screening/scores.py` and the rules document.

**Phone access (`--lan`).**
1. Add `GUI_PASSWORD=choose-something-long` to `.env`. `--lan` refuses to start without it,
   so others on your network can't see your holdings. Once set, every device is asked for it.
2. Allow the port through Windows Firewall, once, from an administrator Command Prompt:
   `netsh advfirewall firewall add rule name="ASX Value Screener GUI" dir=in action=allow protocol=TCP localport=8000 profile=private`
   (your home network must be set to Private in Windows).
3. Run `python gui.py --lan`. It prints the address to open on your phone, for example
   `http://192.168.1.20:8000`. Log in with any username and the password.

The connection is plain HTTP, which is fine on home Wi-Fi. Never forward the port on your
router to expose it to the internet.

**Start it automatically.** In Task Scheduler, create a task triggered "At log on" that runs
`C:\Users\mrdav\Portfolio\.venv\Scripts\python.exe` with arguments `gui.py --lan` and
"Start in" set to `C:\Users\mrdav\Portfolio`.

## Recording Your Holdings (CGT)

`portfolio.py` keeps one record per parcel, since Australian CGT (including the 50%
discount after 12 months) applies per parcel. Brokerage is included in the cost base.

```bash
python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --brokerage 9.95 --broker CommSec
python portfolio.py add BHP --units 3 --price 44.10 --date 2025-09-25 --method DRP
python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --brokerage 9.95
python portfolio.py sell BHP --units 50 --price 48.10 --date 2026-04-02 --order min-tax   # least tax first
python portfolio.py list --all        # open and sold parcels, gains, CGT discount dates
python portfolio.py cgt --fy 2025-26  # realised gains and the financial-year summary
python portfolio.py delete 1a2b3c4d   # fix a mistake (ID from `list`)
```

Selling part of a parcel splits it automatically, apportioning brokerage so the cost base
stays exact. Sell order is oldest first by default; `--order min-tax` sells the parcels
giving the smallest taxable gain (counting the discount) and `--parcel` picks one. Not
covered: dividend income and franking credits, losses carried forward from earlier years,
and cost base adjustments from corporate actions. A record-keeping aid, not tax advice.
Back the table up occasionally, since unlike market data it can't be re-downloaded:
`pg_dump -t holdings asx_value > holdings_backup.sql`.

## Testing

```bash
pip install -r requirements-dev.txt
pytest                  # runs both tiers below
pytest tests/unit       # pure functions + compute_metrics() - no database needed at all
pytest -m integration   # needs a local PostgreSQL instance (see below)
```

Two tiers:

- **`tests/unit/`** - pure functions (`dividends.py`, `graham.py`, `dcf.py`, `ddm.py`) and
  `engine.py`'s `compute_metrics()`, built entirely on plain, unpersisted ORM objects -
  no database connection at all, so these run in well under a second.
- **`tests/integration/`** - the parts that genuinely need a real database:
  `gather_inputs()`'s queries, the overflow-clamp actually round-tripping through
  PostgreSQL, `run_valuation()`'s per-company crash isolation, and the screener's
  SQL against the real view. `tests/conftest.py` creates an `asx_test` database and
  applies `db/schema.sql` automatically on first run (set `TEST_DATABASE_URL` to
  point at a different instance) - it never touches whatever database your `.env`
  points at.

If no PostgreSQL instance is reachable, `tests/integration/` skips with a clear
reason rather than failing - `tests/unit/` is completely unaffected either way.

Several tests pin real historical figures from this project's own bug history
(SUN's FCF averaging, TWR's payout ratio, BRN/WHI's numeric overflow values -
see docs/AS_BUILT.md §10.12) as regression fixtures, not synthetic approximations.

## Daily Automation (Windows Task Scheduler)

`scripts/daily_refresh.ps1` runs the full pipeline unattended, in order:
schema update → ingestion → valuation → signal record (for the track record) → screener, logging everything to a timestamped file
under `logs\` (pruned automatically after 30 days). Each step runs even if
a previous one hit problems, so a transient Yahoo Finance network error
during ingestion doesn't block valuation/screener from running against
whatever data is already in the database.

**Prerequisites** (already set up on a machine you've run the project on
manually): `.venv` created and `requirements.txt` installed, `.env`
configured, and a watchlist file (e.g. `allords.txt`) present at the repo
root. The script resolves the repo root from its own location, so it
keeps working if the repo is moved.

**Schema changes apply themselves.** The first step runs
`python -m src.apply_schema`, so after a `git pull` that adds a column the
next scheduled run brings the database up to date before anything else
touches it. To apply it straight away instead of waiting, run the same
command yourself (no psql or password prompt needed).

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
   check `logs\refresh_<timestamp>.log` for the phase headers and no
   unexpected errors. The Sift dashboard's data chip and footer also show how the last run
   went.

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
