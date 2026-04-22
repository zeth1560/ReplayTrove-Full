"""Tk scoreboard application: orchestration only; features live in sibling modules."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageTk

from scoreboard.config.settings import DEFAULT_COMMANDS_ROOT, Settings, load_settings
from scoreboard.config.unified_adapter import load_scoreboard_unified_snapshot
from scoreboard.obs_health import check_obs_recording_gate, probe_obs_video_recorder_ready
from scoreboard.encoder_status_overlay import EncoderStatusOverlay
from scoreboard.persistence.score_store import load_scores, save_scores
from scoreboard.platform.win32 import win32_force_foreground, win32_synthetic_click_window_center
from scoreboard.encoder_recording_sync import load_encoder_recording_snapshot
from scoreboard.launcher_status import utc_now_iso, write_launcher_status_json
from scoreboard.recording_overlay import RecordingOverlay, RecordingOverlayState
from scoreboard.replay_buffer_loading_overlay import ReplayBufferLoadingOverlay
from scoreboard.replay_controller import ReplayController
from scoreboard.scheduler import AfterScheduler
from scoreboard.screensaver import Screensaver
from scoreboard.ui_focus_diag import operator_foreground_ok, root_wm_snapshot

_LOG = logging.getLogger(__name__)

# Watchdog focus_ok=False: at most one INFO line per this many seconds (pilot log noise).
_FOCUS_WATCHDOG_FAIL_INFO_COOLDOWN_SEC = 30.0

# Operator-facing UI: compact visibility heartbeat and stuck-window detection.
_OPERATOR_UI_HEARTBEAT_MS = 10_000
_OPERATOR_FG_STUCK_SEC = 45.0
_OPERATOR_FG_STUCK_WARN_COOLDOWN_SEC = 90.0
_REC_OVERLAY_NOT_FG_WARN_COOLDOWN_SEC = 45.0
_FOCUS_RECLAIM_FAIL_DIAG_THRESHOLD = 5

# OBS restart pipeline (optional): triggered via command file when OBS_RESTART_CHORD_ENABLED=1.
_OBS_RESTART_COOLDOWN_SEC = 8.0

SAFE_RELOAD_STATUS_PATH = r"C:\ReplayTrove\scoreboard\reload_safe_settings_status.json"

_SAFE_RELOAD_MIN_MS = 100
_SAFE_RELOAD_MAX_MS = 60_000


@dataclass(frozen=True)
class RuntimeSafeSettings:
    # Deliberately tiny live-reload snapshot (Phase 5 allowlist only).
    obs_status_poll_interval_ms: int
    encoder_status_poll_ms: int


class ScoreboardApp:
    def __init__(self, root: tk.Tk, settings: Settings | None = None) -> None:
        self.root = root
        self.logger = _LOG
        self.settings = settings or load_settings()
        self._closing = False
        self.scheduler = AfterScheduler(
            root,
            logger=_LOG.getChild("scheduler"),
            debug_schedule=self.settings.scoreboard_debug,
            alive_check=self._app_is_alive,
        )
        self._runtime_safe_lock = threading.Lock()
        self._runtime_safe_settings = RuntimeSafeSettings(
            obs_status_poll_interval_ms=int(self.settings.obs_status_poll_interval_ms),
            encoder_status_poll_ms=int(self.settings.encoder_status_poll_ms),
        )
        self._commands_root = Path(self.settings.commands_root)
        self._commands_pending_dir = str(self._commands_root / "scoreboard" / "pending")
        self._commands_processed_dir = str(
            self._commands_root / "scoreboard" / "processed"
        )
        self._commands_failed_dir = str(self._commands_root / "scoreboard" / "failed")
        self._legacy_commands_root = Path(DEFAULT_COMMANDS_ROOT)
        self._legacy_pending_dir = str(
            self._legacy_commands_root / "scoreboard" / "pending"
        )
        self._command_pending_scan_dirs: list[str] = [self._commands_pending_dir]
        if Path(self._legacy_pending_dir) != Path(self._commands_pending_dir):
            self._command_pending_scan_dirs.append(self._legacy_pending_dir)
            self.logger.warning(
                "scoreboard command bus root diverged from legacy path configured_root=%s legacy_root=%s compatibility_bridge=legacy_pending_enabled",
                str(self._commands_root),
                str(self._legacy_commands_root),
            )
        self.logger.info(
            "scoreboard command bus directories pending=%s processed=%s failed=%s pending_scan_dirs=%s",
            self._commands_pending_dir,
            self._commands_processed_dir,
            self._commands_failed_dir,
            self._command_pending_scan_dirs,
        )

        state_path = Path(self.settings.state_file)

        self.root.title("Scoreboard")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="black")

        self._score_state = load_scores(state_path, rewrite_defaults_if_corrupt=True)

        self._idle_check_job: str | None = None
        self._focus_watchdog_job: str | None = None
        self._focus_claim_jobs: list[str | None] = []
        self._synthetic_click_jobs: list[str | None] = []
        self._release_topmost_job: str | None = None
        self._heartbeat_job: str | None = None
        self._operator_ui_heartbeat_job: str | None = None
        self._recording_obs_check_in_flight = False
        self._obs_restart_last_mono = 0.0
        self._obs_status_win: tk.Toplevel | None = None
        self._obs_status_inner: tk.Frame | None = None
        self._obs_status_label: tk.Label | None = None
        self._obs_status_poll_after: str | None = None
        self._obs_status_poll_busy = False
        self._encoder_recording_poll_job: str | None = None
        self._encoder_recording_prev_seq: int | None = None
        self._encoder_sync_believes_recording = False
        self.focus_watchdog_ticks_left = 0
        self._focus_watchdog_exhausted_logged = False
        self.last_input_ms = int(time.monotonic() * 1000)
        self._synthetic_click_attempts = 0
        self._last_watchdog_focus_fail_info_mono = 0.0
        self._focus_reclaim_fail_streak = 0
        self._operator_not_fg_since_mono: float | None = None
        self._last_operator_fg_stuck_warn_mono = 0.0
        self._last_rec_overlay_fg_warn_mono = 0.0
        self._last_black_screen_off_mono: float | None = None
        self._heartbeat_prev_rec_ui = False

        self.black_screen_active = False
        self.black_screen_cover_visible = False

        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()

        try:
            self.bg_image = (
                Image.open(self.settings.scoreboard_background_image)
                .resize((self.screen_width, self.screen_height))
                .convert("RGBA")
            )
            self.replay_image = (
                Image.open(self.settings.replay_slate_image)
                .resize((self.screen_width, self.screen_height))
                .convert("RGBA")
            )
        except OSError:
            _LOG.exception(
                "Failed to load or decode scoreboard images (paths validated at startup; file may have changed)"
            )
            raise

        self.bg_photo = ImageTk.PhotoImage(self.bg_image)

        self.transparent_overlay = Image.new(
            "RGBA",
            (self.screen_width, self.screen_height),
            (0, 0, 0, 0),
        )
        self.overlay_photo = ImageTk.PhotoImage(self.transparent_overlay)

        self.canvas = tk.Canvas(
            root,
            width=self.screen_width,
            height=self.screen_height,
            highlightthickness=0,
            takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True)
        self.video_host = tk.Frame(root, bg="black")
        self.black_screen_frame = tk.Frame(root, bg="black", highlightthickness=0)
        self.ensure_window_opaque()

        self.bg_canvas = self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")
        self.overlay_canvas = self.canvas.create_image(0, 0, image=self.overlay_photo, anchor="nw")

        self.left_x = int(self.screen_width * 0.23)
        self.right_x = int(self.screen_width * 0.77)
        self.center_y = int(self.screen_height * 0.51)
        self.font_size = int(self.screen_height * 0.45)
        self.squeeze_x = 0.88

        self._encoder_status_overlay = EncoderStatusOverlay(
            root,
            self.settings,
            self.scheduler,
            self.canvas,
            self.overlay_canvas,
            self.screen_width,
            self.screen_height,
        )

        self.recording_overlay = RecordingOverlay(
            root,
            self.settings,
            self.scheduler,
            self.screen_width,
            self.screen_height,
            on_dismiss_chord=self._on_recording_dismiss_chord,
            on_ui_visibility=self._on_recording_ui_visibility,
        )

        self._replay_buffer_loading = ReplayBufferLoadingOverlay(
            root,
            self.settings,
            self.scheduler,
            self.canvas,
            self.overlay_canvas,
            self.screen_width,
            self.screen_height,
        )

        self.screensaver = Screensaver(
            root,
            self.canvas,
            self.overlay_canvas,
            self.settings,
            self.scheduler,
            self.screen_width,
            self.screen_height,
            lift_recording_overlay=self.recording_overlay.lift,
            reclaim_keyboard_focus=lambda: self.claim_keyboard_focus(
                reason="screensaver_periodic",
            ),
            on_stopped=self._on_screensaver_stopped,
            after_overlay_raise=self._sync_canvas_aux_overlays,
            on_active_changed=lambda _active: self._publish_launcher_status(),
        )
        self.screensaver.set_transparent_overlay_photo(self.overlay_photo)

        self.replay = ReplayController(
            root,
            self.settings,
            self.scheduler,
            self.canvas,
            self.video_host,
            self.bg_canvas,
            self.overlay_canvas,
            self.replay_image,
            self.overlay_photo,
            lift_recording_overlay=self.recording_overlay.lift,
            before_slate_fade_in=self._hide_black_screen_cover,
            after_replay_fade_out=self._after_replay_fade_out,
            redraw_scores=self.draw_scores,
            on_successful_replay_session_end=self.start_replay_buffer_loading_overlay,
            after_overlay_raise=self._sync_canvas_aux_overlays,
        )

        self.draw_scores()

        self.canvas.tag_raise(self.overlay_canvas)
        self._sync_canvas_aux_overlays()

        self._encoder_status_overlay.start()

        self._setup_obs_status_indicator()
        self._bind_keys()
        self.schedule_idle_check()
        self.schedule_claim_focus()
        self.start_focus_watchdog()
        self.schedule_synthetic_focus_clicks()
        self._schedule_heartbeat()
        self._schedule_operator_ui_heartbeat()
        self._apply_hidden_cursor()
        self._schedule_encoder_recording_poll()
        self._publish_launcher_status()
        self._log_startup_readiness()
        self.root.after(100, self.command_poll_loop)

    @property
    def replay_controller(self) -> ReplayController:
        return self.replay

    def check_for_commands(self) -> None:
        try:
            all_json_files: list[Path] = []
            for pending_dir in self._command_pending_scan_dirs:
                pending = Path(pending_dir)
                if not pending.is_dir():
                    continue
                json_files = sorted(
                    p
                    for p in pending.iterdir()
                    if p.is_file()
                    and p.suffix.lower() == ".json"
                    and not p.name.endswith(".tmp")
                )
                all_json_files.extend(json_files)

            seen: set[str] = set()
            for path in sorted(all_json_files):
                path_key = str(path.resolve())
                if path_key in seen:
                    continue
                seen.add(path_key)
                try:
                    if (
                        Path(path).parent == Path(self._legacy_pending_dir)
                        and Path(self._legacy_pending_dir)
                        != Path(self._commands_pending_dir)
                    ):
                        self.logger.warning(
                            "command_bus_legacy_bridge path=%s configured_pending=%s",
                            path,
                            self._commands_pending_dir,
                        )
                    self.process_command_file(str(path))
                except Exception as e:
                    self.logger.error(f"command_poll_error: {e}")
        except Exception as e:
            self.logger.error(f"command_poll_error: {e}")

    def _command_resolve_destination(self, dest_dir: Path, original_name: str) -> Path:
        """Pick a destination path under dest_dir, avoiding name clashes with existing files."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        candidate = dest_dir / original_name
        if not candidate.exists():
            return candidate
        self.logger.info("command_move_collision: destination exists, resolving...")
        stem = Path(original_name).stem
        suf = Path(original_name).suffix
        for n in range(1, 10_000):
            alt = dest_dir / f"{stem}_{n}{suf}"
            if not alt.exists():
                return alt
        self.logger.warning(
            "command_move_collision: suffix space exhausted; removing blocking file %s",
            candidate,
        )
        try:
            candidate.unlink()
        except OSError:
            pass
        return candidate

    def _command_try_move(self, src: Path, dest_dir: str) -> bool:
        if not src.is_file():
            return True
        try:
            dest = self._command_resolve_destination(Path(dest_dir), src.name)
            os.replace(str(src), str(dest))
            self.logger.info("command_move_success src=%s dest=%s", src, dest)
            return True
        except OSError:
            return False

    def process_command_file(self, path: str) -> None:
        path_obj = Path(path)
        cmd_id = "?"
        action = "?"
        cid = "-"
        ok = False
        try:
            with path_obj.open(encoding="utf-8") as f:
                payload = json.load(f)
            cmd_id = payload.get("id", "?")
            action = payload["action"]
            if not isinstance(action, str):
                raise TypeError("action must be a string")
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                raise TypeError("args must be a JSON object")
            cid = str(args.get("correlation_id") or payload.get("correlation_id") or "-")
            self.logger.info(
                "command_received id=%s cid=%s action=%s args=%s",
                cmd_id,
                cid,
                action,
                args,
            )
            self.handle_command(action, args)
            ok = True
            self.logger.info("command_completed id=%s cid=%s action=%s", cmd_id, cid, action)
        except Exception as e:
            self.logger.error("command_failed path=%s id=%s cid=%s action=%s error=%s", path, cmd_id, cid, action, e)

        if not path_obj.is_file():
            return

        primary_dir = self._commands_processed_dir if ok else self._commands_failed_dir
        if self._command_try_move(path_obj, primary_dir):
            return

        self.logger.error(
            "command_failed path=%s error=%s",
            path,
            f"relocate_to_{'processed' if ok else 'failed'}_failed",
        )
        if ok and self._command_try_move(path_obj, self._commands_failed_dir):
            return
        if ok:
            self.logger.error(
                "command_failed path=%s error=%s",
                path,
                "relocate_fallback_failed",
            )

        if path_obj.is_file():
            try:
                path_obj.unlink()
                self.logger.warning(
                    "command_pending_force_removed path=%s handle_ok=%s",
                    path,
                    ok,
                )
            except OSError as e:
                self.logger.error(
                    "command_failed path=%s error=%s",
                    path,
                    f"pending_unlink_failed: {e}",
                )

    def handle_command(self, action: str, args: dict[str, Any]) -> None:
        if action == "black_screen_on":
            self.enable_black_screen()
        elif action == "black_screen_off":
            self.disable_black_screen()
        elif action == "toggle_replay":
            self.logger.warning(
                "replay_command_deprecated action=toggle_replay; use replay_on/replay_off (non-canonical operator path)",
            )
            self.toggle_replay()
        elif action == "replay_on":
            trigger_source = args.get("trigger_source")
            if not isinstance(trigger_source, str):
                trigger_source = None
            trust_category = args.get("canonical_trust_category")
            if trust_category not in {
                "canonical_trusted",
                "canonical_claim_untrusted",
                "legacy_noncanonical",
            }:
                if trigger_source == "save_replay_and_trigger.ps1":
                    trust_category = "canonical_claim_untrusted"
                else:
                    trust_category = "legacy_noncanonical"
            trust_reason = args.get("canonical_trust_reason")
            if not isinstance(trust_reason, str) or not trust_reason.strip():
                trust_reason = "missing_trust_reason"
            if trust_category == "canonical_trusted":
                self.logger.info(
                    "replay_command_trust action=replay_on trust_category=%s trust_reason=%s trigger_source=%s",
                    trust_category,
                    trust_reason,
                    trigger_source,
                )
            elif trust_category == "canonical_claim_untrusted":
                self.logger.warning(
                    "replay_command_trust action=replay_on trust_category=%s trust_reason=%s trigger_source=%s canonical_source=save_replay_and_trigger.ps1",
                    trust_category,
                    trust_reason,
                    trigger_source,
                )
            else:
                self.logger.warning(
                    "replay_command_trust action=replay_on trust_category=%s trust_reason=%s trigger_source=%s canonical_source=save_replay_and_trigger.ps1",
                    trust_category,
                    trust_reason,
                    trigger_source,
                )
            if self._replay_command_is_on():
                self.logger.info(
                    "replay_command_noop action=replay_on reason=already_on",
                )
                return
            self.toggle_replay()
        elif action == "replay_off":
            if not self._replay_command_is_on():
                self.logger.info(
                    "replay_command_noop action=replay_off reason=already_off",
                )
                return
            self.toggle_replay()
        elif action == "score_left_plus":
            try:
                amount = int(args.get("amount", 1))
            except (TypeError, ValueError):
                amount = 1
            self.increment_left(amount)
        elif action == "score_left_minus":
            try:
                amount = int(args.get("amount", 1))
            except (TypeError, ValueError):
                amount = 1
            self.increment_left(-amount)
        elif action == "score_right_plus":
            try:
                amount = int(args.get("amount", 1))
            except (TypeError, ValueError):
                amount = 1
            self.increment_right(amount)
        elif action == "score_right_minus":
            try:
                amount = int(args.get("amount", 1))
            except (TypeError, ValueError):
                amount = 1
            self.increment_right(-amount)
        elif action == "reset_scores":
            self.reset_scores()
        elif action == "recording_start":
            self.on_streamdeck_input(self.on_recording_start_hotkey)
        elif action == "recording_dismiss":
            self.on_streamdeck_input(self._recording_dismiss_deferred)
        elif action == "replay_buffer_loading":
            self.on_streamdeck_input(self.start_replay_buffer_loading_overlay)
        elif action == "obs_restart":
            self.scheduler.schedule(0, self._command_obs_restart, name="command_obs_restart")
        elif action == "dismiss_replay_unavailable":
            self.replay.dismiss_replay_unavailable_overlay()
        elif action == "reload_scoreboard_safe_settings":
            self._reload_scoreboard_safe_settings(args)
        else:
            raise ValueError(f"unknown action: {action!r}")

    def _read_runtime_safe_settings(self) -> RuntimeSafeSettings:
        with self._runtime_safe_lock:
            return self._runtime_safe_settings

    def _replace_runtime_safe_settings(self, new_value: RuntimeSafeSettings) -> None:
        # Atomic snapshot swap under lock; avoid in-place shared mutation.
        with self._runtime_safe_lock:
            self._runtime_safe_settings = new_value

    def _reload_scoreboard_safe_settings(self, args: dict[str, Any]) -> None:
        # Explicit, scoreboard-only safe reload entrypoint.
        cid = str(args.get("correlation_id") or "-")
        requested = [
            "scoreboard.obsStatusPollIntervalMs",
            "scoreboard.encoderStatusPollMs",
        ]
        self.logger.info(
            "reload_attempted action=reload_scoreboard_safe_settings cid=%s requested_keys=%s",
            cid,
            requested,
        )
        try:
            snap = load_scoreboard_unified_snapshot()
            if snap.error:
                self.logger.error(
                    "reload_rejected action=reload_scoreboard_safe_settings cid=%s reason=config_parse_error error=%s",
                    cid,
                    snap.error,
                )
                self.logger.warning(
                    "reload_fallback_preserved action=reload_scoreboard_safe_settings cid=%s reason=parse_error",
                    cid,
                )
                self._write_safe_reload_status(
                    cid=cid,
                    status="rejected",
                    applied_fields=[],
                    rejection_reason=f"config_parse_error: {snap.error}",
                    schema_version=snap.schema_version,
                )
                return

            sb = snap.scoreboard or {}
            obs_raw = sb.get("obsStatusPollIntervalMs")
            enc_raw = sb.get("encoderStatusPollMs")
            errors: list[str] = []
            if not isinstance(obs_raw, int) or isinstance(obs_raw, bool):
                errors.append("obsStatusPollIntervalMs must be integer")
            if not isinstance(enc_raw, int) or isinstance(enc_raw, bool):
                errors.append("encoderStatusPollMs must be integer")

            if not errors:
                if obs_raw < _SAFE_RELOAD_MIN_MS or obs_raw > _SAFE_RELOAD_MAX_MS:
                    errors.append(
                        f"obsStatusPollIntervalMs must be {_SAFE_RELOAD_MIN_MS}-{_SAFE_RELOAD_MAX_MS}"
                    )
                if enc_raw < _SAFE_RELOAD_MIN_MS or enc_raw > _SAFE_RELOAD_MAX_MS:
                    errors.append(
                        f"encoderStatusPollMs must be {_SAFE_RELOAD_MIN_MS}-{_SAFE_RELOAD_MAX_MS}"
                    )

            if errors:
                self.logger.error(
                    "reload_rejected action=reload_scoreboard_safe_settings cid=%s schema_version=%s reasons=%s",
                    cid,
                    snap.schema_version,
                    errors,
                )
                self.logger.warning(
                    "reload_fallback_preserved action=reload_scoreboard_safe_settings cid=%s reason=validation_failed",
                    cid,
                )
                self._write_safe_reload_status(
                    cid=cid,
                    status="rejected",
                    applied_fields=[],
                    rejection_reason="; ".join(errors),
                    schema_version=snap.schema_version,
                )
                return

            old = self._read_runtime_safe_settings()
            new = replace(
                old,
                obs_status_poll_interval_ms=int(obs_raw),
                encoder_status_poll_ms=int(enc_raw),
            )
            self._replace_runtime_safe_settings(new)

            # Idempotent timer refresh: each scheduler path cancels before scheduling.
            self._schedule_obs_status_poll_after()
            self._encoder_status_overlay.set_poll_interval_ms(new.encoder_status_poll_ms)

            self.logger.info(
                "reload_applied action=reload_scoreboard_safe_settings cid=%s schema_version=%s old_values=%s new_values=%s",
                cid,
                snap.schema_version,
                {
                    "obsStatusPollIntervalMs": old.obs_status_poll_interval_ms,
                    "encoderStatusPollMs": old.encoder_status_poll_ms,
                },
                {
                    "obsStatusPollIntervalMs": new.obs_status_poll_interval_ms,
                    "encoderStatusPollMs": new.encoder_status_poll_ms,
                },
            )
            self._write_safe_reload_status(
                cid=cid,
                status="applied",
                applied_fields=requested,
                rejection_reason=None,
                schema_version=snap.schema_version,
            )
        except Exception as exc:
            self.logger.error(
                "reload_rejected action=reload_scoreboard_safe_settings cid=%s reason=unexpected_error error=%s",
                cid,
                exc,
            )
            self.logger.warning(
                "reload_fallback_preserved action=reload_scoreboard_safe_settings cid=%s reason=unexpected_error",
                cid,
            )
            self._write_safe_reload_status(
                cid=cid,
                status="rejected",
                applied_fields=[],
                rejection_reason=f"unexpected_error: {exc}",
                schema_version=None,
            )

    def _write_safe_reload_status(
        self,
        *,
        cid: str,
        status: str,
        applied_fields: list[str],
        rejection_reason: str | None,
        schema_version: int | None,
    ) -> None:
        # Read-only status artifact for Control Center queued-vs-applied clarity.
        try:
            payload: dict[str, Any] = {
                "timestamp": utc_now_iso(),
                "correlation_id": cid,
                "status": status,
                "applied_fields": applied_fields,
                "schema_version": schema_version,
            }
            if rejection_reason:
                payload["rejection_reason"] = rejection_reason
            out = Path(SAFE_RELOAD_STATUS_PATH)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            os.replace(tmp, out)
        except Exception:
            self.logger.debug(
                "reload_safe_settings_status_write_failed",
                exc_info=True,
            )

    def _replay_command_is_on(self) -> bool:
        # Command bus "on" means replay is visible/playing OR mid-transition.
        return (
            self.replay.showing_replay
            or self.replay.replay_video_active
            or self.replay.is_transitioning
        )

    def command_poll_loop(self) -> None:
        self.check_for_commands()
        if not self._closing:
            self.root.after(100, self.command_poll_loop)

    def enable_black_screen(self) -> None:
        if self.replay.blocks_black_screen_toggle():
            self.logger.info(
                "enable_black_screen ignored (replay busy transitioning=%s video=%s showing=%s)",
                self.replay.is_transitioning,
                self.replay.replay_video_active,
                self.replay.showing_replay,
            )
            return
        if self.black_screen_active:
            return
        self.black_screen_active = True
        self._show_black_screen_cover()
        _LOG.info(
            "UI_transition black_screen_on snapshot=%s",
            self._diagnostic_ui_snapshot(),
        )
        self.recording_overlay.lift()

    def disable_black_screen(self) -> None:
        if self.replay.blocks_black_screen_toggle():
            self.logger.info(
                "disable_black_screen ignored (replay busy transitioning=%s video=%s showing=%s)",
                self.replay.is_transitioning,
                self.replay.replay_video_active,
                self.replay.showing_replay,
            )
            return
        if not self.black_screen_active:
            return
        self.black_screen_active = False
        self._hide_black_screen_cover()
        self._recover_after_black_screen_off(event="black_screen_off")
        self.recording_overlay.lift()

    def increment_left(self, amount: int = 1) -> None:
        self.update_score("a", amount)

    def increment_right(self, amount: int = 1) -> None:
        self.update_score("b", amount)

    def _publish_launcher_status(self) -> None:
        """Emit JSON for ReplayTrove launcher (screensaver + process liveness)."""
        if not self.settings.launcher_status_enabled:
            return
        path = self.settings.launcher_status_json_path
        if not path or not str(path).strip():
            return
        payload = {
            "scoreboard_running": not self._closing,
            "screensaver_active": self.screensaver.is_active(),
            "updated_at": utc_now_iso(),
        }
        if write_launcher_status_json(path, payload):
            _LOG.info(
                "Launcher status: wrote %s (scoreboard_running=%s screensaver_active=%s)",
                path,
                payload["scoreboard_running"],
                payload["screensaver_active"],
            )

    def _app_is_alive(self) -> bool:
        """False while shutting down — used by AfterScheduler to drop queued work safely.

        Intentionally does **not** use ``winfo_exists()`` on the root: on some Windows/fullscreen
        setups, that call can return 0 intermittently while the UI is healthy. If the scheduler
        skips a callback, recurring jobs like the recording countdown never reschedule and appear
        stuck (or never start, e.g. OBS gate completion never runs).
        """
        return not self._closing

    def _log_startup_readiness(self) -> None:
        log_path = (self.settings.scoreboard_log_file or "").strip()
        _LOG.info(
            "Startup readiness: command_bus=ok replay_enabled=%s "
            "recording_overlay=ok scheduler=ok synthetic_focus_click=%s "
            "obs_recording_gate=%s encoder_recording_sync=%s obs_restart_chord=%s "
            "obs_status_indicator=%s log_file=%s",
            self.settings.replay_enabled,
            self.settings.synthetic_focus_click,
            "on"
            if self.settings.recording_obs_health_check
            else "off",
            "on" if self.settings.recording_encoder_sync_enabled else "off",
            "on" if self.settings.obs_restart_chord_enabled else "off",
            "on" if self.settings.obs_status_indicator_enabled else "off",
            repr(log_path) if log_path else "(stderr only)",
        )

    def diagnostic_snapshot(self) -> dict[str, Any]:
        """Full operator/UI state for logs, support, or hooks."""
        return self._diagnostic_ui_snapshot()

    def _root_exists_best_effort(self) -> bool:
        try:
            return bool(int(self.root.winfo_exists()))
        except (tk.TclError, ValueError, TypeError):
            return False

    def _diagnostic_ui_snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = {"pid": os.getpid()}
        root_ok = self._root_exists_best_effort()
        snap["root_exists"] = root_ok
        if root_ok:
            try:
                snap["root_wm"] = root_wm_snapshot(self.root)
            except tk.TclError:
                snap["root_wm"] = {"error": "tcl"}
        ro = self.recording_overlay
        rec_top = ro.recording_toplevel()
        rec_active = ro.is_ui_active()
        fg_ok, fg_hwnd, fg_title, fg_pid = operator_foreground_ok(
            self.root,
            rec_top,
            rec_active,
        )
        snap["operator_foreground_ok"] = fg_ok
        snap["foreground_hwnd"] = fg_hwnd
        snap["foreground_title"] = fg_title
        snap["foreground_pid"] = fg_pid
        try:
            snap["focus_widget"] = repr(self.root.focus_get())
        except tk.TclError:
            snap["focus_widget"] = "?"
        snap["believes_keyboard_focus"] = self._focus_keyboard_seems_on_app()
        snap["black_screen"] = {
            "active": self.black_screen_active,
            "cover_visible": self.black_screen_cover_visible,
        }
        snap["replay"] = {
            "phase": self.replay.phase.name,
            "replay_video_active": self.replay.replay_video_active,
            "showing_replay": self.replay.showing_replay,
            "transitioning": self.replay.is_transitioning,
        }
        snap["screensaver_active"] = self.screensaver.is_active()
        snap["recording_overlay"] = {
            "state": ro.state.name,
            "ui_active": rec_active,
        }
        snap["focus_reclaim_eligible"] = self._focus_reclaim_eligible()
        return snap

    def _heartbeat_compact_dict(self) -> dict[str, Any]:
        root_ok = self._root_exists_best_effort()
        mapped = 0
        state = "?"
        viewable = False
        if root_ok:
            fallback_logged = False
            try:
                mapped = int(self.root.winfo_viewable())
                fallback_logged = True
            except Exception:
                mapped = 0
            if fallback_logged:
                _LOG.info("heartbeat_fallback_used winfo_viewable")
            try:
                state = self.root.state()
            except tk.TclError:
                state = "?"
            try:
                viewable = bool(self.root.winfo_viewable())
            except tk.TclError:
                viewable = False
        ro = self.recording_overlay
        rec_active = ro.is_ui_active()
        fg_ok, _, fg_title, fg_pid = operator_foreground_ok(
            self.root,
            ro.recording_toplevel(),
            rec_active,
        )
        try:
            focus_w = repr(self.root.focus_get())
        except tk.TclError:
            focus_w = "?"
        return {
            "pid": os.getpid(),
            "root_exists": root_ok,
            "mapped": mapped,
            "root_state": state,
            "viewable": viewable,
            "black_screen": self.black_screen_active,
            "replay_phase": self.replay.phase.name,
            "rec_ui": rec_active,
            "screensaver": self.screensaver.is_active(),
            "focus_widget": focus_w,
            "fg_title": fg_title,
            "fg_pid": fg_pid,
            "operator_fg_ok": fg_ok,
            "believes_focus": self._focus_keyboard_seems_on_app(),
        }

    def _on_recording_ui_visibility(self, visible: bool) -> None:
        self._encoder_status_overlay.set_recording_overlay_covers(visible)
        event = "recording_overlay_visible" if visible else "recording_overlay_hidden"
        snap = self._diagnostic_ui_snapshot()
        _LOG.info("UI_transition %s snapshot=%s", event, snap)
        if visible:
            fg_ok, _, fg_title, fg_pid = operator_foreground_ok(
                self.root,
                self.recording_overlay.recording_toplevel(),
                True,
            )
            if not fg_ok:
                _LOG.warning(
                    "recording_overlay_visible_not_operator_foreground "
                    "fg_title=%r fg_pid=%s snapshot=%s",
                    fg_title,
                    fg_pid,
                    snap,
                )

    def _on_screensaver_stopped(self) -> None:
        _LOG.info(
            "UI_transition screensaver_off snapshot=%s",
            self._diagnostic_ui_snapshot(),
        )
        self.rearm_focus_watchdog_after_transition("screensaver_stopped")

    def _schedule_operator_ui_heartbeat(self) -> None:
        self.scheduler.cancel(self._operator_ui_heartbeat_job)
        self._operator_ui_heartbeat_job = None
        if self._closing:
            return
        self._operator_ui_heartbeat_job = self.scheduler.schedule(
            _OPERATOR_UI_HEARTBEAT_MS,
            self._operator_ui_heartbeat_tick,
            name="operator_ui_heartbeat",
            background_resilience=True,
        )

    def _operator_ui_heartbeat_tick(self) -> None:
        self._operator_ui_heartbeat_job = None
        if self._closing:
            return
        try:
            try:
                h = self._heartbeat_compact_dict()
                _LOG.info(
                    "operator_ui_heartbeat pid=%s root_exists=%s mapped=%s root_state=%s viewable=%s "
                    "black_screen=%s replay_phase=%s rec_ui=%s screensaver=%s "
                    "focus_widget=%s fg_title=%r fg_pid=%s operator_fg_ok=%s believes_focus=%s",
                    h["pid"],
                    h["root_exists"],
                    h["mapped"],
                    h["root_state"],
                    h["viewable"],
                    h["black_screen"],
                    h["replay_phase"],
                    h["rec_ui"],
                    h["screensaver"],
                    h["focus_widget"],
                    h["fg_title"],
                    h["fg_pid"],
                    h["operator_fg_ok"],
                    h["believes_focus"],
                )
                self._operator_heartbeat_stuck_checks(h)
            except Exception:
                _LOG.exception("operator_ui_heartbeat failed")
        except Exception:
            _LOG.exception("operator_ui_heartbeat outer failed")
        self._schedule_operator_ui_heartbeat()

    def _operator_heartbeat_stuck_checks(self, h: dict[str, Any]) -> None:
        now = time.monotonic()
        fg_ok = bool(h["operator_fg_ok"])
        rec_ui = bool(h["rec_ui"])
        black = self.black_screen_active
        replay_vid = self.replay.replay_video_active
        eligible = self._focus_reclaim_eligible()

        if rec_ui and not self._heartbeat_prev_rec_ui and not fg_ok:
            _LOG.warning(
                "UI_transition recording_overlay_became_visible_not_foreground snapshot=%s",
                self._diagnostic_ui_snapshot(),
            )
        self._heartbeat_prev_rec_ui = rec_ui

        if rec_ui and not fg_ok:
            if now - self._last_rec_overlay_fg_warn_mono >= _REC_OVERLAY_NOT_FG_WARN_COOLDOWN_SEC:
                self._last_rec_overlay_fg_warn_mono = now
                _LOG.warning(
                    "operator_visibility: recording_ui active without operator foreground %s",
                    h,
                )

        if black or replay_vid or not eligible or self._closing:
            self._operator_not_fg_since_mono = None
            return

        if fg_ok:
            self._operator_not_fg_since_mono = None
            return

        if self._operator_not_fg_since_mono is None:
            self._operator_not_fg_since_mono = now
        stuck_sec = now - self._operator_not_fg_since_mono
        if stuck_sec < _OPERATOR_FG_STUCK_SEC:
            return
        if now - self._last_operator_fg_stuck_warn_mono < _OPERATOR_FG_STUCK_WARN_COOLDOWN_SEC:
            return
        self._last_operator_fg_stuck_warn_mono = now
        post_black = ""
        if self._last_black_screen_off_mono is not None:
            dt = now - self._last_black_screen_off_mono
            if dt < 180.0:
                post_black = f" seconds_since_black_screen_off={dt:.0f}"
        _LOG.warning(
            "operator_visibility: eligible reclaim but not operator-foreground for %.0fs "
                    "(UI likely behind another window; focus may not reach scoreboard)%s snapshot=%s",
            stuck_sec,
            post_black,
            self._diagnostic_ui_snapshot(),
        )

    def _recover_after_black_screen_off(self, *, event: str) -> None:
        self._last_black_screen_off_mono = time.monotonic()
        snap = self._diagnostic_ui_snapshot()
        _LOG.info("UI_transition %s pre_recover snapshot=%s", event, snap)
        try:
            if not self.replay.replay_video_active:
                self.claim_keyboard_focus(
                    reason=f"{event}_recover",
                    topmost_hold_ms=400,
                )
        except Exception:
            _LOG.exception("Focus reclaim after %s failed", event)
        post = self._diagnostic_ui_snapshot()
        fg_ok = post.get("operator_foreground_ok")
        focus_ok = post.get("believes_keyboard_focus")
        _LOG.info(
            "UI_transition %s post_recover operator_fg_ok=%s believes_keyboard_focus=%s snapshot=%s",
            event,
            fg_ok,
            focus_ok,
            post,
        )
        self.rearm_focus_watchdog_after_transition(event)

    def _schedule_encoder_recording_poll(self) -> None:
        self.scheduler.cancel(self._encoder_recording_poll_job)
        self._encoder_recording_poll_job = None
        if not self.settings.recording_encoder_sync_enabled:
            return
        self._encoder_recording_poll_job = self.scheduler.schedule(
            self.settings.recording_encoder_poll_ms,
            self._encoder_recording_poll_tick,
            name="encoder_recording_poll",
        )

    def _encoder_recording_poll_tick(self) -> None:
        self._encoder_recording_poll_job = None
        if not self.settings.recording_encoder_sync_enabled or self._closing:
            return

        path = Path(self.settings.encoder_state_path)
        snap = load_encoder_recording_snapshot(
            path,
            self.settings.encoder_status_stale_seconds,
            self._encoder_recording_prev_seq,
        )

        if not snap.usable:
            self._schedule_encoder_recording_poll()
            return

        if snap.session_seq is not None:
            self._encoder_recording_prev_seq = snap.session_seq

        capturing = snap.capturing
        was_enc = self._encoder_sync_believes_recording

        if capturing and not was_enc:
            ro = self.recording_overlay
            if ro.state != RecordingOverlayState.COUNTING:
                if ro.can_start_countdown_from_hotkey():
                    _LOG.info(
                        "Recording overlay: countdown started (encoder capture active; %s)",
                        path,
                    )
                    ro.start_or_restart_countdown()
            self._encoder_sync_believes_recording = True
        elif not capturing and was_enc:
            _LOG.info(
                "Recording overlay: encoder idle — hiding in-progress timer if shown (%s)",
                path,
            )
            self.recording_overlay.dismiss_from_encoder_idle()
            self._encoder_sync_believes_recording = False
        else:
            self._encoder_sync_believes_recording = capturing

        self._schedule_encoder_recording_poll()

    def _apply_hidden_cursor(self) -> None:
        """Hide the mouse pointer over the scoreboard (kiosk-style)."""
        cursor = "none"
        try:
            self.root.option_add("*cursor", cursor)
            self.root.configure(cursor=cursor)
        except tk.TclError:
            _LOG.warning(
                "Could not set cursor=%r (invisible pointer may be unsupported); "
                "using system default",
                cursor,
                exc_info=True,
            )
            return
        for w in (self.canvas, self.video_host, self.black_screen_frame):
            try:
                w.configure(cursor=cursor)
            except tk.TclError:
                _LOG.debug("cursor=%r skipped for widget", cursor, exc_info=True)
        if self._obs_status_win is not None:
            try:
                self._obs_status_win.configure(cursor=cursor)
            except tk.TclError:
                _LOG.debug("cursor=%r skipped for obs status", cursor, exc_info=True)
        self.recording_overlay.apply_hidden_cursor()

    def _setup_obs_status_indicator(self) -> None:
        if not self.settings.obs_status_indicator_enabled:
            return

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            _LOG.debug("obs status: topmost unsupported", exc_info=True)
        try:
            win.transient(self.root)
        except tk.TclError:
            _LOG.debug("obs status: transient failed", exc_info=True)
        win.configure(bg="#0d0d0d", highlightthickness=0, cursor="none")

        fz = max(11, min(18, int(self.screen_height * 0.026)))
        inner = tk.Frame(
            win,
            bg="#3d1818",
            highlightthickness=1,
            highlightbackground="#5a2d2d",
        )
        inner.pack(fill="both", expand=True)
        lbl = tk.Label(
            inner,
            text="VIDEO RECORDER UNAVAILABLE",
            font=("Segoe UI", fz, "bold"),
            fg="#ffecec",
            bg="#3d1818",
            padx=16,
            pady=10,
        )
        lbl.pack()

        win.update_idletasks()
        w = max(1, win.winfo_reqwidth())
        h = max(1, win.winfo_reqheight())
        x = 12
        y = max(0, self.screen_height - h - 12)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.deiconify()

        self._obs_status_win = win
        self._obs_status_inner = inner
        self._obs_status_label = lbl

        self._obs_status_poll_after = self.scheduler.schedule(
            300,
            self._obs_status_poll_tick,
            name="obs_status_poll_initial",
        )

    def _apply_obs_status_ready(self, ready: bool) -> None:
        if self._obs_status_label is None or self._obs_status_inner is None:
            return
        if ready:
            bg = "#163a24"
            fg = "#e8ffee"
            hi = "#2d5a3d"
            text = "VIDEO RECORDER READY"
        else:
            bg = "#3d1818"
            fg = "#ffecec"
            hi = "#5a2d2d"
            text = "VIDEO RECORDER UNAVAILABLE"
        self._obs_status_inner.configure(bg=bg, highlightbackground=hi)
        self._obs_status_label.configure(text=text, bg=bg, fg=fg)

    def _obs_status_poll_worker(self) -> None:
        try:
            ready = probe_obs_video_recorder_ready(self.settings)
        except Exception:
            _LOG.debug("OBS status poll failed", exc_info=True)
            ready = False
        self.scheduler.schedule(
            0,
            lambda r=ready: self._obs_status_poll_done(r),
            name="obs_status_poll_done",
        )

    def _obs_status_poll_done(self, ready: bool) -> None:
        self._obs_status_poll_busy = False
        if self._obs_status_win is None:
            return
        self._apply_obs_status_ready(ready)
        self._schedule_obs_status_poll_after()

    def _schedule_obs_status_poll_after(self) -> None:
        if self._obs_status_win is None:
            return
        self.scheduler.cancel(self._obs_status_poll_after)
        self._obs_status_poll_after = None
        ms = self._read_runtime_safe_settings().obs_status_poll_interval_ms
        self._obs_status_poll_after = self.scheduler.schedule(
            ms,
            self._obs_status_poll_tick,
            name="obs_status_poll_tick",
        )

    def _obs_status_poll_tick(self) -> None:
        self._obs_status_poll_after = None
        if self._obs_status_win is None:
            return
        if self._obs_status_poll_busy:
            self._schedule_obs_status_poll_after()
            return
        self._obs_status_poll_busy = True
        threading.Thread(target=self._obs_status_poll_worker, daemon=True).start()

    def _teardown_obs_status_indicator(self) -> None:
        self.scheduler.cancel(self._obs_status_poll_after)
        self._obs_status_poll_after = None
        if self._obs_status_win is not None:
            try:
                self._obs_status_win.destroy()
            except tk.TclError:
                pass
        self._obs_status_win = None
        self._obs_status_inner = None
        self._obs_status_label = None

    def _bind_keys(self) -> None:
        """Keyboard: local emergency exit only. Operator controls use the command file bus."""
        self.root.bind_all(
            "<Escape>",
            lambda e: self.scheduler.schedule(0, self.close_app, name="escape_close_app"),
        )

    def _command_obs_restart(self) -> None:
        if self.screensaver.is_active():
            self.screensaver.stop()
        if not self.settings.obs_restart_chord_enabled:
            _LOG.info("obs_restart command ignored (OBS_RESTART_CHORD_ENABLED=0)")
            return
        now = time.monotonic()
        if now - self._obs_restart_last_mono < _OBS_RESTART_COOLDOWN_SEC:
            _LOG.debug("obs_restart command ignored (cooldown)")
            return
        self._obs_restart_last_mono = now
        self._trigger_obs_restart_chord()

    def _trigger_obs_restart_chord(self) -> None:
        self.last_input_ms = int(time.monotonic() * 1000)
        if self.screensaver.is_active():
            self.screensaver.stop()
        _LOG.info("OBS restart: background pipeline scheduled")
        threading.Thread(target=self._obs_restart_worker, daemon=True).start()

    def _obs_restart_worker(self) -> None:
        from scoreboard.obs_restart import restart_obs_pipeline

        try:
            ok, msg = restart_obs_pipeline(self.settings)
        except Exception:
            _LOG.exception("OBS restart pipeline failed")
            return
        if ok:
            _LOG.info("OBS restart finished: %s", msg)
        else:
            _LOG.warning("OBS restart finished: %s", msg)

    @property
    def score_a(self) -> int:
        return self._score_state.score_a

    @score_a.setter
    def score_a(self, v: int) -> None:
        self._score_state.score_a = v

    @property
    def score_b(self) -> int:
        return self._score_state.score_b

    @score_b.setter
    def score_b(self, v: int) -> None:
        self._score_state.score_b = v

    def _after_replay_fade_out(self) -> None:
        if self.black_screen_active:
            self._show_black_screen_cover()

        def _replay_fade_out_focus() -> None:
            if (
                not self.black_screen_active
                and not self.replay.replay_video_active
                and self._focus_reclaim_eligible()
            ):
                self.claim_keyboard_focus(
                    reason="replay_fade_out_recover",
                    topmost_hold_ms=250,
                )
            _LOG.info(
                "UI_transition replay_fade_out snapshot=%s",
                self._diagnostic_ui_snapshot(),
            )
            self.rearm_focus_watchdog_after_transition("replay_fade_out")

        self.scheduler.schedule(
            80,
            _replay_fade_out_focus,
            name="replay_fade_out_focus_rearm",
        )

    def on_streamdeck_input(self, action: Callable[[], None]) -> None:
        """Schedule an operator action on the Tk thread (used by command bus and UI buttons)."""
        self.scheduler.schedule(
            0,
            lambda a=action: self._run_streamdeck_action(a),
            name="streamdeck_action",
        )

    def _run_streamdeck_action(self, action: Callable[[], None]) -> None:
        self.last_input_ms = int(time.monotonic() * 1000)

        if self.screensaver.is_active():
            self.screensaver.stop()
            return

        action()

    def on_recording_start_hotkey(self) -> None:
        if not self.recording_overlay.can_start_countdown_from_hotkey():
            return
        if self.settings.recording_obs_health_check:
            if self._recording_obs_check_in_flight:
                _LOG.debug(
                    "Recording OBS check already running; ignoring duplicate recording_start",
                )
                return
            self._recording_obs_check_in_flight = True
            threading.Thread(
                target=self._recording_start_obs_check_worker,
                daemon=True,
            ).start()
        else:
            self.recording_overlay.start_or_restart_countdown()

    def _recording_start_obs_check_worker(self) -> None:
        try:
            ok, msg = check_obs_recording_gate(self.settings)
        except Exception:
            _LOG.exception("OBS recording gate failed unexpectedly")
            ok, msg = False, "Could not verify OBS (unexpected error); see logs."
        self.scheduler.schedule(
            0,
            lambda o=ok, m=msg: self._on_recording_obs_check_done(o, m),
            name="recording_obs_gate_done",
        )

    def _on_recording_obs_check_done(self, ok: bool, msg: str) -> None:
        self._recording_obs_check_in_flight = False
        if ok:
            if not self.recording_overlay.can_start_countdown_from_hotkey():
                return
            self.recording_overlay.start_or_restart_countdown()
            self._apply_obs_status_ready(True)
            return
        _LOG.warning("Recording overlay not started: %s", msg)
        self._apply_obs_status_ready(False)
        if not self.settings.recording_obs_health_fail_closed:
            if not self.recording_overlay.can_start_countdown_from_hotkey():
                return
            _LOG.warning("OBS gate failed; fail-open enabled, starting timer anyway")
            self.recording_overlay.start_or_restart_countdown()
            return
        self.replay.show_replay_unavailable_graphic_overlay()

    def _on_recording_dismiss_chord(self, _event: tk.Event | None = None) -> None:
        """Dismiss chord: do not let screensaver-only short-circuit skip dismiss."""
        self.scheduler.schedule(
            0,
            self._recording_dismiss_deferred,
            name="recording_dismiss_deferred",
        )

    def _recording_dismiss_deferred(self) -> None:
        self.last_input_ms = int(time.monotonic() * 1000)
        if self.screensaver.is_active():
            self.screensaver.stop()
        self.on_recording_dismiss_hotkey()

    def on_recording_dismiss_hotkey(self) -> None:
        if not self.recording_overlay.can_dismiss_from_operator_hotkey():
            return
        self.recording_overlay.dismiss_from_operator_hotkey()

    def _show_black_screen_cover(self) -> None:
        if self.black_screen_cover_visible:
            return
        self.black_screen_frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.black_screen_frame.lift()
        self.black_screen_cover_visible = True
        self.recording_overlay.lift()

    def _hide_black_screen_cover(self) -> None:
        if not self.black_screen_cover_visible:
            return
        self.black_screen_frame.place_forget()
        self.black_screen_cover_visible = False

    def toggle_black_screen(self) -> None:
        if self.replay.blocks_black_screen_toggle():
            _LOG.info(
                "Black screen toggle ignored (replay busy transitioning=%s video=%s showing=%s)",
                self.replay.is_transitioning,
                self.replay.replay_video_active,
                self.replay.showing_replay,
            )
            return
        self.black_screen_active = not self.black_screen_active
        if self.black_screen_active:
            self._show_black_screen_cover()
            _LOG.info(
                "UI_transition black_screen_on snapshot=%s",
                self._diagnostic_ui_snapshot(),
            )
        else:
            self._hide_black_screen_cover()
            self._recover_after_black_screen_off(event="black_screen_off")
        self.recording_overlay.lift()

    def schedule_claim_focus(self) -> None:
        for jid in self._focus_claim_jobs:
            self.scheduler.cancel(jid)
        self._focus_claim_jobs.clear()
        for delay_ms in (0, 50, 150, 400, 800, 1500, 3000, 6000, 12000, 20000):
            jid = self.scheduler.schedule(
                delay_ms,
                lambda ms=delay_ms: self.claim_keyboard_focus(
                    reason=f"startup_claim_{ms}ms",
                ),
                name=f"focus_claim_{delay_ms}ms",
            )
            self._focus_claim_jobs.append(jid)

    def rearm_focus_watchdog_after_transition(self, event: str) -> None:
        """Extend pilot protection: full watchdog duration + startup-style claim burst."""
        approx_s = (
            self.settings.focus_watchdog_ticks
            * self.settings.focus_watchdog_interval_ms
            // 1000
        )
        _LOG.info(
            "Focus: re-arming watchdog after %s (~%s s of periodic reclaim, interval %sms)",
            event,
            approx_s,
            self.settings.focus_watchdog_interval_ms,
        )
        self.start_focus_watchdog()
        self.schedule_claim_focus()

    def _focus_keyboard_seems_on_app(self) -> bool:
        w = self.root.focus_get()
        if w is None:
            return False
        try:
            top = w.winfo_toplevel()
        except tk.TclError:
            return False
        if top == self.root:
            return True
        rec = self.recording_overlay.recording_toplevel()
        return rec is not None and top == rec

    def _focus_reclaim_eligible(self) -> bool:
        """Whether periodic / automatic reclaim should run (centralized guard)."""
        if not self._app_is_alive():
            return False
        if self.replay.replay_video_active:
            return False
        if self.black_screen_active:
            return False
        if self.replay.blocks_idle():
            return False
        if self.recording_overlay.is_ended_message_showing():
            return False
        return True

    def claim_keyboard_focus(
        self,
        *,
        reason: str = "unspecified",
        topmost_hold_ms: int | None = None,
    ) -> None:
        if not self._focus_reclaim_eligible():
            _LOG.debug("Focus reclaim skipped (reason=%s): ineligible context", reason)
            return

        used_win32 = os.name == "nt" and not self.recording_overlay.is_ui_active()
        topmost_ms = 150 if topmost_hold_ms is None else max(50, int(topmost_hold_ms))

        try:
            self.root.update_idletasks()
            self.root.lift()
            # Root topmost on/off makes a transient recording Toplevel flicker on Windows.
            # While the recording box is up, keep the root out of that dance; overlay stays topmost.
            if not self.recording_overlay.is_ui_active():
                self.root.attributes("-topmost", True)
                self.scheduler.cancel(self._release_topmost_job)
                self._release_topmost_job = self.scheduler.schedule(
                    topmost_ms,
                    self._release_topmost_brief,
                    name="focus_release_topmost",
                )
        except tk.TclError:
            _LOG.debug("claim_keyboard_focus: lift/topmost failed", exc_info=True)

        if used_win32:
            try:
                hwnd = int(self.root.winfo_id())
                win32_force_foreground(hwnd)
            except (tk.TclError, ValueError, TypeError):
                _LOG.debug("Focus reclaim: win32_force_foreground skipped", exc_info=True)

        try:
            self.root.focus_force()
            self.root.focus_set()
            self.canvas.focus_set()
            self.canvas.focus_force()
        except tk.TclError:
            _LOG.debug("claim_keyboard_focus: focus_set failed", exc_info=True)

        focus_ok = self._focus_keyboard_seems_on_app()
        ro = self.recording_overlay
        op_fg_ok, _, fg_title, fg_pid = operator_foreground_ok(
            self.root,
            ro.recording_toplevel(),
            ro.is_ui_active(),
        )
        if focus_ok:
            self._focus_reclaim_fail_streak = 0
        else:
            self._focus_reclaim_fail_streak += 1
            if self._focus_reclaim_fail_streak >= _FOCUS_RECLAIM_FAIL_DIAG_THRESHOLD:
                _LOG.warning(
                    "Focus reclaim: %s consecutive failures (operator control may be dead); snapshot next",
                    self._focus_reclaim_fail_streak,
                )
                _LOG.info(
                    "focus_reclaim_repeated_fail snapshot=%s",
                    self._diagnostic_ui_snapshot(),
                )
                self._focus_reclaim_fail_streak = 0

        recover_reason = (
            reason.endswith("_recover")
            or reason == "replay_fade_out_recover"
            or reason.startswith("black_screen")
        )
        if reason.startswith("after_synthetic_click"):
            lvl = logging.INFO
        elif reason == "watchdog":
            if not focus_ok:
                now_mono = time.monotonic()
                if (
                    now_mono - self._last_watchdog_focus_fail_info_mono
                    >= _FOCUS_WATCHDOG_FAIL_INFO_COOLDOWN_SEC
                ):
                    self._last_watchdog_focus_fail_info_mono = now_mono
                    lvl = logging.INFO
                else:
                    lvl = logging.DEBUG
            else:
                lvl = logging.DEBUG
        elif recover_reason:
            lvl = logging.INFO
        else:
            lvl = logging.DEBUG
        _LOG.log(
            lvl,
            "Focus reclaim: reason=%s win32_foreground=%s topmost_ms=%s "
            "focus_ok=%s operator_fg_ok=%s fg_title=%r fg_pid=%s focus_widget=%r",
            reason,
            used_win32,
            topmost_ms,
            focus_ok,
            op_fg_ok,
            fg_title,
            fg_pid,
            self.root.focus_get(),
        )

    def _release_topmost_brief(self) -> None:
        self._release_topmost_job = None
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            _LOG.debug("release topmost failed", exc_info=True)

    def start_focus_watchdog(self) -> None:
        self.cancel_focus_watchdog()
        self.focus_watchdog_ticks_left = self.settings.focus_watchdog_ticks
        self._focus_watchdog_job = self.scheduler.schedule(
            self.settings.focus_watchdog_interval_ms,
            self.focus_watchdog_tick,
            name="focus_watchdog",
            background_resilience=True,
        )
        self._focus_watchdog_exhausted_logged = False

    def cancel_focus_watchdog(self) -> None:
        self.scheduler.cancel(self._focus_watchdog_job)
        self._focus_watchdog_job = None

    def focus_watchdog_tick(self) -> None:
        self._focus_watchdog_job = None

        if self.focus_watchdog_ticks_left <= 0:
            if not self._focus_watchdog_exhausted_logged:
                self._focus_watchdog_exhausted_logged = True
                _LOG.info(
                    "Focus watchdog: initial reclaim phase finished after %s ticks "
                    "(no further periodic focus reclaim; manual input / restarts still apply)",
                    self.settings.focus_watchdog_ticks,
                )
            return

        self.focus_watchdog_ticks_left -= 1

        if self._focus_reclaim_eligible():
            self.claim_keyboard_focus(reason="watchdog")

        self._focus_watchdog_job = self.scheduler.schedule(
            self.settings.focus_watchdog_interval_ms,
            self.focus_watchdog_tick,
            name="focus_watchdog",
            background_resilience=True,
        )

    def schedule_synthetic_focus_clicks(self) -> None:
        if not self.settings.synthetic_focus_click:
            return
        for jid in self._synthetic_click_jobs:
            self.scheduler.cancel(jid)
        self._synthetic_click_jobs.clear()
        for delay_ms in (2500, 6000, 12000):
            jid = self.scheduler.schedule(
                delay_ms,
                self.try_synthetic_focus_click,
                name="synthetic_focus_click",
                background_resilience=True,
            )
            self._synthetic_click_jobs.append(jid)

    def try_synthetic_focus_click(self) -> None:
        if not self.settings.synthetic_focus_click:
            return
        if not self._focus_reclaim_eligible():
            return

        if self._synthetic_click_attempts >= 3:
            return

        self._synthetic_click_attempts += 1

        try:
            hwnd = int(self.root.winfo_id())
            if os.name == "nt":
                win32_force_foreground(hwnd)
            win32_synthetic_click_window_center(hwnd)
            _LOG.info(
                "Focus: synthetic click attempt %s/3 (hwnd=%s); follow-up reclaim",
                self._synthetic_click_attempts,
                hwnd,
            )
            self.claim_keyboard_focus(
                reason=f"after_synthetic_click_{self._synthetic_click_attempts}",
            )
        except (tk.TclError, ValueError, TypeError):
            _LOG.debug("Synthetic focus click failed", exc_info=True)

    def close_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        _LOG.info("Application shutdown requested")
        self._obs_status_poll_busy = False
        self._recording_obs_check_in_flight = False
        self._teardown_obs_status_indicator()
        for jid in self._focus_claim_jobs:
            self.scheduler.cancel(jid)
        self._focus_claim_jobs.clear()
        for jid in self._synthetic_click_jobs:
            self.scheduler.cancel(jid)
        self._synthetic_click_jobs.clear()
        self.scheduler.cancel(self._release_topmost_job)
        self._release_topmost_job = None
        self.scheduler.cancel(self._encoder_recording_poll_job)
        self._encoder_recording_poll_job = None

        self.screensaver.teardown()
        self._encoder_status_overlay.teardown()
        self._replay_buffer_loading.teardown()
        self.replay.teardown()
        self.cancel_focus_watchdog()
        self.scheduler.cancel(self._idle_check_job)
        self._idle_check_job = None
        self.recording_overlay.teardown()
        self.scheduler.cancel(self._heartbeat_job)
        self._heartbeat_job = None
        self.scheduler.cancel(self._operator_ui_heartbeat_job)
        self._operator_ui_heartbeat_job = None
        self.scheduler.cancel_all_tracked()
        self._publish_launcher_status()
        self.root.destroy()

    def schedule_idle_check(self) -> None:
        self.scheduler.cancel(self._idle_check_job)
        self._idle_check_job = self.scheduler.schedule(
            5000,
            self.check_idle_timeout,
            name="idle_timeout_check",
            background_resilience=True,
        )

    def check_idle_timeout(self) -> None:
        self._idle_check_job = None

        now_ms = int(time.monotonic() * 1000)
        idle_ms = now_ms - self.last_input_ms

        if (
            self.settings.slideshow_enabled
            and not self.screensaver.is_active()
            and not self.replay.blocks_idle()
            and not self.recording_overlay.is_ui_active()
            and not self.black_screen_active
            and idle_ms >= self.settings.idle_timeout_ms
        ):
            self.screensaver.start()
            _LOG.info(
                "UI_transition screensaver_on snapshot=%s",
                self._diagnostic_ui_snapshot(),
            )

        self.schedule_idle_check()

    def _schedule_heartbeat(self) -> None:
        self.scheduler.cancel(self._heartbeat_job)
        self._heartbeat_job = None
        n = self.settings.heartbeat_interval_minutes
        if n <= 0:
            return
        ms = n * 60 * 1000
        self._heartbeat_job = self.scheduler.schedule(
            ms,
            self._heartbeat_tick,
            name="pilot_heartbeat",
            background_resilience=True,
        )

    def _heartbeat_tick(self) -> None:
        self._heartbeat_job = None
        try:
            _LOG.info(
                "heartbeat alive replay_phase=%s replay_video=%s screensaver=%s "
                "recording_ui=%s black_screen=%s",
                self.replay.phase.name,
                self.replay.replay_video_active,
                self.screensaver.is_active(),
                self.recording_overlay.is_ui_active(),
                self.black_screen_active,
            )
        except Exception:
            _LOG.exception("heartbeat logging failed")
        self._schedule_heartbeat()

    def create_scaled_text(self, x: int, y: int, text: str, color: str):
        item = self.canvas.create_text(
            x,
            y,
            text=text,
            fill=color,
            font=("Arial", self.font_size, "bold"),
            tags="score",
        )
        self.canvas.scale(item, x, y, self.squeeze_x, 1.0)
        return item

    def draw_text_with_effects(self, x: int, y: int, text: str):
        items = []

        shadow_offset = int(self.font_size * 0.03)
        outline_offset = int(self.font_size * 0.015)

        items.append(
            self.create_scaled_text(
                x + shadow_offset,
                y + shadow_offset,
                text,
                "#000000",
            )
        )

        for dx in [-outline_offset, 0, outline_offset]:
            for dy in [-outline_offset, 0, outline_offset]:
                if dx == 0 and dy == 0:
                    continue
                items.append(
                    self.create_scaled_text(
                        x + dx,
                        y + dy,
                        text,
                        "#000000",
                    )
                )

        items.append(
            self.create_scaled_text(
                x,
                y,
                text,
                "#FFFFFF",
            )
        )

        return items

    def _sync_canvas_aux_overlays(self) -> None:
        """Keep encoder + replay-buffer canvas strips above the transparent overlay."""
        self._encoder_status_overlay.sync_canvas_stack()
        self._replay_buffer_loading.sync_canvas_stack()

    def draw_scores(self) -> None:
        self.canvas.delete("score")

        self.score_a_items = self.draw_text_with_effects(
            self.left_x, self.center_y, str(self.score_a)
        )
        self.score_b_items = self.draw_text_with_effects(
            self.right_x, self.center_y, str(self.score_b)
        )

        self.canvas.tag_raise(self.overlay_canvas)
        self._sync_canvas_aux_overlays()
        self.recording_overlay.lift()

    def update_score(self, team: str, delta: int) -> None:
        if self.black_screen_active:
            return
        if self.replay.blocks_score_updates():
            return

        if team == "a":
            self.score_a = max(0, min(99, self.score_a + delta))
        else:
            self.score_b = max(0, min(99, self.score_b + delta))

        self.draw_scores()
        self.save_state()

    def reset_scores(self) -> None:
        if self.replay.blocks_score_updates():
            return

        if self.black_screen_active:
            self.black_screen_active = False
            self._hide_black_screen_cover()
            self.recording_overlay.lift()
            self._recover_after_black_screen_off(event="black_screen_off_reset")

        self.score_a = 0
        self.score_b = 0
        self.draw_scores()
        self.save_state()

    def toggle_replay(self) -> None:
        if self.replay.dismiss_replay_unavailable_overlay() and not self.replay.showing_replay:
            return
        if not self.settings.replay_enabled:
            _LOG.info("Replay toggle ignored: REPLAY_ENABLED=0")
            return
        self.screensaver.stop()
        _LOG.info(
            "UI_transition replay_toggle snapshot=%s",
            self._diagnostic_ui_snapshot(),
        )
        self.replay.toggle_replay()

    def start_replay_buffer_loading_overlay(self) -> None:
        self._replay_buffer_loading.start_sequence()

    def ensure_window_opaque(self) -> None:
        try:
            self.root.attributes("-alpha", 1.0)
        except tk.TclError:
            _LOG.debug("ensure_window_opaque failed", exc_info=True)

    def save_state(self) -> None:
        save_scores(self.settings.state_file, self._score_state)
