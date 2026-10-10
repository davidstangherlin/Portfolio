---
id: coattail
title: Coattail: following the smart money
category: features
summary: Big funds (fund managers holding the screener's companies, grouped into holder cards), ASX director trades (Appendix 3Y) and substantial holder notices (forms 603, 604, 605), read nightly for every ASX company.
version: 2.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-10
next_review: 2027-01-09
source: AS_BUILT §31
related: [analyst-insights, etfs-presentation, adr-014-asx-notices-source, rb-asx-notices, ai-and-graph, volume-and-short-selling]
code: [src/coattail/views.py, src/coattail/notices.py, src/coattail/notice_reader.py, src/coattail/notice_views.py, scripts/probe_coattail_sources.py]
tables: [top_holders, fund_holdings, asx_notices, director_trades, substantial_holdings]
---

## Purpose

Coattail shows where large investors are moving among Sift's companies, as a prompt for research, using the holder data already collected.

## How it works

A menu heading of its own, after Track record, for coattail investing: watching what big, well-researched investors buy and sell, as a lead for your own research. The user's focus is the ASX; famous US investors are noted for later.

**Stage 1 (built): Who's investing.** `src/coattail/views.py` `holdings()` reads `top_holders` ([§29](kb:analyst-insights): Yahoo's top 10 fund and top 10 institutional holders per screener company, refreshed weekly) and returns every holding with its manager, shares, % held, `shares_change` and report date, plus each company's name, action, price, held flag, watchlists and score wheel. `GET /api/coattail` serves it with the wheel's axes.

- **Managers.** `manager_of()` maps a holder to the manager behind it from a list of name patterns (Vanguard; iShares and BlackRock to BlackRock; DFA and Dimensional to Dimensional; FMR and Fidelity to Fidelity; SPDR and State Street to State Street; and so on), otherwise the holder's own name without suffixes such as Inc, LLC, Pty Ltd or Group. The URL id is `slug()` of the name (`#/coattail/vanguard`).
- **Shares bought or sold.** Yahoo gives a percentage change since the holder's previous report, which the user found hard to read; `shares_change()` turns it into shares: before = now / (1 + change), change = now - before. A change of 1,000% or more is marked `new`.
- **Index funds.** A fund whose name says it tracks an index (index, ETF, tracker, iShares, SPDR, MSCI, FTSE, Russell, S&P) is marked `index_fund`; institutions never are. Shown by default since 2026-10-08 (managers such as Vanguard and BlackRock hold mostly through index funds, and hiding them hid companies the user expected to see); Hide index funds leaves them out.
- **Coattail page.** Reported (last 3, 6 or 12 months, or any time; 12 by default) and Hide index funds. *Where the funds are going*: per company, how many managers added and cut (Most added to, Most cut; 10 each, with wheel and Recommendation (Sift's own suggested action, with the Action hover), there to compare Sift's view with the managers'). The Adding and Cutting counts are centred buttons: clicking one opens a row under the company naming each manager, the shares it bought or sold (or new holding), the holder line and report date, with a link to the manager's page; clicking again closes it. A coverage line says how many screener companies have holder lists (`with_holders`) and how many haven't been fetched yet (`fetched`, from `company_insights`). *Who's investing*: a card per manager, in the style of a collection card (the user's reference image): a tinted band with the first two words of the manager's name, cut with an ellipsis if they don't fit (colour from its name), its name, the average score wheel of the companies it holds (`cardWheel`, with small axis labels), the value of its listed holdings at today's prices, its three largest holdings' codes, the company count and pills for how many it's adding to and cutting. The cards have the same search and condition builder as the other lists ([§30](kb:table-filters)), over Holder, Companies held, Adding, Cutting, Value held and Holds (the codes it holds); search also matches the names of the companies held. A Sort by control orders the cards by companies held (default), adding, cutting or value held; ties go to value held, then name. Value held stands in for funds under management, which Sift has no source for. Tabs (`coattailTabs()`): Big funds (this stage), Director trades and Substantial holders (stage 2), and Most shorted (ASIC's short positions: the most shorted ASX shares and those rising fastest, see [Volume and short selling](kb:volume-and-short-selling)). A Coming next card lists stage 3.
- **Holder page** (`#/coattail/{id}`). The same filters; the manager's company count, value at today's prices, adding and cutting counts and average wheel; and a table with each company once, through the manager's largest listed holding in it (an institution's figure usually includes its own funds, so lines aren't added up; the others show as "+1 more fund" on hover): score, company, held through, shares, change in shares (percentage on hover; New for a new position), % held, value now, reported and Recommendation. When the filters hide some of its companies, the page says how many, with a Show all button.
- **Limits.** Yahoo's holder lists come mostly from overseas funds' filings, so Australian super funds are often missing, and each figure is as at its report date, often months old.

**Stage 2 (built 2026-10-09): ASX director trades and substantial holders.** The user asked for both each day, keeping announcements whose titles contain "Becoming", "Change in" or "Ceasing", and chose: every ASX company (not only Sift's), each notice's PDF read for its details, and the notices shown on Coattail tabs, the company page and the dashboard. Director notices are titled "Change **of** Director's Interest Notice", which "Change in" would miss, so they're matched separately with the user's agreement. Source decision: [ADR-014](kb:adr-014-asx-notices-source).

- **Loading** (`src/coattail/notices.py`, nightly step ASX Notices after ETFs). `fetch_lists()` reads ASX's two market-wide lists, `todayAnns.do` and `prevBusDayAnns.do` (the second catches anything released after the previous night's run), with a browser's fingerprint (`curl_cffi`, as the ETF report download does) and a 1-second pause between requests. `parse_list()` takes each table row with a `displayAnnouncement.do?...idsId=` link: the code (or `default_code` on one company's page, which has no code column), date and time (Sydney), price-sensitive flag, pages and headline (the link cell's text without page count and size). `notice_reader.classify()` keeps director notices (`change of director's interest` or `appendix 3y`) and substantial holder notices (`becoming`, `change in`, `ceasing`, only when the title is about a holding or holder, so "Change in Chief Executive" is ignored). Initial and final director notices (3X, 3Z) are not followed. `save()` inserts new notices once (`ON CONFLICT DO NOTHING` on ASX's id) and links them to Sift's company when there is one.
- **Reading** (`read_unread()`). Each pending notice's PDF is downloaded (`get_pdf()` follows ASX's terms page to the real PDF when it answers with one) and read with `pypdf`. `notice_reader.read_3y()` splits the text at each "Name of Director" and takes each field as the text between its label and the next label found, after removing the form's own guidance sentences (the "Nature of change" example names every kind of change, so leaving it in would make every trade look on-market; hyphens broken across lines are allowed for). It works out direction (BUY, SELL, MIXED, NONE), the kind of change (`nature_kind`: ON_MARKET, OFF_MARKET, EXERCISE, DRP, ISSUE, OTHER), and dollars and price per share from whichever the notice gives. `read_substantial()` takes the holder (after "Details of substantial holder ... Name"), the company, the date, and the voting power percentages in part 2 (before and after for form 604; after for 603; 0 for 605, which says only "below 5%"). `holder_group()` trims legal tails ("and its related bodies corporate", "as trustee for ...", brackets) and `manager_of()` groups the holder as Big funds does. Status: `read`, `partial` (some details not found), `unreadable` (no text: a scanned image) or `failed` (didn't download, retried on the next two nights, `MAX_ATTEMPTS`). `READER_VERSION` goes up with any change to the reading; `--reread` redoes older notices. Each notice is committed as it's read, so a stopped run keeps its work.
- **Command.** `python -m src.coattail.notices` (nightly), `--dry-run` (fetch and read five, print, save nothing: the check after a change or on a new PC), `--codes BHP PLS` or `--mine` (six months of one company's notices from its ASX announcements page, as a backfill), `--html page.html` (a list page saved from the browser, when fetching is refused), `--reread`, `--limit`.
- **Showing** (`src/coattail/notice_views.py`). `GET /api/coattail/notices?group=directors|substantial&days=7|30|90|365` for the two tabs, with the current user's held and watched flags added per request (the notices are shared data). Director trades: a summary of net dollars bought and sold on market per company in the period (`director_summary()`, top 10 each way), and a table (date, company, director, trade, type, notice link) filtered by Bought or Sold, On market only, Yours only and search. Substantial holders: counts (became, raised, cut, ceased) and a table (date, company, holder, linked to its Big funds card when the manager has one, event, before, after, change in points). On phones each row folds into two columns. The company page has a card of the company's notices over the last year (`company_notices()`, in the company payload); the dashboard a card of the last week's notices on your own companies (`my_notices()`, widget `notices`). Release times are shown in Sydney time.
- **AI and graph.** The read-only tool `notices` (code, kind, days, mine) answers in words (`in_words()`). The graph export adds `Director` nodes (by name within the company), `DIRECTOR_OF` and `TRADED` (one per notice) relationships, and `SUBSTANTIAL_NOTICE` from the holder's `Manager` (created when Big funds doesn't have it).
- **Not searchable** (`EXCLUDED` in `src/search/indexer.py`): the notices are reached through Coattail and the company pages, whose companies are indexed (IMP-061).

`scripts/probe_coattail_sources.py` (read-only, standard library only) checks candidate sources from the user's PC, where the build environment's network policy blocks them: ASX announcements three ways and one notice's PDF, and the ASX 200 ETF holdings files of Vanguard (VAS), iShares (IOZ), SPDR (STW) and Betashares (A200). It saves its report to `logs/probe_coattail.txt`.

**Stage 3 (later): famous US investors.** Quarterly 13F filings from SEC EDGAR (free and official) for funds such as Berkshire Hathaway and Bridgewater: holdings, and what was bought and sold. US shares only, and up to 45 days after the quarter.

**Knowledge base.** New category Coattail: `coattail` (the user's definition, how Sift applies it, and what to keep in mind) and `holder-moves` (Who's investing, and the Holder change hover). Getting around lists the page.

**Tests.** `tests/unit/test_coattail.py` (index fund names, managers, shares bought or sold) and `test_coattail_groups_holders_by_manager_with_shares_bought_or_sold` in `tests/integration/test_gui.py`. Notices: `tests/unit/test_notice_reader.py` (titles followed, both PDFs in `tests/fixtures/notices`, laid out like the real forms; text variants with two directors, sells, per-share prices, DRP; forms 603 and 605; list pages; the terms page) and `tests/integration/test_notices.py` (the nightly load against a fake ASX, retries, the tabs, company page, AI tool, each person's dashboard, the dry run).

### Hide index funds

`is_index_fund()` marks a holding when its holder is a fund (not an institution) whose name says it tracks an index (`INDEX_FUND`: index, ETF, iShares, SPDR, MSCI, FTSE, Russell, S&P, tracker). Index funds trade to match their index, not on a view of the company, so ticking Hide index funds leaves them out of every Coattail figure. It's off by default because Vanguard, BlackRock and State Street hold most of their ASX shares through index funds. The reasoning shows on hover (and the "i" on touch screens) from the Help entry `index-funds-coattail`; the Index tag on a holder's page has a matching tooltip. Matching by name misses funds whose names don't say so (IMP-034).

## Code map

- `src/coattail/views.py`: managers, holdings, adding and cutting
- `src/coattail/notices.py`: fetching ASX's lists and PDFs, saving, reading, the command
- `src/coattail/notice_reader.py`: which titles are followed; reading Appendix 3Y and forms 603, 604, 605
- `src/coattail/notice_views.py`: the tabs, company card, dashboard card and AI answers
- `scripts/probe_coattail_sources.py`: checks which ASX and manager sources work from a given connection

## Data

- `top_holders`: the source of holder moves
- `asx_notices`: one row per director or substantial holder notice: code, released, headline, kind, PDF link, read status
- `director_trades`: one row per director in a notice: who, date, bought, sold, dollars, price, kind of change
- `substantial_holdings`: one row per substantial holder notice: holder, manager, date, voting power before and after

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- A manager seems to hold too few companies: Yahoo lists only each company's top 10 holders, and only screener companies are covered (IMP-034).
- No new notices, or many "Not read": see [ASX notices aren't loading](kb:rb-asx-notices).

## Known limits

- The notice reader was built on the forms' published layout and test PDFs laid out the same way; the first nights on real notices are its proof (IMP-060).
- History before the first nightly run comes only from `--codes` or `--mine` (six months per company).
- Notices aren't searchable yet (IMP-061); initial and final director notices (3X, 3Z) aren't followed.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_coattail.py`
