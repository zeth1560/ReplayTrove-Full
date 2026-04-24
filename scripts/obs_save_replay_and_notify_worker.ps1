#Requires -Version 5.1
<#
.SYNOPSIS
  Compatibility wrapper for legacy "save + notify worker" replay trigger.

.DESCRIPTION
  Preserves the existing interface for external callers (Stream Deck, launchers), but
  delegates to the canonical replay entrypoint scripts/save_replay_and_trigger.ps1
  (OBS SaveReplay + worker + scoreboard replay_on on success — full pipeline).

  Prefer that script (or docs/operator-replay-trigger-runbook.md) for new wiring.
#>
param(
    [string] $ObsHost = '127.0.0.1',
    [int] $Port = 4455,
    [string] $Password = 'MonkeyButt',

    [string] $TriggerFile = $(if ($env:REPLAYTROVE_INSTANT_REPLAY_TRIGGER_FILE) { $env:REPLAYTROVE_INSTANT_REPLAY_TRIGGER_FILE } else { 'C:\ReplayTrove\state\instant_replay.trigger' }),

    [switch] $WorkerHttp,

    [string] $HttpHost = $(if ($env:REPLAY_TRIGGER_HTTP_HOST) { $env:REPLAY_TRIGGER_HTTP_HOST } else { '127.0.0.1' }),

    [int] $HttpPort = $(if ($env:REPLAY_TRIGGER_HTTP_PORT) { [int]$env:REPLAY_TRIGGER_HTTP_PORT } else { 0 })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$canonicalScript = Join-Path $PSScriptRoot 'save_replay_and_trigger.ps1'
if (-not (Test-Path -LiteralPath $canonicalScript)) {
    Write-Error "obs_save_replay_and_notify_worker: canonical script missing at $canonicalScript"
    exit 1
}

$args = @(
    '-NoProfile',
    '-WindowStyle', 'Hidden',
    '-ExecutionPolicy', 'Bypass',
    '-File', $canonicalScript,
    '-ObsHost', $ObsHost,
    '-ObsPort', ([string]$Port),
    '-ObsPassword', $Password
)
if ($WorkerHttp) {
    if ($HttpPort -le 0) {
        Write-Error "obs_save_replay_and_notify_worker: -WorkerHttp requires -HttpPort or REPLAY_TRIGGER_HTTP_PORT."
        exit 2
    }
    $args += @(
        '-WorkerReplayHost', $HttpHost,
        '-WorkerReplayPort', ([string]$HttpPort)
    )
}
else {
    # Preserve old default behavior: notify worker via trigger file touch.
    $args += @(
        '-UseWorkerTriggerFile',
        '-WorkerTriggerFile', $TriggerFile
    )
}

$proc = Start-Process -FilePath powershell.exe -ArgumentList $args -WindowStyle Hidden -Wait -PassThru
exit $proc.ExitCode
