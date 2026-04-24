"""
Environment-driven settings for the UVC long-record operator.

Optional: copy .env.example to .env in this directory (or set variables in the system environment).
Values already set in the process environment are not overridden by .env.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


def load_dotenv_if_present() -> None:
    """Load ``.env`` from the encoder package directory, then from the current working directory."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    encoder_dir = Path(__file__).resolve().parent
    load_dotenv(encoder_dir / ".env")
    load_dotenv(Path.cwd() / ".env")


def _unified_settings_path() -> Path:
    encoder_dir = Path(__file__).resolve().parent
    root = encoder_dir.parent
    raw_path = os.environ.get("REPLAYTROVE_SETTINGS_FILE", "").strip()
    return Path(raw_path) if raw_path else root / "config" / "settings.json"


def _read_unified_settings_doc() -> dict | None:
    try:
        cfg_path = _unified_settings_path()
        if not cfg_path.is_file():
            return None
        doc = json.loads(cfg_path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _unified_ffmpeg_path_from_doc(doc: dict | None) -> str | None:
    if not doc:
        return None
    paths = doc.get("obsFfmpegPaths")
    if not isinstance(paths, dict):
        return None
    p = paths.get("ffmpegPath")
    if p is None or not str(p).strip():
        return None
    return str(p).strip()


def _sanitized_ffmpeg_executable_str(path_str: str | None) -> str | None:
    """Return path if it is usable as ffmpeg; None if empty or clearly mpv (common mis-key into unified ffmpegPath)."""
    if path_str is None:
        return None
    s = str(path_str).strip()
    if not s:
        return None
    name = Path(s).name.lower()
    if name in ("mpv.exe", "mpv"):
        return None
    return s


def _unified_uvc_devices_from_doc(doc: dict | None) -> tuple[str | None, str | None]:
    if not doc:
        return None, None
    enc = doc.get("encoder")
    if not isinstance(enc, dict):
        return None, None
    v = enc.get("uvcVideoDevice")
    a = enc.get("uvcAudioDevice")
    vs = str(v).strip() if v is not None and str(v).strip() else None
    au = str(a).strip() if a is not None and str(a).strip() else None
    return vs, au


def resolve_ffmpeg_path() -> Path:
    """Resolve ffmpeg binary: unified ``obsFfmpegPaths.ffmpegPath``, else ``FFMPEG_PATH`` / default, else PATH."""
    load_dotenv_if_present()
    doc = _read_unified_settings_doc()
    unified_ff = _sanitized_ffmpeg_executable_str(_unified_ffmpeg_path_from_doc(doc))
    default_ff = r"C:\ffmpeg\bin\ffmpeg.exe"
    if unified_ff:
        ff = Path(unified_ff)
    else:
        env_ff = _sanitized_ffmpeg_executable_str(os.environ.get("FFMPEG_PATH"))
        ff = Path(env_ff if env_ff else default_ff)
    if not ff.exists():
        w = shutil.which("ffmpeg")
        if w:
            ff = Path(w)
    return ff


def _opt(name: str, default: str) -> str:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    return str(v).strip()


def _opt_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = _opt(name, str(default))
    n = int(raw)
    if minimum is not None and n < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return n


def _opt_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = _opt(name, str(default))
    n = float(raw)
    if minimum is not None and n < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return n


@dataclass(frozen=True)
class EncoderSettings:
    ffmpeg_path: Path
    uvc_capture_backend: str
    uvc_video_device: str
    uvc_audio_device: str
    uvc_rtbufsize: str
    uvc_dshow_video_size: str
    uvc_dshow_framerate: int
    uvc_v4l2_input_format: str
    uvc_v4l2_framerate: int
    uvc_v4l2_video_size: str
    long_preset: str
    long_crf: int
    audio_bitrate_k: int
    long_clips_folder: Path
    long_clips_trigger: Path | None
    encoder_logs_root: Path
    long_record_min_bytes: int
    long_record_verify_stable_seconds: float
    long_output_width: int
    long_output_height: int
    long_output_fps: int
    long_record_max_seconds: int
    long_record_rtbufsize: str
    long_record_input_fps: str
    long_record_output_fps: str
    long_record_encode_width: int
    long_record_encode_height: int
    long_record_keyint_seconds: int
    long_record_video_codec: str
    long_record_video_preset: str
    long_record_video_crf: int
    long_record_pix_fmt: str
    long_record_libx264_tune: str
    long_record_nvenc_preset: str
    long_record_nvenc_tune: str
    long_record_audio_codec: str
    long_record_audio_bitrate: str
    long_record_audio_sample_rate: int
    long_record_audio_sync_offset_ms: int
    long_record_audio_aresample_async_max: int
    long_record_thread_queue_size: int
    long_record_max_muxing_queue_size: int
    long_record_use_wallclock_timestamps: bool
    long_record_dshow_split_audio: bool
    encoder_state_path: Path
    encoder_self_restart_enabled: bool
    encoder_max_auto_restarts_before_app_restart: int
    encoder_unhealthy_window_seconds: float
    encoder_app_restart_exit_code: int
    ffmpeg_child_graceful_wait_seconds: float
    ffmpeg_child_terminate_wait_seconds: float
    long_record_stall_threshold_seconds: float
    long_record_ffprobe_verify: bool
    long_record_ffprobe_min_duration_seconds: float
    encoder_ui_mode: str


def _encoder_ui_mode() -> str:
    raw = _opt("ENCODER_UI_MODE", "").lower()
    if not raw:
        return "hidden" if sys.platform == "win32" else "normal"
    if raw in ("hidden", "headless", "background"):
        return "hidden"
    if raw in ("normal", "visible", "interactive"):
        return "normal"
    raise ValueError("ENCODER_UI_MODE must be 'normal' or 'hidden' (aliases: headless, background)")


def load_encoder_settings() -> EncoderSettings:
    doc = _read_unified_settings_doc()
    unified_vid, unified_aud = _unified_uvc_devices_from_doc(doc)
    ff = resolve_ffmpeg_path()

    default_uvc_backend = "dshow" if sys.platform == "win32" else "v4l2"
    uvc_backend = _opt("UVC_CAPTURE_BACKEND", default_uvc_backend).lower()
    if uvc_backend not in ("dshow", "v4l2"):
        raise ValueError("UVC_CAPTURE_BACKEND must be 'dshow' or 'v4l2'")

    trig_lc = _opt("LONG_CLIPS_TRIGGER_FILE", "")

    log_dir = Path(_opt("ENCODER_LOG_DIR", r"C:\ReplayTrove\logs"))
    log_file = log_dir / "encoder_operator.log"

    uvc_video = (
        unified_vid
        if unified_vid
        else _opt("UVC_VIDEO_DEVICE", "USB3.0 HD Video Capture")
    )
    uvc_audio = (
        unified_aud
        if unified_aud
        else _opt(
            "UVC_AUDIO_DEVICE",
            "Microphone (USB3.0 HD Audio Capture)",
        )
    )

    return EncoderSettings(
        ffmpeg_path=ff,
        uvc_capture_backend=uvc_backend,
        uvc_video_device=uvc_video,
        uvc_audio_device=uvc_audio,
        uvc_rtbufsize=_opt("UVC_DSHOW_RTBUFSIZE", ""),
        uvc_dshow_video_size=_opt("UVC_DSHOW_VIDEO_SIZE", ""),
        uvc_dshow_framerate=_opt_int("UVC_DSHOW_FRAMERATE", 0, 0),
        uvc_v4l2_input_format=_opt("UVC_V4L2_INPUT_FORMAT", ""),
        uvc_v4l2_framerate=_opt_int("UVC_V4L2_FRAMERATE", 60, 1),
        uvc_v4l2_video_size=_opt("UVC_V4L2_VIDEO_SIZE", "1920x1080"),
        long_preset=_opt("X264_PRESET_LONG", "veryfast"),
        long_crf=_opt_int("X264_CRF_LONG", 23, 0),
        audio_bitrate_k=_opt_int("AUDIO_BITRATE_K", 192, 32),
        long_clips_folder=Path(_opt("LONG_CLIPS_FOLDER", r"C:\ReplayTrove\long_clips")),
        long_clips_trigger=Path(trig_lc) if trig_lc else None,
        encoder_logs_root=encoder_logs_root,
        long_record_min_bytes=_opt_int("LONG_RECORD_MIN_BYTES", 256 * 1024, 1024),
        long_record_verify_stable_seconds=_opt_float(
            "LONG_RECORD_VERIFY_STABLE_SECONDS", 3.0, 0.5
        ),
        long_output_width=_opt_int("LONG_OUTPUT_WIDTH", 1920, 16),
        long_output_height=_opt_int("LONG_OUTPUT_HEIGHT", 1080, 16),
        long_output_fps=_opt_int("LONG_OUTPUT_FPS", 30, 1),
        long_record_max_seconds=_opt_int("LONG_RECORD_MAX_SECONDS", 1200, 1),
        long_record_rtbufsize=_opt("LONG_RECORD_RTBUFSIZE", "512M"),
        long_record_input_fps=_opt("LONG_RECORD_INPUT_FRAMERATE", "60"),
        long_record_output_fps=_opt("LONG_RECORD_OUTPUT_FRAMERATE", "30"),
        long_record_encode_width=_opt_int("LONG_RECORD_ENCODE_WIDTH", 0, 0),
        long_record_encode_height=_opt_int("LONG_RECORD_ENCODE_HEIGHT", 0, 0),
        long_record_keyint_seconds=_opt_int("LONG_RECORD_KEYINT_SECONDS", 2, 1),
        long_record_video_codec=_opt("LONG_RECORD_VIDEO_CODEC", "libx264"),
        long_record_video_preset=_opt("LONG_RECORD_VIDEO_PRESET", "superfast"),
        long_record_video_crf=_opt_int("LONG_RECORD_VIDEO_CRF", 23, 0),
        long_record_pix_fmt=_opt("LONG_RECORD_PIX_FMT", "yuv420p"),
        long_record_libx264_tune=_opt("LONG_RECORD_LIBX264_TUNE", ""),
        long_record_nvenc_preset=_opt("LONG_RECORD_NVENC_PRESET", "p1"),
        long_record_nvenc_tune=_opt("LONG_RECORD_NVENC_TUNE", "ll"),
        long_record_audio_codec=_opt("LONG_RECORD_AUDIO_CODEC", "aac"),
        long_record_audio_bitrate=_opt("LONG_RECORD_AUDIO_BITRATE", "128k"),
        long_record_audio_sample_rate=_opt_int(
            "LONG_RECORD_AUDIO_SAMPLE_RATE",
            44100,
            1,
        ),
        long_record_audio_sync_offset_ms=_opt_int(
            "LONG_RECORD_AUDIO_SYNC_OFFSET_MS",
            0,
        ),
        long_record_audio_aresample_async_max=_opt_int(
            "LONG_RECORD_AUDIO_ARESAMPLE_ASYNC_MAX",
            1000,
            0,
        ),
        long_record_thread_queue_size=_opt_int(
            "LONG_RECORD_THREAD_QUEUE_SIZE",
            2048,
            0,
        ),
        long_record_max_muxing_queue_size=_opt_int(
            "LONG_RECORD_MAX_MUXING_QUEUE_SIZE",
            4096,
            0,
        ),
        long_record_use_wallclock_timestamps=(
            _opt(
                "LONG_RECORD_USE_WALLCLOCK_TIMESTAMPS",
                "1" if sys.platform == "win32" else "0",
            ).lower()
            in ("1", "true", "yes", "on")
        ),
        long_record_dshow_split_audio=(
            _opt("LONG_RECORD_DSHOW_SPLIT_AUDIO", "0").lower()
            in ("1", "true", "yes", "on")
        ),
        encoder_state_path=Path(
            _opt(
                "ENCODER_STATE_PATH",
                r"C:\ReplayTrove\scoreboard\encoder_state.json",
            )
        ),
        encoder_self_restart_enabled=(
            _opt("ENCODER_SELF_RESTART_ENABLED", "0").lower()
            in ("1", "true", "yes", "on")
        ),
        encoder_max_auto_restarts_before_app_restart=_opt_int(
            "ENCODER_MAX_AUTO_RESTARTS_BEFORE_APP_RESTART", 5, 1
        ),
        encoder_unhealthy_window_seconds=_opt_float(
            "ENCODER_UNHEALTHY_WINDOW_SECONDS", 120.0, 5.0
        ),
        encoder_app_restart_exit_code=_opt_int(
            "ENCODER_APP_RESTART_EXIT_CODE", 75, 1
        ),
        ffmpeg_child_graceful_wait_seconds=_opt_float(
            "FFMPEG_CHILD_GRACEFUL_WAIT_SECONDS", 2.0, 0.1
        ),
        ffmpeg_child_terminate_wait_seconds=_opt_float(
            "FFMPEG_CHILD_TERMINATE_WAIT_SECONDS", 4.0, 0.1
        ),
        long_record_stall_threshold_seconds=_opt_float(
            "LONG_RECORD_STALL_THRESHOLD_SECONDS", 12.0, 3.0
        ),
        long_record_ffprobe_verify=(
            _opt("LONG_RECORD_FFPROBE_VERIFY", "1").lower()
            in ("1", "true", "yes", "on")
        ),
        long_record_ffprobe_min_duration_seconds=_opt_float(
            "LONG_RECORD_FFPROBE_MIN_DURATION_SECONDS", 0.5, 0.5
        ),
        encoder_ui_mode=_encoder_ui_mode(),
    )
