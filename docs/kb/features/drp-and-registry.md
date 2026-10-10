---
id: drp-and-registry
title: Dividend reinvestment and share registries
category: features
summary: The company page's Dividend reinvestment (DRP) card (shares needed for the dividends to buy a whole new share) and Share registry card (who runs the register, with a link to its investor portal), and how each company's registry is found.
version: 1.1
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-01-10
source: AS_BUILT change log, 2026-10-10
related: [web-gui, ai-and-graph]
code: [src/drp.py, src/registries.py, gui.py, web/app.js]
tables: [companies, dividend_payments]
---

## Purpose

For dividend payers, show how many shares it takes for a dividend reinvestment plan (DRP) to buy whole new shares, and for every share, which registry to log in to for the DRP and the holding itself. Asked for by the user on 2026-10-10, with plain help on how DRPs treat leftover cash.

## How it works

**Dividend reinvestment card** (`src/drp.py` `drp_payload()`, in the company payload as `drp`; `dividendReinvestCard()` beside Dividends per share). From `dividend_payments` (ordinary payments only: one-off, abnormal payments are left out as everywhere in Sift) and today's price:

- *1 new share each payment*: price divided by the latest ordinary dividend per share, rounded up, with what that holding is worth.
- *1 new share a year*: price divided by the ordinary dividends with ex-dates in the last 12 months, rounded up (the user chose the latest payment and the last 12 months over the last financial year).
- *Your shares* (when you hold it): how many new shares your units' dividends would buy each payment and a year.
- No ordinary dividend in 18 months (`STALE_DAYS`): the card isn't shown (the company isn't paying now).
- Franking credits don't count (a tax credit, not cash). The card's note says what people most need to know instead (owner's request, 2026-10-10): a DRP isn't automatic; dividends are paid in cash unless you join through the share registry, usually by the day after the record date. Hovers on the two figures and the help entry `drp` explain the sum, joining, and how DRPs handle leftover cash and pricing.

**Share registry card** (`src/registries.py`, in the company payload as `registry`; `shareRegistryCard()`). The registry's name, a link to its investor portal and its website (both open in a new tab), a note on what the registry does for a DRP with a link to the help entry, and where the registry came from. `REGISTRIES` lists the registries behind nearly every ASX company (Computershare, MUFG Corporate Markets (formerly Link), Automic, BoardRoom, Advanced Share Registry, Xcend) with a name pattern each; `match()` recognises a registry however it's written ("Link Market Services Limited" is MUFG). An unrecognised name is shown without links.

**Finding the registry.** Nightly step Share Registries (`python -m src.registries`, after ETFs): a batch of 120 shares (`BATCH`), those unchecked longest first, each checked about monthly (`CHECK_DAYS`). `lookup()` tries ASX's company details from ASX's data service and then the older ASX API, with a browser's fingerprint; `read_registry()` takes the value of any field whose key mentions the registry (a name inside it, or the text itself), else the first known registry named anywhere in the response. A company with nothing found waits a month. Stored on `companies` (`registry_id`, `registry_name`, `registry_source` asx or admin, `registry_checked_at`). `--dry-run` checks five and prints what ASX says; `--codes BHP CBA` checks given companies.

**Admin correction.** On the card, admins have Change (admin): pick a known registry, type another, or "Use what ASX says". `PUT /api/admin/company/{code}/registry` (`set_by_admin()`): an admin's choice is never overwritten by the nightly check; clearing it puts the company back in the queue.

**AI and graph.** The `company` tool returns `dividend_reinvestment` and `share_registry`; the graph's Company nodes carry `registry`.

## Code map

- `src/drp.py`: shares needed for the dividends to buy a whole new share
- `src/registries.py`: known registries, reading ASX's company details, storing, the admin's choice, the nightly command
- `gui.py`: the company payload's `drp` and `registry`, and the admin route
- `web/app.js`: `dividendReinvestCard()`, `shareRegistryCard()`

## Data

- `companies`: registry_id, registry_name, registry_source, registry_checked_at
- `dividend_payments`: the ordinary payments the DRP figures use

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- No registry on any company: run `python -m src.registries --dry-run` on the PC; ASX may have refused the requests or changed its company details (IMP-063). Set it by hand meanwhile.
- A portal link has moved: update the address in `REGISTRIES` (IMP-064).
- The DRP card is missing on a payer: no ordinary payment in 18 months in `dividend_payments`, or every recent payment was marked abnormal.

## Known limits

- ASX's company details couldn't be reached from the build environment; the reader looks for the registry by field name and by known names, and the first runs on the PC are its proof (IMP-063).
- Each company's own DRP rules (discount, pricing period, minimum holding, leftover cash) aren't known to Sift; the card and help describe the usual practice.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_registries.py`
- `tests/integration/test_drp_registry.py`
