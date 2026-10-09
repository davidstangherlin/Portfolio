---
id: rb-backup-restore
title: Runbook: back up and restore the database
category: operations
summary: How to take a full backup of Sift's database with pg_dump, check it, and restore it to the same or another machine.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [rb-database-connection, setup-and-configuration]
code: [.gitignore]
---

## When

Before a risky change (a big schema change, the move to hosting), weekly as routine, and before handing a copy to a helper (who should get a copy with personal data removed).

## Back up

In PowerShell, from any folder (finds `pg_dump` for whichever PostgreSQL version is installed):

```powershell
$pgdump = (Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" | Sort-Object FullName -Descending | Select-Object -First 1).FullName
& $pgdump -U postgres -h localhost -F c -f "$HOME\Documents\asx_value_backup_$(Get-Date -Format yyyy-MM-dd).dump" asx_value
```

It asks for the database password. Check the file size is similar to the last backup (about 45MB in October 2026). Keep backups out of the Sift folder or rely on `.gitignore` (`*.dump`, `*.backup`), and keep a copy off the PC.

## Restore

To a new, empty database (safest; keeps the old one until you're sure):

```powershell
$bin = Split-Path $pgdump
& "$bin\createdb.exe" -U postgres -h localhost asx_value_restored
& "$bin\pg_restore.exe" -U postgres -h localhost -d asx_value_restored "<path to .dump>"
```

Then point `DATABASE_URL` in `.env` at `asx_value_restored`, start Sift and check the dashboard, a portfolio and the track record.

## Verify

Row counts in the [Data dictionary](kb:ref-data-dictionary) match what you expect; `python -m src.apply_schema` runs cleanly.

## Prevent and escalate

Backups are manual today (IMP-046). Hosting (Phase 4) brings daily automated backups.
