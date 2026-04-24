#Requires -Version 5.1
<#
.SYNOPSIS
  Canonical replay entrypoint for appliance operation.

.DESCRIPTION
  Flow:
    1) Save replay buffer in OBS.
    2) Trigger worker replay processing via HTTP /replay.
    3) Wait for success response (timeout/fail closed).
    4) Only on success, send replay_on to scoreboard command bus.

  Existing scripts are intentionally left in place for compatibility; this script is the
  authoritative path for reliable replay triggering.

  Operator / installer guide: docs/operator-replay-trigger-runbook.md
#>
param(
    [string] $ObsHost = "",
    [int] $ObsPort = 0,
    [string] $ObsPassword = "",

    [string] $WorkerReplayHost = "",
    [int] $WorkerReplayPort = 0,
    [int] $WorkerReplayTimeoutSec = 0,
    [string] $ReplayCanonicalToken = $(if ($env:REPLAY_CANONICAL_TOKEN) { $env:REPLAY_CANONICAL_TOKEN } else { "" }),
    [switch] $SkipScoreboardReplayOn,
    [switch] $SkipObsSave,
    [switch] $UseWorkerTriggerFile,
    [string] $WorkerTriggerFile = $(if ($env:REPLAYTROVE_INSTANT_REPLAY_TRIGGER_FILE) { $env:REPLAYTROVE_INSTANT_REPLAY_TRIGGER_FILE } else { "C:\ReplayTrove\state\instant_replay.trigger" })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path (Split-Path -Parent $PSScriptRoot) "launcher\unified_config_adapter.ps1")
. (Join-Path $PSScriptRoot "replaytrove_json_log.ps1")
. (Join-Path $PSScriptRoot "obs_save_replay_core.ps1")

$stateDir = "C:\ReplayTrove\state"
$cid = [guid]::NewGuid().ToString("N")
$utcNow = [DateTimeOffset]::UtcNow
$triggerUnix = $utcNow.ToUnixTimeSeconds()
$script:WorkerCanonicalTrustCategory = "legacy_noncanonical"
$script:WorkerCanonicalTrustReason = "worker_not_contacted"

function Write-ReplayLog([string] $Message) {
    Write-ReplayTroveJsonl -Component 'scripts' -ScriptName 'save_replay_and_trigger.ps1' -Event 'replay_pipeline' -Level 'INFO' -Message $Message -Data @{
        correlation_id = $cid
        detail         = $Message
    }
}

function Resolve-SettingSource([string] $ParamName, [string] $EnvName) {
    if ($PSBoundParameters.ContainsKey($ParamName)) {
        return "param"
    }
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($EnvName))) {
        return "env"
    }
    return "default"
}

function Get-JsonSettingValue([hashtable] $Data, [string] $Path) {
    if (-not $Data) { return $null }
    $cur = $Data
    foreach ($segment in $Path.Split('.')) {
        if ($null -eq $cur) { return $null }
        if ($cur -is [System.Collections.IDictionary]) {
            if (-not $cur.Contains($segment)) { return $null }
            $cur = $cur[$segment]
            continue
        }
        return $null
    }
    return $cur
}

function Load-UnifiedSettings {
    $defaultPath = Join-Path (Split-Path -Parent $PSScriptRoot) "config\settings.json"
    $cfgPath = if (-not [string]::IsNullOrWhiteSpace($env:REPLAYTROVE_SETTINGS_FILE)) { $env:REPLAYTROVE_SETTINGS_FILE } else { $defaultPath }
    $snapshot = @{
        Found = $false
        Path = $cfgPath
        Data = @{}
        Error = $null
    }
    if (-not (Test-Path -LiteralPath $cfgPath)) {
        return $snapshot
    }
    $snapshot.Found = $true
    try {
        $raw = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8
        $parsed = $raw | ConvertFrom-Json
        $obj = ConvertTo-NestedHashtable -Node $parsed
        if ($obj -is [System.Collections.IDictionary]) {
            $snapshot.Data = $obj
        }
    }
    catch {
        $snapshot.Error = $_.Exception.Message
    }
    return $snapshot
}

function Resolve-ReplayStringSetting {
    param(
        [string]$ParamName,
        [string]$ParamValue,
        [hashtable]$UnifiedData,
        [string]$UnifiedPath,
        [string]$EnvName,
        [string]$DefaultValue
    )
    if ($PSBoundParameters.ContainsKey("ParamValue") -and $PSBoundParameters.ContainsKey("ParamName")) {
        if ($script:ParamNamesBound.Contains($ParamName) -and -not [string]::IsNullOrWhiteSpace($ParamValue)) {
            return @{ Value = $ParamValue.Trim(); Source = "param" }
        }
    }
    $u = Get-JsonSettingValue -Data $UnifiedData -Path $UnifiedPath
    if ($u -is [string] -and -not [string]::IsNullOrWhiteSpace($u)) {
        return @{ Value = $u.Trim(); Source = "unified" }
    }
    $e = [Environment]::GetEnvironmentVariable($EnvName)
    if (-not [string]::IsNullOrWhiteSpace($e)) {
        return @{ Value = $e.Trim(); Source = "env" }
    }
    return @{ Value = $DefaultValue; Source = "default" }
}

function Resolve-ReplayIntSetting {
    param(
        [string]$ParamName,
        [int]$ParamValue,
        [hashtable]$UnifiedData,
        [string]$UnifiedPath,
        [string]$EnvName,
        [int]$DefaultValue,
        [int]$MinimumValue
    )
    if ($script:ParamNamesBound.Contains($ParamName) -and $ParamValue -ge $MinimumValue) {
        return @{ Value = $ParamValue; Source = "param" }
    }
    $u = Get-JsonSettingValue -Data $UnifiedData -Path $UnifiedPath
    if ($u -is [int] -and $u -ge $MinimumValue) {
        return @{ Value = [int]$u; Source = "unified" }
    }
    if ($u -is [double] -and [int]$u -ge $MinimumValue) {
        return @{ Value = [int]$u; Source = "unified" }
    }
    $e = [Environment]::GetEnvironmentVariable($EnvName)
    if (-not [string]::IsNullOrWhiteSpace($e)) {
        try {
            $n = [int]$e.Trim()
            if ($n -ge $MinimumValue) {
                return @{ Value = $n; Source = "env" }
            }
        }
        catch { }
    }
    return @{ Value = $DefaultValue; Source = "default" }
}

function Invoke-ObsSaveReplay {
    if ([string]::IsNullOrWhiteSpace($ObsPassword)) {
        Write-ReplayLog "stage=obs_save password_missing=true note=attempting_without_password_if_obs_requires_auth_this_will_fail"
    }
    Write-ReplayLog "stage=obs_save start in_process=true host=$ObsHost port=$ObsPort"
    try {
        Invoke-ReplayTroveObsSaveReplayBuffer `
            -ObsHost $ObsHost `
            -Port $ObsPort `
            -Password $ObsPassword `
            -CorrelationId $cid
    }
    catch {
        Write-ReplayLog "stage=obs_save error=$($_.Exception.Message)"
        throw "obs_save_replay failed: $($_.Exception.Message)"
    }
    Write-ReplayLog "stage=obs_save ok"
}

function Invoke-WorkerReplayTrigger {
    if ($UseWorkerTriggerFile) {
        $triggerDir = Split-Path -Parent $WorkerTriggerFile
        if (-not (Test-Path -LiteralPath $triggerDir)) {
            New-Item -ItemType Directory -Path $triggerDir -Force | Out-Null
        }
        if (-not (Test-Path -LiteralPath $WorkerTriggerFile)) {
            New-Item -ItemType File -Path $WorkerTriggerFile -Force | Out-Null
            Write-ReplayLog "stage=worker_trigger mode=trigger_file created=$WorkerTriggerFile"
        }
        else {
            (Get-Item -LiteralPath $WorkerTriggerFile).LastWriteTime = Get-Date
            Write-ReplayLog "stage=worker_trigger mode=trigger_file touched=$WorkerTriggerFile"
        }
        return
    }

    if ($WorkerReplayPort -le 0) {
        throw "worker replay port invalid: $WorkerReplayPort"
    }
    $uri = "http://${WorkerReplayHost}:${WorkerReplayPort}/replay?trigger=${triggerUnix}&request_id=${cid}&trigger_source=save_replay_and_trigger.ps1"
    $hasCanonicalToken = -not [string]::IsNullOrWhiteSpace($ReplayCanonicalToken)
    Write-ReplayLog "stage=worker_trigger start uri=$uri timeout_sec=$WorkerReplayTimeoutSec canonical_token_supplied=$hasCanonicalToken"
    $headers = @{}
    if ($hasCanonicalToken) {
        $headers["X-Replay-Canonical-Token"] = $ReplayCanonicalToken
    }
    try {
        # Windows PowerShell 5.1: without -UseBasicParsing, IWR can throw NullReferenceException
        # when the legacy HTML parser (MSHTML) is unavailable or misconfigured (common on appliances).
        $http = Invoke-WebRequest -UseBasicParsing -Uri $uri -Method Get -Headers $headers -TimeoutSec $WorkerReplayTimeoutSec
    }
    catch {
        Write-ReplayLog "stage=worker_trigger transport_error=$($_.Exception.Message)"
        throw "worker replay HTTP request failed: $($_.Exception.Message)"
    }
    $statusCode = [int]$http.StatusCode
    $rawBody = [string]$http.Content
    Write-ReplayLog "stage=worker_trigger http_status=$statusCode body=$rawBody"

    $resp = $null
    try {
        $resp = $rawBody | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Write-ReplayLog "stage=worker_trigger parse_error=$($_.Exception.Message)"
        throw "worker replay returned malformed JSON response"
    }

    if ($null -eq $resp) {
        throw "worker replay returned empty JSON response"
    }
    if ($resp -isnot [pscustomobject] -and $resp -isnot [hashtable]) {
        throw "worker replay returned non-object JSON response"
    }

    $parsedSuccess = $resp.success
    $failureReason = if ($resp.failure_reason) { [string]$resp.failure_reason } else { "" }
    $exitCode = if ($null -ne $resp.exit_code) { [string]$resp.exit_code } else { "" }
    $trustCategory = if ($resp.canonical_trust_category) { [string]$resp.canonical_trust_category } else { "legacy_noncanonical" }
    $trustReason = if ($resp.canonical_trust_reason) { [string]$resp.canonical_trust_reason } else { "missing_worker_trust_fields" }
    $script:WorkerCanonicalTrustCategory = $trustCategory
    $script:WorkerCanonicalTrustReason = $trustReason
    Write-ReplayLog "stage=worker_trigger parsed_success=$parsedSuccess parsed_failure_reason=$failureReason parsed_exit_code=$exitCode trust_category=$trustCategory trust_reason=$trustReason"

    if ($parsedSuccess -ne $true) {
        $reason = if ($failureReason) { $failureReason } else { "missing_or_false_success" }
        throw "worker replay reported failure (failure_reason=$reason)"
    }
}

function Invoke-ScoreboardReplayOn {
    $sendScript = Join-Path $PSScriptRoot "send_command.ps1"
    $argsPayload = @{
        correlation_id = $cid
        triggered_at_utc = $utcNow.ToString("o")
        trigger_source = "save_replay_and_trigger.ps1"
        canonical_trust_category = $script:WorkerCanonicalTrustCategory
        canonical_trust_reason = $script:WorkerCanonicalTrustReason
    } | ConvertTo-Json -Compress
    Write-ReplayLog "stage=scoreboard_replay_on start script=$sendScript"
    & $sendScript -Target "scoreboard" -Action "replay_on" -ArgsJson $argsPayload
    # LASTEXITCODE is unset under StrictMode if the child script exits without a native exit code;
    # send_command.ps1 now ends with explicit exit 0. Treat unset as 0 only when $? is true.
    $sendExit = 0
    if (-not $?) {
        $sendExit = 1
    }
    else {
        try {
            $sendExit = [int]$LASTEXITCODE
        }
        catch {
            $sendExit = 0
        }
    }
    Write-ReplayLog "stage=scoreboard_replay_on exit_code=$sendExit"
    if ($sendExit -ne 0) {
        throw "send_command replay_on failed (exit_code=$sendExit)"
    }
}

try {
    $script:ParamNamesBound = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($k in $PSBoundParameters.Keys) { [void]$script:ParamNamesBound.Add([string]$k) }
    $unifiedSnapshot = Load-UnifiedSettings
    if ($unifiedSnapshot.Error) {
        Write-ReplayLog "config_unified_parse_error path=$($unifiedSnapshot.Path) error=$($unifiedSnapshot.Error)"
    }

    $resolvedWorkerHost = Resolve-ReplayStringSetting `
        -ParamName "WorkerReplayHost" `
        -ParamValue $WorkerReplayHost `
        -UnifiedData $unifiedSnapshot.Data `
        -UnifiedPath "worker.httpReplayTriggerHost" `
        -EnvName "REPLAY_TRIGGER_HTTP_HOST" `
        -DefaultValue "127.0.0.1"
    $resolvedWorkerPort = Resolve-ReplayIntSetting `
        -ParamName "WorkerReplayPort" `
        -ParamValue $WorkerReplayPort `
        -UnifiedData $unifiedSnapshot.Data `
        -UnifiedPath "worker.httpReplayTriggerPort" `
        -EnvName "REPLAY_TRIGGER_HTTP_PORT" `
        -DefaultValue 18765 `
        -MinimumValue 1
    $resolvedWorkerTimeout = Resolve-ReplayIntSetting `
        -ParamName "WorkerReplayTimeoutSec" `
        -ParamValue $WorkerReplayTimeoutSec `
        -UnifiedData $unifiedSnapshot.Data `
        -UnifiedPath "worker.httpReplayTriggerTimeoutSec" `
        -EnvName "REPLAY_TRIGGER_HTTP_TIMEOUT_SEC" `
        -DefaultValue 45 `
        -MinimumValue 1
    $WorkerReplayHost = [string]$resolvedWorkerHost.Value
    $WorkerReplayPort = [int]$resolvedWorkerPort.Value
    $WorkerReplayTimeoutSec = [int]$resolvedWorkerTimeout.Value
    $resolvedObsHost = Resolve-ReplayStringSetting `
        -ParamName "ObsHost" `
        -ParamValue $ObsHost `
        -UnifiedData $unifiedSnapshot.Data `
        -UnifiedPath "scoreboard.obsWebsocketHost" `
        -EnvName "OBS_WEBSOCKET_HOST" `
        -DefaultValue "localhost"
    $resolvedObsPort = Resolve-ReplayIntSetting `
        -ParamName "ObsPort" `
        -ParamValue $ObsPort `
        -UnifiedData $unifiedSnapshot.Data `
        -UnifiedPath "scoreboard.obsWebsocketPort" `
        -EnvName "OBS_WEBSOCKET_PORT" `
        -DefaultValue 4455 `
        -MinimumValue 1
    $resolvedObsPassword = Resolve-ReplayStringSetting `
        -ParamName "ObsPassword" `
        -ParamValue $ObsPassword `
        -UnifiedData $unifiedSnapshot.Data `
        -UnifiedPath "scoreboard.obsWebsocketPassword" `
        -EnvName "OBS_WEBSOCKET_PASSWORD" `
        -DefaultValue ""
    $ObsHost = [string]$resolvedObsHost.Value
    $ObsPort = [int]$resolvedObsPort.Value
    $ObsPassword = [string]$resolvedObsPassword.Value

    $obsHostSource = [string]$resolvedObsHost.Source
    $obsPortSource = [string]$resolvedObsPort.Source
    $obsPassSource = [string]$resolvedObsPassword.Source
    $workerHostSource = [string]$resolvedWorkerHost.Source
    $workerPortSource = [string]$resolvedWorkerPort.Source
    $workerTimeoutSource = [string]$resolvedWorkerTimeout.Source
    $canonicalTokenSource = Resolve-SettingSource -ParamName "ReplayCanonicalToken" -EnvName "REPLAY_CANONICAL_TOKEN"
    Write-ReplayLog "config_sources obs_host=$obsHostSource obs_port=$obsPortSource obs_password=$obsPassSource worker_host=$workerHostSource worker_port=$workerPortSource worker_timeout=$workerTimeoutSource canonical_token=$canonicalTokenSource precedence=param>unified>env>default unified_found=$($unifiedSnapshot.Found)"
    if ($workerHostSource -eq "env" -or $workerPortSource -eq "env" -or $workerTimeoutSource -eq "env" -or $workerHostSource -eq "default" -or $workerPortSource -eq "default" -or $workerTimeoutSource -eq "default") {
        Write-ReplayLog "config_fallback_warning replay_trigger_http_* fell_back_past_unified preferred_unified_keys=worker.httpReplayTriggerHost,worker.httpReplayTriggerPort,worker.httpReplayTriggerTimeoutSec"
    }
    if ($obsHostSource -eq "env" -or $obsHostSource -eq "default" -or $obsPortSource -eq "env" -or $obsPortSource -eq "default") {
        Write-ReplayLog "config_fallback_warning obs_websocket_host_port fell_back_past_unified preferred_unified_keys=scoreboard.obsWebsocketHost,scoreboard.obsWebsocketPort"
    }
    if ($obsPassSource -eq "env" -or $obsPassSource -eq "default") {
        Write-ReplayLog "config_fallback_warning obs_websocket_password fell_back_past_unified preferred_unified_key=scoreboard.obsWebsocketPassword"
    }
    if ($canonicalTokenSource -ne "env" -and [string]::IsNullOrWhiteSpace($ReplayCanonicalToken)) {
        Write-ReplayLog "config_fallback_warning replay_canonical_token_missing requests will be classified untrusted"
    }
    Write-ReplayLog "pipeline=start obs_host=$ObsHost obs_port=$ObsPort worker_host=$WorkerReplayHost worker_port=$WorkerReplayPort"
    if ($SkipObsSave) {
        Write-ReplayLog "stage=obs_save skipped=true"
    }
    else {
        Invoke-ObsSaveReplay
    }
    Invoke-WorkerReplayTrigger
    if ($SkipScoreboardReplayOn) {
        Write-ReplayLog "stage=scoreboard_replay_on skipped=true"
    }
    else {
        Invoke-ScoreboardReplayOn
    }
    Write-ReplayLog "pipeline=success"
    exit 0
}
catch {
    Write-ReplayLog "pipeline=fail reason=$($_.Exception.Message)"
    # Fail closed: do not trigger scoreboard replay if upstream failed.
    exit 1
}
