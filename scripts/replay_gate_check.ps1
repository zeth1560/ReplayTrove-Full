#Requires -Version 5.1
<#
.SYNOPSIS
  30-second replay cooldown gate (Companion / Stream Deck step 1 of 2).

.DESCRIPTION
  Run this first from a button; run save_replay_and_trigger.ps1 second only if this exits 0.

  Exit codes:
    0  Allowed — lock file updated; run the canonical replay script next.
    1  Blocked — still inside cooldown (Companion should skip step 2).
    2  Lock file present but unreadable (misconfigured).

  The legacy replay_start_gate.ps1 still works as a single action; it calls this script
  then spawns the canonical script (blocked path exits 0 for backward compatibility).

  Lock path: C:\ReplayTrove\state\replay_lock.txt (first line = Unix epoch seconds).
#>
param(
    [int]$CooldownSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "replaytrove_json_log.ps1")

$lockPath = "C:\ReplayTrove\state\replay_lock.txt"

function Write-GateLog([string]$msg) {
    Write-ReplayTroveJsonl -Component 'scripts' -ScriptName 'replay_gate_check.ps1' -Event 'replay_gate_check' -Level 'INFO' -Message $msg -Data @{
        detail = $msg
        phase  = 'gate_check'
    }
}

$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
Write-GateLog "start now=$now cooldown_sec=$CooldownSeconds"

if (Test-Path -LiteralPath $lockPath) {
    try {
        $lastRaw = (Get-Content -LiteralPath $lockPath | Select-Object -First 1).Trim()
        $last = [int64]$lastRaw
        $elapsedSinceLock = $now - $last
        if ($elapsedSinceLock -lt $CooldownSeconds) {
            $remaining = $CooldownSeconds - $elapsedSinceLock
            Write-GateLog "blocked cooldown remaining_s=$remaining"
            exit 1
        }
    }
    catch {
        Write-GateLog "error lock_parse_failed $($_.Exception.Message)"
        exit 2
    }
}

$lockDir = Split-Path -Parent $lockPath
if (-not (Test-Path -LiteralPath $lockDir)) {
    New-Item -ItemType Directory -Path $lockDir -Force | Out-Null
}
Set-Content -LiteralPath $lockPath -Value ([string]$now) -Encoding ascii
Write-GateLog "allowed lock_written=$now"
exit 0
