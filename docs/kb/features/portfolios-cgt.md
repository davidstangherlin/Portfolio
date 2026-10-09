---
id: portfolios-cgt
title: Portfolios, parcels and CGT records
category: features
summary: Parcel-level holdings across several portfolios, each with its owner's tax type: buys, sales with parcel splitting, FIFO or minimum-tax order, archiving and the CGT report.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §19
related: [accounts-owners, screener-actions, web-gui]
code: [src/portfolio/holdings.py, src/portfolio/cgt.py, src/portfolio/views.py, src/portfolio/trade_input.py, portfolio.py]
tables: [portfolios, holdings]
---

## Purpose

Portfolios keep the records a person needs at tax time and tell the screener what is held, which changes the suggested action (HOLD, SELL, ACCUMULATE, REVIEW).

## How it works

**Purpose.** Lets the screener know what you own (so held companies get SELL / REVIEW / ACCUMULATE / HOLD rather than buy-side actions, [§9.1](kb:screener-actions)) and keeps the records Australian CGT needs. User choice: a database table rather than a file, with tax-relevant fields and anything else useful for record keeping.

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

**Limits (IMP-019).** Not tracked: dividend income and franking credits, losses carried forward from earlier years, and cost base adjustments from corporate actions (returns of capital, bonus/rights issues, consolidations, demergers). A record-keeping aid to reconcile against broker statements, not tax advice.

**Back it up.** Unlike market data, holdings can't be re-downloaded. The teardown command in [§12](kb:setup-and-configuration) deliberately leaves the table alone, and a periodic `pg_dump -t holdings -t portfolios asx_value > holdings_backup.sql` keeps a copy outside the database.

### Portfolios and Trade Entry in the Browser (stage 2, added 2026-10-05)

**Purpose.** Hold several portfolios (for example your own shares, a family trust and a self-managed super fund), each taxed as its owner is, and record trades in Sift instead of only at the command line.

**Model.** `portfolios` (name, unique ignoring case; `tax_type`; `archived_at`). Every parcel has a `portfolio_id`. The schema migration creates "My portfolio" (individual) and moves existing parcels into it, only when there are parcels without a portfolio, then makes the column `NOT NULL`; re-running it changes nothing. On a fresh database the first `add_parcel()` creates "My portfolio".

**Tax type sets the CGT discount (`cgt.DISCOUNT_RATES`).** Individual 50%, trust 50% (passed through to beneficiaries), complying super fund including SMSF 33⅓%, company 0%. It drives the FY summary (`summarise(..., discount_rate)`), `min-tax` sale ordering, and whether a parcel ever waits for a discount date: company parcels never do, so they're left out of `next_discount_date`, the screener's "consider timing any sale" reason ([§9.1](kb:screener-actions)) and the dashboard's CGT reminders. Changing a portfolio's tax type re-rates the sales already recorded in it (the settings form warns when there are any).

**Rules.**
- **Choosing a portfolio:** a function given no portfolio uses the only active one; with several it refuses and names them (`portfolio.py --portfolio NAME`).
- **Sales stay inside a portfolio:** `sell()` only draws on that portfolio's parcels, and a split-off sold portion keeps the portfolio.
- **Archive** needs every parcel sold; an archived portfolio refuses new trades, leaves the menu and dashboard, and keeps its sales in the CGT report. Unarchive reverses it.
- **Delete** removes the portfolio and its open parcels, and is refused once it has any sale, because the ATO expects records kept for five years after each sale: archive instead.
- **Undo sale** (`undo_sale()`): a sold portion split from a still-open parcel goes back into it (units and buy brokerage restored, so the cost base is exact again); otherwise the parcel reopens. Delete is only for open parcels entered by mistake.
- **Held means held in any portfolio:** suggested actions ([§9.1](kb:screener-actions)) treat a company as held when any active portfolio holds it.

**Browser (`gui.py`).** `GET /api/portfolios` (each with totals; `?brief=1` names only, for the menu), `POST /api/portfolios`, `GET|PATCH|DELETE /api/portfolios/{id}` (detail; rename, tax type, archive or unarchive; delete), `POST /api/portfolios/{id}/buys`, `POST /api/portfolios/{id}/sales`, `DELETE /api/parcels/{id}` (open parcels only), `POST /api/parcels/{id}/undo-sale`. Each change runs in one transaction; a rule broken is a 400 with a plain-English message (`trade_input.py` checks codes, numbers, decimal places within the column sizes, and that the date isn't in the future), and nothing is half-saved. Pages: `#/portfolios` (a card per portfolio, archived ones folded away, and a create form; `?new=1` jumps to it) and `#/portfolio/{id}` (summary strip, holdings, Record a trade, Settings, Open parcels, Sales, Capital gains by financial year). Deleting a parcel or portfolio, undoing a sale and archiving all ask for confirmation first.

**Write protection.** The same password as viewing. Because a browser sends saved Basic-auth credentials with any site's request, a password alone wouldn't stop another website's page posting to Sift, so every POST, PATCH, PUT or DELETE must also pass `_same_site_write()`: the `X-Sift: 1` header that Sift's own script adds (another site can't add a custom header without a CORS permission Sift never grants), `Sec-Fetch-Site` same-origin when the browser sends it, and an `Origin` whose host matches. Anything else gets a 403 before reaching a route.

**CLI.** `portfolio.py portfolios [list|create|archive|unarchive] [NAME] [--tax-type ...]`, `--portfolio/-p` on `add`, `sell`, `list` and `cgt`, and `undo-sale PARCEL`. `list` and `cgt` show every portfolio separately, each `cgt` report at its own discount rate.

## Code map

- `src/portfolio/holdings.py`: portfolios and parcels: add, sell with splitting, undo, archive, positions; scoped to the current person
- `src/portfolio/cgt.py`: Australian CGT arithmetic, discount by tax type, financial-year summary
- `src/portfolio/views.py`: portfolio figures for the pages
- `src/portfolio/trade_input.py`: checks on trades typed in the browser
- `portfolio.py`: the command-line tool

## Data

- `portfolios`: per person (owner_id); name unique per person; tax type sets the CGT discount
- `holdings`: one row per parcel; a partly sold parcel is split, the sold part pointing back with split_from_id

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A sale is refused for too few units: only parcels bought on or before the sale date in that portfolio count.
- Someone sees 'No such portfolio' for a link: portfolios are per person; check who they are signed in as.

## Known limits

- Covers CGT on share parcels only; dividends, franking credits, carried losses and corporate actions aren't modelled (IMP-019).
- Parcels can't be moved between portfolios (IMP-027).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_cgt.py`
- `tests/unit/test_trade_input.py`
- `tests/integration/test_portfolio.py`
