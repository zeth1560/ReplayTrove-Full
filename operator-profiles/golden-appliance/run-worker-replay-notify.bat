@echo off
REM Golden profile: worker HTTP notify only (OBS save must happen elsewhere). See README.md.
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0invoke-worker-replay-notify.ps1"
