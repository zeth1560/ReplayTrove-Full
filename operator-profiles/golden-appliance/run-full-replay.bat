@echo off
REM Golden profile: canonical full replay pipeline. See README.md beside this file.
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0invoke-full-replay.ps1"
