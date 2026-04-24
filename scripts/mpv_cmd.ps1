#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$Json
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\mpv_ipc_core.ps1"

Invoke-MpvIpcCommandBatch @($Json)
