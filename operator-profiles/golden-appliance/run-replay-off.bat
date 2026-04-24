@echo off
REM Golden profile: scoreboard replay_off only. See README.md.
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0invoke-replay-off.ps1"
