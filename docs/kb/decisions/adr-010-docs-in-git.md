---
id: adr-010-docs-in-git
title: Decision: the developer knowledge base lives in git, shown in Sift
category: decisions
summary: Why developer documentation is Markdown in the repository, checked by tests and shown to admins in Sift, rather than edited in the app.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [kb-guide, developer-kb]
code: [docs/kb/, src/devkb/]
---

## Status

Accepted, 2026-10-09.

## Context

The design record had grown into one 1,800-line file, hard to navigate, review or hand to a helper. Documentation must stay in step with the code.

## Decision

One Markdown file per article in `docs/kb/` with a checked header (version, owner, review dates), edited with the code in git, rendered in Admin, Developer, searchable by admins; reference pages generated from the code.

## Options considered

- **Edited in Sift (database):** friendlier for non-developers, but drifts from the code and needs an editor and workflow.
- **A wiki (Confluence, Notion):** good editing, separate from the code and its history.
- **Files only:** not searchable in Sift.

## Consequences

Every change has history and review; edits need git.

## Revisit when

Non-developers need to edit often, or the team outgrows a single repository.
