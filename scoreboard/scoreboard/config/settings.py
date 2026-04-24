"""Application settings: load from environment (.env) with validation."""

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from scoreboard.config.unified_adapter import (
    ScoreboardUnifiedSnapshot,
    load_scoreboard_unified_snapshot,
)


_LOG = logging.getLogger(__name__)


def worker_http_health_endpoint(unified: ScoreboardUnifiedSnapshot) -> tuple[str, int | None]:
    """Host/port for worker ``GET /health`` (replay-trigger-http). ``port`` is None when HTTP trigger is off."""
    w = unified.worker
    host = "127.0.0.1"
    port: int | None = None
    if w:
        hc = w.get("httpReplayTriggerHost")
        if isinstance(hc, str) and hc.strip():
            host = hc.strip()
        en = w.get("httpReplayTriggerEnabled")
        pc = w.get("httpReplayTriggerPort")
        if en is False:
            port = None
        elif isinstance(pc, int) and not isinstance(pc, bool) and pc >= 1:
            port = pc
    eh = os.environ.get("REPLAY_TRIGGER_HTTP_HOST")
    if eh and str(eh).strip():
        host = str(eh).strip()
    ep = os.environ.get("REPLAY_TRIGGER_HTTP_PORT")
    if ep is not None and str(ep).strip() != "":
        try:
            pv = int(str(ep).strip())
            port = pv if pv >= 1 else None
        except ValueError:
            pass
    return host, port

# Defaults (formerly module-level constants in main.py)
DEFAULT_STATE_FILE = "state.json"
DEFAULT_ENV_FILE = ".env"
# Empty: use central JSONL only under REPLAYTROVE_LOGS_ROOT (see logging_config).
DEFAULT_SCOREBOARD_LOG_FILE = ""
DEFAULT_CENTRAL_LOGS_ROOT = r"C:\ReplayTrove\logs"
DEFAULT_SCOREBOARD_BG = "Score BG.png"
DEFAULT_REPLAY_SLATE = "ir slate.png"
DEFAULT_SLIDESHOW_DIR = r"C:\Users\admin\Dropbox\slideshow"
DEFAULT_REPLAY_VIDEO_PATH = r"C:\ReplayTrove\INSTANTREPLAY.mkv"
DEFAULT_REPLAY_UNAVAILABLE_IMAGE = "assets/replay_unavailable.png"
DEFAULT_REPLAY_BUFFER_LOADING_DIR = "assets/replay_buffer_loading"
DEFAULT_COMMANDS_ROOT = r"C:\ReplayTrove\commands"
DEFAULT_ENCODER_STATE_FILE = "encoder_state.json"
DEFAULT_ENCODER_READY_IMAGE = "assets/recorderstatus/ready.png"
DEFAULT_ENCODER_UNAVAILABLE_IMAGE = "assets/recorderstatus/unavailable.png"
DEFAULT_LAUNCHER_RESTART_OBS_SCRIPT = r"C:\ReplayTrove\launcher\restart_obs.ps1"
DEFAULT_LAUNCHER_STATUS_JSON_PATH = r"C:\ReplayTrove\launcher\scoreboard_status.json"

IDLE_TIMEOUT_MS = 30 * 60 * 1000
SLIDESHOW_INTERVAL_MS = 12 * 1000
SLIDESHOW_FADE_DURATION_MS = 1000
SLIDESHOW_FADE_STEPS = 10
SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")

# Hold IR slate on screen this long after fade-in before launching mpv (extra time for clip to finish writing).
# After slate is visible, wait this long before launching mpv (OBS/disk flush). Overridable
# via REPLAY_VIDEO_START_DELAY_MS; was 5000ms and made replay feel frozen with prep mpv_quit.
REPLAY_VIDEO_START_DELAY_MS = 1000
REPLAY_VIDEO_POLL_MS = 500
REPLAY_RETURN_SLATE_HOLD_MS = 350
# Command-bus folder poll (Stream Deck / send_command.ps1). Lower = snappier mpv controls; min 10 ms.
COMMAND_POLL_INTERVAL_MS_DEFAULT = 25
# If fade or handoff hangs, force recovery (ms)
REPLAY_TRANSITION_TIMEOUT_MS = 90_000
# After slate is shown, if video never becomes active this long after launch delay, recover (ms)
REPLAY_SLATE_STUCK_TIMEOUT_MS = 90_000
# Refuse mpv if INSTANTREPLAY file mtime is older than this (seconds). 0 = skip freshness check.
DEFAULT_REPLAY_FILE_MAX_AGE_SECONDS = 120
FOCUS_WATCHDOG_INTERVAL_MS = 3000
# ~12.5 minutes at default interval (250 * 3s); pilot can override via FOCUS_WATCHDOG_TICKS.
FOCUS_WATCHDOG_TICKS = 250

RECORDING_DEFAULT_DURATION_MINUTES = 20
RECORDING_COUNTDOWN_TICK_MS = 1000
RECORDING_BLINK_INTERVAL_MS = 500
RECORDING_OVERLAY_WIDTH = 440
RECORDING_OVERLAY_HEIGHT = 178
RECORDING_ENDED_MESSAGE = (
    "Your recording has reached its maximum length and ended"
)
RECORDING_ENDED_HOLD_MINUTES_DEFAULT = 2
RECORDING_SESSION_END_INFO_MS_DEFAULT = 5000
RECORDING_SESSION_END_MESSAGE = (
    "Recording ended. You will receive an email after your session ends "
    "with the link to download your video."
)
# Optional PNGs: in-progress (on/off for red-dot blink), ended slate with timer overlaid.
RECORDING_ENDED_GRAPHIC_HOLD_MS_DEFAULT = 10_000
RECORDING_OVERLAY_TIMER_X_FRAC_DEFAULT = 0.28
RECORDING_OVERLAY_TIMER_Y_FRAC_DEFAULT = 0.36
RECORDING_OVERLAY_TIMER_FONT_SIZE_DEFAULT = 22


def _env_truthy(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _parse_positive_int(raw: str | None, default: int, name: str, minimum: int = 1) -> int:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        n = int(float(str(raw).strip()))
        if n < minimum:
            _LOG.warning(
                "%s=%r below minimum %s; using default %s",
                name,
                raw,
                minimum,
                default,
            )
            return default
        return n
    except (TypeError, ValueError):
        _LOG.warning("%s=%r invalid; using default %s", name, raw, default)
        return default


def _parse_int_env(raw: str | None, default: int, name: str) -> int:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        _LOG.warning("%s=%r invalid; using default %s", name, raw, default)
        return default


def _parse_float_env(raw: str | None, default: float, name: str) -> float:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = float(str(raw).strip())
        if v < 0.25:
            _LOG.warning("%s=%r too low; using 0.25", name, raw)
            return 0.25
        if v > 30.0:
            _LOG.warning("%s=%r too high; using 30.0", name, raw)
            return 30.0
        return v
    except (TypeError, ValueError):
        _LOG.warning("%s=%r invalid; using default %s", name, raw, default)
        return default


def _normalize_path(p: str | None) -> str:
    if p is None:
        return ""
    return str(p).strip().strip('"').strip("'")


def _parse_mpv_additional_args(raw: str | None) -> tuple[str, ...]:
    """Split MPV_ADDITIONAL_ARGS with shlex (quoted tokens allowed)."""
    if raw is None or not str(raw).strip():
        return ()
    try:
        parts = shlex.split(str(raw).strip(), posix=os.name != "nt")
    except ValueError as e:
        _LOG.warning("MPV_ADDITIONAL_ARGS shlex split failed: %s", e)
        return ()
    return tuple(p for p in parts if p)


@dataclass(frozen=True)
class Settings:
    """Validated configuration loaded once at startup."""

    # Paths
    state_file: str
    scoreboard_background_image: str
    replay_slate_image: str
    slideshow_dir: str
    replay_video_path: str
    replay_unavailable_image: str
    commands_root: str
    mpv_path: str | None

    # mpv / replay
    mpv_exit_hotkey: str
    mpv_embedded: bool

    # Windows focus
    synthetic_focus_click: bool

    # Recording overlay
    recording_max_minutes: int
    recording_duration_sec: int
    recording_ended_hold_ms: int
    replay_buffer_loading_dir: str
    replay_buffer_loading_frame_ms: int
    replay_buffer_loading_margin_px: int

    encoder_status_enabled: bool
    encoder_state_path: str
    encoder_status_ready_image: str
    encoder_status_unavailable_image: str
    encoder_status_poll_ms: int
    encoder_status_stale_seconds: int
    encoder_status_margin_px: int

    # Recording overlay driven by encoder_state.json (long recording signals).
    recording_encoder_sync_enabled: bool
    recording_encoder_poll_ms: int

    # Timing (fixed product defaults; not from .env unless we add later)
    idle_timeout_ms: int = IDLE_TIMEOUT_MS
    slideshow_interval_ms: int = SLIDESHOW_INTERVAL_MS
    slideshow_fade_duration_ms: int = SLIDESHOW_FADE_DURATION_MS
    slideshow_fade_steps: int = SLIDESHOW_FADE_STEPS
    replay_video_start_delay_ms: int = REPLAY_VIDEO_START_DELAY_MS
    replay_video_poll_ms: int = REPLAY_VIDEO_POLL_MS
    replay_return_slate_hold_ms: int = REPLAY_RETURN_SLATE_HOLD_MS
    focus_watchdog_interval_ms: int = FOCUS_WATCHDOG_INTERVAL_MS
    focus_watchdog_ticks: int = FOCUS_WATCHDOG_TICKS
    recording_countdown_tick_ms: int = RECORDING_COUNTDOWN_TICK_MS
    recording_blink_interval_ms: int = RECORDING_BLINK_INTERVAL_MS
    recording_overlay_width: int = RECORDING_OVERLAY_WIDTH
    recording_overlay_height: int = RECORDING_OVERLAY_HEIGHT
    recording_ended_message: str = RECORDING_ENDED_MESSAGE
    recording_session_end_info_ms: int = RECORDING_SESSION_END_INFO_MS_DEFAULT
    recording_session_end_message: str = RECORDING_SESSION_END_MESSAGE
    recording_progress_image_on: str = ""
    recording_progress_image_off: str = ""
    recording_ended_image: str = ""
    recording_ended_graphic_hold_ms: int = RECORDING_ENDED_GRAPHIC_HOLD_MS_DEFAULT
    recording_overlay_timer_x_frac: float = RECORDING_OVERLAY_TIMER_X_FRAC_DEFAULT
    recording_overlay_timer_y_frac: float = RECORDING_OVERLAY_TIMER_Y_FRAC_DEFAULT
    recording_overlay_timer_font_size: int = RECORDING_OVERLAY_TIMER_FONT_SIZE_DEFAULT
    recording_overlay_timer_offset_x_px: int = 0
    recording_overlay_timer_offset_y_px: int = 0

    # Pilot / reliability
    replay_enabled: bool = True
    slideshow_enabled: bool = True
    scoreboard_debug: bool = False
    scoreboard_log_file: str = DEFAULT_SCOREBOARD_LOG_FILE
    central_logs_root: str = DEFAULT_CENTRAL_LOGS_ROOT
    heartbeat_interval_minutes: int = 0
    replay_transition_timeout_ms: int = REPLAY_TRANSITION_TIMEOUT_MS
    replay_slate_stuck_timeout_ms: int = REPLAY_SLATE_STUCK_TIMEOUT_MS
    replay_file_max_age_seconds: int = DEFAULT_REPLAY_FILE_MAX_AGE_SECONDS
    # When instant replay file check fails, OBS WebSocket BroadcastCustomEvent (opt-in).
    replay_obs_broadcast_on_unavailable: bool = False
    # When instant replay file check fails, run launcher restart_obs.ps1 (Windows; opt-in).
    replay_launcher_restart_obs_on_unavailable: bool = False
    replay_launcher_restart_obs_script: str = DEFAULT_LAUNCHER_RESTART_OBS_SCRIPT

    # OBS WebSocket (optional gate before recording overlay — RECORDING_OBS_HEALTH_CHECK).
    recording_obs_health_check: bool = False
    obs_websocket_host: str = "localhost"
    obs_websocket_port: int = 4455
    obs_websocket_password: str = ""
    obs_websocket_timeout_sec: float = 2.0
    recording_obs_block_if_main_recording: bool = False
    # If True, do not start timer when OBS gate check fails.
    # If False (default), log warning but still start timer (fail-open).
    recording_obs_health_fail_closed: bool = False

    # OBS restart chord (Q+R+P): Windows only; see scoreboard.obs_restart.
    obs_restart_chord_enabled: bool = False
    obs_executable: str = ""
    # Startup args for OBS process when restart chord relaunches it.
    # `--disable-shutdown-check` bypasses safe mode prompt after unclean exits.
    obs_restart_launch_args: str = (
        "--disable-shutdown-check --disable-missing-files-check --startreplaybuffer"
    )
    obs_restart_start_replay_buffer: bool = True
    obs_restart_post_launch_delay_ms: int = 4500

    # Bottom-left OBS status strip (WebSocket probe; independent of RECORDING_OBS_HEALTH_CHECK).
    obs_status_indicator_enabled: bool = True
    obs_status_poll_interval_ms: int = 4000
    # If True, status shows unavailable while main output recording is active.
    # Default False so "OBS is up" reads as READY for operators.
    obs_status_require_main_output_idle: bool = False

    # mpv instant-replay subprocess (MPV_* env vars)
    mpv_hwdec_enabled: bool = False
    mpv_hwdec_mode: str = "auto"
    mpv_fullscreen_enabled: bool = True
    mpv_keep_open_enabled: bool = True
    mpv_loop_enabled: bool = True
    mpv_video_sync_mode: str = "display-resample"
    mpv_framedrop_mode: str = "vo"
    mpv_interpolation_enabled: bool = False
    mpv_force_window_enabled: bool = True
    mpv_additional_args: tuple[str, ...] = ()
    mpv_process_priority: str = "normal"
    # Reduce contention with OBS (encoding / GPU composite / fullscreen flip chain).
    mpv_obs_friendly: bool = True
    mpv_borderless_fullscreen: bool = True
    mpv_obs_lower_process_priority: bool = True
    mpv_obs_force_software_decode: bool = False
    # When mpv_obs_friendly: fast | balanced | hq (scaling / mpv builtin profiles).
    mpv_replay_quality: str = "fast"

    # JSON for external launcher (screensaver_active, scoreboard_running).
    launcher_status_enabled: bool = True
    launcher_status_json_path: str = DEFAULT_LAUNCHER_STATUS_JSON_PATH
    # Optional Companion page switching webhooks fired by scoreboard replay state transitions.
    companion_page_switch_enabled: bool = False
    companion_replay_active_page_url: str = ""
    companion_replay_locked_page_url: str = ""
    companion_replay_idle_page_url: str = ""
    # When false, Companion idle/locked readiness ignores OBS WebSocket (mpv + replay file + worker health still apply).
    companion_readiness_require_obs_websocket: bool = True
    # How often the scoreboard scans ``commands/.../pending`` (see SCOREBOARD_COMMAND_POLL_MS).
    command_poll_interval_ms: int = COMMAND_POLL_INTERVAL_MS_DEFAULT
    # Instant-replay readiness: optional GET http://host:port/health (worker replay-trigger-http).
    worker_http_health_host: str = "127.0.0.1"
    worker_http_health_port: int | None = None


def load_settings(env_file: str = DEFAULT_ENV_FILE) -> Settings:
    """Load .env into os.environ, then build and validate Settings."""
    env_path = Path(env_file)
    if env_path.is_file():
        load_dotenv(env_path, override=False)
        _LOG.info("Loaded environment from %s", env_path.resolve())
    else:
        _LOG.info("No %s file; using process environment and defaults", env_file)

    unified = load_scoreboard_unified_snapshot()
    worker_http_health_host, worker_http_health_port = worker_http_health_endpoint(unified)
    _LOG.info(
        "scoreboard unified config: found=%s path=%s schema_version=%s migrated=%s scoreboard_section=%s obsffmpeg_section=%s worker_section=%s worker_http_health=%s:%s",
        unified.found,
        str(unified.path),
        unified.schema_version,
        unified.migrated,
        unified.scoreboard_section_loaded,
        unified.obsffmpeg_section_loaded,
        unified.worker_section_loaded,
        worker_http_health_host,
        worker_http_health_port if worker_http_health_port is not None else "off",
    )
    if unified.error:
        _LOG.warning("scoreboard unified config parse failed: %s", unified.error)

    unified_overrides: dict[str, str] = {}
    source_notes: list[str] = []
    def _set_u_str(env_key: str, value: object) -> None:
        if isinstance(value, str):
            _v = value.strip()
            if _v:
                unified_overrides[env_key] = _v

    def _set_u_bool(env_key: str, value: object) -> None:
        if isinstance(value, bool):
            unified_overrides[env_key] = "1" if value else "0"

    def _set_u_int(env_key: str, value: object) -> None:
        if isinstance(value, int) and not isinstance(value, bool):
            unified_overrides[env_key] = str(value)

    _set_u_str("STATE_FILE", unified.scoreboard.get("stateFile"))
    _set_u_str("COMMANDS_ROOT", unified.scoreboard.get("commandsRoot"))
    _set_u_str(
        "SCOREBOARD_BACKGROUND_IMAGE", unified.scoreboard.get("scoreboardBackgroundImage")
    )
    _set_u_str("REPLAY_SLATE_IMAGE", unified.scoreboard.get("replaySlateImage"))
    _set_u_str("SLIDESHOW_DIR", unified.scoreboard.get("slideshowDir"))
    _set_u_str("REPLAY_VIDEO_PATH", unified.scoreboard.get("replayVideoPath"))
    _set_u_str(
        "REPLAY_UNAVAILABLE_IMAGE", unified.scoreboard.get("replayUnavailableImage")
    )
    _set_u_bool("REPLAY_ENABLED", unified.scoreboard.get("replayEnabled"))
    _set_u_bool("SLIDESHOW_ENABLED", unified.scoreboard.get("slideshowEnabled"))
    _set_u_str("MPV_EXIT_HOTKEY", unified.scoreboard.get("mpvExitHotkey"))
    _set_u_bool("MPV_EMBEDDED", unified.scoreboard.get("mpvEmbedded"))
    _set_u_bool("MPV_FULLSCREEN_ENABLED", unified.scoreboard.get("mpvFullscreenEnabled"))
    _set_u_bool("MPV_LOOP_ENABLED", unified.scoreboard.get("mpvLoopEnabled"))
    _set_u_int(
        "REPLAY_TRANSITION_TIMEOUT_MS",
        unified.scoreboard.get("replayTransitionTimeoutMs"),
    )
    _set_u_int(
        "REPLAY_SLATE_STUCK_TIMEOUT_MS", unified.scoreboard.get("replaySlateStuckTimeoutMs")
    )
    _set_u_int(
        "REPLAY_FILE_MAX_AGE_SECONDS", unified.scoreboard.get("replayFileMaxAgeSeconds")
    )
    _set_u_int(
        "REPLAY_VIDEO_START_DELAY_MS", unified.scoreboard.get("replayVideoStartDelayMs")
    )
    _set_u_int(
        "SCOREBOARD_COMMAND_POLL_MS", unified.scoreboard.get("commandPollIntervalMs")
    )
    _set_u_str(
        "REPLAY_BUFFER_LOADING_DIR", unified.scoreboard.get("replayBufferLoadingDir")
    )
    _set_u_int(
        "REPLAY_BUFFER_LOADING_FRAME_MS",
        unified.scoreboard.get("replayBufferLoadingFrameMs"),
    )
    _set_u_int(
        "REPLAY_BUFFER_LOADING_MARGIN_PX",
        unified.scoreboard.get("replayBufferLoadingMarginPx"),
    )
    _set_u_bool("ENCODER_STATUS_ENABLED", unified.scoreboard.get("encoderStatusEnabled"))
    _set_u_str("ENCODER_STATE_PATH", unified.scoreboard.get("encoderStatePath"))
    _set_u_int("ENCODER_STATUS_POLL_MS", unified.scoreboard.get("encoderStatusPollMs"))
    _set_u_int(
        "ENCODER_STATUS_STALE_SECONDS", unified.scoreboard.get("encoderStatusStaleSeconds")
    )
    _set_u_int("ENCODER_STATUS_MARGIN_PX", unified.scoreboard.get("encoderStatusMarginPx"))
    _set_u_bool(
        "SCOREBOARD_LAUNCHER_STATUS_ENABLED", unified.scoreboard.get("launcherStatusEnabled")
    )
    _set_u_str(
        "SCOREBOARD_LAUNCHER_STATUS_PATH",
        unified.scoreboard.get("launcherStatusJsonPath"),
    )
    _set_u_str("OBS_WEBSOCKET_HOST", unified.scoreboard.get("obsWebsocketHost"))
    _set_u_int("OBS_WEBSOCKET_PORT", unified.scoreboard.get("obsWebsocketPort"))
    _set_u_str("OBS_WEBSOCKET_PASSWORD", unified.scoreboard.get("obsWebsocketPassword"))
    _set_u_bool(
        "OBS_STATUS_INDICATOR_ENABLED", unified.scoreboard.get("obsStatusIndicatorEnabled")
    )
    _set_u_int(
        "OBS_STATUS_POLL_INTERVAL_MS", unified.scoreboard.get("obsStatusPollIntervalMs")
    )
    _set_u_bool(
        "OBS_STATUS_REQUIRE_MAIN_OUTPUT_IDLE",
        unified.scoreboard.get("obsStatusRequireMainOutputIdle"),
    )
    _set_u_bool(
        "COMPANION_PAGE_SWITCH_ENABLED",
        unified.scoreboard.get("companionPageSwitchEnabled"),
    )
    _set_u_str(
        "COMPANION_REPLAY_ACTIVE_PAGE_URL",
        unified.scoreboard.get("companionReplayActivePageUrl"),
    )
    _set_u_str(
        "COMPANION_REPLAY_LOCKED_PAGE_URL",
        unified.scoreboard.get("companionReplayLockedPageUrl"),
    )
    _set_u_str(
        "COMPANION_REPLAY_IDLE_PAGE_URL",
        unified.scoreboard.get("companionReplayIdlePageUrl"),
    )
    _set_u_bool(
        "COMPANION_READINESS_REQUIRE_OBS_WEBSOCKET",
        unified.scoreboard.get("companionReadinessRequireObsWebsocket"),
    )
    _set_u_str("MPV_PATH", unified.obsffmpeg.get("mpvPath"))

    def g(key: str, default: str | None = None) -> str | None:
        if key in unified_overrides:
            source_notes.append(f"{key}=unified")
            return unified_overrides[key]
        v = os.environ.get(key)
        if v is None or str(v).strip() == "":
            source_notes.append(f"{key}=default")
            return default
        source_notes.append(f"{key}=env")
        return str(v).strip()

    slideshow_dir = _normalize_path(
        g("SLIDESHOW_DIR", DEFAULT_SLIDESHOW_DIR) or DEFAULT_SLIDESHOW_DIR
    )
    replay_video_path = _normalize_path(
        g("REPLAY_VIDEO_PATH", DEFAULT_REPLAY_VIDEO_PATH) or DEFAULT_REPLAY_VIDEO_PATH
    )
    replay_unavailable_image = _normalize_path(
        g("REPLAY_UNAVAILABLE_IMAGE", DEFAULT_REPLAY_UNAVAILABLE_IMAGE)
    ) or DEFAULT_REPLAY_UNAVAILABLE_IMAGE
    commands_root = _normalize_path(
        g("COMMANDS_ROOT", DEFAULT_COMMANDS_ROOT) or DEFAULT_COMMANDS_ROOT
    )
    commands_root = str(Path(commands_root))
    mpv_path_raw = _normalize_path(g("MPV_PATH"))
    mpv_path = mpv_path_raw if mpv_path_raw else None

    mpv_exit = (g("MPV_EXIT_HOTKEY", "Ctrl+Alt+q") or "Ctrl+Alt+q").strip()
    if not mpv_exit:
        mpv_exit = "Ctrl+Alt+q"

    mpv_embedded = _env_truthy(g("MPV_EMBEDDED"), False)

    mpv_hwdec_enabled = _env_truthy(g("MPV_HWDEC_ENABLED"), False)
    mpv_hwdec_mode = (g("MPV_HWDEC_MODE", "auto") or "auto").strip()
    mpv_fullscreen_enabled = _env_truthy(g("MPV_FULLSCREEN_ENABLED"), True)
    mpv_keep_open_enabled = _env_truthy(g("MPV_KEEP_OPEN_ENABLED"), True)
    mpv_loop_enabled = _env_truthy(g("MPV_LOOP_ENABLED"), True)
    # display-resample is gentler on vsync/display than desync when OBS is compositing capture.
    mpv_video_sync_mode = (g("MPV_VIDEO_SYNC_MODE", "display-resample") or "display-resample").strip()
    mpv_framedrop_mode = (g("MPV_FRAMEDROP_MODE", "vo") or "vo").strip()
    mpv_interpolation_enabled = _env_truthy(g("MPV_INTERPOLATION_ENABLED"), False)
    mpv_force_window_enabled = _env_truthy(g("MPV_FORCE_WINDOW_ENABLED"), True)
    mpv_additional_args = _parse_mpv_additional_args(g("MPV_ADDITIONAL_ARGS"))
    mpv_obs_friendly = _env_truthy(g("MPV_OBS_FRIENDLY"), True)
    mpv_borderless_fullscreen = _env_truthy(g("MPV_BORDERLESS_FULLSCREEN"), True)
    mpv_obs_lower_process_priority = _env_truthy(g("MPV_OBS_LOWER_PROCESS_PRIORITY"), True)
    mpv_obs_force_software_decode = _env_truthy(g("MPV_OBS_FORCE_SOFTWARE_DECODE"), False)
    _mpv_q = (g("MPV_REPLAY_QUALITY", "fast") or "fast").strip().lower()
    if _mpv_q not in ("fast", "balanced", "hq"):
        _LOG.warning(
            "MPV_REPLAY_QUALITY=%r invalid (use fast|balanced|hq); using fast",
            _mpv_q,
        )
        mpv_replay_quality = "fast"
    else:
        mpv_replay_quality = _mpv_q
    _mpv_prio = (g("MPV_PROCESS_PRIORITY", "normal") or "normal").strip().lower()
    if _mpv_prio not in ("normal", "low"):
        _LOG.warning("MPV_PROCESS_PRIORITY=%r invalid; using normal", _mpv_prio)
        mpv_process_priority = "normal"
    else:
        mpv_process_priority = _mpv_prio

    syn_default = True if os.name == "nt" else False
    synthetic_focus_click = _env_truthy(g("SYNTHETIC_FOCUS_CLICK"), syn_default)

    rec_minutes = _parse_positive_int(
        g("RECORDING_MAX_MINUTES", str(RECORDING_DEFAULT_DURATION_MINUTES)),
        RECORDING_DEFAULT_DURATION_MINUTES,
        "RECORDING_MAX_MINUTES",
        minimum=1,
    )
    recording_duration_sec = rec_minutes * 60

    ended_hold_min = _parse_positive_int(
        g("RECORDING_ENDED_HOLD_MINUTES", str(RECORDING_ENDED_HOLD_MINUTES_DEFAULT)),
        RECORDING_ENDED_HOLD_MINUTES_DEFAULT,
        "RECORDING_ENDED_HOLD_MINUTES",
        minimum=1,
    )
    recording_ended_hold_ms = ended_hold_min * 60 * 1000

    recording_session_end_info_ms = _parse_positive_int(
        g(
            "RECORDING_SESSION_END_INFO_MS",
            str(RECORDING_SESSION_END_INFO_MS_DEFAULT),
        ),
        RECORDING_SESSION_END_INFO_MS_DEFAULT,
        "RECORDING_SESSION_END_INFO_MS",
        minimum=1000,
    )
    recording_session_end_msg_raw = g("RECORDING_SESSION_END_MESSAGE")
    recording_session_end_message = (
        str(recording_session_end_msg_raw).strip()
        if recording_session_end_msg_raw
        else ""
    )
    if not recording_session_end_message:
        recording_session_end_message = RECORDING_SESSION_END_MESSAGE

    recording_progress_image_on = _normalize_path(g("RECORDING_PROGRESS_IMAGE_ON")) or ""
    recording_progress_image_off = _normalize_path(g("RECORDING_PROGRESS_IMAGE_OFF")) or ""
    recording_ended_image = _normalize_path(g("RECORDING_ENDED_IMAGE")) or ""

    recording_ended_graphic_hold_ms = _parse_positive_int(
        g(
            "RECORDING_ENDED_GRAPHIC_HOLD_MS",
            str(RECORDING_ENDED_GRAPHIC_HOLD_MS_DEFAULT),
        ),
        RECORDING_ENDED_GRAPHIC_HOLD_MS_DEFAULT,
        "RECORDING_ENDED_GRAPHIC_HOLD_MS",
        minimum=1000,
    )

    def _unit_float(raw: str | None, default: float, name: str) -> float:
        if raw is None or str(raw).strip() == "":
            return default
        try:
            v = float(str(raw).strip())
            return min(1.0, max(0.0, v))
        except (TypeError, ValueError):
            _LOG.warning("%s=%r invalid; using default %s", name, raw, default)
            return default

    recording_overlay_timer_x_frac = _unit_float(
        g("RECORDING_OVERLAY_TIMER_X_FRAC"),
        RECORDING_OVERLAY_TIMER_X_FRAC_DEFAULT,
        "RECORDING_OVERLAY_TIMER_X_FRAC",
    )
    recording_overlay_timer_y_frac = _unit_float(
        g("RECORDING_OVERLAY_TIMER_Y_FRAC"),
        RECORDING_OVERLAY_TIMER_Y_FRAC_DEFAULT,
        "RECORDING_OVERLAY_TIMER_Y_FRAC",
    )
    recording_overlay_timer_font_size = _parse_int_env(
        g(
            "RECORDING_OVERLAY_TIMER_FONT_SIZE",
            str(RECORDING_OVERLAY_TIMER_FONT_SIZE_DEFAULT),
        ),
        RECORDING_OVERLAY_TIMER_FONT_SIZE_DEFAULT,
        "RECORDING_OVERLAY_TIMER_FONT_SIZE",
    )
    if recording_overlay_timer_font_size == 0:
        _LOG.warning("RECORDING_OVERLAY_TIMER_FONT_SIZE=0 invalid; using %s", RECORDING_OVERLAY_TIMER_FONT_SIZE_DEFAULT)
        recording_overlay_timer_font_size = RECORDING_OVERLAY_TIMER_FONT_SIZE_DEFAULT
    elif recording_overlay_timer_font_size > 0:
        if recording_overlay_timer_font_size < 8:
            recording_overlay_timer_font_size = 8
    else:
        if recording_overlay_timer_font_size > -8:
            recording_overlay_timer_font_size = -8
    recording_overlay_width = _parse_positive_int(
        g("RECORDING_OVERLAY_WIDTH", str(RECORDING_OVERLAY_WIDTH)),
        RECORDING_OVERLAY_WIDTH,
        "RECORDING_OVERLAY_WIDTH",
        minimum=120,
    )
    recording_overlay_height = _parse_positive_int(
        g("RECORDING_OVERLAY_HEIGHT", str(RECORDING_OVERLAY_HEIGHT)),
        RECORDING_OVERLAY_HEIGHT,
        "RECORDING_OVERLAY_HEIGHT",
        minimum=60,
    )
    recording_overlay_timer_offset_x_px = _parse_int_env(
        g("RECORDING_OVERLAY_TIMER_OFFSET_X_PX"),
        0,
        "RECORDING_OVERLAY_TIMER_OFFSET_X_PX",
    )
    recording_overlay_timer_offset_y_px = _parse_int_env(
        g("RECORDING_OVERLAY_TIMER_OFFSET_Y_PX"),
        0,
        "RECORDING_OVERLAY_TIMER_OFFSET_Y_PX",
    )

    state_file = _normalize_path(g("STATE_FILE", DEFAULT_STATE_FILE)) or DEFAULT_STATE_FILE
    scoreboard_bg = (
        _normalize_path(g("SCOREBOARD_BACKGROUND_IMAGE", DEFAULT_SCOREBOARD_BG))
        or DEFAULT_SCOREBOARD_BG
    )
    replay_slate = (
        _normalize_path(g("REPLAY_SLATE_IMAGE", DEFAULT_REPLAY_SLATE)) or DEFAULT_REPLAY_SLATE
    )

    replay_buffer_loading_dir = (
        _normalize_path(
            g("REPLAY_BUFFER_LOADING_DIR", DEFAULT_REPLAY_BUFFER_LOADING_DIR),
        )
        or DEFAULT_REPLAY_BUFFER_LOADING_DIR
    )
    _repo_root = Path(__file__).resolve().parent.parent.parent
    _rbd = Path(replay_buffer_loading_dir)
    if not _rbd.is_absolute():
        replay_buffer_loading_dir = str((_repo_root / _rbd).resolve())
    replay_buffer_loading_frame_ms = _parse_positive_int(
        g("REPLAY_BUFFER_LOADING_FRAME_MS", "3000"),
        3000,
        "REPLAY_BUFFER_LOADING_FRAME_MS",
        minimum=100,
    )
    replay_buffer_loading_margin_px = _parse_positive_int(
        g("REPLAY_BUFFER_LOADING_MARGIN_PX", "24"),
        24,
        "REPLAY_BUFFER_LOADING_MARGIN_PX",
        minimum=0,
    )

    encoder_status_enabled = _env_truthy(g("ENCODER_STATUS_ENABLED"), True)
    encoder_state_path = (
        _normalize_path(g("ENCODER_STATE_PATH", DEFAULT_ENCODER_STATE_FILE))
        or DEFAULT_ENCODER_STATE_FILE
    )
    encoder_status_ready_image = (
        _normalize_path(
            g("ENCODER_STATUS_READY_IMAGE", DEFAULT_ENCODER_READY_IMAGE),
        )
        or DEFAULT_ENCODER_READY_IMAGE
    )
    encoder_status_unavailable_image = (
        _normalize_path(
            g(
                "ENCODER_STATUS_UNAVAILABLE_IMAGE",
                DEFAULT_ENCODER_UNAVAILABLE_IMAGE,
            ),
        )
        or DEFAULT_ENCODER_UNAVAILABLE_IMAGE
    )
    _esp_state = Path(encoder_state_path)
    _esp_ready = Path(encoder_status_ready_image)
    _esp_unavail = Path(encoder_status_unavailable_image)
    if not _esp_state.is_absolute():
        encoder_state_path = str((_repo_root / _esp_state).resolve())
    if not _esp_ready.is_absolute():
        encoder_status_ready_image = str((_repo_root / _esp_ready).resolve())
    if not _esp_unavail.is_absolute():
        encoder_status_unavailable_image = str((_repo_root / _esp_unavail).resolve())
    encoder_status_poll_ms = _parse_positive_int(
        g("ENCODER_STATUS_POLL_MS", "2000"),
        2000,
        "ENCODER_STATUS_POLL_MS",
        minimum=500,
    )
    encoder_status_stale_seconds = _parse_positive_int(
        g("ENCODER_STATUS_STALE_SECONDS", "45"),
        45,
        "ENCODER_STATUS_STALE_SECONDS",
        minimum=5,
    )
    encoder_status_margin_px = _parse_positive_int(
        g("ENCODER_STATUS_MARGIN_PX", "24"),
        24,
        "ENCODER_STATUS_MARGIN_PX",
        minimum=0,
    )

    recording_encoder_sync_enabled = _env_truthy(
        g("RECORDING_ENCODER_SYNC_ENABLED"),
        True,
    )
    recording_encoder_poll_ms = _parse_positive_int(
        g("RECORDING_ENCODER_POLL_MS", "1000"),
        1000,
        "RECORDING_ENCODER_POLL_MS",
        minimum=250,
    )

    launcher_status_enabled = _env_truthy(
        g("SCOREBOARD_LAUNCHER_STATUS_ENABLED"),
        True,
    )
    _launcher_status_path = (
        g(
            "SCOREBOARD_LAUNCHER_STATUS_PATH",
            DEFAULT_LAUNCHER_STATUS_JSON_PATH,
        )
        or DEFAULT_LAUNCHER_STATUS_JSON_PATH
    ).strip()
    _lsp = Path(_launcher_status_path)
    if not _lsp.is_absolute():
        launcher_status_json_path = str((_repo_root / _lsp).resolve())
    else:
        launcher_status_json_path = str(_lsp)
    companion_page_switch_enabled = _env_truthy(
        g("COMPANION_PAGE_SWITCH_ENABLED"),
        False,
    )
    companion_replay_active_page_url = (
        g("COMPANION_REPLAY_ACTIVE_PAGE_URL", "") or ""
    ).strip()
    companion_replay_locked_page_url = (
        g("COMPANION_REPLAY_LOCKED_PAGE_URL", "") or ""
    ).strip()
    companion_replay_idle_page_url = (
        g("COMPANION_REPLAY_IDLE_PAGE_URL", "") or ""
    ).strip()
    companion_readiness_require_obs_websocket = _env_truthy(
        g("COMPANION_READINESS_REQUIRE_OBS_WEBSOCKET"),
        True,
    )
    command_poll_interval_ms = _parse_positive_int(
        g(
            "SCOREBOARD_COMMAND_POLL_MS",
            str(COMMAND_POLL_INTERVAL_MS_DEFAULT),
        ),
        COMMAND_POLL_INTERVAL_MS_DEFAULT,
        "SCOREBOARD_COMMAND_POLL_MS",
        minimum=10,
    )
    if command_poll_interval_ms > 500:
        _LOG.warning(
            "SCOREBOARD_COMMAND_POLL_MS=%s above 500; capping to 500",
            command_poll_interval_ms,
        )
        command_poll_interval_ms = 500

    replay_enabled = _env_truthy(g("REPLAY_ENABLED"), True)
    slideshow_enabled = _env_truthy(g("SLIDESHOW_ENABLED"), True)
    scoreboard_debug = _env_truthy(g("SCOREBOARD_DEBUG"), False)

    heartbeat_interval_minutes = _parse_positive_int(
        g("HEARTBEAT_INTERVAL_MINUTES", "0"),
        0,
        "HEARTBEAT_INTERVAL_MINUTES",
        minimum=0,
    )

    transition_timeout = _parse_positive_int(
        g("REPLAY_TRANSITION_TIMEOUT_MS", str(REPLAY_TRANSITION_TIMEOUT_MS)),
        REPLAY_TRANSITION_TIMEOUT_MS,
        "REPLAY_TRANSITION_TIMEOUT_MS",
        minimum=5000,
    )
    slate_stuck_timeout = _parse_positive_int(
        g("REPLAY_SLATE_STUCK_TIMEOUT_MS", str(REPLAY_SLATE_STUCK_TIMEOUT_MS)),
        REPLAY_SLATE_STUCK_TIMEOUT_MS,
        "REPLAY_SLATE_STUCK_TIMEOUT_MS",
        minimum=5000,
    )

    replay_file_max_age_seconds = _parse_positive_int(
        g(
            "REPLAY_FILE_MAX_AGE_SECONDS",
            str(DEFAULT_REPLAY_FILE_MAX_AGE_SECONDS),
        ),
        DEFAULT_REPLAY_FILE_MAX_AGE_SECONDS,
        "REPLAY_FILE_MAX_AGE_SECONDS",
        minimum=0,
    )
    replay_video_start_delay_ms = _parse_positive_int(
        g(
            "REPLAY_VIDEO_START_DELAY_MS",
            str(REPLAY_VIDEO_START_DELAY_MS),
        ),
        REPLAY_VIDEO_START_DELAY_MS,
        "REPLAY_VIDEO_START_DELAY_MS",
        minimum=0,
    )
    replay_obs_broadcast_on_unavailable = _env_truthy(
        g("REPLAY_OBS_BROADCAST_ON_UNAVAILABLE"), False
    )
    replay_launcher_restart_obs_on_unavailable = _env_truthy(
        g("REPLAY_LAUNCHER_RESTART_OBS_ON_UNAVAILABLE"), False
    )
    replay_launcher_restart_obs_script = _normalize_path(
        g(
            "REPLAY_LAUNCHER_RESTART_OBS_SCRIPT",
            DEFAULT_LAUNCHER_RESTART_OBS_SCRIPT,
        )
    ) or DEFAULT_LAUNCHER_RESTART_OBS_SCRIPT
    _rls = Path(replay_launcher_restart_obs_script)
    if not _rls.is_absolute():
        replay_launcher_restart_obs_script = str((_repo_root / _rls).resolve())

    recording_obs_health_check = _env_truthy(g("RECORDING_OBS_HEALTH_CHECK"), False)
    obs_websocket_host = (g("OBS_WEBSOCKET_HOST", "localhost") or "localhost").strip()
    obs_websocket_port = _parse_positive_int(
        g("OBS_WEBSOCKET_PORT", "4455"),
        4455,
        "OBS_WEBSOCKET_PORT",
        minimum=1,
    )
    if obs_websocket_port > 65535:
        _LOG.warning("OBS_WEBSOCKET_PORT=%s above 65535; using 4455", obs_websocket_port)
        obs_websocket_port = 4455
    obs_websocket_password = g("OBS_WEBSOCKET_PASSWORD", "") or ""
    obs_websocket_timeout_sec = _parse_float_env(
        g("OBS_WEBSOCKET_TIMEOUT_SEC", "2.0"),
        2.0,
        "OBS_WEBSOCKET_TIMEOUT_SEC",
    )
    recording_obs_block_if_main_recording = _env_truthy(
        g("RECORDING_OBS_BLOCK_IF_MAIN_RECORDING", "0"),
        False,
    )
    recording_obs_health_fail_closed = _env_truthy(
        g("RECORDING_OBS_HEALTH_FAIL_CLOSED", "0"),
        False,
    )

    obs_restart_chord_enabled = _env_truthy(g("OBS_RESTART_CHORD_ENABLED"), False)
    obs_executable = _normalize_path(g("OBS_EXECUTABLE", "") or "")
    obs_restart_launch_args = (
        g(
            "OBS_RESTART_LAUNCH_ARGS",
            "--disable-shutdown-check --disable-missing-files-check --startreplaybuffer",
        )
        or ""
    ).strip()
    obs_restart_start_replay_buffer = _env_truthy(
        g("OBS_RESTART_START_REPLAY_BUFFER", "1"),
        True,
    )
    obs_restart_post_launch_delay_ms = _parse_positive_int(
        g("OBS_RESTART_POST_LAUNCH_DELAY_MS", "4500"),
        4500,
        "OBS_RESTART_POST_LAUNCH_DELAY_MS",
        minimum=500,
    )

    obs_status_indicator_enabled = _env_truthy(
        g("OBS_STATUS_INDICATOR_ENABLED", "1"),
        True,
    )
    obs_status_poll_interval_ms = _parse_positive_int(
        g("OBS_STATUS_POLL_INTERVAL_MS", "4000"),
        4000,
        "OBS_STATUS_POLL_INTERVAL_MS",
        minimum=1500,
    )
    obs_status_require_main_output_idle = _env_truthy(
        g("OBS_STATUS_REQUIRE_MAIN_OUTPUT_IDLE", "0"),
        False,
    )

    focus_watchdog_interval_ms = _parse_positive_int(
        g("FOCUS_WATCHDOG_INTERVAL_MS", str(FOCUS_WATCHDOG_INTERVAL_MS)),
        FOCUS_WATCHDOG_INTERVAL_MS,
        "FOCUS_WATCHDOG_INTERVAL_MS",
        minimum=500,
    )
    focus_watchdog_ticks = _parse_positive_int(
        g("FOCUS_WATCHDOG_TICKS", str(FOCUS_WATCHDOG_TICKS)),
        FOCUS_WATCHDOG_TICKS,
        "FOCUS_WATCHDOG_TICKS",
        minimum=1,
    )

    _raw_log = os.environ.get("SCOREBOARD_LOG_FILE")
    if _raw_log is None:
        scoreboard_log_file = DEFAULT_SCOREBOARD_LOG_FILE
    else:
        ls = str(_raw_log).strip().lower()
        if ls in ("", "0", "none", "off", "-", "false", "no"):
            scoreboard_log_file = ""
        else:
            scoreboard_log_file = (
                _normalize_path(str(_raw_log).strip()) or DEFAULT_SCOREBOARD_LOG_FILE
            )

    _raw_central = os.environ.get("REPLAYTROVE_LOGS_ROOT")
    if _raw_central is None or not str(_raw_central).strip():
        central_logs_root = DEFAULT_CENTRAL_LOGS_ROOT
    else:
        central_logs_root = _normalize_path(str(_raw_central).strip()) or DEFAULT_CENTRAL_LOGS_ROOT

    settings = Settings(
        state_file=state_file,
        scoreboard_background_image=scoreboard_bg,
        replay_slate_image=replay_slate,
        slideshow_dir=slideshow_dir,
        replay_video_path=replay_video_path,
        replay_unavailable_image=replay_unavailable_image,
        commands_root=commands_root,
        mpv_path=mpv_path,
        mpv_exit_hotkey=mpv_exit,
        mpv_embedded=mpv_embedded,
        mpv_hwdec_enabled=mpv_hwdec_enabled,
        mpv_hwdec_mode=mpv_hwdec_mode,
        mpv_fullscreen_enabled=mpv_fullscreen_enabled,
        mpv_keep_open_enabled=mpv_keep_open_enabled,
        mpv_loop_enabled=mpv_loop_enabled,
        mpv_video_sync_mode=mpv_video_sync_mode,
        mpv_framedrop_mode=mpv_framedrop_mode,
        mpv_interpolation_enabled=mpv_interpolation_enabled,
        mpv_force_window_enabled=mpv_force_window_enabled,
        mpv_additional_args=mpv_additional_args,
        mpv_process_priority=mpv_process_priority,
        mpv_obs_friendly=mpv_obs_friendly,
        mpv_borderless_fullscreen=mpv_borderless_fullscreen,
        mpv_obs_lower_process_priority=mpv_obs_lower_process_priority,
        mpv_obs_force_software_decode=mpv_obs_force_software_decode,
        mpv_replay_quality=mpv_replay_quality,
        synthetic_focus_click=synthetic_focus_click,
        recording_max_minutes=rec_minutes,
        recording_duration_sec=recording_duration_sec,
        recording_ended_hold_ms=recording_ended_hold_ms,
        replay_buffer_loading_dir=replay_buffer_loading_dir,
        replay_buffer_loading_frame_ms=replay_buffer_loading_frame_ms,
        replay_buffer_loading_margin_px=replay_buffer_loading_margin_px,
        encoder_status_enabled=encoder_status_enabled,
        encoder_state_path=encoder_state_path,
        encoder_status_ready_image=encoder_status_ready_image,
        encoder_status_unavailable_image=encoder_status_unavailable_image,
        encoder_status_poll_ms=encoder_status_poll_ms,
        encoder_status_stale_seconds=encoder_status_stale_seconds,
        encoder_status_margin_px=encoder_status_margin_px,
        recording_encoder_sync_enabled=recording_encoder_sync_enabled,
        recording_encoder_poll_ms=recording_encoder_poll_ms,
        launcher_status_enabled=launcher_status_enabled,
        launcher_status_json_path=launcher_status_json_path,
        companion_page_switch_enabled=companion_page_switch_enabled,
        companion_replay_active_page_url=companion_replay_active_page_url,
        companion_replay_locked_page_url=companion_replay_locked_page_url,
        companion_replay_idle_page_url=companion_replay_idle_page_url,
        companion_readiness_require_obs_websocket=companion_readiness_require_obs_websocket,
        command_poll_interval_ms=command_poll_interval_ms,
        worker_http_health_host=worker_http_health_host,
        worker_http_health_port=worker_http_health_port,
        recording_session_end_info_ms=recording_session_end_info_ms,
        recording_session_end_message=recording_session_end_message,
        recording_overlay_width=recording_overlay_width,
        recording_overlay_height=recording_overlay_height,
        recording_progress_image_on=recording_progress_image_on,
        recording_progress_image_off=recording_progress_image_off,
        recording_ended_image=recording_ended_image,
        recording_ended_graphic_hold_ms=recording_ended_graphic_hold_ms,
        recording_overlay_timer_x_frac=recording_overlay_timer_x_frac,
        recording_overlay_timer_y_frac=recording_overlay_timer_y_frac,
        recording_overlay_timer_font_size=recording_overlay_timer_font_size,
        recording_overlay_timer_offset_x_px=recording_overlay_timer_offset_x_px,
        recording_overlay_timer_offset_y_px=recording_overlay_timer_offset_y_px,
        replay_enabled=replay_enabled,
        slideshow_enabled=slideshow_enabled,
        scoreboard_debug=scoreboard_debug,
        scoreboard_log_file=scoreboard_log_file,
        central_logs_root=central_logs_root,
        heartbeat_interval_minutes=heartbeat_interval_minutes,
        replay_transition_timeout_ms=transition_timeout,
        replay_slate_stuck_timeout_ms=slate_stuck_timeout,
        replay_file_max_age_seconds=replay_file_max_age_seconds,
        replay_video_start_delay_ms=replay_video_start_delay_ms,
        replay_obs_broadcast_on_unavailable=replay_obs_broadcast_on_unavailable,
        replay_launcher_restart_obs_on_unavailable=replay_launcher_restart_obs_on_unavailable,
        replay_launcher_restart_obs_script=replay_launcher_restart_obs_script,
        recording_obs_health_check=recording_obs_health_check,
        obs_websocket_host=obs_websocket_host,
        obs_websocket_port=obs_websocket_port,
        obs_websocket_password=obs_websocket_password,
        obs_websocket_timeout_sec=obs_websocket_timeout_sec,
        recording_obs_block_if_main_recording=recording_obs_block_if_main_recording,
        recording_obs_health_fail_closed=recording_obs_health_fail_closed,
        obs_restart_chord_enabled=obs_restart_chord_enabled,
        obs_executable=obs_executable,
        obs_restart_launch_args=obs_restart_launch_args,
        obs_restart_start_replay_buffer=obs_restart_start_replay_buffer,
        obs_restart_post_launch_delay_ms=obs_restart_post_launch_delay_ms,
        obs_status_indicator_enabled=obs_status_indicator_enabled,
        obs_status_poll_interval_ms=obs_status_poll_interval_ms,
        obs_status_require_main_output_idle=obs_status_require_main_output_idle,
        focus_watchdog_interval_ms=focus_watchdog_interval_ms,
        focus_watchdog_ticks=focus_watchdog_ticks,
    )

    _validate_timing_sane(settings)
    migrated_notes = [
        n
        for n in source_notes
        if n.split("=")[0]
        in (
            "STATE_FILE",
            "COMMANDS_ROOT",
            "SCOREBOARD_BACKGROUND_IMAGE",
            "REPLAY_SLATE_IMAGE",
            "SLIDESHOW_DIR",
            "REPLAY_VIDEO_PATH",
            "REPLAY_UNAVAILABLE_IMAGE",
            "REPLAY_ENABLED",
            "SLIDESHOW_ENABLED",
            "MPV_PATH",
            "MPV_EXIT_HOTKEY",
            "MPV_EMBEDDED",
            "MPV_FULLSCREEN_ENABLED",
            "MPV_LOOP_ENABLED",
            "REPLAY_TRANSITION_TIMEOUT_MS",
            "REPLAY_SLATE_STUCK_TIMEOUT_MS",
            "REPLAY_FILE_MAX_AGE_SECONDS",
            "REPLAY_VIDEO_START_DELAY_MS",
            "REPLAY_BUFFER_LOADING_DIR",
            "REPLAY_BUFFER_LOADING_FRAME_MS",
            "REPLAY_BUFFER_LOADING_MARGIN_PX",
            "ENCODER_STATUS_ENABLED",
            "ENCODER_STATE_PATH",
            "ENCODER_STATUS_POLL_MS",
            "ENCODER_STATUS_STALE_SECONDS",
            "ENCODER_STATUS_MARGIN_PX",
            "SCOREBOARD_LAUNCHER_STATUS_ENABLED",
            "SCOREBOARD_LAUNCHER_STATUS_PATH",
            "OBS_STATUS_INDICATOR_ENABLED",
            "OBS_STATUS_POLL_INTERVAL_MS",
            "OBS_STATUS_REQUIRE_MAIN_OUTPUT_IDLE",
            "COMPANION_PAGE_SWITCH_ENABLED",
            "COMPANION_REPLAY_ACTIVE_PAGE_URL",
            "COMPANION_REPLAY_LOCKED_PAGE_URL",
            "COMPANION_REPLAY_IDLE_PAGE_URL",
            "COMPANION_READINESS_REQUIRE_OBS_WEBSOCKET",
            "SCOREBOARD_COMMAND_POLL_MS",
            "OBS_WEBSOCKET_HOST",
            "OBS_WEBSOCKET_PORT",
            "OBS_WEBSOCKET_PASSWORD",
        )
    ]
    if migrated_notes:
        _LOG.info("scoreboard config source resolution: %s", ", ".join(migrated_notes))
        fallback_notes = [n for n in migrated_notes if not n.endswith("=unified")]
        if fallback_notes:
            _LOG.warning("scoreboard config fallback in use: %s", ", ".join(fallback_notes))
    if "COMMANDS_ROOT=unified" not in source_notes:
        _LOG.warning(
            "scoreboard command bus root using fallback source (prefer unified scoreboard.commandsRoot in config/settings.json)",
        )
    obs_ws_env_notes = [
        n
        for n in source_notes
        if n
        in (
            "OBS_WEBSOCKET_HOST=env",
            "OBS_WEBSOCKET_PORT=env",
            "OBS_WEBSOCKET_PASSWORD=env",
        )
    ]
    if obs_ws_env_notes:
        _LOG.warning(
            "scoreboard OBS websocket config using env source: %s (prefer unified scoreboard.obsWebsocketHost/obsWebsocketPort/obsWebsocketPassword)",
            ", ".join(obs_ws_env_notes),
        )
    if "OBS_WEBSOCKET_PASSWORD=unified" in source_notes:
        _LOG.warning(
            "scoreboard OBS websocket password must remain env-only; unified source is intentionally unsupported",
        )
    return settings


def _validate_timing_sane(settings: Settings) -> None:
    if settings.idle_timeout_ms < 1000:
        _LOG.warning("idle_timeout_ms=%s is very low", settings.idle_timeout_ms)
    if settings.recording_duration_sec < 60:
        _LOG.warning("recording duration under 1 minute may be unintended")
    if settings.slideshow_fade_steps < 1:
        _LOG.error("slideshow_fade_steps invalid; check defaults")
    if settings.replay_video_start_delay_ms < 0:
        _LOG.error("replay_video_start_delay_ms must be non-negative")


def summarize_settings(settings: Settings) -> str:
    """Human-readable summary for startup diagnostics (no secrets)."""
    lines = [
        f"state_file={settings.state_file!r}",
        f"scoreboard_background_image={settings.scoreboard_background_image!r}",
        f"replay_slate_image={settings.replay_slate_image!r}",
        f"slideshow_dir={settings.slideshow_dir!r}",
        f"replay_video_path={settings.replay_video_path!r}",
        f"replay_unavailable_image={settings.replay_unavailable_image!r}",
        f"commands_root={settings.commands_root!r}",
        f"mpv_path={settings.mpv_path!r}",
        f"mpv_embedded={settings.mpv_embedded}",
        f"mpv_hwdec_enabled={settings.mpv_hwdec_enabled}",
        f"mpv_hwdec_mode={settings.mpv_hwdec_mode!r}",
        f"mpv_fullscreen_enabled={settings.mpv_fullscreen_enabled}",
        f"mpv_keep_open_enabled={settings.mpv_keep_open_enabled}",
        f"mpv_loop_enabled={settings.mpv_loop_enabled}",
        f"mpv_video_sync_mode={settings.mpv_video_sync_mode!r}",
        f"mpv_framedrop_mode={settings.mpv_framedrop_mode!r}",
        f"mpv_interpolation_enabled={settings.mpv_interpolation_enabled}",
        f"mpv_force_window_enabled={settings.mpv_force_window_enabled}",
        f"mpv_additional_args={settings.mpv_additional_args!r}",
        f"mpv_process_priority={settings.mpv_process_priority!r}",
        f"mpv_obs_friendly={settings.mpv_obs_friendly}",
        f"mpv_borderless_fullscreen={settings.mpv_borderless_fullscreen}",
        f"mpv_obs_lower_process_priority={settings.mpv_obs_lower_process_priority}",
        f"mpv_obs_force_software_decode={settings.mpv_obs_force_software_decode}",
        f"mpv_replay_quality={settings.mpv_replay_quality!r}",
        f"mpv_exit_hotkey={settings.mpv_exit_hotkey!r}",
        f"synthetic_focus_click={settings.synthetic_focus_click}",
        f"recording_max_minutes={settings.recording_max_minutes}",
        f"recording_ended_hold_ms={settings.recording_ended_hold_ms}",
        f"recording_session_end_info_ms={settings.recording_session_end_info_ms}",
        f"recording_overlay_width={settings.recording_overlay_width}",
        f"recording_overlay_height={settings.recording_overlay_height}",
        f"recording_progress_image_on={settings.recording_progress_image_on!r}",
        f"recording_ended_image={settings.recording_ended_image!r}",
        f"recording_ended_graphic_hold_ms={settings.recording_ended_graphic_hold_ms}",
        f"recording_overlay_timer_offset_x_px={settings.recording_overlay_timer_offset_x_px}",
        f"recording_overlay_timer_offset_y_px={settings.recording_overlay_timer_offset_y_px}",
        f"replay_buffer_loading_dir={settings.replay_buffer_loading_dir!r}",
        f"replay_buffer_loading_frame_ms={settings.replay_buffer_loading_frame_ms}",
        f"replay_buffer_loading_margin_px={settings.replay_buffer_loading_margin_px}",
        f"encoder_status_enabled={settings.encoder_status_enabled}",
        f"encoder_state_path={settings.encoder_state_path!r}",
        f"encoder_status_ready_image={settings.encoder_status_ready_image!r}",
        f"encoder_status_unavailable_image={settings.encoder_status_unavailable_image!r}",
        f"encoder_status_poll_ms={settings.encoder_status_poll_ms}",
        f"encoder_status_stale_seconds={settings.encoder_status_stale_seconds}",
        f"encoder_status_margin_px={settings.encoder_status_margin_px}",
        f"recording_encoder_sync_enabled={settings.recording_encoder_sync_enabled}",
        f"recording_encoder_poll_ms={settings.recording_encoder_poll_ms}",
        f"launcher_status_enabled={settings.launcher_status_enabled}",
        f"launcher_status_json_path={settings.launcher_status_json_path!r}",
        f"companion_page_switch_enabled={settings.companion_page_switch_enabled}",
        f"companion_replay_active_page_url={settings.companion_replay_active_page_url!r}",
        f"companion_replay_locked_page_url={settings.companion_replay_locked_page_url!r}",
        f"companion_replay_idle_page_url={settings.companion_replay_idle_page_url!r}",
        f"companion_readiness_require_obs_websocket={settings.companion_readiness_require_obs_websocket}",
        f"command_poll_interval_ms={settings.command_poll_interval_ms}",
        f"worker_http_health_host={settings.worker_http_health_host!r}",
        f"worker_http_health_port={settings.worker_http_health_port}",
        f"idle_timeout_ms={settings.idle_timeout_ms}",
        f"slideshow_interval_ms={settings.slideshow_interval_ms}",
        f"replay_enabled={settings.replay_enabled}",
        f"slideshow_enabled={settings.slideshow_enabled}",
        f"scoreboard_debug={settings.scoreboard_debug}",
        f"scoreboard_log_file={settings.scoreboard_log_file!r}",
        f"central_logs_root={settings.central_logs_root!r}",
        f"heartbeat_interval_minutes={settings.heartbeat_interval_minutes}",
        f"replay_transition_timeout_ms={settings.replay_transition_timeout_ms}",
        f"replay_slate_stuck_timeout_ms={settings.replay_slate_stuck_timeout_ms}",
        f"replay_file_max_age_seconds={settings.replay_file_max_age_seconds}",
        f"replay_video_start_delay_ms={settings.replay_video_start_delay_ms}",
        f"replay_obs_broadcast_on_unavailable={settings.replay_obs_broadcast_on_unavailable}",
        f"replay_launcher_restart_obs_on_unavailable={settings.replay_launcher_restart_obs_on_unavailable}",
        f"replay_launcher_restart_obs_script={settings.replay_launcher_restart_obs_script!r}",
        f"recording_obs_health_check={settings.recording_obs_health_check}",
        f"obs_websocket_host={settings.obs_websocket_host!r}",
        f"obs_websocket_port={settings.obs_websocket_port}",
        f"obs_websocket_timeout_sec={settings.obs_websocket_timeout_sec}",
        f"recording_obs_block_if_main_recording={settings.recording_obs_block_if_main_recording}",
        f"recording_obs_health_fail_closed={settings.recording_obs_health_fail_closed}",
        f"obs_restart_chord_enabled={settings.obs_restart_chord_enabled}",
        f"obs_executable={settings.obs_executable!r}",
        f"obs_restart_launch_args={settings.obs_restart_launch_args!r}",
        f"obs_restart_start_replay_buffer={settings.obs_restart_start_replay_buffer}",
        f"obs_restart_post_launch_delay_ms={settings.obs_restart_post_launch_delay_ms}",
        f"obs_status_indicator_enabled={settings.obs_status_indicator_enabled}",
        f"obs_status_poll_interval_ms={settings.obs_status_poll_interval_ms}",
        f"obs_status_require_main_output_idle={settings.obs_status_require_main_output_idle}",
        f"focus_watchdog_ticks={settings.focus_watchdog_ticks}",
        f"focus_watchdog_interval_ms={settings.focus_watchdog_interval_ms}",
    ]
    return "\n".join(lines)


