#Requires -Version 5.1
<#
.SYNOPSIS
  Golden profile: worker HTTP /replay notify only (no OBS SaveReplay in this step).

.DESCRIPTION
  Use when OBS Save Replay Buffer already ran (e.g. separate OBS hotkey). Delegates to
  scripts/worker_notify_instant_replay.ps1 -Http (worker /replay, then scoreboard replay_on).

  Prefer invoke-full-replay.ps1 for one button that does OBS + worker + scoreboard.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (-not [string]::IsNullOrWhiteSpace($env:REPLAYTROVE_ROOT)) {
    $repoRoot = $env:REPLAYTROVE_ROOT.Trim().TrimEnd('\', '/')
} else {
    $repoRoot = (Resolve-Path (Join-Path $here '..\..')).Path
}

$script = Join-Path $repoRoot 'scripts\worker_notify_instant_replay.ps1'
if (-not (Test-Path -LiteralPath $script)) {
    Write-Error "Golden profile: worker_notify script not found at $script (set REPLAYTROVE_ROOT if needed)."
    exit 1
}

& $script -Http
exit $LASTEXITCODE
