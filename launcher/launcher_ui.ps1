Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = 'Stop'

function Get-MatchingPythonProcesses {
  param(
    [string]$FolderPath,
    [string]$ScriptName
  )
  $leaf = Split-Path -Path $FolderPath -Leaf
  $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and $_.CommandLine -like "*\$leaf\*" -and $_.CommandLine -like "*$ScriptName*"
    }
  return @($procs)
}

function Stop-ProcessList {
  param([array]$Processes)
  foreach ($p in $Processes) {
    try {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
    } catch {
      # Ignore race conditions where process already exited.
    }
  }
}

function Test-PythonScriptRunning {
  param(
    [string]$FolderPath,
    [string]$ScriptName
  )
  return (Get-MatchingPythonProcesses -FolderPath $FolderPath -ScriptName $ScriptName).Count -gt 0
}

function Test-EncoderStackRunning {
  param([string]$FolderPath)
  foreach ($sn in @('encoder_watchdog.py', 'operator_long_only.py', 'operator_tk.py')) {
    if (Test-PythonScriptRunning -FolderPath $FolderPath -ScriptName $sn) { return $true }
  }
  return $false
}

function Get-EncoderStackPythonProcesses {
  param([string]$FolderPath)
  $all = @()
  foreach ($sn in @('encoder_watchdog.py', 'operator_long_only.py', 'operator_tk.py')) {
    $all += Get-MatchingPythonProcesses -FolderPath $FolderPath -ScriptName $sn
  }
  return @($all | Sort-Object -Property ProcessId -Unique)
}

function Get-MatchingPowerShellScriptProcesses {
  param([string]$ScriptPath)
  $leaf = Split-Path -Path $ScriptPath -Leaf
  $procs = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$leaf*" }
  return @($procs)
}

function Test-CleanerRunning {
  param([string]$CleanerScriptPath)
  return (Get-MatchingPowerShellScriptProcesses -ScriptPath $CleanerScriptPath).Count -gt 0
}

function Start-PythonScript {
  param(
    [string]$FolderPath,
    [string]$ScriptName
  )
  $pythonw = Join-Path $FolderPath '.venv\Scripts\pythonw.exe'
  $python = Join-Path $FolderPath '.venv\Scripts\python.exe'
  $exe = if (Test-Path -LiteralPath $pythonw) { $pythonw } else { $python }
  Start-Process -WorkingDirectory $FolderPath -FilePath $exe -ArgumentList @($ScriptName) -WindowStyle Hidden | Out-Null
}

function Start-Cleaner {
  param([string]$CleanerScriptPath)
  Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File', $CleanerScriptPath) `
    -WindowStyle Hidden | Out-Null
}

function Get-ProcessByNameSafe {
  param([string]$Name)
  return @(Get-Process -Name $Name -ErrorAction SilentlyContinue)
}

function Stop-ProcessByNameSafe {
  param([string]$Name)
  Get-ProcessByNameSafe -Name $Name | ForEach-Object {
    try {
      Stop-Process -Id $_.Id -Force -ErrorAction Stop
    } catch {
      # Ignore race conditions where process already exited.
    }
  }
}

$ObsDir = 'C:\Program Files\obs-studio\bin\64bit'
$ObsExe = Join-Path $ObsDir 'obs64.exe'
$ObsSentinel = Join-Path $env:APPDATA 'obs-studio\.sentinel'
$CleanerScript = 'C:\ReplayTrove\cleaner\cleaner-bee.ps1'
$ControlAppExe = if ($env:REPLAYTROVE_CONTROL_APP_EXE) {
  $env:REPLAYTROVE_CONTROL_APP_EXE
} elseif ($env:REPLAYTROVE_STREAMDECK_EXE) {
  $env:REPLAYTROVE_STREAMDECK_EXE
} else {
  'C:\Program Files\Elgato\StreamDeck\StreamDeck.exe'
}
$ControlAppProcessName = if ($env:REPLAYTROVE_CONTROL_APP_NAME) {
  $env:REPLAYTROVE_CONTROL_APP_NAME
} else {
  'StreamDeck'
}
$ControlAppArgs = if ($env:REPLAYTROVE_CONTROL_APP_ARGS) { $env:REPLAYTROVE_CONTROL_APP_ARGS } else { '' }
$EncoderDir = if ($env:REPLAYTROVE_ENCODER_DIR) { $env:REPLAYTROVE_ENCODER_DIR } else { 'C:\ReplayTrove\encoder' }
$LauncherUiBat = Join-Path $PSScriptRoot 'launcher_ui.bat'
$LauncherUiPs1 = Join-Path $PSScriptRoot 'launcher_ui.ps1'
$SupervisionOwnerLeasePath = Join-Path $PSScriptRoot 'supervision_owner_lease.json'
$SupervisionStatusPath = Join-Path $PSScriptRoot 'supervision_status.json'
$SupervisionStatusStaleSec = 15
$LauncherManagedApps = @('Worker', 'Encoder', 'OBS', 'Scoreboard')
$LauncherIntentsRoot = Join-Path $PSScriptRoot 'intents'
$LauncherIntentsPendingDir = Join-Path $LauncherIntentsRoot 'pending'

function Write-UiLog {
  param([string]$Message)
  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $Message
  Write-Host $line
}

function Get-LauncherOwnershipState {
  if (Test-Path -LiteralPath $SupervisionOwnerLeasePath) {
    try {
      $rawLease = Get-Content -LiteralPath $SupervisionOwnerLeasePath -Raw -ErrorAction Stop
      $lease = $rawLease | ConvertFrom-Json -ErrorAction Stop
      $timeoutSec = 20
      if ($lease.lease_timeout_sec -is [int] -and [int]$lease.lease_timeout_sec -gt 0) {
        $timeoutSec = [int]$lease.lease_timeout_sec
      } elseif ($lease.lease_timeout_sec) {
        try {
          $n = [int]$lease.lease_timeout_sec
          if ($n -gt 0) { $timeoutSec = $n }
        } catch {}
      }
      $updatedAt = $null
      if ($lease.updated_at) {
        $dt = [DateTime]::MinValue
        if ([DateTime]::TryParse([string]$lease.updated_at, [ref]$dt)) {
          $updatedAt = $dt.ToUniversalTime()
        }
      }
      if ($null -eq $updatedAt) {
        return [pscustomobject]@{
          Active = $false
          Reason = 'owner_lease invalid updated_at'
          AgeSec = $null
        }
      }
      $ageSec = ([DateTime]::UtcNow - $updatedAt).TotalSeconds
      $leaseFresh = ($ageSec -le $timeoutSec)
      $pidAlive = $false
      if ($lease.pid) {
        try {
          $pidAlive = $null -ne (Get-Process -Id ([int]$lease.pid) -ErrorAction SilentlyContinue)
        } catch {
          $pidAlive = $false
        }
      }
      if ($leaseFresh -and $pidAlive) {
        return [pscustomobject]@{
          Active = $true
          Reason = ("owner lease active owner_id={0} pid={1} age_sec={2:0.0}" -f [string]$lease.owner_id, [string]$lease.pid, $ageSec)
          AgeSec = [Math]::Round($ageSec, 1)
        }
      }
      $leaseReason = [string]$lease.reason
      if ($leaseReason -in @('shutdown', 'stopped_by_operator', 'supervision_disabled')) {
        return [pscustomobject]@{
          Active = $false
          Reason = ("inactive (graceful shutdown: {0})" -f $leaseReason)
          AgeSec = [Math]::Round($ageSec, 1)
        }
      }
      return [pscustomobject]@{
        Active = $false
        Reason = ("owner lease stale_or_dead age_sec={0:0.0} timeout_sec={1} pid_alive={2}" -f $ageSec, $timeoutSec, $pidAlive)
        AgeSec = [Math]::Round($ageSec, 1)
      }
    } catch {
      # fall back to supervision status artifact.
    }
  }

  if (-not (Test-Path -LiteralPath $SupervisionStatusPath)) {
    return [pscustomobject]@{
      Active = $false
      Reason = "supervision_status missing"
      AgeSec = $null
    }
  }
  try {
    $item = Get-Item -LiteralPath $SupervisionStatusPath -ErrorAction Stop
    $ageSec = ([DateTime]::UtcNow - $item.LastWriteTimeUtc).TotalSeconds
    if ($ageSec -gt $SupervisionStatusStaleSec) {
      return [pscustomobject]@{
        Active = $false
        Reason = ("supervision_status stale age_sec={0:0.0}" -f $ageSec)
        AgeSec = [Math]::Round($ageSec, 1)
      }
    }
    return [pscustomobject]@{
      Active = $true
      Reason = ("supervision active (fresh heartbeat age_sec={0:0.0})" -f $ageSec)
      AgeSec = [Math]::Round($ageSec, 1)
    }
  } catch {
    return [pscustomobject]@{
      Active = $false
      Reason = ("supervision_status unreadable: {0}" -f $_.Exception.Message)
      AgeSec = $null
    }
  }
}

function Get-ManagedTargetName {
  param([string]$AppName)
  switch ($AppName) {
    'Worker' { return 'worker' }
    'Scoreboard' { return 'scoreboard' }
    'OBS' { return 'obs' }
    'Encoder' { return 'encoder_watchdog' }
    default { return $null }
  }
}

function Submit-LauncherIntent {
  param(
    [string]$Action,
    [string]$Target,
    [string]$SourceAction
  )
  $actionNorm = $Action.Trim().ToLowerInvariant()
  if ($actionNorm -notin @('start', 'stop', 'restart')) {
    throw "unsupported intent action: $Action"
  }
  if ([string]::IsNullOrWhiteSpace($Target)) {
    throw "intent target is required"
  }
  New-Item -ItemType Directory -Force -Path $LauncherIntentsPendingDir | Out-Null
  $now = [DateTime]::UtcNow
  $id = [guid]::NewGuid().ToString('N')
  $payload = [ordered]@{
    id = $id
    action = $actionNorm
    target = $Target
    created_at = $now.ToString('o')
    source = 'launcher_ui.ps1'
    source_action = $SourceAction
  }
  $ts = $now.ToString('yyyyMMddHHmmssfff')
  $baseName = "{0}_{1}_{2}_{3}" -f $ts, $actionNorm, $Target, $id
  $tmpPath = Join-Path $LauncherIntentsPendingDir ($baseName + '.tmp')
  $finalPath = Join-Path $LauncherIntentsPendingDir ($baseName + '.json')
  $json = $payload | ConvertTo-Json -Depth 6
  Set-Content -LiteralPath $tmpPath -Encoding UTF8 -Value $json
  Move-Item -LiteralPath $tmpPath -Destination $finalPath -Force
  return $finalPath
}

function Test-UiActionBlockedByOwnership {
  param(
    [hashtable]$Row,
    [string]$Action
  )
  $appName = [string]$Row.App.Name
  if ($LauncherManagedApps -notcontains $appName) {
    return $false
  }
  $owner = Get-LauncherOwnershipState
  if (-not $owner.Active) {
    return $false
  }
  $target = Get-ManagedTargetName -AppName $appName
  $intentAction = switch -Wildcard ($Action.ToLowerInvariant()) {
    'start*' { 'start'; break }
    'stop*' { 'stop'; break }
    default { 'restart' }
  }
  if ([string]::IsNullOrWhiteSpace($target)) {
    $msg = "Launcher supervision is active. Direct UI action '$Action' for '$appName' is blocked to avoid dual-owner conflicts."
    [void][System.Windows.Forms.MessageBox]::Show($msg, 'ReplayTrove Launcher', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
    Write-UiLog "UI action blocked by supervision owner: action=$Action app=$appName reason=$($owner.Reason)"
    return $true
  }
  try {
    $intentPath = Submit-LauncherIntent -Action $intentAction -Target $target -SourceAction $Action
    $msg = "Launcher supervision is active. A '$intentAction' request was sent to launcher supervisor for '$appName'.`n`nIntent: $intentPath"
    [void][System.Windows.Forms.MessageBox]::Show($msg, 'ReplayTrove Launcher', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
    Write-UiLog "UI action rerouted to intent bridge: action=$Action intent_action=$intentAction app=$appName target=$target intent=$intentPath reason=$($owner.Reason)"
  } catch {
    $msg = "Launcher supervision is active, but request failed for '$appName'.`n`nError: $($_.Exception.Message)"
    [void][System.Windows.Forms.MessageBox]::Show($msg, 'ReplayTrove Launcher', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
    Write-UiLog "UI intent submission failed: action=$Action app=$appName target=$target error=$($_.Exception.Message)"
  }
  return $true
}

function Get-LauncherUiProcesses {
  $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      ($_.Name -eq 'powershell.exe' -or $_.Name -eq 'cmd.exe') -and
      $_.CommandLine -and
      ($_.CommandLine -like "*launcher_ui.ps1*" -or $_.CommandLine -like "*launcher_ui.bat*")
    }
  return @($procs)
}

function Test-LauncherUiRunning {
  return (Get-LauncherUiProcesses).Count -gt 0
}

function Stop-LauncherUi {
  # Stop other launcher UI wrappers first; keep the current UI process alive.
  $currentPid = $PID
  $targets = Get-LauncherUiProcesses | Where-Object { $_.ProcessId -ne $currentPid }
  Stop-ProcessList -Processes $targets
}

$apps = @(
  @{
    Name = 'Worker'
    Env = 'REPLAYTROVE_ENABLE_WORKER'
    IsRunning = { Test-PythonScriptRunning -FolderPath 'C:\ReplayTrove\worker' -ScriptName 'main.py' }
    Start = { Start-PythonScript -FolderPath 'C:\ReplayTrove\worker' -ScriptName 'main.py' }
    Stop = { Stop-ProcessList -Processes (Get-MatchingPythonProcesses -FolderPath 'C:\ReplayTrove\worker' -ScriptName 'main.py') }
  }
  @{
    Name = 'Encoder'
    Env = 'REPLAYTROVE_ENABLE_ENCODER'
    IsRunning = { Test-EncoderStackRunning -FolderPath $EncoderDir }
    Start = { Start-PythonScript -FolderPath $EncoderDir -ScriptName 'encoder_watchdog.py' }
    Stop = { Stop-ProcessList -Processes (Get-EncoderStackPythonProcesses -FolderPath $EncoderDir) }
  }
  @{
    Name = 'Cleaner Bee'
    Env = 'REPLAYTROVE_ENABLE_CLEANER'
    IsRunning = { Test-CleanerRunning -CleanerScriptPath $CleanerScript }
    Start = { Start-Cleaner -CleanerScriptPath $CleanerScript }
    Stop = { Stop-ProcessList -Processes (Get-MatchingPowerShellScriptProcesses -ScriptPath $CleanerScript) }
  }
  @{
    Name = 'OBS'
    Env = 'REPLAYTROVE_ENABLE_OBS'
    IsRunning = { (Get-ProcessByNameSafe -Name 'obs64').Count -gt 0 }
    Start = {
      if (Test-Path -LiteralPath $ObsSentinel) {
        Remove-Item -LiteralPath $ObsSentinel -Recurse -Force -ErrorAction SilentlyContinue
      }
      Start-Process -WorkingDirectory $ObsDir -FilePath $ObsExe -ArgumentList @('--disable-shutdown-check', '--startreplaybuffer', '--verbose') -WindowStyle Minimized | Out-Null
    }
    Stop = { Stop-ProcessByNameSafe -Name 'obs64' }
  }
  @{
    Name = 'Control App'
    Env = 'REPLAYTROVE_ENABLE_CONTROL_APP'
    IsRunning = { (Get-ProcessByNameSafe -Name $ControlAppProcessName).Count -gt 0 }
    Start = {
      if ([string]::IsNullOrWhiteSpace($ControlAppArgs)) {
        Start-Process -FilePath $ControlAppExe -WindowStyle Minimized | Out-Null
      } else {
        $argList = $ControlAppArgs.Trim() -split '\s+', [System.StringSplitOptions]::RemoveEmptyEntries
        Start-Process -FilePath $ControlAppExe -ArgumentList $argList -WindowStyle Minimized | Out-Null
      }
    }
    Stop = { Stop-ProcessByNameSafe -Name $ControlAppProcessName }
  }
  @{
    Name = 'Scoreboard'
    Env = 'REPLAYTROVE_ENABLE_SCOREBOARD'
    IsRunning = { Test-PythonScriptRunning -FolderPath 'C:\ReplayTrove\scoreboard' -ScriptName 'main.py' }
    Start = { Start-PythonScript -FolderPath 'C:\ReplayTrove\scoreboard' -ScriptName 'main.py' }
    Stop = { Stop-ProcessList -Processes (Get-MatchingPythonProcesses -FolderPath 'C:\ReplayTrove\scoreboard' -ScriptName 'main.py') }
  }
  @{
    Name = 'Launcher UI'
    Env = 'REPLAYTROVE_ENABLE_LAUNCHER_UI'
    IsRunning = { Test-LauncherUiRunning }
    Start = { Start-Process -FilePath $LauncherUiBat | Out-Null }
    Stop = { Stop-LauncherUi }
  }
)

$form = New-Object System.Windows.Forms.Form
$form.Text = 'ReplayTrove Launcher'
$form.Size = New-Object System.Drawing.Size(740, 460)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false

$title = New-Object System.Windows.Forms.Label
$title.Location = New-Object System.Drawing.Point(15, 12)
$title.Size = New-Object System.Drawing.Size(700, 24)
$title.Text = 'Use checkboxes for supervisor launch, or control selected apps directly below.'
$form.Controls.Add($title)

$ownershipLabel = New-Object System.Windows.Forms.Label
$ownershipLabel.Location = New-Object System.Drawing.Point(15, 34)
$ownershipLabel.Size = New-Object System.Drawing.Size(700, 24)
$ownershipLabel.Text = 'Launcher supervision ownership: checking...'
$form.Controls.Add($ownershipLabel)

$rows = @()
$y = 66
foreach ($app in $apps) {
  $checkbox = New-Object System.Windows.Forms.CheckBox
  $checkbox.Location = New-Object System.Drawing.Point(20, $y)
  $checkbox.Size = New-Object System.Drawing.Size(170, 24)
  $checkbox.Checked = $true
  $checkbox.Text = $app.Name
  $form.Controls.Add($checkbox)

  $status = New-Object System.Windows.Forms.Label
  $status.Location = New-Object System.Drawing.Point(210, ($y + 2))
  $status.Size = New-Object System.Drawing.Size(180, 24)
  $status.Text = 'Status: unknown'
  $form.Controls.Add($status)

  $startBtn = New-Object System.Windows.Forms.Button
  $startBtn.Location = New-Object System.Drawing.Point(410, $y)
  $startBtn.Size = New-Object System.Drawing.Size(80, 24)
  $startBtn.Text = 'Start'
  $form.Controls.Add($startBtn)

  $stopBtn = New-Object System.Windows.Forms.Button
  $stopBtn.Location = New-Object System.Drawing.Point(500, $y)
  $stopBtn.Size = New-Object System.Drawing.Size(80, 24)
  $stopBtn.Text = 'Stop'
  $form.Controls.Add($stopBtn)

  $restartBtn = New-Object System.Windows.Forms.Button
  $restartBtn.Location = New-Object System.Drawing.Point(590, $y)
  $restartBtn.Size = New-Object System.Drawing.Size(80, 24)
  $restartBtn.Text = 'Restart'
  $form.Controls.Add($restartBtn)

  $row = @{
    App = $app
    Check = $checkbox
    Status = $status
    StartButton = $startBtn
    StopButton = $stopBtn
    RestartButton = $restartBtn
  }
  $rows += $row

  $startBtn.Tag = $row
  $stopBtn.Tag = $row
  $restartBtn.Tag = $row

  $startBtn.Add_Click({
    $rowRef = $this.Tag
    if (Test-UiActionBlockedByOwnership -Row $rowRef -Action 'start') { return }
    & $rowRef.App.Start
    Start-Sleep -Milliseconds 500
    Update-Statuses
  })
  $stopBtn.Add_Click({
    $rowRef = $this.Tag
    if (Test-UiActionBlockedByOwnership -Row $rowRef -Action 'stop') { return }
    & $rowRef.App.Stop
    Start-Sleep -Milliseconds 500
    Update-Statuses
  })
  $restartBtn.Add_Click({
    $rowRef = $this.Tag
    if (Test-UiActionBlockedByOwnership -Row $rowRef -Action 'restart') { return }
    & $rowRef.App.Stop
    Start-Sleep -Milliseconds 400
    & $rowRef.App.Start
    Start-Sleep -Milliseconds 600
    Update-Statuses
  })

  $y += 38
}

$launchButton = New-Object System.Windows.Forms.Button
$launchButton.Location = New-Object System.Drawing.Point(20, 350)
$launchButton.Size = New-Object System.Drawing.Size(160, 28)
$launchButton.Text = 'Launch Selected'
$form.Controls.Add($launchButton)

$startSelectedButton = New-Object System.Windows.Forms.Button
$startSelectedButton.Location = New-Object System.Drawing.Point(195, 350)
$startSelectedButton.Size = New-Object System.Drawing.Size(120, 28)
$startSelectedButton.Text = 'Start Selected'
$form.Controls.Add($startSelectedButton)

$stopSelectedButton = New-Object System.Windows.Forms.Button
$stopSelectedButton.Location = New-Object System.Drawing.Point(330, 350)
$stopSelectedButton.Size = New-Object System.Drawing.Size(120, 28)
$stopSelectedButton.Text = 'Stop Selected'
$form.Controls.Add($stopSelectedButton)

$restartSelectedButton = New-Object System.Windows.Forms.Button
$restartSelectedButton.Location = New-Object System.Drawing.Point(465, 350)
$restartSelectedButton.Size = New-Object System.Drawing.Size(120, 28)
$restartSelectedButton.Text = 'Restart Selected'
$form.Controls.Add($restartSelectedButton)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Location = New-Object System.Drawing.Point(600, 350)
$refreshButton.Size = New-Object System.Drawing.Size(120, 28)
$refreshButton.Text = 'Refresh Status'
$form.Controls.Add($refreshButton)

function Update-Statuses {
  $owner = Get-LauncherOwnershipState
  if ($owner.Active) {
    $ownershipLabel.Text = "Launcher supervision ownership: ACTIVE ($($owner.Reason))"
    $ownershipLabel.ForeColor = [System.Drawing.Color]::DarkGreen
  } else {
    $ownershipLabel.Text = "Launcher supervision ownership: INACTIVE ($($owner.Reason))"
    $ownershipLabel.ForeColor = [System.Drawing.Color]::DarkOrange
  }
  foreach ($row in $rows) {
    $running = $false
    try {
      $running = & $row.App.IsRunning
    } catch {
      $running = $false
    }
    if ($running) {
      $row.Status.Text = 'Status: RUNNING'
      $row.Status.ForeColor = [System.Drawing.Color]::DarkGreen
    } else {
      $row.Status.Text = 'Status: NOT RUNNING'
      $row.Status.ForeColor = [System.Drawing.Color]::DarkRed
    }
  }
}

function Invoke-ForSelectedRows {
  param([scriptblock]$Action)
  foreach ($row in $rows) {
    if ($row.Check.Checked) {
      & $Action $row
    }
  }
}

$refreshButton.Add_Click({ Update-Statuses })

$startSelectedButton.Add_Click({
  Invoke-ForSelectedRows -Action { param($row) if (-not (Test-UiActionBlockedByOwnership -Row $row -Action 'start_selected')) { & $row.App.Start } }
  Start-Sleep -Milliseconds 700
  Update-Statuses
})

$stopSelectedButton.Add_Click({
  Invoke-ForSelectedRows -Action { param($row) if (-not (Test-UiActionBlockedByOwnership -Row $row -Action 'stop_selected')) { & $row.App.Stop } }
  Start-Sleep -Milliseconds 700
  Update-Statuses
})

$restartSelectedButton.Add_Click({
  Invoke-ForSelectedRows -Action { param($row) if (-not (Test-UiActionBlockedByOwnership -Row $row -Action 'restart_selected_stop')) { & $row.App.Stop } }
  Start-Sleep -Milliseconds 500
  Invoke-ForSelectedRows -Action { param($row) if (-not (Test-UiActionBlockedByOwnership -Row $row -Action 'restart_selected_start')) { & $row.App.Start } }
  Start-Sleep -Milliseconds 800
  Update-Statuses
})

$launchButton.Add_Click({
  $owner = Get-LauncherOwnershipState
  if ($owner.Active) {
    [void][System.Windows.Forms.MessageBox]::Show(
      "Launcher supervision is already active. Launching another supervisor instance is blocked to avoid ownership conflicts.",
      'ReplayTrove Launcher',
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Warning
    )
    Write-UiLog "UI launch blocked: supervision owner already active ($($owner.Reason))"
    return
  }
  foreach ($row in $rows) {
    $value = if ($row.Check.Checked) { '1' } else { '0' }
    [Environment]::SetEnvironmentVariable($row.App.Env, $value, 'Process')
  }
  $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $script = Join-Path $PSScriptRoot 'start_apps.ps1'
  Start-Process -FilePath $psExe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script) | Out-Null
  Write-UiLog 'UI launched start_apps.ps1 as supervisor owner.'
})

Update-Statuses
[void]$form.ShowDialog()
