# ASX Value Screener: What It Is, Why It Matters, Who It's For

## Executive Summary

This is a self-hosted research tool that applies classic Graham/Buffett value-investing discipline to the ASX, at a scale no individual investor could realistically do by hand. It ingests real market data, computes rigorous intrinsic valuations (including sector-appropriate models for banks and REITs), and screens hundreds of companies daily, flagging not just what's cheap, but what's cheap *and getting cheaper* versus cheap *because the business is deteriorating*. It automates the research grunt work; the judgement calls remain yours.

## What It Does

At its core, the application runs a daily pipeline across roughly 500 ASX-listed companies:

1. **Ingests data** - daily prices and multi-year financial statements, pulled automatically from market data.
2. **Computes intrinsic value** - a two-stage discounted cash flow model for most companies; a dividend discount model for banks, insurers and REITs, since their "free cash flow" doesn't mean what it means for an industrial company.
3. **Calculates the supporting ratios** - ROE, debt/equity, P/E, P/B, franking-adjusted dividend yield, Graham Number, margin of safety.
4. **Tracks trend, not just snapshot** - whether a company's margin of safety is improving over time (price-driven momentum) and whether its underlying fundamentals (ROE, revenue) are improving or declining, independent of price.
5. **Screens and flags** - shows every company against the four classic value criteria, with visible pass/fail indicators rather than silently hiding anything, plus two explicit risk flags: a payout-ratio warning (likely one-off dividend) and a value-trap warning (looks cheap, but the business is deteriorating).
6. **Checks the quality behind the numbers** - whether profit is turning into cash, whether the price is stabilising or still falling, whether the dividend has been held or cut, and how complete the underlying data is.
7. **Suggests a next step, with the reasoning** - BUY, INVESTIGATE, WATCH or AVOID for shares you don't own; ACCUMULATE, HOLD, REVIEW or SELL for ones you do, each with a plain-English reason naming the tests and flags behind it.
8. **Keeps your CGT records** - every parcel you buy or sell, with brokerage, dates and the 12-month discount tracked, a financial-year capital gains summary, and a prompt when waiting a few weeks before selling would halve the tax.
9. **Runs unattended** - a scheduled job refreshes the whole dataset daily, so the research is always current without manual effort.
10. **Shows it all in a browser** - a local web app, usable on your phone at home, with a filterable screener and a page per company: a score wheel built from 30 named checks, price against estimated value, charts of price, value and financial history, and every rule's result in plain English.

## Why It's Helpful to Investing

**It replaces manual screening with systematic, repeatable analysis.** Reviewing 500 companies' financials by hand for value characteristics is not something a part-time investor can sustain. This does it every day, consistently, applying the same criteria every time.

**It separates genuine mispricing from value traps.** A low P/E or high margin of safety alone can be a bargain or a warning sign. By tracking fundamentals trend (ROE and revenue direction) independently of price, the tool flags when "cheap" is cheap *because the market is wrong*, versus cheap because the business is in decline. This is one of the most common mistakes in naive value investing, and the tool is built specifically to catch it.

**It applies the right model to the right sector.** A generic DCF breaks down for banks, insurers and REITs, whose cash flow behaves differently to an industrial company's. Rather than silently producing a misleading number (or no number at all), the tool switches to a dividend discount model for these sectors, so financials get a genuine valuation instead of being skipped.

**It surfaces trend, which most retail screening tools don't.** A static screen tells you what's cheap right now. This tool also tracks whether something has *just become* cheap, or whether it's been sitting there for months (often a sign the market has already correctly priced in a problem). That's the difference between catching an opportunity early and buying into a story everyone else gave up on.

**It builds judgement, not just a list.** Every suggested action comes with the reason behind it, so over time you learn which signals matter and why: the difference between cheap and good value, between a strong yield and a reliable one, between a bargain and a falling knife.

**It connects research to your actual portfolio.** Knowing what you hold lets it tell you when an owned company has started to deteriorate, and when the timing of a sale matters for tax.

**It's transparent about its own limitations.** Every formula, every threshold, and every known weakness is documented. Where data is missing or a calculation would produce a nonsensical result, the tool shows nothing rather than fabricating a number. That discipline matters more in a financial tool than almost anywhere else.

## Who the Target User Group Is

**Primary: the self-directed value investor** who wants Buffett/Graham-style discipline applied systematically across the ASX, without paying for an institutional-grade terminal or manually modelling hundreds of companies. This is someone comfortable reading a spreadsheet of ratios and making their own final call, who wants the heavy lifting done for them first.

**Secondary: a technically capable investor who wants to own and extend their own tooling**, rather than depend on a third-party platform's black-box screening logic. Because it's a local, open codebase, every assumption (growth rates, discount rates, thresholds) is visible and adjustable, not hidden behind someone else's proprietary model.

**Explicitly not the target user:** someone wanting investment advice, a fully automated trading signal, or a tool that removes the need for judgement. The outputs are inputs to a decision, not the decision itself, and the documentation is deliberately upfront about where the models are simple heuristics rather than sophisticated financial modelling.

---

See `README.md` for setup and day-to-day usage, and `docs/AS_BUILT.md` for the full technical design, formulas, known issues and change history.
