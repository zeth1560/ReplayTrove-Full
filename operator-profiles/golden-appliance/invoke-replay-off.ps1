#Requires -Version 5.1
<#
.SYNOPSIS
  Golden profile: scoreboard replay_off (dismiss / hide replay UI only).

.DESCRIPTION
  Does not stop worker ingest or OBS; command-bus only. Pair with full replay or operator workflow.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (-not [string]::IsNullOrWhiteSpace($env:REPLAYTROVE_ROOT)) {
    $repoRoot = $env:REPLAYTROVE_ROOT.Trim().TrimEnd('\', '/')
} else {
    $repoRoot = (Resolve-Path (Join-Path $here '..\..')).Path
}

$script = Join-Path $repoRoot 'scripts\send_command.ps1'
if (-not (Test-Path -LiteralPath $script)) {
    Write-Error "Golden profile: send_command.ps1 not found at $script (set REPLAYTROVE_ROOT if needed)."
    exit 1
}

& $script -Target scoreboard -Action replay_off -ArgsJson '{}'
exit $LASTEXITCODE
