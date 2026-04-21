#Requires -Version 5.1
<#
.SYNOPSIS
  ReplayTrove launcher / supervisor: start apps, wait for readiness, validate processes, UI tweaks.

  Configure paths via environment (set in start_apps.bat) or defaults below.
  REPLAYTROVE_LAUNCHER_DEBUG=1  -> use python.exe and normal windows for Python apps.
  REPLAYTROVE_PAUSE_ON_ERROR=0 -> do not pause on validation failure (e.g. scheduled task).

  When Scoreboard, Encoder, and OBS are all enabled, an interactive session keeps running after
  validation and polls scoreboard_status.json (screensaver_active). Screensaver on stops Encoder+OBS;
  screensaver off restarts them. REPLAYTROVE_SCOREBOARD_STATUS_WATCH=0 disables; =1 forces on.

  Scoreboard focus diagnostics: REPLAYTROVE_SCOREBOARD_STATUS_STALE_SEC (default 60) treats
  scoreboard_status.json updated_at older than N seconds as stale. Optional one-shot restore:
  REPLAYTROVE_SCOREBOARD_FOCUS_RECOVERY=1 after failed focus attempts (conservative; default off).
#>

$ErrorActionPreference = 'Stop'

# --- Config (override with env vars from start_apps.bat) ---
$WorkerDir = if ($env:REPLAYTROVE_WORKER_DIR)         { $env:REPLAYTROVE_WORKER_DIR }         else { 'C:\ReplayTrove\worker' }
$ScoreboardDir   = if ($env:REPLAYTROVE_SCOREBOARD_DIR)     { $env:REPLAYTROVE_SCOREBOARD_DIR }     else { 'C:\ReplayTrove\scoreboard' }
$Logs2DropboxDir = if ($env:REPLAYTROVE_LOGS2DROPBOX_DIR)   { $env:REPLAYTROVE_LOGS2DROPBOX_DIR }   else { 'C:\ReplayTrove\logs2dropbox' }
$EncoderDir      = if ($env:REPLAYTROVE_ENCODER_DIR)        { $env:REPLAYTROVE_ENCODER_DIR }        else { 'C:\ReplayTrove\encoder' }
$CleanerScript   = if ($env:REPLAYTROVE_CLEANER_SCRIPT)      { $env:REPLAYTROVE_CLEANER_SCRIPT }      else { 'C:\ReplayTrove\cleaner\cleaner-bee.ps1' }
$LauncherUiBat   = if ($env:REPLAYTROVE_LAUNCHER_UI_BAT)      { $env:REPLAYTROVE_LAUNCHER_UI_BAT }      else { Join-Path $PSScriptRoot 'launcher_ui.bat' }
$ObsDir          = if ($env:REPLAYTROVE_OBS_DIR) { $env:REPLAYTROVE_OBS_DIR }             else { 'C:\Program Files\obs-studio\bin\64bit' }
$ObsExe          = if ($env:REPLAYTROVE_OBS_EXE)            { $env:REPLAYTROVE_OBS_EXE }            else { Join-Path $ObsDir 'obs64.exe' }
$StreamDeckExe   = if ($env:REPLAYTROVE_STREAMDECK_EXE)     { $env:REPLAYTROVE_STREAMDECK_EXE }     else { 'C:\Program Files\Elgato\StreamDeck\StreamDeck.exe' }
$ObsSentinel     = if ($env:REPLAYTROVE_OBS_SENTINEL)        { $env:REPLAYTROVE_OBS_SENTINEL }        else { Join-Path $env:APPDATA 'obs-studio\.sentinel' }

$DebugMode       = ($env:REPLAYTROVE_LAUNCHER_DEBUG -eq '1')
$PauseOnError    = ($env:REPLAYTROVE_PAUSE_ON_ERROR -ne '0')

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

$EnableWorker = Test-AppEnabled -Name 'WORKER'
$EnableLogs2Dropbox = Test-AppEnabled -Name 'LOGS2DROPBOX'
$EnableEncoder = Test-AppEnabled -Name 'ENCODER'
$EnableCleaner = Test-AppEnabled -Name 'CLEANER'
$EnableObs = Test-AppEnabled -Name 'OBS'
$EnableStreamDeck = Test-AppEnabled -Name 'STREAMDECK'
$EnableScoreboard = Test-AppEnabled -Name 'SCOREBOARD'
$EnableLauncherUi = Test-AppEnabled -Name 'LAUNCHER_UI'

$ReadinessObsSec = if ($env:REPLAYTROVE_READINESS_OBS_SEC) { [int]$env:REPLAYTROVE_READINESS_OBS_SEC } else { 120 }
$ReadinessPythonSec = if ($env:REPLAYTROVE_READINESS_PYTHON_SEC) { [int]$env:REPLAYTROVE_READINESS_PYTHON_SEC } else { 90 }
$ReadinessIntervalSec = if ($env:REPLAYTROVE_READINESS_INTERVAL_SEC) { [int]$env:REPLAYTROVE_READINESS_INTERVAL_SEC } else { 1 }
$FocusMaxAttempts = if ($env:REPLAYTROVE_FOCUS_MAX_ATTEMPTS) { [int]$env:REPLAYTROVE_FOCUS_MAX_ATTEMPTS } else { 40 }
$FocusRetryMs = if ($env:REPLAYTROVE_FOCUS_RETRY_MS) { [int]$env:REPLAYTROVE_FOCUS_RETRY_MS } else { 500 }
$ScoreboardStatusStaleSec = if ($env:REPLAYTROVE_SCOREBOARD_STATUS_STALE_SEC) { [int]$env:REPLAYTROVE_SCOREBOARD_STATUS_STALE_SEC } else { 60 }
$ScoreboardFocusRecovery = ($env:REPLAYTROVE_SCOREBOARD_FOCUS_RECOVERY -eq '1')

$ScoreboardStatusJson = if ($env:REPLAYTROVE_SCOREBOARD_STATUS_JSON) { $env:REPLAYTROVE_SCOREBOARD_STATUS_JSON } else { Join-Path $PSScriptRoot 'scoreboard_status.json' }
$ScoreboardStatusPollSec = if ($env:REPLAYTROVE_SCOREBOARD_STATUS_POLL_SEC) { [int]$env:REPLAYTROVE_SCOREBOARD_STATUS_POLL_SEC } else { 2 }
$ScoreboardWindowTitle = 'ReplayTrove Scoreboard'

$LogDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$script:LaunchLog = Join-Path $LogDir "launcher-$LogStamp.log"

function Write-LauncherLog {
  param([string]$Message)
  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $Message
  Add-Content -LiteralPath $script:LaunchLog -Encoding utf8 -Value $line
  Write-Host $line
}

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
  $name = if ($DebugMode) { 'python.exe' } else { 'pythonw.exe' }
  Join-Path $AppDir ".venv\Scripts\$name"
}

function Test-PythonAppRunning {
  param(
    [string]$FolderPath,
    [string]$ScriptName = 'main.py'
  )
  $leaf = Split-Path -Path $FolderPath -Leaf
  $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue
  foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    if ($cmd -like "*\$leaf\*" -and $cmd -like "*$ScriptName*") { return $true }
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
    [int]$IntervalSec
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  while ((Get-Date) -lt $deadline) {
    try {
      if (& $Test) {
        Write-LauncherLog ('Readiness OK: {0} ({1:0.###}s)' -f $Label, $sw.Elapsed.TotalSeconds)
        return $true
      }
    } catch {
      Write-LauncherLog "Readiness check error ($Label): $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $IntervalSec
  }
  Write-LauncherLog "Readiness TIMEOUT: $Label (${TimeoutSec}s)"
  return $false
}

$script:LauncherWin32Loaded = $false
function Initialize-LauncherWin32 {
  if ($script:LauncherWin32Loaded) { return }
  Add-Type -Namespace ReplayTroveLauncher -Name User32 -Language CSharp -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

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
  $raw = [Environment]::GetEnvironmentVariable('REPLAYTROVE_SCOREBOARD_STATUS_WATCH')
  if ([string]::IsNullOrWhiteSpace($raw)) {
    return [Environment]::UserInteractive
  }
  switch ($raw.Trim().ToLowerInvariant()) {
    '1' { return $true }
    'true' { return $true }
    'yes' { return $true }
    'on' { return $true }
    '0' { return $false }
    'false' { return $false }
    'no' { return $false }
    'off' { return $false }
    default { return [Environment]::UserInteractive }
  }
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

function Invoke-ObsRestartForReplaySignal {
  param([string]$Reason)
  $why = if ([string]::IsNullOrWhiteSpace($Reason)) { '(unspecified)' } else { $Reason }
  Write-LauncherLog "Replay OBS restart signal: executing OBS restart flow (reason=$why)."
  Stop-Obs64ForLauncher
  Start-Sleep -Milliseconds 500
  Start-ObsForLauncher
  Write-LauncherLog "Replay OBS restart signal: OBS restart flow complete (reason=$why)."
}

function Stop-EncoderStackForLauncher {
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
  Start-Process -WorkingDirectory $EncoderDir -FilePath $pyEncoder -ArgumentList @('encoder_watchdog.py') -WindowStyle $pyWindowStyle | Out-Null
}

function Start-ObsForLauncher {
  if (Test-Path -LiteralPath $ObsSentinel) {
    try {
      Remove-Item -LiteralPath $ObsSentinel -Recurse -Force -ErrorAction Stop
    } catch {
      Write-LauncherLog "WARN: could not remove OBS sentinel before restart: $($_.Exception.Message)"
    }
  }
  Start-Process -WorkingDirectory $ObsDir -FilePath $ObsExe -ArgumentList $obsArgs -WindowStyle Minimized | Out-Null
}

function Invoke-ScoreboardStatusWatchLoop {
  param(
    [string]$StatusPath,
    [int]$PollSec
  )
  Write-LauncherLog "Scoreboard status watch started (poll every ${PollSec}s): $StatusPath"
  $lastScreensaver = $null
  $lastReplayRequested = $false
  $lastReplaySignalKey = $null
  while ($true) {
    $status = Read-ScoreboardStatusPayload -Path $StatusPath
    if ($status.ParseError) {
      Write-LauncherLog "Scoreboard status watch: parse error reading status JSON: $($status.ParseError)"
      Start-Sleep -Seconds $PollSec
      continue
    }
    if (-not $status.Available) {
      Start-Sleep -Seconds $PollSec
      continue
    }
    $current = $status.ScreensaverActive
    if ($null -eq $current) {
      Start-Sleep -Seconds $PollSec
      continue
    }

    $replayRequested = ($status.ReplayObsRestartRequested -eq $true)
    if ($replayRequested) {
      $signalKey = if ($null -ne $status.UpdatedAt) { $status.UpdatedAt.ToString('o') } else { $null }
      $isEdgeTrigger = (-not $lastReplayRequested)
      $isNewSignalKey = (-not [string]::IsNullOrWhiteSpace($signalKey) -and $signalKey -ne $lastReplaySignalKey)
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
          $lastReplaySignalKey = $signalKey
        }
      }
    }
    $lastReplayRequested = $replayRequested

    if ($null -eq $lastScreensaver) {
      if ($current) {
        Write-LauncherLog 'Initial scoreboard status: screensaver active; stopping Encoder and OBS.'
        Stop-EncoderStackForLauncher
        Stop-Obs64ForLauncher
      }
      $lastScreensaver = $current
      Start-Sleep -Seconds $PollSec
      continue
    }
    if ($current -eq $lastScreensaver) {
      Start-Sleep -Seconds $PollSec
      continue
    }
    $lastScreensaver = $current
    if ($current) {
      Write-LauncherLog 'Scoreboard entered screensaver; stopping Encoder and OBS.'
      Stop-EncoderStackForLauncher
      Stop-Obs64ForLauncher
    } else {
      Write-LauncherLog 'Scoreboard left screensaver; restarting Encoder and OBS.'
      Start-EncoderWatchdogForLauncher
      Start-Sleep -Milliseconds 400
      Start-ObsForLauncher
    }
    Start-Sleep -Seconds $PollSec
  }
}

function Invoke-StreamDeckMinimize {
  param([int]$MaxAttempts, [int]$RetryMs)
  Add-Type -Namespace Win32 -Name Show -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
'@ | Out-Null
  $SW_MINIMIZE = 6
  for ($i = 1; $i -le $MaxAttempts; $i++) {
    $sd = Get-Process -Name 'StreamDeck' -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero }
    if ($sd) {
      $hwnd = $sd[0].MainWindowHandle
      $called = [Win32.Show]::ShowWindowAsync($hwnd, $SW_MINIMIZE)
      Write-LauncherLog "Stream Deck minimize: ShowWindowAsync attempt $i, hwnd=$hwnd, result=$called"
      if ($called) { return $true }
    } else {
      Write-LauncherLog "Stream Deck minimize: no main window yet (attempt $i/$MaxAttempts)"
    }
    Start-Sleep -Milliseconds $RetryMs
  }
  Write-LauncherLog 'Stream Deck minimize: failed after all attempts'
  return $false
}

# --- Preflight ---
Write-LauncherLog "ReplayTrove launcher starting (supervisor). Log: $script:LaunchLog"
Write-LauncherLog "Mode: $(if ($DebugMode) { 'DEBUG (python.exe)' } else { 'PRODUCTION (pythonw.exe)' })"

$pyWorker = Get-PythonInterpreter $WorkerDir
$pyScore  = Get-PythonInterpreter $ScoreboardDir
$pyLogs = Get-PythonInterpreter $Logs2DropboxDir
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
if ($EnableLogs2Dropbox) {
  $preflight += @{ Path = (Join-Path $Logs2DropboxDir 'main.py'); Label = 'logs2dropbox main.py' }
  $preflight += @{ Path = $pyLogs; Label = 'logs2dropbox venv Python' }
}
if ($EnableEncoder) {
  $preflight += @{ Path = (Join-Path $EncoderDir 'encoder_watchdog.py'); Label = 'Encoder encoder_watchdog.py' }
  $preflight += @{ Path = $pyEncoder; Label = 'Encoder venv Python' }
}
if ($EnableCleaner) {
  $preflight += @{ Path = $CleanerScript; Label = 'Cleaner Bee script' }
}
if ($EnableObs) {
  $preflight += @{ Path = $ObsExe; Label = 'OBS executable' }
}
if ($EnableStreamDeck) {
  $preflight += @{ Path = $StreamDeckExe; Label = 'Stream Deck executable' }
}
if ($EnableLauncherUi) {
  $preflight += @{ Path = $LauncherUiBat; Label = 'Launcher UI batch' }
}

foreach ($item in $preflight) {
  if (-not (Test-Path -LiteralPath $item.Path)) {
    Write-LauncherLog "PREFLIGHT FAIL: $($item.Label) not found at $($item.Path)"
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

$pyWindowStyle = if ($DebugMode) { 'Normal' } else { 'Hidden' }
# --verbose: richer OBS logs under %APPDATA%\obs-studio\logs (Help → Log Files in OBS).
$obsArgs = @('--disable-shutdown-check', '--startreplaybuffer', '--verbose')

if ($EnableWorker) {
  Write-LauncherLog 'Launching worker...'
  Start-Process -WorkingDirectory $WorkerDir -FilePath $pyWorker -ArgumentList @('main.py') -WindowStyle $pyWindowStyle | Out-Null
} else {
  Write-LauncherLog 'Skipping worker (disabled by REPLAYTROVE_ENABLE_WORKER=0)'
}

if ($EnableLogs2Dropbox) {
  Write-LauncherLog 'Launching logs2dropbox...'
  Start-Process -WorkingDirectory $Logs2DropboxDir -FilePath $pyLogs -ArgumentList @('main.py') -WindowStyle $pyWindowStyle | Out-Null
} else {
  Write-LauncherLog 'Skipping logs2dropbox (disabled by REPLAYTROVE_ENABLE_LOGS2DROPBOX=0)'
}

if ($EnableEncoder) {
  Write-LauncherLog 'Launching encoder watchdog...'
  Start-Process -WorkingDirectory $EncoderDir -FilePath $pyEncoder -ArgumentList @('encoder_watchdog.py') -WindowStyle $pyWindowStyle | Out-Null
} else {
  Write-LauncherLog 'Skipping encoder (disabled by REPLAYTROVE_ENABLE_ENCODER=0)'
}

$cleanerProc = $null
if ($EnableCleaner) {
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

if ($EnableLogs2Dropbox) {
  $logs2Ready = Wait-Readiness -Label 'logs2dropbox (python main.py)' -TimeoutSec $ReadinessPythonSec -IntervalSec $ReadinessIntervalSec -Test {
    Test-PythonAppRunning -FolderPath $Logs2DropboxDir
  }
  if (-not $logs2Ready) {
    Write-LauncherLog 'ERROR: logs2dropbox process not detected in time'
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
  Start-Process -WorkingDirectory $ObsDir -FilePath $ObsExe -ArgumentList $obsArgs -WindowStyle Minimized | Out-Null
} else {
  Write-LauncherLog 'Skipping OBS (disabled by REPLAYTROVE_ENABLE_OBS=0)'
}

if ($EnableStreamDeck) {
  Write-LauncherLog 'Launching Stream Deck...'
  Start-Process -FilePath $StreamDeckExe -WindowStyle Minimized | Out-Null
} else {
  Write-LauncherLog 'Skipping Stream Deck (disabled by REPLAYTROVE_ENABLE_STREAMDECK=0)'
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
  Start-Process -WorkingDirectory $ScoreboardDir -FilePath $pyScore -ArgumentList @('main.py') -WindowStyle $pyWindowStyle | Out-Null

  $sbReady = Wait-Readiness -Label 'Scoreboard (python main.py)' -TimeoutSec $ReadinessPythonSec -IntervalSec $ReadinessIntervalSec -Test {
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
if ($EnableLogs2Dropbox) { $validation['logs2dropbox'] = { Test-PythonAppRunning -FolderPath $Logs2DropboxDir } }
if ($EnableEncoder) { $validation['Encoder'] = { Test-PythonAppRunning -FolderPath $EncoderDir -ScriptName 'encoder_watchdog.py' } }
if ($EnableScoreboard) { $validation['Scoreboard'] = { Test-PythonAppRunning -FolderPath $ScoreboardDir } }
if ($EnableObs) { $validation['OBS'] = { $null -ne (Get-Process -Name 'obs64' -ErrorAction SilentlyContinue) } }
if ($EnableStreamDeck) { $validation['StreamDeck'] = { $null -ne (Get-Process -Name 'StreamDeck' -ErrorAction SilentlyContinue) } }

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

if ($EnableCleaner) {
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
if ($EnableStreamDeck) {
  Invoke-StreamDeckMinimize -MaxAttempts $FocusMaxAttempts -RetryMs $FocusRetryMs | Out-Null
}

Write-LauncherLog 'All apps launched and validated.'

if (Test-ScoreboardStatusWatchDesired) {
  try {
    Invoke-ScoreboardStatusWatchLoop -StatusPath $ScoreboardStatusJson -PollSec $ScoreboardStatusPollSec
  } catch {
    Write-LauncherLog "Scoreboard status watch terminated: $($_.Exception.Message)"
    Wait-LauncherAck 'Scoreboard status watch error; press Enter to exit'
    exit 3
  }
}

exit 0
