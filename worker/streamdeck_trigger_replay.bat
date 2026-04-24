@echo off
REM Stream Deck: "System" -> "Open" -> this file (no arguments field needed).
REM Operator guide: docs\operator-replay-trigger-runbook.md
REM
REM Canonical full replay pipeline (OBS save buffer + worker HTTP + scoreboard replay_on):
REM   scripts\save_replay_and_trigger.ps1
REM This shortcut only notifies the worker over HTTP via the compatibility wrapper (no OBS SaveReplay here).
REM Port: set REPLAY_TRIGGER_HTTP_PORT, or defaults from config\settings.json worker.httpReplayTriggerPort, else 18765.
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\ReplayTrove\scripts\worker_notify_instant_replay.ps1" -Http
