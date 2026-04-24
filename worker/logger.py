"""
Logging: human stderr + verbose daily JSONL under the central ReplayTrove logs root.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from replaytrove_logging.setup import setup_component_logging


def _system_heartbeat_enabled() -> bool:
    raw = os.environ.get("REPLAYTROVE_SYSTEM_HEARTBEAT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _system_heartbeat_interval() -> float:
    try:
        return max(5.0, float(os.environ.get("REPLAYTROVE_SYSTEM_HEARTBEAT_INTERVAL_SEC", "20")))
    except ValueError:
        return 20.0


def setup_logging(log_folder: Path, log_filename: str = "replaytrove_worker.log") -> None:
    """
    Configure the root logger.

    ``log_folder`` is the central logs directory (e.g. ``C:\\ReplayTrove\\logs``).
    Files: ``log_folder/YYYY-MM-DD/worker.jsonl`` plus mirrored ``timeline.jsonl``.

    ``log_filename`` is retained for call-site compatibility only.
    """
    _ = log_filename
    setup_component_logging(
        logs_root=Path(log_folder),
        service="worker",
        console_level=logging.INFO,
        file_level=logging.DEBUG,
        attach_to_root=True,
        clear_existing_handlers=True,
        enable_system_heartbeat=_system_heartbeat_enabled(),
        system_heartbeat_interval_sec=_system_heartbeat_interval(),
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_extra(logger: logging.Logger, level: int, msg: str, **fields: object) -> None:
    """Log with structured fields attached as ``record.structured``."""
    logger.log(level, msg, extra={"structured": fields})
