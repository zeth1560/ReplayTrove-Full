# ReplayTrove Config Authority Audit (Phase 1)

This document captures current authority and fallback precedence for replay-critical settings.

## Precedence model (current)

- Worker runtime settings: `config/settings.json` (unified) -> env var -> code default
- Scoreboard migrated settings: `config/settings.json` (unified) -> env var -> code default
- Canonical replay script (`scripts/save_replay_and_trigger.ps1`): script param -> env var -> script default
- Secrets remain env-driven (`OBS_WEBSOCKET_PASSWORD`, `REPLAY_CANONICAL_TOKEN`)

## Authority map (focused settings)

- `worker.httpReplayTriggerHost` / `REPLAY_TRIGGER_HTTP_HOST`
  - Authority: unified (`config/settings.json` -> `worker.httpReplayTriggerHost`) in worker runtime.
  - Canonical script uses env/param today; logs env fallback warning.
  - Drift risk: script host can diverge from worker host if env differs.

- `worker.httpReplayTriggerPort` / `REPLAY_TRIGGER_HTTP_PORT`
  - Authority: unified (`worker.httpReplayTriggerPort`) in worker runtime.
  - Canonical script uses env/param today; logs env fallback warning.
  - Drift risk: script port can diverge from worker listener if env differs.

- `REPLAY_TRIGGER_HTTP_TIMEOUT_SEC`
  - Authority: canonical script param/env/default (`45`).
  - Not currently unified-managed.
  - Drift risk: operator may assume Control Center governs this (it does not).

- `REPLAY_CANONICAL_TOKEN`
  - Authority: env only (secret).
  - Used by canonical script and worker replay HTTP trust checks.
  - Empty/missing token is allowed in phase 1; explicitly logged as untrusted classification path.

- `OBS_WEBSOCKET_HOST` / `OBS_WEBSOCKET_PORT`
  - Scoreboard authority: env/default in scoreboard settings (not unified-managed currently).
  - Canonical script authority: param/env/default.
  - Drift risk: scoreboard OBS target can diverge from script OBS target.

- `OBS_WEBSOCKET_PASSWORD`
  - Authority: env/param (secret); intentionally not unified-managed.
  - Canonical script and scoreboard read separately.

- Replay-related paths (`worker.instantReplaySource`, `worker.longClipsFolder`, `worker.instantReplayTriggerFile`, scoreboard replay asset paths)
  - Authority: unified first in worker/scoreboard settings adapters.
  - Env/default fallback retained for compatibility and logged.

- Scoreboard command bus path
  - Unified field exists: `scoreboard.commandsRoot`.
  - Runtime currently still uses hardcoded constants in `scoreboard/scoreboard/app.py`.
  - Phase-1 mitigation: runtime now logs drift warning if unified path implies a different pending folder.

## Phase-1 cleanup implemented

- Added explicit source/fallback warnings for replay HTTP host/port env fallback in worker startup and standalone server mode.
- Added replay config env-fallback warning in worker settings loader for:
  - `REPLAY_TRIGGER_HTTP_HOST`
  - `REPLAY_TRIGGER_HTTP_PORT`
  - `INSTANT_REPLAY_TRIGGER_FILE`
- Added scoreboard OBS websocket env-source warning for:
  - `OBS_WEBSOCKET_HOST`
  - `OBS_WEBSOCKET_PORT`
  - `OBS_WEBSOCKET_PASSWORD`
- Added canonical script startup config-source logging with precedence:
  - `param > env > default`
  - warns when replay HTTP values come from env fallback
  - warns when canonical token is missing
- Added scoreboard runtime drift warning for `scoreboard.commandsRoot` vs hardcoded command pending path.

## Remaining drift risks

- Canonical script replay HTTP host/port/timeout are still not loaded from unified config directly.
- Scoreboard command bus runtime path is still hardcoded despite unified `scoreboard.commandsRoot`.
- Scoreboard OBS websocket host/port are still env/default based (not unified).
- `REPLAY_TRIGGER_HTTP_TIMEOUT_SEC` has no unified equivalent yet.

## Recommended follow-up cleanup order

1. Add unified field for replay trigger timeout and migrate script to unified-first resolution.
2. Move scoreboard command bus directories to unified-derived runtime paths (with fallback compatibility).
3. Add unified scoreboard OBS websocket host/port fields (keep password in env only).
4. Consolidate canonical replay script resolution through shared config loader module for PowerShell scripts.
5. Add optional enforcement flag to reject non-trusted canonical claims once observability is stable.
