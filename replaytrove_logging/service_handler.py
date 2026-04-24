"""JSONL handler: logs/YYYY-MM-DD/{service}.jsonl + timeline + index."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from replaytrove_logging import day_index
from replaytrove_logging.paths import service_jsonl, timeline_jsonl, utc_day_str
from replaytrove_logging.win_lock import global_log_write_lock


class ServiceJsonlFileHandler(logging.Handler):
    """
    Writes under ``logs_root/UTC_DATE/{service}.jsonl`` and mirrors each line to
    ``timeline.jsonl`` with cross-process locking. Updates ``index.json``.
    """

    def __init__(
        self,
        logs_root: Path,
        service: str,
        *,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.logs_root = Path(logs_root)
        self.service = service
        self.encoding = encoding

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            day = utc_day_str(datetime.fromtimestamp(record.created, tz=timezone.utc))
            rec = json.loads(line)
            ts = str(rec.get("timestamp", ""))
            level = str(rec.get("level", "INFO"))
            event = str(rec.get("event", "log"))
            svc_path = service_jsonl(self.logs_root, day, self.service)
            tl_path = timeline_jsonl(self.logs_root, day)
            idx_path = self.logs_root / day / "index.json"

            with global_log_write_lock():
                svc_path.parent.mkdir(parents=True, exist_ok=True)
                with open(svc_path, "a", encoding=self.encoding) as sf:
                    sf.write(line + "\n")
                with open(tl_path, "a", encoding=self.encoding) as tf:
                    tf.write(line + "\n")
                day_index.bump_index(
                    idx_path,
                    day=day,
                    timestamp=ts,
                    service=self.service,
                    level=level,
                    event=event,
                )
        except Exception:
            self.handleError(record)


# Backward-compatible alias
DailyJsonlFileHandler = ServiceJsonlFileHandler
