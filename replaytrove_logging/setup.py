"""Attach console + date-layout JSONL handlers to the logging tree."""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from replaytrove_logging.service_handler import ServiceJsonlFileHandler


class _JsonlFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        from replaytrove_logging.json_format import format_log_record_json

        return format_log_record_json(record, service=self._service)


class ConsoleFormatter(logging.Formatter):
    """Readable stderr lines."""

    default_time_format = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        from datetime import datetime, timezone

        ts = datetime.fromtimestamp(record.created, timezone.utc).strftime(self.default_time_format)
        base = f"{ts} | {record.levelname:5} | {record.name} | {record.getMessage()}"
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict) and structured:
            try:
                import json

                base += " | " + json.dumps(structured, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                base += f" | {structured!r}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _retention_keep_days() -> int:
    raw = os.environ.get("REPLAYTROVE_LOG_RETENTION_DAYS", "14")
    try:
        return max(1, int(raw.strip()))
    except (TypeError, ValueError):
        return 14


def _retention_compress() -> bool:
    return os.environ.get("REPLAYTROVE_LOG_COMPRESS_OLD", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _schedule_retention(logs_root: Path) -> None:
    from replaytrove_logging.day_index import apply_retention

    def _run() -> None:
        import time

        time.sleep(5)
        try:
            apply_retention(logs_root, keep_days=_retention_keep_days(), compress=_retention_compress())
        except Exception:
            logging.getLogger("replaytrove.retention").debug("retention failed", exc_info=True)

    threading.Thread(target=_run, name="rt_log_retention", daemon=True).start()


def setup_component_logging(
    *,
    logs_root: Path,
    service: str | None = None,
    component: str | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    attach_to_root: bool = True,
    logger_name: str | None = None,
    clear_existing_handlers: bool = True,
    enable_system_heartbeat: bool = False,
    system_heartbeat_interval_sec: float = 20.0,
    run_retention_on_startup: bool = True,
) -> None:
    """
    Configure logging: stderr (human) + ``logs/UTC_DATE/{service}.jsonl`` + timeline + index.

    ``component`` is a deprecated alias for ``service``.
    """
    logs_root = Path(logs_root)
    svc = service or component
    if not svc:
        raise ValueError("service (or deprecated component) is required")
    if not attach_to_root and not logger_name:
        raise ValueError("logger_name is required when attach_to_root is False")
    target = logging.getLogger() if attach_to_root else logging.getLogger(logger_name)
    if clear_existing_handlers and target.handlers:
        for h in list(target.handlers):
            target.removeHandler(h)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(ConsoleFormatter())

    daily = ServiceJsonlFileHandler(logs_root, svc)
    daily.setLevel(file_level)
    daily.setFormatter(_JsonlFormatter(svc))

    target.addHandler(console)
    target.addHandler(daily)

    base_level = min(console_level, file_level)
    target.setLevel(base_level)
    if not attach_to_root and logger_name:
        target.propagate = False

    if run_retention_on_startup:
        _schedule_retention(logs_root)

    if enable_system_heartbeat:
        from replaytrove_logging.system_heartbeat import start_system_heartbeat_thread

        start_system_heartbeat_thread(logs_root, interval_sec=system_heartbeat_interval_sec)
