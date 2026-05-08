"""Lower-left encoder status from encoder_state.json (canvas; same stacking pattern as replay buffer strip)."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageTk

from scoreboard.config.settings import Settings
from scoreboard.scheduler import AfterScheduler

_LOG = logging.getLogger(__name__)

_POLL_JOB = "encoder_status_poll"
_CANVAS_TAG = "encoder_status"

# States that mean the appliance is down regardless of other flags (encoder schema v1).
_UNAVAILABLE_STATES = frozenset(
    {
        "shutting_down",
        "error",
        "fatal",
        "stopped",
        "unavailable",
        "offline",
        "crashed",
    }
)
_LEGACY_READY_STATES = frozenset({"ready", "recording", "idle"})
_BOOL_READY_KEYS = (
    "encoder_ready",
    "long_recording_available",
    "rolling_buffer_applicable",
)


def _try_read_encoder_appliance_ready_once(
    settings: Settings,
) -> tuple[bool, str | None]:
    """Single read attempt. Returns (True, None) or (False, short reason for operators/logs)."""
    path = Path(settings.encoder_state_path)
    if not path.is_file():
        return False, f"no_file:{path}"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except OSError as e:
        return False, f"os_error:{e}"
    except (UnicodeError, json.JSONDecodeError) as e:
        return False, f"json_error:{e}"
    if not isinstance(data, dict):
        return False, "payload_not_object"
    if _is_payload_stale(data.get("updated_at"), settings.encoder_status_stale_seconds):
        return (
            False,
            f"stale:updated_at={data.get('updated_at')!r} "
            f"threshold_sec={settings.encoder_status_stale_seconds}",
        )
    if not _payload_indicates_ready(data):
        st = str(data.get("state", "")).strip().lower()
        return False, f"not_ready:state={st!r} encoder_ready={data.get('encoder_ready')!r}"
    return True, None


def read_encoder_appliance_ready(settings: Settings) -> bool:
    """Same readiness rules as :class:`EncoderStatusOverlay` (encoder_state.json + stale window).

    Retries briefly: on Windows another process may be replacing the file atomically, and a
    single read can occasionally fail or race with the writer.
    """
    last_reason = "unknown"
    for attempt in range(3):
        ok, reason = _try_read_encoder_appliance_ready_once(settings)
        if ok:
            return True
        last_reason = reason or "unknown"
        if attempt < 2:
            time.sleep(0.02)
    _LOG.debug("encoder_appliance_ready false after retries: %s", last_reason)
    return False


def explain_encoder_appliance_ready(settings: Settings) -> tuple[bool, str]:
    """Diagnostic: one read, no retries — exact failure reason for scripts/support."""
    ok, reason = _try_read_encoder_appliance_ready_once(settings)
    if ok:
        return True, "ok"
    return False, reason or "unknown"


class EncoderStatusOverlay:
    def __init__(
        self,
        root: tk.Tk,
        settings: Settings,
        scheduler: AfterScheduler,
        canvas: tk.Canvas,
        overlay_item_id: int,
        screen_width: int,
        screen_height: int,
    ) -> None:
        self._root = root
        self._settings = settings
        self._scheduler = scheduler
        self._canvas = canvas
        self._overlay_item_id = overlay_item_id
        self._screen_w = screen_width
        self._screen_h = screen_height
        self._poll_job: str | None = None
        self._active = False
        self._photo_ready: ImageTk.PhotoImage | None = None
        self._photo_unavail: ImageTk.PhotoImage | None = None
        self._item_a: int | None = None
        self._item_b: int | None = None
        self._front_is_a = True
        self._last_shown_ready: bool | None = None
        self._hidden_for_recording = False
        self._poll_interval_ms = int(settings.encoder_status_poll_ms)

    @property
    def _margin(self) -> int:
        return max(0, self._settings.encoder_status_margin_px)

    def sync_canvas_stack(self) -> None:
        if self._item_a is None or self._hidden_for_recording:
            return
        try:
            self._canvas.tag_raise(_CANVAS_TAG, self._overlay_item_id)
        except tk.TclError:
            _LOG.debug("encoder status: tag_raise failed", exc_info=True)

    def set_recording_overlay_covers(self, covered: bool) -> None:
        """Hide encoder strip while the recording Toplevel is shown; restore when dismissed."""
        if covered == self._hidden_for_recording:
            return
        self._hidden_for_recording = covered
        if covered:
            self._hide_for_external_cover()
        else:
            self._restore_after_external_cover()

    def start(self) -> None:
        if not self._settings.encoder_status_enabled:
            return
        if not self._preload_images():
            _LOG.warning(
                "Encoder status overlay disabled (missing or unreadable PNGs): %s / %s",
                self._settings.encoder_status_ready_image,
                self._settings.encoder_status_unavailable_image,
            )
            return
        self._active = True
        self._schedule_poll()

    def teardown(self) -> None:
        self._active = False
        self._scheduler.cancel(self._poll_job)
        self._poll_job = None
        self._destroy_canvas_items()
        self._photo_ready = None
        self._photo_unavail = None
        self._last_shown_ready = None
        self._hidden_for_recording = False

    def _preload_images(self) -> bool:
        pr = _path_to_rgb_photo(self._settings.encoder_status_ready_image)
        pu = _path_to_rgb_photo(self._settings.encoder_status_unavailable_image)
        if pr is None or pu is None:
            return False
        self._photo_ready = pr
        self._photo_unavail = pu
        return True

    def _schedule_poll(self) -> None:
        if not self._active:
            return
        self._scheduler.cancel(self._poll_job)
        self._poll_job = self._scheduler.schedule(
            self._poll_interval_ms,
            self._poll_tick,
            name=_POLL_JOB,
        )

    def set_poll_interval_ms(self, value: int) -> None:
        self._poll_interval_ms = max(100, int(value))
        if self._active:
            self._schedule_poll()

    def _poll_tick(self) -> None:
        self._poll_job = None
        if not self._active:
            return
        try:
            want_ready = self._read_want_ready()
        except Exception:
            _LOG.debug("encoder status poll failed", exc_info=True)
            want_ready = False
        self._apply_if_changed(want_ready)
        self._schedule_poll()

    def _read_want_ready(self) -> bool:
        return read_encoder_appliance_ready(self._settings)

    def _apply_if_changed(self, want_ready: bool) -> None:
        if self._item_a is not None and self._last_shown_ready == want_ready:
            if not self._hidden_for_recording:
                self.sync_canvas_stack()
            return
        self._last_shown_ready = want_ready
        self._paint_mode(want_ready)
        if self._hidden_for_recording:
            self._hide_for_external_cover()

    def _hide_for_external_cover(self) -> None:
        if self._item_a is None or self._item_b is None:
            return
        try:
            self._canvas.itemconfig(self._item_a, state="hidden")
            self._canvas.itemconfig(self._item_b, state="hidden")
        except tk.TclError:
            _LOG.debug("encoder status: hide for recording failed", exc_info=True)

    def _restore_after_external_cover(self) -> None:
        if self._item_a is None or self._item_b is None:
            return
        try:
            if self._front_is_a:
                self._canvas.itemconfig(self._item_b, state="hidden")
                self._canvas.itemconfig(self._item_a, state="normal")
            else:
                self._canvas.itemconfig(self._item_a, state="hidden")
                self._canvas.itemconfig(self._item_b, state="normal")
            self.sync_canvas_stack()
        except tk.TclError:
            _LOG.debug("encoder status: restore after recording failed", exc_info=True)

    def _paint_mode(self, ready: bool) -> None:
        assert self._photo_ready is not None and self._photo_unavail is not None
        photo = self._photo_ready if ready else self._photo_unavail
        mx = self._margin
        sy = self._screen_h - self._margin

        if self._item_a is None:
            other = self._photo_unavail if ready else self._photo_ready
            self._item_a = self._canvas.create_image(
                mx,
                sy,
                anchor="sw",
                image=photo,
                tags=_CANVAS_TAG,
            )
            self._item_b = self._canvas.create_image(
                mx,
                sy,
                anchor="sw",
                image=other,
                tags=_CANVAS_TAG,
                state="hidden",
            )
            self._front_is_a = True
            if not self._hidden_for_recording:
                self.sync_canvas_stack()
            return

        try:
            if self._front_is_a:
                self._canvas.itemconfig(self._item_b, image=photo)
                self._canvas.itemconfig(self._item_a, state="hidden")
                self._canvas.itemconfig(self._item_b, state="normal")
                self._front_is_a = False
            else:
                self._canvas.itemconfig(self._item_a, image=photo)
                self._canvas.itemconfig(self._item_b, state="hidden")
                self._canvas.itemconfig(self._item_a, state="normal")
                self._front_is_a = True
            if not self._hidden_for_recording:
                self.sync_canvas_stack()
        except tk.TclError:
            _LOG.exception("encoder status: canvas update failed")

    def _destroy_canvas_items(self) -> None:
        self._item_a = None
        self._item_b = None
        try:
            self._canvas.delete(_CANVAS_TAG)
        except tk.TclError:
            pass


def _path_to_rgb_photo(path: str) -> ImageTk.PhotoImage | None:
    try:
        p = Path(path)
        if not p.is_file():
            return None
        with Image.open(p) as im:
            rgba = im.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, (0, 0, 0))
        rgb.paste(rgba, mask=rgba.split()[3])
        return ImageTk.PhotoImage(rgb)
    except OSError:
        return None


def _payload_indicates_ready(data: dict) -> bool:
    """Match encoder_state.json schema v1: booleans + state, with terminal states overriding."""
    state = str(data.get("state", "")).strip().lower()
    # Encoder publishes ``starting`` / ``restarting`` with all readiness booleans false on purpose;
    # still must not flash the unavailable graphic (see encoder.encoder_state module docstring).
    if state in ("starting", "restarting"):
        return True
    if state in _UNAVAILABLE_STATES:
        return False
    present_flags = [data[k] for k in _BOOL_READY_KEYS if k in data]
    if present_flags:
        if any(v is True for v in present_flags if isinstance(v, bool)):
            return True
        if all(isinstance(v, bool) for v in present_flags):
            return False
    return state in _LEGACY_READY_STATES


def _is_payload_stale(updated_at: object, stale_seconds: int) -> bool:
    if updated_at is None:
        return True
    s = str(updated_at).strip()
    if not s:
        return True
    try:
        ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age > float(stale_seconds)
    except ValueError:
        return True
