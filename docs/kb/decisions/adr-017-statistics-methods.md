---
id: adr-017-statistics-methods
title: Decision: simple, explainable statistics that claim less rather than more
category: decisions
summary: Why Sift's chances and ranges come from each share's own volatility with no trend assumed, why the rule test uses the track record's own benchmark with a widened error for overlapping calls, and why everything is shown as words and numbers in 10.
version: 1.2
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-04-10
decision_status: accepted
related: [statistics, adr-016-statistics-libraries, track-record, adr-005-immutable-signal-record]
code: [src/analytics/prices.py, src/analytics/rules.py, src/analytics/words.py]
---

## Status

Accepted, 2026-10-10.

## Context

The owner asked for three statistics: whether each rule is working, the chance of reaching a target price, and a likely price range. Sift's audience is everyday, long-term investors, and Sift is heading to a public service, so the figures must be honest, explainable in a sentence and hard to misread as advice. The owner approved how they'd look from a mock-up before the build.

## Decision

- **Price behaviour from the share's own history, no trend assumed.** Volatility from up to three years of daily prices; the likely range is one standard deviation either side in the log price ("two years in three"); the chance of reaching a level is the chance a driftless random walk touches it within a year. Assuming no trend avoids building a forecast into a "chance", which would read as a prediction.
- **Beta from weekly returns against an ASX 200 fund** (IOZ, then STW, A200, VAS), for the crash test simulator to come. Weekly, because thinly traded shares make daily beta unreliable.
- **The rule test uses the track record's own benchmark** (the average screened share, total return), so the verdict and its test can never disagree, and its own calls (each company's first call each month). A t-test at 95%, needing 30 calls (an admin setting). Calls a month apart overlap when the horizon is longer than a month, so the standard error is widened by the square root of the horizon in months: a conservative rule of thumb that makes Sift claim less. The monthly summary keeps a sum of squares so the test covers the whole history after the daily detail is deleted.
- **Many tests corrected together** (added 2026-10-10, IMP-070). Every action at every period is tested at once, so a few would pass by luck. Benjamini-Hochberg keeps the expected share of false findings at 5%, and the bars are widened to the matching level (Benjamini and Yekutieli, 2005) so the picture and the verdict can't disagree. It is fixed by design, like the confidence level.
- **Words and numbers in 10, not percentages,** with one fixed scale everywhere, and blue (not green or red) for chances and ranges. Exact figures stay in the details for admins.
- **Statistics never change an action** and so don't change the rules version.
- **Two settings, the rest fixed:** the calls needed before judging a rule and the years of price history are admin settings; the confidence level, overlap widening, benchmark, price model and words are fixed and shown as "Fixed by design" on Admin, Model and rules, so a result can't be tuned until a rule passes.

## Options considered

- **A trend (drift) from past returns or the margin of safety:** would make chances look like forecasts and reward recent winners; rejected for now.
- **Fat-tailed or volatility-clustering models (GARCH, Student's t):** more realistic in crashes, harder to explain; revisit for the crash test simulator.
- **Comparing against the ASX 200 index rather than the average screened share:** the mock-up said "ASX 200", but the track record already uses the average screened share; one benchmark avoids two answers to one question.
- **Bonferroni rather than Benjamini-Hochberg:** simpler, but so strict across about 30 tests that a real edge would rarely show; Benjamini-Hochberg controls the share of false findings instead, the usual choice when many strategies are tested (Harvey, Liu and Zhu, 2016, argue the same for finance).
- **Newey-West or block-bootstrap errors for overlap:** more exact, harder to explain and to check; the square-root widening is simpler and errs on the safe side.
- **Percentages on the page:** research on risk communication finds natural frequencies ("4 in 10") are read more accurately by non-specialists.

## Consequences

Simple to explain on the page and in the help. Ranges understate extreme moves (real prices have fatter tails than the model), which the help says. Chances ignore value: a share far below its estimated value shows a low chance of reaching it, which is honest about price movement but must not be read as "it won't recover"; the page says the figure doesn't know about results or news.

## Revisit when

The crash test simulator is designed (consider fat tails and stressed correlations), the track record has a few years of calls (consider bootstrap errors), or users misread the chances.

## References

Full citations with checked links are in the [Statistics](kb:statistics) article. The decision rests mainly on Student (1908) for the t-test, Benjamini and Hochberg (1995) and Benjamini and Yekutieli (2005) for many tests at once, Hansen and Hodrick (1980) and Newey and West (1987) for overlapping returns, Black and Scholes (1973) for log-normal prices, Shreve (2004, section 3.7) for the chance of touching a level, Sharpe (1964), Scholes and Williams (1977) and Dimson (1979) for beta, Mandelbrot (1963) for fat tails, and Gigerenzer and Hoffrage (1995) for numbers in 10.
