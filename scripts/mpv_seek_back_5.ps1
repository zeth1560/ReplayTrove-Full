#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'mpv_scoreboard_delegate.ps1') -Action mpv_seek_back_5
