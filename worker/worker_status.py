"""
Write a machine-readable worker health snapshot for on-site troubleshooting.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Settings
    from connectivity import ConnectivityMonitor
    from job_store import JobStore

logger = logging.getLogger(__name__)

# Windows often returns transient Access denied on atomic replace when another
# reader (AV, explorer, second worker) briefly locks the destination.
_REPLACE_MAX_ATTEMPTS = 8
_REPLACE_INITIAL_DELAY_SEC = 0.02
_REPLACE_MAX_DELAY_SEC = 0.2


def _replace_with_retry(src: Path, dst: Path) -> None:
    """``Path.replace`` with short exponential backoff on permission-style errors."""
    delay = _REPLACE_INITIAL_DELAY_SEC
    last_err: OSError | None = None
    for attempt in range(_REPLACE_MAX_ATTEMPTS):
        try:
            src.replace(dst)
            return
        except OSError as exc:
            winerr = getattr(exc, "winerror", None)
            if isinstance(exc, PermissionError) or winerr == 5 or exc.errno == 13:
                last_err = exc
            else:
                raise
            if attempt + 1 >= _REPLACE_MAX_ATTEMPTS:
                break
            time.sleep(delay)
            delay = min(delay * 2.0, _REPLACE_MAX_DELAY_SEC)
    assert last_err is not None
    raise last_err


class WorkerStatusReporter:
    """Thread-safe counters and periodic JSON snapshot (default ``C:\\ReplayTrove\\status.json``)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._last_upload_monotonic: float | None = None

    def record_original_upload_success(self) -> None:
        with self._lock:
            self._last_upload_monotonic = time.time()

    def write(
        self,
        *,
        settings: Settings,
        connectivity: ConnectivityMonitor,
        job_store: JobStore,
        worker_running: bool,
    ) -> None:
        by_status = job_store.count_rows_by_status()
        stale_n = job_store.count_stale_processing(settings.stale_job_idle_seconds)
        failed_n = int(by_status.get("failed", 0))
        pending_q = job_store.count_remote_sync_pending()

        with self._lock:
            upload_ts = self._last_upload_monotonic

        last_upload_iso: str | None = None
        if upload_ts is not None:
            last_upload_iso = datetime.fromtimestamp(
                upload_ts, tz=timezone.utc
            ).isoformat()

        last_conn_iso = datetime.fromtimestamp(
            connectivity.last_state_change_at, tz=timezone.utc
        ).isoformat()

        payload = {
            "worker_running": worker_running,
            "network_state": connectivity.state,
            "pending_remote_sync_queue": pending_q,
            "failed_jobs": failed_n,
            "stale_jobs": stale_n,
            "last_successful_upload": last_upload_iso,
            "last_connectivity_change": last_conn_iso,
        }

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(payload, indent=2)
            fd, tmp = tempfile.mkstemp(
                suffix=".json",
                dir=str(self._path.parent),
                text=True,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                _replace_with_retry(Path(tmp), self._path)
            except Exception:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        except Exception:
            logger.exception(
                "Failed writing worker status JSON",
                extra={"structured": {"path": str(self._path)}},
            )
