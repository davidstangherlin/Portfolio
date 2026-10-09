---
id: adr-002-fastapi-plain-js
title: Decision: FastAPI and plain JavaScript pages
category: decisions
summary: Why Sift's pages are one plain JavaScript file over a JSON API rather than a front-end framework.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [web-gui, architecture]
code: [gui.py, web/app.js]
---

## Status

Accepted, 2026-10-05.

## Context

Sift needed a browser interface on a PC and a phone, maintained mostly by one person with AI help, with no build tooling to break and nothing loaded from other sites.

## Decision

A FastAPI server returning JSON, and pages built by `web/app.js` with small `h()` and `s()` helpers. No bundler, no framework, no outside scripts or fonts.

## Options considered

- **React or Vue with a build step:** richer ecosystem, but a toolchain to maintain and upgrade.
- **Server-rendered templates:** simple, but every interaction becomes a page load.
- **A desktop app:** no phone access.

## Consequences

Fast to change and nothing to build; the whole app works offline on the home network. `app.js` is large (about 4,000 lines), so it relies on clear sections and tests of the pure parts (`tests/js`).

## Revisit when

`app.js` becomes hard to change safely, or several people work on pages at once; splitting it into modules would come first.
