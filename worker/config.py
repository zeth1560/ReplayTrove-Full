"""
Load and validate worker settings from environment variables (.env supported via python-dotenv).
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Tuple

from dotenv import load_dotenv
from unified_adapter import load_worker_unified_snapshot


_LOG = logging.getLogger(__name__)


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing or empty required environment variable: {name}")
    return value


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def _env_is_set(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and str(value).strip() != ""


def _parse_extensions(raw: str) -> FrozenSet[str]:
    """Parse comma-separated extensions; normalize to lowercase with leading dot."""
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    out: set[str] = set()
    for p in parts:
        if not p.startswith("."):
            p = "." + p
        out.add(p)
    if not out:
        raise ConfigError("VIDEO_EXTENSIONS must list at least one extension")
    return frozenset(out)


def _parse_bool(raw: str, default: bool = False) -> bool:
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off", ""):
        return False
    return default


def _parse_int(name: str, raw: str, minimum: int | None = None) -> int:
    try:
        n = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if minimum is not None and n < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return n


def _parse_float(name: str, raw: str, minimum: float | None = None) -> float:
    try:
        n = float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if minimum is not None and n < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return n


def _parse_csv_strings(raw: str) -> Tuple[str, ...]:
    """Parse comma-separated strings into a tuple, preserving case."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts)


_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the ReplayTrove clip worker."""

    clips_incoming_folder: Path
    clips_processing_folder: Path
    job_db_path: Path
    preview_folder: Path
    processed_folder: Path
    failed_folder: Path
    log_folder: Path

    ffmpeg_path: Path

    aws_region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    s3_bucket: str
    s3_original_prefix: str
    s3_preview_prefix: str

    scott_aws_region: str
    scott_aws_access_key_id: str
    scott_aws_secret_access_key: str
    scott_s3_bucket: str
    scott_s3_preview_prefix: str
    scott_s3_meta_prefix: str

    supabase_url: str
    supabase_key: str
    supabase_clips_table: str
    supabase_bookings_table: str

    pickle_planner_match_url: str
    pickle_planner_api_key: str
    pickle_planner_api_key_header: str

    local_timezone: str

    club_id: str
    court_id: str

    video_extensions: FrozenSet[str]

    preview_width: int
    preview_crf: int
    preview_preset: str

    file_stable_check_seconds: float
    file_stable_retries: int
    file_stable_min_age_seconds: float

    upload_retries: int
    upload_retry_delay_seconds: float

    s3_multipart_threshold_bytes: int
    s3_multipart_chunksize_bytes: int

    move_retries: int
    move_retry_delay_seconds: float

    recent_failure_cooldown_seconds: float
    locked_file_requeue_delay_seconds: float

    ignore_filenames: Tuple[str, ...]
    ignore_prefixes: Tuple[str, ...]
    ignore_suffixes: Tuple[str, ...]

    published: bool

    instant_replay_source: Path | None
    long_clips_folder: Path | None
    long_clip_stable_seconds: float

    instant_replay_post_copy_delay_seconds: float
    clip_readiness_stable_rounds: int
    clip_readiness_max_cycles: int
    ffmpeg_decode_max_soft_fails: int
    ffmpeg_decode_retry_delay_seconds: float

    recent_completed_suppress_seconds: float

    instant_replay_source_min_age_seconds: float
    instant_replay_source_check_seconds: float
    instant_replay_source_retries: int

    instant_replay_trigger_file: Path | None
    instant_replay_trigger_settle_seconds: float
    long_clips_trigger_file: Path | None
    long_clips_scan_interval_seconds: float

    clip_fingerprint_chunk_bytes: int
    clip_fingerprint_include_mtime: bool
    clip_fingerprint_full_hash_max_bytes: int

    worker_concurrency: int
    long_clip_bytes_threshold: int
    long_clip_max_concurrent: int

    large_preview_mode: str
    large_preview_short_seconds: int

    stale_job_idle_seconds: float
    stale_job_policy: str

    worker_health_summary_interval_seconds: float

    booking_match_http_attempts: int
    unmatched_booking_retry_seconds: float
    unmatched_booking_max_attempts: int
    unmatched_booking_poll_seconds: float

    supabase_clip_worker_identity_column: str

    network_retry_base_seconds: float
    network_retry_max_seconds: float
    network_retry_jitter_fraction: float
    network_retry_rounds_per_tick: int
    connectivity_check_interval_seconds: float
    connectivity_probe_timeout_seconds: float
    remote_sync_drain_interval_seconds: float
    remote_sync_max_jobs_per_cycle: int
    remote_sync_inter_job_delay_seconds: float
    remote_sync_inter_job_jitter_seconds: float
    remote_sync_max_total_attempts: int
    remote_sync_max_age_seconds: float
    worker_status_json_path: Path
    worker_status_write_interval_seconds: float

    replay_trigger_http_host: str
    replay_trigger_http_port: int | None

    enable_instant_replay_background_ingest: bool
    enable_replay_scoreboard_auto_sync: bool
    replay_buffer_filename_prefix: str
    replay_scoreboard_auto_sync_interval_seconds: float
    replay_buffer_stable_check_seconds: float
    replay_buffer_stable_min_age_seconds: float
    replay_buffer_stable_rounds_required: int
    replay_buffer_stable_max_retries: int
    replay_buffer_delete_source_after_success: bool
    replay_buffer_remux_max_attempts: int
    replay_buffer_remux_retry_delay_seconds: float


def load_settings(env_file: Path | None = None) -> Settings:
    """
    Load settings from the environment.

    If ``env_file`` is provided, load that file first; otherwise ``load_dotenv()``
    searches for a ``.env`` in the current working directory.
    """
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        load_dotenv(override=False)

    unified = load_worker_unified_snapshot()
    _LOG.info(
        "worker unified config: found=%s path=%s schema_version=%s migrated=%s worker_section=%s general_section=%s storage_section=%s obsffmpeg_section=%s",
        unified.found,
        str(unified.path),
        unified.schema_version,
        unified.migrated,
        unified.worker_section_loaded,
        unified.general_section_loaded,
        unified.storage_section_loaded,
        unified.obsffmpeg_section_loaded,
    )
    if unified.error:
        _LOG.warning("worker unified config parse failed: %s", unified.error)

    source_notes: list[str] = []

    def _pick_string(
        key: str,
        *,
        unified_value: str | None,
        env_name: str,
        default: str,
    ) -> str:
        if unified_value is not None and str(unified_value).strip():
            source_notes.append(f"{key}=unified")
            return str(unified_value).strip()
        if _env_is_set(env_name):
            source_notes.append(f"{key}=env")
            return _optional(env_name, default)
        source_notes.append(f"{key}=default")
        return default

    def _pick_bool(
        key: str,
        *,
        unified_value: bool | None,
        env_name: str,
        default: bool,
    ) -> bool:
        if isinstance(unified_value, bool):
            source_notes.append(f"{key}=unified")
            return unified_value
        if _env_is_set(env_name):
            source_notes.append(f"{key}=env")
            return _parse_bool(_optional(env_name, "1" if default else "0"))
        source_notes.append(f"{key}=default")
        return default

    def _pick_float(
        key: str,
        *,
        unified_value: float | int | None,
        env_name: str,
        default: float,
        minimum: float | None = None,
    ) -> float:
        if isinstance(unified_value, (int, float)) and not isinstance(unified_value, bool):
            source_notes.append(f"{key}=unified")
            return _parse_float(key, str(float(unified_value)), minimum=minimum)
        if _env_is_set(env_name):
            source_notes.append(f"{key}=env")
            return _parse_float(key, _optional(env_name, str(default)), minimum=minimum)
        source_notes.append(f"{key}=default")
        return default

    def _pick_int(
        key: str,
        *,
        unified_value: int | None,
        env_name: str,
        default: int,
        minimum: int | None = None,
    ) -> int:
        if isinstance(unified_value, int) and not isinstance(unified_value, bool):
            source_notes.append(f"{key}=unified")
            return _parse_int(key, str(unified_value), minimum=minimum)
        if _env_is_set(env_name):
            source_notes.append(f"{key}=env")
            return _parse_int(key, _optional(env_name, str(default)), minimum=minimum)
        source_notes.append(f"{key}=default")
        return default

    def _pick_int_optional(
        key: str,
        *,
        unified_enabled: bool | None,
        unified_port: int | None,
        env_name: str,
    ) -> int | None:
        if isinstance(unified_enabled, bool):
            if not unified_enabled:
                source_notes.append(f"{key}=unified_disabled")
                return None
            if isinstance(unified_port, int) and unified_port >= 1:
                source_notes.append(f"{key}=unified")
                return unified_port
            source_notes.append(f"{key}=unified_enabled_missing_port")
            return None
        if _env_is_set(env_name):
            source_notes.append(f"{key}=env")
            return _parse_int(key, os.environ.get(env_name, "").strip(), minimum=1)
        source_notes.append(f"{key}=default")
        return None

    root_default = r"C:\ReplayTrove"
    root_unified = (
        str(unified.general.get("replayTroveRoot")).strip()
        if isinstance(unified.general.get("replayTroveRoot"), str)
        else ""
    )
    replaytrove_root = root_unified or root_default

    incoming = Path(
        _pick_string(
            "WATCH_FOLDER",
            unified_value=(
                unified.worker.get("watchFolder")
                if isinstance(unified.worker.get("watchFolder"), str)
                else None
            ),
            env_name="WATCH_FOLDER",
            default=f"{replaytrove_root}\\clips",
        )
    )
    inc_raw = os.environ.get("CLIPS_INCOMING_FOLDER", "").strip()
    if inc_raw:
        incoming = Path(inc_raw)
    else:
        clips_raw = os.environ.get("CLIPS_FOLDER", "").strip()
        if clips_raw:
            incoming = Path(clips_raw)

    proc_raw = os.environ.get("PROCESSING_CLIPS_FOLDER", "").strip()
    if proc_raw:
        processing = Path(proc_raw)
    else:
        processing = incoming.parent / "clips_processing"

    preview = Path(
        _pick_string(
            "PREVIEW_FOLDER",
            unified_value=(
                unified.worker.get("previewFolder")
                if isinstance(unified.worker.get("previewFolder"), str)
                else None
            ),
            env_name="PREVIEW_FOLDER",
            default=f"{replaytrove_root}\\previews",
        )
    )
    processed = Path(
        _pick_string(
            "PROCESSED_FOLDER",
            unified_value=(
                unified.worker.get("processedFolder")
                if isinstance(unified.worker.get("processedFolder"), str)
                else None
            ),
            env_name="PROCESSED_FOLDER",
            default=f"{replaytrove_root}\\processed",
        )
    )
    failed = Path(
        _pick_string(
            "FAILED_FOLDER",
            unified_value=(
                unified.worker.get("failedFolder")
                if isinstance(unified.worker.get("failedFolder"), str)
                else None
            ),
            env_name="FAILED_FOLDER",
            default=f"{replaytrove_root}\\failed",
        )
    )
    logs = Path(_optional("LOG_FOLDER", f"{replaytrove_root}\\logs"))
    job_db = Path(
        _optional("WORKER_JOB_DB", str(logs / "replaytrove_jobs.sqlite"))
    )

    ffmpeg = Path(
        _pick_string(
            "FFMPEG_PATH",
            unified_value=(
                unified.obsffmpeg.get("ffmpegPath")
                if isinstance(unified.obsffmpeg.get("ffmpegPath"), str)
                else None
            ),
            env_name="FFMPEG_PATH",
            default=r"C:\ffmpeg\bin\ffmpeg.exe",
        )
    )

    region = _require("AWS_REGION")
    key_id = _require("AWS_ACCESS_KEY_ID")
    secret = _require("AWS_SECRET_ACCESS_KEY")
    bucket = _require("S3_BUCKET")

    orig_prefix = _optional("S3_ORIGINAL_PREFIX", "originals").strip("/")
    prev_prefix = _optional("S3_PREVIEW_PREFIX", "previews").strip("/")

    scott_aws_region = _optional("SCOTT_AWS_REGION", "us-east-1")
    scott_aws_access_key_id = _require("SCOTT_AWS_ACCESS_KEY_ID")
    scott_aws_secret_access_key = _require("SCOTT_AWS_SECRET_ACCESS_KEY")
    scott_s3_bucket = _require("SCOTT_S3_BUCKET")
    scott_s3_preview_prefix = _optional("SCOTT_S3_PREVIEW_PREFIX", "replay-trove").strip("/")
    scott_s3_meta_prefix = _optional("SCOTT_S3_META_PREFIX", "replay-trove-meta").strip("/")

    local_timezone = _optional("LOCAL_TIMEZONE", "America/Chicago")

    sb_url = _require("SUPABASE_URL")
    sb_key = _require("SUPABASE_KEY")
    clips_table = _optional("SUPABASE_CLIPS_TABLE", "clips")
    bookings_table = _pick_string(
        "SUPABASE_BOOKINGS_TABLE",
        unified_value=(
            unified.storage.get("supabaseBookingsTable")
            if isinstance(unified.storage.get("supabaseBookingsTable"), str)
            else None
        ),
        env_name="SUPABASE_BOOKINGS_TABLE",
        default="bookings",
    )

    pp_match_url = _require("PICKLE_PLANNER_MATCH_URL")
    pp_api_key = _require("PICKLE_PLANNER_API_KEY")
    pp_api_key_header = _optional("PICKLE_PLANNER_API_KEY_HEADER", "x-api-key")

    club = _require("CLUB_ID")
    court = _require("COURT_ID")

    exts = _parse_extensions(_optional("VIDEO_EXTENSIONS", ".mp4,.mov,.mkv"))

    preview_width = _pick_int(
        "PREVIEW_WIDTH",
        unified_value=(
            unified.worker.get("previewWidth")
            if isinstance(unified.worker.get("previewWidth"), int)
            else None
        ),
        env_name="PREVIEW_WIDTH",
        default=426,
        minimum=16,
    )
    preview_crf = _parse_int("PREVIEW_CRF", _optional("PREVIEW_CRF", "36"), minimum=0)
    preview_preset = _optional("PREVIEW_PRESET", "fast")

    stable_sec = _parse_float(
        "FILE_STABLE_CHECK_SECONDS",
        _optional("FILE_STABLE_CHECK_SECONDS", "2"),
        minimum=0.0001,
    )
    stable_retries = _parse_int(
        "FILE_STABLE_RETRIES",
        _optional("FILE_STABLE_RETRIES", "30"),
        minimum=1,
    )
    stable_min_age = _parse_float(
        "FILE_STABLE_MIN_AGE_SECONDS",
        _optional("FILE_STABLE_MIN_AGE_SECONDS", "8"),
        minimum=0,
    )

    up_retries = _pick_int(
        "UPLOAD_RETRIES",
        unified_value=(
            unified.worker.get("uploadRetries")
            if isinstance(unified.worker.get("uploadRetries"), int)
            else None
        ),
        env_name="UPLOAD_RETRIES",
        default=3,
        minimum=1,
    )
    up_delay = _pick_float(
        "UPLOAD_RETRY_DELAY_SECONDS",
        unified_value=(
            unified.worker.get("uploadRetryDelaySeconds")
            if isinstance(unified.worker.get("uploadRetryDelaySeconds"), (int, float))
            else None
        ),
        env_name="UPLOAD_RETRY_DELAY_SECONDS",
        default=3,
        minimum=0,
    )

    mp_thresh = _parse_int(
        "S3_MULTIPART_THRESHOLD_BYTES",
        _optional("S3_MULTIPART_THRESHOLD_BYTES", str(32 * 1024 * 1024)),
        minimum=8 * 1024 * 1024,
    )
    mp_chunk = _parse_int(
        "S3_MULTIPART_CHUNKSIZE_BYTES",
        _optional("S3_MULTIPART_CHUNKSIZE_BYTES", str(128 * 1024 * 1024)),
        minimum=8 * 1024 * 1024,
    )

    move_retries = _parse_int(
        "MOVE_RETRIES",
        _optional("MOVE_RETRIES", "12"),
        minimum=1,
    )
    move_delay = _parse_float(
        "MOVE_RETRY_DELAY_SECONDS",
        _optional("MOVE_RETRY_DELAY_SECONDS", "2"),
        minimum=0,
    )

    recent_failure_cooldown = _parse_float(
        "RECENT_FAILURE_COOLDOWN_SECONDS",
        _optional("RECENT_FAILURE_COOLDOWN_SECONDS", "120"),
        minimum=0,
    )
    locked_file_requeue_delay = _parse_float(
        "LOCKED_FILE_REQUEUE_DELAY_SECONDS",
        _optional("LOCKED_FILE_REQUEUE_DELAY_SECONDS", "10"),
        minimum=0,
    )

    ignore_filenames = _parse_csv_strings(
        _optional("IGNORE_FILENAMES", "InstantReplay.mp4,InstantReplay.mkv")
    )
    ignore_prefixes = _parse_csv_strings(
        _optional("IGNORE_PREFIXES", "~,.")
    )
    ignore_suffixes = _parse_csv_strings(
        _optional("IGNORE_SUFFIXES", ".tmp,.part,.partial")
    )

    published = _parse_bool(_optional("PUBLISHED", "true"))

    unified_ir = (
        str(unified.worker.get("instantReplaySource")).strip()
        if isinstance(unified.worker.get("instantReplaySource"), str)
        else ""
    )
    if unified_ir:
        source_notes.append("INSTANT_REPLAY_SOURCE=unified")
        instant_replay_source = Path(unified_ir)
    elif "INSTANT_REPLAY_SOURCE" in os.environ:
        source_notes.append("INSTANT_REPLAY_SOURCE=env")
        ir = os.environ["INSTANT_REPLAY_SOURCE"].strip()
        instant_replay_source = Path(ir) if ir else None
    else:
        source_notes.append("INSTANT_REPLAY_SOURCE=default")
        instant_replay_source = Path(f"{replaytrove_root}\\INSTANTREPLAY.mkv")

    unified_lc = (
        str(unified.worker.get("longClipsFolder")).strip()
        if isinstance(unified.worker.get("longClipsFolder"), str)
        else ""
    )
    if unified_lc:
        source_notes.append("LONG_CLIPS_FOLDER=unified")
        long_clips_folder = Path(unified_lc)
    elif "LONG_CLIPS_FOLDER" in os.environ:
        source_notes.append("LONG_CLIPS_FOLDER=env")
        lc = os.environ["LONG_CLIPS_FOLDER"].strip()
        long_clips_folder = Path(lc) if lc else None
    else:
        source_notes.append("LONG_CLIPS_FOLDER=default")
        long_clips_folder = Path(f"{replaytrove_root}\\long_clips")

    long_clip_stable_seconds = _parse_float(
        "LONG_CLIP_STABLE_SECONDS",
        _optional("LONG_CLIP_STABLE_SECONDS", "300"),
        minimum=1,
    )

    instant_replay_post_copy_delay = _parse_float(
        "INSTANT_REPLAY_POST_COPY_DELAY_SECONDS",
        _optional("INSTANT_REPLAY_POST_COPY_DELAY_SECONDS", "4"),
        minimum=0,
    )
    clip_readiness_rounds = _parse_int(
        "CLIP_READINESS_STABLE_ROUNDS",
        _optional("CLIP_READINESS_STABLE_ROUNDS", "2"),
        minimum=1,
    )
    clip_readiness_cycles = _parse_int(
        "CLIP_READINESS_MAX_CYCLES",
        _optional("CLIP_READINESS_MAX_CYCLES", "12"),
        minimum=1,
    )
    ffmpeg_decode_max_soft = _parse_int(
        "FFMPEG_DECODE_MAX_SOFT_FAILS",
        _optional("FFMPEG_DECODE_MAX_SOFT_FAILS", "3"),
        minimum=1,
    )
    ffmpeg_decode_retry_delay = _parse_float(
        "FFMPEG_DECODE_RETRY_DELAY_SECONDS",
        _optional("FFMPEG_DECODE_RETRY_DELAY_SECONDS", "5"),
        minimum=0,
    )

    recent_completed_suppress = _parse_float(
        "RECENT_COMPLETED_SUPPRESS_SECONDS",
        _optional("RECENT_COMPLETED_SUPPRESS_SECONDS", "300"),
        minimum=0,
    )

    ir_src_min_age = _parse_float(
        "INSTANT_REPLAY_SOURCE_MIN_AGE_SECONDS",
        _optional("INSTANT_REPLAY_SOURCE_MIN_AGE_SECONDS", "0.2"),
        minimum=0,
    )
    ir_src_check = _parse_float(
        "INSTANT_REPLAY_SOURCE_CHECK_SECONDS",
        _optional("INSTANT_REPLAY_SOURCE_CHECK_SECONDS", "0.4"),
        minimum=0.05,
    )
    ir_src_retries = _parse_int(
        "INSTANT_REPLAY_SOURCE_RETRIES",
        _optional("INSTANT_REPLAY_SOURCE_RETRIES", "120"),
        minimum=1,
    )

    unified_trigger = (
        str(unified.worker.get("instantReplayTriggerFile")).strip()
        if isinstance(unified.worker.get("instantReplayTriggerFile"), str)
        else None
    )
    if unified_trigger is not None:
        source_notes.append("INSTANT_REPLAY_TRIGGER_FILE=unified")
        instant_replay_trigger_file = Path(unified_trigger) if unified_trigger else None
    elif "INSTANT_REPLAY_TRIGGER_FILE" in os.environ:
        source_notes.append("INSTANT_REPLAY_TRIGGER_FILE=env")
        irt = os.environ["INSTANT_REPLAY_TRIGGER_FILE"].strip()
        instant_replay_trigger_file = Path(irt) if irt else None
    else:
        source_notes.append("INSTANT_REPLAY_TRIGGER_FILE=default")
        instant_replay_trigger_file = None

    instant_replay_trigger_settle = _pick_float(
        "INSTANT_REPLAY_TRIGGER_SETTLE_SECONDS",
        unified_value=(
            unified.worker.get("instantReplayTriggerSettleSeconds")
            if isinstance(unified.worker.get("instantReplayTriggerSettleSeconds"), (int, float))
            else None
        ),
        env_name="INSTANT_REPLAY_TRIGGER_SETTLE_SECONDS",
        default=1.0,
        minimum=0,
    )

    if "LONG_CLIPS_TRIGGER_FILE" in os.environ:
        lct = os.environ["LONG_CLIPS_TRIGGER_FILE"].strip()
        long_clips_trigger_file = Path(lct) if lct else None
    else:
        long_clips_trigger_file = None

    long_clips_scan_interval = _pick_float(
        "LONG_CLIPS_SCAN_INTERVAL_SECONDS",
        unified_value=(
            unified.worker.get("longClipsScanIntervalSeconds")
            if isinstance(unified.worker.get("longClipsScanIntervalSeconds"), (int, float))
            else None
        ),
        env_name="LONG_CLIPS_SCAN_INTERVAL_SECONDS",
        default=10,
        minimum=0,
    )

    clip_fp_chunk = _parse_int(
        "CLIP_FINGERPRINT_CHUNK_BYTES",
        _optional("CLIP_FINGERPRINT_CHUNK_BYTES", str(1024 * 1024)),
        minimum=4096,
    )
    clip_fp_mtime = _parse_bool(_optional("CLIP_FINGERPRINT_INCLUDE_MTIME", "false"))
    clip_fp_full_max = _parse_int(
        "CLIP_FINGERPRINT_FULL_HASH_MAX_BYTES",
        _optional("CLIP_FINGERPRINT_FULL_HASH_MAX_BYTES", "0"),
        minimum=0,
    )

    worker_concurrency = _pick_int(
        "WORKER_CONCURRENCY",
        unified_value=(
            unified.worker.get("workerConcurrency")
            if isinstance(unified.worker.get("workerConcurrency"), int)
            else None
        ),
        env_name="WORKER_CONCURRENCY",
        default=1,
        minimum=1,
    )
    long_clip_threshold = _parse_int(
        "LONG_CLIP_BYTES_THRESHOLD",
        _optional("LONG_CLIP_BYTES_THRESHOLD", str(1024 * 1024 * 1024)),
        minimum=1,
    )
    long_clip_max_conc = _parse_int(
        "LONG_CLIP_MAX_CONCURRENT",
        _optional("LONG_CLIP_MAX_CONCURRENT", "1"),
        minimum=1,
    )

    large_preview_mode = _optional("LARGE_PREVIEW_MODE", "full").strip().lower()
    if large_preview_mode not in ("full", "poster", "short", "defer_after_original"):
        raise ConfigError(
            "LARGE_PREVIEW_MODE must be one of: full, poster, short, defer_after_original"
        )
    large_preview_short_sec = _parse_int(
        "LARGE_PREVIEW_SHORT_SECONDS",
        _optional("LARGE_PREVIEW_SHORT_SECONDS", "15"),
        minimum=1,
    )

    stale_idle = _parse_float(
        "STALE_JOB_IDLE_SECONDS",
        _optional("STALE_JOB_IDLE_SECONDS", "3600"),
        minimum=0,
    )
    stale_policy = _optional("STALE_JOB_POLICY", "log").strip().lower()
    if stale_policy not in ("log", "flag"):
        raise ConfigError("STALE_JOB_POLICY must be log or flag")

    health_iv = _parse_float(
        "WORKER_HEALTH_SUMMARY_INTERVAL_SECONDS",
        _optional("WORKER_HEALTH_SUMMARY_INTERVAL_SECONDS", "300"),
        minimum=0,
    )

    booking_http_attempts = _parse_int(
        "BOOKING_MATCH_HTTP_ATTEMPTS",
        _optional("BOOKING_MATCH_HTTP_ATTEMPTS", "3"),
        minimum=1,
    )
    unmatched_retry_sec = _parse_float(
        "UNMATCHED_BOOKING_RETRY_SECONDS",
        _optional("UNMATCHED_BOOKING_RETRY_SECONDS", "0"),
        minimum=0,
    )
    unmatched_max = _parse_int(
        "UNMATCHED_BOOKING_MAX_ATTEMPTS",
        _optional("UNMATCHED_BOOKING_MAX_ATTEMPTS", "8"),
        minimum=1,
    )
    unmatched_poll = _parse_float(
        "UNMATCHED_BOOKING_POLL_SECONDS",
        _optional("UNMATCHED_BOOKING_POLL_SECONDS", "30"),
        minimum=5,
    )

    sb_worker_id_col = _optional("SUPABASE_CLIP_WORKER_IDENTITY_COLUMN", "").strip()

    net_retry_base = _parse_float(
        "NETWORK_RETRY_BASE_SECONDS",
        _optional("NETWORK_RETRY_BASE_SECONDS", "5"),
        minimum=0.5,
    )
    net_retry_max = _parse_float(
        "NETWORK_RETRY_MAX_SECONDS",
        _optional("NETWORK_RETRY_MAX_SECONDS", "60"),
        minimum=net_retry_base,
    )
    net_retry_jitter = _parse_float(
        "NETWORK_RETRY_JITTER_FRACTION",
        _optional("NETWORK_RETRY_JITTER_FRACTION", "0.2"),
        minimum=0.0,
    )
    net_retry_rounds = _parse_int(
        "NETWORK_RETRY_ROUNDS_PER_TICK",
        _optional("NETWORK_RETRY_ROUNDS_PER_TICK", "6"),
        minimum=1,
    )
    conn_interval = _parse_float(
        "CONNECTIVITY_CHECK_INTERVAL_SECONDS",
        _optional("CONNECTIVITY_CHECK_INTERVAL_SECONDS", "30"),
        minimum=5.0,
    )
    conn_probe_timeout = _parse_float(
        "CONNECTIVITY_PROBE_TIMEOUT_SECONDS",
        _optional("CONNECTIVITY_PROBE_TIMEOUT_SECONDS", "5"),
        minimum=1.0,
    )
    remote_drain_iv = _parse_float(
        "REMOTE_SYNC_DRAIN_INTERVAL_SECONDS",
        _optional("REMOTE_SYNC_DRAIN_INTERVAL_SECONDS", "8"),
        minimum=1.0,
    )
    remote_sync_max_per_cycle = _parse_int(
        "REMOTE_SYNC_MAX_JOBS_PER_CYCLE",
        _optional("REMOTE_SYNC_MAX_JOBS_PER_CYCLE", "3"),
        minimum=1,
    )
    remote_inter_delay = _parse_float(
        "REMOTE_SYNC_INTER_JOB_DELAY_SECONDS",
        _optional("REMOTE_SYNC_INTER_JOB_DELAY_SECONDS", "0.35"),
        minimum=0.0,
    )
    remote_inter_jitter = _parse_float(
        "REMOTE_SYNC_INTER_JOB_JITTER_SECONDS",
        _optional("REMOTE_SYNC_INTER_JOB_JITTER_SECONDS", "0.15"),
        minimum=0.0,
    )
    remote_sync_max_attempts = _parse_int(
        "REMOTE_SYNC_MAX_TOTAL_ATTEMPTS",
        _optional("REMOTE_SYNC_MAX_TOTAL_ATTEMPTS", "20"),
        minimum=0,
    )
    remote_sync_max_age = _parse_float(
        "REMOTE_SYNC_MAX_AGE_SECONDS",
        _optional("REMOTE_SYNC_MAX_AGE_SECONDS", str(24 * 3600)),
        minimum=0.0,
    )
    status_json = Path(
        _pick_string(
            "WORKER_STATUS_JSON_PATH",
            unified_value=(
                unified.worker.get("workerStatusJsonPath")
                if isinstance(unified.worker.get("workerStatusJsonPath"), str)
                else None
            ),
            env_name="WORKER_STATUS_JSON_PATH",
            default=f"{replaytrove_root}\\status.json",
        )
    )
    status_write_iv = _pick_float(
        "WORKER_STATUS_WRITE_INTERVAL_SECONDS",
        unified_value=(
            unified.worker.get("workerStatusWriteIntervalSeconds")
            if isinstance(unified.worker.get("workerStatusWriteIntervalSeconds"), (int, float))
            else None
        ),
        env_name="WORKER_STATUS_WRITE_INTERVAL_SECONDS",
        default=5,
        minimum=0.0,
    )

    replay_trigger_host = _pick_string(
        "REPLAY_TRIGGER_HTTP_HOST",
        unified_value=(
            unified.worker.get("httpReplayTriggerHost")
            if isinstance(unified.worker.get("httpReplayTriggerHost"), str)
            else None
        ),
        env_name="REPLAY_TRIGGER_HTTP_HOST",
        default="127.0.0.1",
    )
    replay_trigger_http_port = _pick_int_optional(
        "REPLAY_TRIGGER_HTTP_PORT",
        unified_enabled=(
            unified.worker.get("httpReplayTriggerEnabled")
            if isinstance(unified.worker.get("httpReplayTriggerEnabled"), bool)
            else None
        ),
        unified_port=(
            unified.worker.get("httpReplayTriggerPort")
            if isinstance(unified.worker.get("httpReplayTriggerPort"), int)
            else None
        ),
        env_name="REPLAY_TRIGGER_HTTP_PORT",
    )

    enable_ir_background = _pick_bool(
        "ENABLE_INSTANT_REPLAY_BACKGROUND_INGEST",
        unified_value=(
            unified.worker.get("enableInstantReplayBackgroundIngest")
            if isinstance(unified.worker.get("enableInstantReplayBackgroundIngest"), bool)
            else None
        ),
        env_name="ENABLE_INSTANT_REPLAY_BACKGROUND_INGEST",
        default=False,
    )
    enable_replay_auto_sync = _pick_bool(
        "ENABLE_REPLAY_SCOREBOARD_AUTO_SYNC",
        unified_value=(
            unified.worker.get("enableReplayScoreboardAutoSync")
            if isinstance(unified.worker.get("enableReplayScoreboardAutoSync"), bool)
            else None
        ),
        env_name="ENABLE_REPLAY_SCOREBOARD_AUTO_SYNC",
        default=False,
    )

    replay_buffer_filename_prefix = _pick_string(
        "REPLAY_BUFFER_FILENAME_PREFIX",
        unified_value=(
            unified.worker.get("replayBufferFilenamePrefix")
            if isinstance(unified.worker.get("replayBufferFilenamePrefix"), str)
            else None
        ),
        env_name="REPLAY_BUFFER_FILENAME_PREFIX",
        default="replay_",
    )
    replay_scoreboard_auto_sync_iv = _pick_float(
        "REPLAY_SCOREBOARD_AUTO_SYNC_INTERVAL_SECONDS",
        unified_value=(
            unified.worker.get("replayScoreboardAutoSyncIntervalSeconds")
            if isinstance(
                unified.worker.get("replayScoreboardAutoSyncIntervalSeconds"),
                (int, float),
            )
            else None
        ),
        env_name="REPLAY_SCOREBOARD_AUTO_SYNC_INTERVAL_SECONDS",
        default=0.0,
        minimum=0.0,
    )

    replay_buf_stable_chk = _pick_float(
        "REPLAY_BUFFER_STABLE_CHECK_SECONDS",
        unified_value=(
            unified.worker.get("replayBufferStableCheckSeconds")
            if isinstance(unified.worker.get("replayBufferStableCheckSeconds"), (int, float))
            else None
        ),
        env_name="REPLAY_BUFFER_STABLE_CHECK_SECONDS",
        default=0.08,
        minimum=0.05,
    )
    replay_buf_stable_min_age = _pick_float(
        "REPLAY_BUFFER_STABLE_MIN_AGE_SECONDS",
        unified_value=(
            unified.worker.get("replayBufferStableMinAgeSeconds")
            if isinstance(unified.worker.get("replayBufferStableMinAgeSeconds"), (int, float))
            else None
        ),
        env_name="REPLAY_BUFFER_STABLE_MIN_AGE_SECONDS",
        default=0.1,
        minimum=0.0,
    )
    replay_buf_stable_rounds = _pick_int(
        "REPLAY_BUFFER_STABLE_ROUNDS",
        unified_value=(
            unified.worker.get("replayBufferStableRoundsRequired")
            if isinstance(unified.worker.get("replayBufferStableRoundsRequired"), int)
            else None
        ),
        env_name="REPLAY_BUFFER_STABLE_ROUNDS",
        default=2,
        minimum=1,
    )
    replay_buf_stable_max_ret = _pick_int(
        "REPLAY_BUFFER_STABLE_MAX_RETRIES",
        unified_value=(
            unified.worker.get("replayBufferStableMaxRetries")
            if isinstance(unified.worker.get("replayBufferStableMaxRetries"), int)
            else None
        ),
        env_name="REPLAY_BUFFER_STABLE_MAX_RETRIES",
        default=80,
        minimum=5,
    )
    replay_buf_delete_src = _pick_bool(
        "REPLAY_BUFFER_DELETE_SOURCE_AFTER_SUCCESS",
        unified_value=(
            unified.worker.get("replayBufferDeleteSourceAfterSuccess")
            if isinstance(unified.worker.get("replayBufferDeleteSourceAfterSuccess"), bool)
            else None
        ),
        env_name="REPLAY_BUFFER_DELETE_SOURCE_AFTER_SUCCESS",
        default=True,
    )
    replay_buf_remux_attempts = _pick_int(
        "REPLAY_BUFFER_REMUX_MAX_ATTEMPTS",
        unified_value=(
            unified.worker.get("replayBufferRemuxMaxAttempts")
            if isinstance(unified.worker.get("replayBufferRemuxMaxAttempts"), int)
            else None
        ),
        env_name="REPLAY_BUFFER_REMUX_MAX_ATTEMPTS",
        default=10,
        minimum=1,
    )
    replay_buf_remux_delay = _pick_float(
        "REPLAY_BUFFER_REMUX_RETRY_DELAY_SECONDS",
        unified_value=(
            unified.worker.get("replayBufferRemuxRetryDelaySeconds")
            if isinstance(unified.worker.get("replayBufferRemuxRetryDelaySeconds"), (int, float))
            else None
        ),
        env_name="REPLAY_BUFFER_REMUX_RETRY_DELAY_SECONDS",
        default=4,
        minimum=0,
    )
    _LOG.info("worker config source resolution: %s", ", ".join(source_notes))
    fallback_notes = [n for n in source_notes if not n.endswith("=unified")]
    if fallback_notes:
        _LOG.warning("worker config fallback in use: %s", ", ".join(fallback_notes))
    legacy_replay_env_notes = [
        n
        for n in source_notes
        if n
        in (
            "REPLAY_TRIGGER_HTTP_HOST=env",
            "REPLAY_TRIGGER_HTTP_PORT=env",
            "INSTANT_REPLAY_TRIGGER_FILE=env",
        )
    ]
    if legacy_replay_env_notes:
        _LOG.warning(
            "worker replay config using env fallback: %s (prefer unified config/settings.json worker.* values)",
            ", ".join(legacy_replay_env_notes),
        )

    return Settings(
        clips_incoming_folder=incoming,
        clips_processing_folder=processing,
        job_db_path=job_db,
        preview_folder=preview,
        processed_folder=processed,
        failed_folder=failed,
        log_folder=logs,
        ffmpeg_path=ffmpeg,
        aws_region=region,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        s3_bucket=bucket,
        s3_original_prefix=orig_prefix,
        s3_preview_prefix=prev_prefix,
        scott_aws_region=scott_aws_region,
        scott_aws_access_key_id=scott_aws_access_key_id,
        scott_aws_secret_access_key=scott_aws_secret_access_key,
        scott_s3_bucket=scott_s3_bucket,
        scott_s3_preview_prefix=scott_s3_preview_prefix,
        scott_s3_meta_prefix=scott_s3_meta_prefix,
        supabase_url=sb_url,
        supabase_key=sb_key,
        supabase_clips_table=clips_table,
        supabase_bookings_table=bookings_table,
        pickle_planner_match_url=pp_match_url,
        pickle_planner_api_key=pp_api_key,
        pickle_planner_api_key_header=pp_api_key_header,
        local_timezone=local_timezone,
        club_id=club,
        court_id=court,
        video_extensions=exts,
        preview_width=preview_width,
        preview_crf=preview_crf,
        preview_preset=preview_preset,
        file_stable_check_seconds=stable_sec,
        file_stable_retries=stable_retries,
        file_stable_min_age_seconds=stable_min_age,
        upload_retries=up_retries,
        upload_retry_delay_seconds=up_delay,
        s3_multipart_threshold_bytes=mp_thresh,
        s3_multipart_chunksize_bytes=mp_chunk,
        move_retries=move_retries,
        move_retry_delay_seconds=move_delay,
        recent_failure_cooldown_seconds=recent_failure_cooldown,
        locked_file_requeue_delay_seconds=locked_file_requeue_delay,
        ignore_filenames=ignore_filenames,
        ignore_prefixes=ignore_prefixes,
        ignore_suffixes=ignore_suffixes,
        published=published,
        instant_replay_source=instant_replay_source,
        long_clips_folder=long_clips_folder,
        long_clip_stable_seconds=long_clip_stable_seconds,
        instant_replay_post_copy_delay_seconds=instant_replay_post_copy_delay,
        clip_readiness_stable_rounds=clip_readiness_rounds,
        clip_readiness_max_cycles=clip_readiness_cycles,
        ffmpeg_decode_max_soft_fails=ffmpeg_decode_max_soft,
        ffmpeg_decode_retry_delay_seconds=ffmpeg_decode_retry_delay,
        recent_completed_suppress_seconds=recent_completed_suppress,
        instant_replay_source_min_age_seconds=ir_src_min_age,
        instant_replay_source_check_seconds=ir_src_check,
        instant_replay_source_retries=ir_src_retries,
        instant_replay_trigger_file=instant_replay_trigger_file,
        instant_replay_trigger_settle_seconds=instant_replay_trigger_settle,
        long_clips_trigger_file=long_clips_trigger_file,
        long_clips_scan_interval_seconds=long_clips_scan_interval,
        clip_fingerprint_chunk_bytes=clip_fp_chunk,
        clip_fingerprint_include_mtime=clip_fp_mtime,
        clip_fingerprint_full_hash_max_bytes=clip_fp_full_max,
        worker_concurrency=worker_concurrency,
        long_clip_bytes_threshold=long_clip_threshold,
        long_clip_max_concurrent=long_clip_max_conc,
        large_preview_mode=large_preview_mode,
        large_preview_short_seconds=large_preview_short_sec,
        stale_job_idle_seconds=stale_idle,
        stale_job_policy=stale_policy,
        worker_health_summary_interval_seconds=health_iv,
        booking_match_http_attempts=booking_http_attempts,
        unmatched_booking_retry_seconds=unmatched_retry_sec,
        unmatched_booking_max_attempts=unmatched_max,
        unmatched_booking_poll_seconds=unmatched_poll,
        supabase_clip_worker_identity_column=sb_worker_id_col,
        network_retry_base_seconds=net_retry_base,
        network_retry_max_seconds=net_retry_max,
        network_retry_jitter_fraction=net_retry_jitter,
        network_retry_rounds_per_tick=net_retry_rounds,
        connectivity_check_interval_seconds=conn_interval,
        connectivity_probe_timeout_seconds=conn_probe_timeout,
        remote_sync_drain_interval_seconds=remote_drain_iv,
        remote_sync_max_jobs_per_cycle=remote_sync_max_per_cycle,
        remote_sync_inter_job_delay_seconds=remote_inter_delay,
        remote_sync_inter_job_jitter_seconds=remote_inter_jitter,
        remote_sync_max_total_attempts=remote_sync_max_attempts,
        remote_sync_max_age_seconds=remote_sync_max_age,
        worker_status_json_path=status_json,
        worker_status_write_interval_seconds=status_write_iv,
        replay_trigger_http_host=replay_trigger_host,
        replay_trigger_http_port=replay_trigger_http_port,
        enable_instant_replay_background_ingest=enable_ir_background,
        enable_replay_scoreboard_auto_sync=enable_replay_auto_sync,
        replay_buffer_filename_prefix=replay_buffer_filename_prefix,
        replay_scoreboard_auto_sync_interval_seconds=replay_scoreboard_auto_sync_iv,
        replay_buffer_stable_check_seconds=replay_buf_stable_chk,
        replay_buffer_stable_min_age_seconds=replay_buf_stable_min_age,
        replay_buffer_stable_rounds_required=replay_buf_stable_rounds,
        replay_buffer_stable_max_retries=replay_buf_stable_max_ret,
        replay_buffer_delete_source_after_success=replay_buf_delete_src,
        replay_buffer_remux_max_attempts=replay_buf_remux_attempts,
        replay_buffer_remux_retry_delay_seconds=replay_buf_remux_delay,
    )


def slug_from_stem(stem: str) -> str:
    """URL-ish slug from a filename stem (lowercase, hyphen-separated)."""
    s = stem.strip().lower()
    s = _SLUG_SAFE.sub("-", s)
    s = s.strip("-")
    if not s:
        s = "clip"
    return s