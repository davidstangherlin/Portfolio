---
id: lics
title: LICs: listed investment companies and trusts
category: features
summary: How LICs are judged on share price against net tangible assets (NTA) rather than valued as companies.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §27
related: [etfs-collection, etfs-presentation]
code: [src/etf/views.py, src/etf/asx_report.py]
tables: [etf_monthly]
---

## Purpose

A LIC's price can sit well above or below the value of what it holds; the premium or discount to NTA is the main signal.

## How it works

**Purpose.** The user supplied an ASX LIC NTA report alongside the ETF report, and chose to treat LICs as a third group under their own heading, apart from shares and ETFs, with NTA figures taken from the ASX monthly report only (no separate LIC NTA file), and no Morningstar data (it needs a paid licence). An LIC is a listed company (or, for an LIT, a trust) whose business is holding other investments; with a fixed number of shares, its price can sit well above or below the value of what it holds. The value measure is therefore the share price against **net tangible assets (NTA)**, not a cash flow valuation, which doesn't fit a company whose assets are other shares.

**Source.** The "Spotlight LIC List" sheet of the same ASX Investment Products report ([§25.1](kb:etfs-collection)). Headings: ASX Code, Type (Shares = LIC, Units = LIT, CDI for a foreign-domiciled one), Fund Name, MER (% p.a), Outperf Fee (Yes/No), Mkt Cap ($m, written with commas), flows and trading, **Prem/Disc % NTA (pre-tax) at NTA Date** (a fraction), **NTA Date**, **NTA Price**, last close, year high and low, distribution yield and 1-month, 1, 3 and 5-year total returns (Bloomberg, gross dividends). Categories are section rows, as on the ETP sheet; the Australian Indices section is left out. The July 2026 report gives 91 LICs and LITs (68 LIC, 22 LIT, 1 CDI); AFI reads as NTA $7.93 at 30 June 2026, an 11.1% discount, market cap $8.4 billion, fee 0.16%, no performance fee.

**Model.**
- `companies.security_type` gains `LIC` (the check constraint is dropped and re-added, so an existing database upgrades in place).
- `etf_monthly` and `etf_performance` hold LICs as well as ETFs (the names are kept so existing databases don't need migrating). New `etf_monthly` columns: `nta_pre_tax`, `nta_date`, `nta_premium_percent`, `performance_fee`. For LICs, `fum_aud` holds market capitalisation.
- `watchlist_items.nta_discount_above`: an LIC trigger, met while the price is at least that many percent below the last NTA.

**Reading and loading (`asx_report.py`).** `sheet_kind()` sends ETP sheets to the ETF reader and the LIC sheet to the same reader with LIC rules: NTA headings (`nta_premium_percent`, `nta_date`, `nta_pre_tax`; post-tax NTA ignored), "Outperf Fee" before the fee rule, "Mkt Cap" as size, Shares/Units shown as LIC/LIT, premium fractions scaled on the median like the other percents. `load_report()` creates or keeps each as security type LIC. **An LIC already in the nightly ticker file as a share is reclassified** (logged as a WARNING), which takes it out of the share valuation, screener, signals and the track record's average; its past signals stay in the track record. LICs the newest report no longer lists are marked inactive, separately from ETFs.

**Prices, dividends and performance.** The nightly ETF step ([§16](kb:nightly-run) step 1b) now fetches prices and dividends for active LICs too, with the same full-history backfill and total-return figures. The share ingestion (`run_ingestion`) skips any code that is an ETF or LIC, so an LIC in `allords.txt` isn't fetched twice or given financial statements.

**Premium or discount now (`views.premium_now`).** The latest close against the last reported NTA, in percent; until an LIC has prices stored, the ASX report's own figure at the NTA date (`premium_basis` says which). NTA is monthly, so the figure compares today's price with NTA at the end of the previous month or so.

**In Sift.**
- **Menu:** **LICs** next to ETFs. The LIC screener (`#/lics`, `/api/lics`) lists every active LIC with category, premium/discount to NTA (deepest discount first by default), fee, performance fee, market cap, 1, 3 and 5-year returns and yield; LIT marks a trust.
- **LIC page (`#/lic/CODE`, `/api/lic/CODE?compare=`):** share price, premium/discount to NTA (against NTA $x at its date), fee with the performance fee, yield; performance against the category average, a reference LIC and the ASX report; growth of $10,000; share price with dividend markers; **premium/discount to NTA over time** (builds month by month); dividends per share by financial year; company facts. A company page for an LIC code redirects here, and search opens it.
- **Dashboard:** an **LICs** card beside the ETFs card (LIC watchlist triggers, LIC parcels reaching the CGT discount, LICs held or watched with day move, premium/discount and 1-year return). The portfolio line splits Shares | ETFs | LICs.
- **Portfolios and watchlists:** an **LICs** section under its own heading in each, with share price, premium/discount and yield; parcels and sales tag LIC codes. Watchlist triggers for LICs: price at or below, yield above, and discount to NTA of at least X%; the margin of safety trigger is refused.
- **Layout:** with nine menu items, the menu folds behind the menu button below 1120px (was 1060px), menu items are tighter below 1400px, the search box keeps at least 96px, and on phones long cells and headings switch to short forms ("-14.3%", "vs NTA").

**Help.** A new LICs topic: LIC (now with hover text and a guide), NTA (acronym, Word glossary), Premium/discount to NTA (Word glossary term "Discount to NTA"), performance fee, market cap, the LIC screener and an LIC's page; the getting around, dashboard, portfolios and watchlists guides mention LICs.

**Tests.** `tests/integration/test_lic_gui.py`: an LIC in the share list moves to its own heading; the LIC screener and both premium bases; the LIC page and its LIC-only reference list; dashboard, portfolio and watchlist sections with the trigger rules; the share ingestion skipping ETFs and LICs; LIC prices and performance from the ETF step. `tests/unit/test_asx_report.py` covers the LIC sheet (a replica of the real layout), its headings and sheet selection.

**Limits.**
- NTA is monthly and about a month old when the report comes out; the live premium mixes today's price with that NTA. Post-tax NTA (in the separate LIC NTA report) isn't used.
- Yields are cash only; most Australian LICs pay fully franked dividends, so their grossed-up yield is higher.
- No suggested actions or scores for LICs; a wide discount can persist or widen for good reason (fees, performance, liquidity), so it's a prompt to look, not a signal.

## Code map

- `src/etf/views.py`: LIC rows and the premium or discount
- `src/etf/asx_report.py`: NTA from the ASX report

## Data

- `etf_monthly`: NTA per LIC per month

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A premium looks odd after a sharp market move: NTA is about a month old (IMP-033).

## Known limits

- NTA is monthly (IMP-033).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/integration/test_lic_gui.py`
