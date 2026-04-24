# Unified Config Migration Ledger (Phase 4)

Resolution order for migrated settings:

1. Unified config (`config/settings.json`)
2. Legacy env / app-specific config
3. Existing hardcoded default

## Worker (proposed then wired in this phase)

| Legacy input | Unified field | Status | Fallback behavior | Restart |
|---|---|---|---|---|
| `WATCH_FOLDER` | `worker.watchFolder` | migrated | env then default | yes |
| `PREVIEW_FOLDER` | `worker.previewFolder` | migrated | env then default | yes |
| `PROCESSED_FOLDER` | `worker.processedFolder` | migrated | env then default | yes |
| `FAILED_FOLDER` | `worker.failedFolder` | migrated | env then default | yes |
| `WORKER_CONCURRENCY` | `worker.workerConcurrency` | migrated | env then default | yes |
| `PREVIEW_WIDTH` | `worker.previewWidth` | migrated | env then default | yes |
| `UPLOAD_RETRIES` | `worker.uploadRetries` | migrated | env then default | yes |
| `UPLOAD_RETRY_DELAY_SECONDS` | `worker.uploadRetryDelaySeconds` | migrated | env then default | yes |
| `INSTANT_REPLAY_SOURCE` | `worker.instantReplaySource` | migrated | env then root default | yes |
| `LONG_CLIPS_FOLDER` | `worker.longClipsFolder` | migrated | env then root default | yes |
| `LONG_CLIPS_SCAN_INTERVAL_SECONDS` | `worker.longClipsScanIntervalSeconds` | migrated | env then default | yes |
| `INSTANT_REPLAY_TRIGGER_FILE` | `worker.instantReplayTriggerFile` | migrated | env then disabled | yes |
| `INSTANT_REPLAY_TRIGGER_SETTLE_SECONDS` | `worker.instantReplayTriggerSettleSeconds` | migrated | env then default | yes |
| `WORKER_STATUS_JSON_PATH` | `worker.workerStatusJsonPath` | migrated | env then root default | yes |
| `WORKER_STATUS_WRITE_INTERVAL_SECONDS` | `worker.workerStatusWriteIntervalSeconds` | migrated | env then default | yes |
| `SUPABASE_BOOKINGS_TABLE` | `storage.supabaseBookingsTable` | migrated | env then default | yes |
| `REPLAY_TRIGGER_HTTP_HOST` | `worker.httpReplayTriggerHost` | migrated | env then default | yes |
| `REPLAY_TRIGGER_HTTP_PORT` | `worker.httpReplayTriggerPort` + `worker.httpReplayTriggerEnabled` | migrated | env then disabled | yes |
| `ENABLE_INSTANT_REPLAY_BACKGROUND_INGEST` | `worker.enableInstantReplayBackgroundIngest` | migrated | env then default | yes |
| `ENABLE_REPLAY_SCOREBOARD_AUTO_SYNC` | `worker.enableReplayScoreboardAutoSync` | migrated | env then default | yes |
| `REPLAY_SCOREBOARD_AUTO_SYNC_INTERVAL_SECONDS` | `worker.replayScoreboardAutoSyncIntervalSeconds` | migrated | env then default | yes |
| `REPLAY_BUFFER_*` stability/remux flags | `worker.replayBuffer*` fields | migrated | env then default | yes |

## Scoreboard (proposed then wired in this phase)

| Legacy input | Unified field | Status | Fallback behavior | Restart |
|---|---|---|---|---|
| `STATE_FILE` | `scoreboard.stateFile` | migrated | env then default | yes |
| `SCOREBOARD_BACKGROUND_IMAGE` | `scoreboard.scoreboardBackgroundImage` | migrated | env then default | yes |
| `REPLAY_SLATE_IMAGE` | `scoreboard.replaySlateImage` | migrated | env then default | yes |
| `SLIDESHOW_DIR` | `scoreboard.slideshowDir` | migrated | env then default | yes |
| `REPLAY_VIDEO_PATH` | `scoreboard.replayVideoPath` | migrated | env then default | yes |
| `REPLAY_UNAVAILABLE_IMAGE` | `scoreboard.replayUnavailableImage` | migrated | env then default | yes |
| `MPV_PATH` | `obsFfmpegPaths.mpvPath` | migrated | env then default | yes |
| `MPV_EMBEDDED` | `scoreboard.mpvEmbedded` | migrated | env then default | yes |
| `MPV_EXIT_HOTKEY` | `scoreboard.mpvExitHotkey` | migrated | env then default | yes |
| `MPV_FULLSCREEN_ENABLED` | `scoreboard.mpvFullscreenEnabled` | migrated | env then default | yes |
| `MPV_LOOP_ENABLED` | `scoreboard.mpvLoopEnabled` | migrated | env then default | yes |
| `REPLAY_ENABLED` | `scoreboard.replayEnabled` | migrated | env then default | yes |
| `SLIDESHOW_ENABLED` | `scoreboard.slideshowEnabled` | migrated | env then default | yes |
| `REPLAY_TRANSITION_TIMEOUT_MS` | `scoreboard.replayTransitionTimeoutMs` | migrated | env then default | yes |
| `REPLAY_SLATE_STUCK_TIMEOUT_MS` | `scoreboard.replaySlateStuckTimeoutMs` | migrated | env then default | yes |
| `REPLAY_FILE_MAX_AGE_SECONDS` | `scoreboard.replayFileMaxAgeSeconds` | migrated | env then default | yes |
| `REPLAY_BUFFER_LOADING_*` | `scoreboard.replayBufferLoading*` fields | migrated | env then default | yes |
| `ENCODER_STATUS_*` | `scoreboard.encoderStatus*` fields | migrated | env then default | yes |
| `SCOREBOARD_LAUNCHER_STATUS_*` | `scoreboard.launcherStatus*` fields | migrated | env then default | yes |
| `OBS_STATUS_*` | `scoreboard.obsStatus*` fields | migrated | env then default | yes |

## Launcher (proposed then wired in this phase)

| Legacy input | Unified field | Status | Fallback behavior | Restart |
|---|---|---|---|---|
| `REPLAYTROVE_*_DIR` / defaults | `launcher.*Dir` fields + `general.replayTroveRoot` | migrated | env then root default | yes |
| `REPLAYTROVE_ENABLE_WORKER` | `launcher.enableWorker` | migrated | env then default | yes |
| `REPLAYTROVE_ENABLE_ENCODER` | `launcher.enableEncoder` | migrated | env then default | yes |
| `REPLAYTROVE_ENABLE_CLEANER` | `launcher.enableCleaner` | migrated | env then default | yes |
| `REPLAYTROVE_ENABLE_OBS` | `launcher.enableObs` | migrated | env then default | yes |
| `REPLAYTROVE_ENABLE_CONTROL_APP` | `launcher.enableControlApp` | migrated | env then default | yes |
| `REPLAYTROVE_ENABLE_SCOREBOARD` | `launcher.enableScoreboard` | migrated | env then default | yes |
| `REPLAYTROVE_ENABLE_LAUNCHER_UI` | `launcher.enableLauncherUi` | migrated | env then default | yes |
| `REPLAYTROVE_CONTROL_APP_*` | `launcher.controlApp*` fields | migrated | env then default | yes |
| `REPLAYTROVE_READINESS_*` | `launcher.readiness*` fields | migrated | env then default | yes |
| `REPLAYTROVE_FOCUS_*` | `launcher.focus*` fields | migrated | env then default | yes |
| `REPLAYTROVE_SCOREBOARD_STATUS_*` | `launcher.scoreboardStatus*` fields | migrated | env then default | yes |
| `REPLAYTROVE_SCOREBOARD_FOCUS_RECOVERY` | `launcher.scoreboardFocusRecovery` | migrated | env then default | yes |
| `REPLAYTROVE_SCOREBOARD_STATUS_WATCH` | `launcher.scoreboardStatusWatch` | migrated | env then default | yes |
| `REPLAYTROVE_PAUSE_ON_ERROR` | `launcher.pauseOnError` | migrated | env then default | yes |
| `REPLAYTROVE_LAUNCHER_DEBUG` | `launcher.debugMode` | migrated | env then default | yes |

## Intentionally Legacy-Only (for now)

- Secrets and credentials (`AWS_*`, `SUPABASE_KEY`, `OBS_WEBSOCKET_PASSWORD`, API keys).
- Ephemeral runtime state (`state.json`, command queues, status outputs, lock files).
- Debug-only or deep-tuning knobs with high blast radius that are not operator-facing.

## Phase 4.5 UI/Safety Metadata (Form-Surfaced)

| Unified field | restartRequired | dangerous | advanced | hotReloadCandidate | UI surface |
|---|---:|---:|---:|---:|---|
| `worker.httpReplayTriggerHost` | yes | no | no | no | form |
| `worker.watchFolder` | yes | yes (runtime) | no | no | form |
| `worker.instantReplaySource` | yes | yes (runtime) | no | no | form |
| `worker.longClipsFolder` | yes | yes (runtime) | no | no | form |
| `worker.workerStatusJsonPath` | yes | no | yes | yes | form |
| `worker.workerConcurrency` | yes | no | yes | no | form |
| `worker.uploadRetries` | yes | no | yes | yes | form |
| `worker.uploadRetryDelaySeconds` | yes | no | yes | yes | form |
| `worker.replayScoreboardAutoSyncIntervalSeconds` | yes | no | yes | yes | form |
| `worker.httpReplayTriggerEnabled` | yes | yes (runtime) | no | no | form |
| `worker.httpReplayTriggerPort` | yes | yes (conflict) | no | no | form |
| `worker.enableInstantReplayBackgroundIngest` | yes | yes (runtime) | no | no | form |
| `worker.enableReplayScoreboardAutoSync` | yes | no | yes | no | form |
| `worker.replayBufferDeleteSourceAfterSuccess` | yes | yes (runtime) | yes | no | form |
| `scoreboard.stateFile` | yes | yes (runtime) | no | no | form |
| `scoreboard.slideshowDir` | yes | no | no | no | form |
| `scoreboard.replayUnavailableImage` | yes | no | no | no | form |
| `scoreboard.replayBufferLoadingDir` | yes | no | yes | no | form |
| `scoreboard.launcherStatusJsonPath` | yes | no | yes | yes | form |
| `scoreboard.replayFileMaxAgeSeconds` | yes | no | yes | yes | form |
| `scoreboard.replayTransitionTimeoutMs` | yes | no | yes | yes | form |
| `scoreboard.replayEnabled` | yes | yes (runtime) | no | no | form |
| `scoreboard.slideshowEnabled` | yes | no | no | no | form |
| `scoreboard.mpvEmbedded` | yes | no | yes | no | form |
| `scoreboard.obsStatusIndicatorEnabled` | yes | no | no | yes | form |
| `scoreboard.encoderStatusEnabled` | yes | no | no | yes | form |
| `scoreboard.replayVideoPath` | yes | yes (runtime) | no | no | form |
| `launcher.obsDir` | yes | yes (startup) | yes | no | form |
| `launcher.enableWorker` | yes | yes (startup) | no | no | form |
| `launcher.enableScoreboard` | yes | yes (startup) | no | no | form |
| `launcher.enableObs` | yes | yes (startup) | no | no | form |
| `launcher.enableControlApp` | yes | yes (startup) | no | no | form |
| `launcher.workerDir` | yes | yes (startup) | no | no | form |
| `launcher.scoreboardDir` | yes | yes (startup) | no | no | form |
| `launcher.encoderDir` | yes | yes (startup) | yes | no | form |
| `launcher.controlAppExe` | yes | yes (startup) | no | no | form |
| `launcher.controlAppProcessName` | yes | no | yes | no | form |
| `launcher.readinessObsSec` | yes | no | yes | yes | form |
| `launcher.readinessPythonSec` | yes | no | yes | yes | form |
| `launcher.focusRetryMs` | yes | no | yes | yes | form |
| `launcher.scoreboardStatusPollSec` | yes | no | yes | yes | form |
| `launcher.scoreboardStatusWatch` | yes | no | yes | no | form |
| `launcher.pauseOnError` | yes | no | yes | no | form |
| `launcher.debugMode` | yes | no | yes | no | form |
| `obsFfmpegPaths.obsExecutable` | yes | yes (startup) | no | no | JSON-only |
| `obsFfmpegPaths.ffmpegPath` | yes | yes (runtime) | no | no | JSON-only |
| `obsFfmpegPaths.mpvPath` | yes | yes (startup) | no | no | JSON-only |
| `webApp.port` | yes | yes (conflict) | yes | no | JSON-only |

## Phase 5 Implemented (Scoreboard Safe Live Reload)

- Implemented command: `reload_scoreboard_safe_settings`
- Implemented live-reload allowlist (only):
  - `scoreboard.obsStatusPollIntervalMs`
  - `scoreboard.encoderStatusPollMs`
- Reload remains explicit-action-only (no auto-apply on save).
- Runtime apply is all-or-nothing with fallback preservation.
- Last outcome artifact path:
  - `C:\ReplayTrove\scoreboard\reload_safe_settings_status.json`
