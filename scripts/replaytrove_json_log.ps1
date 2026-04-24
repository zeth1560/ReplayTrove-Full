#Requires -Version 5.1
<#
.SYNOPSIS
  Append standard JSONL records under ReplayTrove central logs (date-first layout).

.LAYOUT
  {REPLAYTROVE_LOGS_ROOT}/yyyy-MM-dd/{service}.jsonl
  Same line mirrored to timeline.jsonl; index.json updated (Local mutex Local\ReplayTroveLogWrite).

.NOTES
  Set REPLAYTROVE_LOGS_ROOT or REPLAYTROVE_ROOT. Standard fields: timestamp, level, service,
  event, message, correlation_id, session_id, clip_id, context, metrics, state, type
#>

$script:RtLogMutexName = 'Local\ReplayTroveLogWrite'

function Get-ReplayTroveLogsRoot {
    if ($env:REPLAYTROVE_LOGS_ROOT -and $env:REPLAYTROVE_LOGS_ROOT.Trim()) {
        return $env:REPLAYTROVE_LOGS_ROOT.Trim()
    }
    $root = if ($env:REPLAYTROVE_ROOT -and $env:REPLAYTROVE_ROOT.Trim()) { $env:REPLAYTROVE_ROOT.Trim() } else { 'C:\ReplayTrove' }
    return (Join-Path $root 'logs')
}

function ConvertTo-RtStandardLevel {
    param([string]$Level)
    $u = $Level.ToUpperInvariant()
    if ($u -eq 'WARN') { return 'WARNING' }
    return $u
}

function Update-ReplayTroveDayIndex {
    param(
        [string]$IndexPath,
        [string]$Day,
        [string]$Timestamp,
        [string]$Service,
        [string]$Level,
        [string]$Event
    )
    $default = [ordered]@{
        date          = $Day
        services      = @()
        total_events  = 0
        error_count   = 0
        warnings      = 0
        restarts      = 0
        first_event   = $null
        last_event    = $null
    }
    $data = $default
    if (Test-Path -LiteralPath $IndexPath) {
        try {
            $raw = Get-Content -LiteralPath $IndexPath -Raw -Encoding UTF8
            $parsed = $raw | ConvertFrom-Json
            if ($parsed) {
                foreach ($k in $default.Keys) {
                    if ($null -ne $parsed.$k) { $data[$k] = $parsed.$k }
                }
            }
        }
        catch { }
    }
    $data.date = $Day
    $data.total_events = [int]$data.total_events + 1
    $svcSet = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($s in @($data.services)) { [void]$svcSet.Add([string]$s) }
    [void]$svcSet.Add($Service)
    $data.services = @($svcSet | Sort-Object)

    $ul = $Level.ToUpperInvariant()
    if ($ul -in 'ERROR', 'CRITICAL') { $data.error_count = [int]$data.error_count + 1 }
    if ($ul -eq 'WARNING') { $data.warnings = [int]$data.warnings + 1 }
    $evl = $Event.ToLowerInvariant()
    if ($evl -match 'restart|respawn|supervisor_restart') {
        $data.restarts = [int]$data.restarts + 1
    }
    if (-not $data.first_event -or ($Timestamp -lt [string]$data.first_event)) {
        $data.first_event = $Timestamp
    }
    if (-not $data.last_event -or ($Timestamp -gt [string]$data.last_event)) {
        $data.last_event = $Timestamp
    }
    $json = $data | ConvertTo-Json -Depth 12
    Set-Content -LiteralPath $IndexPath -Value $json -Encoding UTF8
}

function Write-ReplayTroveJsonl {
    param(
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][Alias('Component')][string]$Service,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Event,
        [ValidateSet('DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL')][string]$Level = 'INFO',
        [string]$Message = '',
        [hashtable]$Context = @{},
        [hashtable]$Metrics = @{},
        [Alias('Data')]
        [hashtable]$State = @{},
        [string]$Type = 'script',
        [string]$CorrelationId = $null,
        [string]$SessionId = $null,
        [string]$ClipId = $null,
        [string]$ScriptName = $null
    )

    $ErrorActionPreference = 'Stop'
    if ([string]::IsNullOrWhiteSpace($SessionId) -and $env:REPLAYTROVE_SESSION_ID) {
        $SessionId = $env:REPLAYTROVE_SESSION_ID.Trim()
    }
    $lvl = ConvertTo-RtStandardLevel -Level $Level
    $root = Get-ReplayTroveLogsRoot
    $day = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    $obsNs = [DateTime]::UtcNow.Ticks * 100

    $ctx = [ordered]@{}
    foreach ($k in $Context.Keys) { $ctx[$k] = $Context[$k] }
    $ctx.hostname = [Environment]::MachineName
    $ctx.process_id = $PID
    if ($ScriptName) { $ctx.script = $ScriptName }
    $ctx.observed_at_ns = $obsNs

    $payload = [ordered]@{
        timestamp       = $ts
        level           = $lvl
        service         = $Service
        event           = $Event
        message         = $Message
        correlation_id  = $CorrelationId
        session_id      = $SessionId
        clip_id         = $ClipId
        context         = $ctx
        metrics         = @{}
        state           = @{}
        type            = $Type
    }
    foreach ($k in $Metrics.Keys) { $payload.metrics[$k] = $Metrics[$k] }
    foreach ($k in $State.Keys) { $payload.state[$k] = $State[$k] }

    $line = ($payload | ConvertTo-Json -Compress -Depth 25)
    $dayDir = Join-Path $root $day
    $svcFile = Join-Path $dayDir ("{0}.jsonl" -f $Service)
    $tlFile = Join-Path $dayDir 'timeline.jsonl'
    $idxFile = Join-Path $dayDir 'index.json'

    $mtx = New-Object System.Threading.Mutex($false, $script:RtLogMutexName)
    [void]$mtx.WaitOne(120000)
    try {
        if (-not (Test-Path -LiteralPath $dayDir)) {
            New-Item -ItemType Directory -Path $dayDir -Force | Out-Null
        }
        Add-Content -LiteralPath $svcFile -Value $line -Encoding utf8
        Add-Content -LiteralPath $tlFile -Value $line -Encoding utf8
        Update-ReplayTroveDayIndex -IndexPath $idxFile -Day $day -Timestamp $ts -Service $Service -Level $lvl -Event $Event
    }
    finally {
        $mtx.ReleaseMutex()
        $mtx.Dispose()
    }
}
