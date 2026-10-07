<#
.SYNOPSIS
    Daily refresh for the ASX value investing pipeline: ingest latest prices
    and fundamentals, recompute valuations, and log the current screener
    result. Intended to be run unattended via Windows Task Scheduler.

.DESCRIPTION
    Runs, in order:
        0. src.apply_schema              (bring the database up to the code's schema)
        1. src.ingestion.run_ingestion   (prices for the watchlist; fundamentals, analyst ratings
                                          and holders for the seventh fetched longest ago)
        1b. src.etf.run_etfs             (ASX ETF report if due, ETF prices and distributions, ETF performance)
        2. src.valuation.run_valuation   (recompute every company's metrics)
        3. src.tracking.record_signals   (tonight's signals, for the track record)
        4. src.tracking.score_signals    (score signals whose 1/3/6/12 months have passed; prune)
        5. screen_asx.py --actions       (today's suggested actions, with reasons)
    Everything each step prints (including errors) is captured into one
    timestamped log file under logs\, with each step's start time and
    duration, so a run can be checked after the
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

# Runs one step, logging its start time, everything it prints, and how
# long it took, so a slow or stalled step is obvious from the log alone.
function Invoke-Step {
    param([string]$Name, [scriptblock]$Command)
    Write-Log ""
    Write-Log "--- $Name --- started $(Get-Date -Format 'HH:mm:ss')"
    $Clock = [Diagnostics.Stopwatch]::StartNew()
    & $Command 2>&1 | ForEach-Object {
        # Python logs to stderr, which Windows PowerShell wraps as error
        # records; a blank stderr line would otherwise be written as
        # "System.Management.Automation.RemoteException".
        $Line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
        if ($Line -eq 'System.Management.Automation.RemoteException') { $Line = '' }
        Add-Content -Path $LogFile -Value $Line
    }
    Write-Log "    $Name took $([math]::Round($Clock.Elapsed.TotalMinutes, 1)) min"
}

Invoke-Step "Schema" { python -m src.apply_schema }
# Prices for every share; statements for the seventh fetched longest ago
# (each refreshed weekly); analyst ratings and holders likewise.
Invoke-Step "Ingestion" { python -m src.ingestion.run_ingestion --tickers-file $WatchlistFile --delay 0.5 --weekly-fundamentals }
Invoke-Step "ETFs" { python -m src.etf.run_etfs }
Invoke-Step "Valuation" { python -m src.valuation.run_valuation --all }
Invoke-Step "Signal Record" { python -m src.tracking.record_signals }
Invoke-Step "Track Record" { python -m src.tracking.score_signals }
Invoke-Step "Suggested Actions" { python screen_asx.py --actions }

Write-Log ""
Write-Log "===== Daily Refresh Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="

# Keep the logs folder from growing forever.
Get-ChildItem -Path $LogDir -Filter "refresh_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force
