param(
    [string]$ObsHost = "127.0.0.1",
    [int]$Port = 4455,
    [string]$Password = "",
    [string]$CorrelationId = ""
)

# Standalone CLI entrypoint; canonical pipeline dot-sources obs_save_replay_core.ps1 in-process instead.
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "replaytrove_json_log.ps1")
. (Join-Path $PSScriptRoot "obs_save_replay_core.ps1")
try {
    Invoke-ReplayTroveObsSaveReplayBuffer -ObsHost $ObsHost -Port $Port -Password $Password -CorrelationId $CorrelationId
    exit 0
}
catch {
    exit 1
}
