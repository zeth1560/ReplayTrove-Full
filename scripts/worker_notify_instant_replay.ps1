#Requires -Version 5.1
<#
.SYNOPSIS
  Compatibility wrapper for legacy worker replay notify triggers.

.DESCRIPTION
  Preserves existing interface (-Http / -TriggerFile), but delegates to the canonical
  replay entrypoint (save_replay_and_trigger.ps1) with -SkipObsSave only.

  Use when OBS SaveReplay already ran (e.g. separate hotkey). Still runs worker ingest
  and, on worker success, sends replay_on to the scoreboard (same as full pipeline).

  For when to use this vs the full canonical script, see:
  docs/operator-replay-trigger-runbook.md
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

. (Join-Path $PSScriptRoot 'replaytrove_json_log.ps1')

function Write-NotifyLog([string] $Message) {
    Write-ReplayTroveJsonl -Component 'scripts' -ScriptName 'worker_notify_instant_replay.ps1' -Event 'worker_notify' -Level 'INFO' -Message $Message -Data @{
        detail = $Message
    }
}

function Resolve-HttpReplayPortFromUnified {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $defaultPath = Join-Path $repoRoot 'config\settings.json'
    $cfgPath = if (-not [string]::IsNullOrWhiteSpace($env:REPLAYTROVE_SETTINGS_FILE)) { $env:REPLAYTROVE_SETTINGS_FILE } else { $defaultPath }
    if (-not (Test-Path -LiteralPath $cfgPath)) {
        return @{ Port = $null; Path = $cfgPath }
    }
    try {
        $j = Get-Content -LiteralPath $cfgPath -Raw | ConvertFrom-Json -ErrorAction Stop
        $p = $j.worker.httpReplayTriggerPort
        return @{ Port = $p; Path = $cfgPath }
    } catch {
        return @{ Port = $null; Path = $cfgPath }
    }
}

$canonicalScript = Join-Path $PSScriptRoot 'save_replay_and_trigger.ps1'
if (-not (Test-Path -LiteralPath $canonicalScript)) {
    Write-NotifyLog "compat_wrapper=fail reason=canonical_missing path=$canonicalScript"
    Write-Error "worker_notify_instant_replay: canonical script missing at $canonicalScript"
    exit 1
}

$args = @(
    '-NoProfile',
    '-WindowStyle', 'Hidden',
    '-ExecutionPolicy', 'Bypass',
    '-File', $canonicalScript,
    '-SkipObsSave'
)
if ($Http) {
    if ($HttpPort -le 0) {
        $unified = Resolve-HttpReplayPortFromUnified
        $portSource = 'default_18765'
        if ($null -ne $unified.Port) {
            try {
                $HttpPort = [int]$unified.Port
                $portSource = 'unified_settings'
            } catch {
                $HttpPort = 0
            }
        }
        if ($HttpPort -le 0) {
            $HttpPort = 18765
            $portSource = 'default_18765'
        }
        Write-NotifyLog ("compat_wrapper=http_port_resolved port={0} source={1} cfg={2}" -f $HttpPort, $portSource, $unified.Path)
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

$proc = Start-Process -FilePath powershell.exe -ArgumentList $args -WindowStyle Hidden -Wait -PassThru
Write-NotifyLog "compat_wrapper=canonical_exit code=$($proc.ExitCode)"
exit $proc.ExitCode
