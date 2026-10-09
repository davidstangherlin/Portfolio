---
id: help-knowledge-base
title: Help and the user knowledge base
category: features
summary: How web/knowledge.json supplies the Help page, every hover explanation and the Word rules document's glossary.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
source: AS_BUILT §23
related: [search, developer-kb]
code: [web/knowledge.json, scripts/build_rules_doc.js]
---

## Purpose

One file explains every term and screen to users, so the Help page, hovers and the printed glossary never disagree. (This developer knowledge base is separate and admin-only.)

## How it works

**Purpose.** One searchable place for every term, rule and how-to, and one source for text that used to live in three places (the hover explanations in `app.js`, the Word glossary in the document builder, and the README), so a definition can't say one thing on hover and another in the document.

**Source: `web/knowledge.json`.** `categories` (ten topics) and `entries`, each with: `id` (also its link, `#/help/<id>`), `title`, `category`, `definition` (one line; the Word glossary text for glossary entries), optional `hover` and `labels` (the UI labels that show it, e.g. "Debt/equity"), `body` paragraphs, `aliases` (search words such as SMSF or special dividend), `related` IDs and `links` into Sift. Glossary entries carry `glossary: "acronym"` (with `abbreviation` and `full`) or `glossary: "term"` (with `glossary_title`). `{margin_of_safety}`, `{roe}`, `{debt_to_equity}` and `{yield}` are filled with the live thresholds wherever the text is shown. The first version merged the 37 hover explanations, both valuation-model explanations, 23 acronyms and 27 glossary terms into 78 entries (one per concept, e.g. ROE's acronym, glossary meaning and hover text are one entry), and added guides to the dashboard, the nightly refresh, actions, the score wheel, portfolios and trades, watchlists and the track record, each checked against the code.

**Where it's used.**
- **Hover explanations:** `app.js` loads the file before the first page draws and builds `FIELD_HELP` (label to text) and `ESTIMATED_VALUE_HELP` (DCF/DDM) from it; `withHelp()` and `svgLabelHelp()` are unchanged. If the file can't load, pages still work without explanations.
- **Help page (`#/help`, `#/help?q=`, `#/help/<id>`):** entries grouped by topic, each a collapsible row (pink twisty) with the definition, "In Sift" hover text where it differs, the full explanation, related terms and links. Search needs every word to appear and ranks exact names, then titles starting with the query, then names and aliases, then definitions, then anywhere; up to three results open automatically. Topic chips filter.
- **Menu search:** an exact company code wins; then an exact term (title, abbreviation or full name before aliases) opens its entry; then companies by code prefix or name; then, if any entry matches, the Help results. Terms appear in the search list labelled Help.
- **Word document:** `scripts/build_rules_doc.js` takes Appendix A's acronyms and key terms from the file (sorted by name), and writes the rest of the document itself. Run `npm install` once in `scripts/`, then `node build_rules_doc.js`.

**Checks (`tests/unit/test_knowledge.py`).** IDs unique and URL-safe; every entry has a title, definition and known category; every related ID and link is real; every UI label Sift asks for is explained exactly once; both valuation models are explained; glossary entries have what the Word table needs and none were lost; and, per entry, no em dashes and no unknown placeholders. `test_gui.py` checks the file is served behind the password.

**Not included, by choice:** AS_BUILT stays a separate technical document, and there's no AI question-answering (it would need an API key and send questions out). Both can be added later; the Help search would be the place to hang Q&A.

## Code map

- `web/knowledge.json`: every help entry: title, definition, body, aliases, labels, links
- `scripts/build_rules_doc.js`: builds the Word rules document from it

## Data

No tables of its own.

## Diagnosing problems

- A test fails on knowledge.json: an em dash, an unknown placeholder or a hover label explained twice; the test names the entry.

## Known limits

- Users can't add or edit help in the app; changes go through git.

The full list, with status: [Improvement register](#/admin/kb/register).

## Tests

- `tests/unit/test_knowledge.py`
