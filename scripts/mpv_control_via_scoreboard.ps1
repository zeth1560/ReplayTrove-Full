#Requires -Version 5.1
<#
  Optional explicit router (same as ``mpv_*.ps1`` now). Prefer keeping Companion paths on
  ``mpv_pause.ps1`` etc.; those scripts delegate here via ``mpv_scoreboard_delegate.ps1``.
#>
param(
    [Parameter(Mandatory = $true)]
    [string] $Action
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'mpv_scoreboard_delegate.ps1') -Action $Action
