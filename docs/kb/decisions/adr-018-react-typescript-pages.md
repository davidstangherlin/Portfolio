---
id: adr-018-react-typescript-pages
title: Decision: all Sift pages in React and TypeScript, migrated in phases inside the current app
category: decisions
summary: Why every Sift page is moving to React and TypeScript, new work first and then the existing pages phase by phase as islands inside the current app, until React owns the shell and router and app.js is retired.
version: 2.0
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-04-10
decision_status: accepted
related: [adr-002-fastapi-plain-js, web-gui, architecture, financial-health]
code: [web/app.js, web/style.css, web/index.html, gui.py, frontend/src/main.tsx, frontend/src/lib/host.ts, frontend/scripts/build-info.mjs, tests/unit/test_frontend.py]
---

## Status

Accepted, 2026-10-10. Supersedes the front-end half of [ADR-002](kb:adr-002-fastapi-plain-js); the FastAPI JSON API stays. Version 2.0 (same day): after the first card was built, the owner asked to rebuild the remaining pages too, replacing "existing pages move when next redesigned" with a phased full migration.

## Context

`web/app.js` has grown to about 4,800 lines of plain JavaScript in one file. The roadmap adds richer screens (the crash test simulator, portfolio diversification, a later AI assistant and possibly a phone app), and Sift is heading to a hosted, multi-user service that others may help build. The owner asked that, from now on, all pages be built in the new web format, and chose React with TypeScript, with existing pages moved when they are next changed.

## Decision

- **React with TypeScript** for every new page and every new card or panel on an existing page. TypeScript checks the shapes of the API's answers, so mistakes show at build time, not in the browser.
- **Inside the current app, not a separate site.** New pages and cards mount into Sift's existing shell (menu, sign-in, search, router in `web/app.js`) as islands, until enough has moved for React to own the routing.
- **Same look and rules.** Components use Sift's colour tokens and classes from `web/style.css` (pink actions, blue links, red delete, chart colours `--s1` to `--s3`), Australian English, the "plain words first, details behind a twisty" pattern, help links from `web/knowledge.json`, and desktop and phone checks.
- **Every existing page moves, in phases** (owner's request, 2026-10-10: "rebuild the remaining web pages in the new format"). It is a like-for-like rebuild: same look, words and behaviour, so users notice nothing but speed and polish. The order is shared pieces first (charts, tooltips, tables, the table filter, the dashboard layout), then the pages one at a time, then the shell (menu, sign-in, search, router), after which `web/app.js`, `tablefilter.js` and `dashlayout.js` are retired. Each phase is pushed with the whole app working and the test suite passing; until the last phase, `app.js` builds the shell and mounts React pages and cards as islands.
- **How islands work.** `frontend/src/main.tsx` registers components and exposes `window.SiftUI.mount(name, element, props)` and `sweep()`. `island()` in `app.js` mounts one, and the router calls `sweep()` after each page change to unmount islands whose page has gone. `window.SiftHost` (typed in `frontend/src/lib/host.ts`) lends components what the old app knows (help entries, opening help, whether the user is an admin) until React owns those too.
- **Built with Vite; the built files are committed** to the repository (`web/dist/sift-ui.js`, one script loaded before `app.js`), so the owner's PC runs Sift without Node.js. Only whoever builds pages needs Node.js. Library versions are pinned exactly (`.npmrc` `save-exact=true`). `web/dist/build-info.json` records a fingerprint of the sources, and `tests/unit/test_frontend.py` fails if `frontend/` changed without a rebuild.
- **The API is unchanged:** components call the same JSON routes in `gui.py`.
- **Tests:** component tests with Vitest beside each component, run from the pytest suite when Node.js is installed, plus the existing browser checks at desktop and phone widths.

## Options considered

- **Svelte with TypeScript:** lighter and less code per page, but a smaller pool of developers and no direct path to a phone app.
- **Vue with TypeScript:** a middle ground with fewer Australian developers than React.
- **Stay with plain JavaScript:** no build step, but the single file keeps growing and richer screens get slower and riskier to build.
- **Rewrite every page at once:** cleanest in the end, but everything breaks at once if it goes wrong. Rejected in favour of phases.
- **Move pages only when next redesigned** (version 1.0 of this decision): least effort, but two styles of page for years; the owner chose a full migration instead.

## Consequences

The largest pool of developers to hire or hand over to, and skills that carry to React Native for a phone app. A build step and a toolchain to keep current. During the migration Sift has two styles of page; the shared tokens keep them looking the same. The bundle with React is about 62 KB compressed (196 KB raw), loaded once. The toolchain was set up with the first card, Financial health ([Financial health](kb:financial-health)). The migration is IMP-084 in the register.

## Revisit when

Phase 3 hosting (build in the deployment pipeline rather than committing built files), the last page has moved (hand routing to React and retire `app.js`), or a phone app is started.
