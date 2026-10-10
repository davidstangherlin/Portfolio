---
id: table-filters
title: Table filters
category: features
summary: The condition builder and chips shared by the screener, ETF and LIC lists, watchlists, portfolios and Coattail.
version: 1.2
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-10
next_review: 2027-01-09
source: AS_BUILT §30
related: [web-gui]
code: [web/tablefilter.js, frontend/src/lib/tableFilter.ts, frontend/src/components/TableFilter.tsx, frontend/src/components/FilterableTable.tsx]
---

## Purpose

One filter engine gives every table the same way to narrow rows, so people learn it once.

## How it works

Every list view can be searched and filtered by any column: the share screener, the ETF and LIC screeners, each watchlist's Shares, ETFs and LICs tables, and each portfolio's holdings tables. The existing quick filters (action chips, sector, category, issuer, watchlist, Held only, Passes all four tests) stay as they were; the table filter applies on top of them.

**Origin.** Ported from the user's `filter_component.py` (Streamlit and pandas) to plain JavaScript, keeping its design: one filter state per table, conditions as data (column, operator, value, join), a pure filtering function, removable chips, a pink button that opens the condition builder, and "Show matching" / "Filter out". Fixed in the port (each has a check in `tests/js/table_filter.test.js`):

| Issue in the original | Fix |
|---|---|
| Typed values stayed text, so `MoS > 20` compared a number with "20" | Number columns parse the value: `20`, `20%`, `-1.5`, `$1,234.50`, `1.2B`, `300k` |
| "between" had one input but expected two values | Two inputs; either end may be left open |
| A list of values could only be set in code | Comma-separated values are a list (`BHP, RIO`); a value picked by right-click stays one value, commas and all |
| "Show matching" on a blank cell matched nothing | A blank cell offers "is empty" / "is not empty" |
| "Show matching" replaced every condition on the column and appended with AND, rewriting OR chains | Replaces only a lone AND condition on that column; otherwise adds one |
| Search matched raw stored values | Search matches the text as shown in every column (so "60%" finds a stored 60) |

**Behaviour.**
- **Search box** (replacing each screener's old code-or-name search): rows whose shown text in any column contains the typed text. The ETF and LIC screeners also search the benchmark and issuer.
- **Filter button** (pink; filled, with a count, while conditions apply): the builder. Each row is column, condition and value. Conditions offered depend on the column: text columns get equals, does not equal, contains, does not contain, is empty and is not empty; number columns also get greater than, less than and between. Text values suggest the column's own values. Conditions apply top to bottom with no brackets: A AND B OR C means (A AND B) OR C, which the builder states. A condition still being typed has a dashed chip and is skipped rather than emptying the table.
- **Right-click a cell** (press and hold on a phone; the menu key on a focused row uses the first column): Show matching, Filter out, and for numbers Greater than and Less than that value. The tap that ends a press and hold doesn't open the row.
- **Chips** under the controls: one per condition, click to remove, and Clear all.
- **Memory.** Each table keeps its filters until the page reloads (`TF_STATES`, keyed by table: `screener`, `ETF`, `LIC`, `watch:<id>:<type>`, `portfolio:<id>:<type>`). A link that presets a screener (from the dashboard) clears that screener's table filters, so it shows what the link says.
- **Small tables.** A watchlist or portfolio table with one row shows no filter controls.

**Structure (React, since 2026-10-10).** The screener and the ETF and LIC lists use the TypeScript port: `frontend/src/lib/tableFilter.ts` (the pure rules, with the same checks in `tableFilter.test.ts`, and `filterState(key)` and `forgetFilters(key)` for each table's memory) and `useTableFilter()` in `frontend/src/components/TableFilter.tsx` (the search box, toggle, builder, chips and the right-click or press-and-hold menu, given to the `<table>` as `tableProps(columns, shownRows)`). Fields are `FIELDS` in `ScreenerPage.tsx` and `fieldsFor(kind)` in `pages/funds/FundsPage.tsx`. Watchlists and portfolios use it too, through `FilterableTable` (`frontend/src/components/FilterableTable.tsx`, the React `filterableTable()`). Only Coattail's holders still use the plain JavaScript below until they move (IMP-084).

**Structure (plain JavaScript).** `web/tablefilter.js` loads before `app.js`. The pure part (`tfNumber`, `tfReady`, `tfTest`, `tfApply`, `tfUpsert`) runs in Node for tests; the controls use `app.js`'s `h()`. Pages describe their columns as fields (`label`, `type` num or text, `get` the value, `text` the value as shown): `WATCH_SHARE_FIELDS`, `fundWatchFields(kind)`, `holdingFields(kind)`. Coattail's holders call `tableFilter()` inside their own refresh; watchlists and portfolios use `filterableTable()`, which redraws the table on each change. Help: "Filtering a table" (`table-filters`).

**Tests.** `tests/js/table_filter.test.js`, run by `tests/unit/test_table_filter.py` (skipped without Node), and `frontend/src/lib/tableFilter.test.ts` with the same checks for the TypeScript port; `ScreenerPage.test.tsx` uses the builder. A browser check covered every table at desktop and phone widths, including a press and hold on a phone.

## Code map

- `frontend/src/lib/tableFilter.ts`, `frontend/src/components/TableFilter.tsx`: the React version (screener, ETFs, LICs)
- `frontend/src/components/FilterableTable.tsx`: a whole filterable table (watchlists, portfolios)
- `web/tablefilter.js`: the evaluator, the bar, the builder, chips and the column menu (Coattail holders, until it moves)

## Data

No tables of its own.

## Diagnosing problems

- A filter gives no rows unexpectedly: check the chips; conditions combine with AND.

## Known limits

- Filters aren't saved between visits.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_table_filter.py`
- `tests/js/table_filter.test.js`
