@echo off
setlocal EnableExtensions

rem ReplayTrove launcher: sets paths and env, then runs supervisor (start_apps.ps1).
rem Uses powershell.exe consistently for all PowerShell work.
rem OBS %APPDATA%\obs-studio\.sentinel cleanup is done in start_apps.ps1 (Remove-Item -Force, same intent as del /f /q).

rem --- Paths (override here if your install differs) ---
set "REPLAYTROVE_WORKER_DIR=C:\ReplayTrove\worker"
set "REPLAYTROVE_SCOREBOARD_DIR=C:\ReplayTrove\scoreboard"
set "REPLAYTROVE_ENCODER_DIR=C:\ReplayTrove\encoder"
set "REPLAYTROVE_CLEANER_SCRIPT=C:\ReplayTrove\cleaner\cleaner-bee.ps1"
set "REPLAYTROVE_OBS_DIR=C:\Program Files\obs-studio\bin\64bit"
set "REPLAYTROVE_OBS_EXE=%REPLAYTROVE_OBS_DIR%\obs64.exe"
set "REPLAYTROVE_OBS_SENTINEL=%APPDATA%\obs-studio\.sentinel"
rem Control surface app (default: Bitfocus Companion). Adjust EXE path if your install differs.
set "REPLAYTROVE_CONTROL_APP_EXE=C:\Program Files\Companion\Companion.exe"
set "REPLAYTROVE_CONTROL_APP_NAME=Companion"
set "REPLAYTROVE_CONTROL_APP_ARGS="
rem Legacy Stream Deck fallback: used when REPLAYTROVE_CONTROL_APP_EXE is not set (start_apps.ps1); harmless if Companion vars above are set.
rem set "REPLAYTROVE_STREAMDECK_EXE=C:\Program Files\Elgato\StreamDeck\StreamDeck.exe"

rem --- Modes ---
rem Interactive default: pause on preflight/validation failure.
rem For Task Scheduler, set REPLAYTROVE_PAUSE_ON_ERROR=0 before calling this batch (or uncomment below).
set "REPLAYTROVE_PAUSE_ON_ERROR=1"
rem set "REPLAYTROVE_PAUSE_ON_ERROR=0"

rem Production uses pythonw.exe (no consoles). For visible Python errors use debug:
rem set "REPLAYTROVE_LAUNCHER_DEBUG=1"
rem Optional per-app toggles (1=enabled, 0=disabled):
rem set "REPLAYTROVE_ENABLE_WORKER=1"
rem set "REPLAYTROVE_ENABLE_ENCODER=1"
rem set "REPLAYTROVE_ENABLE_CLEANER=1"
rem Cleaner ownership mode: task_scheduler (recommended) or launcher (legacy behavior).
rem set "REPLAYTROVE_CLEANER_OWNER_MODE=task_scheduler"
rem set "REPLAYTROVE_ENABLE_OBS=1"
rem set "REPLAYTROVE_ENABLE_CONTROL_APP=1"
rem Legacy: REPLAYTROVE_ENABLE_STREAMDECK (used only if REPLAYTROVE_ENABLE_CONTROL_APP is unset in start_apps.ps1)
rem set "REPLAYTROVE_ENABLE_STREAMDECK=1"
rem set "REPLAYTROVE_ENABLE_SCOREBOARD=1"
rem set "REPLAYTROVE_ENABLE_LAUNCHER_UI=1"

rem Scoreboard screensaver: when Encoder+OBS+Scoreboard are enabled, interactive runs of this
rem batch keep start_apps.ps1 open and poll scoreboard_status.json — Encoder/OBS stop in
rem screensaver and restart when active again. Task Scheduler: set REPLAYTROVE_SCOREBOARD_STATUS_WATCH=0
rem unless you want a blocking watch. Optional: REPLAYTROVE_SCOREBOARD_STATUS_JSON, POLL_SEC.
rem set "REPLAYTROVE_SCOREBOARD_STATUS_WATCH=0"
rem Launcher keepalive supervision loop (phase 1).
rem set "REPLAYTROVE_SUPERVISION_ENABLED=1"

rem Optional tuning — see start_apps.ps1 for meaning (seconds / milliseconds).
rem set "REPLAYTROVE_READINESS_OBS_SEC=120"
rem set "REPLAYTROVE_READINESS_PYTHON_SEC=90"
rem set "REPLAYTROVE_READINESS_INTERVAL_SEC=1"
rem set "REPLAYTROVE_FOCUS_MAX_ATTEMPTS=40"
rem set "REPLAYTROVE_FOCUS_RETRY_MS=500"
rem set "REPLAYTROVE_SCOREBOARD_STATUS_STALE_SEC=60"
rem set "REPLAYTROVE_SCOREBOARD_FOCUS_RECOVERY=0"

set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_apps.ps1"
exit /b %ERRORLEVEL%
