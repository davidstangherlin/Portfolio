---
id: adr-015-asic-short-positions
title: Decision: ASIC's daily short positions, shown as a caution that never changes the action
category: decisions
summary: Why short interest comes from ASIC's free daily file, and why a heavily shorted share gets a caution (short interest and days to cover) beside its action rather than a red flag that blocks a BUY.
version: 1.1
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-04-10
decision_status: accepted
related: [volume-and-short-selling, rb-short-positions, screener-actions, track-record]
code: [src/ingestion/short_positions.py, src/screening/short_caution.py]
---

## Status

Accepted, 2026-10-10.

## Context

The owner asked how to see whether a company is shorted, and chose a company card, a screener column, a Most shorted list and a flag or trigger. A first build made more than 10% sold short a red flag, which turns a BUY into INVESTIGATE. The owner then set the rule: "Shares that are shorted are volatile. People can buy them but do so with caution", with a formula based on professional practice.

## Decision

Load ASIC's daily aggregated short position file (free, every ASX product, about four business days behind) nightly. Rate each share with the two measures professional short-interest services report, short interest % and days to cover (shares short / 20-day average volume), plus the month's change, into a caution: HIGH or ELEVATED. Show it as an amber tag and a note in the action's reason; never change the action. Because actions don't change, the rules version stays as it is and the track record isn't split.

## Options considered

- **A red flag** (the first build): simple, but it hides BUYs the owner wants to see, and shorts are sometimes hedges, not a view on the company.
- **A score wheel check:** would move scores and needs a new rules version; a caution says more in words.
- **A trader's shorted-share framework** (crowdedness from short interest of float, borrow fee and utilisation; squeeze risk from days to cover and the price against its 50-day average; fundamental decay from revenue growth and free cash flow; signals such as "viable short candidate"), reviewed 2026-10-10: its signals are for short sellers, not Sift's buyers and holders, and borrow fees and utilisation aren't public in Australia. Its fundamentals cross-check was adopted as **Why might they be short?** (days to cover and the 50-day trend for squeeze risk; sales, free cash flow, earnings quality and the fundamentals trend for decay), worded for a buyer or holder.
- **A paid short-interest service:** daily and richer (borrow cost, utilisation), but a cost before Sift has users; ASIC's file is the source those services start from.

## Consequences

Heavily shorted shares stay in BUY lists with a visible caution. The thresholds are settings. ASIC's file layout is proven only on the owner's PC (IMP-066); a change shows as a failed step ([runbook](kb:rb-short-positions)).

## Revisit when

The track record shows heavily shorted BUYs doing markedly worse (then a red flag or score check may be justified, with a new rules version), ASIC changes the file, or Sift is hosted for the public (check ASIC's terms for redistribution).
