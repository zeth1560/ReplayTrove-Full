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
$StreamDeckExe = 'C:\Program Files\Elgato\StreamDeck\StreamDeck.exe'
$CleanerScript = 'C:\ReplayTrove\cleaner\cleaner-bee.ps1'
$EncoderDir = if ($env:REPLAYTROVE_ENCODER_DIR) { $env:REPLAYTROVE_ENCODER_DIR } else { 'C:\ReplayTrove\encoder' }
$LauncherUiBat = Join-Path $PSScriptRoot 'launcher_ui.bat'
$LauncherUiPs1 = Join-Path $PSScriptRoot 'launcher_ui.ps1'

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
    Name = 'logs2dropbox'
    Env = 'REPLAYTROVE_ENABLE_LOGS2DROPBOX'
    IsRunning = { Test-PythonScriptRunning -FolderPath 'C:\ReplayTrove\logs2dropbox' -ScriptName 'main.py' }
    Start = { Start-PythonScript -FolderPath 'C:\ReplayTrove\logs2dropbox' -ScriptName 'main.py' }
    Stop = { Stop-ProcessList -Processes (Get-MatchingPythonProcesses -FolderPath 'C:\ReplayTrove\logs2dropbox' -ScriptName 'main.py') }
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
    Name = 'StreamDeck'
    Env = 'REPLAYTROVE_ENABLE_STREAMDECK'
    IsRunning = { (Get-ProcessByNameSafe -Name 'StreamDeck').Count -gt 0 }
    Start = { Start-Process -FilePath $StreamDeckExe -WindowStyle Minimized | Out-Null }
    Stop = { Stop-ProcessByNameSafe -Name 'StreamDeck' }
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
$form.Size = New-Object System.Drawing.Size(740, 430)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false

$title = New-Object System.Windows.Forms.Label
$title.Location = New-Object System.Drawing.Point(15, 12)
$title.Size = New-Object System.Drawing.Size(700, 24)
$title.Text = 'Use checkboxes for supervisor launch, or control selected apps directly below.'
$form.Controls.Add($title)

$rows = @()
$y = 45
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
    & $rowRef.App.Start
    Start-Sleep -Milliseconds 500
    Update-Statuses
  })
  $stopBtn.Add_Click({
    $rowRef = $this.Tag
    & $rowRef.App.Stop
    Start-Sleep -Milliseconds 500
    Update-Statuses
  })
  $restartBtn.Add_Click({
    $rowRef = $this.Tag
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
  Invoke-ForSelectedRows -Action { param($row) & $row.App.Start }
  Start-Sleep -Milliseconds 700
  Update-Statuses
})

$stopSelectedButton.Add_Click({
  Invoke-ForSelectedRows -Action { param($row) & $row.App.Stop }
  Start-Sleep -Milliseconds 700
  Update-Statuses
})

$restartSelectedButton.Add_Click({
  Invoke-ForSelectedRows -Action { param($row) & $row.App.Stop }
  Start-Sleep -Milliseconds 500
  Invoke-ForSelectedRows -Action { param($row) & $row.App.Start }
  Start-Sleep -Milliseconds 800
  Update-Statuses
})

$launchButton.Add_Click({
  foreach ($row in $rows) {
    $value = if ($row.Check.Checked) { '1' } else { '0' }
    [Environment]::SetEnvironmentVariable($row.App.Env, $value, 'Process')
  }
  $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $script = Join-Path $PSScriptRoot 'start_apps.ps1'
  Start-Process -FilePath $psExe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script) | Out-Null
})

Update-Statuses
[void]$form.ShowDialog()
