# ReplayTrove Config Authority Audit (Phase 1)

> **Operator note:** This document started as a Phase 1 drift audit. Runtime behavior has since converged on **unified `config/settings.json` first**, with environment overrides and compatibility bridges where noted. Use the **Current authority (operator summary)** section below as the practical source of truth; later sections retain audit history and residual-risk notes.

## Current authority (operator summary)

- **Unified config:** `config/settings.json` drives worker replay HTTP (`worker.httpReplayTriggerHost`, `worker.httpReplayTriggerPort`, `worker.httpReplayTriggerTimeoutSec`), replay paths, scoreboard OBS (`scoreboard.obsWebsocketHost` / `Port` / `Password`), command bus root (`scoreboard.commandsRoot`), and related launcher fields. Control Center edits the same document.
- **Env overrides:** Many keys still map to env vars (e.g. `REPLAY_TRIGGER_HTTP_*`, `OBS_WEBSOCKET_*`) for deployment flexibility; loaders log when values come from env vs unified.
- **Secrets:** `REPLAY_CANONICAL_TOKEN` remains env-only for the canonical replay script and worker trust checks. OBS websocket password may live in unified JSON on appliance installs—**protect file permissions** on `config/settings.json` (and any secrets sidecar) like any file that can start encoders or touch production paths.
- **Canonical replay script** (`scripts/save_replay_and_trigger.ps1`): resolves replay HTTP host/port/timeout and OBS targets **unified-first** with param/env fallbacks; startup logs show precedence.
- **Scoreboard command bus:** Pending/processed paths derive from unified `scoreboard.commandsRoot`. If the legacy default tree differs, the runtime **still scans the legacy pending folder** as a compatibility bridge (not removed here).
- **Stream Deck / shortcuts:** Any hardcoded replay HTTP port must match `worker.httpReplayTriggerPort` (default **18765**). See `worker/streamdeck_trigger_replay.bat`.

---

## Precedence model (historical — still broadly true)

- Worker runtime settings: `config/settings.json` (unified) → env var → code default
- Scoreboard migrated settings: same pattern
- Canonical replay script: unified-first, then param → env → script default
- Token: `REPLAY_CANONICAL_TOKEN` env only

## Authority map (historical detail)

- `worker.httpReplayTriggerHost` / `REPLAY_TRIGGER_HTTP_HOST` — unified in worker; script unified-first.
- `worker.httpReplayTriggerPort` / `REPLAY_TRIGGER_HTTP_PORT` — unified in worker; script unified-first.
- `worker.httpReplayTriggerTimeoutSec` / `REPLAY_TRIGGER_HTTP_TIMEOUT_SEC` — unified field exists; script unified-first (verify logs if you rely on env-only overrides).
- `REPLAY_CANONICAL_TOKEN` — env only; empty allowed with explicit “untrusted” logging path.
- `scoreboard.obsWebsocket*` / `OBS_WEBSOCKET_*` — scoreboard loads unified first; env overrides logged.
- Replay-related paths — unified first in adapters; env/default fallback retained.
- Scoreboard command bus — `scoreboard.commandsRoot` is authoritative for primary pending/processed; legacy pending scan remains when paths diverge.

## Phase-1 cleanup implemented (audit log)

- Source/fallback warnings for replay HTTP host/port in worker startup and standalone server mode.
- Replay config env-fallback warnings in worker settings loader (`REPLAY_TRIGGER_HTTP_*`, `INSTANT_REPLAY_TRIGGER_FILE`).
- Scoreboard OBS websocket env-source warnings.
- Canonical script startup config-source logging (`param > env > default`), replay HTTP env warnings, missing-token warnings.
- Scoreboard drift warning when unified `scoreboard.commandsRoot` implies a different tree than legacy constants (bridge still active).

## Residual drift / confusion risks

- **Legacy entrypoints** (e.g. VBS, `toggle_replay`, direct worker HTTP) can bypass the full canonical script path—operators should prefer `save_replay_and_trigger.ps1` or documented wrappers for consistent OBS/scoreboard behavior.
- **Two pending folders** may be scanned if unified root ≠ legacy layout—intentional bridge; watch logs for `command_bus_legacy_bridge`.
- **Protect unified JSON** if it contains OBS password or other sensitive operator data.

## Recommended follow-up cleanup order

1. Optional: tighten documentation for all Companion/Stream Deck actions to a single canonical trigger story (HTTP port + script), without removing legacy bridges yet.
2. When observability is stable, optional enforcement flag for non-trusted canonical claims.
3. Longer-term: reduce duplicate env surface where unified + env duplicate the same key without clear operator docs.
