#Requires -Version 5.1
<#
.SYNOPSIS
  Compatibility wrapper for legacy worker replay notify triggers.

.DESCRIPTION
  Preserves existing interface (-Http / -TriggerFile), but delegates to the canonical
  replay entrypoint script (save_replay_and_trigger.ps1) with:
    -SkipObsSave -SkipScoreboardReplayOn
#>
param(
    [Parameter(Mandatory = $false)]
    [string] $TriggerFile = $(if ($env:REPLAYTROVE_INSTANT_REPLAY_TRIGGER_FILE) { $env:REPLAYTROVE_INSTANT_REPLAY_TRIGGER_FILE } else { 'C:\ReplayTrove\state\instant_replay.trigger' }),

    [switch] $Http,

    [string] $HttpHost = $(if ($env:REPLAY_TRIGGER_HTTP_HOST) { $env:REPLAY_TRIGGER_HTTP_HOST } else { '127.0.0.1' }),

    [int] $HttpPort = $(if ($env:REPLAY_TRIGGER_HTTP_PORT) { [int]$env:REPLAY_TRIGGER_HTTP_PORT } else { 0 })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-NotifyLog([string] $Message) {
    $logDir = 'C:\ReplayTrove\state'
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $logPath = Join-Path $logDir 'worker_notify_instant_replay_log.txt'
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss.fff')
    Add-Content -LiteralPath $logPath -Value "$stamp  $Message"
}

$canonicalScript = Join-Path $PSScriptRoot 'save_replay_and_trigger.ps1'
if (-not (Test-Path -LiteralPath $canonicalScript)) {
    Write-NotifyLog "compat_wrapper=fail reason=canonical_missing path=$canonicalScript"
    Write-Error "worker_notify_instant_replay: canonical script missing at $canonicalScript"
    exit 1
}

$args = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', $canonicalScript,
    '-SkipObsSave',
    '-SkipScoreboardReplayOn'
)
if ($Http) {
    if ($HttpPort -le 0) {
        Write-Error "worker_notify_instant_replay: -Http requires a port (set -HttpPort or REPLAY_TRIGGER_HTTP_PORT)."
        exit 2
    }
    $args += @(
        '-WorkerReplayHost', $HttpHost,
        '-WorkerReplayPort', ([string]$HttpPort)
    )
    Write-NotifyLog "compat_wrapper=forward mode=http host=$HttpHost port=$HttpPort"
}
else {
    $args += @(
        '-UseWorkerTriggerFile',
        '-WorkerTriggerFile', $TriggerFile
    )
    Write-NotifyLog "compat_wrapper=forward mode=trigger_file path=$TriggerFile"
}

$proc = Start-Process -FilePath powershell.exe -ArgumentList $args -Wait -PassThru
Write-NotifyLog "compat_wrapper=canonical_exit code=$($proc.ExitCode)"
exit $proc.ExitCode
