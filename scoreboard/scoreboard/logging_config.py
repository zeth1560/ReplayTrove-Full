"""Central logging setup for the scoreboard application."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from replaytrove_logging.json_format import format_log_record_json
from replaytrove_logging.service_handler import ServiceJsonlFileHandler
from replaytrove_logging.setup import ConsoleFormatter

# Optional legacy text log (SCOREBOARD_LOG_FILE); size-rotated if set.
_LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
_LOG_FILE_BACKUP_COUNT = 5


class _ScoreboardJsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return format_log_record_json(record, service="scoreboard")


def configure_logging(
    level: int = logging.INFO,
    *,
    log_file: str | None = None,
    central_logs_root: Path | None = None,
) -> None:
    """Configure root logger: stderr + daily JSONL under central_logs_root + optional legacy file."""
    root = logging.getLogger()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not root.handlers:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(ConsoleFormatter())
        root.addHandler(stderr_handler)

        if central_logs_root is not None:
            try:
                daily = ServiceJsonlFileHandler(Path(central_logs_root), "scoreboard")
                daily.setFormatter(_ScoreboardJsonlFormatter())
                daily.setLevel(logging.DEBUG)
                root.addHandler(daily)
            except OSError:
                print(
                    f"scoreboard: could not open central JSONL under {central_logs_root!r}",
                    file=sys.stderr,
                )

        if log_file:
            try:
                path = Path(log_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = RotatingFileHandler(
                    path,
                    maxBytes=_LOG_FILE_MAX_BYTES,
                    backupCount=_LOG_FILE_BACKUP_COUNT,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                root.addHandler(file_handler)
            except OSError:
                print(
                    f"scoreboard: could not open legacy log file {log_file!r}",
                    file=sys.stderr,
                )

    root.setLevel(level)
    for h in root.handlers:
        if isinstance(h, (logging.StreamHandler, RotatingFileHandler)):
            h.setLevel(level)
        elif isinstance(h, ServiceJsonlFileHandler):
            h.setLevel(logging.DEBUG)
