#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\mpv_ipc_core.ps1"

# Short connect timeout: this runs before every replay launch when no mpv is listening;
# waiting the ipc_core default (8s) makes the scoreboard feel frozen.
Invoke-MpvIpcPipeline -ConnectTimeoutMs 800 -ReadTimeoutMs 2000 {
    param($send)
    & $send @{ command = @('quit') }
}
