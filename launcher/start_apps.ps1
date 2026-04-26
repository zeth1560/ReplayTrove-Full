#Requires -Version 5.1
<#
.SYNOPSIS
  ReplayTrove launcher / supervisor: start apps, wait for readiness, validate processes, UI tweaks.

  Configure paths via environment (set in start_apps.bat) or defaults below.
  REPLAYTROVE_LAUNCHER_DEBUG=1  -> python.exe + Normal windows (easier troubleshooting).
  Production: pythonw; worker/encoder Hidden; scoreboard Minimized (Tk must not use Hidden); OBS Normal.
  REPLAYTROVE_PAUSE_ON_ERROR=0 -> do not pause on validation failure (e.g. scheduled task).

  When Scoreboard, Encoder, and OBS are all enabled, an interactive session keeps running after
  validation and polls scoreboard_status.json (screensaver_active). Screensaver on stops Encoder+OBS;
  screensaver off restarts them. REPLAYTROVE_SCOREBOARD_STATUS_WATCH=0 disables; =1 forces on.

  Scoreboard focus diagnostics: REPLAYTROVE_SCOREBOARD_STATUS_STALE_SEC (default 60) treats
  scoreboard_status.json updated_at older than N seconds as stale. Optional one-shot restore:
  REPLAYTROVE_SCOREBOARD_FOCUS_RECOVERY=1 after failed focus attempts (conservative; default off).
#>

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'unified_config_adapter.ps1')

$script:UnifiedResolutionNotes = @()
$script:DesiredStateMap = $null
$UnifiedSnapshot = Get-ReplayTroveUnifiedConfig
$UnifiedData = if ($UnifiedSnapshot.Data -is [System.Collections.IDictionary]) { $UnifiedSnapshot.Data } else { @{} }
$UnifiedRoot = Get-UnifiedNestedValue -Object $UnifiedData -Path 'general.replayTroveRoot'
if (-not ($UnifiedRoot -is [string]) -or [string]::IsNullOrWhiteSpace($UnifiedRoot)) {
  $UnifiedRoot = 'C:\ReplayTrove'
}
$UnifiedRoot = $UnifiedRoot.Trim()

# --- Config (override with env vars from start_apps.bat) ---
$WorkerDirObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.workerDir' -EnvName 'REPLAYTROVE_WORKER_DIR' -Default (Join-Path $UnifiedRoot 'worker') -Label 'WorkerDir'
$WorkerDir = $WorkerDirObj.Value
$script:UnifiedResolutionNotes += "$($WorkerDirObj.Label)=$($WorkerDirObj.Source)"
$ScoreboardDirObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.scoreboardDir' -EnvName 'REPLAYTROVE_SCOREBOARD_DIR' -Default (Join-Path $UnifiedRoot 'scoreboard') -Label 'ScoreboardDir'
$ScoreboardDir = $ScoreboardDirObj.Value
$script:UnifiedResolutionNotes += "$($ScoreboardDirObj.Label)=$($ScoreboardDirObj.Source)"
$EncoderDirObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.encoderDir' -EnvName 'REPLAYTROVE_ENCODER_DIR' -Default (Join-Path $UnifiedRoot 'encoder') -Label 'EncoderDir'
$EncoderDir = $EncoderDirObj.Value
$script:UnifiedResolutionNotes += "$($EncoderDirObj.Label)=$($EncoderDirObj.Source)"
$CleanerScriptObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.cleanerScript' -EnvName 'REPLAYTROVE_CLEANER_SCRIPT' -Default (Join-Path $UnifiedRoot 'cleaner\cleaner-bee.ps1') -Label 'CleanerScript'
$CleanerScript = $CleanerScriptObj.Value
$script:UnifiedResolutionNotes += "$($CleanerScriptObj.Label)=$($CleanerScriptObj.Source)"
$LauncherUiBatObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.launcherUiBat' -EnvName 'REPLAYTROVE_LAUNCHER_UI_BAT' -Default (Join-Path $PSScriptRoot 'launcher_ui.bat') -Label 'LauncherUiBat'
$LauncherUiBat = $LauncherUiBatObj.Value
$script:UnifiedResolutionNotes += "$($LauncherUiBatObj.Label)=$($LauncherUiBatObj.Source)"
$ObsDirObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.obsDir' -EnvName 'REPLAYTROVE_OBS_DIR' -Default 'C:\Program Files\obs-studio\bin\64bit' -Label 'ObsDir'
$ObsDir = $ObsDirObj.Value
$script:UnifiedResolutionNotes += "$($ObsDirObj.Label)=$($ObsDirObj.Source)"
$ObsExeObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'obsFfmpegPaths.obsExecutable' -EnvName 'REPLAYTROVE_OBS_EXE' -Default (Join-Path $ObsDir 'obs64.exe') -Label 'ObsExe'
$ObsExe = $ObsExeObj.Value
$script:UnifiedResolutionNotes += "$($ObsExeObj.Label)=$($ObsExeObj.Source)"
$ObsSentinelObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.obsSentinelPath' -EnvName 'REPLAYTROVE_OBS_SENTINEL' -Default (Join-Path $env:APPDATA 'obs-studio\.sentinel') -Label 'ObsSentinel'
# Config stores e.g. %APPDATA%\obs-studio\.sentinel — must expand or OBS keeps the crash sentinel and shows Safe/Normal mode (OBS 32+ removed --disable-shutdown-check).
$ObsSentinel = [Environment]::ExpandEnvironmentVariables($ObsSentinelObj.Value.Trim())
$script:UnifiedResolutionNotes += "$($ObsSentinelObj.Label)=$($ObsSentinelObj.Source)"

$DebugModeObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.debugMode' -EnvName 'REPLAYTROVE_LAUNCHER_DEBUG' -Default $false -Label 'DebugMode'
$DebugMode = $DebugModeObj.Value
$script:UnifiedResolutionNotes += "$($DebugModeObj.Label)=$($DebugModeObj.Source)"
$PauseOnErrorObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.pauseOnError' -EnvName 'REPLAYTROVE_PAUSE_ON_ERROR' -Default $true -Label 'PauseOnError'
$PauseOnError = $PauseOnErrorObj.Value
$script:UnifiedResolutionNotes += "$($PauseOnErrorObj.Label)=$($PauseOnErrorObj.Source)"

function Test-AppEnabled {
  param(
    [string]$Name,
    [bool]$Default = $true
  )
  $raw = [Environment]::GetEnvironmentVariable("REPLAYTROVE_ENABLE_$Name")
  if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
  switch ($raw.Trim().ToLowerInvariant()) {
    '1' { return $true }
    'true' { return $true }
    'yes' { return $true }
    'on' { return $true }
    '0' { return $false }
    'false' { return $false }
    'no' { return $false }
    'off' { return $false }
    default { return $Default }
  }
}

$EnableWorkerObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.enableWorker' -EnvName 'REPLAYTROVE_ENABLE_WORKER' -Default $true -Label 'EnableWorker'
$EnableWorker = $EnableWorkerObj.Value
$script:UnifiedResolutionNotes += "$($EnableWorkerObj.Label)=$($EnableWorkerObj.Source)"
$EnableEncoderObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.enableEncoder' -EnvName 'REPLAYTROVE_ENABLE_ENCODER' -Default $true -Label 'EnableEncoder'
$EnableEncoder = $EnableEncoderObj.Value
$script:UnifiedResolutionNotes += "$($EnableEncoderObj.Label)=$($EnableEncoderObj.Source)"
$EnableCleanerObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.enableCleaner' -EnvName 'REPLAYTROVE_ENABLE_CLEANER' -Default $true -Label 'EnableCleaner'
$EnableCleaner = $EnableCleanerObj.Value
$script:UnifiedResolutionNotes += "$($EnableCleanerObj.Label)=$($EnableCleanerObj.Source)"
$EnableObsObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.enableObs' -EnvName 'REPLAYTROVE_ENABLE_OBS' -Default $true -Label 'EnableObs'
$EnableObs = $EnableObsObj.Value
$script:UnifiedResolutionNotes += "$($EnableObsObj.Label)=$($EnableObsObj.Source)"
$rawEnableControlApp = [Environment]::GetEnvironmentVariable('REPLAYTROVE_ENABLE_CONTROL_APP')
$defaultEnableControlApp = if ([string]::IsNullOrWhiteSpace($rawEnableControlApp)) { Test-AppEnabled -Name 'STREAMDECK' } else { Test-AppEnabled -Name 'CONTROL_APP' }
$EnableControlAppObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.enableControlApp' -EnvName 'REPLAYTROVE_ENABLE_CONTROL_APP' -Default $defaultEnableControlApp -Label 'EnableControlApp'
$EnableControlApp = $EnableControlAppObj.Value
$script:UnifiedResolutionNotes += "$($EnableControlAppObj.Label)=$($EnableControlAppObj.Source)"
$EnableScoreboardObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.enableScoreboard' -EnvName 'REPLAYTROVE_ENABLE_SCOREBOARD' -Default $true -Label 'EnableScoreboard'
$EnableScoreboard = $EnableScoreboardObj.Value
$script:UnifiedResolutionNotes += "$($EnableScoreboardObj.Label)=$($EnableScoreboardObj.Source)"
$EnableLauncherUiObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.enableLauncherUi' -EnvName 'REPLAYTROVE_ENABLE_LAUNCHER_UI' -Default $true -Label 'EnableLauncherUi'
$EnableLauncherUi = $EnableLauncherUiObj.Value
$script:UnifiedResolutionNotes += "$($EnableLauncherUiObj.Label)=$($EnableLauncherUiObj.Source)"

# Control surface app (Bitfocus Companion, Elgato Stream Deck, etc.). New env vars take precedence; legacy Stream Deck vars used when unset.
$ControlAppExeObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.controlAppExe' -EnvName 'REPLAYTROVE_CONTROL_APP_EXE' -Default ($(if ($env:REPLAYTROVE_STREAMDECK_EXE) { $env:REPLAYTROVE_STREAMDECK_EXE } else { 'C:\Program Files\Elgato\StreamDeck\StreamDeck.exe' })) -Label 'ControlAppExe'
$ControlAppExe = $ControlAppExeObj.Value
$script:UnifiedResolutionNotes += "$($ControlAppExeObj.Label)=$($ControlAppExeObj.Source)"
$ControlAppProcessNameObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.controlAppProcessName' -EnvName 'REPLAYTROVE_CONTROL_APP_NAME' -Default 'StreamDeck' -Label 'ControlAppProcessName'
$ControlAppProcessName = $ControlAppProcessNameObj.Value
$script:UnifiedResolutionNotes += "$($ControlAppProcessNameObj.Label)=$($ControlAppProcessNameObj.Source)"
$ControlAppArgsObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.controlAppArgs' -EnvName 'REPLAYTROVE_CONTROL_APP_ARGS' -Default '' -Label 'ControlAppArgs'
$ControlAppArgs = $ControlAppArgsObj.Value
$script:UnifiedResolutionNotes += "$($ControlAppArgsObj.Label)=$($ControlAppArgsObj.Source)"

$ReadinessObsSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.readinessObsSec' -EnvName 'REPLAYTROVE_READINESS_OBS_SEC' -Default 120 -Minimum 1 -Label 'ReadinessObsSec'
$ReadinessObsSec = $ReadinessObsSecObj.Value
$script:UnifiedResolutionNotes += "$($ReadinessObsSecObj.Label)=$($ReadinessObsSecObj.Source)"
$ReadinessPythonSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.readinessPythonSec' -EnvName 'REPLAYTROVE_READINESS_PYTHON_SEC' -Default 90 -Minimum 1 -Label 'ReadinessPythonSec'
$ReadinessPythonSec = $ReadinessPythonSecObj.Value
$script:UnifiedResolutionNotes += "$($ReadinessPythonSecObj.Label)=$($ReadinessPythonSecObj.Source)"
$ReadinessIntervalSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.readinessIntervalSec' -EnvName 'REPLAYTROVE_READINESS_INTERVAL_SEC' -Default 1 -Minimum 1 -Label 'ReadinessIntervalSec'
$ReadinessIntervalSec = $ReadinessIntervalSecObj.Value
$script:UnifiedResolutionNotes += "$($ReadinessIntervalSecObj.Label)=$($ReadinessIntervalSecObj.Source)"
$FocusMaxAttemptsObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.focusMaxAttempts' -EnvName 'REPLAYTROVE_FOCUS_MAX_ATTEMPTS' -Default 40 -Minimum 1 -Label 'FocusMaxAttempts'
$FocusMaxAttempts = $FocusMaxAttemptsObj.Value
$script:UnifiedResolutionNotes += "$($FocusMaxAttemptsObj.Label)=$($FocusMaxAttemptsObj.Source)"
$FocusRetryMsObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.focusRetryMs' -EnvName 'REPLAYTROVE_FOCUS_RETRY_MS' -Default 500 -Minimum 10 -Label 'FocusRetryMs'
$FocusRetryMs = $FocusRetryMsObj.Value
$script:UnifiedResolutionNotes += "$($FocusRetryMsObj.Label)=$($FocusRetryMsObj.Source)"
$ScoreboardStatusStaleSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.scoreboardStatusStaleSec' -EnvName 'REPLAYTROVE_SCOREBOARD_STATUS_STALE_SEC' -Default 60 -Minimum 1 -Label 'ScoreboardStatusStaleSec'
$ScoreboardStatusStaleSec = $ScoreboardStatusStaleSecObj.Value
$script:UnifiedResolutionNotes += "$($ScoreboardStatusStaleSecObj.Label)=$($ScoreboardStatusStaleSecObj.Source)"
$ScoreboardFocusRecoveryObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.scoreboardFocusRecovery' -EnvName 'REPLAYTROVE_SCOREBOARD_FOCUS_RECOVERY' -Default $false -Label 'ScoreboardFocusRecovery'
$ScoreboardFocusRecovery = $ScoreboardFocusRecoveryObj.Value
$script:UnifiedResolutionNotes += "$($ScoreboardFocusRecoveryObj.Label)=$($ScoreboardFocusRecoveryObj.Source)"

$ScoreboardStatusJsonObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.scoreboardStatusJsonPath' -EnvName 'REPLAYTROVE_SCOREBOARD_STATUS_JSON' -Default (Join-Path $PSScriptRoot 'scoreboard_status.json') -Label 'ScoreboardStatusJson'
$ScoreboardStatusJson = $ScoreboardStatusJsonObj.Value
$script:UnifiedResolutionNotes += "$($ScoreboardStatusJsonObj.Label)=$($ScoreboardStatusJsonObj.Source)"
$ScoreboardStatusPollSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.scoreboardStatusPollSec' -EnvName 'REPLAYTROVE_SCOREBOARD_STATUS_POLL_SEC' -Default 2 -Minimum 1 -Label 'ScoreboardStatusPollSec'
$ScoreboardStatusPollSec = $ScoreboardStatusPollSecObj.Value
$script:UnifiedResolutionNotes += "$($ScoreboardStatusPollSecObj.Label)=$($ScoreboardStatusPollSecObj.Source)"
$ScoreboardStatusWatchDefault = [Environment]::UserInteractive
$ScoreboardStatusWatchObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.scoreboardStatusWatch' -EnvName 'REPLAYTROVE_SCOREBOARD_STATUS_WATCH' -Default $ScoreboardStatusWatchDefault -Label 'ScoreboardStatusWatch'
$ScoreboardStatusWatch = $ScoreboardStatusWatchObj.Value
$script:UnifiedResolutionNotes += "$($ScoreboardStatusWatchObj.Label)=$($ScoreboardStatusWatchObj.Source)"
$CleanerOwnerModeObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'launcher.cleanerOwnerMode' -EnvName 'REPLAYTROVE_CLEANER_OWNER_MODE' -Default 'task_scheduler' -Label 'CleanerOwnerMode'
$CleanerOwnerMode = $CleanerOwnerModeObj.Value.Trim().ToLowerInvariant()
if ($CleanerOwnerMode -notin @('task_scheduler', 'launcher')) {
  $CleanerOwnerMode = 'task_scheduler'
}
$script:UnifiedResolutionNotes += "$($CleanerOwnerModeObj.Label)=$($CleanerOwnerModeObj.Source)"
$SupervisionEnabledObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'launcher.supervisionEnabled' -EnvName 'REPLAYTROVE_SUPERVISION_ENABLED' -Default $true -Label 'SupervisionEnabled'
$SupervisionEnabled = $SupervisionEnabledObj.Value
$script:UnifiedResolutionNotes += "$($SupervisionEnabledObj.Label)=$($SupervisionEnabledObj.Source)"
$SupervisionPollSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.supervisionPollSec' -EnvName 'REPLAYTROVE_SUPERVISION_POLL_SEC' -Default 5 -Minimum 1 -Label 'SupervisionPollSec'
$SupervisionPollSec = $SupervisionPollSecObj.Value
$script:UnifiedResolutionNotes += "$($SupervisionPollSecObj.Label)=$($SupervisionPollSecObj.Source)"
$SupervisionMaxRestartsPerWindowObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.supervisionMaxRestartsPerWindow' -EnvName 'REPLAYTROVE_SUPERVISION_MAX_RESTARTS_PER_WINDOW' -Default 6 -Minimum 1 -Label 'SupervisionMaxRestartsPerWindow'
$SupervisionMaxRestartsPerWindow = $SupervisionMaxRestartsPerWindowObj.Value
$script:UnifiedResolutionNotes += "$($SupervisionMaxRestartsPerWindowObj.Label)=$($SupervisionMaxRestartsPerWindowObj.Source)"
$SupervisionWindowSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.supervisionWindowSec' -EnvName 'REPLAYTROVE_SUPERVISION_WINDOW_SEC' -Default 300 -Minimum 10 -Label 'SupervisionWindowSec'
$SupervisionWindowSec = $SupervisionWindowSecObj.Value
$script:UnifiedResolutionNotes += "$($SupervisionWindowSecObj.Label)=$($SupervisionWindowSecObj.Source)"
$SupervisionBaseBackoffSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'launcher.supervisionBaseBackoffSec' -EnvName 'REPLAYTROVE_SUPERVISION_BASE_BACKOFF_SEC' -Default 5 -Minimum 1 -Label 'SupervisionBaseBackoffSec'
$SupervisionBaseBackoffSec = $SupervisionBaseBackoffSecObj.Value
$script:UnifiedResolutionNotes += "$($SupervisionBaseBackoffSecObj.Label)=$($SupervisionBaseBackoffSecObj.Source)"
$WorkerStatusJsonPathObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'worker.workerStatusJsonPath' -EnvName 'WORKER_STATUS_JSON_PATH' -Default (Join-Path $UnifiedRoot 'status.json') -Label 'WorkerStatusJsonPath'
$WorkerStatusJsonPath = $WorkerStatusJsonPathObj.Value
$script:UnifiedResolutionNotes += "$($WorkerStatusJsonPathObj.Label)=$($WorkerStatusJsonPathObj.Source)"
$WorkerStatusWriteIntervalSecObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'worker.workerStatusWriteIntervalSeconds' -EnvName 'WORKER_STATUS_WRITE_INTERVAL_SECONDS' -Default 5 -Minimum 1 -Label 'WorkerStatusWriteIntervalSec'
$WorkerStatusWriteIntervalSec = $WorkerStatusWriteIntervalSecObj.Value
$script:UnifiedResolutionNotes += "$($WorkerStatusWriteIntervalSecObj.Label)=$($WorkerStatusWriteIntervalSecObj.Source)"
$WorkerReplayHostObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'worker.httpReplayTriggerHost' -EnvName 'REPLAY_TRIGGER_HTTP_HOST' -Default '127.0.0.1' -Label 'WorkerReplayHost'
$WorkerReplayHost = $WorkerReplayHostObj.Value
$script:UnifiedResolutionNotes += "$($WorkerReplayHostObj.Label)=$($WorkerReplayHostObj.Source)"
$WorkerReplayPortObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'worker.httpReplayTriggerPort' -EnvName 'REPLAY_TRIGGER_HTTP_PORT' -Default 18765 -Minimum 1 -Label 'WorkerReplayPort'
$WorkerReplayPort = $WorkerReplayPortObj.Value
$script:UnifiedResolutionNotes += "$($WorkerReplayPortObj.Label)=$($WorkerReplayPortObj.Source)"
$WorkerReplayTriggerEnabledObj = Resolve-UnifiedFirstBool -UnifiedData $UnifiedData -UnifiedPath 'worker.httpReplayTriggerEnabled' -EnvName 'REPLAYTROVE_WORKER_REPLAY_TRIGGER_ENABLED' -Default $true -Label 'WorkerReplayTriggerEnabled'
$WorkerReplayTriggerEnabled = $WorkerReplayTriggerEnabledObj.Value
$script:UnifiedResolutionNotes += "$($WorkerReplayTriggerEnabledObj.Label)=$($WorkerReplayTriggerEnabledObj.Source)"
$ObsWebsocketHostObj = Resolve-UnifiedFirstString -UnifiedData $UnifiedData -UnifiedPath 'scoreboard.obsWebsocketHost' -EnvName 'OBS_WEBSOCKET_HOST' -Default 'localhost' -Label 'ObsWebsocketHost'
$ObsWebsocketHost = $ObsWebsocketHostObj.Value
$script:UnifiedResolutionNotes += "$($ObsWebsocketHostObj.Label)=$($ObsWebsocketHostObj.Source)"
$ObsWebsocketPortObj = Resolve-UnifiedFirstInt -UnifiedData $UnifiedData -UnifiedPath 'scoreboard.obsWebsocketPort' -EnvName 'OBS_WEBSOCKET_PORT' -Default 4455 -Minimum 1 -Label 'ObsWebsocketPort'
$ObsWebsocketPort = $ObsWebsocketPortObj.Value
$script:UnifiedResolutionNotes += "$($ObsWebsocketPortObj.Label)=$($ObsWebsocketPortObj.Source)"
$WorkerStatusStaleSec = [Math]::Max(15, $WorkerStatusWriteIntervalSec * 3)
$SupervisionStatusPath = Join-Path $PSScriptRoot 'supervision_status.json'
$SupervisionOwnerLeasePath = Join-Path $PSScriptRoot 'supervision_owner_lease.json'
$SupervisionDesiredStatePath = Join-Path $PSScriptRoot 'supervision_desired_state.json'
$LauncherIntentsRoot = Join-Path $PSScriptRoot 'intents'
$LauncherIntentsPendingDir = Join-Path $LauncherIntentsRoot 'pending'
$LauncherIntentsProcessedDir = Join-Path $LauncherIntentsRoot 'processed'
$LauncherIntentsFailedDir = Join-Path $LauncherIntentsRoot 'failed'
$ScoreboardWindowTitle = 'ReplayTrove Scoreboard'

$CentralLogsRoot = Join-Path $UnifiedRoot 'logs'
$env:REPLAYTROVE_LOGS_ROOT = $CentralLogsRoot
New-Item -ItemType Directory -Force -Path $CentralLogsRoot | Out-Null
. (Join-Path $UnifiedRoot 'scripts\replaytrove_json_log.ps1')
$script:OwnerLeaseId = [guid]::NewGuid().ToString('N')
$script:OwnerLeaseCreatedAtUtc = [DateTime]::UtcNow
$script:OwnerLeaseClaimed = $false
$OwnerLeaseStaleSec = [Math]::Max(20, $SupervisionPollSec * 3)

function Write-LauncherLog {
  param([string]$Message)
  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $Message
  Write-Host $line
  try {
    Write-ReplayTroveJsonl -Component 'launcher' -Event 'log' -Level 'INFO' -Message $Message -Data @{
      unified_root = $UnifiedRoot
    }
  }
  catch {
    Write-Host "[WARN] central JSONL log failed: $($_.Exception.Message)"
  }
}

function Test-ProcessIdAlive {
  param([object]$Pid)
  try {
    $pidNum = [int]$Pid
    return $null -ne (Get-Process -Id $pidNum -ErrorAction SilentlyContinue)
  } catch {
    return $false
  }
}

function Read-OwnerLease {
  if (-not (Test-Path -LiteralPath $SupervisionOwnerLeasePath)) {
    return $null
  }
  try {
    $raw = Get-Content -LiteralPath $SupervisionOwnerLeasePath -Raw -ErrorAction Stop
    $obj = $raw | ConvertFrom-Json -ErrorAction Stop
    return $obj
  } catch {
    Write-LauncherLog "SUPERVISION OWNER LEASE WARN: failed reading lease file: $($_.Exception.Message)"
    return $null
  }
}

function Write-OwnerLease {
  param([string]$Reason = 'refresh')
  $payload = [ordered]@{
    owner_id = $script:OwnerLeaseId
    pid = $PID
    hostname = [Environment]::MachineName
    created_at = $script:OwnerLeaseCreatedAtUtc.ToString('o')
    updated_at = [DateTime]::UtcNow.ToString('o')
    lease_timeout_sec = $OwnerLeaseStaleSec
    reason = $Reason
  }
  try {
    $tmpPath = "$SupervisionOwnerLeasePath.tmp"
    $json = $payload | ConvertTo-Json -Depth 6
    Set-Content -LiteralPath $tmpPath -Encoding UTF8 -Value $json
    Move-Item -LiteralPath $tmpPath -Destination $SupervisionOwnerLeasePath -Force
    return $true
  } catch {
    Write-LauncherLog "SUPERVISION OWNER LEASE ERROR: failed writing lease: $($_.Exception.Message)"
    return $false
  }
}

function Release-OwnerLease {
  param([string]$Reason = 'shutdown')
  if (-not $script:OwnerLeaseClaimed) {
    return
  }
  if ([string]::IsNullOrWhiteSpace($Reason)) {
    $Reason = 'shutdown'
  }
  $ok = Write-OwnerLease -Reason $Reason
  if ($ok) {
    Write-LauncherLog "SUPERVISION OWNER LEASE: gracefully released reason=$Reason owner_id=$($script:OwnerLeaseId)"
  } else {
    Write-LauncherLog "SUPERVISION OWNER LEASE WARN: graceful release write failed reason=$Reason"
  }
}

function Try-ClaimOwnerLease {
  $existing = Read-OwnerLease
  if ($null -eq $existing) {
    Write-LauncherLog "SUPERVISION OWNER LEASE: no existing lease found; claiming ownership."
    $ok = Write-OwnerLease -Reason 'initial_claim_no_existing_lease'
    if ($ok) { $script:OwnerLeaseClaimed = $true }
    return $ok
  }

  $existingOwner = [string]($existing.owner_id)
  $existingPid = $existing.pid
  $existingUpdated = $null
  if ($existing.updated_at) {
    $dt = [DateTime]::MinValue
    if ([DateTime]::TryParse([string]$existing.updated_at, [ref]$dt)) {
      $existingUpdated = $dt.ToUniversalTime()
    }
  }
  $ageSec = if ($null -eq $existingUpdated) { [double]::PositiveInfinity } else { ([DateTime]::UtcNow - $existingUpdated).TotalSeconds }
  $existingPidAlive = Test-ProcessIdAlive -Pid $existingPid
  $fresh = ($ageSec -le $OwnerLeaseStaleSec)
  $occupied = ($fresh -and $existingPidAlive -and $existingOwner -ne $script:OwnerLeaseId)

  if ($occupied) {
    Write-LauncherLog ("SUPERVISION OWNER LEASE: startup refused; active owner exists owner_id={0} pid={1} age_sec={2:0.0} timeout_sec={3}" -f $existingOwner, $existingPid, $ageSec, $OwnerLeaseStaleSec)
    return $false
  }

  $existingReason = [string]($existing.reason)
  if ($existingReason -in @('shutdown', 'stopped_by_operator', 'supervision_disabled')) {
    Write-LauncherLog ("SUPERVISION OWNER LEASE: prior graceful shutdown marker detected reason={0} owner_id={1} pid={2}" -f $existingReason, $existingOwner, $existingPid)
  }

  if (-not $fresh) {
    Write-LauncherLog ("SUPERVISION OWNER LEASE: reclaiming stale lease owner_id={0} pid={1} age_sec={2:0.0} timeout_sec={3}" -f $existingOwner, $existingPid, $ageSec, $OwnerLeaseStaleSec)
  } elseif (-not $existingPidAlive) {
    Write-LauncherLog ("SUPERVISION OWNER LEASE: reclaiming lease from dead pid owner_id={0} pid={1}" -f $existingOwner, $existingPid)
  } else {
    Write-LauncherLog "SUPERVISION OWNER LEASE: replacing unreadable or incomplete lease ownership."
  }
  $ok = Write-OwnerLease -Reason 'reclaim_or_replace'
  if ($ok) { $script:OwnerLeaseClaimed = $true }
  return $ok
}

Write-LauncherLog ("Unified config status: found={0} path={1} schema_version={2} migrated={3} general_section={4} launcher_section={5} obsffmpeg_section={6}" -f `
  $UnifiedSnapshot.Found, `
  $UnifiedSnapshot.Path, `
  $UnifiedSnapshot.SchemaVersion, `
  $UnifiedSnapshot.Migrated, `
  $UnifiedSnapshot.GeneralLoaded, `
  $UnifiedSnapshot.LauncherLoaded, `
  $UnifiedSnapshot.ObsFfmpegLoaded)
if ($UnifiedSnapshot.Error) {
  Write-LauncherLog "Unified config parse error: $($UnifiedSnapshot.Error)"
}
if ($script:UnifiedResolutionNotes.Count -gt 0) {
  Write-LauncherLog ("Config source resolution: " + ($script:UnifiedResolutionNotes -join ', '))
  $fallback = @($script:UnifiedResolutionNotes | Where-Object { $_ -notlike '*=unified' })
  if ($fallback.Count -gt 0) {
    Write-LauncherLog ("Config fallback in use: " + ($fallback -join ', '))
  }
}
Write-LauncherLog "Ownership mode: launcher is primary runtime owner for worker/scoreboard/encoder_watchdog/obs."
Write-LauncherLog "Cleaner owner mode: $CleanerOwnerMode (enableCleaner=$EnableCleaner)"

function Wait-LauncherAck {
  param([string]$Prompt)
  if (-not $PauseOnError) { return }
  if (-not [Environment]::UserInteractive) {
    Write-LauncherLog 'Pause skipped (non-interactive session).'
    return
  }
  Read-Host $Prompt | Out-Null
}

function Get-PythonInterpreter {
  param([string]$AppDir)
  $scripts = Join-Path $AppDir '.venv\Scripts'
  $pyw = Join-Path $scripts 'pythonw.exe'
  $py = Join-Path $scripts 'python.exe'
  if ($DebugMode) {
    return $py
  }
  if (Test-Path -LiteralPath $pyw) {
    return $pyw
  }
  if (Test-Path -LiteralPath $py) {
    Write-LauncherLog "WARN: pythonw.exe not found at $pyw; using python.exe (windowless workers prefer pythonw — repair venv if consoles appear)"
    return $py
  }
  return $pyw
}

function Normalize-AppDirectoryPath {
  param([string]$FolderPath)
  if ([string]::IsNullOrWhiteSpace($FolderPath)) { return $null }
  try {
    $full = [System.IO.Path]::GetFullPath($FolderPath)
  } catch {
    $full = $FolderPath
  }
  return (($full -replace '/', '\').TrimEnd('\'))
}

function Test-PythonProcessMatchesAppDir {
  param(
    $Proc,
    [string]$AppDirNormalized,
    [string]$ScriptName
  )
  if (-not $AppDirNormalized) { return $false }
  $dirLower = $AppDirNormalized.ToLowerInvariant()
  $prefix = "$dirLower\"
  $scriptLower = $ScriptName.ToLowerInvariant()
  $leafLower = [System.IO.Path]::GetFileName($AppDirNormalized).ToLowerInvariant()
  $leafNeedle = if ($leafLower) { '\' + $leafLower + '\' } else { $null }
  $cmd = $Proc.CommandLine
  if ($cmd) {
    $cn = ($cmd -replace '/', '\').ToLowerInvariant()
    if ($cn.Contains($prefix) -and $cn.Contains($scriptLower)) { return $true }
    if ($leafNeedle -and $cn.Contains($leafNeedle) -and $cn.Contains($scriptLower)) { return $true }
  }
  $exe = $Proc.ExecutablePath
  if ($exe) {
    try {
      $en = [System.IO.Path]::GetFullPath(($exe -replace '/', '\')).ToLowerInvariant()
    } catch {
      $en = ($exe -replace '/', '\').ToLowerInvariant()
    }
    try {
      $dirFull = [System.IO.Path]::GetFullPath(($AppDirNormalized -replace '/', '\')).ToLowerInvariant().TrimEnd('\')
      $prefixFull = "$dirFull\"
      if ($en.StartsWith($prefixFull)) { return $true }
    } catch {
      # fall through to legacy prefix match
    }
    if ($en.StartsWith($prefix)) { return $true }
    if ($leafNeedle -and $en.Contains($leafNeedle)) { return $true }
  }
  return $false
}

function Get-MatchingPythonProcesses {
  param(
    [string]$FolderPath,
    [string]$ScriptName
  )
  if ([string]::IsNullOrWhiteSpace($FolderPath) -or -not (Test-Path -LiteralPath $FolderPath)) { return @() }
  $dirNorm = Normalize-AppDirectoryPath $FolderPath
  $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { Test-PythonProcessMatchesAppDir -Proc $_ -AppDirNormalized $dirNorm -ScriptName $ScriptName }
  return @($procs)
}

function Stop-ProcessList {
  param([array]$Processes)
  foreach ($p in $Processes) {
    try {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
    } catch {
      # Ignore races where process exits before stop.
    }
  }
}

function Test-PythonAppRunning {
  param(
    [string]$FolderPath,
    [string]$ScriptName = 'main.py'
  )
  if ([string]::IsNullOrWhiteSpace($FolderPath) -or -not (Test-Path -LiteralPath $FolderPath)) { return $false }
  $dirNorm = Normalize-AppDirectoryPath $FolderPath
  $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue
  foreach ($p in $procs) {
    if (Test-PythonProcessMatchesAppDir -Proc $p -AppDirNormalized $dirNorm -ScriptName $ScriptName) { return $true }
  }
  return $false
}

function Test-CleanerBeeRunning {
  $procs = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue
  $leaf = Split-Path -Path $CleanerScript -Leaf
  foreach ($p in $procs) {
    if ($p.CommandLine -like "*$leaf*") { return $true }
  }
  return $false
}

function Wait-Readiness {
  param(
    [string]$Label,
    [scriptblock]$Test,
    [int]$TimeoutSec,
    [int]$IntervalSec,
    [int]$StabilitySec = 0
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $lastProgressLog = [datetime]::MinValue
  while ((Get-Date) -lt $deadline) {
    try {
      if (& $Test) {
        if ($StabilitySec -gt 0) {
          Start-Sleep -Seconds $StabilitySec
          if (-not (& $Test)) {
            Write-LauncherLog "Readiness: $Label passed once then disappeared within ${StabilitySec}s (startup crash or fast exit — check app logs, e.g. scoreboard log under logs/)."
            continue
          }
        }
        Write-LauncherLog ('Readiness OK: {0} ({1:0.###}s)' -f $Label, $sw.Elapsed.TotalSeconds)
        return $true
      }
    } catch {
      Write-LauncherLog "Readiness check error ($Label): $($_.Exception.Message)"
    }
    $now = Get-Date
    if (($now - $lastProgressLog).TotalSeconds -ge 30) {
      Write-LauncherLog ("Readiness still waiting: {0} (elapsed {1:0.#}s / {2}s)..." -f $Label, $sw.Elapsed.TotalSeconds, $TimeoutSec)
      $lastProgressLog = $now
    }
    Start-Sleep -Seconds $IntervalSec
  }
  Write-LauncherLog "Readiness TIMEOUT: $Label (${TimeoutSec}s)"
  return $false
}

$script:LauncherWin32Loaded = $false
function Initialize-LauncherWin32 {
  if ($script:LauncherWin32Loaded) { return }
  Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace ReplayTroveLauncher {
public static class User32 {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetWindowTextLength(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

  public static string SafeGetWindowTitle(IntPtr hWnd) {
    if (hWnd == IntPtr.Zero) { return ""; }
    int n = GetWindowTextLength(hWnd);
    if (n <= 0) { return ""; }
    var sb = new StringBuilder(n + 1);
    GetWindowText(hWnd, sb, sb.Capacity);
    return sb.ToString();
  }
}
}
'@
  $script:LauncherWin32Loaded = $true
}

function Format-LauncherLogWindowTitle {
  param([string]$Title, [int]$MaxLen = 120)
  if ([string]::IsNullOrEmpty($Title)) { return '(empty)' }
  if ($Title.Length -le $MaxLen) { return $Title }
  return $Title.Substring(0, $MaxLen) + '…'
}

function Get-ForegroundWindowSnapshot {
  Initialize-LauncherWin32
  $hwnd = [ReplayTroveLauncher.User32]::GetForegroundWindow()
  $snap = @{
    Hwnd = $hwnd
    Title = ''
    Pid = $null
    ProcessName = ''
  }
  if ($hwnd -eq [IntPtr]::Zero) {
    return [pscustomobject]$snap
  }
  $snap.Title = [ReplayTroveLauncher.User32]::SafeGetWindowTitle($hwnd)
  $pidOut = [uint32]0
  [void][ReplayTroveLauncher.User32]::GetWindowThreadProcessId($hwnd, [ref]$pidOut)
  if ($pidOut -ne 0) {
    $snap.Pid = [int]$pidOut
    try {
      $snap.ProcessName = [string](Get-Process -Id $snap.Pid -ErrorAction Stop).ProcessName
    } catch {
      $snap.ProcessName = '(unknown)'
    }
  }
  return [pscustomobject]$snap
}

function Get-ScoreboardProcessSnapshot {
  param([string]$FolderPath)
  $leaf = Split-Path -Path $FolderPath -Leaf
  $cim = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue | Where-Object {
      $cmd = $_.CommandLine
      if (-not $cmd) { return $false }
      ($cmd -like "*\$leaf\*") -and ($cmd -like '*main.py*')
    })
  if ($cim.Count -eq 0) {
    return [pscustomobject]@{
      Alive       = $false
      Pids        = [int[]]@()
      MainPid     = $null
      MainWindowHwnd = [IntPtr]::Zero
      HasMainWindow = $false
      IsWindowVisible = $null
      IsMinimized = $null
    }
  }
  Initialize-LauncherWin32
  $pids = @($cim | ForEach-Object { [int]$_.ProcessId } | Sort-Object -Unique)
  $mainHwnd = [IntPtr]::Zero
  $mainPid = $pids[0]
  foreach ($procId in $pids) {
    try {
      $gp = Get-Process -Id $procId -ErrorAction Stop
      if ($gp.MainWindowHandle -ne [IntPtr]::Zero) {
        $mainHwnd = $gp.MainWindowHandle
        $mainPid = $procId
        break
      }
    } catch { }
  }
  $hasWin = ($mainHwnd -ne [IntPtr]::Zero)
  $vis = $null
  $iconic = $null
  if ($hasWin) {
    $vis = [ReplayTroveLauncher.User32]::IsWindowVisible($mainHwnd)
    $iconic = [ReplayTroveLauncher.User32]::IsIconic($mainHwnd)
  }
  return [pscustomobject]@{
    Alive            = $true
    Pids             = $pids
    MainPid          = $mainPid
    MainWindowHwnd   = $mainHwnd
    HasMainWindow    = $hasWin
    IsWindowVisible  = $vis
    IsMinimized      = $iconic
  }
}

function Read-ScoreboardStatusHeartbeat {
  param(
    [string]$Path,
    [int]$StaleSec
  )
  $r = [pscustomobject]@{
    Available   = $false
    UpdatedAt   = $null
    AgeSec      = $null
    IsStale     = $null
    RawError    = $null
  }
  if (-not (Test-Path -LiteralPath $Path)) {
    return $r
  }
  try {
    $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
    $j = $raw | ConvertFrom-Json
    $r.Available = $true
    if ($null -eq $j -or [string]::IsNullOrWhiteSpace([string]$j.updated_at)) {
      return $r
    }
    $dt = [DateTime]::MinValue
    if (-not [DateTime]::TryParse([string]$j.updated_at, [ref]$dt)) {
      $r.RawError = 'updated_at unparsable'
      return $r
    }
    $r.UpdatedAt = $dt.ToUniversalTime()
    $age = ([DateTime]::UtcNow - $r.UpdatedAt).TotalSeconds
    $r.AgeSec = [Math]::Round($age, 3)
    $r.IsStale = ($age -gt $StaleSec)
  } catch {
    $r.RawError = $_.Exception.Message
  }
  return $r
}

function Write-ScoreboardFocusDiagnostics {
  param(
    [string]$Reason,
    [int]$AttemptsUsed,
    [pscustomobject]$ScoreboardSnap,
    [pscustomobject]$Heartbeat,
    [pscustomobject]$ForegroundAfter,
    [IntPtr]$ScoreboardTitleHwnd,
    [int]$StaleThresholdSec
  )
  $hbLine = if (-not $Heartbeat.Available) {
    'heartbeat file missing or unreadable'
  } elseif ($Heartbeat.RawError) {
    "heartbeat error: $($Heartbeat.RawError)"
  } elseif ($null -eq $Heartbeat.UpdatedAt) {
    'heartbeat has no updated_at'
  } else {
    "heartbeat updated_at=$($Heartbeat.UpdatedAt.ToString('o')) age_sec=$($Heartbeat.AgeSec) stale_threshold_sec=$StaleThresholdSec stale=$($Heartbeat.IsStale)"
  }

  $winLine = if (-not $ScoreboardSnap.Alive) {
    'scoreboard window: n/a (process not running)'
  } elseif (-not $ScoreboardSnap.HasMainWindow) {
    "scoreboard window: no MainWindowHandle yet (pids=$($ScoreboardSnap.Pids -join ','))"
  } else {
    $vh = if ($null -eq $ScoreboardSnap.IsWindowVisible) { '?' } else { $ScoreboardSnap.IsWindowVisible }
    $ic = if ($null -eq $ScoreboardSnap.IsMinimized) { '?' } else { $ScoreboardSnap.IsMinimized }
    "scoreboard window: hwnd=$($ScoreboardSnap.MainWindowHwnd) visible=$vh minimized=$ic"
  }

  $fgPid = if ($null -eq $ForegroundAfter.Pid) { '?' } else { [string]$ForegroundAfter.Pid }
  $fgTitle = Format-LauncherLogWindowTitle -Title $ForegroundAfter.Title
  Write-LauncherLog "Scoreboard focus DIAG: reason=$Reason attempts=$AttemptsUsed scoreboard_pid=$($ScoreboardSnap.MainPid) scoreboard_pids=$($ScoreboardSnap.Pids -join ',') alive=$($ScoreboardSnap.Alive) $winLine title_hwnd_match=$($ScoreboardTitleHwnd -ne [IntPtr]::Zero) title_hwnd=$ScoreboardTitleHwnd $hbLine foreground_pid=$fgPid foreground_name=$($ForegroundAfter.ProcessName) foreground_title=$fgTitle"

  if (-not $ScoreboardSnap.Alive) {
    Write-LauncherLog 'Scoreboard focus DIAG classification: process not running — focus failure is expected; this is consistent with a dead scoreboard (confirm outside launcher). AppActivate failure does not by itself prove a prior crash.'
    return
  }

  if ($Heartbeat.Available -and ($Heartbeat.IsStale -eq $true)) {
    Write-LauncherLog 'Scoreboard focus DIAG classification: process alive but status heartbeat is STALE — likely UI stall, blocked event loop, or writer failure; unfocusable window alone does not explain a frozen updated_at.'
  }

  if ($ScoreboardSnap.HasMainWindow -and $ScoreboardSnap.IsWindowVisible -eq $false) {
    Write-LauncherLog 'Scoreboard focus DIAG classification: main window exists but IsWindowVisible=false — likely hidden or off-screen; AppActivate may fail without implying process death.'
  } elseif ($ScoreboardSnap.HasMainWindow -and $ScoreboardSnap.IsMinimized -eq $true) {
    Write-LauncherLog 'Scoreboard focus DIAG classification: main window minimized — focus/z-order issues common; process may still be healthy.'
  }

  if ($Heartbeat.Available -and ($Heartbeat.IsStale -eq $false)) {
    Write-LauncherLog 'Scoreboard focus DIAG classification: process alive and heartbeat fresh, but focus API failed — likely z-order, focus guards, or another app holding foreground; not treated as scoreboard crash.'
  } elseif (-not $Heartbeat.Available -or $null -eq $Heartbeat.UpdatedAt) {
    Write-LauncherLog 'Scoreboard focus DIAG classification: cannot assess heartbeat — focus failure still does not prove crash; check scoreboard_status.json path and updated_at field.'
  }
}

function Invoke-ScoreboardFocusRecovery {
  param(
    [string]$Title,
    [pscustomobject]$ScoreboardSnap
  )
  Initialize-LauncherWin32
  $ws = New-Object -ComObject WScript.Shell
  $SW_SHOW = 5
  $SW_RESTORE = 9
  if ($ScoreboardSnap.HasMainWindow -and $ScoreboardSnap.MainWindowHwnd -ne [IntPtr]::Zero) {
    $cmd = if ($ScoreboardSnap.IsMinimized -eq $true) { $SW_RESTORE } else { $SW_SHOW }
    $shown = [ReplayTroveLauncher.User32]::ShowWindowAsync($ScoreboardSnap.MainWindowHwnd, $cmd)
    Write-LauncherLog "Scoreboard focus RECOVERY: ShowWindowAsync hwnd=$($ScoreboardSnap.MainWindowHwnd) nCmd=$cmd result=$shown (one-shot, optional)"
    Start-Sleep -Milliseconds 300
  } else {
    Write-LauncherLog 'Scoreboard focus RECOVERY: no main window handle; skipping ShowWindowAsync (one-shot optional step)'
  }
  $ok = $false
  try { $ok = [bool]$ws.AppActivate($Title) } catch { $ok = $false }
  $fg = Get-ForegroundWindowSnapshot
  $fgTitle = Format-LauncherLogWindowTitle -Title $fg.Title
  Write-LauncherLog "Scoreboard focus RECOVERY: AppActivate('$Title') result=$ok foreground_after pid=$($fg.Pid) name=$($fg.ProcessName) title=$fgTitle"
  return $ok
}

function Invoke-ScoreboardFocus {
  param(
    [int]$MaxAttempts,
    [int]$RetryMs,
    [string]$Reason = 'unspecified',
    [string]$Title,
    [string]$ScoreboardFolderPath,
    [string]$StatusJsonPath,
    [int]$StaleSec,
    [bool]$AllowRecovery
  )
  Initialize-LauncherWin32
  $ws = New-Object -ComObject WScript.Shell
  for ($i = 1; $i -le $MaxAttempts; $i++) {
    $fgBefore = Get-ForegroundWindowSnapshot
    $fgBTitle = Format-LauncherLogWindowTitle -Title $fgBefore.Title
    Write-LauncherLog "Scoreboard focus attempt: reason=$Reason i=$i max=$MaxAttempts foreground_before pid=$($fgBefore.Pid) name=$($fgBefore.ProcessName) title=$fgBTitle"

    $ok = $false
    try { $ok = [bool]$ws.AppActivate($Title) } catch { $ok = $false }

    Start-Sleep -Milliseconds 80
    $fgAfter = Get-ForegroundWindowSnapshot
    $fgATitle = Format-LauncherLogWindowTitle -Title $fgAfter.Title
    $sbSnap = Get-ScoreboardProcessSnapshot -FolderPath $ScoreboardFolderPath
    $scoreboardIsForeground = $false
    if ($sbSnap.Alive -and $sbSnap.HasMainWindow -and $fgAfter.Hwnd -eq $sbSnap.MainWindowHwnd) {
      $scoreboardIsForeground = $true
    }
    if (-not $scoreboardIsForeground -and $sbSnap.Alive -and $null -ne $sbSnap.MainPid -and $fgAfter.Pid -eq $sbSnap.MainPid) {
      $scoreboardIsForeground = $true
    }

    Write-LauncherLog "Scoreboard focus attempt result: reason=$Reason i=$i AppActivate_returned=$ok scoreboard_foreground=$scoreboardIsForeground foreground_after pid=$($fgAfter.Pid) name=$($fgAfter.ProcessName) title=$fgATitle"

    if ($ok -and $scoreboardIsForeground) {
      Write-LauncherLog "Scoreboard focus OK: healthy — reason=$Reason attempt=$i AppActivate succeeded and scoreboard owns foreground (pid=$($sbSnap.MainPid) hwnd=$($sbSnap.MainWindowHwnd))."
      return $true
    }
    if ($ok -and -not $scoreboardIsForeground) {
      Write-LauncherLog "Scoreboard focus WARN: reason=$Reason attempt=$i AppActivate returned True but foreground is not scoreboard — another window may have taken focus (pid=$($fgAfter.Pid))."
      return $true
    }

    Start-Sleep -Milliseconds $RetryMs
  }

  $finalFg = Get-ForegroundWindowSnapshot
  $sbFinal = Get-ScoreboardProcessSnapshot -FolderPath $ScoreboardFolderPath
  $heartbeat = Read-ScoreboardStatusHeartbeat -Path $StatusJsonPath -StaleSec $StaleSec
  $sbTitleHwnd = [ReplayTroveLauncher.User32]::FindWindow($null, $Title)

  Write-ScoreboardFocusDiagnostics -Reason $Reason -AttemptsUsed $MaxAttempts -ScoreboardSnap $sbFinal -Heartbeat $heartbeat -ForegroundAfter $finalFg -ScoreboardTitleHwnd $sbTitleHwnd -StaleThresholdSec $StaleSec

  if ($AllowRecovery -and $sbFinal.Alive) {
    $recOk = Invoke-ScoreboardFocusRecovery -Title $Title -ScoreboardSnap $sbFinal
    if ($recOk) {
      Write-LauncherLog 'Scoreboard focus RECOVERY: succeeded after optional one-shot sequence.'
      return $true
    }
    Write-LauncherLog 'Scoreboard focus RECOVERY: optional one-shot sequence did not achieve focus; not retrying further.'
  }

  Write-LauncherLog "Scoreboard focus FAIL: reason=$Reason AppActivate did not yield scoreboard foreground after $MaxAttempts attempts (see DIAG lines above; failure is not assumed to mean crash)."
  return $false
}

function Test-ScoreboardStatusWatchDesired {
  if (-not ($EnableScoreboard -and $EnableEncoder -and $EnableObs)) { return $false }
  return [bool]$ScoreboardStatusWatch
}

function Read-ScoreboardScreensaverActive {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try {
    $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
    $j = $raw | ConvertFrom-Json
    if ($null -eq $j -or $null -eq $j.PSObject.Properties['screensaver_active']) { return $null }
    return [bool]$j.screensaver_active
  } catch {
    return $null
  }
}

function Read-ScoreboardStatusPayload {
  param([string]$Path)
  $r = [pscustomobject]@{
    Available = $false
    ParseError = $null
    RawObject = $null
    ScreensaverActive = $null
    ReplayObsRestartRequested = $false
    ReplayObsRestartReason = $null
    UpdatedAt = $null
  }
  if (-not (Test-Path -LiteralPath $Path)) { return $r }
  try {
    $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
    $j = $raw | ConvertFrom-Json
    $r.Available = $true
    $r.RawObject = $j
    if ($null -ne $j.PSObject.Properties['screensaver_active']) {
      $r.ScreensaverActive = [bool]$j.screensaver_active
    }
    if ($null -ne $j.PSObject.Properties['replay_obs_restart_requested']) {
      $r.ReplayObsRestartRequested = [bool]$j.replay_obs_restart_requested
    }
    if ($null -ne $j.PSObject.Properties['replay_obs_restart_reason']) {
      $r.ReplayObsRestartReason = [string]$j.replay_obs_restart_reason
    }
    if ($null -ne $j.PSObject.Properties['updated_at'] -and -not [string]::IsNullOrWhiteSpace([string]$j.updated_at)) {
      $dt = [DateTime]::MinValue
      if ([DateTime]::TryParse([string]$j.updated_at, [ref]$dt)) {
        $r.UpdatedAt = $dt.ToUniversalTime()
      }
    }
  } catch {
    $r.ParseError = $_.Exception.Message
  }
  return $r
}

function Acknowledge-ReplayObsRestartSignal {
  param(
    [string]$Path,
    [pscustomobject]$StatusPayload
  )
  if (-not $StatusPayload.Available -or $null -eq $StatusPayload.RawObject) { return }
  try {
    $obj = $StatusPayload.RawObject
    $obj | Add-Member -NotePropertyName 'replay_obs_restart_requested' -NotePropertyValue $false -Force
    $obj | Add-Member -NotePropertyName 'replay_obs_restart_acknowledged_at' -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
    if (-not [string]::IsNullOrWhiteSpace($StatusPayload.ReplayObsRestartReason)) {
      $obj | Add-Member -NotePropertyName 'replay_obs_restart_ack_reason' -NotePropertyValue $StatusPayload.ReplayObsRestartReason -Force
    }
    $json = $obj | ConvertTo-Json -Depth 20
    Set-Content -LiteralPath $Path -Encoding utf8 -Value $json
    Write-LauncherLog "Replay OBS restart signal acknowledged in status JSON (updated_at=$($StatusPayload.UpdatedAt), reason=$($StatusPayload.ReplayObsRestartReason))."
  } catch {
    Write-LauncherLog "WARN: failed to acknowledge replay OBS restart signal in status JSON: $($_.Exception.Message)"
  }
}

function Invoke-ManagedStartIfDesiredRunning {
  param(
    [string]$ComponentName,
    [string]$Source,
    [scriptblock]$StartAction
  )
  $desired = Get-DesiredState -DesiredStateMap $script:DesiredStateMap -ComponentName $ComponentName
  if ($desired -eq 'stopped') {
    Write-LauncherLog "SUPERVISION DESIRED_STATE: component=$ComponentName source=$Source desired_state=stopped decision=start_suppressed"
    return $false
  }
  Write-LauncherLog "SUPERVISION DESIRED_STATE: component=$ComponentName source=$Source desired_state=running decision=start_allowed"
  & $StartAction
  return $true
}

function Invoke-ObsRestartForReplaySignal {
  param([string]$Reason)
  $why = if ([string]::IsNullOrWhiteSpace($Reason)) { '(unspecified)' } else { $Reason }
  Write-LauncherLog "Replay OBS restart signal: executing OBS restart flow (reason=$why)."
  Stop-Obs64ForLauncher
  Start-Sleep -Milliseconds 500
  $started = Invoke-ManagedStartIfDesiredRunning -ComponentName 'obs' -Source 'replay_restart_signal' -StartAction { Start-ObsForLauncher }
  if ($started) {
    Write-LauncherLog "Replay OBS restart signal: OBS restart flow complete (reason=$why)."
  } else {
    Write-LauncherLog "Replay OBS restart signal: OBS start suppressed by desired state (reason=$why)."
  }
}

function Get-EncoderStatePathForLauncher {
  $raw = [Environment]::GetEnvironmentVariable('ENCODER_STATE_PATH')
  if (-not [string]::IsNullOrWhiteSpace($raw)) {
    $t = $raw.Trim()
    if ([System.IO.Path]::IsPathRooted($t)) {
      return [System.IO.Path]::GetFullPath($t)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $UnifiedRoot $t.TrimStart('\','/')))
  }
  $rel = Get-UnifiedNestedValue -Object $UnifiedData -Path 'scoreboard.encoderStatePath'
  if ($rel -is [string] -and -not [string]::IsNullOrWhiteSpace($rel)) {
    $t = $rel.Trim()
    if ([System.IO.Path]::IsPathRooted($t)) {
      return [System.IO.Path]::GetFullPath($t)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $ScoreboardDir $t))
  }
  return [System.IO.Path]::GetFullPath((Join-Path $ScoreboardDir 'encoder_state.json'))
}

function Test-EncoderLongRecordingActive {
  $path = Get-EncoderStatePathForLauncher
  if (-not (Test-Path -LiteralPath $path)) { return $false }
  try {
    $j = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
  } catch {
    return $false
  }
  if ($null -eq $j) { return $false }
  if ($j.long_recording_active -eq $true) { return $true }
  $st = [string]$j.state
  if (-not [string]::IsNullOrWhiteSpace($st) -and $st.Trim().ToLowerInvariant() -eq 'recording') {
    return $true
  }
  return $false
}

function Stop-EncoderStackForLauncher {
  if (Test-EncoderLongRecordingActive) {
    Write-LauncherLog 'Stop-EncoderStack skipped: encoder long recording active (policy: only operator stop or max duration ends a take).'
    return
  }
  $leaf = Split-Path -Path $EncoderDir -Leaf
  $names = @('encoder_watchdog.py', 'operator_long_only.py', 'operator_tk.py')
  $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue
  foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd -or $cmd -notlike "*\$leaf\*") { continue }
    foreach ($sn in $names) {
      if ($cmd -like "*$sn*") {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch { }
        break
      }
    }
  }
}

function Stop-Obs64ForLauncher {
  Get-Process -Name 'obs64' -ErrorAction SilentlyContinue | ForEach-Object {
    try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch { }
  }
}

function Start-EncoderWatchdogForLauncher {
  Start-Process -WorkingDirectory $EncoderDir -FilePath $pyEncoder -ArgumentList @('encoder_watchdog.py') -WindowStyle $pyHeadlessWindowStyle | Out-Null
}

function Start-ObsForLauncher {
  if (Test-Path -LiteralPath $ObsSentinel) {
    try {
      Remove-Item -LiteralPath $ObsSentinel -Recurse -Force -ErrorAction Stop
    } catch {
      Write-LauncherLog "WARN: could not remove OBS sentinel before restart: $($_.Exception.Message)"
    }
  }
  Start-Process -WorkingDirectory $ObsDir -FilePath $ObsExe -ArgumentList $obsArgs -WindowStyle $obsWindowStyle | Out-Null
}

function Initialize-ScoreboardStatusWatchState {
  $script:ScoreboardStatusLastScreensaver = $null
  $script:ScoreboardStatusLastReplayRequested = $false
  $script:ScoreboardStatusLastReplaySignalKey = $null
  $script:ScoreboardScreensaverActive = $false
}

function Invoke-ScoreboardStatusWatchTick {
  param([string]$StatusPath)
  $status = Read-ScoreboardStatusPayload -Path $StatusPath
  if ($status.ParseError) {
    Write-LauncherLog "Scoreboard status watch: parse error reading status JSON: $($status.ParseError)"
    return
  }
  if (-not $status.Available) { return }
  if ($null -eq $status.UpdatedAt) {
    Write-LauncherLog 'Scoreboard status watch: ignoring status JSON with missing/invalid updated_at (stale guard).'
    return
  }
  $ageSec = ([DateTime]::UtcNow - $status.UpdatedAt).TotalSeconds
  if ($ageSec -gt $ScoreboardStatusStaleSec) {
    Write-LauncherLog ("Scoreboard status watch: ignoring stale status JSON (age_sec={0:0.0} > stale_sec={1})." -f $ageSec, $ScoreboardStatusStaleSec)
    return
  }
  $current = $status.ScreensaverActive
  if ($null -eq $current) { return }
  $script:ScoreboardScreensaverActive = [bool]$current

  $replayRequested = ($status.ReplayObsRestartRequested -eq $true)
  if ($replayRequested) {
    $signalKey = if ($null -ne $status.UpdatedAt) { $status.UpdatedAt.ToString('o') } else { $null }
    $isEdgeTrigger = (-not $script:ScoreboardStatusLastReplayRequested)
    $isNewSignalKey = (-not [string]::IsNullOrWhiteSpace($signalKey) -and $signalKey -ne $script:ScoreboardStatusLastReplaySignalKey)
    if ($isEdgeTrigger -or $isNewSignalKey) {
      $reason = if ([string]::IsNullOrWhiteSpace($status.ReplayObsRestartReason)) { '(unspecified)' } else { $status.ReplayObsRestartReason }
      Write-LauncherLog "Scoreboard status watch: replay OBS restart requested=true (reason=$reason, updated_at=$signalKey, edge=$isEdgeTrigger, new_key=$isNewSignalKey)."
      if ($EnableObs) {
        Invoke-ObsRestartForReplaySignal -Reason $status.ReplayObsRestartReason
      } else {
        Write-LauncherLog "Replay OBS restart signal ignored because OBS is disabled (reason=$reason)."
      }
      Acknowledge-ReplayObsRestartSignal -Path $StatusPath -StatusPayload $status
      if (-not [string]::IsNullOrWhiteSpace($signalKey)) {
        $script:ScoreboardStatusLastReplaySignalKey = $signalKey
      }
    }
  }
  $script:ScoreboardStatusLastReplayRequested = $replayRequested

  if ($null -eq $script:ScoreboardStatusLastScreensaver) {
    if ($current) {
      Write-LauncherLog 'Initial scoreboard status: screensaver active; stopping Encoder and OBS.'
      Stop-EncoderStackForLauncher
      Stop-Obs64ForLauncher
    }
    $script:ScoreboardStatusLastScreensaver = $current
    return
  }
  if ($current -eq $script:ScoreboardStatusLastScreensaver) { return }
  $script:ScoreboardStatusLastScreensaver = $current
  if ($current) {
    Write-LauncherLog 'Scoreboard entered screensaver; stopping Encoder and OBS.'
    Stop-EncoderStackForLauncher
    Stop-Obs64ForLauncher
  } else {
    Write-LauncherLog 'Scoreboard left screensaver; restarting Encoder and OBS.'
    [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'encoder_watchdog' -Source 'scoreboard_screensaver_exit' -StartAction { Start-EncoderWatchdogForLauncher })
    Start-Sleep -Milliseconds 400
    [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'obs' -Source 'scoreboard_screensaver_exit' -StartAction { Start-ObsForLauncher })
  }
}

function Start-ControlAppForLauncher {
  param(
    [string]$ExePath,
    [string]$ArgumentsRaw
  )
  if ([string]::IsNullOrWhiteSpace($ArgumentsRaw)) {
    Start-Process -FilePath $ExePath -WindowStyle Minimized | Out-Null
  } else {
    $argList = $ArgumentsRaw.Trim() -split '\s+', [System.StringSplitOptions]::RemoveEmptyEntries
    Start-Process -FilePath $ExePath -ArgumentList $argList -WindowStyle Minimized | Out-Null
  }
}

function Invoke-ControlAppMinimizeIfNeeded {
  param(
    [string]$ProcessName,
    [int]$MaxAttempts,
    [int]$RetryMs
  )
  if ($ProcessName -cne 'StreamDeck') { return $false }
  Add-Type -Namespace Win32 -Name Show -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
'@ | Out-Null
  $SW_MINIMIZE = 6
  for ($i = 1; $i -le $MaxAttempts; $i++) {
    $sd = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero }
    if ($sd) {
      $hwnd = $sd[0].MainWindowHandle
      $called = [Win32.Show]::ShowWindowAsync($hwnd, $SW_MINIMIZE)
      Write-LauncherLog "Control app minimize (Stream Deck): ShowWindowAsync attempt $i, hwnd=$hwnd, result=$called"
      if ($called) { return $true }
    } else {
      Write-LauncherLog "Control app minimize (Stream Deck): no main window yet (attempt $i/$MaxAttempts)"
    }
    Start-Sleep -Milliseconds $RetryMs
  }
  Write-LauncherLog 'Control app minimize (Stream Deck): failed after all attempts'
  return $false
}

function Start-WorkerForLauncher {
  Start-Process -WorkingDirectory $WorkerDir -FilePath $pyWorker -ArgumentList @('main.py') -WindowStyle $pyHeadlessWindowStyle | Out-Null
}

function Stop-WorkerForLauncher {
  $procs = Get-MatchingPythonProcesses -FolderPath $WorkerDir -ScriptName 'main.py'
  Stop-ProcessList -Processes $procs
}

function Start-ScoreboardForLauncher {
  if ($EnableObs -and -not (Get-Process -Name 'obs64' -ErrorAction SilentlyContinue)) {
    Write-LauncherLog 'SUPERVISION: OBS is down while restarting scoreboard; attempting OBS start first.'
    [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'obs' -Source 'scoreboard_prestart_obs' -StartAction { Start-ObsForLauncher })
    [void](Wait-Readiness -Label 'OBS (obs64) pre-scoreboard-restart' -TimeoutSec $ReadinessObsSec -IntervalSec $ReadinessIntervalSec -Test {
      $null -ne (Get-Process -Name 'obs64' -ErrorAction SilentlyContinue)
    })
  }
  Start-Process -WorkingDirectory $ScoreboardDir -FilePath $pyScore -ArgumentList @('main.py') -WindowStyle $pyGuiWindowStyle | Out-Null
}

function Stop-ScoreboardForLauncher {
  $procs = Get-MatchingPythonProcesses -FolderPath $ScoreboardDir -ScriptName 'main.py'
  Stop-ProcessList -Processes $procs
}

function Ensure-LauncherIntentDirectories {
  foreach ($dir in @($LauncherIntentsRoot, $LauncherIntentsPendingDir, $LauncherIntentsProcessedDir, $LauncherIntentsFailedDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }
}

function Test-LauncherManagedTargetRunning {
  param([string]$Target)
  switch ($Target) {
    'worker' { return (Test-PythonAppRunning -FolderPath $WorkerDir -ScriptName 'main.py') }
    'scoreboard' { return (Test-PythonAppRunning -FolderPath $ScoreboardDir -ScriptName 'main.py') }
    'obs' { return ($null -ne (Get-Process -Name 'obs64' -ErrorAction SilentlyContinue)) }
    'encoder_watchdog' { return (Test-PythonAppRunning -FolderPath $EncoderDir -ScriptName 'encoder_watchdog.py') }
    default { return $false }
  }
}

function Invoke-LauncherManagedTargetAction {
  param(
    [string]$Action,
    [string]$Target,
    [hashtable]$DesiredStateMap = $null
  )
  $actionNorm = $Action.Trim().ToLowerInvariant()
  if ($actionNorm -notin @('start', 'stop', 'restart')) {
    return [pscustomobject]@{ Ok = $false; Message = "unsupported action: $Action" }
  }

  $enabledCheck = switch ($Target) {
    'worker' { $EnableWorker; break }
    'scoreboard' { $EnableScoreboard; break }
    'obs' { $EnableObs; break }
    'encoder_watchdog' { $EnableEncoder; break }
    default { $null }
  }
  if ($null -eq $enabledCheck) {
    return [pscustomobject]@{ Ok = $false; Message = "unsupported target: $Target" }
  }
  if (-not $enabledCheck) {
    return [pscustomobject]@{ Ok = $false; Message = "$Target disabled by configuration" }
  }

  $isRunning = Test-LauncherManagedTargetRunning -Target $Target
  if ($actionNorm -eq 'start' -and $isRunning) {
    Set-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $Target -DesiredState 'running' -Source "intent_$actionNorm"
    return [pscustomobject]@{ Ok = $true; Message = "$Target already running (no-op)" }
  }
  if ($actionNorm -eq 'stop' -and -not $isRunning) {
    Set-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $Target -DesiredState 'stopped' -Source "intent_$actionNorm"
    return [pscustomobject]@{ Ok = $true; Message = "$Target already stopped (no-op)" }
  }

  if ($actionNorm -eq 'start') {
    Set-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $Target -DesiredState 'running' -Source "intent_$actionNorm"
  } elseif ($actionNorm -eq 'stop') {
    Set-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $Target -DesiredState 'stopped' -Source "intent_$actionNorm"
  } elseif ($actionNorm -eq 'restart') {
    Set-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $Target -DesiredState 'running' -Source "intent_$actionNorm"
  }

  switch ($Target) {
    'worker' {
      if ($actionNorm -in @('stop', 'restart')) { Stop-WorkerForLauncher }
      if ($actionNorm -eq 'restart') { Start-Sleep -Milliseconds 200 }
      if ($actionNorm -in @('start', 'restart')) { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'worker' -Source ("intent_{0}" -f $actionNorm) -StartAction { Start-WorkerForLauncher }) }
      return [pscustomobject]@{ Ok = $true; Message = "worker $actionNorm requested" }
    }
    'scoreboard' {
      if ($actionNorm -in @('stop', 'restart')) { Stop-ScoreboardForLauncher }
      if ($actionNorm -eq 'restart') { Start-Sleep -Milliseconds 250 }
      if ($actionNorm -in @('start', 'restart')) { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'scoreboard' -Source ("intent_{0}" -f $actionNorm) -StartAction { Start-ScoreboardForLauncher }) }
      return [pscustomobject]@{ Ok = $true; Message = "scoreboard $actionNorm requested" }
    }
    'obs' {
      if ($actionNorm -in @('stop', 'restart')) { Stop-Obs64ForLauncher }
      if ($actionNorm -eq 'restart') { Start-Sleep -Milliseconds 400 }
      if ($actionNorm -in @('start', 'restart')) { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'obs' -Source ("intent_{0}" -f $actionNorm) -StartAction { Start-ObsForLauncher }) }
      return [pscustomobject]@{ Ok = $true; Message = "obs $actionNorm requested" }
    }
    'encoder_watchdog' {
      if ($actionNorm -in @('stop', 'restart')) { Stop-EncoderStackForLauncher }
      if ($actionNorm -eq 'restart') { Start-Sleep -Milliseconds 250 }
      if ($actionNorm -in @('start', 'restart')) { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'encoder_watchdog' -Source ("intent_{0}" -f $actionNorm) -StartAction { Start-EncoderWatchdogForLauncher }) }
      return [pscustomobject]@{ Ok = $true; Message = "encoder_watchdog $actionNorm requested" }
    }
  }
}

function Move-IntentFile {
  param(
    [string]$SourcePath,
    [string]$DestinationDir
  )
  $name = [System.IO.Path]::GetFileName($SourcePath)
  $stamp = (Get-Date).ToString('yyyyMMddHHmmssfff')
  $dest = Join-Path $DestinationDir ("{0}_{1}" -f $stamp, $name)
  Move-Item -LiteralPath $SourcePath -Destination $dest -Force
  return $dest
}

function Process-LauncherIntentFile {
  param(
    [string]$IntentPath,
    [hashtable]$DesiredStateMap = $null
  )
  $name = [System.IO.Path]::GetFileName($IntentPath)
  try {
    $raw = Get-Content -LiteralPath $IntentPath -Raw -ErrorAction Stop
    $payload = $raw | ConvertFrom-Json -ErrorAction Stop
  } catch {
    $msg = "intent parse failed file=$name error=$($_.Exception.Message)"
    Write-LauncherLog "INTENT failed: $msg"
    [void](Move-IntentFile -SourcePath $IntentPath -DestinationDir $LauncherIntentsFailedDir)
    return
  }

  $action = [string]($payload.action)
  $target = [string]($payload.target)
  $source = [string]($payload.source)
  $intentId = [string]($payload.id)
  if ([string]::IsNullOrWhiteSpace($intentId)) { $intentId = $name }

  Write-LauncherLog "INTENT received: id=$intentId action=$action target=$target source=$source file=$name"
  if ($action -notin @('start', 'stop', 'restart')) {
    Write-LauncherLog "INTENT failed: id=$intentId unsupported action=$action"
    [void](Move-IntentFile -SourcePath $IntentPath -DestinationDir $LauncherIntentsFailedDir)
    return
  }

  $result = Invoke-LauncherManagedTargetAction -Action $action -Target $target -DesiredStateMap $DesiredStateMap
  if ($result.Ok) {
    Write-LauncherLog "INTENT applied: id=$intentId action=$action target=$target result=$($result.Message)"
    [void](Move-IntentFile -SourcePath $IntentPath -DestinationDir $LauncherIntentsProcessedDir)
    return
  }

  Write-LauncherLog "INTENT failed: id=$intentId action=$action target=$target reason=$($result.Message)"
  [void](Move-IntentFile -SourcePath $IntentPath -DestinationDir $LauncherIntentsFailedDir)
}

function Process-LauncherIntentQueue {
  param([hashtable]$DesiredStateMap = $null)
  Ensure-LauncherIntentDirectories
  $files = @(Get-ChildItem -LiteralPath $LauncherIntentsPendingDir -File -Filter '*.json' -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc, Name)
  foreach ($f in $files) {
    Process-LauncherIntentFile -IntentPath $f.FullName -DesiredStateMap $DesiredStateMap
  }
}

function New-HealthResult {
  param(
    [string]$Classification,
    [string]$Reason
  )
  return [pscustomobject]@{
    Classification = $Classification
    Reason = $Reason
  }
}

function Test-TcpEndpoint {
  param(
    [string]$Host,
    [int]$Port,
    [int]$TimeoutMs = 1500
  )
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
      $iar = $client.BeginConnect($Host, $Port, $null, $null)
      if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
        return $false
      }
      $client.EndConnect($iar) | Out-Null
      return $true
    } finally {
      $client.Close()
    }
  } catch {
    return $false
  }
}

function Invoke-HttpHealthCheck {
  param(
    [string]$Host,
    [int]$Port
  )
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri ("http://{0}:{1}/health" -f $Host, $Port) -TimeoutSec 2 -Method GET
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
  } catch {
    return $false
  }
}

function Read-JsonFileSafe {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return [pscustomobject]@{ Exists = $false; Parsed = $null; LastWriteUtc = $null; Error = $null }
  }
  try {
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
    $obj = $raw | ConvertFrom-Json
    return [pscustomobject]@{
      Exists = $true
      Parsed = $obj
      LastWriteUtc = $item.LastWriteTimeUtc
      Error = $null
    }
  } catch {
    return [pscustomobject]@{
      Exists = $true
      Parsed = $null
      LastWriteUtc = $null
      Error = $_.Exception.Message
    }
  }
}

function Try-ParseUtcDate {
  param([object]$Value)
  if ($null -eq $Value) { return $null }
  $txt = [string]$Value
  if ([string]::IsNullOrWhiteSpace($txt)) { return $null }
  $dt = [DateTime]::MinValue
  if (-not [DateTime]::TryParse($txt, [ref]$dt)) {
    return $null
  }
  return $dt.ToUniversalTime()
}

function Get-WorkerHealth {
  if (-not (Test-PythonAppRunning -FolderPath $WorkerDir -ScriptName 'main.py')) {
    return New-HealthResult -Classification 'not_running' -Reason 'worker_process_missing'
  }
  $status = Read-JsonFileSafe -Path $WorkerStatusJsonPath
  if (-not $status.Exists) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'worker_status_json_missing'
  }
  if ($status.Error -or $null -eq $status.Parsed) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'worker_status_json_unreadable'
  }
  if ($null -eq $status.LastWriteUtc) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'worker_status_json_mtime_unknown'
  }
  $ageSec = ([DateTime]::UtcNow - $status.LastWriteUtc).TotalSeconds
  if ($ageSec -gt $WorkerStatusStaleSec) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason ("worker_status_json_stale age_sec={0:0.0}" -f $ageSec)
  }
  if ($status.Parsed.PSObject.Properties.Name -contains 'worker_running') {
    if (-not [bool]$status.Parsed.worker_running) {
      return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'worker_status_reports_not_running'
    }
  }
  if ($WorkerReplayTriggerEnabled) {
    if (-not (Invoke-HttpHealthCheck -Host $WorkerReplayHost -Port $WorkerReplayPort)) {
      return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason ("worker_http_health_unreachable host={0} port={1}" -f $WorkerReplayHost, $WorkerReplayPort)
    }
  }
  return New-HealthResult -Classification 'running_and_healthy' -Reason 'worker_status_and_http_health_ok'
}

function Get-ScoreboardHealth {
  if (-not (Test-PythonAppRunning -FolderPath $ScoreboardDir -ScriptName 'main.py')) {
    return New-HealthResult -Classification 'not_running' -Reason 'scoreboard_process_missing'
  }
  $status = Read-JsonFileSafe -Path $ScoreboardStatusJson
  if (-not $status.Exists) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'scoreboard_status_json_missing'
  }
  if ($status.Error -or $null -eq $status.Parsed) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'scoreboard_status_json_unreadable'
  }
  if ($null -eq $status.Parsed.PSObject.Properties['scoreboard_running'] -or -not [bool]$status.Parsed.scoreboard_running) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'scoreboard_status_reports_not_running'
  }
  $updatedAtUtc = Try-ParseUtcDate -Value $status.Parsed.updated_at
  if ($null -eq $updatedAtUtc) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'scoreboard_status_updated_at_missing_or_invalid'
  }
  $ageSec = ([DateTime]::UtcNow - $updatedAtUtc).TotalSeconds
  if ($ageSec -gt $ScoreboardStatusStaleSec) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason ("scoreboard_status_stale age_sec={0:0.0}" -f $ageSec)
  }
  return New-HealthResult -Classification 'running_and_healthy' -Reason 'scoreboard_status_json_fresh'
}

function Get-ObsHealth {
  if ($null -eq (Get-Process -Name 'obs64' -ErrorAction SilentlyContinue)) {
    return New-HealthResult -Classification 'not_running' -Reason 'obs_process_missing'
  }
  if (-not (Test-TcpEndpoint -Host $ObsWebsocketHost -Port $ObsWebsocketPort -TimeoutMs 1200)) {
    return New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason ("obs_websocket_unreachable host={0} port={1}" -f $ObsWebsocketHost, $ObsWebsocketPort)
  }
  return New-HealthResult -Classification 'running_and_healthy' -Reason 'obs_websocket_reachable'
}

function Get-SupervisionComponents {
  $items = @()
  if ($EnableWorker) {
    $items += [pscustomobject]@{
      Name = 'worker'
      Probe = { Get-WorkerHealth }
      Start = { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'worker' -Source 'supervision_health_restart' -StartAction { Start-WorkerForLauncher }) }
      AllowRestart = { return $true }
    }
  }
  if ($EnableEncoder) {
    $items += [pscustomobject]@{
      Name = 'encoder_watchdog'
      Probe = {
        if (Test-PythonAppRunning -FolderPath $EncoderDir -ScriptName 'encoder_watchdog.py') {
          New-HealthResult -Classification 'running_and_healthy' -Reason 'watchdog_process_present'
        } else {
          New-HealthResult -Classification 'not_running' -Reason 'watchdog_process_missing'
        }
      }
      Start = { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'encoder_watchdog' -Source 'supervision_health_restart' -StartAction { Start-EncoderWatchdogForLauncher }) }
      AllowRestart = { return -not $script:ScoreboardScreensaverActive }
    }
  }
  if ($EnableObs) {
    $items += [pscustomobject]@{
      Name = 'obs'
      Probe = { Get-ObsHealth }
      Start = { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'obs' -Source 'supervision_health_restart' -StartAction { Start-ObsForLauncher }) }
      AllowRestart = { return -not $script:ScoreboardScreensaverActive }
    }
  }
  if ($EnableScoreboard) {
    $items += [pscustomobject]@{
      Name = 'scoreboard'
      Probe = { Get-ScoreboardHealth }
      Start = { [void](Invoke-ManagedStartIfDesiredRunning -ComponentName 'scoreboard' -Source 'supervision_health_restart' -StartAction { Start-ScoreboardForLauncher }) }
      AllowRestart = { return $true }
    }
  }
  return $items
}

function Get-ManagedDesiredStateComponentNames {
  return @('worker', 'scoreboard', 'obs', 'encoder_watchdog')
}

function New-DesiredStateMap {
  param([array]$Components)
  $map = @{}
  foreach ($name in Get-ManagedDesiredStateComponentNames) {
    $map[$name] = 'running'
  }
  return $map
}

function Get-DesiredState {
  param(
    [hashtable]$DesiredStateMap,
    [string]$ComponentName
  )
  if ($null -eq $DesiredStateMap) { return 'running' }
  if (-not $DesiredStateMap.ContainsKey($ComponentName)) { return 'running' }
  $state = [string]$DesiredStateMap[$ComponentName]
  if ($state -notin @('running', 'stopped')) { return 'running' }
  return $state
}

function Set-DesiredState {
  param(
    [hashtable]$DesiredStateMap,
    [string]$ComponentName,
    [string]$DesiredState,
    [string]$Source
  )
  if ($null -eq $DesiredStateMap) { return }
  if ($DesiredState -notin @('running', 'stopped')) { return }
  $old = Get-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $ComponentName
  $DesiredStateMap[$ComponentName] = $DesiredState
  if ($old -ne $DesiredState) {
    Write-LauncherLog "SUPERVISION DESIRED_STATE: component=$ComponentName old=$old new=$DesiredState source=$Source"
    if ($null -ne $script:DesiredStateMap -and [object]::ReferenceEquals($DesiredStateMap, $script:DesiredStateMap)) {
      Write-SupervisionDesiredStateSnapshot -Reason $Source
    }
  }
}

function Write-SupervisionDesiredStateSnapshot {
  param([string]$Reason = 'update')
  if ($null -eq $script:DesiredStateMap) { return }
  $comps = [ordered]@{}
  foreach ($name in Get-ManagedDesiredStateComponentNames) {
    $comps[$name] = Get-DesiredState -DesiredStateMap $script:DesiredStateMap -ComponentName $name
  }
  $payload = [ordered]@{
    schema_version = 1
    updated_at = [DateTime]::UtcNow.ToString('o')
    update_reason = $Reason
    components = $comps
  }
  try {
    $parent = Split-Path -Path $SupervisionDesiredStatePath -Parent
    if (-not [string]::IsNullOrWhiteSpace($parent) -and -not (Test-Path -LiteralPath $parent)) {
      New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $tmpPath = "$SupervisionDesiredStatePath.tmp"
    $json = $payload | ConvertTo-Json -Depth 6
    Set-Content -LiteralPath $tmpPath -Encoding UTF8 -Value $json
    Move-Item -LiteralPath $tmpPath -Destination $SupervisionDesiredStatePath -Force
    Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT: wrote path=$SupervisionDesiredStatePath reason=$Reason"
  } catch {
    Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT WARN: write failed path=$SupervisionDesiredStatePath error=$($_.Exception.Message)"
  }
}

function Merge-SupervisionDesiredStateFromSnapshot {
  param([hashtable]$DesiredStateMap)
  if ($null -eq $DesiredStateMap) { return }
  if (-not (Test-Path -LiteralPath $SupervisionDesiredStatePath)) {
    Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT: no file at $SupervisionDesiredStatePath; using defaults (all running)."
    return
  }
  try {
    $raw = Get-Content -LiteralPath $SupervisionDesiredStatePath -Raw -ErrorAction Stop
    $j = $raw | ConvertFrom-Json -ErrorAction Stop
  } catch {
    Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT WARN: corrupt or unreadable; ignoring. path=$SupervisionDesiredStatePath error=$($_.Exception.Message)"
    return
  }
  $blob = $null
  if ($null -ne $j.PSObject.Properties['components']) {
    $blob = $j.components
  } else {
    $blob = $j
  }
  if ($null -eq $blob) {
    Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT WARN: empty payload; using defaults."
    return
  }
  $propNames = @($blob.PSObject.Properties | ForEach-Object { $_.Name })
  $applied = 0
  foreach ($name in Get-ManagedDesiredStateComponentNames) {
    if ($propNames -notcontains $name) { continue }
    try {
      $v = [string]$blob.$name
    } catch {
      continue
    }
    if ($v -notin @('running', 'stopped')) {
      Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT WARN: invalid value for component=$name value=$v; skipping."
      continue
    }
    $DesiredStateMap[$name] = $v
    $applied++
  }
  Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT: loaded path=$SupervisionDesiredStatePath applied_entries=$applied"
}

function New-SupervisionStateMap {
  param([array]$Components)
  $map = @{}
  foreach ($comp in $Components) {
    $map[$comp.Name] = [pscustomobject]@{
      RestartTimes = New-Object System.Collections.Generic.List[datetime]
      LastAttemptAt = [DateTime]::MinValue
      LastObservedAt = [DateTime]::MinValue
      LastClassification = $null
      LastReason = $null
      LastRestartAt = [DateTime]::MinValue
      LastRestartReason = $null
      LastLoggedClassification = $null
      LastLoggedReason = $null
      ConsecutiveUnhealthy = 0
    }
  }
  return $map
}

function Write-SupervisionStatusSnapshot {
  param(
    [hashtable]$StateMap,
    [hashtable]$DesiredStateMap = $null
  )
  $payload = [ordered]@{
    timestamp = [DateTime]::UtcNow.ToString('o')
    components = @{}
  }
  foreach ($name in $StateMap.Keys) {
    $s = $StateMap[$name]
    $payload.components[$name] = [ordered]@{
      desired_state = Get-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $name
      last_observed_at = if ($s.LastObservedAt -eq [DateTime]::MinValue) { $null } else { $s.LastObservedAt.ToUniversalTime().ToString('o') }
      last_classification = $s.LastClassification
      last_reason = $s.LastReason
      last_restart_at = if ($s.LastRestartAt -eq [DateTime]::MinValue) { $null } else { $s.LastRestartAt.ToUniversalTime().ToString('o') }
      last_restart_reason = $s.LastRestartReason
      consecutive_unhealthy = $s.ConsecutiveUnhealthy
    }
  }
  try {
    $tmpPath = "$SupervisionStatusPath.tmp"
    $json = $payload | ConvertTo-Json -Depth 8
    Set-Content -LiteralPath $tmpPath -Encoding UTF8 -Value $json
    Move-Item -LiteralPath $tmpPath -Destination $SupervisionStatusPath -Force
  } catch {
    Write-LauncherLog "SUPERVISION WARN: failed writing supervision status snapshot: $($_.Exception.Message)"
  }
}

function Invoke-SupervisionTick {
  param(
    [array]$Components,
    [hashtable]$StateMap,
    [hashtable]$DesiredStateMap = $null
  )
  $now = Get-Date
  foreach ($comp in $Components) {
    $name = [string]$comp.Name
    $state = $StateMap[$name]
    $health = $null
    try {
      $health = & $comp.Probe
    } catch {
      Write-LauncherLog "SUPERVISION WARN: health probe failed for ${name}: $($_.Exception.Message)"
      $health = New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason ("health_probe_error {0}" -f $_.Exception.Message)
    }
    if ($null -eq $health -or [string]::IsNullOrWhiteSpace([string]$health.Classification)) {
      $health = New-HealthResult -Classification 'running_but_unhealthy_or_stale' -Reason 'health_probe_returned_no_classification'
    }
    $classification = [string]$health.Classification
    $reason = [string]$health.Reason
    $desiredState = Get-DesiredState -DesiredStateMap $DesiredStateMap -ComponentName $name
    $state.LastObservedAt = $now
    $state.LastClassification = $classification
    $state.LastReason = $reason
    if ($classification -eq 'running_and_healthy') {
      $state.ConsecutiveUnhealthy = 0
      if ($state.LastLoggedClassification -ne $classification -or $state.LastLoggedReason -ne $reason) {
        Write-LauncherLog "SUPERVISION HEALTH: component=$name classification=$classification reason=$reason decision=none"
        $state.LastLoggedClassification = $classification
        $state.LastLoggedReason = $reason
      }
      continue
    }

    if ($classification -eq 'running_but_unhealthy_or_stale') {
      $state.ConsecutiveUnhealthy += 1
    } else {
      $state.ConsecutiveUnhealthy = 0
    }

    if ($desiredState -eq 'stopped') {
      Write-LauncherLog "SUPERVISION HEALTH: component=$name desired_state=stopped classification=$classification reason=$reason decision=restart_suppressed"
      $state.LastLoggedClassification = $classification
      $state.LastLoggedReason = $reason
      continue
    }

    $allowed = $false
    try {
      $allowed = [bool](& $comp.AllowRestart)
    } catch {
      $allowed = $true
    }
    if (-not $allowed) {
      Write-LauncherLog "SUPERVISION HEALTH: component=$name classification=$classification reason=$reason decision=restart_suppressed"
      $state.LastLoggedClassification = $classification
      $state.LastLoggedReason = $reason
      continue
    }

    if ($classification -eq 'running_but_unhealthy_or_stale' -and $state.ConsecutiveUnhealthy -lt 2) {
      Write-LauncherLog "SUPERVISION HEALTH: component=$name classification=$classification reason=$reason decision=observe_wait unhealthy_strikes=$($state.ConsecutiveUnhealthy)"
      $state.LastLoggedClassification = $classification
      $state.LastLoggedReason = $reason
      continue
    }

    $windowStart = $now.AddSeconds(-1 * $SupervisionWindowSec)
    $filtered = New-Object System.Collections.Generic.List[datetime]
    foreach ($t in $state.RestartTimes) {
      if ($t -gt $windowStart) {
        [void]$filtered.Add($t)
      }
    }
    $state.RestartTimes = $filtered
    $attemptCount = $state.RestartTimes.Count
    if ($attemptCount -ge $SupervisionMaxRestartsPerWindow) {
      Write-LauncherLog "SUPERVISION HEALTH: component=$name classification=$classification reason=$reason decision=budget_exhausted attempts=$attemptCount window_sec=$SupervisionWindowSec"
      $state.LastLoggedClassification = $classification
      $state.LastLoggedReason = $reason
      continue
    }

    $backoffSec = [Math]::Min(60, $SupervisionBaseBackoffSec * [Math]::Pow(2, $attemptCount))
    $sinceLastAttempt = ($now - $state.LastAttemptAt).TotalSeconds
    if ($state.LastAttemptAt -ne [DateTime]::MinValue -and $sinceLastAttempt -lt $backoffSec) {
      continue
    }

    Write-LauncherLog "SUPERVISION HEALTH: component=$name classification=$classification reason=$reason decision=restart attempt=$($attemptCount + 1) window_sec=$SupervisionWindowSec backoff_sec=$backoffSec"
    try {
      & $comp.Start
      $state.LastAttemptAt = Get-Date
      $state.LastRestartAt = $state.LastAttemptAt
      $state.LastRestartReason = "$classification;$reason"
      [void]$state.RestartTimes.Add($state.LastAttemptAt)
      $state.ConsecutiveUnhealthy = 0
      $state.LastLoggedClassification = $classification
      $state.LastLoggedReason = $reason
    } catch {
      $state.LastAttemptAt = Get-Date
      $state.LastRestartAt = $state.LastAttemptAt
      $state.LastRestartReason = "restart_failed;$classification;$reason"
      [void]$state.RestartTimes.Add($state.LastAttemptAt)
      Write-LauncherLog "SUPERVISION ERROR: restart failed for ${name}: $($_.Exception.Message)"
      $state.LastLoggedClassification = $classification
      $state.LastLoggedReason = $reason
    }
  }
  Write-SupervisionStatusSnapshot -StateMap $StateMap -DesiredStateMap $DesiredStateMap
}

# --- Preflight ---
Write-LauncherLog "ReplayTrove launcher starting (supervisor). Central JSONL layout: $CentralLogsRoot\$(Get-Date -Format 'yyyy-MM-dd')\launcher.jsonl (+ timeline.jsonl, index.json)"
Write-LauncherLog "Mode: $(if ($DebugMode) { 'DEBUG (python.exe)' } else { 'PRODUCTION (pythonw.exe)' })"

$pyWorker = Get-PythonInterpreter $WorkerDir
$pyScore  = Get-PythonInterpreter $ScoreboardDir
$pyEncoder = Get-PythonInterpreter $EncoderDir

$preflight = @()
if ($EnableWorker) {
  $preflight += @{ Path = (Join-Path $WorkerDir 'main.py'); Label = 'Worker main.py' }
  $preflight += @{ Path = $pyWorker; Label = 'Worker venv Python' }
}
if ($EnableScoreboard) {
  $preflight += @{ Path = (Join-Path $ScoreboardDir 'main.py'); Label = 'Scoreboard main.py' }
  $preflight += @{ Path = $pyScore; Label = 'Scoreboard venv Python' }
}
if ($EnableEncoder) {
  $preflight += @{ Path = (Join-Path $EncoderDir 'encoder_watchdog.py'); Label = 'Encoder encoder_watchdog.py' }
  $preflight += @{ Path = $pyEncoder; Label = 'Encoder venv Python' }
}
if ($EnableCleaner -and $CleanerOwnerMode -eq 'launcher') {
  $preflight += @{ Path = $CleanerScript; Label = 'Cleaner Bee script' }
}
if ($EnableObs) {
  $preflight += @{ Path = $ObsExe; Label = 'OBS executable' }
}
if ($EnableControlApp) {
  $preflight += @{ Path = $ControlAppExe; Label = 'Control app executable' }
}
if ($EnableLauncherUi) {
  $preflight += @{ Path = $LauncherUiBat; Label = 'Launcher UI batch' }
}

foreach ($item in $preflight) {
  if (-not (Test-Path -LiteralPath $item.Path)) {
    Write-LauncherLog "PREFLIGHT FAIL: $($item.Label) not found at $($item.Path)"
    if ($item.Label -like '*venv Python*') {
      Write-LauncherLog "Hint: in that component folder run: py -3 -m venv .venv  then  .\.venv\Scripts\pip install -r requirements.txt"
    }
    Wait-LauncherAck 'Preflight failed; press Enter to exit'
    exit 1
  }
}

# --- Sentinel (equivalent to: del /f /q "%OBS_SENTINEL%") ---
if ($EnableObs -and (Test-Path -LiteralPath $ObsSentinel)) {
  try {
    Remove-Item -LiteralPath $ObsSentinel -Recurse -Force -ErrorAction Stop
    Write-LauncherLog "OBS sentinel removed: $ObsSentinel"
  } catch {
    Write-LauncherLog "WARN: could not remove OBS sentinel: $($_.Exception.Message)"
  }
}

# Headless Python (worker, encoder): Hidden in production is OK. Scoreboard is Tkinter — never use Hidden
# (SW_HIDE can prevent the UI from coming up). OBS: Normal window avoids failed/minimized startup on some GPUs.
$pyHeadlessWindowStyle = if ($DebugMode) { 'Normal' } else { 'Hidden' }
$pyGuiWindowStyle = if ($DebugMode) { 'Normal' } else { 'Minimized' }
$obsWindowStyle = 'Normal'
# --disable-shutdown-check: honored on OBS 31.x; removed/ignored on OBS 32+ (rely on clearing .sentinel above).
# --disable-missing-files-check: avoids another modal that blocks automation.
# --verbose: richer OBS logs under %APPDATA%\obs-studio\logs (Help → Log Files in OBS).
$obsArgs = @('--disable-shutdown-check', '--disable-missing-files-check', '--startreplaybuffer', '--verbose')

if ($EnableWorker) {
  Write-LauncherLog 'Launching worker...'
  Start-Process -WorkingDirectory $WorkerDir -FilePath $pyWorker -ArgumentList @('main.py') -WindowStyle $pyHeadlessWindowStyle | Out-Null
} else {
  Write-LauncherLog 'Skipping worker (disabled by REPLAYTROVE_ENABLE_WORKER=0)'
}

if ($EnableEncoder) {
  Write-LauncherLog 'Launching encoder watchdog...'
  Start-Process -WorkingDirectory $EncoderDir -FilePath $pyEncoder -ArgumentList @('encoder_watchdog.py') -WindowStyle $pyHeadlessWindowStyle | Out-Null
} else {
  Write-LauncherLog 'Skipping encoder (disabled by REPLAYTROVE_ENABLE_ENCODER=0)'
}

$cleanerProc = $null
if ($EnableCleaner -and $CleanerOwnerMode -eq 'launcher') {
  Write-LauncherLog 'Launching Cleaner Bee...'
  $cleanerProc = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -ArgumentList @(
      '-NoProfile',
      '-WindowStyle', 'Hidden',
      '-ExecutionPolicy', 'Bypass',
      '-File', $CleanerScript
    ) `
    -WindowStyle Hidden `
    -PassThru
  if (-not $cleanerProc) {
    Write-LauncherLog 'ERROR: Cleaner Bee Start-Process did not return a process handle'
  }
} elseif ($EnableCleaner -and $CleanerOwnerMode -eq 'task_scheduler') {
  Write-LauncherLog 'Cleaner Bee ownership: task_scheduler mode active; launcher will not start cleaner process.'
} else {
  Write-LauncherLog 'Skipping Cleaner Bee (disabled by REPLAYTROVE_ENABLE_CLEANER=0)'
}

if ($EnableWorker) {
  $workerReady = Wait-Readiness -Label 'Worker (python main.py)' -TimeoutSec $ReadinessPythonSec -IntervalSec $ReadinessIntervalSec -Test {
    Test-PythonAppRunning -FolderPath $WorkerDir
  }
  if (-not $workerReady) {
    Write-LauncherLog 'ERROR: Worker process not detected in time'
  }
}

if ($EnableEncoder) {
  $encoderReady = Wait-Readiness -Label 'Encoder (python encoder_watchdog.py)' -TimeoutSec $ReadinessPythonSec -IntervalSec $ReadinessIntervalSec -Test {
    Test-PythonAppRunning -FolderPath $EncoderDir -ScriptName 'encoder_watchdog.py'
  }
  if (-not $encoderReady) {
    Write-LauncherLog 'ERROR: Encoder process not detected in time'
  }
}

if ($EnableObs) {
  Write-LauncherLog 'Launching OBS...'
  Start-Process -WorkingDirectory $ObsDir -FilePath $ObsExe -ArgumentList $obsArgs -WindowStyle $obsWindowStyle | Out-Null
} else {
  Write-LauncherLog 'Skipping OBS (disabled by REPLAYTROVE_ENABLE_OBS=0)'
}

if ($EnableControlApp) {
  Write-LauncherLog 'Launching control app...'
  Start-ControlAppForLauncher -ExePath $ControlAppExe -ArgumentsRaw $ControlAppArgs
} else {
  Write-LauncherLog 'Skipping control app (disabled by REPLAYTROVE_ENABLE_CONTROL_APP=0)'
}

if ($EnableLauncherUi) {
  Write-LauncherLog 'Launching Launcher UI...'
  Start-Process -FilePath $LauncherUiBat | Out-Null
} else {
  Write-LauncherLog 'Skipping Launcher UI (disabled by REPLAYTROVE_ENABLE_LAUNCHER_UI=0)'
}

# Readiness: OBS should be running before scoreboard (replaces fixed long sleep).
if ($EnableObs) {
  $obsReady = Wait-Readiness -Label 'OBS (obs64)' -TimeoutSec $ReadinessObsSec -IntervalSec $ReadinessIntervalSec -Test {
    $null -ne (Get-Process -Name 'obs64' -ErrorAction SilentlyContinue)
  }
  if (-not $obsReady) {
    Write-LauncherLog 'ERROR: OBS did not become ready in time'
  }
}

if ($EnableScoreboard) {
  Write-LauncherLog 'Launching scoreboard...'
  Start-Process -WorkingDirectory $ScoreboardDir -FilePath $pyScore -ArgumentList @('main.py') -WindowStyle $pyGuiWindowStyle | Out-Null

  $sbReady = Wait-Readiness -Label 'Scoreboard (python main.py)' -TimeoutSec $ReadinessPythonSec -IntervalSec $ReadinessIntervalSec -StabilitySec 3 -Test {
    Test-PythonAppRunning -FolderPath $ScoreboardDir
  }
  if (-not $sbReady) {
    Write-LauncherLog 'ERROR: Scoreboard process not detected in time'
  }
} else {
  Write-LauncherLog 'Skipping scoreboard (disabled by REPLAYTROVE_ENABLE_SCOREBOARD=0)'
}

# Post-launch validation (snapshot after short settle)
Start-Sleep -Seconds $ReadinessIntervalSec

Write-LauncherLog 'Post-launch validation...'
$validation = [ordered]@{}
if ($EnableWorker) { $validation['Worker'] = { Test-PythonAppRunning -FolderPath $WorkerDir } }
if ($EnableEncoder) { $validation['Encoder'] = { Test-PythonAppRunning -FolderPath $EncoderDir -ScriptName 'encoder_watchdog.py' } }
if ($EnableScoreboard) { $validation['Scoreboard'] = { Test-PythonAppRunning -FolderPath $ScoreboardDir } }
if ($EnableObs) { $validation['OBS'] = { $null -ne (Get-Process -Name 'obs64' -ErrorAction SilentlyContinue) } }
if ($EnableControlApp) { $validation['ControlApp'] = { $null -ne (Get-Process -Name $ControlAppProcessName -ErrorAction SilentlyContinue) } }

$allOk = $true
foreach ($key in $validation.Keys) {
  try {
    $ok = & $validation[$key]
  } catch {
    $ok = $false
    Write-LauncherLog "Validation error [$key]: $($_.Exception.Message)"
  }
  Write-LauncherLog "Validation: $key = $(if ($ok) { 'OK' } else { 'FAIL' })"
  if (-not $ok) { $allOk = $false }
}

if ($EnableCleaner -and $CleanerOwnerMode -eq 'launcher') {
  # Cleaner Bee: still running, or exited successfully (one-shot script)
  $cleanerOk = $false
  if ($cleanerProc) {
    try {
      $cleanerProc.Refresh()
      if (-not $cleanerProc.HasExited) {
        $cleanerOk = $true
        Write-LauncherLog 'Validation: Cleaner Bee = OK (still running)'
      } else {
        $code = $cleanerProc.ExitCode
        $cleanerOk = ($code -eq 0)
        Write-LauncherLog "Validation: Cleaner Bee = $(if ($cleanerOk) { 'OK' } else { 'FAIL' }) (exited, code $code)"
      }
    } catch {
      Write-LauncherLog "Validation: Cleaner Bee = indeterminate ($($_.Exception.Message)); checking WMI fallback"
      $cleanerOk = Test-CleanerBeeRunning
      Write-LauncherLog "Validation: Cleaner Bee (WMI fallback) = $(if ($cleanerOk) { 'OK' } else { 'FAIL' })"
    }
  } else {
    $cleanerOk = Test-CleanerBeeRunning
    Write-LauncherLog "Validation: Cleaner Bee (no PassThru proc) = $(if ($cleanerOk) { 'OK' } else { 'FAIL' }) (WMI)"
  }

  if (-not $cleanerOk) { $allOk = $false }
}

if (-not $allOk) {
  Write-LauncherLog 'SUPERVISOR: one or more validations failed.'
  Wait-LauncherAck 'Validation failed; press Enter to exit'
  exit 2
}

Write-LauncherLog 'Post-launch validation passed; UI focus/minimize...'
if ($EnableScoreboard) {
  Invoke-ScoreboardFocus -MaxAttempts $FocusMaxAttempts -RetryMs $FocusRetryMs `
    -Reason 'post-validation UI focus' -Title $ScoreboardWindowTitle -ScoreboardFolderPath $ScoreboardDir `
    -StatusJsonPath $ScoreboardStatusJson -StaleSec $ScoreboardStatusStaleSec -AllowRecovery $ScoreboardFocusRecovery | Out-Null
}
if ($EnableControlApp) {
  Invoke-ControlAppMinimizeIfNeeded -ProcessName $ControlAppProcessName -MaxAttempts $FocusMaxAttempts -RetryMs $FocusRetryMs | Out-Null
}

Write-LauncherLog 'All apps launched and validated.'

if (-not $SupervisionEnabled) {
  Write-LauncherLog 'SUPERVISION: disabled by configuration; launcher exiting after startup bootstrap.'
  Release-OwnerLease -Reason 'supervision_disabled'
  exit 0
}

Write-LauncherLog "SUPERVISION OWNER LEASE: path=$SupervisionOwnerLeasePath timeout_sec=$OwnerLeaseStaleSec"
if (-not (Try-ClaimOwnerLease)) {
  Wait-LauncherAck 'Another active launcher supervisor owner was detected; press Enter to exit'
  exit 4
}

Initialize-ScoreboardStatusWatchState
$watchDesired = Test-ScoreboardStatusWatchDesired
if ($watchDesired) {
  Write-LauncherLog "Scoreboard status watch enabled inside supervision loop (poll every ${ScoreboardStatusPollSec}s): $ScoreboardStatusJson"
} else {
  Write-LauncherLog 'Scoreboard status watch disabled for this run.'
}

$supervisionComponents = Get-SupervisionComponents
$supervisionStateMap = New-SupervisionStateMap -Components $supervisionComponents
$script:DesiredStateMap = New-DesiredStateMap -Components $supervisionComponents
if ($null -eq $script:DesiredStateMap) { $script:DesiredStateMap = @{} }
Write-LauncherLog ("SUPERVISION: phase-1 keepalive active components=" + (($supervisionComponents | ForEach-Object { $_.Name }) -join ','))
Write-LauncherLog "SUPERVISION DESIRED_STATE SNAPSHOT: path=$SupervisionDesiredStatePath"
Merge-SupervisionDesiredStateFromSnapshot -DesiredStateMap $script:DesiredStateMap
$rehydrated = (Get-ManagedDesiredStateComponentNames | ForEach-Object { "{0}={1}" -f $_, (Get-DesiredState -DesiredStateMap $script:DesiredStateMap -ComponentName $_) }) -join ', '
Write-LauncherLog "SUPERVISION DESIRED_STATE: after rehydration $rehydrated"
Ensure-LauncherIntentDirectories
Write-LauncherLog "INTENT bridge active: pending=$LauncherIntentsPendingDir processed=$LauncherIntentsProcessedDir failed=$LauncherIntentsFailedDir"

$lastScoreboardWatchTick = [DateTime]::MinValue
try {
  while ($true) {
    try {
      [void](Write-OwnerLease -Reason 'heartbeat')
      Process-LauncherIntentQueue -DesiredStateMap $script:DesiredStateMap
      if ($watchDesired) {
        $nowTick = Get-Date
        $elapsed = ($nowTick - $lastScoreboardWatchTick).TotalSeconds
        if ($lastScoreboardWatchTick -eq [DateTime]::MinValue -or $elapsed -ge $ScoreboardStatusPollSec) {
          Invoke-ScoreboardStatusWatchTick -StatusPath $ScoreboardStatusJson
          $lastScoreboardWatchTick = $nowTick
        }
      }
      Invoke-SupervisionTick -Components $supervisionComponents -StateMap $supervisionStateMap -DesiredStateMap $script:DesiredStateMap
    } catch {
      Write-LauncherLog "SUPERVISION ERROR: loop iteration failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $SupervisionPollSec
  }
} finally {
  Release-OwnerLease -Reason 'shutdown'
}
