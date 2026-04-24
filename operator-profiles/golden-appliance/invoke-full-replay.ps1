#Requires -Version 5.1
<#
.SYNOPSIS
  Golden profile: full canonical instant replay (OBS save + worker HTTP + scoreboard replay_on).

.DESCRIPTION
  Delegates to scripts/save_replay_and_trigger.ps1. See README.md in this folder and
  docs/operator-replay-trigger-runbook.md.

  Repo root: REPLAYTROVE_ROOT env, else parent of operator-profiles/ (two levels above this file).
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (-not [string]::IsNullOrWhiteSpace($env:REPLAYTROVE_ROOT)) {
    $repoRoot = $env:REPLAYTROVE_ROOT.Trim().TrimEnd('\', '/')
} else {
    $repoRoot = (Resolve-Path (Join-Path $here '..\..')).Path
}

$script = Join-Path $repoRoot 'scripts\save_replay_and_trigger.ps1'
if (-not (Test-Path -LiteralPath $script)) {
    Write-Error "Golden profile: canonical script not found at $script (set REPLAYTROVE_ROOT if install is not standard)."
    exit 1
}

& $script @args
exit $LASTEXITCODE
