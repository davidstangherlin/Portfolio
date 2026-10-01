<#
.SYNOPSIS
    Daily refresh for the ASX value investing pipeline: ingest latest prices
    and fundamentals, recompute valuations, and log the current screener
    result. Intended to be run unattended via Windows Task Scheduler.

.DESCRIPTION
    Runs, in order:
        1. src.ingestion.run_ingestion   (prices + fundamentals for the watchlist)
        2. src.valuation.run_valuation   (recompute every company's metrics)
        3. screen_asx.py                 (today's screener result)
    Everything each step prints (including errors) is captured into one
    timestamped log file under logs\, so a run can be checked after the
    fact without having to watch it live. Logs older than 30 days are
    pruned automatically.

    Assumes: the repo is already cloned, python -m venv .venv has already
    been run inside it, requirements.txt is installed, .env is configured,
    and the watchlist file below exists. See docs/AS_BUILT.md for setup
    and for how this script is wired into Task Scheduler.

.NOTES
    Each step runs regardless of whether a previous one reported problems -
    deliberately not using "&&"/stop-on-error chaining, so one bad step
    (e.g. a transient network issue during ingestion) doesn't prevent the
    valuation/screener steps from still running against whatever data is
    already in the database.
#>

# Resolve the repo root from this script's own location, so the script
# keeps working if the repo is ever moved or cloned to a different path.
$RepoDir = Split-Path -Parent $PSScriptRoot
$VenvActivate = Join-Path $RepoDir ".venv\Scripts\Activate.ps1"
$WatchlistFile = Join-Path $RepoDir "allords.txt"   # swap for asx300.txt etc. if your watchlist changes
$LogDir = Join-Path $RepoDir "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "refresh_$Timestamp.log"

function Write-Log {
    param([string]$Message)
    Add-Content -Path $LogFile -Value $Message
}

Set-Location $RepoDir
. $VenvActivate

Write-Log "===== Daily Refresh Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="

Write-Log ""
Write-Log "--- Ingestion ---"
python -m src.ingestion.run_ingestion --tickers-file $WatchlistFile --delay 0.5 2>&1 |
    ForEach-Object { Add-Content -Path $LogFile -Value $_ }

Write-Log ""
Write-Log "--- Valuation ---"
python -m src.valuation.run_valuation --all 2>&1 |
    ForEach-Object { Add-Content -Path $LogFile -Value $_ }

Write-Log ""
Write-Log "--- Screener Result ---"
python screen_asx.py 2>&1 |
    ForEach-Object { Add-Content -Path $LogFile -Value $_ }

Write-Log ""
Write-Log "===== Daily Refresh Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="

# Keep the logs folder from growing forever.
Get-ChildItem -Path $LogDir -Filter "refresh_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force
