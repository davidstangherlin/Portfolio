---
id: web-gui
title: Sift web app: pages, dashboard and layout
category: features
summary: How the FastAPI server and the plain JavaScript pages fit together: routes, the dashboard and its arrangeable widgets, company pages, charts, phone layout and the house UI rules.
version: 1.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §20
related: [architecture, profile-preferences-impersonation, table-filters, adr-002-fastapi-plain-js]
code: [gui.py, web/index.html, web/app.js, web/style.css, web/dashlayout.js, web/tablefilter.js]
tables: [ui_preferences]
---

## Purpose

Sift's pages are how people use everything else. The server returns JSON; one JavaScript file builds every page, so there is no build step and nothing loads from other sites.

## How it works

**Purpose.** A browser view of the screener, Simply Wall St style: a filterable table of every company and a page per company with a score wheel, valuation, quality markers and charts. Usable from a phone on home Wi-Fi. Writes only portfolios and trades ([§19.1](kb:portfolios-cgt)).

**Architecture.**
- `gui.py`: FastAPI app run by uvicorn. `GET /api/screener` (every row, trimmed to the fields the table needs, plus five axis scores) and `GET /api/company/{code}` (the full row, the 30 checks, the four tests with thresholds, red flags, position, 365 days of prices, margin-of-safety history and up to 5 FY reports). `/` and `/static/*` serve `web/`.
- Added with the dashboard (stage 1): `GET /api/dashboard`, `GET /api/status` (the data chip) and `GET /api/companies` (the search list); see "Menu bar and dashboard" below.
- Both endpoints call `screen_asx.load_annotated_rows()`, the same loader the CLI uses, so the browser and `screen_asx.py` can never disagree on a test, flag or action. Two extra `DISTINCT ON` queries add `roic`, `graham_number` and the latest FY report for the score wheel without a per-company query. Since stage 1 this enrichment lives in `src/screening/enriched.py` (`load_universe()`), shared with the signal recorder ([§21](kb:track-record)).
- `web/`: plain HTML, CSS and JavaScript, no framework, no build step, no CDN. Charts are inline SVG drawn at their real on-screen width (redrawn on resize) so text stays legible on a phone. All text is inserted with `textContent`. Hash routing: `#/` dashboard, `#/screener` (optionally `?action=BUY,INVESTIGATE`, `?held=1` or `?watchlist=NAME` to open it pre-filtered), `#/company/BHP`, `#/portfolios` and `#/portfolio/{id}`, `#/watchlists` and `#/watchlist/{id}`, `#/track-record`, `#/help` (with `?q=` or `/{entry}`, [§23](kb:help-knowledge-base)); anything else goes to the dashboard.
- Charts follow the dataviz method: validated categorical palette (blue/orange, checked light and dark), 2px lines, hairline grid, one axis per chart, legend only for two or more series, crosshair or per-bar tooltips, a data table under every chart, and light and dark themes.

**Field explanations.** The text comes from `web/knowledge.json` ([§23](kb:help-knowledge-base)), loaded before the first page draws. Every screener column heading, every label in the company page's markers and key-ratios panels, and the three bar labels in "Price against estimated value" (share price, estimated value, Graham Number) carries a plain-English explanation (what it measures, the formula, and the pass threshold, read from the live thresholds so it can't drift from the rules). `withHelp()` in `app.js` shows it on mouse hover and keyboard focus; on touch screens a small "i" button shows it on tap without triggering the column sort. With a mouse the "i" buttons are hidden and headings get a dotted underline instead, which keeps the table within a 1280px screen. The estimated value explanation follows the company's model (DCF or DDM, with its growth, terminal and discount rates); labels inside SVG charts use `svgLabelHelp()`, with an SVG "i" for touch screens.

**Score wheel (`scores.py`).** Five axes, six yes/no checks each; the score per axis is the count passed (0-6). A check is True, False or None (no data), and None never counts as a pass. Thresholds reuse the screener's own where one exists.

| Axis | Checks |
|---|---|
| Value | margin of safety > 0; > 20%; > 40%; P/E between 0 and 15; P/B between 0 and 1.5; price below Graham Number |
| Performance | ROE > 12%; ROE > 20%; ROIC > 10%; fundamentals not DECLINING; earnings quality STRONG or ADEQUATE; earnings quality STRONG |
| Health | debt/equity < 0.8; < 0.4; cash ≥ total debt; positive equity; positive free cash flow; positive net profit |
| Dividend | pays a dividend; grossed-up yield > 4.5%; > 6%; payout ratio ≤ 100%; dividend trend STEADY or GROWING; GROWING |
| Momentum | price signal UPTREND; not NEW LOWS; in upper half of 52-week range; margin-of-safety trend > 0; momentum_ok; fundamentals IMPROVING |

The wheel describes; it does not decide. The suggested action still comes only from [§9.1](kb:screener-actions)'s rules.

**Start-up.** `main()` applies `db/schema.sql` before serving (`prepare_database()`), so a `git pull` followed by a GUI restart can't leave the pages failing until the nightly run. An unexpected error on any route is logged with its traceback and returned as a readable `detail` (`error_message()`), which the page shows after "Could not load".

**Security.** Default host `127.0.0.1` (this PC only). `--lan` binds `0.0.0.0` and refuses to start unless `GUI_PASSWORD` is set. When set, middleware requires HTTP Basic auth (any username, constant-time password compare) on every route including static files; a malformed header is a 401, not an error. The only writes are portfolios and trades, and they must also come from Sift's own pages ([§19.1](kb:portfolios-cgt)). Known-issue #23 covers plain HTTP on the LAN.

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

**Action colour (2026-10-09).** One rule for every button, at the user's request ("keep all action buttons consistent"): pink (`--action`, the `--twisty` token) means *do something*, blue (`--accent`) means *go somewhere* (links), red means delete (`.btn.danger`). Main buttons (`.btn.primary`: Search, Add, Create watchlist, Save) are solid pink; secondary buttons (`.btn`: Rebuild, + Add condition, Show all) have pink text; icon buttons (search, scope ▾, settings gear, ✕, dashboard ↑ ↓ and Hide, the ☆ watchlist star, thumbs, pins, twisties, Filter) are pink at rest with a soft pink hover (`--action-soft`); Show more and "+ New watchlist" are pink. The small help "i" icons stay grey until hovered so headings aren't crowded; chips and segmented controls are toggles, not actions, and keep their neutral style; count buttons keep their green and red. White on pink measures 4.6:1 (AA) in light mode; dark text on the lighter pink in dark mode. The rule is one block at the end of `web/style.css` ("Action colour"), and `CLAUDE.md` tells future changes to use the classes or tokens rather than raw colours.

**Run it.** See README, Web GUI: `python gui.py`, or `python gui.py --lan` with `GUI_PASSWORD` and a one-off firewall rule for phone access.

**Menu bar today (2026-10-09).** Dashboard | Screener ▾ (ASX Stocks, ETFs, LICs) | Watchlists ▾ | Portfolios ▾ | Track record | Coattail | Markets ↗ ▾, then the search box, the data chip, the avatar menu and a ? icon for Help (`#help-btn`, `.icon-btn.help-btn`, outlined while on Help). The share screener's page is titled ASX Stocks; its address stays `#/screener` so bookmarks and the `g s` shortcut still work. `markCurrent()` marks the open page inside its dropdown and underlines the heading it sits under (`NAV_GROUPS`: ETF and LIC detail pages count as ETFs and LICs). The original stage 1 design follows.

**Menu bar and dashboard (stage 1, 2026-10-05).**
- **Menu bar:** Dashboard | Screener | Watchlists ▾ | Portfolios ▾ | Track record | Markets ↗ ▾, then a company search, the data chip and the settings gear. The current page has a pink (`--twisty`) underline; a company page highlights nothing. Dropdowns open on click (so they work on touch), close on Escape, an outside click or navigation, and only one is open at a time. Below 1060px the menu folds behind a ☰ button into a vertical panel (current page marked with a pink left bar). Markets links open in a new tab with `rel="noopener noreferrer"`: ASX, the ASX exchange traded products directory, NYSE and Nasdaq. Watchlists and Portfolios list each watchlist and portfolio, with All and + New links ([§19.1](kb:portfolios-cgt), [§22](kb:watchlists)).
- **Search:** a `<datalist>` of every screened code and name from `/api/companies`. Picking an entry, or pressing Enter, opens the company: exact code first, then code prefix, then name contains. No match shows a short tooltip.
- **Data chip (`/api/status`):** newest `valuation_metrics.as_of_date`, newest price date, and the latest `logs/refresh_*.log` parsed by `last_refresh()`. Stale when the newest valuation is older than the previous weekday (so Friday's data is current all weekend; a public holiday shows amber harmlessly). The log reader handles UTF-8 and UTF-16 (PowerShell) files and classifies a run as `ok`, `errors` (one or more ERROR lines: individual companies that failed, normal on most nights), `crashed` (a traceback with no ERROR line before it: a whole step died), `running` (unfinished and under 3 hours old) or `incomplete`. Amber, with a "!", only for stale data, `crashed` or `incomplete`, so routine Yahoo gaps don't train you to ignore it.
- **Dashboard (`/api/dashboard`):** one `load_universe()` call feeds: a portfolio strip (value at the latest close, today's change from the two latest closes, unrealised gain, cost base); Needs attention (held SELL/REVIEW with reasons, parcels reaching the CGT discount within 90 days, holdings not on the watchlist file); What changed ([§21](kb:track-record)); Biggest movers (`src/screening/movers.py`: the 5 screener shares, each with its score wheel, that rose and fell most by percentage from the previous close to the latest one, and the top 5 each way for ETFs and for LICs; only rows priced on the group's latest trading day count, so a suspended stock's weeks-old move isn't today's; no price or volume floor, by the user's choice of a pure percentage ranking); Top opportunities (up to six, BUY then INVESTIGATE, by score total then margin of safety; shares you hold are excluded because their actions are the held set); action counts linking to the pre-filtered screener; recording status; and a footer repeating the data status in full.
- **Portfolios:** the Portfolios menu lists active portfolios; with more than one, the dashboard adds a card listing each with its value and gain ([§19.1](kb:portfolios-cgt)).
- **Back link:** a company page's back link returns to the page you came from (dashboard, screener with its filters, holdings or track record), defaulting to the screener.

## Code map

- `gui.py`: the FastAPI app: middleware (password, same-site writes, who the request is from), every /api route, payload builders
- `web/index.html`: the page shell: menu bar, search box, avatar menu
- `web/app.js`: every page, chart and dialog
- `web/style.css`: tokens (light and dark), layout, the action colour rule
- `web/dashlayout.js`: dashboard widget arrangement
- `web/tablefilter.js`: table filters

## Data

- `ui_preferences`: per person: the dashboard layout and Preferences

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A page says 'Could not load: ...': the message is the server's; the full traceback is in the window running gui.py. See [A page shows an error](kb:rb-page-error).
- An open tab reloads by itself: the page files changed (a git pull); the X-Sift-Version header tells the page.

## Known limits

- Phone access over home Wi-Fi uses HTTP Basic authentication over plain HTTP (IMP-023) until hosting (Phase 4).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/integration/test_gui.py`
- `tests/unit/test_dashboard.py`
- `tests/unit/test_dash_layout.py`
- `tests/js/dash_layout.test.js`
