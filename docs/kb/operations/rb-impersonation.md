---
id: rb-impersonation
title: Runbook: impersonation and account problems
category: operations
summary: Ending an impersonation that's stuck, finding who impersonated whom, and restoring an admin who lost access.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [profile-preferences-impersonation, accounts-owners]
code: [src/accounts.py]
tables: [users, impersonations]
---

## Symptoms

- An admin sees the amber banner in every browser and can't reach the admin console.
- Someone asks who looked at their data.
- No active admin is left (should be impossible through Sift; possible by editing the database).

## Check and fix

- **End an impersonation:** the banner's End impersonation button. Without the page: `DELETE /api/impersonation` from the admin's browser, or in the database:
  ```sql
  UPDATE impersonations SET ended_at = now(), ended_how = 'ended' WHERE ended_at IS NULL;
  ```
  Sessions also end by themselves after 8 hours.
- **Who impersonated whom:** Admin, Users, Impersonation log (last 50), or `SELECT * FROM impersonations ORDER BY started_at DESC;`.
- **Restore an admin:**
  ```sql
  UPDATE users SET role = 'admin', status = 'active' WHERE email = 'owner@sift.local';
  ```

## Verify

`/api/me` shows the expected person and no `impersonated_by`.

## Prevent and escalate

Sift refuses removing your own admin role and keeps one active admin. Any unexplained impersonation is a security matter: record it, and change the GUI password.
