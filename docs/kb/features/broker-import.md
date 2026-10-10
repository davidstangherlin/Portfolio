---
id: broker-import
title: Importing from a broker, and printing
category: features
summary: How a broker's CSV or Excel export (trade history or holdings) becomes parcels in a portfolio, recognising each broker's columns with a preview to confirm; and how any page prints or saves as PDF on A4 landscape.
version: 1.0
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-01-10
source: AS_BUILT change log, 2026-10-10
related: [portfolios-cgt, web-gui]
code: [src/portfolio/importer.py, gui.py, web/app.js, web/style.css]
tables: [holdings, portfolios]
---

## Purpose

Let people bring their real portfolios into Sift from the brokers they use (asked for 2026-10-10: Moomoo, CommSec, Sharesies, nabtrade, CMC Invest, Tiger, ANZ, Interactive Brokers, eToro and other popular platforms), and print or save any page as a PDF on A4 landscape.

## How it works

**One reader for every broker** (`src/portfolio/importer.py`). Brokers name columns differently and change them, so instead of a parser per broker the importer reads the headings: `FIELDS` lists the names known for each field (code, side, units, price, average cost, total cost, date, brokerage, market, currency, details, debit, credit). `find_header()` finds the heading row among the first 40 (statements often start with account details); `guess_mapping()` matches columns; `detect_broker()` names the broker from its signature headings (`BROKERS`, which also holds a line on where to export). Particular cases: CommSec's transaction file, whose Details read "B 100 BHP @ 45.000000" and whose Debit and Credit include brokerage (worked out as the difference, if it's plausible); Interactive Brokers' activity statements, whose rows start "Trades,Header" and "Trades,Data" (`_ibkr_trades()`) and whose quantities are signed. Files: CSV (any delimiter, UTF-8 or Windows encodings) and Excel .xlsx (the sheet with most rows), up to 3 MB and 5,000 lines; the browser sends the file as base64 in JSON, so no upload library is needed.

**Two kinds of file.** A trade history (a date with a side or price, or CommSec details) gives each buy and sale with its date, price and brokerage. A holdings snapshot (no dates) gives code, units and average cost (or total cost divided by units), with one bought-on date the person gives (it decides the CGT discount). The person can switch the kind and correct any column.

**What comes in.** `to_lines()` reads each row: codes cleaned (BHP.AX, ASX:BHP), Australian day-first dates and the other common formats, numbers with $ and brackets, sides (B, Buy, BOUGHT, S, Sell). Skipped, with the reason shown: lines on another market (a market column that isn't the ASX, a code suffix such as .US) or in another currency; dividends, deposits and fees; lines without a code, units, price or readable date; future dates. A code Sift doesn't know is marked Check the code and left unticked. A line already in the chosen portfolio (same code, side, date, units and price, adding back parcels split by sales) is Already in Sift, so importing twice adds nothing.

**Preview, then import.** `POST /api/portfolios/import/preview` saves nothing and returns the headings, the mapping, the kind, each line's status and the counts. `POST /api/portfolios/import` (through `change()`, one transaction) imports the ticked lines into the chosen portfolio or a new one (name and tax type): buys as parcels (`add_parcel`, broker and file row noted), then sales in date order first in, first out (`holdings.sell`, each in a savepoint so a sale with nothing to sell is reported, not fatal). Both act only on the current person's portfolios (`get_portfolio`).

**The page** (`#/portfolios/import`, Import from a broker on Portfolios): 1. choose the file and (optionally) the broker; 2. what was found, Trade history or Holdings now, the bought-on date for holdings, Columns; 3. where to put them; then the lines with tick boxes and statuses, and Import ticked lines.

**Printing.** Print or save as PDF in the avatar menu (or Ctrl+P). `@media print` in `web/style.css`: `@page { size: A4 landscape }`, the menu bar, buttons, filters, dashboard tools and admin editors hidden, cards kept whole where they fit, colours kept. On `beforeprint` the page switches to the light theme, adds a heading line (page, subtitle and time printed) and redraws the charts; `afterprint` restores them.

## Code map

- `src/portfolio/importer.py`: reading files, finding columns, each line's status, preview and import
- `gui.py`: the preview and import routes
- `web/app.js`: `renderImport()`; the beforeprint and afterprint handlers
- `web/style.css`: the import page; `@media print`

## Data

- `holdings`: imported parcels, with broker and a note naming the file and row
- `portfolios`: a new portfolio when the person names one

## Diagnosing problems

- A broker's file isn't recognised: open Columns and choose them; then add its headings to `FIELDS` (and a signature to `BROKERS`) with a test (IMP-065).
- Dates come in a month out: the file uses month-first dates; `parse_when()` reads day first, as Australian brokers write them.
- A sale "couldn't be added": nothing to sell in that portfolio on that date (the buys weren't imported, or came earlier from another broker).

## Known limits

- The broker layouts were built from their usual column names, not their real files: each broker is proven by its first real export (IMP-065).
- Only ASX shares; corporate actions (splits, consolidations, takeovers) aren't read from exports and are entered by hand.
- Old .xls files must be saved as .xlsx or CSV first.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_importer.py`
- `tests/integration/test_broker_import.py`
