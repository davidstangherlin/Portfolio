---
id: adr-016-statistics-libraries
title: Decision: NumPy, SciPy and statsmodels for statistics and forecasting
category: decisions
summary: Why Sift's statistical work (probabilities, regressions, forecasts and back-tests) is built on NumPy, SciPy and statsmodels in the Python engine, rather than a niche library, a separate service or code written by hand.
version: 1.0
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-04-10
decision_status: accepted
related: [setup-and-configuration, ref-dependencies, track-record, valuation-models]
code: [requirements.txt, tests/unit/test_stats_stack.py]
---

## Status

Accepted, 2026-10-10.

## Context

The owner wants Sift to do more advanced analysis: for example the chance of a share reaching its target price, how reliable each rule has been in the track record, and trends and forecasts. These need tested statistical methods (probability distributions, hypothesis tests, regressions, time series), not sums written by hand. The owner asked whether the choice is right for the long term.

## Decision

Add three pinned libraries to `requirements.txt`, used inside the existing Python engine:

- **NumPy** (2.4.6): fast arrays; already installed with pandas, now pinned so it can't shift underneath the others.
- **SciPy** (1.17.1): probability distributions and statistical tests (for example the chance a price moves past a level, or whether a rule's results beat chance).
- **statsmodels** (0.15.0): regressions and time-series models with their confidence intervals and diagnostics, which explain *how sure* a result is: what a cautious investing tool needs.

Results are worked out in the nightly run or the API and reach pages and AI tools as plain words and figures, as everything else does.

## Options considered

- **Write the maths by hand:** no new libraries, but slow to build and easy to get subtly wrong; tested libraries are safer.
- **scikit-learn (machine learning) now:** good for prediction, but it optimises accuracy over explanation, and Sift explains its reasons. Add it later for a specific need; it builds on the same three.
- **A separate analytics service or language (R, a cloud service):** more moving parts and cost for one user; revisit only if the hosted service needs heavy computation.
- **Specialised libraries (PyMC for Bayesian models, arch for volatility):** narrower; add on top when a feature needs them.

## Consequences

These are the most widely used scientific libraries in Python: maintained for over 15 years, by large communities, with free licences (BSD) that allow commercial use, and the base most other analysis tools build on. They add about 60 MB to the install and nothing to page load. Versions are pinned and checked by `tests/unit/test_stats_stack.py`; Windows wheels exist for Python 3.11 to 3.14, so `pip install -r requirements.txt` (or `sift_console.bat`) installs them on the owner's PC without compilers.

## Revisit when

A feature needs machine learning, Bayesian modelling or heavy computation that the nightly run can't finish in time, or the hosted service moves analysis off the web server.
