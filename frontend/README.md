# Sift's pages in React and TypeScript

Why and how: `docs/kb/decisions/adr-018-react-typescript-pages.md`. The components here are built into `web/dist/sift-ui.js`. That file is committed, so running Sift needs no Node.js. You only need Node.js if you change something in this folder.

## Build after a change

```
cd frontend
npm ci            # first time only (uses package-lock.json; .npmrc pins exact versions)
npm test          # component tests (Vitest)
npm run build     # type check, build web/dist/sift-ui.js, write web/dist/build-info.json
```

Commit `web/dist` with your change. `tests/unit/test_frontend.py` fails if `frontend/` changed and `web/dist` wasn't rebuilt.

## How a component reaches a page

Until React owns the whole app, `web/app.js` builds each page and mounts React components on it as islands:

- `src/main.tsx` lists the islands and exposes `window.SiftUI.mount(name, element, props)` and `sweep()`.
- `island(name, props, title)` in `web/app.js` mounts one as a card. After each route change, `SiftUI.sweep()` unmounts any island whose page has gone.
- `window.SiftHost` (set in `web/app.js`, typed in `src/lib/host.ts`) gives components what the old app knows: help entries, opening help, and whether the user is an admin.

## Rules

- Use Sift's classes and colour tokens from `web/style.css`; never raw colours.
- Write in Australian English, with no em dashes.
- Pin library versions exactly (`save-exact=true`).
- Every component gets a Vitest test beside it (`*.test.tsx`).
