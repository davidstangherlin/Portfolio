---
id: rb-database-connection
title: Runbook: the database won't connect
category: operations
summary: Sift or the nightly run can't reach PostgreSQL; how to check the service, the connection settings and the port.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [setup-and-configuration, rb-backup-restore, rb-page-error]
code: [src/config.py, .env.example]
---

## Symptoms

`OperationalError: could not connect to server`, `password authentication failed`, or every page failing at once.

## Impact

Nothing works until the database is back. No data is lost by a stopped service.

## Check

1. Windows: Services, `postgresql-x64-18` (or similar), Status. Or in PowerShell: `Get-Service postgresql*`.
2. Is the port listening? `Test-NetConnection localhost -Port 5432`.
3. `.env` has the right `DATABASE_URL` (open the file; never paste the password into chat, email or a ticket).
4. Disk space on the drive holding the PostgreSQL data folder.

## Fix

- Service stopped: start it (Services, Start; or `Start-Service postgresql-x64-18` as administrator).
- Password changed: update `DATABASE_URL` in `.env`.
- Disk full: free space, then start the service.
- Database damaged: restore from the latest backup ([Backup and restore](kb:rb-backup-restore)).

## Verify

`python -m src.apply_schema` finishes without error, and Sift's pages load.

## Prevent and escalate

Keep regular backups. If the service stops by itself repeatedly, check the Windows event log (Application, source PostgreSQL) and record it in the register.
