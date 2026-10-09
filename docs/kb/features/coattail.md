---
id: coattail
title: Coattail: following the smart money
category: features
summary: How fund managers holding the screener's companies are grouped into holder cards, with what they're adding and cutting, and the plan for director trades and substantial holders.
version: 1.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §31
related: [analyst-insights, etfs-presentation]
code: [src/coattail/views.py, scripts/probe_coattail_sources.py]
tables: [top_holders, fund_holdings]
---

## Purpose

Coattail shows where large investors are moving among Sift's companies, as a prompt for research, using the holder data already collected.

## How it works

A menu heading of its own, after Track record, for coattail investing: watching what big, well-researched investors buy and sell, as a lead for your own research. The user's focus is the ASX; famous US investors are noted for later.

**Stage 1 (built): Who's investing.** `src/coattail/views.py` `holdings()` reads `top_holders` ([§29](kb:analyst-insights): Yahoo's top 10 fund and top 10 institutional holders per screener company, refreshed weekly) and returns every holding with its manager, shares, % held, `shares_change` and report date, plus each company's name, action, price, held flag, watchlists and score wheel. `GET /api/coattail` serves it with the wheel's axes.

- **Managers.** `manager_of()` maps a holder to the manager behind it from a list of name patterns (Vanguard; iShares and BlackRock to BlackRock; DFA and Dimensional to Dimensional; FMR and Fidelity to Fidelity; SPDR and State Street to State Street; and so on), otherwise the holder's own name without suffixes such as Inc, LLC, Pty Ltd or Group. The URL id is `slug()` of the name (`#/coattail/vanguard`).
- **Shares bought or sold.** Yahoo gives a percentage change since the holder's previous report, which the user found hard to read; `shares_change()` turns it into shares: before = now / (1 + change), change = now - before. A change of 1,000% or more is marked `new`.
- **Index funds.** A fund whose name says it tracks an index (index, ETF, tracker, iShares, SPDR, MSCI, FTSE, Russell, S&P) is marked `index_fund`; institutions never are. Shown by default since 2026-10-08 (managers such as Vanguard and BlackRock hold mostly through index funds, and hiding them hid companies the user expected to see); Hide index funds leaves them out.
- **Coattail page.** Reported (last 3, 6 or 12 months, or any time; 12 by default) and Hide index funds. *Where the funds are going*: per company, how many managers added and cut (Most added to, Most cut; 10 each, with wheel and Recommendation (Sift's own suggested action, with the Action hover), there to compare Sift's view with the managers'). The Adding and Cutting counts are centred buttons: clicking one opens a row under the company naming each manager, the shares it bought or sold (or new holding), the holder line and report date, with a link to the manager's page; clicking again closes it. A coverage line says how many screener companies have holder lists (`with_holders`) and how many haven't been fetched yet (`fetched`, from `company_insights`). *Who's investing*: a card per manager, in the style of a collection card (the user's reference image): a tinted band with the first two words of the manager's name, cut with an ellipsis if they don't fit (colour from its name), its name, the average score wheel of the companies it holds (`cardWheel`, with small axis labels), the value of its listed holdings at today's prices, its three largest holdings' codes, the company count and pills for how many it's adding to and cutting. The cards have the same search and condition builder as the other lists ([§30](kb:table-filters)), over Holder, Companies held, Adding, Cutting, Value held and Holds (the codes it holds); search also matches the names of the companies held. A Sort by control orders the cards by companies held (default), adding, cutting or value held; ties go to value held, then name. Value held stands in for funds under management, which Sift has no source for. A Coming next card lists stages 2 and 3.
- **Holder page** (`#/coattail/{id}`). The same filters; the manager's company count, value at today's prices, adding and cutting counts and average wheel; and a table with each company once, through the manager's largest listed holding in it (an institution's figure usually includes its own funds, so lines aren't added up; the others show as "+1 more fund" on hover): score, company, held through, shares, change in shares (percentage on hover; New for a new position), % held, value now, reported and Recommendation. When the filters hide some of its companies, the page says how many, with a Show all button.
- **Limits.** Yahoo's holder lists come mostly from overseas funds' filings, so Australian super funds are often missing, and each figure is as at its report date, often months old.

**Stage 2 (planned): ASX director trades and substantial holders.** Appendix 3Y notices (directors trading their own company's shares) and substantial holder notices (forms 603, 604 and 605: stakes of 5% or more). Both are ASX announcements; a source is to be confirmed (ASX's own announcement data, which Sift can't reach from the build environment, or a paid feed, which the public service in the multi-user plan would need anyway).

`scripts/probe_coattail_sources.py` (read-only, standard library only) checks the candidate sources from the user's PC, where the build environment's network policy blocks them: ASX announcements three ways (the ASX website's data service, the older ASX API and the announcements search page), counting director interest and substantial holder notices and trying one notice's PDF; and the ASX 200 ETF holdings files of Vanguard (VAS), iShares (IOZ), SPDR (STW) and Betashares (A200), as candidates for managers' full ASX holdings. It saves its report to `logs/probe_coattail.txt`.

**Stage 3 (later): famous US investors.** Quarterly 13F filings from SEC EDGAR (free and official) for funds such as Berkshire Hathaway and Bridgewater: holdings, and what was bought and sold. US shares only, and up to 45 days after the quarter.

**Knowledge base.** New category Coattail: `coattail` (the user's definition, how Sift applies it, and what to keep in mind) and `holder-moves` (Who's investing, and the Holder change hover). Getting around lists the page.

**Tests.** `tests/unit/test_coattail.py` (index fund names, managers, shares bought or sold) and `test_coattail_groups_holders_by_manager_with_shares_bought_or_sold` in `tests/integration/test_gui.py`.

### Hide index funds

`is_index_fund()` marks a holding when its holder is a fund (not an institution) whose name says it tracks an index (`INDEX_FUND`: index, ETF, iShares, SPDR, MSCI, FTSE, Russell, S&P, tracker). Index funds trade to match their index, not on a view of the company, so ticking Hide index funds leaves them out of every Coattail figure. It's off by default because Vanguard, BlackRock and State Street hold most of their ASX shares through index funds. The reasoning shows on hover (and the "i" on touch screens) from the Help entry `index-funds-coattail`; the Index tag on a holder's page has a matching tooltip. Matching by name misses funds whose names don't say so (IMP-034).

## Code map

- `src/coattail/views.py`: managers, holdings, adding and cutting
- `scripts/probe_coattail_sources.py`: checks which ASX and manager sources work from a given connection

## Data

- `top_holders`: the source of holder moves

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A manager seems to hold too few companies: Yahoo lists only each company's top 10 holders, and only screener companies are covered (IMP-034).

## Known limits

- Director trades and substantial holder notices await the source probe (IMP-040).

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_coattail.py`
