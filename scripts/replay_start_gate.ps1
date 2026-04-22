#Requires -Version 5.1
<#
.SYNOPSIS
  Compatibility wrapper for legacy replay start gate trigger.

.DESCRIPTION
  This script preserves the cooldown-gate interface used by existing operator tooling,
  but delegates replay orchestration to the canonical script:
    scripts/save_replay_and_trigger.ps1
#>

$lockPath = "C:\ReplayTrove\state\replay_lock.txt"
$logPath = "C:\ReplayTrove\state\replay_start_gate_log.txt"
$cooldownSeconds = 30

function Log-Line($msg) {
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss.fff")
    $logDir = Split-Path -Parent $logPath
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    Add-Content -LiteralPath $logPath -Value "$stamp  $msg"
}

$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
Log-Line "compat_wrapper=start now=$now"

if (Test-Path -LiteralPath $lockPath) {
    try {
        $lastRaw = (Get-Content -LiteralPath $lockPath | Select-Object -First 1).Trim()
        $last = [int64]$lastRaw
        $elapsedSinceLock = $now - $last
        if ($elapsedSinceLock -lt $cooldownSeconds) {
            $remaining = $cooldownSeconds - $elapsedSinceLock
            Log-Line "compat_wrapper=blocked reason=cooldown remaining=${remaining}s"
            exit 0
        }
    }
    catch {
        Log-Line "compat_wrapper=blocked reason=lock_parse_failed error=$($_.Exception.Message)"
        exit 1
    }
}

$canonicalScript = Join-Path $PSScriptRoot "save_replay_and_trigger.ps1"
if (-not (Test-Path -LiteralPath $canonicalScript)) {
    Log-Line "compat_wrapper=fail reason=canonical_missing path=$canonicalScript"
    exit 1
}

Log-Line "compat_wrapper=forward canonical=$canonicalScript"
$proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $canonicalScript
) -Wait -PassThru
Log-Line "compat_wrapper=canonical_exit code=$($proc.ExitCode)"
exit $proc.ExitCode