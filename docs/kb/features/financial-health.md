---
id: financial-health
title: Financial health: Piotroski F-Score and Altman Z-Score
category: features
summary: The Financial health card on each company page (Sift's first React card), the nightly F-Score and Z-Score behind it, and the distress caution added to the action's reason without changing the action.
version: 1.1
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-01-10
source: AS_BUILT change log, 2026-10-10
related: [screener-actions, statistics, ingestion, adr-018-react-typescript-pages, adr-017-statistics-methods]
code: [src/analytics/health.py, src/analytics/run.py, src/screening/actions.py, src/ingestion/yahoo_client.py, src/ingestion/fundamentals_ingestion.py, src/ingestion/currency.py, src/models/financial_report.py, src/ai/tools.py, gui.py, screen_asx.py, frontend/src/islands/FinancialHealthCard.tsx, frontend/src/pages/company/CompanyPage.tsx, web/style.css]
tables: [financial_health, financial_reports]
---

## Purpose

Separate cheap shares whose business is getting stronger from cheap shares that are cheap for a reason (Sift's value-trap problem), and flag companies at risk of financial distress. These were roadmap items IMP-068 and IMP-069, which the owner asked to build on 2026-10-10. Both are long-established, explainable measures that suit everyday investors: a score out of 9 and three zones.

## How it works

**New statement lines.** `financial_reports` gains `current_assets`, `current_liabilities`, `gross_profit`, `retained_earnings` and `shares_outstanding`, read from Yahoo's statements (`CurrentAssets`, `CurrentLiabilities`, `GrossProfit`, `RetainedEarnings`, `OrdinarySharesNumber` or `ShareIssued`) and converted to Australian dollars like the other money lines (`MONETARY_FIELDS`). They fill in as each company's statements refresh each week. Until then, checks that need them show as "no data".

**F-Score** (`piotroski()`, Piotroski 2000). Nine pass-or-fail checks on the latest two annual reports: a profit, cash in from operations, return on assets improving, operating cash flow above profit (both against assets), debt to assets falling (or no debt in either year), current ratio improving, no new shares (a 0.5% rise is treated as rounding), gross margin improving, and asset turnover improving. Return on assets and turnover use the assets at the start of the year, as Piotroski did, and fall back to the year's own figure when the earlier year is missing. A check without data neither passes nor fails. The level is STRONG for 7 to 9, MIDDLING for 4 to 6 and WEAK for 0 to 3. With fewer than 6 checks made, it is NOT_ENOUGH ("Not enough data yet").

**Z-Score** (`altman()`, Altman 1968, the original public-company model): 1.2 x working capital / assets + 1.4 x retained earnings / assets + 3.3 x EBIT / assets + 0.6 x market value / liabilities + 1.0 x revenue / assets. Market value is the latest market capitalisation, or price x shares on issue. SAFE above 2.99, GREY from 1.81 to 2.99, DISTRESS below 1.81. Any missing input means no score.

**Excluded sectors.** Financial Services and Real Estate (`EXCLUDED_SECTORS`) get no score, with the reason stored in `excluded_reason`, because neither model fits bank, insurer or property trust balance sheets.

**Nightly.** `health.refresh()` runs in the Statistics step (`src/analytics/run.py`) for every active share with annual reports and upserts one row per company. The screener view joins `financial_health` and appends `f_score`, `f_checks`, `f_level`, `z_score` and `z_zone`.

**The distress caution.** In `suggest_action()` (`src/screening/actions.py`), a DISTRESS zone adds "; caution: possible financial distress (Altman Z-Score X, distress zone): check the balance sheet and latest results" to any reason except IGNORE's. It works like the short-selling caution: the action never changes, so the rules version doesn't either.

**The card** (`frontend/src/islands/FinancialHealthCard.tsx`, Sift's first React card, [ADR-018](kb:adr-018-react-typescript-pages)). The company page (React since 2026-10-10, `frontend/src/pages/company/CompanyPage.tsx`) shows it with data from `company_health()` in the company payload (`health`). It shows the answer first:

- the F-Score out of 9 with a pill (Strong, Middling, Weak, Not enough data yet) and the nine checks with ticks, crosses or "no data";
- the Z-Score with its zone pill and a sentence on what it means;
- a three-band Distress, Grey and Safe scale reusing the short-selling scale's style. The band is amber only for Distress; any other zone gets a neutral outline;
- "How this is worked out", closed by default. For admins it also shows the five Z-Score parts.

Pills use the shared `vpill` classes (good, bad as amber, wait), so no new colours are needed.

**Where else.** The AI company tool gives `financial_health` (`src/ai/tools.py`). The screener rows carry the fields for a later optional column. The help article is `financial-health` in `web/knowledge.json`.

## Code map

- `src/analytics/health.py`: `piotroski()`, `altman()`, `caution_text()`, `refresh()`, `company_health()`, plus `F_WORDS` and `Z_WORDS`
- `src/analytics/run.py`: runs `health.refresh()` nightly and logs the counts
- `src/screening/actions.py`: adds the distress caution to the reason
- `src/ingestion/yahoo_client.py`, `fundamentals_ingestion.py`, `currency.py`, `src/models/financial_report.py`: the new statement lines
- `gui.py`: `health` in the company payload, and the screener fields
- `frontend/src/islands/FinancialHealthCard.tsx` (+ `.test.tsx`), `frontend/src/pages/company/CompanyPage.tsx`, `web/style.css` (`health-*`, `zone-scale`)

## Data

- `financial_health`: one row per company: `as_of_date`, `fiscal_year`, `f_score`, `f_checks`, `f_level`, `f_detail` (the nine checks as JSON), `z_score`, `z_zone`, `z_parts` (JSON), `excluded_reason` and `computed_at`. It is shared market data with no owner, and excluded from search because it holds only numbers (the help article is searchable).
- `financial_reports`: the five new columns above.

## Diagnosing problems

- A share shows "Not enough data yet" or no Z-Score: its statements haven't refreshed since the new lines were added (weekly), or Yahoo doesn't report them for it. Check `financial_reports` for the latest FY row.
- The card says it didn't load: `web/dist/sift-ui.js` is missing or stale. Rebuild it (`frontend/README.md`) and check `tests/unit/test_frontend.py`.
- A bank or REIT shows "Not scored": this is by design.

## Known limits

- Both models were built on United States companies decades ago. The Z-Score was built on manufacturers, so young growth companies with low retained earnings can score low without being in trouble. The help says so.
- Only annual reports are used, so the scores change once a year per company, plus any market-value move in the Z-Score.
- Whether the F-Score should change any action (for example, block a BUY on a WEAK score) is an open question for the track record to answer. A change would need a rules version.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_health.py`
- `tests/integration/test_financial_health.py`
- `frontend/src/islands/FinancialHealthCard.test.tsx` (run by `tests/unit/test_frontend.py` when Node.js is installed)

## References

| Used for | Reference |
|---|---|
| F-Score | Piotroski, J. D. (2000). Value investing: the use of historical financial statement information to separate winners from losers. *Journal of Accounting Research*, 38 (Supplement), 1 to 41. [SSRN 249455](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=249455) |
| Z-Score | Altman, E. I. (1968). Financial ratios, discriminant analysis and the prediction of corporate bankruptcy. *Journal of Finance*, 23(4), 589 to 609. [doi:10.1111/j.1540-6261.1968.tb00843.x](https://doi.org/10.1111/j.1540-6261.1968.tb00843.x) |
