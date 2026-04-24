#Requires -Version 5.1
<#
.SYNOPSIS
  Legacy VBS entrypoint forwarder (non-blocking).

.DESCRIPTION
  Logs use of deprecated *.vbs replay shortcuts, then starts save_replay_and_trigger.ps1 in a separate
  process. Prefer Stream Deck / Companion calling save_replay_and_trigger.ps1 or worker_notify_instant_replay.ps1 directly.

  See docs/operator-replay-trigger-runbook.md (avoid new VBS replay shortcuts).
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $Source
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'replaytrove_json_log.ps1')
Write-ReplayTroveJsonl -Component 'scripts' -ScriptName 'forward_vbs_to_canonical_replay.ps1' -Event 'deprecated_vbs_forward' -Level 'WARN' -Message 'VBS replay entry forwarded to canonical script' -Data @{
    source             = $Source
    non_canonical_path = 'vbs'
}

$canonical = Join-Path $PSScriptRoot 'save_replay_and_trigger.ps1'
if (-not (Test-Path -LiteralPath $canonical)) {
    Write-ReplayTroveJsonl -Component 'scripts' -ScriptName 'forward_vbs_to_canonical_replay.ps1' -Event 'deprecated_vbs_error' -Level 'ERROR' -Message 'canonical script missing' -Data @{
        source = $Source
        path   = $canonical
    }
    exit 1
}

$argList = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-WindowStyle', 'Hidden',
    '-File', $canonical
)
Start-Process -FilePath powershell.exe -ArgumentList $argList -WindowStyle Hidden
exit 0
