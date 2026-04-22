Set-StrictMode -Version Latest

function Get-UnifiedNestedValue {
  param(
    [hashtable]$Object,
    [string]$Path
  )
  if (-not $Object) { return $null }
  $current = $Object
  foreach ($segment in $Path.Split('.')) {
    if ($null -eq $current) { return $null }
    if ($current -is [System.Collections.IDictionary]) {
      if (-not $current.Contains($segment)) { return $null }
      $current = $current[$segment]
      continue
    }
    return $null
  }
  return $current
}

function Get-ReplayTroveUnifiedConfig {
  $defaultPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'config\settings.json'
  $cfgPath = if ($env:REPLAYTROVE_SETTINGS_FILE) { $env:REPLAYTROVE_SETTINGS_FILE } else { $defaultPath }
  $snapshot = [ordered]@{
    Path = $cfgPath
    Found = $false
    SchemaVersion = $null
    Migrated = $false
    GeneralLoaded = $false
    LauncherLoaded = $false
    ObsFfmpegLoaded = $false
    Data = @{}
    Error = $null
  }
  if (-not (Test-Path -LiteralPath $cfgPath)) {
    return [pscustomobject]$snapshot
  }
  $snapshot.Found = $true
  try {
    $raw = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8
    $obj = $raw | ConvertFrom-Json -AsHashtable
    $snapshot.Data = $obj
    $snapshot.SchemaVersion = $obj['schemaVersion']
    $snapshot.GeneralLoaded = ($obj['general'] -is [System.Collections.IDictionary])
    $snapshot.LauncherLoaded = ($obj['launcher'] -is [System.Collections.IDictionary])
    $snapshot.ObsFfmpegLoaded = ($obj['obsFfmpegPaths'] -is [System.Collections.IDictionary])
  } catch {
    $snapshot.Error = $_.Exception.Message
  }
  return [pscustomobject]$snapshot
}

function Resolve-UnifiedFirstString {
  param(
    [hashtable]$UnifiedData,
    [string]$UnifiedPath,
    [string]$EnvName,
    [string]$Default,
    [string]$Label
  )
  $u = Get-UnifiedNestedValue -Object $UnifiedData -Path $UnifiedPath
  if ($u -is [string] -and -not [string]::IsNullOrWhiteSpace($u)) {
    return [pscustomobject]@{ Value = $u.Trim(); Source = 'unified'; Label = $Label }
  }
  $e = [Environment]::GetEnvironmentVariable($EnvName)
  if (-not [string]::IsNullOrWhiteSpace($e)) {
    return [pscustomobject]@{ Value = $e.Trim(); Source = 'env'; Label = $Label }
  }
  return [pscustomobject]@{ Value = $Default; Source = 'default'; Label = $Label }
}

function Resolve-UnifiedFirstBool {
  param(
    [hashtable]$UnifiedData,
    [string]$UnifiedPath,
    [string]$EnvName,
    [bool]$Default,
    [string]$Label
  )
  $u = Get-UnifiedNestedValue -Object $UnifiedData -Path $UnifiedPath
  if ($u -is [bool]) {
    return [pscustomobject]@{ Value = [bool]$u; Source = 'unified'; Label = $Label }
  }
  $e = [Environment]::GetEnvironmentVariable($EnvName)
  if (-not [string]::IsNullOrWhiteSpace($e)) {
    $v = $e.Trim().ToLowerInvariant()
    $b = $v -in @('1','true','yes','on')
    return [pscustomobject]@{ Value = $b; Source = 'env'; Label = $Label }
  }
  return [pscustomobject]@{ Value = $Default; Source = 'default'; Label = $Label }
}

function Resolve-UnifiedFirstInt {
  param(
    [hashtable]$UnifiedData,
    [string]$UnifiedPath,
    [string]$EnvName,
    [int]$Default,
    [int]$Minimum,
    [string]$Label
  )
  $u = Get-UnifiedNestedValue -Object $UnifiedData -Path $UnifiedPath
  if ($u -is [int] -and $u -ge $Minimum) {
    return [pscustomobject]@{ Value = [int]$u; Source = 'unified'; Label = $Label }
  }
  $e = [Environment]::GetEnvironmentVariable($EnvName)
  if (-not [string]::IsNullOrWhiteSpace($e)) {
    try {
      $n = [int]$e.Trim()
      if ($n -ge $Minimum) {
        return [pscustomobject]@{ Value = $n; Source = 'env'; Label = $Label }
      }
    } catch {}
  }
  return [pscustomobject]@{ Value = $Default; Source = 'default'; Label = $Label }
}
