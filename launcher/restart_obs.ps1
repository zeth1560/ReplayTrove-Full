#Requires -Version 5.1
<#
.SYNOPSIS
  Stop OBS (obs64) and relaunch with the same flags ReplayTrove launcher uses.

.DESCRIPTION
  Intended for hooks from scoreboard (instant replay unavailable) or operators.
  Paths match start_apps.ps1 / launcher_ui.ps1 (override with REPLAYTROVE_OBS_* env).
#>

$ErrorActionPreference = 'Stop'

$ObsDir = if ($env:REPLAYTROVE_OBS_DIR) { $env:REPLAYTROVE_OBS_DIR } else { 'C:\Program Files\obs-studio\bin\64bit' }
$ObsExe = if ($env:REPLAYTROVE_OBS_EXE) { $env:REPLAYTROVE_OBS_EXE } else { Join-Path $ObsDir 'obs64.exe' }
$ObsSentinelRaw = if ($env:REPLAYTROVE_OBS_SENTINEL) { $env:REPLAYTROVE_OBS_SENTINEL } else { Join-Path $env:APPDATA 'obs-studio\.sentinel' }
$ObsSentinel = [Environment]::ExpandEnvironmentVariables($ObsSentinelRaw.Trim())
$obsArgs = @('--disable-shutdown-check', '--disable-missing-files-check', '--startreplaybuffer', '--verbose')

if (-not (Test-Path -LiteralPath $ObsExe)) {
  Write-Error "OBS executable not found: $ObsExe"
  exit 1
}

Get-Process -Name 'obs64' -ErrorAction SilentlyContinue | ForEach-Object {
  try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch { }
}
Start-Sleep -Milliseconds 500

if (Test-Path -LiteralPath $ObsSentinel) {
  try {
    Remove-Item -LiteralPath $ObsSentinel -Recurse -Force -ErrorAction Stop
  } catch {
    Write-Warning "Could not remove OBS sentinel: $ObsSentinel — $($_.Exception.Message)"
  }
}

Start-Process -WorkingDirectory $ObsDir -FilePath $ObsExe -ArgumentList $obsArgs -WindowStyle Minimized | Out-Null
exit 0
