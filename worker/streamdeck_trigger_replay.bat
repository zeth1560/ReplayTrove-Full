@echo off
REM Stream Deck: "System" -> "Open" -> this file (no arguments field needed).
REM Change the port if yours is not 8791 (must match REPLAY_TRIGGER_HTTP_PORT).
set "RT_REPLAY_PORT=8791"

REM Route through canonical compatibility wrapper so bypass usage is visible in logs.
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$env:REPLAY_TRIGGER_HTTP_PORT=$env:RT_REPLAY_PORT; & 'C:\ReplayTrove\scripts\worker_notify_instant_replay.ps1' -Http"
