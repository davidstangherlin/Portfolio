# ASX Value Investing Database & Screener

A local application for screening ASX-listed equities on classic Graham/Buffett
value criteria: margin of safety, ROE, debt/equity, and franking-adjusted
dividend yield.

See `docs/OVERVIEW.md` for a plain-English explanation of what this does, why
it's useful, and who it's for. See `docs/AS_BUILT.md` for full technical design.

## Project Layout

```
db/
  schema.sql               PostgreSQL schema: market data, valuations, holdings and portfolios,
                            watchlists, the track record, saved scenarios and the screener view
src/
  config.py                DB connection (env-var driven)
  accounts.py              users and who Sift is acting for: personal data is scoped to them (multi-user Phase 1)
  settings.py              every adjustable setting: live values, ranges, formulas (see Admin console)
  apply_schema.py          brings the database up to the schema (nightly step 0, and on GUI start)
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
    cgt.py                    Australian CGT arithmetic, discount by tax type, FY summary
    holdings.py               portfolios and parcels: add, sell (with splitting), undo, archive, positions
    views.py                  portfolio figures for the web GUI
    trade_input.py            checks on trades typed into the browser
  screening/
    actions.py                suggested action + reason for each company
    scores.py                 score wheel checks for the web GUI
    enriched.py               screener rows with scores and valuation status (GUI and track record)
  etf/
    asx_report.py             finds, downloads and reads the ASX Investment Products report
    prices.py                 nightly ETF prices and distributions (full history the first time)
    performance.py            ETF total returns, 1 month to 10 years, and trailing yield
    views.py                  the ETF screener and ETF pages' figures
    run_etfs.py               CLI entrypoint (nightly step, --inspect, --report)
  admin/
    scenarios.py              what-if runs compared with live, on today's data
    workings.py               a company's figures step by step, and the sensitivity grid
  watchlist/
    lists.py                  watchlists: entries, notes, triggers
  tracking/
    signals.py, record_signals.py   nightly signal record (nightly step 3)
    outcomes.py, score_signals.py   scores signals at 1/3/6/12 months (nightly step 4)
    report.py                 the Track record page's figures
screen_asx.py               CLI value screener
portfolio.py                CLI for your portfolios, holdings and CGT records
gui.py                      web GUI server, Sift (see Web GUI below)
web/                        web GUI page, styles and script (no build step)
  knowledge.json            the knowledge base: Help page, hover text and Word glossary
requirements.txt
requirements-dev.txt        requirements.txt + pytest (see Testing below)
pytest.ini
.env.example
scripts/
  daily_refresh.ps1          Windows Task Scheduler automation (see below)
  build_rules_doc.js         builds the Word rules document (see Editing the Help text)
tests/
  conftest.py                 test-database setup (see Testing below)
  unit/                       no database needed
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

# Analyst ratings, price targets and holders are fetched weekly as part of
# the normal run (a seventh of the shares each night). To fetch them all now:
python -m src.ingestion.run_ingestion --tickers-file watchlist.txt --insights-only --insights-all --delay 0.75

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
disagree). It only ever writes portfolios and trades you enter, and only from its own pages.

```
python gui.py           # this PC: open http://localhost:8000
# or double-click start_sift.bat in the project folder: it uses .venv's Python directly
# (no activation needed) and opens the browser
python gui.py --lan     # also your phone on home Wi-Fi (see below)
```
Press `Ctrl+C` to stop it. On start it brings the database up to date (the same step the
nightly job runs first), so restarting it after a `git pull` is enough.

**After a reboot**, double-click `sift_console.bat` for a command window ready to run Sift's
scripts. It starts PostgreSQL if it's stopped (run it as administrator if that's refused),
pulls the latest code, installs any new packages, brings the database up to date, then opens
PowerShell (7 if installed) with `.venv`'s Python switched on and a list of common commands.
The execution policy is bypassed for that window only, so `.\scripts\daily_refresh.ps1` runs too.

**Accounts (multi-user Phase 1).** Sift keeps a `users` table, and your portfolios,
watchlists, what-if scenarios and dashboard layout belong to the first admin account,
"Owner". Nothing changes in use: until sign-in arrives (Phase 3) every request, the command
line and the nightly run act as the owner. Market data, valuations and help are shared. The
plan and its status: `docs/MULTI_USER_PLAN.md`.

- **Menu bar:** Dashboard, Screener, Watchlists, Portfolios, Track record and Markets (links
  to the ASX, the ASX's exchange traded funds (ETFs) list, the New York Stock Exchange (NYSE)
  and Nasdaq, opening in a new tab). The pink underline shows where you are. On a phone or
  narrow window the menu folds behind the ☰ button. The Watchlists and Portfolios menus list
  yours, with a link to create a new one.
- **Filter any table:** every list (the screeners, watchlists and portfolio holdings) has a search box
  over all its columns, a pink **Filter** button for conditions such as Margin of safety > 20% AND Sector
  = Financial Services, and right-click on any cell (press and hold on a phone) for Show matching or
  Filter out (docs/AS_BUILT.md §30).
- **Find a company or term:** type a code or part of a name in the search box and pick from the
  list, or press Enter, to jump straight to that company's page. Type a term instead (franking,
  SMSF, margin of safety) and it opens that Help entry, or the Help search results.
- **Help** (the ? to the right of your profile picture): a searchable page of every term, rule and how-to in Sift: 78 entries in ten topics,
  from margin of safety and the four value tests to portfolios, watchlists and the track record.
  Each entry has a one-line definition, the full explanation with the live thresholds, related
  terms and links to the right page (for example, the screener filtered to BUY).
- **Data chip:** next to the search box, the date of the latest prices and valuations. Green
  when current; amber with a "!" when the data is behind the last weekday's close (the
  nightly job didn't run, or it was a public holiday) or the last nightly run crashed or
  didn't finish. Hover it for the details, including when the last run started and finished
  and how many companies it couldn't update.
- **Dashboard (home page):** your portfolio's value, today's change, unrealised gain and cost
  base; **Needs attention** (held shares flagged SELL or REVIEW, parcels reaching the
  capital gains tax (CGT) discount within 90 days, and watchlist triggers met); **What changed**
  (companies whose suggested action moved since the previous night, watchlist companies first,
  then better moves first); **Biggest movers** (the 5 screener shares that rose and fell
  most on the last trading day, by percentage, with their score wheels, and the top 5 each
  way for ETFs and LICs);
  **Top opportunities** (BUY, then
  INVESTIGATE, by score); today's action counts (click one to open the screener filtered to
  it); and how far the track record has got. **Arrange the widgets:** click a widget's pin
  (top right) to unlock it, then drag it by its title bar, use the arrows, switch it between
  half and full width, or hide it; click the pin again to lock it. The layout is saved in the
  database, so it's the same in every browser; **Reset to default layout** under the widgets
  undoes it all.
- **Watchlists:** named lists of companies to follow without owning them (for example
  "Dividend ideas" or "Wait for a dip"). Add a company with the **☆** at the left of its row in
  the screener (the ETF and LIC lists have it too), with **☆ Add to watchlist** on its page
  (tick the lists, or name a new one), or from the watchlist's own page. Each entry can have a
  note and up to two triggers: **margin of safety above X%** and **price at or below $Y**. A
  trigger met shows a tick on the watchlist page and appears under Needs attention on the
  dashboard until it stops being true. Watched companies carry a pink ★ in the screener, which
  can also be filtered to one watchlist or to any. Removing a company or deleting a list asks
  first. Only companies Sift values can be watched: these lists are separate from the nightly
  ticker file (`allords.txt`), which decides which companies are valued at all.
- **Portfolios:** keep several portfolios (for example your own shares, a family trust and a
  self-managed super fund), each with its owner's tax type, which sets its capital gains tax
  (CGT) discount: individual or trust 50%, SMSF 33⅓%, company none. The Portfolios menu lists
  them; **All portfolios** shows a card for each and a form to create one. Each portfolio's page
  has its holdings, a **Record a trade** form (buy, or sell with oldest parcels first, smallest
  taxable gain first, or one chosen parcel), its open parcels, its sales, CGT by financial year
  and its settings (rename, change tax type, archive, delete). Mistakes: **Delete** removes a
  parcel entered by mistake and **Undo** reverses a sale; both ask first. A portfolio with
  sales can't be deleted, because those are tax records: archive it once everything is sold
  and it moves out of the way with its sales still in the CGT report. With more than one
  portfolio, the dashboard lists each one.
- **Track record:** is Sift right? Every night Sift records each company's suggested action,
  valuation and score, never editing them afterwards. The shared record is Sift's call for
  someone who doesn't hold the share, the same for everyone; each person's calls on the shares
  they hold (HOLD, SELL, ACCUMULATE, REVIEW) are recorded for them alone, so "What changed",
  "What did I miss?" and the calls that saved money are your own. Each company's first signal of each
  month is then scored 1, 3, 6 and 12 months later: its total return including dividends,
  against the average of every company screened that night. The page answers three questions:
  - **Is Sift accurate?** One sentence per action and period, for example "BUY calls beat the
    average screened share by 5.8 points over 3 months; 67% of 202 beat it", with a confidence
    label (too early under 30 signals, moderate up to 100, solid above), and a check that BUY
    beats WATCH and WATCH beats AVOID. A table shows each month's results.
  - **What did I miss?** BUY and INVESTIGATE calls on shares you didn't buy within 30 days that
    beat the average by more than 10 points, and AVOID and SELL calls that saved you money.
  - **What should I look at now?** Today's signals of the kind that has proven itself, still
    more than 20% below estimated value: new this week, still open, and those that have moved on.
  Filter by rules version to judge each set of rules on its own results. Results start one month
  after recording begins; until then each panel says when its results are due. The dashboard's
  Track record card shows the headline BUY result once there is one.
- **Search** (top right) finds anything in Sift: shares, ETFs, LICs, fund managers, your watchlists
  and portfolios, help articles, pages and settings. The pink **▾** beside the magnifying glass
  chooses **Everything** or **This page**: the dashboard searches everything, every other page
  itself (its list's search box, or highlighting the words on the page). Admins also get
  **Developer knowledge base**, which searches only the developer articles; they're never in
  Everything. Results come with tick
  boxes down the left (type, sector or category, recommendation, Mine, knowledge article topic).
  The index is rebuilt after each nightly run, your own lists when you save them, and help and
  pages when Sift starts; rebuild it now from **Admin → Search**, or with
  `.venv\Scripts\python.exe -m src.search.reindex`. Search learns: opened results and pink
  thumbs up rise for the same search, thumbs down sink. **Admin → Search** also has synonyms
  (cba = commonwealth bank), search insights (top and failed searches), and meaning-based (AI)
  search, built in but off until you install a small local model.
- **Coattail:** follow the smart money. A card per fund manager holding the screener's
  companies (Vanguard, BlackRock and so on, from Yahoo's top holder lists, refreshed weekly),
  with the average score wheel of what it holds and how many it's adding to and cutting; click
  one for every company it holds and the shares bought or sold. Also which companies managers
  are adding to and cutting most. ASX director trades and substantial holders are next.
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
- **You (avatar, top right):** Profile (your display name), Preferences and Keyboard shortcuts;
  admins also get Impersonate user, Users, Model and rules and What-if scenarios. Preferences
  are saved to your account so they follow you to any browser: theme (Dark, the default, or Light),
  compact spacing, wrapping long names, help tips, reduce motion, patterns and data tables for
  charts, always-visible buttons, keyboard shortcuts, start page, search scope and rows shown.
  Shortcuts: `/` search, `?` the list, `g` then a letter to go somewhere (`g s` Screener).
- **Developer knowledge base (admins):** Admin, Developer: how Sift is designed and how it works,
  in articles kept with the code in `docs/kb/`. Start here guides, one article per feature, data,
  runbooks for common problems, decision records, reference pages generated from Sift itself (data
  dictionary, API, settings, dependencies, tests), the improvement register and release notes. Each
  article has a version, owner and review dates; overdue reviews show on its home page. Sift's
  version is in `src/version.py`.
- **Users and impersonation (admins):** Admin, Users adds, disables and changes the role of
  accounts. Impersonate lets an admin see and use Sift exactly as a member does, with a banner
  and End button on every page; sessions end by themselves after 8 hours and are all logged.
  Users also shows each person's last login, last seen, sessions and average session length
  over 30 days, and a log of recent sessions (a session ends after 30 minutes idle). Profile
  shows your previous visit. Admin, Search insights breaks searching down by person.
- **Field explanations:** hover any column heading, or any label on the company page, to see
  what it measures, how it is calculated and the pass threshold. Underlined headings have one.
  On a phone, tap the small "i" next to the heading instead. These come from the same
  knowledge base as the Help page (see "Editing the Help text" below).
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

### Editing the Help text

`web/knowledge.json` is the single source for three things: the Help page, the hover
explanations, and the glossary in the Word rules document. Edit a definition there, reload
Sift, and the Help page and hover text change together. `{margin_of_safety}`, `{roe}`,
`{debt_to_equity}` and `{yield}` are replaced with the live thresholds. `pytest` checks the
file (unique IDs, working links, every hover label covered, no unknown placeholders).

To rebuild the Word document after a change (needs Node.js, once: `npm install`):
```
cd scripts
npm install
node build_rules_doc.js
```

### Admin console: model, workings and what-if scenarios

Open your avatar menu (top right) and choose **Model and rules** or **What-if scenarios**. Same
password as the rest of Sift.

- **Model and rules** lists the nightly steps and all 29 settings Sift uses (valuation
  models, value tests, markers and actions, score wheel), each with its live value, allowed
  range, formula and where it's used. The pink **?** opens the Help entry for that concept.
- **Show workings**, at the foot of every company page, walks through each figure: the cash
  flow or dividend base, the year-by-year projection, discounting, estimated value, margin of
  safety, ratios, each test and marker. A sensitivity grid shows the estimated value across
  discount and growth rates. Choose a saved scenario to see the workings under it.
- **What-if scenarios**: change any settings (changed values turn pink), then **Run** to see
  what would change today: actions under live and the scenario, the companies that move
  (yours and your watchlists flagged), the margin of safety spread and average score.
  **Save** keeps the scenario by name. Settings that make no sense together (for example a
  discount rate below terminal growth) are refused with the reason.

Nothing live changes: a run writes nothing, and the nightly job, screener, dashboard and track
record keep using the live settings in `src/settings.py`. Changing a live setting is still a
code change (edit `src/settings.py`, run `pytest`, commit). See docs/AS_BUILT.md §24.

### Company page extras

- **About:** the first two sentences of Yahoo's business summary under the sector line, with
  **more** for the rest (docs/AS_BUILT.md §28).
- **Analyst ratings, price targets and holders** from Yahoo Finance: monthly strong buy to
  strong sell counts, the low / average / high price target against today's price and Sift's
  estimated value, the major holders breakdown, and the top 10 mutual fund and institutional
  holders. Context only: none of it feeds Sift's value, scores or signals. Refreshed weekly;
  coverage of smaller ASX companies is thin (docs/AS_BUILT.md §29).

## ETFs

Every ETF listed on the ASX is collected alongside the shares and shown under its own
**ETFs** heading, apart from shares (stages 1 and 2 of 4). See docs/AS_BUILT.md §25 and §26.

- **Screener menu, ETFs:** the ETF screener (fee, fund size, 1 to 10-year returns, yield, spread; filter
  by category, issuer, watchlist or held) and a page per ETF: performance against its
  category average and a reference fund you choose, growth of $10,000, unit price with
  distributions marked, distributions per financial year, fund facts.
- **Dashboard, portfolios and watchlists** show ETFs in their own section: an ETFs card on the
  dashboard, Shares and ETFs subtotals in each portfolio, Shares and ETFs tables in each
  watchlist. Watchlist triggers for ETFs are price at or below and yield above; margin of
  safety triggers are for shares only.
- **What it holds:** each ETF's description, asset mix, top 10 holdings and sector weightings (and
  credit ratings and duration for bond funds) from Yahoo Finance, refreshed weekly; LICs show their
  description. To fetch every fund now: `python -m src.etf.run_etfs --skip-report --profiles-all`.

**LICs** (listed investment companies and trusts, such as AFI, ARG, WAM) come from the same
ASX report's LIC sheet and have their own **LICs** heading, apart from shares and ETFs: an LIC
screener sorted by discount to net tangible assets (NTA), a page per LIC with NTA history,
and LIC sections on the dashboard, in portfolios and in watchlists (with a "discount to NTA of
at least X%" trigger). An LIC in `allords.txt` moves out of the share screener the first time
the report loads; the ETF step fetches its prices. See docs/AS_BUILT.md §27.

**LICs page empty?** The report has to be loaded by the current version of Sift. After a
`git pull`, restart `gui.py` and run `python -m src.etf.run_etfs` with the report saved in
`data\asx_reports\`: a month loaded by an older version is loaded again automatically.
Keep each month's file there (any of `...-aug-2026-abs.xlsx`, `...-july-2026-abs.xlsx` style
names work): every month in the folder is loaded, which gives the fund size and NTA charts
their history.

How the data is collected:

- **Which ETFs, and their fund facts** (issuer, category, fees, size, flows, spread, the
  ASX's own performance figures) come from the ASX Investment Products report, a spreadsheet
  the ASX publishes monthly. The nightly job loads last month's report as soon as it's out:
  it looks in `data/asx_reports/` first, then downloads it from the ASX website.
- **Prices and distributions** come from Yahoo Finance nightly, with each ETF's full history
  the first time it's seen (the first night takes 10 to 15 minutes longer than usual).
- **Performance** is Sift's own total return with distributions reinvested, for 1, 3 and 6
  months, 1, 3, 5 and 10 years and since first price (yearly rates beyond a year), plus the
  trailing 12-month yield. Each month it's checked against the ASX's figure.
- ETFs aren't valued or scored like companies, so they don't appear in the share screener.

**First run, on your PC.** Download the latest spreadsheet from the
[ASX report page](https://www.asx.com.au/issuers/investment-products/asx-investment-products-monthly-report)
into `data\asx_reports\`, then:
```
pip install -r requirements.txt                                     # adds openpyxl, to read the spreadsheet
python -m src.apply_schema                                          # add the ETF tables now
python -m src.etf.run_etfs --inspect data\asx_reports\<file>.xlsx   # check how it's read; loads nothing
python -m src.etf.run_etfs                                          # load it, backfill prices, performance
```
`--inspect` lists every column and what it was matched to. If something important shows
"(kept in raw only)" or "Not found", that heading needs adding to `match_field()` in
`src/etf/asx_report.py`; keep the output to work from.

**If the download stops working**, save the spreadsheet into `data\asx_reports\` by hand;
the next nightly run picks it up. Or load it straight away with
`python -m src.etf.run_etfs --report <file>` (add `--month 2026-09` if the file name
doesn't include the month).

**Price history is now stored as traded.** Until now Yahoo's prices were stored with past
dividends taken off a month at a time, leaving a small step at each ex-date. New prices are
stored as traded. To clean the existing share history once (a few minutes):
`python -m src.ingestion.run_ingestion --tickers-file allords.txt --prices-only --period 2y`

## Recording Your Holdings (CGT)

Record trades in the browser (Sift's Portfolios pages, above) or with `portfolio.py`; both
use the same records and rules. Each parcel is kept separately, since Australian CGT
(including the discount after 12 months) applies per parcel. Brokerage is included in the
cost base.

**Portfolios.** Every parcel belongs to a portfolio with its owner's tax type: individual or
trust (50% discount), self-managed super fund (33⅓%) or company (none). Existing parcels
moved into "My portfolio" (individual) automatically. With one active portfolio there is
nothing to choose; with several, name one with `--portfolio` on `add` and `sell` (`list` and
`cgt` show every portfolio, each with its own discount, unless you name one).

```bash
python portfolio.py portfolios                                   # list them
python portfolio.py portfolios create "Super fund" --tax-type SMSF
python portfolio.py portfolios archive "Old account"             # once everything in it is sold
python portfolio.py add BHP --units 100 --price 42.50 --date 2025-03-14 --portfolio "Super fund"
python portfolio.py undo-sale 5e6f7a8b                           # reverse a sale entered by mistake
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
`pg_dump -t holdings -t portfolios asx_value > holdings_backup.sql`.

## AI assistants and the graph (optional)

Sift is ready for AI assistants and knowledge graphs; PostgreSQL stays the source of truth.

- **Ask Claude about your data:** install the optional package, then add Sift to Claude Desktop
  (Settings, Developer, Edit Config, `mcpServers`):
  ```
  .venv\Scripts\pip install -r requirements-ai.txt
  "sift": {"command": "C:\\Users\\you\\Portfolio\\.venv\\Scripts\\python.exe",
           "args": ["-m", "src.ai.mcp_server"], "cwd": "C:\\Users\\you\\Portfolio"}
  ```
  Restart Claude Desktop and ask, for example, "Using Sift, how is my portfolio going?", "Why is
  BHP a BUY?", "Which funds hold BHP?" or "How much do VAS and IOZ overlap?". The connector is
  read-only, runs on your PC and acts for you (the owner; `--user <email>` for another account).
- **Neo4j:** each night (or `python -m src.graph.export`) Sift writes `data/graph/`: CSV files
  for companies, sectors, fund categories, managers, holders, who holds what, what each ETF
  holds, and your portfolios and watchlists, plus `load.cypher`. Copy the CSV files into a Neo4j
  database's `import` folder and run `load.cypher` in Neo4j Browser. `--shared-only` leaves out
  your personal data. The folder is ignored by git.

Details, example questions and Cypher: the developer knowledge base, "AI and graph readiness".

## Testing

```bash
pip install -r requirements-dev.txt
pytest                  # runs both tiers below
pytest tests/unit       # pure functions + compute_metrics() - no database needed at all
pytest -m integration   # needs a local PostgreSQL instance (see below)
```

Two tiers, 556 tests in all:

- **`tests/unit/`** (426 tests) - no database connection at all, so these run in about a
  second: the valuation formulas and `compute_metrics()`, decision markers, suggested actions,
  the score wheel, dividend history and currency conversion, franking, CGT arithmetic
  (including the discount by tax type), browser input checks and the cross-site write guard,
  watchlist triggers, the dashboard's log reading and stale-data rule, the settings registry
  (live values pinned, guard rails), reading the ASX ETF report (two layouts), ETF total
  returns and the ETF page's figures, and the knowledge base behind the Help page (one check
  per entry).
- **`tests/integration/`** (130 tests) - the parts that genuinely need a real database: the
  schema (re-applied, upgraded from an older version, and built from nothing), ingestion
  upserts, valuation, the screener's SQL against the real view, portfolios and parcels, the
  web API end to end (screener, company, dashboard, portfolios, trades, watchlists, password
  and same-page guards), signal recording, track record scoring against 13 months of
  made-up history, and the admin console (a scenario with no changes matches live exactly,
  workings match the engine), and ETFs (loading reports, kept out of the screener, backfill,
  splits, performance, and shown apart from shares in every page), and LICs (NTA premium, sections,
  trigger rules). `tests/conftest.py` creates an `asx_test` database and applies
  `db/schema.sql` automatically on first run (set `TEST_DATABASE_URL` to point at a
  different instance) - it never touches whatever database your `.env` points at.

If no PostgreSQL instance is reachable, `tests/integration/` skips with a clear
reason rather than failing - `tests/unit/` is completely unaffected either way.

Several tests pin real historical figures from this project's own bug history
(SUN's FCF averaging, TWR's payout ratio, BRN/WHI's numeric overflow values -
see docs/AS_BUILT.md §10.12) as regression fixtures, not synthetic approximations.

## Daily Automation (Windows Task Scheduler)

`scripts/daily_refresh.ps1` runs the full pipeline unattended, in order:
schema update → ingestion → ETFs → valuation → signal record → track record scoring → screener → search index, logging everything to a timestamped file
under `logs\` (pruned automatically after 30 days). Each step's heading in the log shows when it
started, and a line after it says how long it took.

Prices are fetched for every share every night. Annual statements, analyst ratings and holders
change far less often, so each night refreshes the seventh of the shares fetched longest ago
(`--weekly-fundamentals`), and every share is refreshed about weekly. A normal night takes about
40 minutes (shares, then about 550 ETFs and LICs); without the weekly refresh it would be over an
hour. The first run after a big update (new ETFs and LICs, a backfill) takes longer. Each step runs even if
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
   - **General**: name it e.g. `ASX Refresh`; select "Run whether user is
     logged on or not" if you want it to run even when locked out (it then
     runs without a window at all).
   - **Triggers** → **New**: Daily, start time after ASX close with a
     buffer for Yahoo Finance data to settle — **6:00 PM** local time is a
     reasonable default.
   - **Actions** → **New**:
     - Program/script: `powershell.exe`
     - Add arguments: `-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\Users\mrdav\Portfolio\scripts\daily_refresh.ps1"`
       (`-WindowStyle Hidden` keeps the run out of sight, so it can't be closed by accident:
       closing the window kills the run partway, result `0xC000013A`)
   - **Conditions**: untick "Start the task only if the computer is idle" and
     "Stop if the computer ceases to be idle" (with these on, touching the mouse
     ends the run). Untick "Start the task only if the computer is on AC power"
     if this runs on a laptop that may be on battery.
   - **Settings**: tick "Run task as soon as possible after a scheduled
     start is missed" so a missed run (machine off at 6pm) catches up next
     time it's on, and set "Stop the task if it runs longer than" to 4 hours.
   To apply all of these to an existing task in one go, run this in PowerShell as
   administrator (change `ASX Refresh` if you named it differently):
   ```powershell
   $t = Get-ScheduledTask 'ASX Refresh'
   $t.Settings.RunOnlyIfIdle = $false
   $t.Settings.IdleSettings.StopOnIdleEnd = $false
   $t.Settings.ExecutionTimeLimit = 'PT4H'
   $t.Settings.StartWhenAvailable = $true
   $t.Actions[0].Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\Users\mrdav\Portfolio\scripts\daily_refresh.ps1"'
   Set-ScheduledTask -InputObject $t
   ```
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
