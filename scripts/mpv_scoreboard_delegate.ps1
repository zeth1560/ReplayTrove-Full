#Requires -Version 5.1
<#
  Used by ``mpv_*.ps1`` operator scripts. Forwards to the scoreboard command bus so in-process
  JSON IPC reaches replay mpv. External ``powershell.exe`` often cannot see ``\\.\pipe\mpv``
  for the scoreboard-spawned instance.
#>
param(
    [Parameter(Mandatory = $true)]
    [string] $Action
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$send = Join-Path $PSScriptRoot 'send_command.ps1'
if (-not (Test-Path -LiteralPath $send)) {
    throw "send_command.ps1 not found: $send"
}
& $send -Target scoreboard -Action $Action.Trim() -ArgsJson '{}'
