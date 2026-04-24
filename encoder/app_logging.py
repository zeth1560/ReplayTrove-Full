"""Daily JSONL file logging + optional Tk queue handler for the encoder operator."""

from __future__ import annotations

import logging
import queue
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from replaytrove_logging.setup import setup_component_logging


class TkQueueLogHandler(logging.Handler):
    """Push formatted log lines to a queue consumed by the Tk text widget."""

    def __init__(self, log_q: queue.Queue[str]) -> None:
        super().__init__()
        self._q = log_q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) + "\n"
            self._q.put(msg)
        except Exception:
            self.handleError(record)


def setup_encoder_logging(
    logs_root: Path,
    *,
    ui_queue: queue.Queue[str] | None = None,
) -> logging.Logger:
    """
    Configure ``replaytrove.encoder`` tree: stderr + ``logs/encoder/encoder-YYYY-MM-DD.jsonl``.
    """
    setup_component_logging(
        logs_root=Path(logs_root),
        service="encoder",
        console_level=logging.DEBUG,
        file_level=logging.DEBUG,
        attach_to_root=False,
        logger_name="replaytrove.encoder",
        clear_existing_handlers=True,
        enable_system_heartbeat=False,
    )
    root = logging.getLogger("replaytrove.encoder")
    root.setLevel(logging.DEBUG)

    if ui_queue is not None:
        qh = TkQueueLogHandler(ui_queue)
        qh.setLevel(logging.INFO)
        qh.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(qh)

    return root


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
