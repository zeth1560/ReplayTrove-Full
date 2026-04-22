# ReplayTrove Configuration Inventory (Baseline)

This inventory captures current configuration sources before unified config migration.

## Current Sources

- **Environment files**
  - `scoreboard/.env.example`
  - `worker/.env.example`
  - `encoder/.env.example`
- **Python settings loaders**
  - `scoreboard/scoreboard/config/settings.py` (`load_settings`, env parsing + defaults)
  - `worker/config.py` (`load_settings`, `_require` / `_optional`)
  - `encoder/settings.py` (`load_encoder_settings`, `_opt`)
- **Launcher / automation settings**
  - `launcher/start_apps.bat` (REPLAYTROVE_* path + enable toggles)
  - `launcher/start_apps.ps1` (env-driven orchestration)
  - `launcher/launcher_ui.ps1` (hardcoded app paths + toggles)
  - `scripts/*.ps1`, `scripts/*.vbs` (hardcoded paths, host/port defaults)
- **State / generated files (runtime)**
  - `status.json`
  - `state/*.txt`
  - `commands/*/{pending,processed,failed}/*.json`
  - `launcher/scoreboard_status.json`

## Grouping

### A) Shared / global (editable operator settings candidate)

- Replay behavior defaults (timeouts, toggles, overlay choices)
- Scoreboard visual/operator timing values
- Worker non-secret pipeline controls
- Launcher behavior toggles / startup policy
- Cleaner maintenance cadence policies
- FFmpeg/OBS non-secret runtime knobs

### B) App-specific (editable operator settings candidate)

- Worker replay and ingestion tuning
- Scoreboard UI/overlay behavior
- Launcher process orchestration behavior
- Cleaner retention windows
- Web app/app shell controls (future)

### C) Secrets (env / secret-store only)

- AWS credentials (`AWS_*`, `SCOTT_AWS_*`)
- Supabase credentials (`SUPABASE_*`)
- Pickle Planner API key(s)
- OBS websocket password

### D) Runtime / generated state (not editable config)

- `commands/**` queue files
- `state/**` logs and lock files
- `status.json`
- `launcher/scoreboard_status.json`
- `encoder_state.json` and other health/status snapshots

## Migration Notes

- Current apps are env-first. Migration should keep env compatibility while moving non-secret settings to central config.
- Hardcoded absolute paths (`C:\ReplayTrove\...`) are common in scripts and launchers; introduce a shared root path setting and derive where possible.
- Preserve idempotent operator behavior while replacing legacy settings surfaces.
