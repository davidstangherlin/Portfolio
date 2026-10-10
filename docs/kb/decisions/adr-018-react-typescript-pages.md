---
id: adr-018-react-typescript-pages
title: Decision: new pages in React and TypeScript, existing pages moved when next redesigned
category: decisions
summary: Why every new Sift page or card is built with React and TypeScript, mounted inside the current app, while existing plain JavaScript pages move over only when they next get a significant change.
version: 1.0
status: published
owner: Product owner
published: 2026-10-10
reviewed: 2026-10-10
next_review: 2027-04-10
decision_status: accepted
related: [adr-002-fastapi-plain-js, web-gui, architecture]
code: [web/app.js, web/style.css, gui.py]
---

## Status

Accepted, 2026-10-10. Supersedes the front-end half of [ADR-002](kb:adr-002-fastapi-plain-js); the FastAPI JSON API stays.

## Context

`web/app.js` has grown to about 4,800 lines of plain JavaScript in one file. The roadmap adds richer screens (the crash test simulator, portfolio diversification, a later AI assistant and possibly a phone app), and Sift is heading to a hosted, multi-user service that others may help build. The owner asked that, from now on, all pages be built in the new web format, and chose React with TypeScript, with existing pages moved when they are next changed.

## Decision

- **React with TypeScript** for every new page and every new card or panel on an existing page. TypeScript checks the shapes of the API's answers, so mistakes show at build time, not in the browser.
- **Inside the current app, not a separate site.** New pages and cards mount into Sift's existing shell (menu, sign-in, search, router in `web/app.js`) as islands, until enough has moved for React to own the routing.
- **Same look and rules.** Components use Sift's colour tokens and classes from `web/style.css` (pink actions, blue links, red delete, chart colours `--s1` to `--s3`), Australian English, the "plain words first, details behind a twisty" pattern, help links from `web/knowledge.json`, and desktop and phone checks.
- **Existing pages move when next redesigned.** A substantial redesign of a page (not a small fix or one extra line) rebuilds it in React; nothing is rewritten for its own sake.
- **Built with Vite; the built files are committed** to the repository, so the owner's PC runs Sift without Node.js. Only whoever builds pages needs Node.js. Library versions are pinned exactly.
- **The API is unchanged:** components call the same JSON routes in `gui.py`.
- **Tests:** component tests with Vitest alongside the existing pytest suite and browser checks.

## Options considered

- **Svelte with TypeScript:** lighter and less code per page, but a smaller pool of developers and no direct path to a phone app.
- **Vue with TypeScript:** a middle ground with fewer Australian developers than React.
- **Stay with plain JavaScript:** no build step, but the single file keeps growing and richer screens get slower and riskier to build.
- **Rewrite every page now:** cleanest in the end, but weeks of work users won't see, and everything breaks at once if it goes wrong.

## Consequences

The largest pool of developers to hire or hand over to, and skills that carry to React Native for a phone app. A build step and a toolchain to keep current. For a while Sift has two styles of page; the shared tokens keep them looking the same. React adds about 45 KB (compressed) to the first page load. The toolchain is set up with the first page or card built under this decision.

## Revisit when

Phase 3 hosting (build in the deployment pipeline rather than committing built files), most pages have moved (hand routing to React and retire the old router), or a phone app is started.
