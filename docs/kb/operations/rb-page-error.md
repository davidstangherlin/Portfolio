---
id: rb-page-error
title: Runbook: a page shows an error
category: operations
summary: A Sift page shows "Could not load" or a red message; how to find the cause in the server window and the usual fixes.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [web-gui, rb-database-connection, adr-011-idempotent-schema]
code: [gui.py, src/apply_schema.py]
---

## Symptoms

- "Could not load: ..." on a page, or a red message under a form.
- "Sign in to use Sift" (401), "This account is disabled" (403) or "Only an admin can do that" (403).

## Impact

Usually one page or action; the rest of Sift works.

## Check

1. Read the message: Sift writes the cause in plain words. The full traceback is in the window running `gui.py` (`start_sift.bat`).
2. "Missing a table or column" or `UndefinedColumn`: the code is newer than the database schema.
3. "could not connect": the database is down; see [Database won't connect](kb:rb-database-connection).
4. A 400 message under a form is a rule the person broke (for example a duplicate name); it isn't a fault.
5. 403 "Only an admin can do that" while an admin is impersonating: expected; the console is closed until impersonation ends.

## Fix

- Schema behind: `python -m src.apply_schema` from the Sift folder, or restart Sift (it applies the schema on start).
- Anything else: copy the traceback into a register item (IMP) with the page and the steps.

## Verify

Reload the page.

## Prevent and escalate

Every fixed fault should get a test that would have caught it, added with the fix.
