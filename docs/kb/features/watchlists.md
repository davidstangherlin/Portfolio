---
id: watchlists
title: Watchlists and triggers
category: features
summary: Named lists of companies, ETFs and LICs to follow, each entry with a note and triggers (margin of safety, price, yield, NTA discount).
version: 1.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-10
next_review: 2027-01-09
source: AS_BUILT §22
related: [accounts-owners, web-gui]
code: [src/watchlist/lists.py, frontend/src/components/watch.tsx]
tables: [watchlists, watchlist_items]
---

## Purpose

Watchlists let a person follow companies without owning them and be told on the dashboard when one becomes interesting.

## How it works

**Purpose.** Follow companies without owning them, in as many named lists as you like, with a reason and a price or value level for each, so the dashboard says when one gets there.

**ETFs and LICs (added 2026-10-06, [§26](kb:etfs-presentation), [§27](kb:lics)):** watchlists hold ETFs and LICs too, each under its own heading; LICs add a discount to NTA trigger (`nta_discount_above`). ETFs:, shown under their own heading, with a yield trigger for ETFs (`yield_above`); a margin of safety trigger is for shares only.

**Model.** `watchlists` (name, unique ignoring case and repeated spaces) and `watchlist_items` keyed `(watchlist_id, company_id)`: optional `note` (up to 500 characters), `mos_above` (percent, may be negative) and `price_below` (above zero). Both foreign keys cascade, so deleting a list deletes its entries and nothing else. Entries reference `companies`, so only companies Sift values can be watched; adding any other code is refused with a pointer to the nightly ticker file (`allords.txt`). That file and these lists are different things: the file decides what gets valued, a list decides what you follow.

**Triggers (`triggers()`).** Judged against the screener's own row for the company: margin of safety **strictly above** `mos_above`, latest close **at or below** `price_below`. A company with no current value or price meets neither. An entry is "triggered" while any trigger is met; it's a live state, not a stored event (IMP-028).

**Where watchlists show.**
- **Watchlists pages:** `#/watchlists` (a card per list with company and trigger counts, and a create form; `?new=1` jumps to it) and `#/watchlist/{id}` (entries, triggered first, with score, price, margin of safety, valuation, action, each trigger ticked or not, and the note; one form adds a company or, via Edit, updates its note and triggers; rename and delete).
- **Company page:** "☆ Add to watchlist" opens a panel ticking every list the company is on; ticking adds, unticking removes straight away (no confirmation, at the user's request; the entry's note and triggers go with it), and naming a new list creates it with the company on it. A line under the strip names the lists and whether a trigger is met.
- **Screener, ETF and LIC lists:** a star at the left of every row: ☆ when it's on no list, a pink ★ when it is (hover for the list names). Clicking it (or Enter) opens the same picker as the company page, floating under the star (a fixed panel on phones), without opening the row; Escape or a click elsewhere closes it. Changes update the star in place and the Watchlists menu. The star column isn't sortable or filterable, and right-click stays the filter menu. Plus a filter: any watchlist, or one by name (`#/screener?watchlist=NAME` presets it). The ETF and LIC list APIs send each watchlist's id for this.
- **Dashboard:** triggered entries join Needs attention with the list, the trigger and the note; What changed lists watchlist companies first, then better moves first.
- **Menu:** the Watchlists dropdown lists every watchlist, plus All watchlists and + New watchlist.

**API.** `GET /api/watchlists` (counts; `?brief=1` names only), `POST /api/watchlists` (optionally with `asx_code` to start it with that company), `GET|PATCH|DELETE /api/watchlists/{id}`, `PUT /api/watchlists/{id}/items/{code}` (add or update: the same call), `DELETE /api/watchlists/{id}/items/{code}`. The screener rows carry `watchlists` (list names), the company payload carries every list with membership, note and triggers, and the dashboard carries `triggered`. Writes go through the same password, same-page guard and one-transaction `change()` as portfolios ([§19.1](kb:portfolios-cgt)); rule breaks return a 400 with a plain-English message.


**The watchlist button and stars** (React since 2026-10-10: `frontend/src/components/watch.tsx`). The company and fund pages' Add to watchlist button and picker (`WatchButton`, `WatchPicker`, `WatchNote`) and the star on each row of the screener and fund lists (`WatchCell`, which floats the same picker under the star; Escape or a click elsewhere closes it, and Enter in its form never opens the row).
## Code map

- `src/watchlist/lists.py`: lists, entries and triggers; scoped to the current person

## Data

- `watchlists`: per person; name unique per person
- `watchlist_items`: one company on one list, with note and triggers

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A trigger shows then disappears: triggers are a state, true only while the condition holds (IMP-028).

## Known limits

- Nothing is sent when a trigger is met (IMP-028).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_watchlist_triggers.py`
- `tests/integration/test_watchlists.py`
