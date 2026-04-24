#Requires -Version 5.1
<#
.SYNOPSIS
  Compatibility wrapper: cooldown gate + canonical replay in one action.

.DESCRIPTION
  Runs replay_gate_check.ps1, then save_replay_and_trigger.ps1 in a hidden child process.

  When the gate blocks (cooldown), exits 0 without running replay (legacy behavior so a
  single Companion action does not surface as a hard error).

  For lowest latency + two Companion steps, run replay_gate_check.ps1 then
  save_replay_and_trigger.ps1 directly (see replay_gate_check.ps1 header).
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "replaytrove_json_log.ps1")

function Log-Line($msg) {
    Write-ReplayTroveJsonl -Component 'scripts' -ScriptName 'replay_start_gate.ps1' -Event 'replay_start_gate' -Level 'INFO' -Message $msg -Data @{
        detail = $msg
    }
}

$checkScript = Join-Path $PSScriptRoot "replay_gate_check.ps1"
if (-not (Test-Path -LiteralPath $checkScript)) {
    Log-Line "compat_wrapper=fail reason=gate_check_missing path=$checkScript"
    exit 1
}

& $checkScript
$gateCode = $LASTEXITCODE
if ($gateCode -eq 1) {
    Log-Line "compat_wrapper=skipped reason=cooldown (gate exit 1)"
    exit 0
}
if ($gateCode -ne 0) {
    Log-Line "compat_wrapper=fail reason=gate_exit_code=$gateCode"
    exit $gateCode
}

$canonicalScript = Join-Path $PSScriptRoot "save_replay_and_trigger.ps1"
if (-not (Test-Path -LiteralPath $canonicalScript)) {
    Log-Line "compat_wrapper=fail reason=canonical_missing path=$canonicalScript"
    exit 1
}

Log-Line "compat_wrapper=forward canonical=$canonicalScript"
$proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", $canonicalScript
) -WindowStyle Hidden -Wait -PassThru
Log-Line "compat_wrapper=canonical_exit code=$($proc.ExitCode)"
exit $proc.ExitCode
