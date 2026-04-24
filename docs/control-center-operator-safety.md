# Control Center Operator Safety Guide

The Control Center is designed for local appliance operators. It favors safe defaults, clear warnings, and compatibility with legacy environment settings.

## Opening Control Center on Windows (preferred)

On a Windows appliance or dev machine with the repo installed, **double-click `launch_control_center.bat` at the repository root** (or run it from Explorer). It starts the Control Center API and Vite UI if they are not already listening, opens the UI in your default browser, and appends a trace to `state\control_center_launch.log`. You can still start services manually with `npm` from the repo root if you prefer; the batch file does not replace that workflow.

Optional environment variables (before launch, or set system-wide): `REPLAYTROVE_ROOT` (repo path if the batch file is not in the repo root), `REPLAYTROVE_CONTROL_CENTER_API_PORT` (default `4311`, must match the UI’s API URL), and `REPLAYTROVE_CONTROL_CENTER_UI_PORT` (default `5173`).

## Safe/common settings

These are commonly adjusted during normal operations:

- Replay display toggle (`scoreboard.replayEnabled`)
- Slideshow and status display behavior
- Poll intervals and non-critical timing values

## Advanced settings

Advanced settings are still available, but some are hidden behind form collapse or JSON expert mode:

- Launcher focus/retry tuning
- Deep replay/ingest timing and retry internals
- Port and service conflict-prone fields

Use advanced settings only when troubleshooting or following a documented rollout.

## Dangerous settings

Dangerous settings are marked because they can break startup or replay plumbing if misconfigured.

### Startup-dangerous examples

- Launcher app directories and enable switches
- OBS / MPV / FFmpeg executable paths
- Control app executable path

### Runtime-dangerous examples

- Worker replay/watch/source folders
- Scoreboard replay media path
- Replay trigger enable/host/port fields

### Conflict-dangerous examples

- Port-bearing fields (`worker.httpReplayTriggerPort`, `webApp.port`)

## Save confirmation behavior

When dangerous fields are changed, Control Center asks for confirmation and lists:

- changed dangerous fields
- why each matters (impact text)
- whether restart is required

This confirmation is selective and only appears for high-impact edits.

## Restart expectations

Most worker/scoreboard/launcher/obs path and startup changes require restart.  
Phase 5 adds a narrow exception: scoreboard safe live reload for two polling intervals only.

## Scoreboard safe live reload workflow (Phase 5)

Use this only for:

- `scoreboard.obsStatusPollIntervalMs`
- `scoreboard.encoderStatusPollMs`

Operator steps:

1. Save config to disk.
2. Click **Apply safe live settings to scoreboard**.
3. Check:
   - **Safe Live Reload Queue Result** (queued vs failed to queue)
   - **Last Scoreboard Reload Outcome** (applied vs rejected from scoreboard status artifact)

Important:

- Queue success is not the same as applied success.
- Restart is still the safest path for all non-allowlisted settings.

## Secrets policy

Most secrets are intentionally excluded from editable unified config.  
Current exception: `scoreboard.obsWebsocketPassword` is operator-managed in Control Center for local appliance simplicity.

Do not put cloud credentials or API keys into `config/settings.json`.

## See also

- **Replay buttons and HTTP ports:** `docs/operator-replay-trigger-runbook.md`
