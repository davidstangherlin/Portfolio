---
id: kb-guide
title: How this knowledge base works
category: start-here
summary: What the developer knowledge base is for, how articles are written, versioned and reviewed, and how to add a new article, decision record or release note.
version: 1.1
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [change-process, system-overview, architecture, developer-kb]
code: [docs/kb/, src/devkb/, tests/unit/test_devkb.py]
---

## Purpose

This is Sift's developer knowledge base: how Sift is designed and how it works, for admins and for anyone who helps build or run it. Use it to diagnose problems, plan improvements and bring a new helper up to speed. It's separate from Help (`web/knowledge.json`), which explains Sift to the people who use it.

## Where articles live

Every article is a Markdown file in `docs/kb/`, in a folder for its category, named after its id (`docs/kb/features/search.md` has the id `search`). Articles are edited in git with the code they describe, so every change has history and review. Sift shows them under **Admin, Developer**, to admins only. To search them, an admin picks **Developer knowledge base** in the search box's pink ▾ menu (the default on these pages); they're never mixed into Everything.

| Category | Folder | What goes there |
|---|---|---|
| Start here | `start-here/` | Orientation: overview, architecture, setup, testing, how changes are made |
| Features | `features/` | One article per part of Sift, all on the same template |
| Data | `data/` | Data model and data sources (the data dictionary is generated) |
| Operations | `operations/` | The nightly run, the fault-finding table and runbooks (`rb-...`) |
| Decision records | `decisions/` | One record per significant design decision (`adr-...`) |
| Generated reference | none | Built from Sift each time it's opened: data dictionary, API, settings, dependencies, tests |
| Release notes | `releases/` | One article per Sift version |

The improvement register is `docs/kb/improvements.json`, shown at Admin, Developer, Improvement register.

## The header block

Every article starts with a header between `---` lines. A test (`tests/unit/test_devkb.py`) fails if a field is missing or wrong, so nothing is published half-described.

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Lower case and hyphens; the same as the file name |
| `title`, `summary` | yes | The summary is one sentence, shown in lists and search |
| `category` | yes | One of the categories above |
| `version` | yes | major.minor: add 0.1 for a correction or addition, a whole number for a rewrite |
| `status` | yes | `draft`, `published` or `retired` (retired articles stay for history but drop out of search) |
| `owner` | yes | The role accountable for keeping it right (a role, not a person, so it survives staff changes) |
| `published`, `reviewed`, `next_review` | yes | Dates (YYYY-MM-DD); `next_review` must be after `reviewed` |
| `related` | no | Ids of related articles, shown beside the article |
| `code`, `tables` | no | Files and tables the article describes; the test checks each file exists |
| `source` | no | Where the content came from (for example `AS_BUILT §32`) |
| `release` | release notes | The Sift version the notes describe |
| `decision_status` | decision records | `proposed`, `accepted`, `superseded` or `deprecated` |

## Templates

**Feature articles:** Purpose, How it works, Code map, Data, Diagnosing problems, Known limits, Tests.

**Runbooks:** Symptoms, Impact, Check, Fix, Verify, Prevent and escalate.

**Decision records:** Status, Context, Decision, Options considered, Consequences, Revisit when.

**Release notes:** Highlights, Changes (by area), Upgrade steps, Known issues, Articles updated.

## Writing style

Australian English, plain words, no em dashes (the test enforces it). Say what the code does and why; link instead of repeating. Link to another article with `[text](kb:article-id)`, to a heading in it with `kb:article-id#heading-anchor`, to a Sift page with `#/...`. Register items written as IMP-001 link to the register automatically.

## Review cycle

Each article has a next review date: three months for features, runbooks and guides, six months for decision records, a year for release notes. Due and overdue reviews show on the knowledge base home page. To review: read the article against the code, fix anything out of date, set `reviewed` to today, move `next_review` on, and add 0.1 to `version` if anything changed.

## Adding something

1. Copy an article of the same kind, change the header (new id, file name to match), write the body on the template.
2. Run the tests (`.venv/bin/python -m pytest -q tests/unit/test_devkb.py`).
3. Commit with the code change it describes. See [How changes are made](kb:change-process).

## The as-built record

`docs/AS_BUILT.md` is the original design record and remains the **change log**: every change still gets a row there. Its numbered sections were split into these articles on 9 October 2026 and are kept as history; the articles are now the current description.
